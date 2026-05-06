"""
Happy-path tests for the POST /api/data/workflow/{batch_id}/settle-external/{person_id}
endpoint introduced in the "paid externally" disposition feature.

DB strategy: same in-memory SQLite + StaticPool pattern used across the test suite.
Run:
    PYTHONPATH=/path/to/zpay-v2-fresh pytest backend/tests/test_settle_external.py -v
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import BigInteger, Column, Integer, Text, create_engine, event, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ── Project root ──────────────────────────────────────────────────────────────
_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault(
    "ZPAY_SECRET_KEY",
    "test-secret-settle-external-long-enough-to-pass",
)
os.environ.setdefault("DATABASE_URL", "sqlite://")

from backend.db.models import Base, ZRateOverride  # noqa: E402

# ── Metadata patches (same as other test files) ───────────────────────────────
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

# Also patch the Boolean default for settled_externally (FALSE is postgres default)
for _tbl in Base.metadata.tables.values():
    for _col in _tbl.columns:
        if _col.server_default is not None:
            _sd = _col.server_default
            try:
                _arg = _sd.arg.text if hasattr(_sd, "arg") and hasattr(_sd.arg, "text") else ""
            except Exception:
                _arg = ""
            if "FALSE" in _arg:
                _col.nullable = True
                _col.server_default = None

_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

Base.metadata.create_all(_engine)
_SessionFactory = sessionmaker(bind=_engine, autoflush=False, autocommit=False)

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402
from backend.db import get_db  # noqa: E402
from backend.db.models import (  # noqa: E402
    BatchCorrectionLog,
    DriverBalance,
    PayrollBatch,
    Person,
)
from backend.middleware.auth import COOKIE_NAME, create_session  # noqa: E402


def _override_get_db():
    db = _SessionFactory()
    try:
        yield db
    finally:
        db.close()


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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _db():
    return _SessionFactory()


def _wipe():
    sess = _db()
    try:
        sess.query(BatchCorrectionLog).delete(synchronize_session=False)
        sess.query(DriverBalance).delete(synchronize_session=False)
        sess.query(PayrollBatch).delete(synchronize_session=False)
        sess.query(Person).delete(synchronize_session=False)
        sess.commit()
    finally:
        sess.close()


def _seed(
    person_id: int = 321,
    batch_id: int = 87,
    carried_over: float = 160.00,
    person_name: str = "Mostafa Test",
):
    sess = _db()
    try:
        p = Person(
            person_id=person_id,
            full_name=person_name,
            paycheck_code="9999",
            active=True,
            status="active",
        )
        sess.add(p)
        b = PayrollBatch(
            payroll_batch_id=batch_id,
            source="acumen",
            company_name="FirstAlt",
            batch_ref=f"W-test-{batch_id}",
            status="finalized",
            period_start=date(2026, 5, 6),
            period_end=date(2026, 5, 6),
        )
        sess.add(b)
        if carried_over > 0:
            bal = DriverBalance(
                person_id=person_id,
                payroll_batch_id=batch_id,
                carried_over=carried_over,
            )
            sess.add(bal)
        sess.commit()
    finally:
        sess.close()


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestSettleExternal:

    def setup_method(self):
        _wipe()

    def test_settle_zelle_creates_row_and_zeroes_carried_over(self):
        """Happy path: settle via Zelle, carried_over should become 0."""
        _seed(person_id=321, batch_id=87, carried_over=160.00)

        resp = client.post(
            "/api/data/workflow/87/settle-external/321",
            json={"method": "zelle", "amount": 160.00, "note": "paid by mom"},
            cookies=_AUTH,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["ok"] is True
        assert data["settled_externally"] is True
        assert data["external_method"] == "zelle"
        assert data["external_amount"] == 160.00

        sess = _db()
        try:
            bal = sess.query(DriverBalance).filter(
                DriverBalance.person_id == 321,
                DriverBalance.payroll_batch_id == 87,
            ).first()
            assert bal is not None
            assert bal.settled_externally is True
            assert float(bal.carried_over) == 0.0
            assert bal.external_method == "zelle"
            assert float(bal.external_amount) == 160.00
            assert bal.external_note == "paid by mom"
        finally:
            sess.close()

    def test_settle_creates_row_when_no_existing_balance(self):
        """settle-external should upsert even if no DriverBalance row exists yet."""
        _seed(person_id=321, batch_id=87, carried_over=0)  # no balance row created

        resp = client.post(
            "/api/data/workflow/87/settle-external/321",
            json={"method": "cash", "amount": 58.00, "note": ""},
            cookies=_AUTH,
        )
        assert resp.status_code == 200, resp.text

        sess = _db()
        try:
            bal = sess.query(DriverBalance).filter(
                DriverBalance.person_id == 321,
                DriverBalance.payroll_batch_id == 87,
            ).first()
            assert bal is not None
            assert bal.settled_externally is True
            assert bal.external_method == "cash"
            assert float(bal.external_amount) == 58.00
        finally:
            sess.close()

    def test_settle_retained_method(self):
        """retained method works the same as zelle/cash."""
        _seed(person_id=293, batch_id=87, carried_over=58.00, person_name="Eyakem Test")

        resp = client.post(
            "/api/data/workflow/87/settle-external/293",
            json={"method": "retained", "amount": 58.00, "note": "retained by company"},
            cookies=_AUTH,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["external_method"] == "retained"

    def test_invalid_method_returns_422(self):
        """Unknown method should return 422."""
        _seed(person_id=321, batch_id=87, carried_over=100.00)

        resp = client.post(
            "/api/data/workflow/87/settle-external/321",
            json={"method": "venmo", "amount": 100.00},
            cookies=_AUTH,
        )
        assert resp.status_code == 422

    def test_missing_batch_returns_404(self):
        """Non-existent batch_id should return 404."""
        _seed(person_id=321, batch_id=87, carried_over=100.00)

        resp = client.post(
            "/api/data/workflow/9999/settle-external/321",
            json={"method": "zelle", "amount": 100.00},
            cookies=_AUTH,
        )
        assert resp.status_code == 404

    def test_missing_person_returns_404(self):
        """Non-existent person_id should return 404."""
        _seed(person_id=321, batch_id=87, carried_over=100.00)

        resp = client.post(
            "/api/data/workflow/87/settle-external/9999",
            json={"method": "zelle", "amount": 100.00},
            cookies=_AUTH,
        )
        assert resp.status_code == 404

    def test_audit_log_entry_created(self):
        """A BatchCorrectionLog row should be inserted on settle."""
        _seed(person_id=321, batch_id=87, carried_over=160.00)

        resp = client.post(
            "/api/data/workflow/87/settle-external/321",
            json={"method": "zelle", "amount": 160.00, "note": "audit test"},
            cookies=_AUTH,
        )
        assert resp.status_code == 200

        sess = _db()
        try:
            log = sess.query(BatchCorrectionLog).filter(
                BatchCorrectionLog.batch_id == 87,
                BatchCorrectionLog.person_id == 321,
                BatchCorrectionLog.field == "settled_externally",
            ).first()
            assert log is not None
            assert "zelle" in (log.new_value or "")
        finally:
            sess.close()

    def test_idempotent_second_call_updates_fields(self):
        """Calling settle-external twice should update, not error."""
        _seed(person_id=321, batch_id=87, carried_over=160.00)

        client.post(
            "/api/data/workflow/87/settle-external/321",
            json={"method": "zelle", "amount": 160.00},
            cookies=_AUTH,
        )
        resp2 = client.post(
            "/api/data/workflow/87/settle-external/321",
            json={"method": "cash", "amount": 160.00, "note": "correction"},
            cookies=_AUTH,
        )
        assert resp2.status_code == 200
        assert resp2.json()["external_method"] == "cash"
