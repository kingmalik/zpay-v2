"""
Tests for the "Permanent adjustment carries forward" bug fix (2026-09-26).

Bug (operator report, 2026-09-23): on a driver's paystub page, a manual
payment/adjustment marked "Permanent" did not reappear on the next week's
payroll batch — it was a single `ride` row scoped to one batch, and nothing
in the schema recorded "permanent" at all.

Fix under test:
  - POST /api/data/rides accepts `permanent: true` and creates a
    RecurringAdjustment template row alongside the concrete ride.
  - backend/services/recurring_adjustments.apply_recurring_adjustments_to_batch
    (called by services/excell_reader.py and services/pdf_reader.py at the
    end of every batch import) re-materializes every active template
    matching the new batch's `source` into a fresh ride on that batch.
  - DELETE /api/data/rides/{id} deactivates (active=False, never hard-deleted)
    the template when the deleted ride came from one, so it stops
    re-applying to future batches.
  - A one-time adjustment (permanent=false, the default) never gets a
    template and never appears on any batch but the one it was created on.

DB strategy matches test_manual_adjustments.py (in-memory SQLite via
StaticPool + the same production-metadata patches).

Run:
    PYTHONPATH=/path/to/zpay-v2-fresh pytest backend/tests/test_recurring_adjustments.py -v
"""
from __future__ import annotations

import os
import re as _re
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import BigInteger, Integer, Text, create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ── Project root on sys.path so backend.* imports resolve ────────────────────
_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault(
    "ZPAY_SECRET_KEY",
    "test-secret-key-for-recurring-adjustments-tests-long-enough",
)
os.environ.setdefault("DATABASE_URL", "sqlite://")

from backend.db.models import Base, ZRateOverride  # noqa: E402

# ── Metadata patches — identical to test_manual_adjustments.py ───────────────

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
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


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

_SessionFactory = sessionmaker(bind=_engine, autoflush=False, autocommit=False)

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402
from backend.db import get_db  # noqa: E402
from backend.db.models import (  # noqa: E402
    BatchCorrectionLog,
    PayrollBatch,
    Person,
    RecurringAdjustment,
    Ride,
)
from backend.middleware.auth import COOKIE_NAME, create_session  # noqa: E402
from backend.services.recurring_adjustments import (  # noqa: E402
    apply_recurring_adjustments_to_batch,
)


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


def _db():
    return _SessionFactory()


def _wipe():
    sess = _db()
    try:
        sess.query(BatchCorrectionLog).delete(synchronize_session=False)
        sess.query(Ride).delete(synchronize_session=False)
        sess.query(RecurringAdjustment).delete(synchronize_session=False)
        sess.query(PayrollBatch).delete(synchronize_session=False)
        sess.query(Person).delete(synchronize_session=False)
        sess.commit()
    finally:
        sess.close()


def _seed_person(sess, person_id: int = 1, full_name: str = "Test Driver") -> Person:
    p = Person(
        person_id=person_id,
        full_name=full_name,
        paycheck_code="1001",
        active=True,
        status="active",
        created_at=_NOW,
    )
    sess.add(p)
    sess.flush()
    return p


def _seed_batch(
    sess,
    batch_id: int,
    source: str = "acumen",
    company_name: str = "FirstAlt",
    period_end=date(2026, 9, 20),
) -> PayrollBatch:
    b = PayrollBatch(
        payroll_batch_id=batch_id,
        source=source,
        company_name=company_name,
        batch_ref=f"W-test-{batch_id}",
        status="uploaded",
        period_start=period_end,
        period_end=period_end,
        currency="USD",
        uploaded_at=_NOW,
    )
    sess.add(b)
    sess.flush()
    return b


def _post_freeform(
    batch_id: int,
    person_id: int = 1,
    amount: float = 50.0,
    service_name: str = "Makeup Pay",
    reason: str = "recurring loan repayment",
    permanent: bool = False,
    **extra,
):
    payload = {
        "person_id": person_id,
        "payroll_batch_id": batch_id,
        "date": "2026-09-20",
        "service_name": service_name,
        "driver_pay": amount,
        "reason": reason,
        "mode": "freeform",
        "permanent": permanent,
        **extra,
    }
    return client.post("/api/data/rides", json=payload, cookies=_AUTH)


class TestPermanentAdjustmentCarriesForward:
    def setup_method(self):
        _wipe()
        sess = _db()
        _seed_person(sess)
        _seed_batch(sess, batch_id=1)
        sess.commit()
        sess.close()

    def teardown_method(self):
        _wipe()

    def test_permanent_adjustment_applies_to_next_batch_with_same_amount(self):
        """The core regression: create a permanent adjustment on batch N,
        generate batch N+1, it must appear with the same amount."""
        r = _post_freeform(batch_id=1, amount=-40.0, service_name="Weekly loan repayment", permanent=True)
        assert r.status_code == 200, r.text
        assert r.json()["permanent"] is True

        sess = _db()
        try:
            batch2 = _seed_batch(sess, batch_id=2)
            applied = apply_recurring_adjustments_to_batch(sess, batch2)
            sess.commit()
            assert applied == 1

            rides_b2 = sess.query(Ride).filter(Ride.payroll_batch_id == 2).all()
            assert len(rides_b2) == 1
            assert rides_b2[0].service_name == "Weekly loan repayment"
            assert float(rides_b2[0].z_rate) == -40.0
            assert rides_b2[0].recurring_adjustment_id is not None
            assert rides_b2[0].z_rate_source == "manual_recurring"

            # Audit trail for the auto-applied ride
            log = (
                sess.query(BatchCorrectionLog)
                .filter(
                    BatchCorrectionLog.batch_id == 2,
                    BatchCorrectionLog.field == "manual_ride_recurring_applied",
                )
                .first()
            )
            assert log is not None
        finally:
            sess.close()

    def test_one_time_adjustment_does_not_carry_forward(self):
        r = _post_freeform(batch_id=1, amount=25.0, service_name="One-off bonus", permanent=False)
        assert r.status_code == 200, r.text
        assert r.json()["permanent"] is False

        sess = _db()
        try:
            batch2 = _seed_batch(sess, batch_id=2)
            applied = apply_recurring_adjustments_to_batch(sess, batch2)
            sess.commit()
            assert applied == 0
            assert sess.query(Ride).filter(Ride.payroll_batch_id == 2).count() == 0
            # And no RecurringAdjustment template exists for it at all
            assert sess.query(RecurringAdjustment).count() == 0
        finally:
            sess.close()

    def test_applies_across_three_consecutive_batches(self):
        _post_freeform(batch_id=1, amount=15.0, service_name="Standing bonus", permanent=True)

        sess = _db()
        try:
            for bid in (2, 3):
                batch = _seed_batch(sess, batch_id=bid)
                applied = apply_recurring_adjustments_to_batch(sess, batch)
                sess.commit()
                assert applied == 1

            for bid in (1, 2, 3):
                rides = sess.query(Ride).filter(Ride.payroll_batch_id == bid).all()
                assert len(rides) == 1
                assert float(rides[0].z_rate) == 15.0
        finally:
            sess.close()

    def test_is_idempotent_when_called_twice_on_the_same_batch(self):
        _post_freeform(batch_id=1, amount=10.0, service_name="Standing bonus", permanent=True)

        sess = _db()
        try:
            batch2 = _seed_batch(sess, batch_id=2)
            first = apply_recurring_adjustments_to_batch(sess, batch2)
            sess.commit()
            second = apply_recurring_adjustments_to_batch(sess, batch2)
            sess.commit()
            assert first == 1
            assert second == 0
            assert sess.query(Ride).filter(Ride.payroll_batch_id == 2).count() == 1
        finally:
            sess.close()

    def test_only_applies_to_batches_with_matching_source(self):
        _post_freeform(batch_id=1, amount=10.0, service_name="Standing bonus", permanent=True)

        sess = _db()
        try:
            maz_batch = _seed_batch(sess, batch_id=2, source="maz", company_name="EverDriven")
            applied = apply_recurring_adjustments_to_batch(sess, maz_batch)
            sess.commit()
            assert applied == 0
            assert sess.query(Ride).filter(Ride.payroll_batch_id == 2).count() == 0
        finally:
            sess.close()

    def test_deleting_the_adjustment_deactivates_it_and_it_stops_applying(self):
        r = _post_freeform(batch_id=1, amount=10.0, service_name="Standing bonus", permanent=True)
        ride_id = r.json()["ride_id"]

        del_resp = client.delete(
            f"/api/data/rides/{ride_id}", cookies=_AUTH, headers={"Accept": "application/json"},
        )
        assert del_resp.status_code == 200, del_resp.text
        assert del_resp.json()["recurring_adjustment_stopped"] is True

        sess = _db()
        try:
            template = sess.query(RecurringAdjustment).first()
            assert template is not None
            assert template.active is False
            assert template.deactivated_at is not None

            batch2 = _seed_batch(sess, batch_id=2)
            applied = apply_recurring_adjustments_to_batch(sess, batch2)
            sess.commit()
            assert applied == 0
            assert sess.query(Ride).filter(Ride.payroll_batch_id == 2).count() == 0

            log = (
                sess.query(BatchCorrectionLog)
                .filter(BatchCorrectionLog.field == "recurring_adjustment_deactivated")
                .first()
            )
            assert log is not None
        finally:
            sess.close()

    def test_deleting_a_one_time_adjustment_does_not_touch_any_template(self):
        r = _post_freeform(batch_id=1, amount=25.0, service_name="One-off bonus", permanent=False)
        ride_id = r.json()["ride_id"]

        del_resp = client.delete(
            f"/api/data/rides/{ride_id}", cookies=_AUTH, headers={"Accept": "application/json"},
        )
        assert del_resp.status_code == 200, del_resp.text
        assert del_resp.json()["recurring_adjustment_stopped"] is False
