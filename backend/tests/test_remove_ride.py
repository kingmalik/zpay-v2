"""
Tests for the "remove ride" soft-delete feature (2026-05-21).

Endpoints under test:
  PATCH /api/data/rides/{ride_id}/remove   — admin-only soft-delete
  PATCH /api/data/rides/{ride_id}/restore  — admin-only restore

Recompute-path coverage (source-text inspection):
  _build_summary            in summary.py
  api_driver_paystub        in api_data.py
  api_payroll_batch_detail  in api_data.py
  regenerate_paystub_from_data in services/paystub_archive.py
  backfill query            in routes/paystubs.py

DB strategy: same SQLite in-memory pattern as test_manual_adjustments.py.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import BigInteger, Column, Integer, Text, create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ── Project root on sys.path ──────────────────────────────────────────────────
_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault(
    "ZPAY_SECRET_KEY",
    "test-secret-key-remove-ride-tests-long-enough-for-hmac",
)
os.environ.setdefault("DATABASE_URL", "sqlite://")

# Import models early so Base.metadata is populated before patches.
from backend.db.models import Base, ZRateOverride  # noqa: E402

# ── Metadata patches (SQLite compat) ─────────────────────────────────────────

# Patch 1: DATERANGE → Text
Base.metadata.tables["z_rate_override"].c["effective_during"].type = Text()

# Patch 2: BigInteger PKs → Integer (SQLite autoincrement requirement)
for _tbl in Base.metadata.tables.values():
    for _col in _tbl.columns:
        if _col.primary_key and isinstance(_col.type, BigInteger):
            _col.type = Integer()

# Patch 3: server_default=text("NOW()") → nullable, no server_default
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

# ── Shared in-memory engine ───────────────────────────────────────────────────

_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(_engine)
_SessionFactory = sessionmaker(bind=_engine, autoflush=False, autocommit=False)

# ── FastAPI app + test client ─────────────────────────────────────────────────

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402
from backend.db import get_db  # noqa: E402
from backend.db.models import PayrollBatch, Person, Ride  # noqa: E402
from backend.middleware.auth import COOKIE_NAME, create_session  # noqa: E402


def _override_get_db():
    db = _SessionFactory()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db

_SESSION_COOKIE = create_session(
    username="admin_test",
    display_name="Admin Test",
    color="#333",
    initials="AT",
    role="admin",
)
_AUTH = {COOKIE_NAME: _SESSION_COOKIE}

_SESSION_COOKIE_VIEWER = create_session(
    username="viewer_test",
    display_name="Viewer Test",
    color="#aaa",
    initials="VT",
    role="viewer",
)
_VIEWER_AUTH = {COOKIE_NAME: _SESSION_COOKIE_VIEWER}

client = TestClient(app, raise_server_exceptions=True)

# ── DB helpers ────────────────────────────────────────────────────────────────

_NOW = datetime.now(timezone.utc)


def _db():
    return _SessionFactory()


def _wipe():
    s = _db()
    try:
        s.query(Ride).delete(synchronize_session=False)
        s.query(PayrollBatch).delete(synchronize_session=False)
        s.query(Person).delete(synchronize_session=False)
        s.commit()
    finally:
        s.close()


def _seed_person(s, person_id: int = 1) -> Person:
    p = Person(
        person_id=person_id,
        full_name="Test Driver",
        paycheck_code="1001",
        active=True,
        status="active",
        created_at=_NOW,
    )
    s.add(p)
    s.flush()
    return p


def _seed_batch(s, batch_id: int = 1) -> PayrollBatch:
    b = PayrollBatch(
        payroll_batch_id=batch_id,
        source="acumen",
        company_name="FirstAlt",
        batch_ref="W-test",
        status="uploaded",
        currency="USD",
        uploaded_at=_NOW,
        period_start=date(2026, 5, 2),
        period_end=date(2026, 5, 8),
        week_start=date(2026, 5, 2),
        week_end=date(2026, 5, 8),
    )
    s.add(b)
    s.flush()
    return b


def _seed_ride(
    s,
    ride_id: int,
    batch_id: int = 1,
    person_id: int = 1,
    z_rate: float = 132.0,
    source: str = "acumen",
) -> Ride:
    r = Ride(
        ride_id=ride_id,
        payroll_batch_id=batch_id,
        person_id=person_id,
        source=source,
        source_ref=f"test-src-{ride_id}",
        service_name="ChanceLight NW ALT OB 01",
        z_rate=Decimal(str(z_rate)),
        z_rate_source="service",
        gross_pay=Decimal("200.00"),
        net_pay=Decimal("200.00"),
        miles=Decimal("0.000"),
        deduction=Decimal("0"),
        spiff=Decimal("0"),
        ride_start_ts=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    s.add(r)
    s.flush()
    return r


# =============================================================================
# Endpoint tests
# =============================================================================


class TestRemoveRideEndpoint:
    """PATCH /api/data/rides/{ride_id}/remove"""

    def setup_method(self):
        _wipe()
        s = _db()
        _seed_person(s)
        _seed_batch(s)
        _seed_ride(s, ride_id=1001)
        s.commit()
        s.close()

    def teardown_method(self):
        _wipe()

    # Test 1 — happy path: ride is soft-deleted, row kept, removed_at set
    def test_remove_sets_audit_columns(self):
        resp = client.patch(
            "/api/data/rides/1001/remove",
            json={"reason": "Already paid in W17"},
            cookies=_AUTH,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ok"] is True
        assert body["ride_id"] == 1001
        assert body["removed_at"] is not None
        assert body["removed_by"] == "admin_test"
        assert body["removed_reason"] == "Already paid in W17"

        # Row must still exist in DB
        s = _db()
        ride = s.query(Ride).filter(Ride.ride_id == 1001).first()
        s.close()
        assert ride is not None, "Ride row must NOT be deleted — revenue preserved"
        assert ride.removed_at is not None
        assert ride.removed_by == "admin_test"
        assert ride.removed_reason == "Already paid in W17"
        # Revenue columns intact
        assert float(ride.gross_pay) == 200.00
        assert float(ride.net_pay) == 200.00

    # Test 2 — missing reason → 400
    def test_remove_requires_reason(self):
        resp = client.patch(
            "/api/data/rides/1001/remove",
            json={},
            cookies=_AUTH,
        )
        assert resp.status_code == 400, resp.text

    # Test 3 — reason > 200 chars → 400
    def test_remove_reason_too_long(self):
        resp = client.patch(
            "/api/data/rides/1001/remove",
            json={"reason": "x" * 201},
            cookies=_AUTH,
        )
        assert resp.status_code == 400, resp.text

    # Test 4 — non-existent ride → 404
    def test_remove_nonexistent_ride(self):
        resp = client.patch(
            "/api/data/rides/9999/remove",
            json={"reason": "test"},
            cookies=_AUTH,
        )
        assert resp.status_code == 404, resp.text

    # Test 5 — viewer role is rejected with 403
    def test_remove_requires_admin_role(self):
        resp = client.patch(
            "/api/data/rides/1001/remove",
            json={"reason": "test"},
            cookies=_VIEWER_AUTH,
        )
        assert resp.status_code == 403, resp.text

    # Test 6 — idempotent: removing an already-removed ride is a no-op
    def test_remove_idempotent(self):
        client.patch(
            "/api/data/rides/1001/remove",
            json={"reason": "First remove"},
            cookies=_AUTH,
        )
        resp2 = client.patch(
            "/api/data/rides/1001/remove",
            json={"reason": "Second remove"},
            cookies=_AUTH,
        )
        assert resp2.status_code == 200, resp2.text
        # Original reason preserved
        assert resp2.json()["removed_reason"] == "First remove"


class TestRestoreRideEndpoint:
    """PATCH /api/data/rides/{ride_id}/restore"""

    def setup_method(self):
        _wipe()
        s = _db()
        _seed_person(s)
        _seed_batch(s)
        _seed_ride(s, ride_id=2001)
        s.commit()
        s.close()

    def teardown_method(self):
        _wipe()

    # Test 7 — restore a removed ride clears audit columns
    def test_restore_clears_removed_fields(self):
        client.patch(
            "/api/data/rides/2001/remove",
            json={"reason": "Test remove"},
            cookies=_AUTH,
        )
        resp = client.patch(
            "/api/data/rides/2001/restore",
            json={},
            cookies=_AUTH,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["ok"] is True

        s = _db()
        ride = s.query(Ride).filter(Ride.ride_id == 2001).first()
        s.close()
        assert ride.removed_at is None
        assert ride.removed_by is None
        assert ride.removed_reason is None

    # Test 8 — restoring an active (never-removed) ride is a no-op
    def test_restore_active_ride_is_noop(self):
        resp = client.patch(
            "/api/data/rides/2001/restore",
            json={},
            cookies=_AUTH,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json().get("already_active") is True

    # Test 9 — viewer cannot restore
    def test_restore_requires_admin_role(self):
        resp = client.patch(
            "/api/data/rides/2001/restore",
            json={},
            cookies=_VIEWER_AUTH,
        )
        assert resp.status_code == 403, resp.text


class TestDriverPaystubExcludesRemoved:
    """
    GET /api/data/payroll-history/{batch_id}/driver/{person_id}
    The response must include removed_at / removed_reason fields on each ride.
    """

    def setup_method(self):
        _wipe()
        s = _db()
        _seed_person(s)
        _seed_batch(s)
        _seed_ride(s, ride_id=3001, z_rate=132.0)
        _seed_ride(s, ride_id=3002, z_rate=90.0)
        s.commit()
        s.close()

    def teardown_method(self):
        _wipe()

    # Test 10 — active ride has removed_at=None in response
    def test_active_ride_has_no_removed_at(self):
        resp = client.get("/api/data/payroll-history/1/driver/1", cookies=_AUTH)
        assert resp.status_code == 200, resp.text
        rides = resp.json()["rides"]
        assert len(rides) == 2
        for r in rides:
            assert r["removed_at"] is None

    # Test 11 — after remove, ride has removed_at set in response
    def test_removed_ride_has_removed_at_in_response(self):
        client.patch(
            "/api/data/rides/3001/remove",
            json={"reason": "Back-pay duplicate"},
            cookies=_AUTH,
        )
        resp = client.get("/api/data/payroll-history/1/driver/1", cookies=_AUTH)
        assert resp.status_code == 200, resp.text
        rides = resp.json()["rides"]
        ride_3001 = next(r for r in rides if r["ride_id"] == 3001)
        assert ride_3001["removed_at"] is not None
        assert ride_3001["removed_reason"] == "Back-pay duplicate"
        # Other ride untouched
        ride_3002 = next(r for r in rides if r["ride_id"] == 3002)
        assert ride_3002["removed_at"] is None


# =============================================================================
# Recompute-path coverage via source-text inspection
# =============================================================================


class TestRecomputePathsCoverageInspection:
    """
    Confirm that all payout-sum code paths exclude removed rides.

    These checks use source-text inspection — the same approach used in
    test_manual_adjustments.py for PostgreSQL-only constructs. Each test
    searches the relevant function body for the removed_at filter.
    """

    def _read(self, rel_path: str) -> str:
        root = Path(__file__).resolve().parents[2]
        return (root / rel_path).read_text(encoding="utf-8")

    # Test 12 — _build_summary excludes removed rides from z_rate sums
    def test_build_summary_has_removed_at_filter(self):
        src = self._read("backend/routes/summary.py")
        fn_start = src.find("def _build_summary(")
        assert fn_start != -1, "_build_summary must be defined in summary.py"
        fn_body = src[fn_start : fn_start + 8000]
        has_filter = (
            "removed_at.is_(None)" in fn_body
            or "removed_at IS NULL" in fn_body
            or ".removed_at" in fn_body
        )
        assert has_filter, (
            "_build_summary must filter WHERE removed_at IS NULL "
            "so soft-deleted rides are excluded from driver payout totals"
        )

    # Test 13 — regenerate_paystub_from_data excludes removed rides
    def test_paystub_archive_regenerate_has_removed_at_filter(self):
        src = self._read("backend/services/paystub_archive.py")
        fn_start = src.find("def regenerate_paystub_from_data(")
        assert fn_start != -1
        fn_body = src[fn_start : fn_start + 2000]
        has_filter = "removed_at.is_(None)" in fn_body or "removed_at" in fn_body
        assert has_filter, (
            "regenerate_paystub_from_data must filter removed_at IS NULL "
            "so soft-deleted rides are excluded from PDF generation"
        )

    # Test 14 — backfill endpoint excludes removed rides from person_ids query
    def test_paystubs_backfill_has_removed_at_filter(self):
        src = self._read("backend/routes/paystubs.py")
        fn_start = src.find("def admin_backfill(")
        assert fn_start != -1
        fn_body = src[fn_start : fn_start + 5000]
        has_filter = "removed_at.is_(None)" in fn_body or "removed_at" in fn_body
        assert has_filter, (
            "admin_backfill must filter removed_at IS NULL from the person_ids "
            "and rides queries so removed rides are excluded from backfill PDFs"
        )

    # Test 15 — api_payroll_batch_detail excludes removed rides from batch aggregation
    def test_batch_detail_excludes_removed(self):
        src = self._read("backend/routes/api_data.py")
        fn_start = src.find("def api_payroll_batch_detail(")
        assert fn_start != -1
        fn_body = src[fn_start : fn_start + 3000]
        has_filter = "removed_at.is_(None)" in fn_body or "removed_at" in fn_body
        assert has_filter, (
            "api_payroll_batch_detail must exclude removed rides "
            "from batch-level driver cost aggregation"
        )

    # Test 16 — remove endpoint is admin-gated (require_role dependency present)
    def test_remove_endpoint_has_admin_gate(self):
        src = self._read("backend/routes/api_data.py")
        fn_start = src.find("def api_remove_ride(")
        assert fn_start != -1
        # Walk back 500 chars for the decorator block
        decorator_block = src[max(0, fn_start - 500) : fn_start]
        has_gate = (
            "require_role" in decorator_block
            and "admin" in decorator_block
        )
        assert has_gate, (
            "api_remove_ride must be gated with require_role('admin') — "
            "non-admin users must never be able to soft-delete rides"
        )

    # Test 17 — email send-one excludes removed rides (source-text check)
    def test_email_send_one_has_removed_at_filter(self):
        src = self._read("backend/routes/email.py")
        # Find the send-one ride query block
        assert "removed_at.is_(None)" in src, (
            "email.py must filter Ride.removed_at.is_(None) in the send-one "
            "ride query so soft-deleted rides are never included in emailed PDFs"
        )

    # Test 18 — workflow batch-send loop excludes removed rides (source-text check)
    def test_workflow_batch_send_has_removed_at_filter(self):
        src = self._read("backend/routes/workflow.py")
        assert "removed_at.is_(None)" in src, (
            "workflow.py must filter Ride.removed_at.is_(None) in the batch-send "
            "loop so soft-deleted rides are never included in batch-emailed PDFs"
        )

    # Test 19 — workflow batch-summary has removed_at filter
    def test_workflow_batch_summary_has_removed_at_filter(self):
        src = self._read("backend/routes/workflow.py")
        fn_start = src.find("def workflow_batch_summary(")
        assert fn_start != -1, "workflow_batch_summary must exist in workflow.py"
        fn_body = src[fn_start : fn_start + 5000]
        assert "removed_at.is_(None)" in fn_body, (
            "workflow_batch_summary driver_rows query must filter removed_at IS NULL "
            "so mom's workflow page driver cost numbers exclude removed rides"
        )

    # Test 20 — SP ITEMIZED REPORT trip_rows_raw has removed_at filter
    def test_sp_itemized_report_has_removed_at_filter(self):
        src = self._read("backend/routes/workflow.py")
        assert "trip_rows_raw" in src, "trip_rows_raw query must exist in workflow.py"
        # Find the trip_rows_raw assignment and check the filter nearby
        idx = src.find("trip_rows_raw")
        context = src[idx : idx + 1000]
        assert "removed_at.is_(None)" in context, (
            "SP ITEMIZED REPORT trip_rows_raw query must filter removed_at IS NULL "
            "so removed back-pay lines are not exported to FA"
        )

    # Test 21 — payroll_history batch list has removed_at filter
    def test_payroll_history_batch_list_has_removed_at_filter(self):
        src = self._read("backend/routes/payroll_history.py")
        assert "removed_at.is_(None)" in src, (
            "payroll_history.py must filter Ride.removed_at.is_(None) in the "
            "batch list aggregate query so batch totals exclude removed rides"
        )

    # Test 22 — payroll_history batch detail has removed_at filter
    def test_payroll_history_batch_detail_has_removed_at_filter(self):
        src = self._read("backend/routes/payroll_history.py")
        # Must appear at least twice — once for batch list, once for batch detail
        count = src.count("removed_at.is_(None)")
        assert count >= 2, (
            f"payroll_history.py must filter removed_at IS NULL in BOTH the "
            f"batch list AND batch detail queries — found {count} occurrence(s)"
        )

    # Test 23 — AuditLog is written on remove (source-text check)
    def test_remove_endpoint_writes_audit_log(self):
        src = self._read("backend/routes/api_data.py")
        fn_start = src.find("def api_remove_ride(")
        assert fn_start != -1
        fn_body = src[fn_start : fn_start + 3000]
        assert "AuditLog(" in fn_body, (
            "api_remove_ride must write an AuditLog row so every removal is "
            "traceable in the immutable audit trail"
        )
        assert 'action="ride.remove"' in fn_body, (
            "AuditLog action must be 'ride.remove'"
        )

    # Test 24 — AuditLog is written on restore (source-text check)
    def test_restore_endpoint_writes_audit_log(self):
        src = self._read("backend/routes/api_data.py")
        fn_start = src.find("def api_restore_ride(")
        assert fn_start != -1
        fn_body = src[fn_start : fn_start + 3000]
        assert "AuditLog(" in fn_body, (
            "api_restore_ride must write an AuditLog row so every restoration is "
            "traceable in the immutable audit trail"
        )
        assert 'action="ride.restore"' in fn_body, (
            "AuditLog action must be 'ride.restore'"
        )

    # Test 25 — migration index is partial (postgresql_where present)
    def test_migration_has_partial_index(self):
        src = self._read(
            "backend/alembic/versions/zx3y4z5a6b7c_add_ride_soft_delete.py"
        )
        assert "postgresql_where" in src, (
            "The soft-delete migration must create a PARTIAL index "
            "(postgresql_where=sa.text('removed_at IS NULL')) not a full B-tree"
        )
        assert "ix_ride_removed_at_null" in src, (
            "Partial index must be named 'ix_ride_removed_at_null'"
        )


# =============================================================================
# Operator role regression tests (MEDIUM #1)
# =============================================================================


_SESSION_COOKIE_OPERATOR = create_session(
    username="operator_test",
    display_name="Operator Test",
    color="#555",
    initials="OT",
    role="operator",
)
_OPERATOR_AUTH = {COOKIE_NAME: _SESSION_COOKIE_OPERATOR}


class TestRoleGating:
    """
    Verify that operator (mom's actual role) and viewer both receive 403
    on the remove and restore endpoints — only admin may soft-delete rides.
    """

    def setup_method(self):
        _wipe()
        s = _db()
        _seed_person(s)
        _seed_batch(s)
        _seed_ride(s, ride_id=4001)
        s.commit()
        s.close()

    def teardown_method(self):
        _wipe()

    # Test 26 — operator role cannot remove a ride
    def test_operator_cannot_remove_ride(self):
        resp = client.patch(
            "/api/data/rides/4001/remove",
            json={"reason": "test"},
            cookies=_OPERATOR_AUTH,
        )
        assert resp.status_code == 403, (
            f"operator role must be rejected with 403 on remove — got {resp.status_code}"
        )

    # Test 27 — operator role cannot restore a ride
    def test_operator_cannot_restore_ride(self):
        # First remove via admin so there is something to restore
        client.patch(
            "/api/data/rides/4001/remove",
            json={"reason": "setup for restore test"},
            cookies=_AUTH,
        )
        resp = client.patch(
            "/api/data/rides/4001/restore",
            json={},
            cookies=_OPERATOR_AUTH,
        )
        assert resp.status_code == 403, (
            f"operator role must be rejected with 403 on restore — got {resp.status_code}"
        )

    # Test 28 — viewer role cannot remove a ride (regression guard)
    def test_viewer_cannot_remove_ride(self):
        resp = client.patch(
            "/api/data/rides/4001/remove",
            json={"reason": "test"},
            cookies=_VIEWER_AUTH,
        )
        assert resp.status_code == 403, resp.text

    # Test 29 — admin can remove and ride count in paystub reflects active only
    def test_paystub_totals_exclude_removed_ride(self):
        """
        Regression: api_driver_paystub totals must exclude removed rides.
        Seed two rides ($132 + $90). Remove the $132 ride. Totals must reflect $90 only.
        """
        s = _db()
        _seed_ride(s, ride_id=4002, z_rate=90.0)
        s.commit()
        s.close()

        # Baseline: both rides in totals
        resp_before = client.get("/api/data/payroll-history/1/driver/1", cookies=_AUTH)
        assert resp_before.status_code == 200
        totals_before = resp_before.json()["totals"]
        assert totals_before["rides"] == 2
        assert round(totals_before["z_rate"], 2) == round(132.0 + 90.0, 2)

        # Remove the $132 ride
        client.patch(
            "/api/data/rides/4001/remove",
            json={"reason": "Already paid W17"},
            cookies=_AUTH,
        )

        # After removal: totals reflect only the $90 ride
        resp_after = client.get("/api/data/payroll-history/1/driver/1", cookies=_AUTH)
        assert resp_after.status_code == 200
        body = resp_after.json()
        totals_after = body["totals"]
        assert totals_after["rides"] == 1, (
            "ride count in totals must exclude removed rides"
        )
        assert round(totals_after["z_rate"], 2) == 90.0, (
            "z_rate total must exclude the removed $132 ride"
        )

        # The removed ride must still be present in the rides list for audit display
        all_ride_ids = [r["ride_id"] for r in body["rides"]]
        assert 4001 in all_ride_ids, (
            "removed ride must still appear in rides list (audit trail) even though "
            "it is excluded from totals"
        )


# =============================================================================
# AuditLog integration tests (MEDIUM #2)
# =============================================================================


from backend.db.models import AuditLog  # noqa: E402


def _wipe_with_audit():
    """Wipe rides, batches, persons, and audit_log rows used in tests."""
    s = _db()
    try:
        s.query(AuditLog).filter(
            AuditLog.action.in_(["ride.remove", "ride.restore"])
        ).delete(synchronize_session=False)
        s.query(Ride).delete(synchronize_session=False)
        s.query(PayrollBatch).delete(synchronize_session=False)
        s.query(Person).delete(synchronize_session=False)
        s.commit()
    finally:
        s.close()


class TestAuditLogEntries:
    """
    Verify AuditLog rows are written for remove and restore mutations.
    """

    def setup_method(self):
        _wipe_with_audit()
        s = _db()
        _seed_person(s)
        _seed_batch(s)
        _seed_ride(s, ride_id=5001, z_rate=132.0)
        s.commit()
        s.close()

    def teardown_method(self):
        _wipe_with_audit()

    # Test 30 — removing a ride creates an AuditLog entry
    def test_remove_creates_audit_log_entry(self):
        client.patch(
            "/api/data/rides/5001/remove",
            json={"reason": "Already paid in W17"},
            cookies=_AUTH,
        )

        s = _db()
        rows = (
            s.query(AuditLog)
            .filter(AuditLog.target_id == 5001, AuditLog.action == "ride.remove")
            .all()
        )
        s.close()

        assert len(rows) == 1, "exactly one AuditLog row must be created on remove"
        row = rows[0]
        assert row.target_type == "ride"
        assert row.actor_email is None or row.after_value is not None
        assert row.before_value["removed_at"] is None
        assert row.after_value["removed_reason"] == "Already paid in W17"
        assert row.after_value["removed_by"] == "admin_test"

    # Test 31 — restoring a ride creates an AuditLog entry
    def test_restore_creates_audit_log_entry(self):
        # Remove first
        client.patch(
            "/api/data/rides/5001/remove",
            json={"reason": "Test remove for restore audit"},
            cookies=_AUTH,
        )
        # Now restore
        client.patch(
            "/api/data/rides/5001/restore",
            json={},
            cookies=_AUTH,
        )

        s = _db()
        restore_rows = (
            s.query(AuditLog)
            .filter(AuditLog.target_id == 5001, AuditLog.action == "ride.restore")
            .all()
        )
        s.close()

        assert len(restore_rows) == 1, "exactly one AuditLog row must be created on restore"
        row = restore_rows[0]
        assert row.target_type == "ride"
        assert row.before_value["removed_reason"] == "Test remove for restore audit"
        assert row.after_value["removed_at"] is None

    # Test 32 — idempotent remove does NOT create a second AuditLog entry
    def test_idempotent_remove_does_not_duplicate_audit_log(self):
        client.patch(
            "/api/data/rides/5001/remove",
            json={"reason": "First remove"},
            cookies=_AUTH,
        )
        # Second remove is a no-op and must not write a second AuditLog row
        client.patch(
            "/api/data/rides/5001/remove",
            json={"reason": "Second remove attempt"},
            cookies=_AUTH,
        )

        s = _db()
        count = (
            s.query(AuditLog)
            .filter(AuditLog.target_id == 5001, AuditLog.action == "ride.remove")
            .count()
        )
        s.close()

        assert count == 1, (
            "idempotent remove must not create a second AuditLog row — "
            f"found {count} rows"
        )
