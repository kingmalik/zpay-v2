"""
Tests for backend/services/school_service.py — school address book +
IB/OB address back-fill sidedness.

Real in-memory SQLite (StaticPool), inline fixture — no conftest.py, per
the repo's per-file isolation pattern (see test_assignment_service.py).

Run with:
    PYTHONPATH=. pytest backend/tests/test_school_service.py -x -v
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.db.models import Base, School, SeasonRide
from backend.services import school_service


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _register_now(dbapi_conn, _rec):
        dbapi_conn.create_function("NOW", 0, lambda: datetime.now(timezone.utc).isoformat())

    Base.metadata.create_all(engine, tables=[School.__table__, SeasonRide.__table__])
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _season_ride(db, school: School, direction: str, **overrides) -> SeasonRide:
    fields = {
        "season": "2026-27",
        "source": "firstalt",
        "route_school": school.display_name,
        "route_direction": direction,
        "route_number": "01",
        "route_is_odt": False,
        "school_id": school.school_id,
        **overrides,
    }
    ride = SeasonRide(**fields)
    db.add(ride)
    db.flush()
    return ride


# ── get_or_create_school ─────────────────────────────────────────────────────

def test_get_or_create_school_creates_new_school(db):
    school = school_service.get_or_create_school(db, "Risalah ES")
    assert school.school_id is not None
    assert school.display_name == "Risalah ES"
    assert school.name == "risalah es"


def test_get_or_create_school_normalizes_dedupe_key(db):
    first = school_service.get_or_create_school(db, "Risalah ES")
    db.commit()
    second = school_service.get_or_create_school(db, "  risalah   es  ")
    assert second.school_id == first.school_id


def test_get_or_create_school_dedupes_across_casing_variants(db):
    first = school_service.get_or_create_school(db, "Cedar Heights MS")
    db.commit()
    second = school_service.get_or_create_school(db, "CEDAR HEIGHTS MS")
    assert second.school_id == first.school_id
    # Original display casing is preserved, not overwritten by the new call.
    assert second.display_name == "Cedar Heights MS"


def test_get_or_create_school_raises_on_blank_name(db):
    with pytest.raises(ValueError):
        school_service.get_or_create_school(db, "")
    with pytest.raises(ValueError):
        school_service.get_or_create_school(db, "   ")


# ── apply_school_address sidedness ───────────────────────────────────────────

def test_apply_school_address_ib_ride_fills_dropoff_side(db):
    school = school_service.get_or_create_school(db, "Kent Meridian HS")
    db.commit()
    ride = _season_ride(db, school, "IB")
    db.commit()

    school_service.apply_school_address(
        db, school.school_id, address="10020 SE 256th St, Kent, WA", city="Kent",
    )
    db.commit()
    db.refresh(ride)

    assert ride.dropoff_address == "10020 SE 256th St, Kent, WA"
    assert ride.dropoff_city == "Kent"
    assert ride.pickup_address is None
    assert ride.pickup_city is None


def test_apply_school_address_ob_ride_fills_pickup_side(db):
    school = school_service.get_or_create_school(db, "Kent Meridian HS")
    db.commit()
    ride = _season_ride(db, school, "OB")
    db.commit()

    school_service.apply_school_address(
        db, school.school_id, address="10020 SE 256th St, Kent, WA", city="Kent",
    )
    db.commit()
    db.refresh(ride)

    assert ride.pickup_address == "10020 SE 256th St, Kent, WA"
    assert ride.pickup_city == "Kent"
    assert ride.dropoff_address is None
    assert ride.dropoff_city is None


def test_apply_school_address_only_backfills_null_fields(db):
    school = school_service.get_or_create_school(db, "Cedar Heights MS")
    db.commit()
    ride = _season_ride(
        db, school, "IB",
        dropoff_address="Already set by mom", dropoff_city="Somewhere Else",
    )
    db.commit()

    school_service.apply_school_address(
        db, school.school_id, address="New address", city="New City",
    )
    db.commit()
    db.refresh(ride)

    assert ride.dropoff_address == "Already set by mom"
    assert ride.dropoff_city == "Somewhere Else"


def test_apply_school_address_sets_district_and_school_fields(db):
    school = school_service.get_or_create_school(db, "Risalah ES")
    db.commit()

    updated = school_service.apply_school_address(
        db, school.school_id, address="123 Main St", city="Bellevue", district="Bellevue SD",
    )
    db.commit()

    assert updated.address == "123 Main St"
    assert updated.city == "Bellevue"
    assert updated.district == "Bellevue SD"


def test_apply_school_address_raises_on_unknown_school(db):
    with pytest.raises(ValueError):
        school_service.apply_school_address(db, 999, address="nowhere")


def test_apply_school_address_updates_multiple_rides_at_same_school(db):
    school = school_service.get_or_create_school(db, "Cedar Heights MS")
    db.commit()
    ride_a = _season_ride(db, school, "IB", route_number="01")
    ride_b = _season_ride(db, school, "IB", route_number="02")
    db.commit()

    school_service.apply_school_address(db, school.school_id, address="1 School Way", city="Kent")
    db.commit()
    db.refresh(ride_a)
    db.refresh(ride_b)

    assert ride_a.dropoff_address == "1 School Way"
    assert ride_b.dropoff_address == "1 School Way"


# ── schools_overview ─────────────────────────────────────────────────────────

def test_schools_overview_reports_ride_count_and_needs_address(db):
    with_address = school_service.get_or_create_school(db, "Cedar Heights MS")
    with_address.address = "1 School Way"
    needs_address = school_service.get_or_create_school(db, "Risalah ES")
    db.commit()

    _season_ride(db, with_address, "IB", route_number="01")
    _season_ride(db, with_address, "OB", route_number="01")
    _season_ride(db, needs_address, "IB", route_number="01")
    db.commit()

    overview = school_service.schools_overview(db)
    by_name = {row["display_name"]: row for row in overview}

    assert by_name["Cedar Heights MS"]["ride_count"] == 2
    assert by_name["Cedar Heights MS"]["needs_address"] is False
    assert by_name["Risalah ES"]["ride_count"] == 1
    assert by_name["Risalah ES"]["needs_address"] is True


def test_schools_overview_surfaces_needs_address_rows_first(db):
    has_address = school_service.get_or_create_school(db, "AAA School")
    has_address.address = "somewhere"
    missing_address = school_service.get_or_create_school(db, "ZZZ School")
    db.commit()

    overview = school_service.schools_overview(db)
    names_in_order = [row["display_name"] for row in overview]

    assert names_in_order.index("ZZZ School") < names_in_order.index("AAA School")


def test_schools_overview_zero_rides_for_school_with_no_season_rides(db):
    school_service.get_or_create_school(db, "Brand New School")
    db.commit()

    overview = school_service.schools_overview(db)
    assert overview[0]["ride_count"] == 0
