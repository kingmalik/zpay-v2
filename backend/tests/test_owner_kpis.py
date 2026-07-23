"""
Tests for backend/routes/owner_kpis.py (S8).

Same in-memory SQLite harness as test_assignment_routes.py.
Run in isolation:
    PYTHONPATH=. pytest backend/tests/test_owner_kpis.py -x -v
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import BigInteger, Integer, Text, create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault("ZPAY_SECRET_KEY", "test-secret-key-for-owner-kpis-tests-long-enough")
os.environ.setdefault("DATABASE_URL", "sqlite://")

from backend.db.models import Base  # noqa: E402

Base.metadata.tables["z_rate_override"].c["effective_during"].type = Text()
for _tbl in Base.metadata.tables.values():
    for _col in _tbl.columns:
        if _col.primary_key and isinstance(_col.type, BigInteger):
            _col.type = Integer()
for _tbl in Base.metadata.tables.values():
    for _col in _tbl.columns:
        if _col.server_default is not None:
            _sd = _col.server_default
            try:
                _arg = _sd.arg.text if hasattr(_sd, "arg") and hasattr(_sd.arg, "text") else ""
            except Exception:
                _arg = ""
            if "NOW()" in _arg:
                _col.nullable = True
                _col.server_default = None

_engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
)


@event.listens_for(_engine, "connect")
def _register_now(dbapi_conn, _rec):
    dbapi_conn.create_function("NOW", 0, lambda: datetime.now(timezone.utc).isoformat())


Base.metadata.create_all(_engine)
_SessionFactory = sessionmaker(bind=_engine, autoflush=False, autocommit=False)

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402
from backend.db import get_db  # noqa: E402
from backend.db.models import (  # noqa: E402
    PayrollBatch,
    Person,
    Ride,
    RouteBackup,
    RouteRoster,
    TripNotification,
)
from backend.middleware.auth import COOKIE_NAME, create_session  # noqa: E402


def _override_get_db():
    db = _SessionFactory()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db

_AUTH = {COOKIE_NAME: create_session(
    username="testadmin", display_name="Test Admin", color="#333", initials="TA", role="admin",
)}
client = TestClient(app, raise_server_exceptions=True)


def _db():
    return _SessionFactory()


def _wipe():
    sess = _db()
    try:
        for model in (Ride, PayrollBatch, TripNotification, RouteBackup, RouteRoster, Person):
            sess.query(model).delete(synchronize_session=False)
        sess.commit()
    finally:
        sess.close()


@pytest.fixture(autouse=True)
def _clean_db():
    _wipe()
    yield
    _wipe()


def _seed_week(sess):
    p = Person(full_name="Test Driver", active=True, status="active")
    sess.add(p)
    sess.flush()
    b = PayrollBatch(
        source="acumen", company_name="Acumen International",
        week_start=datetime.now(timezone.utc).date() - timedelta(days=6),
        week_end=datetime.now(timezone.utc).date() - timedelta(days=1),
        status="complete",
    )
    sess.add(b)
    sess.flush()
    for i, (gross, z) in enumerate(((100.0, 60.0), (80.0, 50.0))):
        sess.add(Ride(
            payroll_batch_id=b.payroll_batch_id, person_id=p.person_id,
            source="acumen", source_ref=f"seed-{i}", gross_pay=gross, net_pay=gross, z_rate=z, miles=10,
        ))
    sess.commit()
    return p, b


class TestOwnerKpis:
    def test_requires_auth(self):
        resp = client.get("/api/data/owner/kpis", follow_redirects=False)
        assert resp.status_code == 302  # AuthMiddleware bounce to /login
        assert resp.headers["location"] == "/login"

    def test_shape_and_money_math(self):
        sess = _db()
        _seed_week(sess)
        sess.close()

        resp = client.get("/api/data/owner/kpis", cookies=_AUTH)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        for window in ("daily", "weekly", "monthly"):
            assert window in data
        wk = data["weekly"]
        # payroll_history semantics: revenue=sum(gross_pay)=180, cost=sum(z_rate)=110
        assert wk["revenue"] == 180.0
        assert wk["cost"] == 110.0
        assert wk["margin"] == 70.0
        assert wk["margin_pct"] == round(70.0 / 180.0 * 100, 1)
        assert wk["drivers_paid"] == 1

    def test_partner_gross_total_overrides_ride_sum(self):
        sess = _db()
        _, b = _seed_week(sess)
        b.partner_gross_total = 200.0
        sess.commit()
        sess.close()

        resp = client.get("/api/data/owner/kpis", cookies=_AUTH)
        wk = resp.json()["weekly"]
        assert wk["revenue"] == 200.0
        assert wk["margin"] == 90.0

    def test_removed_rides_excluded(self):
        sess = _db()
        p, b = _seed_week(sess)
        sess.add(Ride(
            payroll_batch_id=b.payroll_batch_id, person_id=p.person_id,
            source="acumen", source_ref="seed-removed", gross_pay=999.0, net_pay=999.0, z_rate=999.0,
            miles=10, removed_at=datetime.now(timezone.utc),
        ))
        sess.commit()
        sess.close()

        resp = client.get("/api/data/owner/kpis", cookies=_AUTH)
        assert resp.json()["weekly"]["revenue"] == 180.0

    def test_daily_dispatch_counts(self):
        sess = _db()
        p, _ = _seed_week(sess)
        yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
        sess.add(TripNotification(
            person_id=p.person_id, trip_date=yesterday, source="firstalt", trip_ref="a",
            completed_at=datetime.now(timezone.utc),
        ))
        sess.add(TripNotification(
            person_id=p.person_id, trip_date=yesterday, source="firstalt", trip_ref="b",
            accept_sms_at=datetime.now(timezone.utc), accept_call_at=datetime.now(timezone.utc),
        ))
        sess.commit()
        sess.close()

        d = client.get("/api/data/owner/kpis", cookies=_AUTH).json()["daily"]
        assert d["trips"] == 2
        assert d["completed"] == 1
        assert d["nudges_sent"] == 1
        assert d["calls_made"] == 1
        assert d["zero_touch"] == 1

    def test_backup_coverage_pct(self):
        sess = _db()
        p, _ = _seed_week(sess)
        r1 = RouteRoster(source="acumen", route_school="A ES", route_direction="IB",
                         route_number="01", route_is_odt=False, active=True)
        r2 = RouteRoster(source="acumen", route_school="B ES", route_direction="OB",
                         route_number="02", route_is_odt=False, active=True)
        sess.add_all([r1, r2])
        sess.flush()
        sess.add(RouteBackup(roster_id=r1.roster_id, person_id=p.person_id, rank=1))
        sess.commit()
        sess.close()

        m = client.get("/api/data/owner/kpis", cookies=_AUTH).json()["monthly"]
        assert m["backup_coverage_pct"] == 50.0
