"""
Tests for backend/services/rate_shadow.py — S3 shadow mode.

Run with:
    PYTHONPATH=. pytest backend/tests/test_rate_shadow.py -x -v

Real in-memory SQLite for the tables the shadow run touches; the v2 pool is
patched with synthetic profiles so verdicts are deterministic.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.db.models import Base, PayrollBatch, Person, RateShadowResult, Ride
from backend.services import rate_shadow
from backend.services.rate_engine_v2 import ServiceProfile
from backend.services.route_identity import parse_route_identity


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _register_now(dbapi_conn, _rec):
        dbapi_conn.create_function(
            "NOW", 0, lambda: datetime.now(timezone.utc).isoformat()
        )

    Base.metadata.create_all(
        engine,
        tables=[
            Person.__table__, PayrollBatch.__table__,
            Ride.__table__, RateShadowResult.__table__,
        ],
    )
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _seed(db, service_name: str, z_rate: str, miles: float = 12.0):
    person = db.query(Person).first()
    if person is None:
        person = Person(full_name="Driver", active=True)
        db.add(person)
        db.flush()
    batch = db.query(PayrollBatch).first()
    if batch is None:
        batch = PayrollBatch(source="acumen", company_name="FirstAlt")
        db.add(batch)
        db.flush()
    # SQLite doesn't autoincrement BIGINT PKs — assign explicitly.
    next_ride_id = (db.query(Ride).count()) + 1
    ride = Ride(
        ride_id=next_ride_id,
        payroll_batch_id=batch.payroll_batch_id,
        person_id=person.person_id,
        source="acumen",
        source_ref=f"t:{service_name}:{db.query(Ride).count()}",
        service_name=service_name,
        z_rate=Decimal(z_rate),
        z_rate_source="service_default",
        miles=Decimal(str(miles)),
        gross_pay=Decimal(z_rate),
        net_pay=Decimal(z_rate),
        deduction=0,
        spiff=0,
    )
    db.add(ride)
    db.commit()
    return batch.payroll_batch_id


def _pool(*entries):
    out = []
    for name, rate, miles in entries:
        ident = parse_route_identity(name)
        out.append(ServiceProfile(
            service_name=name, identity=ident, rate=Decimal(rate),
            z_rate_service_id=1, ride_count=50, median_miles=miles,
        ))
    return out


def test_off_mode_returns_none(db, monkeypatch):
    monkeypatch.setenv("RATE_ENGINE_V2", "0")
    assert rate_shadow.run_shadow_for_batch(db, 1) is None


def test_agreement_recorded(db, monkeypatch):
    monkeypatch.setenv("RATE_ENGINE_V2", "shadow")
    batch_id = _seed(db, "Risalah ES IB 05_A", "45.00")
    pool = _pool(("Risalah ES IB 05", "45.00", 12.0))
    with patch.object(rate_shadow, "load_pricing_context", return_value=pool):
        summary = rate_shadow.run_shadow_for_batch(db, batch_id)

    assert summary["rides"] == 1
    assert summary["v2_resolved"] == 1
    assert summary["disagree"] == 0
    row = db.query(RateShadowResult).one()
    assert row.agrees is True
    assert row.v2_tier == "tier1_identity"


def test_disagreement_recorded_and_alerted(db, monkeypatch):
    monkeypatch.setenv("RATE_ENGINE_V2", "shadow")
    batch_id = _seed(db, "Risalah ES IB 05_A", "40.00")   # v1 said 40
    pool = _pool(("Risalah ES IB 05", "45.00", 12.0))     # v2 says 45
    with patch.object(rate_shadow, "load_pricing_context", return_value=pool), \
         patch("backend.services.notification_service.alert_admin") as mock_alert:
        summary = rate_shadow.run_shadow_for_batch(db, batch_id)

    assert summary["disagree"] == 1
    assert summary["disagreements"][0]["v2_rate"] == "45.00"
    mock_alert.assert_called_once()
    assert "RATE SHADOW" in mock_alert.call_args[0][0]
    row = db.query(RateShadowResult).one()
    assert row.agrees is False


def test_refusal_counts_as_agreement(db, monkeypatch):
    monkeypatch.setenv("RATE_ENGINE_V2", "shadow")
    batch_id = _seed(db, "Brand New SCH IB 01", "38.00")
    with patch.object(rate_shadow, "load_pricing_context", return_value=[]), \
         patch("backend.services.notification_service.alert_admin") as mock_alert:
        summary = rate_shadow.run_shadow_for_batch(db, batch_id)

    assert summary["v2_refused"] == 1
    assert summary["disagree"] == 0
    mock_alert.assert_not_called()
    row = db.query(RateShadowResult).one()
    assert row.agrees is True
    assert row.v2_tier == "none"


def test_shadow_failure_never_raises(db, monkeypatch):
    monkeypatch.setenv("RATE_ENGINE_V2", "shadow")
    batch_id = _seed(db, "Risalah ES IB 05", "45.00")
    with patch.object(rate_shadow, "load_pricing_context", side_effect=RuntimeError("boom")):
        assert rate_shadow.run_shadow_for_batch(db, batch_id) is None
