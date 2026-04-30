"""
Tests for GET /api/data/dashboard/summary

DB strategy: in-memory SQLite with the same StaticPool + metadata patches
used by test_manual_adjustments.py.  health_check / health_alert tables are
raw-SQL tables created by a migration; we create minimal stubs in SQLite so
the endpoint can query them.

Run:
    PYTHONPATH=/path/to/zpay-v2-fresh pytest backend/tests/test_dashboard_summary.py -v
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import BigInteger, Column, Integer, Text, create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ── project root on sys.path ─────────────────────────────────────────────────
_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault(
    "ZPAY_SECRET_KEY",
    "test-secret-key-for-dashboard-summary-tests-long-enough",
)
os.environ.setdefault("DATABASE_URL", "sqlite://")

from backend.db.models import Base, ZRateOverride  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB  # noqa: E402

# ── Metadata patches ──────────────────────────────────────────────────────────
Base.metadata.tables["z_rate_override"].c["effective_during"].type = Text()

# Patch 0: JSONB is PostgreSQL-only — replace with Text for SQLite.
# Also clear PostgreSQL-specific server_defaults (e.g. '{}'::jsonb) that
# SQLite can't parse.
for _tbl in Base.metadata.tables.values():
    for _col in _tbl.columns:
        if isinstance(_col.type, JSONB):
            _col.type = Text()
            _col.nullable = True
            _col.server_default = None

for _tbl in Base.metadata.tables.values():
    for _col in _tbl.columns:
        if _col.primary_key and isinstance(_col.type, BigInteger):
            _col.type = Integer()

for _tbl in Base.metadata.tables.values():
    for _col in _tbl.columns:
        if _col.server_default is not None:
            try:
                _arg = (
                    _col.server_default.arg.text
                    if hasattr(_col.server_default, "arg")
                    and hasattr(_col.server_default.arg, "text")
                    else ""
                )
            except Exception:
                _arg = ""
            if "NOW()" in _arg:
                _col.nullable = True
                _col.server_default = None

# ── SQLite engine ─────────────────────────────────────────────────────────────
_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


import re as _re


def _sqlite_regexp_replace(value: str, pattern: str, repl: str, flags: str) -> str:
    if value is None:
        return ""
    if "g" in (flags or ""):
        return _re.sub(pattern or "", repl or "", str(value))
    return _re.sub(pattern or "", repl or "", str(value), count=1)


@event.listens_for(_engine, "connect")
def _register_sqlite_udfs(dbapi_conn, rec):
    dbapi_conn.create_function("regexp_replace", 4, _sqlite_regexp_replace)


Base.metadata.create_all(_engine)

# Create health_check + health_alert stubs (raw SQL tables, not in ORM)
from sqlalchemy import text as _stext  # noqa: E402 (needed at module scope for table creation)

with _engine.begin() as conn:
    conn.execute(_stext(
        "CREATE TABLE IF NOT EXISTS health_check ("
        " check_name TEXT PRIMARY KEY,"
        " status TEXT,"
        " last_checked_at DATETIME,"
        " consecutive_failures INTEGER DEFAULT 0,"
        " last_ok_at DATETIME,"
        " latency_ms INTEGER DEFAULT 0,"
        " detail TEXT,"
        " enabled INTEGER DEFAULT 1,"
        " muted_until DATETIME"
        ")"
    ))
    conn.execute(_stext(
        "CREATE TABLE IF NOT EXISTS health_alert ("
        " alert_id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " check_name TEXT,"
        " severity TEXT,"
        " message TEXT,"
        " created_at DATETIME,"
        " resolved_at DATETIME,"
        " acked_at DATETIME,"
        " notified TEXT"
        ")"
    ))

_SessionFactory = sessionmaker(bind=_engine, autoflush=False, autocommit=False)

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402
from backend.db import get_db  # noqa: E402
from backend.db.models import (  # noqa: E402
    BatchCorrectionLog,
    PayrollBatch,
    Person,
    Ride,
    TripNotification,
    ZRateService,
)
from backend.middleware.auth import COOKIE_NAME, create_session  # noqa: E402


def _override_get_db():
    db = _SessionFactory()
    try:
        yield db
    finally:
        db.close()


# Apply override at module level.  Each test class re-applies it in
# setup_method to guard against cross-module contamination (other test files
# replace the override on the shared FastAPI app instance).
app.dependency_overrides[get_db] = _override_get_db

_SESSION_COOKIE = create_session(
    username="testadmin",
    display_name="Test Admin",
    color="#333",
    initials="TA",
    role="admin",
)
_AUTH = {COOKIE_NAME: _SESSION_COOKIE}

client = TestClient(app, raise_server_exceptions=True)

_NOW = datetime.now(timezone.utc)


# ── helpers ───────────────────────────────────────────────────────────────────

def _db():
    return _SessionFactory()


def _wipe():
    sess = _db()
    try:
        sess.query(BatchCorrectionLog).delete(synchronize_session=False)
        sess.query(TripNotification).delete(synchronize_session=False)
        sess.query(Ride).delete(synchronize_session=False)
        sess.query(ZRateService).delete(synchronize_session=False)
        sess.query(PayrollBatch).delete(synchronize_session=False)
        sess.query(Person).delete(synchronize_session=False)
        # wipe health stubs
        from sqlalchemy import text
        sess.execute(text("DELETE FROM health_check"))
        sess.execute(text("DELETE FROM health_alert"))
        sess.commit()
    finally:
        sess.close()


def _seed_person(sess, person_id: int = 1, full_name: str = "Driver One") -> Person:
    p = Person(
        person_id=person_id,
        full_name=full_name,
        active=True,
        status="active",
        created_at=_NOW,
    )
    sess.add(p)
    sess.flush()
    return p


def _seed_batch(
    sess,
    batch_id: int = 1,
    source: str = "acumen",
    company_name: str = "FirstAlt",
    status: str = "complete",
    finalized_at=None,
    week_start=None,
    week_end=None,
) -> PayrollBatch:
    b = PayrollBatch(
        payroll_batch_id=batch_id,
        source=source,
        company_name=company_name,
        batch_ref=f"W-test-{batch_id}",
        status=status,
        finalized_at=finalized_at or _NOW,
        week_start=week_start or date(2026, 4, 14),
        week_end=week_end or date(2026, 4, 18),
        period_start=date(2026, 4, 14),
        period_end=date(2026, 4, 18),
        currency="USD",
        uploaded_at=_NOW,
    )
    sess.add(b)
    sess.flush()
    return b


def _seed_ride(
    sess,
    ride_id: int,
    batch_id: int,
    person_id: int,
    z_rate: float = 90.0,
    net_pay: float = 90.0,
) -> Ride:
    r = Ride(
        ride_id=ride_id,
        payroll_batch_id=batch_id,
        person_id=person_id,
        source="acumen",
        source_ref=f"auto-{ride_id}",
        service_name="Test Route",
        net_pay=Decimal(str(net_pay)),
        z_rate=Decimal(str(z_rate)),
        gross_pay=Decimal(str(z_rate)),
        z_rate_source="service",
        miles=Decimal("10"),
        deduction=Decimal("0"),
        spiff=Decimal("0"),
    )
    sess.add(r)
    sess.flush()
    return r


def _seed_trip(
    sess,
    person_id: int,
    trip_date=None,
    source: str = "firstalt",
    trip_ref: str = "T001",
    trip_status: str = None,
    started_at=None,
    accept_escalated_at=None,
    start_escalated_at=None,
) -> TripNotification:
    tn = TripNotification(
        person_id=person_id,
        trip_date=trip_date or date.today(),
        source=source,
        trip_ref=trip_ref,
        trip_status=trip_status,
        started_at=started_at,
        accept_escalated_at=accept_escalated_at,
        start_escalated_at=start_escalated_at,
    )
    sess.add(tn)
    sess.flush()
    return tn


def _seed_health_check(sess, check_name: str = "db_responsive", status: str = "green"):
    from sqlalchemy import text
    sess.execute(
        text(
            "INSERT OR REPLACE INTO health_check "
            "(check_name, status, consecutive_failures) "
            "VALUES (:name, :status, 0)"
        ),
        {"name": check_name, "status": status},
    )
    sess.commit()


# ── Override management ───────────────────────────────────────────────────────
# Other test files also override app.dependency_overrides[get_db] at module
# level.  Whichever file is collected last wins the module-level override, so
# any test class that needs our SQLite session must re-apply it in setup_method
# and restore the previous value in teardown_method.

def _apply_override():
    prev = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _override_get_db
    return prev


def _restore_override(prev):
    if prev is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = prev


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestDashboardSummaryShape:
    """Test 1 — response has all required top-level keys with correct types."""

    def setup_method(self):
        self._prev = _apply_override()
        _wipe()

    def teardown_method(self):
        _wipe()
        _restore_override(self._prev)

    def test_response_shape(self):
        resp = client.get("/api/data/dashboard/summary", cookies=_AUTH)
        assert resp.status_code == 200, resp.text
        body = resp.json()

        required_keys = {
            "today_trips", "active_drivers", "health",
            "inflight_alerts", "last_payroll", "week_progress",
            "money_flow", "server_time",
        }
        missing = required_keys - set(body.keys())
        assert not missing, f"Missing keys: {missing}"

        # today_trips sub-keys
        tt = body["today_trips"]
        assert "fa" in tt and "ed" in tt and "total" in tt
        for partner_key in ("fa", "ed"):
            for sub in ("total", "live", "completed", "canceled", "escalations"):
                assert sub in tt[partner_key], f"Missing {sub} in today_trips.{partner_key}"

        # active_drivers
        ad = body["active_drivers"]
        assert "count" in ad and "idle_over_2h" in ad

        # health
        h = body["health"]
        assert "overall" in h and "checks" in h and "open_alerts" in h

        # week_progress
        wp = body["week_progress"]
        for k in ("days_into_week", "week_day_count", "today_total", "avg_daily_last_4w", "projected_week_total"):
            assert k in wp, f"Missing {k} in week_progress"

        # money_flow
        mf = body["money_flow"]
        for k in ("partner_receipts", "driver_pay", "margin", "margin_pct"):
            assert k in mf, f"Missing {k} in money_flow"


class TestDashboardTodayTrips:
    """Tests 2-4: today_trips counting by source and status."""

    def setup_method(self):
        self._prev = _apply_override()
        _wipe()
        sess = _db()
        _seed_person(sess, 1, "Driver A")
        _seed_person(sess, 2, "Driver B")
        _seed_person(sess, 3, "Driver C")
        sess.commit()
        sess.close()

    def teardown_method(self):
        _wipe()
        _restore_override(self._prev)

    def test_fa_trip_counted_under_fa(self):
        """Test 2 — FA (firstalt source) trips count in today_trips.fa."""
        sess = _db()
        _seed_trip(sess, person_id=1, source="firstalt", trip_ref="FA001", trip_status="InProgress")
        sess.commit()
        sess.close()

        resp = client.get("/api/data/dashboard/summary", cookies=_AUTH)
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["today_trips"]["fa"]["total"] == 1
        assert body["today_trips"]["ed"]["total"] == 0
        assert body["today_trips"]["total"] == 1

    def test_ed_trip_counted_under_ed(self):
        """Test 3 — ED (maz source) trips count in today_trips.ed."""
        sess = _db()
        _seed_trip(sess, person_id=2, source="maz", trip_ref="ED001", trip_status="ToStop")
        sess.commit()
        sess.close()

        resp = client.get("/api/data/dashboard/summary", cookies=_AUTH)
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["today_trips"]["ed"]["total"] == 1
        assert body["today_trips"]["fa"]["total"] == 0

    def test_canceled_trip_counted_as_canceled(self):
        """Test 4 — NoShowReported status maps to canceled bucket."""
        sess = _db()
        _seed_trip(sess, person_id=3, source="firstalt", trip_ref="FA002", trip_status="NoShowReported")
        sess.commit()
        sess.close()

        resp = client.get("/api/data/dashboard/summary", cookies=_AUTH)
        assert resp.status_code == 200, resp.text
        fa = resp.json()["today_trips"]["fa"]

        assert fa["canceled"] == 1
        assert fa["live"] == 0
        assert fa["completed"] == 0


class TestDashboardActiveDrivers:
    """Tests 5-6: active driver count derived from today's trip notifications."""

    def setup_method(self):
        self._prev = _apply_override()
        _wipe()

    def teardown_method(self):
        _wipe()
        _restore_override(self._prev)

    def test_active_count_reflects_unique_drivers_today(self):
        """Test 5 — 2 trips for same driver = count 1, not 2."""
        sess = _db()
        _seed_person(sess, 10)
        _seed_trip(sess, person_id=10, trip_ref="T010a")
        _seed_trip(sess, person_id=10, trip_ref="T010b")
        sess.commit()
        sess.close()

        resp = client.get("/api/data/dashboard/summary", cookies=_AUTH)
        body = resp.json()
        assert body["active_drivers"]["count"] == 1

    def test_zero_active_when_no_trips_today(self):
        """Test 6 — no trip notifications today → active count 0."""
        resp = client.get("/api/data/dashboard/summary", cookies=_AUTH)
        body = resp.json()
        assert body["active_drivers"]["count"] == 0
        assert body["active_drivers"]["idle_over_2h"] == 0


class TestDashboardHealthChecks:
    """Tests 7-8: health overall derived from health_check table."""

    def setup_method(self):
        self._prev = _apply_override()
        _wipe()

    def teardown_method(self):
        _wipe()
        _restore_override(self._prev)

    def test_all_green_checks_produce_green_overall(self):
        """Test 7 — all checks green → overall=green."""
        sess = _db()
        _seed_health_check(sess, "backend_alive", "green")
        _seed_health_check(sess, "db_responsive", "green")

        resp = client.get("/api/data/dashboard/summary", cookies=_AUTH)
        assert resp.json()["health"]["overall"] == "green"

    def test_one_red_check_produces_red_overall(self):
        """Test 8 — one red check → overall=red."""
        sess = _db()
        _seed_health_check(sess, "backend_alive", "green")
        _seed_health_check(sess, "db_responsive", "red")

        resp = client.get("/api/data/dashboard/summary", cookies=_AUTH)
        assert resp.json()["health"]["overall"] == "red"


class TestDashboardLastPayroll:
    """Tests 9-10: last_payroll from most recent finalized batch."""

    def setup_method(self):
        self._prev = _apply_override()
        _wipe()

    def teardown_method(self):
        _wipe()
        _restore_override(self._prev)

    def test_last_payroll_null_when_no_finalized_batch(self):
        """Test 9 — no finalized batches → last_payroll is null."""
        sess = _db()
        _seed_batch(sess, batch_id=1, finalized_at=None, status="uploaded")
        sess.commit()
        sess.close()

        # Override finalized_at to None
        sess = _db()
        from sqlalchemy import text
        sess.execute(text("UPDATE payroll_batch SET finalized_at = NULL WHERE payroll_batch_id = 1"))
        sess.commit()
        sess.close()

        resp = client.get("/api/data/dashboard/summary", cookies=_AUTH)
        assert resp.json()["last_payroll"] is None

    def test_last_payroll_has_correct_driver_count_and_total(self):
        """Test 10 — finalized batch with 2 drivers and known z_rates returns correct totals."""
        sess = _db()
        _seed_person(sess, 20, "Driver Twenty")
        _seed_person(sess, 21, "Driver TwentyOne")
        _seed_batch(sess, batch_id=50, source="acumen", finalized_at=_NOW)
        _seed_ride(sess, ride_id=500, batch_id=50, person_id=20, z_rate=90.0)
        _seed_ride(sess, ride_id=501, batch_id=50, person_id=21, z_rate=100.0)
        sess.commit()
        sess.close()

        resp = client.get("/api/data/dashboard/summary", cookies=_AUTH)
        assert resp.status_code == 200, resp.text
        lp = resp.json()["last_payroll"]
        assert lp is not None
        assert lp["driver_count"] == 2
        assert abs(lp["total_paid"] - 190.0) < 0.01


class TestDashboardMoneyFlow:
    """Tests 11-12: money_flow margin calculation."""

    def setup_method(self):
        self._prev = _apply_override()
        _wipe()

    def teardown_method(self):
        _wipe()
        _restore_override(self._prev)

    def test_margin_is_receipts_minus_driver_pay(self):
        """Test 11 — margin = partner_receipts - driver_pay."""
        sess = _db()
        _seed_person(sess, 30)
        # Use current week_start (this Monday) so the query window covers it
        today = date.today()
        week_monday = today - timedelta(days=today.weekday())
        _seed_batch(
            sess, batch_id=60, source="acumen",
            week_start=week_monday, week_end=week_monday + timedelta(days=4),
        )
        # net_pay = 120 (partner receipt), z_rate = 90 (driver pay) → margin = 30
        _seed_ride(sess, ride_id=600, batch_id=60, person_id=30, z_rate=90.0, net_pay=120.0)
        sess.commit()
        sess.close()

        resp = client.get("/api/data/dashboard/summary", cookies=_AUTH)
        mf = resp.json()["money_flow"]
        assert abs(mf["partner_receipts"] - 120.0) < 0.01
        assert abs(mf["driver_pay"] - 90.0) < 0.01
        assert abs(mf["margin"] - 30.0) < 0.01

    def test_margin_zero_when_no_rides_this_week(self):
        """Test 12 — no rides in current week → all money_flow values are 0."""
        resp = client.get("/api/data/dashboard/summary", cookies=_AUTH)
        mf = resp.json()["money_flow"]
        assert mf["partner_receipts"] == 0.0
        assert mf["driver_pay"] == 0.0
        assert mf["margin"] == 0.0
        assert mf["margin_pct"] == 0.0


class TestDashboardInflightAlerts:
    """Test 13 — escalated trip notifications counted in inflight_alerts."""

    def setup_method(self):
        self._prev = _apply_override()
        _wipe()

    def teardown_method(self):
        _wipe()
        _restore_override(self._prev)

    def test_escalated_trips_counted(self):
        """Test 13 — 2 escalated trips → inflight_alerts = 2."""
        sess = _db()
        _seed_person(sess, 40, "Escalated Driver A")
        _seed_person(sess, 41, "Escalated Driver B")
        _seed_trip(
            sess, person_id=40, trip_ref="ESC001",
            accept_escalated_at=_NOW,
        )
        _seed_trip(
            sess, person_id=41, trip_ref="ESC002",
            start_escalated_at=_NOW,
        )
        sess.commit()
        sess.close()

        resp = client.get("/api/data/dashboard/summary", cookies=_AUTH)
        assert resp.json()["inflight_alerts"] == 2
