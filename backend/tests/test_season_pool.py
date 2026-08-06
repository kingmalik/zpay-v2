"""
Tests for backend/services/season_pool.py — intake -> season_ride mapping,
requirement keyword flags, dedupe upsert, and sheet import.

Real in-memory SQLite (StaticPool), inline fixture — no conftest.py, per
the repo's per-file isolation pattern (see test_assignment_service.py).

Run with:
    PYTHONPATH=. pytest backend/tests/test_season_pool.py -x -v
"""
from __future__ import annotations

import io
import os
import sys
from datetime import datetime, timezone

import pandas as pd
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.db.models import Base, RideIntake, School, SeasonRide
from backend.services import season_pool
from backend.services.season_pool import ImportReport, parse_requirement_flags


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _register_now(dbapi_conn, _rec):
        dbapi_conn.create_function("NOW", 0, lambda: datetime.now(timezone.utc).isoformat())

    Base.metadata.create_all(
        engine, tables=[School.__table__, SeasonRide.__table__, RideIntake.__table__],
    )
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _intake(db, parsed: dict, status: str = "taken") -> RideIntake:
    row = RideIntake(raw_text="raw", parsed=parsed, status=status)
    db.add(row)
    db.flush()
    return row


BASE_PARSED = {
    "school": "Risalah ES",
    "direction": "IB",
    "number": "05",
    "is_odt": False,
    "wheelchair": False,
    "miles": 8.5,
    "net_pay": 45.0,
    "days": ["M", "T", "W", "Th", "F"],
    "start_time": "7:45 AM",
    "notes": None,
    "district": "Lake Washington",
    "is_recurring": True,
    "net_pay_ib": None,
    "net_pay_ob": None,
    "start_date": None,
    "origin": "Kirkland",
    "destination": "Redmond",
    "requirements": None,
}


# ── parse_requirement_flags ──────────────────────────────────────────────────

def test_parse_requirement_flags_car_seat():
    flags = parse_requirement_flags("requires a car seat")
    assert flags["car_seat"] is True
    assert flags["booster"] is False


def test_parse_requirement_flags_booster():
    flags = parse_requirement_flags("two booster seats")
    assert flags["booster"] is True


def test_parse_requirement_flags_harness_variants():
    assert parse_requirement_flags("needs harness")["harness"] is True
    assert parse_requirement_flags("safety vest required")["harness"] is True
    assert parse_requirement_flags("safety belt")["harness"] is True


def test_parse_requirement_flags_monitor_variants():
    assert parse_requirement_flags("monitor required")["monitor"] is True
    assert parse_requirement_flags("needs an attendant")["monitor"] is True
    assert parse_requirement_flags("aide on board")["monitor"] is True


def test_parse_requirement_flags_wheelchair_variants():
    assert parse_requirement_flags("wheelchair accessible")["wheelchair"] is True
    assert parse_requirement_flags("HCV vehicle")["wheelchair"] is True
    assert parse_requirement_flags("w/c required")["wheelchair"] is True


def test_parse_requirement_flags_from_list():
    flags = parse_requirement_flags(["booster seat", "harness"])
    assert flags["booster"] is True
    assert flags["harness"] is True
    assert flags["monitor"] is False


def test_parse_requirement_flags_none_input_all_false():
    flags = parse_requirement_flags(None)
    assert all(v is False for v in flags.values())


def test_parse_requirement_flags_extra_wheelchair_ors_in():
    flags = parse_requirement_flags(None, extra_wheelchair=True)
    assert flags["wheelchair"] is True


# ── upsert_from_intake — mapping ─────────────────────────────────────────────

def test_upsert_from_intake_maps_core_fields(db):
    intake = _intake(db, BASE_PARSED)
    db.commit()

    rows = season_pool.upsert_from_intake(db, intake)
    db.commit()

    assert len(rows) == 1
    row = rows[0]
    assert row.route_school == "risalah es"  # canonicalized: casing never forks identity
    assert row.route_direction == "IB"
    assert row.route_number == "05"
    assert row.route_is_odt is False
    assert float(row.miles) == 8.5
    assert float(row.net_pay) == 45.0
    assert row.days == "M,T,W,Th,F"
    assert row.pickup_time == "7:45 AM"
    assert row.status == "unassigned"


def test_upsert_from_intake_creates_school_and_links_it(db):
    intake = _intake(db, BASE_PARSED)
    db.commit()

    rows = season_pool.upsert_from_intake(db, intake)
    db.commit()

    school = db.query(School).filter(School.school_id == rows[0].school_id).first()
    assert school is not None
    assert school.display_name == "Risalah ES"
    assert school.district == "Lake Washington"


def test_upsert_from_intake_ib_pickup_dropoff_from_origin_destination(db):
    intake = _intake(db, {**BASE_PARSED, "origin": "Kirkland, WA", "destination": "Redmond, WA"})
    db.commit()

    rows = season_pool.upsert_from_intake(db, intake)
    assert rows[0].pickup_city == "Kirkland"
    assert rows[0].dropoff_city == "Redmond"


def test_upsert_from_intake_ob_reverses_pickup_dropoff(db):
    intake = _intake(db, {
        **BASE_PARSED, "direction": "OB", "origin": "Kirkland, WA", "destination": "Redmond, WA",
    })
    db.commit()

    rows = season_pool.upsert_from_intake(db, intake)
    # OB runs the corridor home-ward: pickup at school side (destination),
    # dropoff at home side (origin).
    assert rows[0].pickup_city == "Redmond"
    assert rows[0].dropoff_city == "Kirkland"


def test_upsert_from_intake_wheelchair_flag_sets_requires(db):
    intake = _intake(db, {**BASE_PARSED, "wheelchair": True})
    db.commit()

    rows = season_pool.upsert_from_intake(db, intake)
    assert rows[0].requires["wheelchair"] is True


def test_upsert_from_intake_requirements_text_sets_flags(db):
    intake = _intake(db, {**BASE_PARSED, "requirements": ["booster seat", "monitor required"]})
    db.commit()

    rows = season_pool.upsert_from_intake(db, intake)
    assert rows[0].requires["booster"] is True
    assert rows[0].requires["monitor"] is True
    assert rows[0].requires["car_seat"] is False


def test_upsert_from_intake_raises_when_school_missing(db):
    intake = _intake(db, {**BASE_PARSED, "school": None})
    db.commit()
    with pytest.raises(ValueError):
        season_pool.upsert_from_intake(db, intake)


def test_upsert_from_intake_raises_when_number_missing(db):
    intake = _intake(db, {**BASE_PARSED, "number": None})
    db.commit()
    with pytest.raises(ValueError):
        season_pool.upsert_from_intake(db, intake)


def test_upsert_from_intake_raises_when_direction_unresolvable(db):
    intake = _intake(db, {**BASE_PARSED, "direction": None, "origin": None, "destination": None})
    db.commit()
    with pytest.raises(ValueError):
        season_pool.upsert_from_intake(db, intake)


# ── upsert_from_intake — IB/OB round trip splitting ──────────────────────────

def test_upsert_from_intake_both_directional_pays_creates_two_rows(db):
    intake = _intake(db, {
        **BASE_PARSED, "direction": None, "net_pay_ib": 54.75, "net_pay_ob": 49.75,
    })
    db.commit()

    rows = season_pool.upsert_from_intake(db, intake)
    directions = {r.route_direction for r in rows}
    assert directions == {"IB", "OB"}

    ib_row = next(r for r in rows if r.route_direction == "IB")
    ob_row = next(r for r in rows if r.route_direction == "OB")
    assert float(ib_row.net_pay) == 54.75
    assert float(ob_row.net_pay) == 49.75


def test_upsert_from_intake_direction_missing_but_corridor_named_creates_two_rows(db):
    intake = _intake(db, {**BASE_PARSED, "direction": None})
    db.commit()

    rows = season_pool.upsert_from_intake(db, intake)
    assert {r.route_direction for r in rows} == {"IB", "OB"}


def test_upsert_from_intake_single_direction_creates_one_row(db):
    intake = _intake(db, BASE_PARSED)
    db.commit()

    rows = season_pool.upsert_from_intake(db, intake)
    assert len(rows) == 1
    assert rows[0].route_direction == "IB"


# ── upsert_from_intake — dedupe ──────────────────────────────────────────────

def test_upsert_from_intake_twice_updates_instead_of_duplicating(db):
    intake = _intake(db, BASE_PARSED)
    db.commit()

    first = season_pool.upsert_from_intake(db, intake)
    db.commit()
    updated_parsed = {**BASE_PARSED, "net_pay": 60.0}
    intake.parsed = updated_parsed
    db.commit()

    second = season_pool.upsert_from_intake(db, intake)
    db.commit()

    assert first[0].season_ride_id == second[0].season_ride_id
    assert db.query(SeasonRide).count() == 1
    assert float(second[0].net_pay) == 60.0


def test_upsert_from_intake_different_intakes_same_identity_dedupe(db):
    intake_a = _intake(db, BASE_PARSED)
    db.commit()
    season_pool.upsert_from_intake(db, intake_a)
    db.commit()

    intake_b = _intake(db, BASE_PARSED)
    db.commit()
    season_pool.upsert_from_intake(db, intake_b)
    db.commit()

    assert db.query(SeasonRide).count() == 1


def test_upsert_from_intake_different_school_creates_separate_row(db):
    intake_a = _intake(db, BASE_PARSED)
    intake_b = _intake(db, {**BASE_PARSED, "school": "Cedar Heights MS"})
    db.commit()

    season_pool.upsert_from_intake(db, intake_a)
    season_pool.upsert_from_intake(db, intake_b)
    db.commit()

    assert db.query(SeasonRide).count() == 2


# ── backfill_from_intakes ────────────────────────────────────────────────────

def test_backfill_from_intakes_pools_only_taken_intakes(db):
    _intake(db, BASE_PARSED, status="taken")
    _intake(db, {**BASE_PARSED, "school": "Cedar Heights MS"}, status="draft")
    _intake(db, {**BASE_PARSED, "school": "Alderwood MS"}, status="passed")
    db.commit()

    result = season_pool.backfill_from_intakes(db)
    db.commit()

    assert result["processed"] == 1
    assert result["rows"] == 1
    assert db.query(SeasonRide).count() == 1


def test_backfill_from_intakes_collects_errors_without_aborting(db):
    _intake(db, BASE_PARSED, status="taken")
    _intake(db, {**BASE_PARSED, "school": None}, status="taken")
    db.commit()

    result = season_pool.backfill_from_intakes(db)
    db.commit()

    assert result["processed"] == 2
    assert result["rows"] == 1
    assert len(result["errors"]) == 1
    assert db.query(SeasonRide).count() == 1


# ── import_sheet ──────────────────────────────────────────────────────────────

def _xlsx_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


def test_import_sheet_happy_path_creates_rows(db):
    df = pd.DataFrame([
        {
            "School": "Risalah ES", "Direction": "IB", "Route Number": "05",
            "Days": "M,T,W,Th,F", "Pickup Address": "Kirkland, WA",
            "Dropoff Address": "Redmond, WA", "Pickup Time": "7:45",
            "Dropoff Time": "8:15", "Miles": 8.5, "Net Pay": 45.0,
            "Requirements": "booster seat", "District": "Lake Washington",
        },
        {
            "School": "Cedar Heights MS", "Direction": "OB", "Route Number": "02",
            "Days": "M,T,W,Th,F", "Pickup Address": "", "Dropoff Address": "",
            "Pickup Time": "", "Dropoff Time": "", "Miles": None, "Net Pay": 38.0,
            "Requirements": "", "District": "Kent SD",
        },
    ])
    report = season_pool.import_sheet(db, _xlsx_bytes(df), "routes.xlsx")
    db.commit()

    assert report.total_rows == 2
    assert report.created == 2
    assert report.errors == []
    assert db.query(SeasonRide).count() == 2

    risalah = db.query(SeasonRide).filter(SeasonRide.route_school == "risalah es").first()
    assert risalah.pickup_city == "Kirkland"
    assert risalah.dropoff_city == "Redmond"
    assert risalah.requires["booster"] is True


def test_import_sheet_junk_rows_collected_as_errors_not_aborted(db):
    df = pd.DataFrame([
        {"School": "Risalah ES", "Direction": "IB", "Route Number": "05", "Net Pay": 45.0},
        {"School": "", "Direction": "IB", "Route Number": "06", "Net Pay": 40.0},
        {"School": "Cedar Heights MS", "Direction": "SIDEWAYS", "Route Number": "07", "Net Pay": 40.0},
        {"School": "Alderwood MS", "Direction": "OB", "Route Number": "08", "Net Pay": 40.0},
    ])
    report = season_pool.import_sheet(db, _xlsx_bytes(df), "routes.xlsx")
    db.commit()

    assert report.total_rows == 4
    assert report.created == 2
    assert len(report.errors) == 2
    assert db.query(SeasonRide).count() == 2


def test_import_sheet_missing_required_columns_reports_error_no_rows(db):
    df = pd.DataFrame([{"Notes": "nothing useful here"}])
    report = season_pool.import_sheet(db, _xlsx_bytes(df), "routes.xlsx")

    assert report.created == 0
    assert len(report.errors) == 1
    assert db.query(SeasonRide).count() == 0


def test_import_sheet_dedupes_on_reimport_update_not_duplicate(db):
    df = pd.DataFrame([
        {"School": "Risalah ES", "Direction": "IB", "Route Number": "05", "Net Pay": 45.0},
    ])
    season_pool.import_sheet(db, _xlsx_bytes(df), "routes.xlsx")
    db.commit()

    df2 = pd.DataFrame([
        {"School": "Risalah ES", "Direction": "IB", "Route Number": "05", "Net Pay": 60.0},
    ])
    report2 = season_pool.import_sheet(db, _xlsx_bytes(df2), "routes.xlsx")
    db.commit()

    assert report2.created == 0
    assert report2.updated == 1
    assert db.query(SeasonRide).count() == 1
    row = db.query(SeasonRide).first()
    assert float(row.net_pay) == 60.0


def test_import_sheet_csv_happy_path(db):
    csv_bytes = (
        b"School,Direction,Route Number,Net Pay\n"
        b"Risalah ES,IB,05,45.0\n"
    )
    report = season_pool.import_sheet(db, csv_bytes, "routes.csv")
    db.commit()

    assert report.created == 1
    assert db.query(SeasonRide).count() == 1


def test_import_sheet_unreadable_file_reports_error(db):
    report = season_pool.import_sheet(db, b"not a real spreadsheet", "routes.xlsx")
    assert report.created == 0
    assert len(report.errors) == 1


# ── review-round regression tests (S10 ship gate) ────────────────────────────

def test_upsert_school_casing_never_forks_identity(db):
    intake_a = _intake(db, {**BASE_PARSED, "school": "Risalah ES"})
    intake_b = _intake(db, {**BASE_PARSED, "school": "RISALAH  es"})
    season_pool.upsert_from_intake(db, intake_a)
    season_pool.upsert_from_intake(db, intake_b)
    rows = db.query(SeasonRide).all()
    assert len(rows) == 1
    assert rows[0].route_school == "risalah es"


def test_upsert_skips_explicit_one_off_trips(db):
    intake = _intake(db, {**BASE_PARSED, "is_recurring": False})
    rows = season_pool.upsert_from_intake(db, intake)
    assert rows == []
    assert db.query(SeasonRide).count() == 0


def test_upsert_pools_when_recurrence_unknown(db):
    intake = _intake(db, {**BASE_PARSED, "is_recurring": None})
    rows = season_pool.upsert_from_intake(db, intake)
    assert len(rows) == 1


def test_backfill_skips_prior_school_year_intakes(db):
    old = _intake(db, dict(BASE_PARSED))
    old.decided_at = datetime(2026, 3, 1, tzinfo=timezone.utc)  # last school year
    new = _intake(db, {**BASE_PARSED, "school": "Juanita HS"})
    new.decided_at = datetime(2026, 8, 1, tzinfo=timezone.utc)
    db.flush()
    result = season_pool.backfill_from_intakes(db, season="2026-27")
    assert result["processed"] == 1
    schools = {r.route_school for r in db.query(SeasonRide).all()}
    assert schools == {"juanita hs"}


def test_sheet_reimport_merges_requires_never_clears_manual_flag(db):
    sheet = pd.DataFrame([{
        "School": "Risalah ES", "Direction": "IB", "Route Number": "05",
        "Requirements": "car seat",
    }])
    buf = io.BytesIO()
    sheet.to_excel(buf, index=False)
    season_pool.import_sheet(db, buf.getvalue(), "season.xlsx")

    ride = db.query(SeasonRide).one()
    # Mom manually flags a monitor on the ride card.
    ride.requires = {**ride.requires, "monitor": True}
    db.flush()

    # Re-import of the same sheet (which never mentions a monitor) must
    # keep her flag while still applying its own.
    buf2 = io.BytesIO()
    sheet.to_excel(buf2, index=False)
    report = season_pool.import_sheet(db, buf2.getvalue(), "season.xlsx")
    assert report.updated == 1

    ride = db.query(SeasonRide).one()
    assert ride.requires["monitor"] is True
    assert ride.requires["car_seat"] is True
