"""
Tests for POST /api/data/onboarding/join/{token}/step — the driver self-service
onboarding step-submission endpoint.

Covers the S6 punch-list fix: ALLOWED_STEPS previously whitelisted only
"personal_info", so maz_training and maz_contract submissions 400'd silently
(the frontend didn't check res.ok, so drivers saw a fake success screen).

DB strategy: same in-memory SQLite + StaticPool pattern used across the
test suite (see test_settle_external.py).

Run in isolation:
    PYTHONPATH=/path/to/zpay-v2-fresh pytest backend/tests/test_join_submit_step.py -v
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import BigInteger, Integer, Text, create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault(
    "ZPAY_SECRET_KEY",
    "test-secret-join-submit-step-long-enough-to-pass",
)
os.environ.setdefault("DATABASE_URL", "sqlite://")

from backend.db.models import Base, OnboardingRecord, Person  # noqa: E402

# ── Metadata patches (same boilerplate as test_settle_external.py) ──────────
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


def _override_get_db():
    db = _SessionFactory()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db

client = TestClient(app, raise_server_exceptions=True)


def _db():
    return _SessionFactory()


def _wipe():
    sess = _db()
    try:
        sess.query(OnboardingRecord).delete(synchronize_session=False)
        sess.query(Person).delete(synchronize_session=False)
        sess.commit()
    finally:
        sess.close()


def _seed(
    person_id: int = 900,
    onboarding_id: int = 900,
    token: str = "tok-abc-900",
    started_at: datetime | None = None,
    maz_training_status: str = "pending",
    maz_contract_status: str = "pending",
) -> None:
    sess = _db()
    try:
        p = Person(
            person_id=person_id,
            full_name="Test Driver",
            active=True,
            status="active",
        )
        sess.add(p)
        rec = OnboardingRecord(
            id=onboarding_id,
            person_id=person_id,
            invite_token=token,
            started_at=started_at or datetime.now(timezone.utc),
            maz_training_status=maz_training_status,
            maz_contract_status=maz_contract_status,
        )
        sess.add(rec)
        sess.commit()
    finally:
        sess.close()


class TestMazTrainingStep:
    def setup_method(self):
        _wipe()

    def test_maz_training_step_no_longer_400s(self):
        """The headline S6 fix: maz_training used to 400 (not in ALLOWED_STEPS)."""
        _seed(token="tok-training-1")
        resp = client.post(
            "/api/data/onboarding/join/tok-training-1/step",
            json={"step": "maz_training", "acknowledged": True, "name": "Test Driver"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["maz_training_status"] == "complete"

    def test_maz_training_persists_to_db(self):
        _seed(token="tok-training-2", onboarding_id=901, person_id=901)
        client.post(
            "/api/data/onboarding/join/tok-training-2/step",
            json={"step": "maz_training", "acknowledged": True, "name": "Test Driver"},
        )
        sess = _db()
        try:
            rec = sess.query(OnboardingRecord).filter_by(id=901).first()
            assert rec.maz_training_status == "complete"
        finally:
            sess.close()

    def test_maz_training_requires_acknowledgment(self):
        _seed(token="tok-training-3", onboarding_id=902, person_id=902)
        resp = client.post(
            "/api/data/onboarding/join/tok-training-3/step",
            json={"step": "maz_training", "acknowledged": False, "name": "Test Driver"},
        )
        assert resp.status_code == 400

    def test_maz_training_requires_name(self):
        _seed(token="tok-training-4", onboarding_id=903, person_id=903)
        resp = client.post(
            "/api/data/onboarding/join/tok-training-4/step",
            json={"step": "maz_training", "acknowledged": True, "name": "  "},
        )
        assert resp.status_code == 400


class TestMazContractStep:
    def setup_method(self):
        _wipe()

    def test_maz_contract_step_no_longer_400s(self):
        """The headline S6 fix: maz_contract used to 400 (not in ALLOWED_STEPS)."""
        _seed(token="tok-contract-1", onboarding_id=910, person_id=910)
        resp = client.post(
            "/api/data/onboarding/join/tok-contract-1/step",
            json={
                "step": "maz_contract",
                "signed": True,
                "name": "Test Driver",
                "signed_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["maz_contract_status"] == "signed"

    def test_maz_contract_persists_signed_name_and_timestamp(self):
        _seed(token="tok-contract-2", onboarding_id=911, person_id=911)
        client.post(
            "/api/data/onboarding/join/tok-contract-2/step",
            json={"step": "maz_contract", "signed": True, "name": "Jane Driver"},
        )
        sess = _db()
        try:
            rec = sess.query(OnboardingRecord).filter_by(id=911).first()
            assert rec.maz_contract_status == "signed"
            assert rec.maz_contract_signed_name == "Jane Driver"
            assert rec.maz_contract_signed_at is not None
        finally:
            sess.close()

    def test_maz_contract_requires_signed_flag(self):
        _seed(token="tok-contract-3", onboarding_id=912, person_id=912)
        resp = client.post(
            "/api/data/onboarding/join/tok-contract-3/step",
            json={"step": "maz_contract", "signed": False, "name": "Test Driver"},
        )
        assert resp.status_code == 400

    def test_maz_contract_requires_name(self):
        _seed(token="tok-contract-4", onboarding_id=913, person_id=913)
        resp = client.post(
            "/api/data/onboarding/join/tok-contract-4/step",
            json={"step": "maz_contract", "signed": True, "name": ""},
        )
        assert resp.status_code == 400


class TestUnknownStepStillRejected:
    def setup_method(self):
        _wipe()

    def test_unknown_step_still_400s(self):
        """Regression guard — the whitelist should still reject garbage step names."""
        _seed(token="tok-unknown-1", onboarding_id=920, person_id=920)
        resp = client.post(
            "/api/data/onboarding/join/tok-unknown-1/step",
            json={"step": "not_a_real_step", "data": {}},
        )
        assert resp.status_code == 400

    def test_personal_info_step_still_works(self):
        """Regression guard — the pre-existing personal_info step must keep working."""
        _seed(token="tok-personal-1", onboarding_id=921, person_id=921)
        resp = client.post(
            "/api/data/onboarding/join/tok-personal-1/step",
            json={"step": "personal_info", "data": {"full_name": "New Name"}},
        )
        assert resp.status_code == 200


class TestTokenExpiry:
    def setup_method(self):
        _wipe()

    def test_get_and_post_use_same_expiry_window(self):
        """GET and POST previously disagreed (30d vs 14d) — now unified."""
        old_started = datetime.now(timezone.utc) - timedelta(days=20)
        _seed(token="tok-expiry-1", onboarding_id=930, person_id=930, started_at=old_started)

        get_resp = client.get("/api/data/onboarding/join/tok-expiry-1")
        post_resp = client.post(
            "/api/data/onboarding/join/tok-expiry-1/step",
            json={"step": "maz_training", "acknowledged": True, "name": "Test Driver"},
        )

        # A 20-day-old link must be valid on BOTH paths under the unified window.
        assert get_resp.status_code == 200
        assert post_resp.status_code == 200

    def test_post_expires_after_30_days(self):
        old_started = datetime.now(timezone.utc) - timedelta(days=31)
        _seed(token="tok-expiry-2", onboarding_id=931, person_id=931, started_at=old_started)

        resp = client.post(
            "/api/data/onboarding/join/tok-expiry-2/step",
            json={"step": "maz_training", "acknowledged": True, "name": "Test Driver"},
        )
        assert resp.status_code == 401
