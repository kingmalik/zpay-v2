"""
Tests for the S7 certification extension to POST /api/data/onboarding/join/{token}/step
(step="maz_training") and the new GET /api/data/onboarding/join/{token}/certification
public course-content endpoint.

DB strategy: same in-memory SQLite + StaticPool pattern used across the test
suite (see test_join_submit_step.py, test_settle_external.py).

Run in isolation:
    PYTHONPATH=. pytest backend/tests/test_certification_join_submit.py -v
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
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
    "test-secret-certification-join-submit-long-enough-to-pass",
)
os.environ.setdefault("DATABASE_URL", "sqlite://")

from backend.db.models import Base, DriverCertification, OnboardingRecord, Person  # noqa: E402

# ── Metadata patches (same boilerplate as test_join_submit_step.py) ─────────
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
from backend.services import certification  # noqa: E402


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
        sess.query(DriverCertification).delete(synchronize_session=False)
        sess.query(OnboardingRecord).delete(synchronize_session=False)
        sess.query(Person).delete(synchronize_session=False)
        sess.commit()
    finally:
        sess.close()


def _seed(person_id: int, onboarding_id: int, token: str) -> None:
    sess = _db()
    try:
        p = Person(person_id=person_id, full_name="Test Driver", active=True, status="active")
        sess.add(p)
        rec = OnboardingRecord(
            id=onboarding_id,
            person_id=person_id,
            invite_token=token,
            started_at=datetime.now(timezone.utc),
            maz_training_status="pending",
        )
        sess.add(rec)
        sess.commit()
    finally:
        sess.close()


class TestQuizGatedCertification:
    def setup_method(self):
        _wipe()

    def test_below_threshold_quiz_score_rejected(self):
        _seed(person_id=100, onboarding_id=100, token="tok-cert-100")
        resp = client.post(
            "/api/data/onboarding/join/tok-cert-100/step",
            json={
                "step": "maz_training",
                "acknowledged": True,
                "name": "Test Driver",
                "quiz_score": 7,
                "quiz_total": 10,
                "course_version": certification.COURSE_VERSION,
                "signed_name": "Test Driver",
            },
        )
        assert resp.status_code == 400
        sess = _db()
        try:
            rec = sess.query(OnboardingRecord).filter_by(id=100).first()
            assert rec.maz_training_status == "pending"
            assert sess.query(DriverCertification).filter_by(person_id=100).count() == 0
        finally:
            sess.close()

    def test_at_threshold_quiz_score_accepted_and_certifies(self):
        _seed(person_id=101, onboarding_id=101, token="tok-cert-101")
        resp = client.post(
            "/api/data/onboarding/join/tok-cert-101/step",
            json={
                "step": "maz_training",
                "acknowledged": True,
                "name": "Test Driver",
                "quiz_score": 8,
                "quiz_total": 10,
                "course_version": certification.COURSE_VERSION,
                "signed_name": "Test Driver",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["maz_training_status"] == "complete"
        assert body["certification"]["quiz_score"] == 8
        assert body["certification"]["quiz_total"] == 10
        assert body["certification"]["course_version"] == certification.COURSE_VERSION

        sess = _db()
        try:
            rec = sess.query(OnboardingRecord).filter_by(id=101).first()
            assert rec.maz_training_status == "complete"
            cert = sess.query(DriverCertification).filter_by(person_id=101).first()
            assert cert is not None
            assert cert.quiz_score == 8
            assert cert.signed_name == "Test Driver"
        finally:
            sess.close()

        assert certification.is_certified(_db(), 101) is True

    def test_perfect_score_accepted(self):
        _seed(person_id=102, onboarding_id=102, token="tok-cert-102")
        resp = client.post(
            "/api/data/onboarding/join/tok-cert-102/step",
            json={
                "step": "maz_training",
                "acknowledged": True,
                "name": "Test Driver",
                "quiz_score": 10,
                "quiz_total": 10,
                "signed_name": "Test Driver",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["certification"]["quiz_score"] == 10

    def test_non_integer_quiz_score_rejected(self):
        _seed(person_id=103, onboarding_id=103, token="tok-cert-103")
        resp = client.post(
            "/api/data/onboarding/join/tok-cert-103/step",
            json={
                "step": "maz_training",
                "acknowledged": True,
                "name": "Test Driver",
                "quiz_score": "not-a-number",
                "quiz_total": 10,
                "signed_name": "Test Driver",
            },
        )
        assert resp.status_code == 400

    def test_zero_quiz_total_rejected(self):
        _seed(person_id=104, onboarding_id=104, token="tok-cert-104")
        resp = client.post(
            "/api/data/onboarding/join/tok-cert-104/step",
            json={
                "step": "maz_training",
                "acknowledged": True,
                "name": "Test Driver",
                "quiz_score": 0,
                "quiz_total": 0,
                "signed_name": "Test Driver",
            },
        )
        assert resp.status_code == 400

    def test_legacy_payload_without_quiz_fields_still_works_no_cert_row(self):
        """Backward compatibility: the pre-S7 shape (plain acknowledged+name,
        no quiz fields) still marks the step complete, but writes no
        certification row — matches test_join_submit_step.py's existing
        (unmodified) coverage of this exact shape."""
        _seed(person_id=105, onboarding_id=105, token="tok-cert-105")
        resp = client.post(
            "/api/data/onboarding/join/tok-cert-105/step",
            json={"step": "maz_training", "acknowledged": True, "name": "Test Driver"},
        )
        assert resp.status_code == 200
        assert resp.json()["maz_training_status"] == "complete"
        assert "certification" not in resp.json()

        sess = _db()
        try:
            assert sess.query(DriverCertification).filter_by(person_id=105).count() == 0
        finally:
            sess.close()


class TestCertificationCourseContentEndpoint:
    def setup_method(self):
        _wipe()

    def test_returns_course_content_for_valid_token(self):
        _seed(person_id=200, onboarding_id=200, token="tok-course-200")
        resp = client.get("/api/data/onboarding/join/tok-course-200/certification")
        assert resp.status_code == 200
        body = resp.json()
        assert body["course_version"] == certification.COURSE_VERSION
        assert len(body["modules"]) == 6
        assert len(body["quiz"]) == 10

    def test_unknown_token_404s(self):
        resp = client.get("/api/data/onboarding/join/tok-does-not-exist/certification")
        assert resp.status_code == 404
