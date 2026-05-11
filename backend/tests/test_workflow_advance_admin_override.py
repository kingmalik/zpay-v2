"""
Tests for the admin-only force-advance bypass on the /advance endpoint.

Endpoint under test:
  POST /api/data/workflow/{batch_id}/advance

What we verify:
  1. Normal advance blocked when z_rate=0 rides exist and no force flag (existing gate preserved).
  2. Non-admin caller with force=true → 403.
  3. Admin caller with force=true → 200, batch advances, AuditLog row created.
  4. AuditLog row captures correct action, target, before/after, and actor fields.
  5. Admin force-advance with NO z_rate=0 rides → advances cleanly, NO AuditLog row.

DB strategy (matches test_audit_log_toggle_active.py pattern):
  In-memory SQLite via StaticPool. Same metadata patches applied before create_all.

Run:
    PYTHONPATH=/path/to/zpay-v2-fresh pytest backend/tests/test_workflow_advance_admin_override.py -v
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import BigInteger, Integer, Text, create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ── Project root on sys.path ──────────────────────────────────────────────────
_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Auth middleware reads ZPAY_SECRET_KEY at import time.
os.environ.setdefault(
    "ZPAY_SECRET_KEY",
    "test-secret-key-for-advance-admin-override-tests-32chars",
)
os.environ.setdefault("DATABASE_URL", "sqlite://")

# Import models so Base.metadata is populated before we patch + create_all.
from backend.db.models import (  # noqa: E402
    AuditLog, Base, PayrollBatch, Person, Ride, ZRateOverride,
)

# ── Metadata patches ──────────────────────────────────────────────────────────

# Patch 1: DATERANGE is PostgreSQL-only — swap to Text so SQLite can create the table.
Base.metadata.tables["z_rate_override"].c["effective_during"].type = Text()

# Patch 2: BigInteger PKs → Integer (SQLite autoincrement only works on INTEGER).
for _tbl in Base.metadata.tables.values():
    for _col in _tbl.columns:
        if _col.primary_key and isinstance(_col.type, BigInteger):
            _col.type = Integer()

# Patch 3: Columns with server_default NOW() — make nullable, remove default.
# SQLite has no NOW(); we set created_at explicitly where the test needs it.
for _tbl in Base.metadata.tables.values():
    for _col in _tbl.columns:
        if _col.server_default is not None:
            try:
                _arg = (
                    _col.server_default.arg.text
                    if hasattr(_col.server_default, "arg") and hasattr(_col.server_default.arg, "text")
                    else ""
                )
            except Exception:
                _arg = ""
            if "NOW()" in _arg:
                _col.nullable = True
                _col.server_default = None

# ── Shared in-memory SQLite engine ───────────────────────────────────────────
_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(_engine)
_SessionFactory = sessionmaker(bind=_engine, autoflush=False, autocommit=False)

# ── FastAPI app + dependency overrides ───────────────────────────────────────
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402
from backend.db import get_db  # noqa: E402
from backend.middleware.auth import COOKIE_NAME, create_session  # noqa: E402


def _override_get_db():
    db = _SessionFactory()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db

# Two session cookies — one admin, one operator (non-admin).
_ADMIN_COOKIE = create_session(
    username="testadmin",
    display_name="Test Admin",
    color="#333",
    initials="TA",
    role="admin",
    user_id=1,
)
_OPERATOR_COOKIE = create_session(
    username="testoperator",
    display_name="Test Operator",
    color="#666",
    initials="TO",
    role="operator",
    user_id=2,
)

admin_client = TestClient(app, raise_server_exceptions=True)
admin_client.cookies.set(COOKIE_NAME, _ADMIN_COOKIE)

operator_client = TestClient(app, raise_server_exceptions=True)
operator_client.cookies.set(COOKIE_NAME, _OPERATOR_COOKIE)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _db():
    return _SessionFactory()


_batch_counter = 0
_person_counter = 0


def _make_batch(db, *, status: str = "rates_review") -> PayrollBatch:
    global _batch_counter
    _batch_counter += 1
    batch = PayrollBatch(
        status=status,
        source="fa",
        company_name=f"Test Company {_batch_counter}",
        week_start=date(2026, 5, 5),
        week_end=date(2026, 5, 9),
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return batch


def _make_person(db, *, full_name: str = "Test Driver") -> Person:
    global _person_counter
    _person_counter += 1
    p = Person(
        full_name=f"{full_name} {_person_counter}",
        email=f"driver_{_person_counter}@example.com",
        active=True,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _make_ride(
    db,
    *,
    batch_id: int,
    person_id: int,
    z_rate: Decimal = Decimal("0"),
    z_rate_source: str = "default",
    service_name: str = "Loew Hall FT IB ODT 01",
) -> Ride:
    import uuid
    ride = Ride(
        payroll_batch_id=batch_id,
        person_id=person_id,
        source="fa",
        source_ref=str(uuid.uuid4()),
        service_name=service_name,
        z_rate=z_rate,
        z_rate_source=z_rate_source,
        gross_pay=Decimal("50.00"),
        net_pay=Decimal("50.00"),
        deduction=Decimal("0"),
        spiff=Decimal("0"),
        miles=Decimal("10"),
    )
    db.add(ride)
    db.commit()
    db.refresh(ride)
    return ride


def _wipe(db):
    db.query(AuditLog).delete(synchronize_session=False)
    db.query(Ride).delete(synchronize_session=False)
    db.query(PayrollBatch).delete(synchronize_session=False)
    db.query(Person).delete(synchronize_session=False)
    db.commit()


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestAdvanceAdminOverride:

    def setup_method(self):
        """Clean slate before every test."""
        db = _db()
        _wipe(db)
        db.close()

    # ── 1. Normal gate preserved ──────────────────────────────────────────────

    def test_advance_blocked_when_zero_rate_rides_exist_no_force(self):
        """Default gate: batch with z_rate=0 rides cannot advance without force."""
        db = _db()
        batch = _make_batch(db, status="rates_review")
        person = _make_person(db)
        _make_ride(db, batch_id=batch.payroll_batch_id, person_id=person.person_id, z_rate=Decimal("0"))
        bid = batch.payroll_batch_id
        db.close()

        resp = admin_client.post(f"/api/data/workflow/{bid}/advance", json={})
        assert resp.status_code == 400, resp.text
        body = resp.json()
        assert body["ok"] is False
        assert any("z_rate=0" in b for b in body.get("blockers", [])), (
            f"Expected a z_rate=0 blocker in response, got: {body}"
        )

    # ── 2. Non-admin 403 on force ─────────────────────────────────────────────

    def test_non_admin_force_returns_403(self):
        """Operator role with force=true must be rejected with 403."""
        db = _db()
        batch = _make_batch(db, status="rates_review")
        person = _make_person(db)
        _make_ride(db, batch_id=batch.payroll_batch_id, person_id=person.person_id, z_rate=Decimal("0"))
        bid = batch.payroll_batch_id
        db.close()

        resp = operator_client.post(f"/api/data/workflow/{bid}/advance", json={"force": True})
        assert resp.status_code == 403, resp.text
        body = resp.json()
        assert body["ok"] is False
        assert "Admin" in body.get("error", "") or "admin" in body.get("error", ""), (
            f"Expected admin-role error message, got: {body}"
        )

    # ── 3. Admin force succeeds and advances batch ────────────────────────────

    def test_admin_force_advance_succeeds(self):
        """Admin with force=true bypasses the z_rate=0 gate and advances the batch."""
        db = _db()
        batch = _make_batch(db, status="rates_review")
        person = _make_person(db)
        _make_ride(db, batch_id=batch.payroll_batch_id, person_id=person.person_id, z_rate=Decimal("0"))
        bid = batch.payroll_batch_id
        db.close()

        resp = admin_client.post(f"/api/data/workflow/{bid}/advance", json={"force": True})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ok"] is True
        assert body["status"] == "payroll_review"

    # ── 4. AuditLog row written correctly ─────────────────────────────────────

    def test_admin_force_advance_writes_audit_log(self):
        """AuditLog row is created when admin force-advances past z_rate=0."""
        db = _db()
        batch = _make_batch(db, status="rates_review")
        person = _make_person(db)
        ride = _make_ride(
            db,
            batch_id=batch.payroll_batch_id,
            person_id=person.person_id,
            z_rate=Decimal("0"),
            service_name="Loew Hall FT IB ODT 01",
        )
        bid = batch.payroll_batch_id
        db.close()

        resp = admin_client.post(f"/api/data/workflow/{bid}/advance", json={"force": True})
        assert resp.status_code == 200, resp.text

        db = _db()
        rows = db.query(AuditLog).filter(
            AuditLog.target_id == bid,
            AuditLog.action == "batch.admin_force_advance",
        ).all()
        db.close()

        assert len(rows) == 1, f"Expected 1 audit row, got {len(rows)}"
        row = rows[0]
        assert row.target_type == "payroll_batch"
        assert row.actor_user_id == 1  # admin user_id from cookie
        assert row.before_value["status"] == "rates_review"
        assert row.before_value["zero_rate_ride_count"] == 1
        assert row.after_value["status"] == "payroll_review"
        # The zero_rate_rides snapshot must include the ride we created.
        zero_rides = row.after_value.get("zero_rate_rides", [])
        assert len(zero_rides) == 1
        assert zero_rides[0]["ride_id"] == ride.ride_id
        assert zero_rides[0]["service_name"] == "Loew Hall FT IB ODT 01"

    # ── 5. No AuditLog when all rides already priced ──────────────────────────

    def test_admin_force_no_zero_rides_no_audit_log(self):
        """When there are no z_rate=0 rides, force-advance succeeds with no AuditLog row."""
        db = _db()
        batch = _make_batch(db, status="rates_review")
        person = _make_person(db)
        _make_ride(
            db,
            batch_id=batch.payroll_batch_id,
            person_id=person.person_id,
            z_rate=Decimal("42.00"),
            z_rate_source="service_default",
        )
        bid = batch.payroll_batch_id
        db.close()

        resp = admin_client.post(f"/api/data/workflow/{bid}/advance", json={"force": True})
        assert resp.status_code == 200, resp.text

        db = _db()
        count = db.query(AuditLog).filter(
            AuditLog.target_id == bid,
            AuditLog.action == "batch.admin_force_advance",
        ).count()
        db.close()

        assert count == 0, f"Expected 0 audit rows when no zero-rate rides, got {count}"

    # ── 6. canceled_trip rides excluded from audit snapshot ───────────────────

    def test_canceled_trip_rides_not_counted_as_zero_rate_violations(self):
        """z_rate=0 rides with z_rate_source='canceled_trip' are exempt from the gate
        and must not appear in the audit snapshot."""
        db = _db()
        batch = _make_batch(db, status="rates_review")
        person = _make_person(db)
        # Only canceled_trip rides — these should NOT block the normal advance.
        _make_ride(
            db,
            batch_id=batch.payroll_batch_id,
            person_id=person.person_id,
            z_rate=Decimal("0"),
            z_rate_source="canceled_trip",
        )
        bid = batch.payroll_batch_id
        db.close()

        # Normal advance (no force) should succeed because canceled_trip is exempt.
        resp = admin_client.post(f"/api/data/workflow/{bid}/advance", json={})
        assert resp.status_code == 200, (
            f"Expected advance to succeed with only canceled_trip rides, got: {resp.text}"
        )
        assert resp.json()["ok"] is True
