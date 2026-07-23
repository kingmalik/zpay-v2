"""
Tests for backend/services/coverage_service.py — roster sync + call-out solver.

Real in-memory SQLite (StaticPool). backup_candidates() flows through
assignment_service.suggest_drivers(), whose pricing pool is patched empty
(pricing is not under test here — see test_assignment_service.py).

Run in isolation (documented pre-existing pattern, see test_manual_adjustments.py).

Run with:
    PYTHONPATH=. pytest backend/tests/test_coverage_service.py -x -v
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import Integer, Text, create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.db.models import (
    Base, DriverCertification, NotificationEvent, Person, Ride, RouteBackup, RouteRoster,
    TripNotification, ZRateOverride,
)
from backend.services import assignment_service, coverage_service
from backend.services.coverage_service import backup_candidates, find_coverage, sync_rosters

# Anchor a real Tuesday so weekday-based scheduling logic is deterministic.
NOW = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)  # 2026-07-21 is a Tuesday
TARGET_DATE = date(2026, 7, 28)  # next Tuesday

ZRateOverride.__table__.c.effective_during.type = Text()
Ride.__table__.c.ride_id.type = Integer()


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _register_now(dbapi_conn, _rec):
        dbapi_conn.create_function("NOW", 0, lambda: datetime.now(timezone.utc).isoformat())

    Base.metadata.create_all(
        engine,
        tables=[
            Person.__table__, Ride.__table__, RouteRoster.__table__, RouteBackup.__table__,
            TripNotification.__table__, NotificationEvent.__table__,
            # S7 — suggest_drivers() (via backup_candidates) now calls
            # certification.is_certified(), which queries this table.
            DriverCertification.__table__,
        ],
    )
    session = sessionmaker(bind=engine)()
    from backend.services import driver_reliability_tier
    driver_reliability_tier.invalidate_cache()
    yield session
    session.close()


def _person(db, name: str, **overrides) -> Person:
    fields = {"full_name": name, "active": True, "status": "active", **overrides}
    p = Person(**fields)
    db.add(p)
    db.flush()
    return p


def _ride(db, person: Person, school: str, direction: str, number: str, ts: datetime, source: str = "acumen"):
    r = Ride(
        payroll_batch_id=1,
        person_id=person.person_id,
        ride_start_ts=ts,
        service_name=f"{school} {direction} {number}",
        source=source,
        route_school=school,
        route_direction=direction,
        route_number=number,
        route_is_odt=False,
        source_ref=f"ref-{person.person_id}-{school}-{direction}-{number}-{ts.isoformat()}",
    )
    db.add(r)
    db.flush()
    return r


# ── sync_rosters ─────────────────────────────────────────────────────────────

def test_sync_creates_roster_with_modal_primary_driver(db):
    main_driver = _person(db, "Main Driver")
    fill_in = _person(db, "Fill-in Driver")

    # main_driver drove this route 8 of the last 10 times; fill_in covered twice.
    for i in range(10):
        driver = fill_in if i in (0, 1) else main_driver
        ts = NOW - timedelta(days=i * 2)
        _ride(db, driver, "Risalah ES", "IB", "05", ts)
    db.commit()

    result = sync_rosters(db)
    assert result["created"] == 1
    assert result["updated"] == 0
    assert result["deactivated"] == 0

    roster = db.query(RouteRoster).one()
    assert roster.route_school == "Risalah ES"
    assert roster.primary_person_id == main_driver.person_id
    assert roster.active is True


def test_sync_is_idempotent_on_second_run(db):
    driver = _person(db, "Driver")
    _ride(db, driver, "Alderwood MS", "OB", "09", NOW)
    db.commit()

    first = sync_rosters(db)
    second = sync_rosters(db)
    assert first["created"] == 1
    assert second["created"] == 0
    assert second["updated"] == 1
    assert db.query(RouteRoster).count() == 1


def test_sync_deactivates_stale_roster(db):
    driver = _person(db, "Driver")
    # Ride older than the 400-day staleness window won't be picked up at all —
    # simulate staleness by first creating a live roster, then re-syncing with
    # no matching rides in the window (route stopped running).
    _ride(db, driver, "Old School", "IB", "01", NOW)
    db.commit()
    sync_rosters(db)

    # Remove the only ride for this identity so the next sync sees nothing.
    db.query(Ride).delete()
    db.commit()

    result = sync_rosters(db)
    assert result["deactivated"] == 1
    roster = db.query(RouteRoster).one()
    assert roster.active is False


# ── backup_candidates ────────────────────────────────────────────────────────

def test_backup_candidates_excludes_primary_and_existing_backups(db):
    primary = _person(db, "Primary Driver")
    existing_backup = _person(db, "Existing Backup")
    candidate = _person(db, "New Candidate")

    roster = RouteRoster(
        source="acumen", route_school="Risalah ES", route_direction="IB", route_number="05",
        route_is_odt=False, primary_person_id=primary.person_id, active=True,
    )
    db.add(roster)
    db.flush()
    db.add(RouteBackup(roster_id=roster.roster_id, person_id=existing_backup.person_id, rank=1))
    db.commit()

    with patch.object(assignment_service, "load_pricing_context", return_value=[]):
        candidates = backup_candidates(db, roster.roster_id)

    ids = {c.person_id for c in candidates}
    assert primary.person_id not in ids
    assert existing_backup.person_id not in ids
    assert candidate.person_id in ids


def test_backup_candidates_unknown_roster_returns_empty(db):
    assert backup_candidates(db, 999) == []


# ── find_coverage ────────────────────────────────────────────────────────────

def _tuesday_ts(hour: int, minute: int = 0, weeks_ago: int = 1) -> datetime:
    return datetime(2026, 7, 28, hour, minute, tzinfo=timezone.utc) - timedelta(weeks=weeks_ago)


def test_find_coverage_direct_match_when_driver_is_free(db):
    primary = _person(db, "Primary Driver")
    free_driver = _person(db, "Free Driver")
    busy_driver = _person(db, "Busy Driver")

    roster = RouteRoster(
        source="acumen", route_school="Risalah ES", route_direction="IB", route_number="05",
        route_is_odt=False, primary_person_id=primary.person_id, active=True,
    )
    db.add(roster)
    db.flush()

    # Target route's typical time: 7:45 AM on Tuesdays.
    for w in range(1, 5):
        _ride(db, primary, "Risalah ES", "IB", "05", _tuesday_ts(7, 45, weeks_ago=w))
    # busy_driver has their own 7:45 AM Tuesday obligation elsewhere — conflicts.
    for w in range(1, 5):
        _ride(db, busy_driver, "Other School", "OB", "02", _tuesday_ts(7, 40, weeks_ago=w))
    # free_driver only drives afternoons — no conflict.
    for w in range(1, 5):
        _ride(db, free_driver, "Afternoon School", "OB", "03", _tuesday_ts(15, 0, weeks_ago=w))
    db.commit()

    result = find_coverage(db, roster.roster_id, TARGET_DATE)
    direct_ids = {d["person_id"] for d in result["direct"]}
    assert free_driver.person_id in direct_ids
    assert busy_driver.person_id not in direct_ids


def test_find_coverage_unknown_roster_returns_empty_with_note(db):
    result = find_coverage(db, 999, TARGET_DATE)
    assert result["direct"] == []
    assert result["chains"] == []
    assert "not found" in result["notes"][0]


def test_find_coverage_falls_back_to_chain_when_nobody_free(db):
    primary = _person(db, "Primary Driver")
    swap_driver = _person(db, "Swap Driver")   # busy at target time, but not chronic
    backfill_driver = _person(db, "Backfill Driver")

    roster = RouteRoster(
        source="acumen", route_school="Risalah ES", route_direction="IB", route_number="05",
        route_is_odt=False, primary_person_id=primary.person_id, active=True,
    )
    other_roster = RouteRoster(
        source="acumen", route_school="Other School", route_direction="OB", route_number="02",
        route_is_odt=False, primary_person_id=swap_driver.person_id, active=True,
    )
    db.add_all([roster, other_roster])
    db.flush()

    for w in range(1, 5):
        _ride(db, primary, "Risalah ES", "IB", "05", _tuesday_ts(7, 45, weeks_ago=w))
    # swap_driver drives two things: an ad-hoc morning run that conflicts with
    # the target slot (making them "busy", not simply free), AND their real
    # standing route (Other School OB 02, tracked as their own roster) at a
    # different time in the afternoon — that's the seat that needs backfilling.
    for w in range(1, 5):
        _ride(db, swap_driver, "Ad Hoc School", "IB", "07", _tuesday_ts(7, 40, weeks_ago=w))
        _ride(db, swap_driver, "Other School", "OB", "02", _tuesday_ts(15, 0, weeks_ago=w))
    # backfill_driver is also busy in the morning (so they're not simply
    # "direct" free for the target) but has nothing scheduled in the
    # afternoon — free to backfill swap_driver's Other School run.
    for w in range(1, 5):
        _ride(db, backfill_driver, "Third School", "IB", "12", _tuesday_ts(7, 42, weeks_ago=w))
    db.commit()

    result = find_coverage(db, roster.roster_id, TARGET_DATE)
    assert result["direct"] == []
    assert len(result["chains"]) == 1
    chain = result["chains"][0]
    actioned_ids = {m["person_id"] for m in chain["moves"]}
    assert swap_driver.person_id in actioned_ids
    assert backfill_driver.person_id in actioned_ids
    assert "moves to cover" in chain["description"]
