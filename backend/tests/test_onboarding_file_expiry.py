"""
Tests for the S6 punch-list fix: OnboardingFile.expires_at is now written on
upload (previously the column existed but nothing ever set it) and feeds a
new internal-only health-check nag (onboarding_file_expiry).

Covers:
  - GET /onboarding/{id} now attaches the files list at all (it previously
    didn't — the admin FileSlot UI always showed "Not uploaded" regardless
    of what was actually on R2, a bug upstream of the expires_at gap).
  - POST /onboarding/{id}/upload persists an optional expires_at form field.
  - Re-uploading without a new expires_at doesn't wipe out a previously set one.
  - Invalid expires_at input 400s instead of silently parsing garbage.
  - health_monitor._check_onboarding_file_expiry: green/yellow/red logic.
  - Wiring: the new check is actually registered in health_monitor.CHECKS.

DB strategy: same in-memory SQLite + StaticPool pattern used across the
test suite (see test_settle_external.py).

Run in isolation:
    PYTHONPATH=/path/to/zpay-v2-fresh pytest backend/tests/test_onboarding_file_expiry.py -v
"""

from __future__ import annotations

import io
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
BACKEND_DIR = Path(__file__).resolve().parents[1]

os.environ.setdefault(
    "ZPAY_SECRET_KEY",
    "test-secret-file-expiry-long-enough-to-pass",
)
os.environ.setdefault("DATABASE_URL", "sqlite://")

from backend.db.models import Base, OnboardingFile, OnboardingRecord, Person  # noqa: E402

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

_SESSION_COOKIE = create_session(
    username="testadmin",
    display_name="Test Admin",
    color="#333",
    initials="TA",
    role="admin",
)
_AUTH = {COOKIE_NAME: _SESSION_COOKIE}

client = TestClient(app, raise_server_exceptions=True)


def _db():
    return _SessionFactory()


def _wipe():
    sess = _db()
    try:
        sess.query(OnboardingFile).delete(synchronize_session=False)
        sess.query(OnboardingRecord).delete(synchronize_session=False)
        sess.query(Person).delete(synchronize_session=False)
        sess.commit()
    finally:
        sess.close()


def _seed_record(person_id: int, onboarding_id: int) -> None:
    sess = _db()
    try:
        p = Person(person_id=person_id, full_name=f"Driver {person_id}", active=True, status="active")
        sess.add(p)
        rec = OnboardingRecord(id=onboarding_id, person_id=person_id, invite_token=f"tok-{onboarding_id}")
        sess.add(rec)
        sess.commit()
    finally:
        sess.close()


_PDF_BYTES = b"%PDF-1.4 fake test pdf content"


class TestGetOnboardingIncludesFiles:
    def setup_method(self):
        _wipe()

    def test_files_key_present_and_empty_when_none_uploaded(self):
        _seed_record(person_id=100, onboarding_id=100)
        resp = client.get("/api/data/onboarding/100", cookies=_AUTH)
        assert resp.status_code == 200
        assert resp.json()["files"] == []

    def test_files_key_reflects_uploaded_file(self):
        _seed_record(person_id=101, onboarding_id=101)
        client.post(
            "/api/data/onboarding/101/upload",
            files={"file": ("license.pdf", io.BytesIO(_PDF_BYTES), "application/pdf")},
            data={"file_type": "drivers_license"},
            cookies=_AUTH,
            headers={"Accept": "application/json"},
        )
        resp = client.get("/api/data/onboarding/101", cookies=_AUTH)
        files = resp.json()["files"]
        assert len(files) == 1
        assert files[0]["file_type"] == "drivers_license"
        assert files[0]["filename"] == "license.pdf"


class TestUploadExpiresAt:
    def setup_method(self):
        _wipe()

    def test_expires_at_persists_on_upload(self):
        _seed_record(person_id=110, onboarding_id=110)
        resp = client.post(
            "/api/data/onboarding/110/upload",
            files={"file": ("reg.pdf", io.BytesIO(_PDF_BYTES), "application/pdf")},
            data={"file_type": "vehicle_registration", "expires_at": "2027-03-15"},
            cookies=_AUTH,
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 200
        sess = _db()
        try:
            f = sess.query(OnboardingFile).filter_by(onboarding_id=110).first()
            assert f.expires_at is not None
            assert f.expires_at.date().isoformat() == "2027-03-15"
        finally:
            sess.close()

    def test_expires_at_optional_defaults_to_none(self):
        _seed_record(person_id=111, onboarding_id=111)
        client.post(
            "/api/data/onboarding/111/upload",
            files={"file": ("insp.pdf", io.BytesIO(_PDF_BYTES), "application/pdf")},
            data={"file_type": "inspection"},
            cookies=_AUTH,
            headers={"Accept": "application/json"},
        )
        sess = _db()
        try:
            f = sess.query(OnboardingFile).filter_by(onboarding_id=111).first()
            assert f.expires_at is None
        finally:
            sess.close()

    def test_reupload_without_expires_at_keeps_previous_value(self):
        _seed_record(person_id=112, onboarding_id=112)
        client.post(
            "/api/data/onboarding/112/upload",
            files={"file": ("dl_v1.pdf", io.BytesIO(_PDF_BYTES), "application/pdf")},
            data={"file_type": "drivers_license", "expires_at": "2027-01-01"},
            cookies=_AUTH,
            headers={"Accept": "application/json"},
        )
        # Re-upload a replacement file without specifying expires_at again
        client.post(
            "/api/data/onboarding/112/upload",
            files={"file": ("dl_v2.pdf", io.BytesIO(_PDF_BYTES), "application/pdf")},
            data={"file_type": "drivers_license"},
            cookies=_AUTH,
            headers={"Accept": "application/json"},
        )
        sess = _db()
        try:
            f = sess.query(OnboardingFile).filter_by(onboarding_id=112, file_type="drivers_license").first()
            assert f.filename == "dl_v2.pdf"
            assert f.expires_at is not None
            assert f.expires_at.date().isoformat() == "2027-01-01"
        finally:
            sess.close()

    def test_invalid_expires_at_400s(self):
        _seed_record(person_id=113, onboarding_id=113)
        resp = client.post(
            "/api/data/onboarding/113/upload",
            files={"file": ("dl.pdf", io.BytesIO(_PDF_BYTES), "application/pdf")},
            data={"file_type": "drivers_license", "expires_at": "not-a-date"},
            cookies=_AUTH,
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 400


class TestHealthCheckOnboardingFileExpiry:
    def setup_method(self):
        _wipe()

    def _run_check(self, monkeypatch):
        from backend.services import health_monitor
        monkeypatch.setattr(health_monitor, "SessionLocal", _SessionFactory)
        return health_monitor._check_onboarding_file_expiry()

    def test_green_when_nothing_expiring(self, monkeypatch):
        _seed_record(person_id=200, onboarding_id=200)
        result = self._run_check(monkeypatch)
        assert result.status == "green"

    def test_yellow_when_expiring_within_30_days(self, monkeypatch):
        _seed_record(person_id=201, onboarding_id=201)
        sess = _db()
        try:
            soon = datetime.now(timezone.utc) + timedelta(days=10)
            sess.add(OnboardingFile(
                onboarding_id=201, file_type="drivers_license",
                filename="dl.pdf", expires_at=soon,
            ))
            sess.commit()
        finally:
            sess.close()
        result = self._run_check(monkeypatch)
        assert result.status == "yellow"
        assert len(result.detail["expiring_soon"]) == 1

    def test_red_when_already_expired(self, monkeypatch):
        _seed_record(person_id=202, onboarding_id=202)
        sess = _db()
        try:
            past = datetime.now(timezone.utc) - timedelta(days=2)
            sess.add(OnboardingFile(
                onboarding_id=202, file_type="inspection",
                filename="insp.pdf", expires_at=past,
            ))
            sess.commit()
        finally:
            sess.close()
        result = self._run_check(monkeypatch)
        assert result.status == "red"
        assert len(result.detail["expired"]) == 1

    def test_green_when_expiry_far_in_future(self, monkeypatch):
        _seed_record(person_id=203, onboarding_id=203)
        sess = _db()
        try:
            far = datetime.now(timezone.utc) + timedelta(days=365)
            sess.add(OnboardingFile(
                onboarding_id=203, file_type="insurance",
                filename="ins.pdf", expires_at=far,
            ))
            sess.commit()
        finally:
            sess.close()
        result = self._run_check(monkeypatch)
        assert result.status == "green"


class TestWiring:
    """Source-text checks that the check is actually plugged into the registry."""

    def test_health_monitor_registers_onboarding_file_expiry_check(self):
        src = (BACKEND_DIR / "services" / "health_monitor.py").read_text(encoding="utf-8")
        assert '"onboarding_file_expiry"' in src
        assert "_check_onboarding_file_expiry" in src

    def test_app_wires_ed_compliance_sync_behind_flag(self):
        src = (BACKEND_DIR / "app.py").read_text(encoding="utf-8")
        assert "ED_COMPLIANCE_SYNC" in src
        assert "everdriven_compliance" in src
