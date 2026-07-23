"""
Tests for the S6 punch-list item 6: standardize the partner (Acumen)
contract on the internal typed-name e-sign flow instead of paying for
Adobe Sign — Adobe stays wired but unreferenced unless ADOBE_SIGN_ENABLED=1
AND ADOBE_SIGN_INTEGRATION_KEY are both set.

Covers:
  - POST /{id}/send-contract: default path routes to internal e-sign
    (contract_status="sent", no Adobe call attempted).
  - POST /{id}/send-contract: legacy path when explicitly enabled.
  - POST /{id}/partner-contract/sign: the new internal e-sign endpoint —
    happy path + validation errors.
  - onboarding_monitor._auto_send_contract: same default/legacy gating.

DB strategy: same in-memory SQLite + StaticPool pattern used across the
test suite (see test_settle_external.py).

Run in isolation:
    PYTHONPATH=/path/to/zpay-v2-fresh pytest backend/tests/test_partner_contract_esign.py -v
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import BigInteger, Integer, Text, create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault(
    "ZPAY_SECRET_KEY",
    "test-secret-partner-contract-esign-long-enough",
)
os.environ.setdefault("DATABASE_URL", "sqlite://")

from backend.db.models import Base, OnboardingRecord, Person  # noqa: E402

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
    username="testadmin", display_name="Test Admin", color="#333", initials="TA", role="admin",
)
_AUTH = {COOKIE_NAME: _SESSION_COOKIE}
_JSON_HEADERS = {"Accept": "application/json"}

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


def _seed(person_id: int, onboarding_id: int, email: str = "driver@example.com") -> None:
    sess = _db()
    try:
        p = Person(person_id=person_id, full_name="Test Driver", email=email, active=True, status="active")
        sess.add(p)
        rec = OnboardingRecord(id=onboarding_id, person_id=person_id, invite_token=f"tok-{onboarding_id}")
        sess.add(rec)
        sess.commit()
    finally:
        sess.close()


class TestSendContractDefaultsToInternalEsign:
    def setup_method(self):
        _wipe()
        os.environ.pop("ADOBE_SIGN_ENABLED", None)
        os.environ.pop("ADOBE_SIGN_INTEGRATION_KEY", None)

    def test_default_routes_to_internal_esign_no_adobe_call(self):
        _seed(person_id=300, onboarding_id=300)
        with patch("backend.services.adobe_sign.send_envelope") as mock_adobe:
            resp = client.post(
                "/api/data/onboarding/300/send-contract",
                cookies=_AUTH, headers=_JSON_HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["internal_esign_mode"] is True
        assert body["contract_status"] == "sent"
        mock_adobe.assert_not_called()

        sess = _db()
        try:
            rec = sess.query(OnboardingRecord).filter_by(id=300).first()
            assert rec.contract_status == "sent"
        finally:
            sess.close()

    def test_flag_set_without_key_still_uses_internal_esign(self):
        """ADOBE_SIGN_ENABLED=1 alone (no key) must NOT attempt a real Adobe call."""
        os.environ["ADOBE_SIGN_ENABLED"] = "1"
        _seed(person_id=301, onboarding_id=301)
        with patch("backend.services.adobe_sign.send_envelope") as mock_adobe:
            resp = client.post(
                "/api/data/onboarding/301/send-contract",
                cookies=_AUTH, headers=_JSON_HEADERS,
            )
        assert resp.json()["internal_esign_mode"] is True
        mock_adobe.assert_not_called()

    def test_both_flag_and_key_set_uses_legacy_adobe_path(self):
        os.environ["ADOBE_SIGN_ENABLED"] = "1"
        os.environ["ADOBE_SIGN_INTEGRATION_KEY"] = "fake-key-for-test"
        _seed(person_id=302, onboarding_id=302)
        with patch("backend.services.adobe_sign.send_envelope") as mock_adobe:
            mock_adobe.return_value = {"id": "envelope-123"}
            resp = client.post(
                "/api/data/onboarding/302/send-contract",
                cookies=_AUTH, headers=_JSON_HEADERS,
            )
        assert resp.status_code == 200
        assert "internal_esign_mode" not in resp.json()
        mock_adobe.assert_called_once()

    def teardown_method(self):
        os.environ.pop("ADOBE_SIGN_ENABLED", None)
        os.environ.pop("ADOBE_SIGN_INTEGRATION_KEY", None)


class TestPartnerContractSignEndpoint:
    def setup_method(self):
        _wipe()

    def test_happy_path_signs_and_persists(self):
        _seed(person_id=310, onboarding_id=310)
        resp = client.post(
            "/api/data/onboarding/310/partner-contract/sign",
            json={"signed_name": "Test Driver", "agreed": True},
            cookies=_AUTH, headers=_JSON_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        sess = _db()
        try:
            rec = sess.query(OnboardingRecord).filter_by(id=310).first()
            assert rec.contract_status == "signed"
            assert rec.contract_signed_name == "Test Driver"
            assert rec.contract_signed_at is not None
        finally:
            sess.close()

    def test_requires_signed_name(self):
        _seed(person_id=311, onboarding_id=311)
        resp = client.post(
            "/api/data/onboarding/311/partner-contract/sign",
            json={"signed_name": "", "agreed": True},
            cookies=_AUTH, headers=_JSON_HEADERS,
        )
        assert resp.status_code == 400

    def test_requires_agreed_flag(self):
        _seed(person_id=312, onboarding_id=312)
        resp = client.post(
            "/api/data/onboarding/312/partner-contract/sign",
            json={"signed_name": "Test Driver", "agreed": False},
            cookies=_AUTH, headers=_JSON_HEADERS,
        )
        assert resp.status_code == 400

    def test_does_not_touch_maz_contract_columns(self):
        """The partner contract and Maz contract are legally distinct — signing
        one must not bleed into the other's columns."""
        _seed(person_id=313, onboarding_id=313)
        client.post(
            "/api/data/onboarding/313/partner-contract/sign",
            json={"signed_name": "Test Driver", "agreed": True},
            cookies=_AUTH, headers=_JSON_HEADERS,
        )
        sess = _db()
        try:
            rec = sess.query(OnboardingRecord).filter_by(id=313).first()
            assert rec.maz_contract_status == "pending"
            assert rec.maz_contract_signed_name is None
        finally:
            sess.close()

    def test_record_not_found_404s(self):
        resp = client.post(
            "/api/data/onboarding/999999/partner-contract/sign",
            json={"signed_name": "Test Driver", "agreed": True},
            cookies=_AUTH, headers=_JSON_HEADERS,
        )
        assert resp.status_code == 404


class TestOnboardingMonitorAutoSendContract:
    """onboarding_monitor._auto_send_contract — the path that's actually live
    in prod today (MONITOR_ENABLED=1), separate from the router endpoint above."""

    def setup_method(self):
        os.environ.pop("ADOBE_SIGN_ENABLED", None)
        os.environ.pop("ADOBE_SIGN_INTEGRATION_KEY", None)

    def teardown_method(self):
        os.environ.pop("ADOBE_SIGN_ENABLED", None)
        os.environ.pop("ADOBE_SIGN_INTEGRATION_KEY", None)

    def test_default_marks_sent_for_internal_esign_no_adobe_call(self):
        from backend.services import onboarding_monitor

        rec = MagicMock(id=400, contract_status="pending", notes=None)
        person = MagicMock(email="driver@example.com", full_name="Test Driver")

        with patch("backend.services.adobe_sign.send_envelope") as mock_adobe:
            result = onboarding_monitor._auto_send_contract(rec, person)

        assert result is False
        assert rec.contract_status == "sent"
        mock_adobe.assert_not_called()

    def test_enabled_with_key_calls_adobe(self):
        os.environ["ADOBE_SIGN_ENABLED"] = "1"
        os.environ["ADOBE_SIGN_INTEGRATION_KEY"] = "fake-key-for-test"
        from backend.services import onboarding_monitor
        import importlib
        importlib.reload(onboarding_monitor)

        rec = MagicMock(id=401, contract_status="pending", notes=None)
        person = MagicMock(email="driver@example.com", full_name="Test Driver")

        with patch("backend.services.adobe_sign.send_envelope") as mock_adobe:
            mock_adobe.return_value = {"id": "envelope-999"}
            result = onboarding_monitor._auto_send_contract(rec, person)

        mock_adobe.assert_called_once()
        assert result is True
