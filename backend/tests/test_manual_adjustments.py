"""
Tests for the manual pay-stub adjustments feature shipped 2026-04-28.

Endpoints under test:
  POST   /api/data/rides                       — create manual ride (free-form + route modes)
  DELETE /api/data/rides/{ride_id}             — delete manual ride only
  GET    /api/data/workflow/{batch_id}/routes  — route picker (active routes only)
  GET    /api/data/batches                     — batch list with include_locked filter
  GET    /api/data/routes/current              — must exclude source='manual' rides

DB strategy:
  We use an in-memory SQLite engine shared across all connections via StaticPool.
  Three patches to the production ORM metadata are applied before create_all:

    1.  ZRateOverride.effective_during  DATERANGE -> Text
        (PostgreSQL-only type, SQLite can't render it)

    2.  Ride.ride_id / any BigInteger PK -> Integer
        (SQLite autoincrement only works on INTEGER primary keys)

    3.  Columns with server_default=text("NOW()"):
        nullable set to True + server_default removed
        (SQLite doesn't have NOW(); the endpoint code doesn't set these columns
        explicitly, so we make them optional rather than faking a server function)

  FastAPI's dependency injection is used to override get_db so every request
  inside the TestClient uses our SQLite session.

Run:
    PYTHONPATH=/path/to/zpay-v2-fresh pytest backend/tests/test_manual_adjustments.py -v
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import re as _re
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import BigInteger, Column, Integer, Text, create_engine, event, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ── Project root on sys.path so backend.* imports resolve ────────────────────
_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Set ZPAY_SECRET_KEY before importing the app — auth middleware reads it at
# module import time via a cached singleton.
os.environ.setdefault(
    "ZPAY_SECRET_KEY",
    "test-secret-key-for-manual-adjustments-tests-long-enough",
)
os.environ.setdefault("DATABASE_URL", "sqlite://")  # silenced by get_db override

# Import production models so their __tablename__ registrations land in
# Base.metadata before we patch + call create_all.
from backend.db.models import Base, ZRateOverride  # noqa: E402  (import order intentional)

# ── Metadata patches — must happen before create_all ─────────────────────────

# Patch 1: DATERANGE is PostgreSQL-only — replace with Text for SQLite
Base.metadata.tables["z_rate_override"].c["effective_during"].type = Text()

# Patch 2: BigInteger PKs are not autoincrement-capable in SQLite; use Integer
for _tbl in Base.metadata.tables.values():
    for _col in _tbl.columns:
        if _col.primary_key and isinstance(_col.type, BigInteger):
            _col.type = Integer()

# Patch 3: Columns with server_default=text("NOW()") rely on a PostgreSQL
# function SQLite doesn't have. Make them nullable + remove server_default so
# SQLAlchemy doesn't try to RETURNING them and SQLite doesn't choke on NULL.
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

# ── Shared SQLite engine (StaticPool shares one in-memory DB across threads) ──

_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


def _sqlite_regexp_replace(value: str, pattern: str, repl: str, flags: str) -> str:
    """SQLite UDF that mimics PostgreSQL regexp_replace(string, pattern, replacement, flags).

    _pick_latest_service_row() in rates.py calls:
        regexp_replace(col, '\\s+', ' ', 'g')
    to normalize whitespace in service_name before comparison.
    Our test service names have no extra whitespace, so this is a no-op in practice,
    but the function must be registered so SQLite doesn't raise 'no such function'.

    SQLite UDF signature matches PostgreSQL: regexp_replace(string, pattern, replacement, flags).
    """
    if value is None:
        return ""
    if "g" in (flags or ""):
        return _re.sub(pattern or "", repl or "", str(value))
    return _re.sub(pattern or "", repl or "", str(value), count=1)


@event.listens_for(_engine, "connect")
def _register_sqlite_udfs(dbapi_conn, rec):
    """Register PostgreSQL-compatible UDFs on every new SQLite connection."""
    # regexp_replace(pattern, replacement, flags, value) — note SQLAlchemy arg order
    dbapi_conn.create_function("regexp_replace", 4, _sqlite_regexp_replace)


Base.metadata.create_all(_engine)

_SessionFactory = sessionmaker(bind=_engine, autoflush=False, autocommit=False)

# ── Import FastAPI app + dependencies after metadata patches ──────────────────

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402
from backend.db import get_db  # noqa: E402
from backend.db.models import (  # noqa: E402
    BatchCorrectionLog,
    PayrollBatch,
    Person,
    Ride,
    ZRateService,
)
from backend.middleware.auth import COOKIE_NAME, create_session  # noqa: E402


def _override_get_db():
    """FastAPI dependency override — all requests use the SQLite session."""
    db = _SessionFactory()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db

# ── Auth cookie (stateless session, no DB user FK required) ──────────────────

_SESSION_COOKIE = create_session(
    username="testadmin",
    display_name="Test Admin",
    color="#333",
    initials="TA",
    role="admin",
)

_AUTH = {COOKIE_NAME: _SESSION_COOKIE}

# ── TestClient ────────────────────────────────────────────────────────────────

client = TestClient(app, raise_server_exceptions=True)


# ── DB helpers ────────────────────────────────────────────────────────────────

def _db():
    """Return a fresh session; caller must .close() it."""
    return _SessionFactory()


def _wipe():
    """Delete all rows in FK-safe order to give each test a clean slate."""
    sess = _db()
    try:
        sess.query(BatchCorrectionLog).delete(synchronize_session=False)
        sess.query(Ride).delete(synchronize_session=False)
        sess.query(ZRateService).delete(synchronize_session=False)
        sess.query(PayrollBatch).delete(synchronize_session=False)
        sess.query(Person).delete(synchronize_session=False)
        sess.commit()
    finally:
        sess.close()


_NOW = datetime.now(timezone.utc)  # shared constant for seed helpers


def _seed_person(
    sess,
    person_id: int = 1,
    full_name: str = "Test Driver",
    paycheck_code: str | None = "1001",
    paycheck_code_maz: str | None = None,
) -> Person:
    p = Person(
        person_id=person_id,
        full_name=full_name,
        paycheck_code=paycheck_code,
        paycheck_code_maz=paycheck_code_maz,
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
    status: str = "uploaded",
    finalized_at=None,
    paychex_exported_at=None,
) -> PayrollBatch:
    b = PayrollBatch(
        payroll_batch_id=batch_id,
        source=source,
        company_name=company_name,
        batch_ref=f"W-test-{batch_id}",
        status=status,
        finalized_at=finalized_at,
        paychex_exported_at=paychex_exported_at,
        period_end=date(2026, 4, 21),
        currency="USD",
        uploaded_at=_NOW,
    )
    sess.add(b)
    sess.flush()
    return b


def _seed_service(
    sess,
    svc_id: int = 1,
    service_name: str = "Test Route",
    default_rate: float = 75.00,
    active: bool = True,
    source: str = "",
    company_name: str = "",
) -> ZRateService:
    svc = ZRateService(
        z_rate_service_id=svc_id,
        service_key=f"test-svc-{svc_id}",
        service_name=service_name,
        default_rate=Decimal(str(default_rate)),
        active=active,
        source=source,
        company_name=company_name,
        currency="USD",
        created_at=_NOW,
    )
    sess.add(svc)
    sess.flush()
    return svc


def _seed_ride(
    sess,
    ride_id: int,
    batch_id: int,
    person_id: int,
    source: str = "acumen",
    service_name: str = "Ella Baker 01_B",
    net_pay: float = 100.0,
    z_rate: float = 100.0,
    ride_start_ts: datetime | None = None,
) -> Ride:
    r = Ride(
        ride_id=ride_id,
        payroll_batch_id=batch_id,
        person_id=person_id,
        source=source,
        source_ref=f"auto-{ride_id}-{source}",
        service_name=service_name,
        net_pay=Decimal(str(net_pay)),
        z_rate=Decimal(str(z_rate)),
        gross_pay=Decimal(str(z_rate)),
        z_rate_source="service",
        miles=Decimal("10.000"),
        deduction=Decimal("0"),
        spiff=Decimal("0"),
        ride_start_ts=ride_start_ts,
    )
    sess.add(r)
    sess.flush()
    return r


def _post_freeform(
    batch_id: int = 1,
    person_id: int = 1,
    amount: float = 50.0,
    service_name: str = "Makeup Pay",
    reason: str = "missed shift",
    **extra,
):
    payload = {
        "person_id": person_id,
        "payroll_batch_id": batch_id,
        "date": "2026-04-21",
        "service_name": service_name,
        "driver_pay": amount,
        "reason": reason,
        "mode": "freeform",
        **extra,
    }
    return client.post("/api/data/rides", json=payload, cookies=_AUTH)


# ─────────────────────────────────────────────────────────────────────────────
# Free-form mode (Tests 1-5)
# ─────────────────────────────────────────────────────────────────────────────


class TestFreeformMode:
    def setup_method(self):
        _wipe()
        sess = _db()
        _seed_person(sess)
        _seed_batch(sess)
        sess.commit()
        sess.close()

    def teardown_method(self):
        _wipe()

    # Test 1 — core field invariants on a successful free-form POST
    def test_freeform_ride_row_invariants(self):
        resp = _post_freeform()
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ok"] is True
        ride_id = body["ride_id"]

        sess = _db()
        ride = sess.query(Ride).filter(Ride.ride_id == ride_id).first()
        sess.close()

        assert ride is not None
        assert ride.source == "manual"
        assert float(ride.net_pay) == 0.0, "Bug B fix: net_pay must be 0 for manuals"
        assert float(ride.z_rate) == 50.0
        assert float(ride.gross_pay) == 50.0
        assert float(ride.gross_pay) == float(ride.z_rate), (
            "gross_pay must equal z_rate (documented invariant from excell_reader.py:275)"
        )
        assert ride.z_rate_source == "manual"
        assert ride.service_ref_type == "manual"
        assert re.match(r"^manual-[0-9a-f]{12}$", ride.source_ref), (
            f"source_ref must match manual-{{12hex}}, got: {ride.source_ref!r}"
        )

    # Test 2 — BatchCorrectionLog entry written with correct JSON shape
    def test_freeform_writes_audit_log(self):
        resp = _post_freeform()
        assert resp.status_code == 200, resp.text
        ride_id = resp.json()["ride_id"]

        sess = _db()
        log = (
            sess.query(BatchCorrectionLog)
            .filter(
                BatchCorrectionLog.batch_id == 1,
                BatchCorrectionLog.field == "manual_ride",
            )
            .first()
        )
        sess.close()

        assert log is not None, "BatchCorrectionLog row must be written (Bug D fix)"
        assert log.field == "manual_ride"
        parsed = json.loads(log.new_value)
        assert parsed["ride_id"] == ride_id
        assert parsed["mode"] == "freeform"
        assert "service_name" in parsed
        assert "z_rate" in parsed

    # Test 3 — amount = 0 is rejected with 400
    def test_freeform_amount_zero_returns_400(self):
        resp = _post_freeform(amount=0)
        assert resp.status_code == 400, resp.text

    # Test 4 — negative amount is rejected with 400
    def test_freeform_amount_negative_returns_400(self):
        resp = _post_freeform(amount=-50)
        assert resp.status_code == 400, resp.text

    # Test 5 — reason > 200 chars is rejected with 400 (Refinement G)
    def test_freeform_reason_too_long_returns_400(self):
        resp = _post_freeform(reason="x" * 201)
        assert resp.status_code == 400, resp.text


# ─────────────────────────────────────────────────────────────────────────────
# Route mode (Tests 6-10)
# ─────────────────────────────────────────────────────────────────────────────


class TestRouteMode:
    """Tests 6-10: route-mode behavior for the manual ride endpoint.

    The route-mode code path calls resolve_rate_for_ride() which internally
    queries ZRateOverride using the PostgreSQL @> (DATERANGE containment)
    operator. The workflow/{batch_id}/routes endpoint uses a LATERAL JOIN —
    also PostgreSQL-only. Both constructs fail on SQLite.

    Tests 6-9 patch resolve_rate_for_ride at the import site used by api_data.py
    so the endpoint logic can run without the Postgres-specific ORM query.
    Test 10 is verified via source-text inspection of the SQL WHERE clause.

    This matches the established pattern in test_ingest_guards.py for invariants
    that are easier to assert via code analysis than live DB execution.
    """

    def setup_method(self):
        _wipe()
        sess = _db()
        _seed_person(sess)
        _seed_batch(sess)
        sess.commit()
        sess.close()

    def teardown_method(self):
        _wipe()

    def _post_route_patched(
        self,
        svc_id: int,
        resolved_rate: float,
        override_rate=None,
    ):
        """POST a route-mode ride with resolve_rate_for_ride patched to return resolved_rate."""
        svc_id_int = int(svc_id)
        patch_target = "backend.services.rates.resolve_rate_for_ride"
        mock_return = (Decimal(str(resolved_rate)), "service", svc_id_int, None)
        payload = {
            "person_id": 1,
            "payroll_batch_id": 1,
            "date": "2026-04-21",
            "z_rate_service_id": svc_id,
            "reason": "route-mode test",
            "mode": "route",
        }
        if override_rate is not None:
            payload["override_rate"] = override_rate
        with patch(patch_target, return_value=mock_return):
            return client.post("/api/data/rides", json=payload, cookies=_AUTH)

    # Test 6 — route mode stores z_rate from resolved service rate and sets correct fields
    def test_route_mode_resolves_rate_from_service(self):
        sess = _db()
        _seed_service(sess, svc_id=10, service_name="Redmond AM", default_rate=75.00)
        sess.commit()
        sess.close()

        resp = self._post_route_patched(svc_id=10, resolved_rate=75.00)
        assert resp.status_code == 200, resp.text
        ride_id = resp.json()["ride_id"]

        sess = _db()
        ride = sess.query(Ride).filter(Ride.ride_id == ride_id).first()
        log = (
            sess.query(BatchCorrectionLog)
            .filter(BatchCorrectionLog.field == "manual_ride")
            .first()
        )
        sess.close()

        assert float(ride.z_rate) == 75.00
        assert ride.z_rate_service_id == 10
        assert ride.service_name == "Redmond AM", (
            "service_name must come from ZRateService row, not operator input"
        )
        parsed = json.loads(log.new_value)
        assert parsed["mode"] == "route"

    # Test 7 — override_rate wins; audit log captures both default and override
    def test_route_mode_override_rate_wins(self):
        sess = _db()
        _seed_service(sess, svc_id=11, service_name="Timberline", default_rate=90.00)
        sess.commit()
        sess.close()

        resp = self._post_route_patched(svc_id=11, resolved_rate=90.00, override_rate=120)
        assert resp.status_code == 200, resp.text
        ride_id = resp.json()["ride_id"]

        sess = _db()
        ride = sess.query(Ride).filter(Ride.ride_id == ride_id).first()
        log = (
            sess.query(BatchCorrectionLog)
            .filter(BatchCorrectionLog.field == "manual_ride")
            .first()
        )
        sess.close()

        assert float(ride.z_rate) == 120.0, "override_rate must win over resolved default_rate"
        parsed = json.loads(log.new_value)
        assert "default_rate" in parsed, "audit log must record default_rate"
        assert "override_rate" in parsed, "audit log must record override_rate"
        assert parsed["default_rate"] == 90.0
        assert parsed["override_rate"] == 120.0

    # Test 8 — resolved rate = 0 with no override is rejected with 400 (Refinement C)
    def test_route_mode_zero_rate_no_override_returns_400(self):
        sess = _db()
        _seed_service(sess, svc_id=12, service_name="Unconfigured Route", default_rate=0.00)
        sess.commit()
        sess.close()

        resp = self._post_route_patched(svc_id=12, resolved_rate=0.00)
        assert resp.status_code == 400, resp.text
        assert "rate" in resp.json().get("error", "").lower()

    # Test 9 — zero resolved rate WITH override_rate supplied succeeds (Refinement C)
    def test_route_mode_zero_rate_with_override_succeeds(self):
        sess = _db()
        _seed_service(sess, svc_id=13, service_name="Zero Rate Route", default_rate=0.00)
        sess.commit()
        sess.close()

        resp = self._post_route_patched(svc_id=13, resolved_rate=0.00, override_rate=50)
        assert resp.status_code == 200, resp.text

        sess = _db()
        ride = sess.query(Ride).filter(Ride.ride_id == resp.json()["ride_id"]).first()
        sess.close()
        assert float(ride.z_rate) == 50.0

    # Test 10 — inactive routes excluded from route picker (Refinement B)
    #
    # The workflow/{batch_id}/routes endpoint uses LATERAL JOIN (Postgres-only).
    # We verify the filter via source-text inspection of the WHERE clause.
    def test_inactive_service_excluded_from_route_picker(self):
        backend_dir = Path(__file__).resolve().parents[1]
        src = (backend_dir / "routes" / "workflow.py").read_text(encoding="utf-8")

        fn_start = src.find("def workflow_batch_routes(")
        assert fn_start != -1, "workflow_batch_routes must be defined in workflow.py"
        fn_body = src[fn_start : fn_start + 4000]

        has_active_filter = (
            "active = TRUE" in fn_body
            or "active = true" in fn_body
            or "svc.active" in fn_body
        )
        assert has_active_filter, (
            "workflow_batch_routes SQL must filter WHERE svc.active = TRUE "
            "so inactive/retired routes are excluded from the route picker (Refinement B)"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Lock check — three gates (Tests 11-14)
# ─────────────────────────────────────────────────────────────────────────────


class TestLockCheck:
    """All three batch-lock gates must block both POST and DELETE (Refinement A)."""

    def setup_method(self):
        _wipe()
        sess = _db()
        _seed_person(sess)
        sess.commit()
        sess.close()

    def teardown_method(self):
        _wipe()

    # Test 11 — status='complete' blocks POST
    def test_status_complete_blocks_post(self):
        sess = _db()
        _seed_batch(sess, batch_id=20, status="complete")
        sess.commit()
        sess.close()

        resp = _post_freeform(batch_id=20)
        assert resp.status_code == 409, resp.text

    # Test 12 — finalized_at set blocks POST (Refinement A)
    def test_finalized_at_blocks_post(self):
        sess = _db()
        _seed_batch(sess, batch_id=21, finalized_at=datetime.now(timezone.utc))
        sess.commit()
        sess.close()

        resp = _post_freeform(batch_id=21)
        assert resp.status_code == 409, resp.text

    # Test 13 — paychex_exported_at set blocks POST
    def test_paychex_exported_at_blocks_post(self):
        sess = _db()
        _seed_batch(sess, batch_id=22, paychex_exported_at=datetime.now(timezone.utc))
        sess.commit()
        sess.close()

        resp = _post_freeform(batch_id=22)
        assert resp.status_code == 409, resp.text

    # Test 14 — all three lock gates block DELETE
    def test_all_lock_states_block_delete(self):
        now = datetime.now(timezone.utc)
        scenarios = [
            (30, {"status": "complete"}),
            (31, {"finalized_at": now}),
            (32, {"paychex_exported_at": now}),
        ]
        for batch_id, lock_kwargs in scenarios:
            sess = _db()
            _seed_batch(sess, batch_id=batch_id, **lock_kwargs)
            # Seed manual ride directly — can't use endpoint since batch is locked
            r = Ride(
                payroll_batch_id=batch_id,
                person_id=1,
                source="manual",
                source_ref=f"manual-deadbeef{batch_id:04d}",
                z_rate=Decimal("50"),
                z_rate_source="manual",
                gross_pay=Decimal("50"),
                net_pay=Decimal("0"),
                miles=Decimal("0"),
                deduction=Decimal("0"),
                spiff=Decimal("0"),
            )
            sess.add(r)
            sess.commit()
            ride_id = r.ride_id
            sess.close()

            # DELETE must include Accept: application/json so the CSRF middleware
            # takes the JSON-API exemption path (same as POST requests).
            resp = client.delete(
                f"/api/data/rides/{ride_id}",
                cookies=_AUTH,
                headers={"Accept": "application/json"},
            )
            assert resp.status_code == 409, (
                f"Expected 409 for lock config {lock_kwargs}, "
                f"got {resp.status_code}: {resp.text}"
            )

            # clean up between iterations
            sess = _db()
            sess.query(BatchCorrectionLog).filter(
                BatchCorrectionLog.batch_id == batch_id
            ).delete(synchronize_session=False)
            sess.query(Ride).filter(Ride.ride_id == ride_id).delete(synchronize_session=False)
            sess.query(PayrollBatch).filter(
                PayrollBatch.payroll_batch_id == batch_id
            ).delete(synchronize_session=False)
            sess.commit()
            sess.close()


# ─────────────────────────────────────────────────────────────────────────────
# DELETE endpoint (Tests 15-16)
# ─────────────────────────────────────────────────────────────────────────────


class TestDeleteEndpoint:
    def setup_method(self):
        _wipe()
        sess = _db()
        _seed_person(sess)
        _seed_batch(sess)
        sess.commit()
        sess.close()

    def teardown_method(self):
        _wipe()

    # Test 15 — POST then DELETE: ride gone, audit row written
    def test_post_then_delete_removes_ride_and_writes_audit(self):
        resp = _post_freeform()
        assert resp.status_code == 200, resp.text
        ride_id = resp.json()["ride_id"]

        # DELETE must include Accept: application/json so the CSRF middleware
        # exempts it (same exemption path as POST — JSON API requests are
        # CORS-protected, not CSRF-token-protected).
        del_resp = client.delete(
            f"/api/data/rides/{ride_id}",
            cookies=_AUTH,
            headers={"Accept": "application/json"},
        )
        assert del_resp.status_code == 200, del_resp.text
        assert del_resp.json()["ok"] is True

        sess = _db()
        ride = sess.query(Ride).filter(Ride.ride_id == ride_id).first()
        log = (
            sess.query(BatchCorrectionLog)
            .filter(BatchCorrectionLog.field == "manual_ride_deleted")
            .first()
        )
        sess.close()

        assert ride is None, "Deleted ride must not be present in the database"
        assert log is not None, "BatchCorrectionLog 'manual_ride_deleted' row must be written"

    # Test 16 — DELETE a real (non-manual) ride → 403
    def test_delete_real_ride_returns_403(self):
        sess = _db()
        _seed_ride(sess, ride_id=9001, batch_id=1, person_id=1, source="acumen")
        sess.commit()
        sess.close()

        resp = client.delete(
            "/api/data/rides/9001",
            cookies=_AUTH,
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 403, resp.text


# ─────────────────────────────────────────────────────────────────────────────
# Routes-current filter — Risk #6 mitigation (Test 17)
# ─────────────────────────────────────────────────────────────────────────────


class TestRoutesCurrentFilter:
    """Test 17: /api/data/routes/current must not return manual-source rides.

    The endpoint uses DISTINCT ON (r.service_name) ORDER BY ride_start_ts DESC
    to find the most-recent driver per route. Without the source filter, a
    manual ride with a later timestamp would win and expose the wrong driver.

    Note: the endpoint's SQL uses PostgreSQL-specific DISTINCT ON syntax which
    SQLite does not support. The live endpoint cannot run against the in-memory
    SQLite test DB. We verify the filter via source-text inspection — confirming
    the WHERE clause contains 'source != \'manual\'' — and treat this as a
    regression guard for the Risk #6 fix.
    """

    # Test 17 — /routes/current SQL contains the source != 'manual' filter
    def test_routes_current_sql_excludes_manual_source(self):
        backend_dir = Path(__file__).resolve().parents[1]
        src = (backend_dir / "routes" / "api_data.py").read_text(encoding="utf-8")

        # Find api_routes_current function body
        fn_start = src.find("def api_routes_current(")
        assert fn_start != -1, "api_routes_current must be defined in api_data.py"
        fn_body = src[fn_start : fn_start + 3000]

        # The SQL WHERE clause must filter out manual-source rides
        has_filter = (
            "source != 'manual'" in fn_body
            or 'source != "manual"' in fn_body
            or "source <> 'manual'" in fn_body
        )
        assert has_filter, (
            "api_routes_current SQL must contain WHERE r.source != 'manual' "
            "to prevent manual rides from winning DISTINCT ON and misleading dispatch planning (Risk #6)"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Paychex code warning — Risk #12 mitigation (Tests 18-19)
# ─────────────────────────────────────────────────────────────────────────────


class TestPaychexCodeWarning:
    def setup_method(self):
        _wipe()

    def teardown_method(self):
        _wipe()

    # Test 18 — driver with no Paychex code → response.warning is non-empty
    def test_missing_paychex_code_produces_warning(self):
        sess = _db()
        _seed_person(
            sess,
            person_id=1,
            full_name="No Code Driver",
            paycheck_code=None,
            paycheck_code_maz=None,
        )
        _seed_batch(sess, batch_id=1, source="acumen", company_name="FirstAlt")
        sess.commit()
        sess.close()

        resp = _post_freeform()
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "warning" in body and body["warning"], (
            "Response must include a non-empty 'warning' when driver lacks Paychex code"
        )
        warn_lower = body["warning"].lower()
        assert "paychex" in warn_lower or "worker id" in warn_lower, (
            f"Warning must mention Paychex/Worker ID. Got: {body['warning']!r}"
        )

    # Test 19 — Maz driver with paycheck_code_maz → no warning for a Maz batch
    def test_maz_driver_with_code_maz_no_warning(self):
        sess = _db()
        _seed_person(
            sess,
            person_id=2,
            full_name="Maz Driver",
            paycheck_code=None,
            paycheck_code_maz="MAZ-99",
        )
        _seed_batch(sess, batch_id=2, source="maz", company_name="Maz Services")
        sess.commit()
        sess.close()

        resp = _post_freeform(batch_id=2, person_id=2)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert not body.get("warning"), (
            "No warning expected when driver has paycheck_code_maz for a Maz batch. "
            f"Got: {body.get('warning')!r}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Batches list endpoint (Tests 20-21)
# ─────────────────────────────────────────────────────────────────────────────


class TestBatchesList:
    def setup_method(self):
        _wipe()

    def teardown_method(self):
        _wipe()

    # Test 20 — default (include_locked=false) returns only open batch
    def test_default_excludes_locked_batches(self):
        now = datetime.now(timezone.utc)
        sess = _db()
        _seed_batch(sess, batch_id=101, status="uploaded")
        _seed_batch(sess, batch_id=102, finalized_at=now)
        _seed_batch(sess, batch_id=103, paychex_exported_at=now)
        _seed_batch(sess, batch_id=104, status="complete")
        sess.commit()
        sess.close()

        resp = client.get("/api/data/batches", cookies=_AUTH)
        assert resp.status_code == 200, resp.text
        ids = {b["payroll_batch_id"] for b in resp.json()}

        assert 101 in ids, "Open batch must be included"
        assert 102 not in ids, "Finalized batch must be excluded"
        assert 103 not in ids, "Exported batch must be excluded"
        assert 104 not in ids, "Complete batch must be excluded"

    # Test 21 — include_locked=true returns all batches
    def test_include_locked_returns_all_batches(self):
        now = datetime.now(timezone.utc)
        sess = _db()
        _seed_batch(sess, batch_id=201, status="uploaded")
        _seed_batch(sess, batch_id=202, finalized_at=now)
        _seed_batch(sess, batch_id=203, paychex_exported_at=now)
        sess.commit()
        sess.close()

        resp = client.get("/api/data/batches?include_locked=true", cookies=_AUTH)
        assert resp.status_code == 200, resp.text
        ids = {b["payroll_batch_id"] for b in resp.json()}

        assert 201 in ids
        assert 202 in ids
        assert 203 in ids


# ─────────────────────────────────────────────────────────────────────────────
# Workflow warnings — manuals excluded from late-cancel detection (Test 22)
# ─────────────────────────────────────────────────────────────────────────────


class TestWorkflowWarningsManualExclusion:
    """Test 22: manual rides must not trigger false late-cancellation warnings.

    workflow_payroll_preview filters late-cancel rides by:
        Ride.source == 'maz' AND Ride.net_pay > 0

    After Bug A fix: manuals have source='manual' → excluded by source check.
    After Bug B fix: manuals have net_pay=0 → excluded by net_pay check.
    Both conditions independently protect against false positives.

    Note: workflow_payroll_preview internally calls _build_summary which queries
    payroll_withheld_override and payroll_manual_withhold tables that are not
    in the ORM models (they are raw SQL tables from an older migration). Testing
    the live endpoint would require creating those tables as SQL fixtures.
    We verify the guard via source-text inspection — matching the pattern
    established in test_ingest_guards.py for invariants that are easier to
    assert via code analysis than live execution.
    """

    def test_late_cancel_filter_gates_on_maz_source_and_positive_net_pay(self):
        """workflow.py late-cancel detection must gate on source='maz' and net_pay>0."""
        backend_dir = Path(__file__).resolve().parents[1]
        src = (backend_dir / "routes" / "workflow.py").read_text(encoding="utf-8")

        # Isolate the workflow_payroll_preview function body (first 8 KB is sufficient)
        fn_start = src.find("def workflow_payroll_preview(")
        assert fn_start != -1, "workflow_payroll_preview must be defined in workflow.py"
        fn_body = src[fn_start : fn_start + 12000]

        # Must gate on source == 'maz' so manuals (source='manual') are excluded
        has_source_filter = (
            'Ride.source == "maz"' in fn_body or "source == 'maz'" in fn_body
        )
        assert has_source_filter, (
            "Late-cancel filter must compare Ride.source == 'maz' "
            "so manuals with source='manual' are excluded (Bug A fix regression check)"
        )

        # Must gate on net_pay > 0 so manuals (net_pay=0 after Bug B fix) are excluded
        has_net_pay_filter = "Ride.net_pay > 0" in fn_body or "net_pay > 0" in fn_body
        assert has_net_pay_filter, (
            "Late-cancel filter must require Ride.net_pay > 0 "
            "so manuals with net_pay=0 are excluded (Bug B fix regression check)"
        )
