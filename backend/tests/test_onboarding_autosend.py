"""
Tests for the S6 punch-list item 2: auto-send the Maz training + contract
portal links to the driver (email/SMS) instead of an operator copying them
by hand.

HARD CONSTRAINT under test: no driver-facing send can fire unless
ONBOARDING_AUTOSEND=1 is explicitly set — the default (unset/"0") must
always fall back to a dry-run log, even when the caller passes
dry_run=False (this is what onboarding_automation.check_and_advance does
when a record has automation_live=True and the compliance-sync loop calls
it live).

Uses lightweight MagicMock stand-ins for the SQLAlchemy models (same
approach as test_onboarding_pipeline.py) rather than a real DB — this
module has no FastAPI/DB-session surface of its own.

Run in isolation:
    PYTHONPATH=/path/to/zpay-v2-fresh pytest backend/tests/test_onboarding_autosend.py -v
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault("ZPAY_SECRET_KEY", "test-secret-autosend-long-enough-to-pass")
os.environ.setdefault("DATABASE_URL", "sqlite://")

from backend.services import onboarding_autosend  # noqa: E402


def _make_person(**kwargs):
    p = MagicMock()
    p.person_id = kwargs.get("person_id", 500)
    p.full_name = kwargs.get("full_name", "Jane Driver")
    p.email = kwargs.get("email", "jane@example.com")
    p.phone = kwargs.get("phone", "2065551234")
    return p


def _make_record(**kwargs):
    r = MagicMock()
    r.id = kwargs.get("id", 1)
    r.invite_token = kwargs.get("invite_token", "tok-abc")
    r.automation_log = kwargs.get("automation_log", [])
    r.contract_status = kwargs.get("contract_status", "pending")
    r.maz_training_status = kwargs.get("maz_training_status", "pending")
    r.maz_contract_status = kwargs.get("maz_contract_status", "pending")
    r.person_id = kwargs.get("person_id", 500)
    return r


class TestLinkBuilders:
    def test_build_training_link_uses_default_base(self, monkeypatch):
        monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
        monkeypatch.delenv("FRONTEND_URL", raising=False)
        link = onboarding_autosend.build_training_link("tok123")
        assert link == "https://frontend-ruddy-ten-82.vercel.app/training/tok123"

    def test_build_contract_link_uses_default_base(self, monkeypatch):
        monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
        monkeypatch.delenv("FRONTEND_URL", raising=False)
        link = onboarding_autosend.build_contract_link("tok456")
        assert link == "https://frontend-ruddy-ten-82.vercel.app/contract/tok456"

    def test_build_link_honors_public_base_url_override(self, monkeypatch):
        monkeypatch.setenv("PUBLIC_BASE_URL", "https://custom.example.com")
        link = onboarding_autosend.build_training_link("tokX")
        assert link == "https://custom.example.com/training/tokX"


class TestAutosendGateDefaultOff:
    """The hard constraint: nothing real fires unless ONBOARDING_AUTOSEND=1."""

    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("ONBOARDING_AUTOSEND", raising=False)
        assert onboarding_autosend._autosend_enabled() is False

    def test_dry_run_true_never_sends_even_if_flag_set(self, monkeypatch):
        monkeypatch.setenv("ONBOARDING_AUTOSEND", "1")
        person = _make_person()
        record = _make_record()
        with patch("backend.services.email_service.send_plain_email") as mock_email, \
             patch("backend.services.notification_service.send_sms") as mock_sms:
            action = onboarding_autosend.send_step_link(
                person, record, "https://example.com/training/tok",
                step_name="Maz Training", action_name="send_training_link",
                dry_run=True, now="2026-07-22T00:00:00Z",
            )
        mock_email.assert_not_called()
        mock_sms.assert_not_called()
        assert action["executed"] is False
        assert action["dry_run"] is True

    def test_flag_unset_blocks_real_send_even_with_dry_run_false(self, monkeypatch):
        """The critical case: automation_live=True + compliance sync calls
        check_and_advance(dry_run=False) — but ONBOARDING_AUTOSEND is still
        unset, so nothing driver-facing may fire."""
        monkeypatch.delenv("ONBOARDING_AUTOSEND", raising=False)
        person = _make_person()
        record = _make_record()
        with patch("backend.services.email_service.send_plain_email") as mock_email, \
             patch("backend.services.notification_service.send_sms") as mock_sms:
            action = onboarding_autosend.send_step_link(
                person, record, "https://example.com/training/tok",
                step_name="Maz Training", action_name="send_training_link",
                dry_run=False, now="2026-07-22T00:00:00Z",
            )
        mock_email.assert_not_called()
        mock_sms.assert_not_called()
        assert action["executed"] is False

    def test_flag_enabled_and_dry_run_false_sends_for_real(self, monkeypatch):
        monkeypatch.setenv("ONBOARDING_AUTOSEND", "1")
        person = _make_person()
        record = _make_record()
        with patch("backend.services.email_service.send_plain_email") as mock_email, \
             patch("backend.services.notification_service.send_sms") as mock_sms:
            action = onboarding_autosend.send_step_link(
                person, record, "https://example.com/training/tok",
                step_name="Maz Training", action_name="send_training_link",
                dry_run=False, now="2026-07-22T00:00:00Z",
            )
        mock_email.assert_called_once()
        mock_sms.assert_called_once()
        assert action["executed"] is True


class TestSendStepLinkGuards:
    def test_no_contact_info_returns_none(self, monkeypatch):
        monkeypatch.setenv("ONBOARDING_AUTOSEND", "1")
        person = _make_person(email=None, phone=None)
        record = _make_record()
        action = onboarding_autosend.send_step_link(
            person, record, "https://example.com/x",
            step_name="Maz Training", action_name="send_training_link",
            dry_run=True, now="2026-07-22T00:00:00Z",
        )
        assert action is None

    def test_already_sent_is_idempotent(self, monkeypatch):
        """Compliance sync runs every 6h — without this guard a driver would
        get re-texted the same link on every cycle until they finish the step."""
        monkeypatch.setenv("ONBOARDING_AUTOSEND", "1")
        person = _make_person()
        record = _make_record(automation_log=[
            {"action": "send_training_link", "executed": True},
        ])
        with patch("backend.services.email_service.send_plain_email") as mock_email:
            action = onboarding_autosend.send_step_link(
                person, record, "https://example.com/x",
                step_name="Maz Training", action_name="send_training_link",
                dry_run=False, now="2026-07-22T00:00:00Z",
            )
        assert action is None
        mock_email.assert_not_called()

    def test_only_email_present_sends_only_email(self, monkeypatch):
        monkeypatch.setenv("ONBOARDING_AUTOSEND", "1")
        person = _make_person(phone=None)
        record = _make_record()
        with patch("backend.services.email_service.send_plain_email") as mock_email, \
             patch("backend.services.notification_service.send_sms") as mock_sms:
            action = onboarding_autosend.send_step_link(
                person, record, "https://example.com/x",
                step_name="Maz Contract", action_name="send_contract_link",
                dry_run=False, now="2026-07-22T00:00:00Z",
            )
        mock_email.assert_called_once()
        mock_sms.assert_not_called()
        assert action["executed"] is True


class TestCheckAndAdvanceWiring:
    """check_and_advance() triggers autosend at the right step transitions."""

    def _load_service(self):
        import importlib
        name = "backend.services.onboarding_automation"
        if name in sys.modules:
            del sys.modules[name]
        return importlib.import_module(name)

    def test_step8_fires_when_partner_contract_clears(self, monkeypatch):
        monkeypatch.setenv("ONBOARDING_AUTOSEND", "0")  # dry-run only
        svc = self._load_service()
        person = _make_person(firstalt_driver_id=999, firstalt_compliance={})
        record = _make_record(contract_status="signed", maz_training_status="pending")
        db = MagicMock()

        actions = svc.check_and_advance(record, person, db, dry_run=True)
        step_names = [a.get("action") for a in actions]
        assert "send_training_link" in step_names

    def test_step8_does_not_fire_before_contract_clears(self, monkeypatch):
        svc = self._load_service()
        person = _make_person(firstalt_driver_id=999, firstalt_compliance={})
        record = _make_record(contract_status="pending", maz_training_status="pending")
        db = MagicMock()

        actions = svc.check_and_advance(record, person, db, dry_run=True)
        step_names = [a.get("action") for a in actions]
        assert "send_training_link" not in step_names

    def test_step9_fires_when_maz_training_completes(self, monkeypatch):
        svc = self._load_service()
        person = _make_person(firstalt_driver_id=999, firstalt_compliance={})
        record = _make_record(
            contract_status="signed",
            maz_training_status="complete",
            maz_contract_status="pending",
        )
        db = MagicMock()

        actions = svc.check_and_advance(record, person, db, dry_run=True)
        step_names = [a.get("action") for a in actions]
        assert "send_contract_link" in step_names

    def test_step9_does_not_fire_before_training_completes(self, monkeypatch):
        svc = self._load_service()
        person = _make_person(firstalt_driver_id=999, firstalt_compliance={})
        record = _make_record(
            contract_status="signed",
            maz_training_status="pending",
            maz_contract_status="pending",
        )
        db = MagicMock()

        actions = svc.check_and_advance(record, person, db, dry_run=True)
        step_names = [a.get("action") for a in actions]
        assert "send_contract_link" not in step_names
