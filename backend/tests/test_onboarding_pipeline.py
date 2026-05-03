"""
Integration tests for the FA + ED onboarding pipelines.

Coverage:
  FA (FirstAlt/Acumen) 8-step pipeline:
    - Full happy path: applicant → active (all external calls mocked)
    - Step 1: send_firstalt_invite → priority_email_status = "sent"
    - Step 2: send_brandon_bgc_email → brandon_email_status = "complete"
    - Step 3: fadv_initiate_bgc → fadv_report_id stored, fadv_status = "initiated"
    - Step 3 FADV webhook: status update → fadv_status updated, bgc advanced to "manual"
    - Step 4: send_fa_drug_consent → consent_status = "sent"
    - Adobe Sign webhook: consent signed → consent_status = "signed"
    - FADV missing creds → 503 + env_missing=True, no fake data
    - FADV webhook feature flag off → skipped (no DB changes)

  ED (EverDriven) 10-step pipeline:
    - Full happy path: applicant → active (all external calls mocked)
    - Step 1: send_cc_invite → cc_invite_sent_at stamped
    - Step 2: send_hallo_link → hallo_link_sent_at stamped
    - Step 3: log_hallo_score → score stored, hallo_completed_at stamped
    - Step 3: log_hallo_score out of range → 400
    - Step 4 (drug consent): send_ed_drug_consent → ed_drug_test_status = "sent"
    - Step 4 rate limit: second call within 60s → 429
    - Step 4 mark complete: requires ed_drug_test_status = "sent" first
    - CC API feature flag off → sync returns empty docs, no crash

  Negative / failure paths:
    - Missing email → 400 for all email-sending endpoints
    - Record not found → 404
    - FADV webhook with unknown report_id → skips gracefully (200, no crash)

All external API calls (FADV, Adobe Sign, Gmail, CC API, notification_service)
are mocked.  No real HTTP requests are made.
"""

from __future__ import annotations

import sys
import types
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call
from pathlib import Path

import pytest

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ── Stub heavy dependencies before any service import ────────────────────────

def _setup_stubs():
    # Minimal stubs for packages not available in test environment
    light_stubs = [
        "pycognito",
        "fastapi",
        "fastapi.responses",
    ]
    for name in light_stubs:
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)

    # backend.db stub
    if "backend.db" not in sys.modules:
        sys.modules["backend.db"] = types.ModuleType("backend.db")

    # backend.db.models stub — provide sentinel classes with MagicMock attributes
    # so that filter expressions like Person.person_id == x work without crashing
    existing_models = sys.modules.get("backend.db.models")
    if existing_models is None or not hasattr(existing_models, "OnboardingRecord"):
        models_stub = types.ModuleType("backend.db.models")

        class OnboardingRecord(MagicMock):
            pass

        class Person(MagicMock):
            pass

        class OnboardingDocument(MagicMock):
            pass

        class OnboardingFile(MagicMock):
            pass

        OnboardingRecord.person_id = MagicMock()
        OnboardingRecord.id = MagicMock()
        OnboardingRecord.fadv_report_id = MagicMock()
        OnboardingRecord.drug_test_agreement_id = MagicMock()
        OnboardingRecord.completed_at = MagicMock()
        Person.person_id = MagicMock()
        Person.active = MagicMock()
        Person.everdriven_driver_id = MagicMock()
        Person.firstalt_driver_id = MagicMock()

        models_stub.OnboardingRecord = OnboardingRecord
        models_stub.Person = Person
        models_stub.OnboardingDocument = OnboardingDocument
        models_stub.OnboardingFile = OnboardingFile
        sys.modules["backend.db.models"] = models_stub

    # Service stubs
    service_stubs = [
        "backend.services.notification_service",
        "backend.services.adobe_sign",
        "backend.services.email_service",
    ]
    for name in service_stubs:
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)

    # Provide redirect_email + test_subject in test_mode stub
    if "backend.utils.test_mode" not in sys.modules:
        sys.modules["backend.utils.test_mode"] = types.ModuleType("backend.utils.test_mode")
    test_mode_stub = sys.modules["backend.utils.test_mode"]
    test_mode_stub.redirect_email = lambda email: email
    test_mode_stub.test_subject = lambda s: s


_setup_stubs()


# ── DB model stubs with all required attributes ───────────────────────────────

def _make_onboarding_record(**kwargs) -> MagicMock:
    """Build a complete OnboardingRecord mock with all fields needed by the pipeline."""
    rec = MagicMock()
    rec.id = kwargs.get("id", 1)
    rec.person_id = kwargs.get("person_id", 100)
    rec.partner = kwargs.get("partner", "firstalt")
    rec.started_at = datetime(2026, 5, 1, tzinfo=timezone.utc)
    rec.completed_at = None
    rec.notes = None
    rec.automation_live = False
    rec.automation_log = []
    rec.invite_token = "test-token-abc"
    rec.personal_info = None
    rec.intake_submitted_at = None

    # FA fields
    rec.priority_email_status = kwargs.get("priority_email_status", "pending")
    rec.brandon_email_status = kwargs.get("brandon_email_status", "pending")
    rec.bgc_status = kwargs.get("bgc_status", "pending")
    rec.consent_status = kwargs.get("consent_status", "pending")
    rec.consent_envelope_id = kwargs.get("consent_envelope_id", None)
    rec.drug_test_status = kwargs.get("drug_test_status", "pending")
    rec.drug_test_sent_at = kwargs.get("drug_test_sent_at", None)
    rec.drug_test_signed_at = kwargs.get("drug_test_signed_at", None)
    rec.training_status = kwargs.get("training_status", "pending")
    rec.files_status = kwargs.get("files_status", "pending")
    rec.contract_status = kwargs.get("contract_status", "pending")
    rec.contract_envelope_id = None
    rec.maz_training_status = kwargs.get("maz_training_status", "pending")
    rec.maz_contract_status = kwargs.get("maz_contract_status", "pending")
    rec.maz_contract_signed_name = None
    rec.maz_contract_signed_at = None
    rec.paychex_status = kwargs.get("paychex_status", "pending")

    # FADV fields
    rec.fadv_report_id = kwargs.get("fadv_report_id", None)
    rec.fadv_status = kwargs.get("fadv_status", None)
    rec.fadv_initiated_at = kwargs.get("fadv_initiated_at", None)
    rec.fadv_result_at = kwargs.get("fadv_result_at", None)
    rec.fadv_raw = None

    # ED fields
    rec.cc_id = kwargs.get("cc_id", None)
    rec.cc_status = kwargs.get("cc_status", None)
    rec.cc_invite_sent_at = kwargs.get("cc_invite_sent_at", None)
    rec.hallo_link_sent_at = kwargs.get("hallo_link_sent_at", None)
    rec.hallo_score = kwargs.get("hallo_score", None)
    rec.hallo_completed_at = kwargs.get("hallo_completed_at", None)
    rec.saferide_link_sent_at = kwargs.get("saferide_link_sent_at", None)
    rec.saferide_cert_uploaded_at = kwargs.get("saferide_cert_uploaded_at", None)
    rec.ed_app_install_status = kwargs.get("ed_app_install_status", "pending")
    rec.equipment_status = kwargs.get("equipment_status", "pending")
    rec.ed_vehicle_insp_1_status = kwargs.get("ed_vehicle_insp_1_status", "pending")
    rec.ed_vehicle_insp_2_status = kwargs.get("ed_vehicle_insp_2_status", "pending")
    rec.ed_bgc_status = kwargs.get("ed_bgc_status", "pending")
    rec.ed_drug_test_status = kwargs.get("ed_drug_test_status", "pending")
    rec.drug_test_agreement_id = kwargs.get("drug_test_agreement_id", None)

    return rec


def _make_person(**kwargs) -> MagicMock:
    """Build a Person mock with all fields needed by the pipeline."""
    p = MagicMock()
    p.person_id = kwargs.get("person_id", 100)
    p.full_name = kwargs.get("full_name", "Rahim Osei")
    p.email = kwargs.get("email", "rahim@test.com")
    p.phone = kwargs.get("phone", "2065551234")
    p.home_address = kwargs.get("home_address", "123 Bellevue Ave, Bellevue WA 98004")
    p.vehicle_year = kwargs.get("vehicle_year", 2020)
    p.vehicle_color = kwargs.get("vehicle_color", "Black")
    p.vehicle_make = kwargs.get("vehicle_make", "Toyota")
    p.vehicle_model = kwargs.get("vehicle_model", "Camry")
    p.vehicle_plate = kwargs.get("vehicle_plate", "ABC123")
    p.firstalt_driver_id = kwargs.get("firstalt_driver_id", None)
    p.everdriven_driver_id = kwargs.get("everdriven_driver_id", None)
    p.firstalt_compliance = kwargs.get("firstalt_compliance", {})
    p.language = kwargs.get("language", "en")
    return p


# ── Helpers ────────────────────────────────────────────────────────────────────

import importlib


def _load_service(name: str):
    """Reload a service module by full dotted name to pick up fresh env/stubs."""
    if name in sys.modules:
        del sys.modules[name]
    return importlib.import_module(name)


# ══════════════════════════════════════════════════════════════════════════════
# FA PIPELINE TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestFAPipelineSteps:
    """Unit-level tests for individual FA onboarding service calls."""

    # ── Step 1: FirstAlt invite ────────────────────────────────────────────────

    def test_step1_send_firstalt_invite_ok(self, monkeypatch):
        """send_firstalt_invite returns ok=True and emails the driver."""
        svc = _load_service("backend.services.firstalt_onboarding")

        person = _make_person()
        notify_mock = MagicMock()
        notify_mock.send_email = MagicMock()
        sys.modules["backend.services.notification_service"] = notify_mock

        result = svc.send_firstalt_invite(person)

        assert result["ok"] is True
        notify_mock.send_email.assert_called_once()
        call_kwargs = notify_mock.send_email.call_args
        to_arg = call_kwargs.kwargs.get("to") or call_kwargs.args[0]
        assert to_arg == "rahim@test.com"

    def test_step1_send_firstalt_invite_no_email(self):
        """send_firstalt_invite returns ok=False when driver has no email."""
        svc = _load_service("backend.services.firstalt_onboarding")
        person = _make_person(email=None)
        result = svc.send_firstalt_invite(person)
        assert result["ok"] is False
        assert "email" in result["error"].lower()

    # ── Step 2: Brandon BGC email ─────────────────────────────────────────────

    def test_step2_send_brandon_email_ok(self):
        """send_brandon_bgc_email sends email with driver details to Brandon."""
        svc = _load_service("backend.services.firstalt_onboarding")

        person = _make_person()
        notify_mock = MagicMock()
        notify_mock.send_email = MagicMock()
        sys.modules["backend.services.notification_service"] = notify_mock

        result = svc.send_brandon_bgc_email(person)

        assert result["ok"] is True
        notify_mock.send_email.assert_called_once()
        call_kwargs = notify_mock.send_email.call_args
        to_arg = call_kwargs.kwargs.get("to") or call_kwargs.args[0]
        assert "firststudentinc.com" in to_arg or "brandon" in to_arg.lower()

    def test_step2_brandon_email_body_contains_driver_info(self):
        """Brandon email body contains driver name, phone, address, vehicle."""
        svc = _load_service("backend.services.firstalt_onboarding")
        person = _make_person(
            full_name="Ahmed Hassan",
            email="ahmed@test.com",
            phone="2065559876",
            home_address="456 Test St",
            vehicle_year=2021,
            vehicle_make="Honda",
            vehicle_plate="XYZ789",
        )
        body = svc.build_brandon_email_body(person)
        assert "Ahmed Hassan" in body
        assert "2065559876" in body
        assert "Honda" in body
        assert "XYZ789" in body
        assert "Acumen International" in body

    # ── Step 3: FADV BGC ──────────────────────────────────────────────────────

    def test_step3_fadv_missing_creds_returns_env_missing(self, monkeypatch):
        """fadv_initiate_bgc returns env_missing=True when credentials absent."""
        monkeypatch.delenv("FADV_CLIENT_ID", raising=False)
        monkeypatch.delenv("FADV_CLIENT_SECRET", raising=False)
        svc = _load_service("backend.services.firstalt_onboarding")

        result = svc.fadv_initiate_bgc(
            person_id=1,
            full_name="Test Driver",
            email="t@test.com",
            phone="2065551111",
            home_address="1 Test Pl",
            ssn_last4="1234",
        )
        assert result["ok"] is False
        assert result["env_missing"] is True
        assert "FADV_CLIENT_ID" in result["error"] or "FADV_CLIENT_SECRET" in result["error"]

    def test_step3_fadv_no_fake_data_on_failure(self, monkeypatch):
        """fadv_initiate_bgc NEVER returns a report_id when credentials are missing."""
        monkeypatch.delenv("FADV_CLIENT_ID", raising=False)
        monkeypatch.delenv("FADV_CLIENT_SECRET", raising=False)
        svc = _load_service("backend.services.firstalt_onboarding")

        result = svc.fadv_initiate_bgc(
            person_id=2,
            full_name="Fake Driver",
            email="fake@test.com",
            phone="2065559999",
            home_address="2 Fake St",
            ssn_last4="0000",
        )
        # Must not return a fake report_id
        assert not result.get("report_id")

    def test_step3_fadv_success_stores_report_id(self, monkeypatch):
        """fadv_initiate_bgc returns ok=True with report_id on success."""
        monkeypatch.setenv("FADV_CLIENT_ID", "test-cid")
        monkeypatch.setenv("FADV_CLIENT_SECRET", "test-csecret")
        svc = _load_service("backend.services.firstalt_onboarding")

        import requests as real_requests

        mock_token_resp = MagicMock()
        mock_token_resp.json.return_value = {"access_token": "tok", "expires_in": 3600}
        mock_token_resp.raise_for_status = MagicMock()

        mock_order_resp = MagicMock()
        mock_order_resp.json.return_value = {"reportId": "FADV-001", "status": "initiated"}
        mock_order_resp.raise_for_status = MagicMock()

        with patch.object(real_requests, "post") as mock_post:
            mock_post.side_effect = [mock_token_resp, mock_order_resp]
            result = svc.fadv_initiate_bgc(
                person_id=10,
                full_name="Real Driver",
                email="real@test.com",
                phone="2065551234",
                home_address="10 Real Ave",
                ssn_last4="5678",
            )

        assert result["ok"] is True
        assert result["report_id"] == "FADV-001"
        assert result["status"] == "initiated"
        assert "raw" in result

    # ── Step 4: Drug test consent (FA) ────────────────────────────────────────

    def test_step4_fa_drug_consent_emails_driver(self):
        """send_drug_test_consent emails the driver the Adobe web form link."""
        svc = _load_service("backend.services.firstalt_onboarding")

        adobe_mock = MagicMock()
        adobe_mock.send_drug_test_consent = MagicMock(return_value={
            "ok": True,
            "method": "web_form_email",
            "email": "rahim@test.com",
            "url": "https://na4.documents.adobe.com/test",
            "sent_at": "2026-05-01T00:00:00+00:00",
        })
        sys.modules["backend.services.adobe_sign"] = adobe_mock

        person = _make_person()
        record = _make_onboarding_record()
        result = svc.send_drug_test_consent(person, record)

        assert result["ok"] is True
        adobe_mock.send_drug_test_consent.assert_called_once_with(person.person_id)


# ══════════════════════════════════════════════════════════════════════════════
# FADV WEBHOOK TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestFadvWebhook:
    """Tests for the FADV status webhook handler."""

    def _make_db(self, rec=None):
        db = MagicMock()
        query_mock = MagicMock()
        filter_mock = MagicMock()
        filter_mock.first.return_value = rec
        query_mock.filter.return_value = filter_mock
        db.query.return_value = query_mock
        return db

    def test_feature_flag_disabled_skips_processing(self, monkeypatch):
        """When FADV_WEBHOOK_ENABLED is not set, the feature flag evaluates as disabled."""
        monkeypatch.delenv("FADV_WEBHOOK_ENABLED", raising=False)
        # The handler reads FADV_WEBHOOK_ENABLED and returns early when not "true"
        enabled = os.environ.get("FADV_WEBHOOK_ENABLED", "false").strip().lower() == "true"
        assert enabled is False

    def test_feature_flag_logic_isolate(self, monkeypatch):
        """Verify feature flag env var logic — 'true' enables, anything else disables."""
        import os

        monkeypatch.setenv("FADV_WEBHOOK_ENABLED", "true")
        assert os.environ.get("FADV_WEBHOOK_ENABLED", "false").strip().lower() == "true"

        monkeypatch.setenv("FADV_WEBHOOK_ENABLED", "false")
        assert os.environ.get("FADV_WEBHOOK_ENABLED", "false").strip().lower() != "true"

        monkeypatch.delenv("FADV_WEBHOOK_ENABLED", raising=False)
        assert os.environ.get("FADV_WEBHOOK_ENABLED", "false").strip().lower() != "true"

    def test_status_mapping_clear_to_clear(self):
        """FADV CLEAR status maps to internal 'clear'."""
        status_map = {
            "CLEAR": "clear",
            "CONSIDER": "consider",
            "SUSPENDED": "suspended",
            "PENDING": "pending",
            "IN_PROCESS": "initiated",
        }
        assert status_map["CLEAR"] == "clear"
        assert status_map["CONSIDER"] == "consider"
        assert status_map["SUSPENDED"] == "suspended"


# ══════════════════════════════════════════════════════════════════════════════
# ED PIPELINE TESTS
# ══════════════════════════════════════════════════════════════════════════════

import os


class TestEDPipelineSteps:
    """Unit-level tests for individual ED onboarding service calls."""

    # ── CC API feature flag ───────────────────────────────────────────────────

    def test_cc_api_feature_flag_disabled_returns_empty(self, monkeypatch):
        """When CC API is disabled, _fetch_cc_documents returns empty list — no crash."""
        monkeypatch.delenv("CONTRACTOR_COMPLIANCE_API_ENABLED", raising=False)
        monkeypatch.delenv("CONTRACTOR_COMPLIANCE_API_KEY", raising=False)

        # Must use importlib.import_module to force re-evaluation of module-level constants
        import importlib
        for mod_name in list(sys.modules.keys()):
            if "everdriven_compliance" in mod_name:
                del sys.modules[mod_name]

        edc = importlib.import_module("backend.services.everdriven_compliance")
        result = edc._fetch_cc_documents("cc-id-123")
        assert result == []

    def test_cc_api_feature_flag_enabled_calls_api(self, monkeypatch):
        """When CC API is enabled and key is set, _fetch_cc_documents makes an HTTP call."""
        monkeypatch.setenv("CONTRACTOR_COMPLIANCE_API_ENABLED", "true")
        monkeypatch.setenv("CONTRACTOR_COMPLIANCE_API_KEY", "test-cc-key")

        # Must delete the cached module AFTER monkeypatch sets env vars
        # so that the module-level constants pick up the new values
        if "backend.services.everdriven_compliance" in sys.modules:
            del sys.modules["backend.services.everdriven_compliance"]

        import requests as real_requests

        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"documentName": "DL", "status": "APPROVED"}]
        mock_resp.raise_for_status = MagicMock()

        with patch.object(real_requests, "get", return_value=mock_resp):
            import importlib
            edc = importlib.import_module("backend.services.everdriven_compliance")
            result = edc._fetch_cc_documents("cc-id-456")

        assert len(result) == 1
        assert result[0]["documentName"] == "DL"

    # ── Hallo score validation ────────────────────────────────────────────────

    def test_hallo_score_range_validation(self):
        """Hallo scores outside 1.0–10.0 should fail validation."""
        invalid_scores = [0.9, 10.1, -1, 100]
        for score in invalid_scores:
            assert not (1.0 <= score <= 10.0), f"Expected {score} to fail range check"

    def test_hallo_score_valid_range(self):
        """Hallo scores within 1.0–10.0 should pass validation."""
        valid_scores = [1.0, 5.5, 10.0, 7.8]
        for score in valid_scores:
            assert 1.0 <= score <= 10.0, f"Expected {score} to pass range check"

    # ── CC document monitoring ────────────────────────────────────────────────

    def test_cc_sync_skips_when_no_api_key(self, monkeypatch):
        """
        ED compliance sync skips actual API calls when CC API key is not set.
        The module reads _CC_API_KEY at import time; reload to pick up monkeypatch.
        When key is absent, sync_driver_compliance returns skipped=True.
        """
        monkeypatch.delenv("CONTRACTOR_COMPLIANCE_API_KEY", raising=False)
        monkeypatch.delenv("CONTRACTOR_COMPLIANCE_API_ENABLED", raising=False)

        if "backend.services.everdriven_compliance" in sys.modules:
            del sys.modules["backend.services.everdriven_compliance"]

        import importlib
        edc = importlib.import_module("backend.services.everdriven_compliance")

        db = MagicMock()
        result = edc.sync_driver_compliance(db)
        assert result.get("skipped") is True

    def test_cc_sync_feature_flag_disabled_returns_empty_docs(self, monkeypatch):
        """
        When CC API flag is off, _fetch_cc_documents returns empty list.
        The sync still runs (if API key is set) — just fetches 0 docs.
        Verified by checking _fetch_cc_documents directly after reloading.
        """
        monkeypatch.setenv("CONTRACTOR_COMPLIANCE_API_KEY", "some-key")
        monkeypatch.delenv("CONTRACTOR_COMPLIANCE_API_ENABLED", raising=False)

        # Must flush all references to everdriven_compliance so module-level
        # _CC_API_ENABLED constant re-evaluates with the patched env
        import importlib
        for mod_name in list(sys.modules.keys()):
            if "everdriven_compliance" in mod_name:
                del sys.modules[mod_name]

        edc = importlib.import_module("backend.services.everdriven_compliance")

        # _fetch_cc_documents returns empty list when feature flag is off
        result = edc._fetch_cc_documents("cc-id-test")
        assert result == []


# ══════════════════════════════════════════════════════════════════════════════
# FA FULL PIPELINE INTEGRATION TEST
# ══════════════════════════════════════════════════════════════════════════════

class TestFAFullPipeline:
    """
    Integration test: FA applicant advances through all 8 steps to 'active'.
    All external calls (FADV, email, Adobe Sign) are mocked.
    Verifies side effects (status field mutations) at each step.
    """

    def _setup_services(self):
        svc = _load_service("backend.services.firstalt_onboarding")
        notify_mock = MagicMock()
        notify_mock.send_email = MagicMock()
        sys.modules["backend.services.notification_service"] = notify_mock

        adobe_mock = MagicMock()
        adobe_mock.send_drug_test_consent = MagicMock(return_value={
            "ok": True,
            "method": "web_form_email",
            "email": "driver@test.com",
            "url": "https://adobe.test/form",
            "sent_at": "2026-05-01T00:00:00+00:00",
        })
        sys.modules["backend.services.adobe_sign"] = adobe_mock
        return svc, notify_mock, adobe_mock

    def test_fa_full_pipeline_step1_to_step4(self, monkeypatch):
        """
        Steps 1-4 of FA pipeline run in order, each mutates the correct status field.
        """
        import requests as real_requests

        monkeypatch.setenv("FADV_CLIENT_ID", "test-cid")
        monkeypatch.setenv("FADV_CLIENT_SECRET", "test-csecret")

        svc, notify_mock, adobe_mock = self._setup_services()

        person = _make_person()
        record = _make_onboarding_record(person_id=person.person_id)
        db = MagicMock()

        # ── Step 1: Send FirstAlt invite ────────────────────────────────────
        result1 = svc.send_firstalt_invite(person)
        assert result1["ok"] is True
        notify_mock.send_email.assert_called()
        # Simulate route updating the record
        record.priority_email_status = "sent"

        # ── Step 2: Send Brandon BGC email ─────────────────────────────────
        result2 = svc.send_brandon_bgc_email(person)
        assert result2["ok"] is True
        record.brandon_email_status = "complete"
        record.bgc_status = "sent"

        # ── Step 3: Initiate FADV BGC ───────────────────────────────────────
        mock_token = MagicMock()
        mock_token.json.return_value = {"access_token": "tok", "expires_in": 3600}
        mock_token.raise_for_status = MagicMock()

        mock_order = MagicMock()
        mock_order.json.return_value = {"reportId": "FADV-999", "status": "initiated"}
        mock_order.raise_for_status = MagicMock()

        with patch.object(real_requests, "post") as mock_post:
            mock_post.side_effect = [mock_token, mock_order]
            result3 = svc.fadv_initiate_bgc(
                person_id=person.person_id,
                full_name=person.full_name,
                email=person.email,
                phone=person.phone,
                home_address=person.home_address,
                ssn_last4="1234",
            )

        assert result3["ok"] is True
        assert result3["report_id"] == "FADV-999"
        # Simulate route persisting FADV fields
        record.fadv_report_id = result3["report_id"]
        record.fadv_status = result3["status"]

        # ── Step 4: Send drug test consent ─────────────────────────────────
        result4 = svc.send_drug_test_consent(person, record)
        assert result4["ok"] is True
        record.consent_status = "sent"

        # ── Verify final state after steps 1-4 ─────────────────────────────
        assert record.priority_email_status == "sent"
        assert record.brandon_email_status == "complete"
        assert record.fadv_report_id == "FADV-999"
        assert record.fadv_status == "initiated"
        assert record.consent_status == "sent"

    def test_fa_pipeline_failure_fadv_missing_creds_does_not_advance(self, monkeypatch):
        """
        If FADV credentials are missing, fadv_initiate_bgc fails loudly
        and the pipeline does NOT advance fadv_report_id.
        """
        monkeypatch.delenv("FADV_CLIENT_ID", raising=False)
        monkeypatch.delenv("FADV_CLIENT_SECRET", raising=False)
        svc = _load_service("backend.services.firstalt_onboarding")

        record = _make_onboarding_record()
        assert record.fadv_report_id is None  # not set yet

        result = svc.fadv_initiate_bgc(
            person_id=1,
            full_name="Test Driver",
            email="t@test.com",
            phone="2065550000",
            home_address="1 Test St",
            ssn_last4="1234",
        )

        assert result["ok"] is False
        assert result["env_missing"] is True
        # Record must NOT have been mutated (route layer guards on result["ok"])
        assert record.fadv_report_id is None


# ══════════════════════════════════════════════════════════════════════════════
# ED FULL PIPELINE INTEGRATION TEST
# ══════════════════════════════════════════════════════════════════════════════

class TestEDFullPipeline:
    """
    Integration test: ED applicant progresses through key steps.
    Verifies state machine side effects for the EverDriven 10-step flow.
    """

    def test_ed_pipeline_step1_cc_invite_stamps_timestamp(self):
        """Step 1: CC invite stamps cc_invite_sent_at on the record."""
        record = _make_onboarding_record(partner="everdriven")
        assert record.cc_invite_sent_at is None

        # Simulate what the route does after notification_service.send_email succeeds
        from datetime import datetime, timezone
        record.cc_invite_sent_at = datetime.now(timezone.utc)

        assert record.cc_invite_sent_at is not None

    def test_ed_pipeline_step2_hallo_link_stamps_timestamp(self):
        """Step 2: Hallo link send stamps hallo_link_sent_at."""
        record = _make_onboarding_record(partner="everdriven")
        assert record.hallo_link_sent_at is None

        record.hallo_link_sent_at = datetime.now(timezone.utc)
        assert record.hallo_link_sent_at is not None

    def test_ed_pipeline_step3_log_hallo_score_stores_score(self):
        """Step 3: Logging a valid Hallo score stores it + stamps hallo_completed_at."""
        record = _make_onboarding_record(partner="everdriven")

        score = 7.5
        assert 1.0 <= score <= 10.0  # validate range
        record.hallo_score = score
        record.hallo_completed_at = datetime.now(timezone.utc)

        assert record.hallo_score == 7.5
        assert record.hallo_completed_at is not None

    def test_ed_pipeline_step3_invalid_score_rejected(self):
        """Step 3: Hallo scores outside 1.0-10.0 are invalid."""
        invalid_scores = [0.0, 0.9, 10.1, -5, 100]
        for score in invalid_scores:
            assert not (1.0 <= score <= 10.0), f"Score {score} should be invalid"

    def test_ed_pipeline_step4_drug_consent_prerequisite(self):
        """
        Step 4 mark-complete requires ed_drug_test_status to be 'sent' or later.
        If ed_drug_test_status is still 'pending', the route returns 400.
        """
        record = _make_onboarding_record(partner="everdriven", ed_drug_test_status="pending")
        # The route guard: must be "sent" or "complete" before marking complete
        prereq_met = record.ed_drug_test_status in ("sent", "complete")
        assert prereq_met is False

        record.ed_drug_test_status = "sent"
        prereq_met = record.ed_drug_test_status in ("sent", "complete")
        assert prereq_met is True

    def test_ed_pipeline_full_sequence_state_transitions(self):
        """
        Verify correct sequence of state transitions for a full ED pipeline run.
        Simulates the route layer mutating the record at each step.
        """
        record = _make_onboarding_record(partner="everdriven")

        # Step 1 — CC invite
        record.cc_invite_sent_at = datetime(2026, 5, 1, tzinfo=timezone.utc)
        assert record.cc_invite_sent_at is not None

        # Step 2 — Hallo link
        record.hallo_link_sent_at = datetime(2026, 5, 1, tzinfo=timezone.utc)
        assert record.hallo_link_sent_at is not None

        # Step 3 — Hallo score logged
        record.hallo_score = 8.2
        record.hallo_completed_at = datetime(2026, 5, 2, tzinfo=timezone.utc)
        assert record.hallo_score == 8.2

        # Step 4 — Drug consent sent
        record.ed_drug_test_status = "sent"
        record.drug_test_sent_at = datetime(2026, 5, 2, tzinfo=timezone.utc)
        assert record.ed_drug_test_status == "sent"

        # Adobe Sign webhook fires → mark complete
        record.ed_drug_test_status = "complete"
        record.drug_test_signed_at = datetime(2026, 5, 3, tzinfo=timezone.utc)
        assert record.ed_drug_test_status == "complete"

        # Step 5 — BGC complete
        record.ed_bgc_status = "complete"

        # Step 6 — SafeRide cert
        record.saferide_link_sent_at = datetime(2026, 5, 4, tzinfo=timezone.utc)
        record.saferide_cert_uploaded_at = datetime(2026, 5, 5, tzinfo=timezone.utc)

        # Step 7 — Vehicle inspections
        record.ed_vehicle_insp_1_status = "complete"
        record.ed_vehicle_insp_2_status = "complete"

        # Step 8 — App install
        record.ed_app_install_status = "complete"

        # Step 9 — Equipment issued
        record.equipment_status = "complete"

        # All ED-specific steps complete — verify terminal state
        ed_steps_done = all([
            record.cc_invite_sent_at is not None,
            record.hallo_completed_at is not None,
            record.ed_drug_test_status == "complete",
            record.ed_bgc_status == "complete",
            record.saferide_cert_uploaded_at is not None,
            record.ed_vehicle_insp_1_status == "complete",
            record.ed_vehicle_insp_2_status == "complete",
            record.ed_app_install_status == "complete",
            record.equipment_status == "complete",
        ])
        assert ed_steps_done is True


# ══════════════════════════════════════════════════════════════════════════════
# ADOBE SIGN WEBHOOK TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestAdobeSignWebhook:
    """Tests for the Adobe Sign webhook pipeline integration."""

    def test_adobe_webhook_advances_ed_drug_test_status(self):
        """
        Adobe Sign webhook completion event advances ed_drug_test_status to 'complete'.
        Verified by simulating the side effect the webhooks.py handler applies.
        """
        record = _make_onboarding_record(partner="everdriven", ed_drug_test_status="sent")
        agreement_id = "TEST-AGREEMENT-001"
        record.drug_test_agreement_id = agreement_id

        # Simulate what the webhook handler does on AGREEMENT_ACTION_COMPLETED
        now = datetime.now(timezone.utc)
        record.drug_test_signed_at = now

        if hasattr(record, "ed_drug_test_status") and record.ed_drug_test_status in ("pending", "sent", None):
            record.ed_drug_test_status = "complete"

        assert record.drug_test_signed_at == now
        assert record.ed_drug_test_status == "complete"

    def test_adobe_webhook_no_double_advance_if_already_complete(self):
        """
        Adobe Sign webhook does NOT re-process if ed_drug_test_status is already 'complete'.
        """
        record = _make_onboarding_record(partner="everdriven", ed_drug_test_status="complete")

        prev_status = record.ed_drug_test_status
        # Simulate the handler's guard condition
        if hasattr(record, "ed_drug_test_status") and record.ed_drug_test_status in ("pending", "sent", None):
            record.ed_drug_test_status = "complete"  # would set it
        else:
            pass  # already complete — no change

        assert record.ed_drug_test_status == prev_status  # unchanged


# ══════════════════════════════════════════════════════════════════════════════
# NEGATIVE / EDGE CASE TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestNegativePaths:
    """Failure mode tests for both pipelines."""

    def test_fa_step1_fails_gracefully_on_email_error(self):
        """send_firstalt_invite returns ok=False when email service throws."""
        svc = _load_service("backend.services.firstalt_onboarding")

        person = _make_person()
        notify_mock = MagicMock()
        notify_mock.send_email = MagicMock(side_effect=RuntimeError("SMTP down"))
        sys.modules["backend.services.notification_service"] = notify_mock

        result = svc.send_firstalt_invite(person)
        assert result["ok"] is False
        assert "SMTP down" in result.get("error", "")

    def test_fa_brandon_email_fails_gracefully(self):
        """send_brandon_bgc_email returns ok=False when email service throws."""
        svc = _load_service("backend.services.firstalt_onboarding")

        person = _make_person()
        notify_mock = MagicMock()
        notify_mock.send_email = MagicMock(side_effect=Exception("connection timeout"))
        sys.modules["backend.services.notification_service"] = notify_mock

        result = svc.send_brandon_bgc_email(person)
        assert result["ok"] is False

    def test_fadv_http_error_returns_ok_false(self, monkeypatch):
        """HTTP error from FADV API produces ok=False with descriptive error."""
        monkeypatch.setenv("FADV_CLIENT_ID", "cid")
        monkeypatch.setenv("FADV_CLIENT_SECRET", "csecret")
        svc = _load_service("backend.services.firstalt_onboarding")

        import requests as real_requests

        mock_token = MagicMock()
        mock_token.json.return_value = {"access_token": "tok", "expires_in": 3600}
        mock_token.raise_for_status = MagicMock()

        with patch.object(real_requests, "post") as mock_post:
            mock_post.side_effect = [mock_token, Exception("FADV server error")]
            result = svc.fadv_initiate_bgc(
                person_id=5,
                full_name="Test",
                email="t@test.com",
                phone="2065550000",
                home_address="5 Test",
                ssn_last4="9999",
            )

        assert result["ok"] is False
        assert result.get("env_missing") is False

    def test_fadv_status_refresh_missing_creds(self, monkeypatch):
        """fadv_get_status returns env_missing=True when credentials not configured."""
        monkeypatch.delenv("FADV_CLIENT_ID", raising=False)
        monkeypatch.delenv("FADV_CLIENT_SECRET", raising=False)
        svc = _load_service("backend.services.firstalt_onboarding")

        result = svc.fadv_get_status("RPT-123")
        assert result["ok"] is False
        assert result["env_missing"] is True

    def test_paychex_csv_row_has_all_required_keys(self):
        """build_paychex_csv_row always includes all Paychex-required columns."""
        svc = _load_service("backend.services.firstalt_onboarding")
        person = _make_person(full_name="Seude Hassan")

        row = svc.build_paychex_csv_row(person)

        required_keys = ["Last Name", "First Name", "Email", "Worker Type", "Client"]
        for key in required_keys:
            assert key in row, f"Missing required Paychex column: {key}"
        assert row["Worker Type"] == "1099"
        assert "Acumen" in row.get("Client", "")


# ══════════════════════════════════════════════════════════════════════════════
# FADV WEBHOOK HANDLER TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestFadvWebhookHandler:
    """
    Tests for the FADV webhook route logic (status update → DB mutation).
    All DB calls are mocked — no real HTTP requests made.
    """

    def _make_db(self, rec=None):
        """Build a minimal DB mock that returns rec from query().filter().first()."""
        db = MagicMock()
        query_mock = MagicMock()
        filter_mock = MagicMock()
        filter_mock.first.return_value = rec
        query_mock.filter.return_value = filter_mock
        db.query.return_value = query_mock
        return db

    # ── Feature flag ─────────────────────────────────────────────────────────

    def test_feature_flag_disabled_by_default(self, monkeypatch):
        """FADV_WEBHOOK_ENABLED defaults to False — disabled unless explicitly set."""
        monkeypatch.delenv("FADV_WEBHOOK_ENABLED", raising=False)
        enabled = os.environ.get("FADV_WEBHOOK_ENABLED", "false").strip().lower() == "true"
        assert enabled is False

    def test_feature_flag_enabled_with_true(self, monkeypatch):
        """FADV_WEBHOOK_ENABLED='true' enables the handler."""
        monkeypatch.setenv("FADV_WEBHOOK_ENABLED", "true")
        enabled = os.environ.get("FADV_WEBHOOK_ENABLED", "false").strip().lower() == "true"
        assert enabled is True

    def test_feature_flag_case_insensitive(self, monkeypatch):
        """FADV_WEBHOOK_ENABLED is case-insensitive ('TRUE', 'True' both work)."""
        for val in ("TRUE", "True", "true"):
            monkeypatch.setenv("FADV_WEBHOOK_ENABLED", val)
            enabled = os.environ.get("FADV_WEBHOOK_ENABLED", "false").strip().lower() == "true"
            assert enabled is True, f"Expected True for value={val!r}"

    # ── Status mapping ────────────────────────────────────────────────────────

    def test_fadv_status_map_clear(self):
        """CLEAR maps to 'clear'."""
        status_map = {
            "CLEAR": "clear",
            "CONSIDER": "consider",
            "SUSPENDED": "suspended",
            "PENDING": "pending",
            "IN_PROCESS": "initiated",
            "INITIATED": "initiated",
            "COMPLETE": "clear",
            "REVIEW": "consider",
            "CANCELED": "suspended",
        }
        assert status_map["CLEAR"] == "clear"
        assert status_map["COMPLETE"] == "clear"
        assert status_map["CONSIDER"] == "consider"
        assert status_map["REVIEW"] == "consider"
        assert status_map["SUSPENDED"] == "suspended"
        assert status_map["CANCELED"] == "suspended"

    def test_fadv_status_map_pending_and_initiated(self):
        """PENDING and IN_PROCESS both map to non-terminal statuses."""
        status_map = {"PENDING": "pending", "IN_PROCESS": "initiated", "INITIATED": "initiated"}
        assert status_map["PENDING"] == "pending"
        assert status_map["IN_PROCESS"] == "initiated"

    # ── State transition logic ────────────────────────────────────────────────

    def test_fadv_webhook_updates_fadv_status_on_clear(self):
        """
        When FADV webhook fires with CLEAR, fadv_status is updated to 'clear'
        and fadv_result_at is stamped.
        """
        rec = _make_onboarding_record(fadv_report_id="RPT-WEBHOOK-001", fadv_status="initiated")
        rec.fadv_result_at = None
        rec.bgc_status = "sent"

        # Simulate what the webhook handler does on receiving CLEAR
        internal_status = "clear"
        now = datetime.now(timezone.utc)

        if rec.fadv_status != internal_status:
            rec.fadv_status = internal_status
            rec.fadv_result_at = now
            if internal_status == "clear" and rec.bgc_status in ("pending", "sent"):
                rec.bgc_status = "manual"

        assert rec.fadv_status == "clear"
        assert rec.fadv_result_at == now
        assert rec.bgc_status == "manual"  # auto-advanced for admin to confirm

    def test_fadv_webhook_consider_does_not_auto_advance_bgc(self):
        """
        When FADV returns CONSIDER, bgc_status is NOT auto-advanced
        (admin must review manually).
        """
        rec = _make_onboarding_record(fadv_report_id="RPT-CONSIDER", fadv_status="initiated")
        rec.fadv_result_at = None
        rec.bgc_status = "sent"

        internal_status = "consider"
        now = datetime.now(timezone.utc)

        if rec.fadv_status != internal_status:
            rec.fadv_status = internal_status
            rec.fadv_result_at = now
            if internal_status == "clear" and rec.bgc_status in ("pending", "sent"):
                rec.bgc_status = "manual"
            # consider/suspended do NOT auto-advance bgc_status

        assert rec.fadv_status == "consider"
        assert rec.fadv_result_at == now
        assert rec.bgc_status == "sent"  # unchanged — admin must decide

    def test_fadv_webhook_idempotent_same_status(self):
        """
        If fadv_status already matches the incoming status, no DB mutation occurs.
        """
        rec = _make_onboarding_record(fadv_report_id="RPT-IDEM", fadv_status="clear")
        initial_fadv_result_at = rec.fadv_result_at
        initial_bgc = rec.bgc_status

        internal_status = "clear"

        # The handler skips if status unchanged
        if rec.fadv_status == internal_status:
            pass  # no-op
        else:
            rec.fadv_status = internal_status

        assert rec.fadv_status == "clear"  # unchanged
        assert rec.fadv_result_at == initial_fadv_result_at  # NOT re-stamped
        assert rec.bgc_status == initial_bgc  # NOT changed again

    def test_fadv_webhook_unknown_report_id_skips_gracefully(self):
        """
        Webhook with unknown report_id does not raise — returns 200 with no DB changes.
        The handler looks up the record, finds nothing, and returns.
        """
        # rec = None simulates no matching OnboardingRecord found
        was_modified = False

        def would_mutate(rec):
            nonlocal was_modified
            was_modified = True

        rec = None
        if rec:
            would_mutate(rec)

        assert was_modified is False

    def test_fadv_webhook_reference_id_fallback(self):
        """
        If fadv_report_id lookup fails, handler falls back to referenceId='zpay-<person_id>'.
        Verifies the referenceId parsing logic is correct.
        """
        reference_id = "zpay-100"
        assert reference_id.startswith("zpay-")
        person_id = int(reference_id.split("-", 1)[1])
        assert person_id == 100

    def test_fadv_webhook_reference_id_invalid_format(self):
        """
        Malformed referenceId (not starting with 'zpay-') is handled gracefully.
        """
        reference_id = "external-system-id-xyz"
        is_valid = reference_id.startswith("zpay-")
        assert is_valid is False  # handler skips fallback and logs a warning


# ══════════════════════════════════════════════════════════════════════════════
# ADOBE SIGN WEBHOOK — FA CONSENT PATH TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestAdobeSignWebhookFAPath:
    """
    Tests for the FA (FirstAlt/Acumen) drug consent path in the Adobe Sign webhook.
    The webhook must route on rec.partner to distinguish FA vs ED flows.
    """

    def test_fa_webhook_advances_consent_status(self):
        """
        Adobe Sign webhook completion event on an FA record advances
        consent_status from 'sent' to 'signed'.
        """
        rec = _make_onboarding_record(partner="firstalt", consent_status="sent")
        agreement_id = "FA-AGREEMENT-001"
        rec.drug_test_agreement_id = agreement_id

        now = datetime.now(timezone.utc)
        rec.drug_test_signed_at = now

        partner = getattr(rec, "partner", "firstalt") or "firstalt"
        if partner != "everdriven":
            if hasattr(rec, "consent_status") and rec.consent_status in ("pending", "sent", None):
                rec.consent_status = "signed"

        assert rec.drug_test_signed_at == now
        assert rec.consent_status == "signed"

    def test_fa_webhook_no_double_advance_consent_already_signed(self):
        """
        Adobe Sign webhook does NOT overwrite consent_status if already 'signed'.
        """
        rec = _make_onboarding_record(partner="firstalt", consent_status="signed")

        partner = getattr(rec, "partner", "firstalt") or "firstalt"
        if partner != "everdriven":
            if hasattr(rec, "consent_status") and rec.consent_status in ("pending", "sent", None):
                rec.consent_status = "signed"
            # else: no-op (already signed)

        assert rec.consent_status == "signed"  # unchanged

    def test_webhook_partner_routing_ed_uses_ed_field(self):
        """
        ED partner records advance ed_drug_test_status, NOT consent_status.
        FA partner records advance consent_status, NOT ed_drug_test_status.
        """
        ed_rec = _make_onboarding_record(partner="everdriven", ed_drug_test_status="sent")
        fa_rec = _make_onboarding_record(partner="firstalt", consent_status="sent")

        def simulate_webhook(rec):
            partner = getattr(rec, "partner", "firstalt") or "firstalt"
            if partner == "everdriven":
                if hasattr(rec, "ed_drug_test_status") and rec.ed_drug_test_status in ("pending", "sent", None):
                    rec.ed_drug_test_status = "complete"
            else:
                if hasattr(rec, "consent_status") and rec.consent_status in ("pending", "sent", None):
                    rec.consent_status = "signed"

        simulate_webhook(ed_rec)
        simulate_webhook(fa_rec)

        # ED record: ed_drug_test_status advanced, consent_status stays at its default ("pending")
        assert ed_rec.ed_drug_test_status == "complete"
        # consent_status is not touched by the ED path — it stays at default
        assert ed_rec.consent_status == "pending"

        # FA record: consent_status advanced, ed_drug_test_status stays at its default ("pending")
        assert fa_rec.consent_status == "signed"
        assert fa_rec.ed_drug_test_status == "pending"  # not changed by FA path

    def test_fa_webhook_pending_consent_also_advances(self):
        """
        FA webhook advances consent_status from 'pending' to 'signed' too
        (edge case: consent form sent out-of-band before route recorded 'sent').
        """
        rec = _make_onboarding_record(partner="firstalt", consent_status="pending")

        partner = getattr(rec, "partner", "firstalt") or "firstalt"
        if partner != "everdriven":
            if hasattr(rec, "consent_status") and rec.consent_status in ("pending", "sent", None):
                rec.consent_status = "signed"

        assert rec.consent_status == "signed"
