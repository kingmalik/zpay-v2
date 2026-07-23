"""
Tests for backend/services/assignment_service.py — driver ranking + pricing.

Real in-memory SQLite (StaticPool) for driver/ride/tier queries. The Tier-2
pricing pool (backend.services.rate_engine_v2.load_pricing_context) uses
Postgres-only percentile_cont() so — mirroring test_rate_shadow.py's
established pattern — it's patched with synthetic ServiceProfile pools
rather than exercised against SQLite.

Run in isolation — this file mutates shared ORM metadata column types the
same way other test files in this repo do (documented pre-existing pattern,
see test_manual_adjustments.py).

Run with:
    PYTHONPATH=. pytest backend/tests/test_assignment_service.py -x -v
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import Integer, Text, create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.db.models import (
    Base, DriverCertification, NotificationEvent, Person, Ride, TripNotification, ZRateOverride,
)
from backend.services import assignment_service
from backend.services.assignment_service import _score_candidate, predict_pricing, suggest_drivers
from backend.services.rate_engine_v2 import ServiceProfile
from backend.services.route_identity import parse_route_identity

NOW = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)

# SQLite-only type patches (module-scoped, isolated by running this file alone).
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
            Person.__table__, Ride.__table__, TripNotification.__table__, NotificationEvent.__table__,
            # S7 — suggest_drivers() now calls certification.is_certified(), which
            # queries this table.
            DriverCertification.__table__,
        ],
    )
    session = sessionmaker(bind=engine)()
    from backend.services import driver_reliability_tier
    driver_reliability_tier.invalidate_cache()
    yield session
    session.close()


def _pool(*entries) -> list[ServiceProfile]:
    out = []
    for name, rate, miles in entries:
        ident = parse_route_identity(name)
        out.append(ServiceProfile(
            service_name=name, identity=ident, rate=Decimal(rate),
            z_rate_service_id=1, ride_count=50, median_miles=miles,
        ))
    return out


def _person(db, name: str, **overrides) -> Person:
    fields = {"full_name": name, "active": True, "status": "active", **overrides}
    p = Person(**fields)
    db.add(p)
    db.flush()
    return p


def _ride(db, person: Person, school: str, direction: str = "IB", days_ago: int = 10, source: str = "acumen"):
    r = Ride(
        payroll_batch_id=1,
        person_id=person.person_id,
        ride_start_ts=NOW - timedelta(days=days_ago),
        service_name=f"{school} {direction} 01",
        source=source,
        route_school=school,
        route_direction=direction,
        route_number="01",
        route_is_odt=False,
        source_ref=f"ref-{person.person_id}-{school}-{direction}-{days_ago}",
    )
    db.add(r)
    db.flush()
    return r


def _trusted_history(db, person: Person, trips: int = 12):
    """Seed enough clean trip_notification rows to earn the 'trusted' tier."""
    for i in range(trips):
        db.add(TripNotification(
            person_id=person.person_id,
            trip_date=(NOW - timedelta(days=i)).date(),
            source="firstalt",
            trip_ref=f"trip-{person.person_id}-{i}",
        ))
    db.commit()


# ── pure scoring ─────────────────────────────────────────────────────────────

def test_score_rewards_familiarity_and_trusted_tier_and_light_load():
    score_experienced, reasons_a = _score_candidate(8, "trusted", 1, "Bellevue")
    score_new, reasons_b = _score_candidate(0, "watch", 1, None)
    assert score_experienced > score_new
    assert any("8 ride" in r for r in reasons_a)
    assert any("trusted" in r for r in reasons_a)


def test_score_penalizes_chronic_and_heavy_load():
    score_chronic, _ = _score_candidate(5, "chronic", 20, None)
    score_watch, reasons = _score_candidate(5, "watch", 20, None)
    assert score_chronic < score_watch
    assert any("busy" in r for r in reasons)


def test_score_caps_familiarity_beyond_threshold():
    score_10, _ = _score_candidate(10, "watch", 0, None)
    score_50, _ = _score_candidate(50, "watch", 0, None)
    assert score_10 == score_50


def test_score_home_area_is_tie_break_only():
    with_home, _ = _score_candidate(0, "watch", 0, "Renton")
    without_home, _ = _score_candidate(0, "watch", 0, None)
    assert with_home > without_home


# ── suggest_drivers ranking (pricing pool patched empty — not under test) ───

def test_suggest_drivers_ranks_familiar_trusted_driver_first(db):
    familiar = _person(db, "Familiar Trusted", home_area="Bellevue")
    _trusted_history(db, familiar)
    for i in range(8):
        _ride(db, familiar, "Risalah ES", days_ago=30 + i)

    unfamiliar = _person(db, "New Driver")
    db.commit()

    with patch.object(assignment_service, "load_pricing_context", return_value=[]):
        suggestions, _pricing = suggest_drivers(
            db, school="Risalah ES", direction="IB", miles=10.0, net_pay=45.0,
        )

    assert suggestions[0].person_id == familiar.person_id
    assert suggestions[0].familiar_rides == 8
    assert any(s.person_id == unfamiliar.person_id for s in suggestions)


def test_suggest_drivers_excludes_person_ids(db):
    a = _person(db, "Driver A")
    b = _person(db, "Driver B")
    db.commit()

    with patch.object(assignment_service, "load_pricing_context", return_value=[]):
        suggestions, _pricing = suggest_drivers(
            db, school="Some School", direction="OB",
            exclude_person_ids=frozenset({a.person_id}),
        )
    ids = {s.person_id for s in suggestions}
    assert a.person_id not in ids
    assert b.person_id in ids


def test_suggest_drivers_filters_inactive_and_dormant(db):
    active = _person(db, "Active Driver")
    inactive = _person(db, "Inactive Driver", active=False)
    dormant = _person(db, "Dormant Driver", status="dormant")
    db.commit()

    with patch.object(assignment_service, "load_pricing_context", return_value=[]):
        suggestions, _pricing = suggest_drivers(db, school="Any School", direction="IB")
    ids = {s.person_id for s in suggestions}
    assert active.person_id in ids
    assert inactive.person_id not in ids
    assert dormant.person_id not in ids


def test_suggest_drivers_with_no_school_returns_empty(db):
    _person(db, "Someone")
    db.commit()
    suggestions, pricing = suggest_drivers(db, school=None, direction=None)
    assert suggestions == []
    assert pricing.predicted_rate is None


# ── pricing ──────────────────────────────────────────────────────────────────

def test_wheelchair_ride_never_gets_predicted_rate(db):
    pricing = predict_pricing(
        db, school="Cedar Heights MS", direction="OB", miles=9.0, net_pay=62.0,
        wheelchair=True,
    )
    assert pricing.predicted_rate is None
    assert pricing.pass_through_suggestion == 62.0
    assert pricing.manual_review is True


def test_pricing_tier2_distance_inherits_established_rate(db):
    pool = _pool(("Risalah ES IB 05", "45.00", 10.0))
    with patch.object(assignment_service, "load_pricing_context", return_value=pool):
        pricing = predict_pricing(
            db, school="Risalah ES", direction="IB", miles=10.2, net_pay=60.0, source="acumen",
        )
    assert pricing.predicted_rate == 45.0
    assert pricing.margin == 15.0
    assert pricing.unprofitable is False


def test_pricing_unresolved_when_no_established_route(db):
    with patch.object(assignment_service, "load_pricing_context", return_value=[]):
        pricing = predict_pricing(
            db, school="Brand New School", direction="IB", miles=12.0, net_pay=40.0, source="acumen",
        )
    assert pricing.predicted_rate is None
    assert pricing.unprofitable is False


def test_pricing_flags_unprofitable_when_margin_below_floor(db):
    # Default ASSIGN_MARGIN_WARN_FLOOR is $8 — a $4 margin should trip it.
    pool = _pool(("Alderwood MS OB 09", "50.00", 14.0))
    with patch.object(assignment_service, "load_pricing_context", return_value=pool):
        pricing = predict_pricing(
            db, school="Alderwood MS", direction="OB", miles=14.0, net_pay=54.0, source="acumen",
        )
    assert pricing.predicted_rate == 50.0
    assert pricing.margin == 4.0
    assert pricing.unprofitable is True


def test_pricing_skipped_when_school_or_direction_missing(db):
    pricing = predict_pricing(db, school=None, direction=None, miles=10.0, net_pay=40.0)
    assert pricing.predicted_rate is None
    assert pricing.manual_review is False
