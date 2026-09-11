"""
Tests for POST /api/data/onboarding/training-link/{person_id} — the one-tap
operator training link (routes/training_link.py).

Coverage:
  - Operator role can call it (not just admin).
  - No onboarding record yet → one is created, URL returned, no email/SMS
    side effects (nothing to mock — the route never imports Gmail/Twilio).
  - Second call for the same person returns the SAME invite token (idempotent,
    not regenerated) when the existing record is not expired.
  - Unknown person_id → 404.
  - Viewer role (not admin/operator) → 403.

DB strategy: same in-memory SQLite + StaticPool pattern used across the
suite (see test_workflow_advance_admin_override.py, test_certification_join_submit.py).

Run in isolation:
    PYTHONPATH=. pytest backend/tests/test_training_link.py -v
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
    "test-secret-key-for-training-link-tests-32-chars-min",
)
os.environ.setdefault("DATABASE_URL", "sqlite://")

from backend.db.models import Base, DriverCertification, OnboardingRecord, Person  # noqa: E402

# ── Metadata patches (same boilerplate as the rest of the suite) ────────────
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
from backend.middleware.auth import COOKIE_NAME, create_session  # noqa: E402


def _override_get_db():
    db = _SessionFactory()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db

_OPERATOR_COOKIE = create_session(
    username="testoperator",
    display_name="Test Operator",
    color="#666",
    initials="TO",
    role="operator",
    user_id=2,
)
_VIEWER_COOKIE = create_session(
    username="testviewer",
    display_name="Test Viewer",
    color="#999",
    initials="TV",
    role="viewer",
    user_id=3,
)

operator_client = TestClient(app, raise_server_exceptions=True)
operator_client.cookies.set(COOKIE_NAME, _OPERATOR_COOKIE)

viewer_client = TestClient(app, raise_server_exceptions=True)
viewer_client.cookies.set(COOKIE_NAME, _VIEWER_COOKIE)


def _db():
    return _SessionFactory()


def _wipe():
    sess = _db()
    try:
        sess.query(DriverCertification).delete(synchronize_session=False)
        sess.query(OnboardingRecord).delete(synchronize_session=False)
        sess.query(Person).delete(synchronize_session=False)
        sess.commit()
    finally:
        sess.close()


def _make_person(db, person_id: int, full_name: str = "Test Driver") -> Person:
    p = Person(person_id=person_id, full_name=full_name, active=True, status="active")
    db.add(p)
    db.commit()
    return p


class TestTrainingLinkCreate:
    def setup_method(self):
        _wipe()

    def test_operator_can_call_it_and_it_creates_a_record(self):
        db = _db()
        try:
            _make_person(db, 200)
        finally:
            db.close()

        assert _db().query(OnboardingRecord).filter(OnboardingRecord.person_id == 200).first() is None

        resp = operator_client.post("/api/data/onboarding/training-link/200", json={})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "/training/" in body["url"]
        assert body["certified"] is False
        assert body["course_version"] is None
        assert body["expires_at"]

        db = _db()
        try:
            rec = db.query(OnboardingRecord).filter(OnboardingRecord.person_id == 200).first()
            assert rec is not None
            assert rec.invite_token in body["url"]
            assert rec.partner == "firstalt"
        finally:
            db.close()

    def test_second_call_returns_same_token(self):
        db = _db()
        try:
            _make_person(db, 201)
        finally:
            db.close()

        first = operator_client.post("/api/data/onboarding/training-link/201", json={}).json()
        second = operator_client.post("/api/data/onboarding/training-link/201", json={}).json()
        assert first["url"] == second["url"]

    def test_unknown_person_404(self):
        resp = operator_client.post("/api/data/onboarding/training-link/999999", json={})
        assert resp.status_code == 404

    def test_viewer_role_forbidden(self):
        db = _db()
        try:
            _make_person(db, 202)
        finally:
            db.close()
        resp = viewer_client.post("/api/data/onboarding/training-link/202", json={})
        assert resp.status_code == 403

    def test_expired_record_gets_new_token(self):
        db = _db()
        try:
            _make_person(db, 203)
            stale_started = datetime.now(timezone.utc) - timedelta(days=45)
            rec = OnboardingRecord(
                person_id=203,
                invite_token="stale-token-203",
                started_at=stale_started,
            )
            db.add(rec)
            db.commit()
        finally:
            db.close()

        resp = operator_client.post("/api/data/onboarding/training-link/203", json={})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "stale-token-203" not in body["url"]

    def test_certified_driver_reflects_status(self):
        from backend.services.certification import COURSE_VERSION

        db = _db()
        try:
            _make_person(db, 204)
            cert = DriverCertification(
                person_id=204,
                course_version=COURSE_VERSION,
                quiz_score=5,
                quiz_total=5,
                signed_name="Test Driver",
                certified_at=datetime.now(timezone.utc),
            )
            db.add(cert)
            db.commit()
        finally:
            db.close()

        resp = operator_client.post("/api/data/onboarding/training-link/204", json={})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["certified"] is True
        assert body["course_version"] == COURSE_VERSION
