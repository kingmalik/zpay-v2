"""
Tests for onboarder_tools.py — read-only driver onboarding status helpers.

All tests use mocked DB sessions or in-memory SQLite fixtures.
No live DB connections, no Anthropic calls.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from backend.services.onboarder_tools import (
    get_bgc_status,
    get_cc_status,
    get_onboarding_status,
    list_pending_onboarding,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def _make_person(person_id: int = 1, full_name: str = "Rahim Osei") -> MagicMock:
    p = MagicMock()
    p.person_id = person_id
    p.full_name = full_name
    return p


def _make_record(**kwargs) -> MagicMock:
    """Build a minimal OnboardingRecord mock with sensible defaults."""
    rec = MagicMock()
    rec.person_id = kwargs.get("person_id", 1)
    rec.intake_submitted_at = kwargs.get("intake_submitted_at", datetime(2026, 4, 1, tzinfo=timezone.utc))
    rec.fadv_status = kwargs.get("fadv_status", "initiated")
    rec.fadv_report_id = kwargs.get("fadv_report_id", "RPT-001")
    rec.fadv_initiated_at = kwargs.get("fadv_initiated_at", datetime(2026, 4, 2, tzinfo=timezone.utc))
    rec.fadv_result_at = kwargs.get("fadv_result_at", None)
    rec.bgc_status = kwargs.get("bgc_status", "pending")
    rec.contract_status = kwargs.get("contract_status", "pending")
    rec.cc_invite_sent_at = kwargs.get("cc_invite_sent_at", None)
    rec.cc_id = kwargs.get("cc_id", None)
    rec.cc_status = kwargs.get("cc_status", None)
    rec.priority_email_status = kwargs.get("priority_email_status", "pending")
    rec.started_at = kwargs.get("started_at", datetime(2026, 4, 1, tzinfo=timezone.utc))
    rec.completed_at = kwargs.get("completed_at", None)
    rec.notes = kwargs.get("notes", None)
    rec.partner = kwargs.get("partner", "firstalt")
    return rec


def _mock_db(person: MagicMock | None, record: MagicMock | None) -> MagicMock:
    """Return a mock Session whose .query().filter().first() chain resolves correctly."""
    db = MagicMock()

    def query_side_effect(model):
        from backend.db.models import OnboardingRecord, Person
        q = MagicMock()
        if model is Person:
            q.filter.return_value.first.return_value = person
        elif model is OnboardingRecord:
            q.filter.return_value.first.return_value = record
        else:
            q.filter.return_value.first.return_value = None
        return q

    db.query.side_effect = query_side_effect
    return db


# ─── Test 1: get_onboarding_status — driver mid-onboarding ────────────────────

def test_get_onboarding_status_mid_onboarding():
    """Returns correct step for a driver who has applied and placed BGC but not cleared."""
    person = _make_person(person_id=10, full_name="Rahim Osei")
    # BGC initiated but not cleared → stuck at step 3
    rec = _make_record(
        person_id=10,
        fadv_status="initiated",
        bgc_status="pending",
    )
    db = _mock_db(person, rec)

    result = get_onboarding_status(db, 10)

    assert result["person_id"] == 10
    assert result["name"] == "Rahim Osei"
    assert result["step"] == 3
    assert result["status"] == "in_progress"
    assert "Next:" not in result.get("step_name", "")   # step_name is a label, not a sentence
    assert result["next_action"] != ""


# ─── Test 2: get_onboarding_status — no onboarding record ─────────────────────

def test_get_onboarding_status_not_started():
    """Returns 'not_started' for a driver who has no onboarding record."""
    person = _make_person(person_id=99, full_name="Dawit Bekele")
    db = _mock_db(person, record=None)

    result = get_onboarding_status(db, 99)

    assert result["status"] == "not_started"
    assert result["step"] == 0
    assert result["name"] == "Dawit Bekele"
    assert "next_action" in result


# ─── Test 3: list_pending_onboarding — only incomplete, sorted ────────────────

def test_list_pending_onboarding_returns_incomplete_sorted():
    """Returns only incomplete drivers, sorted by days stuck (longest first)."""
    db = MagicMock()

    # Two mock rows from the DB query
    older_row = MagicMock()
    older_row.person_id = 1
    older_row.full_name = "Rahim Osei"
    older_row.started_at = datetime(2026, 3, 1, tzinfo=timezone.utc)   # older
    older_row.intake_submitted_at = datetime(2026, 3, 1, tzinfo=timezone.utc)
    older_row.fadv_status = "initiated"
    older_row.bgc_status = "pending"
    older_row.contract_status = "pending"
    older_row.cc_invite_sent_at = None
    older_row.cc_id = None
    older_row.priority_email_status = "pending"
    older_row.notes = None
    older_row.partner = "firstalt"

    newer_row = MagicMock()
    newer_row.person_id = 2
    newer_row.full_name = "Dawit Bekele"
    newer_row.started_at = datetime(2026, 4, 20, tzinfo=timezone.utc)  # newer
    newer_row.intake_submitted_at = datetime(2026, 4, 20, tzinfo=timezone.utc)
    newer_row.fadv_status = "initiated"
    newer_row.bgc_status = "pending"
    newer_row.contract_status = "pending"
    newer_row.cc_invite_sent_at = None
    newer_row.cc_id = None
    newer_row.priority_email_status = "pending"
    newer_row.notes = None
    newer_row.partner = "firstalt"

    # DB returns newer first (as if ORDER BY started_at ASC), we expect sort to fix it
    db.execute.return_value.fetchall.return_value = [newer_row, older_row]

    result = list_pending_onboarding(db, limit=20)

    assert result["count"] == 2
    # Oldest (most stuck) must come first
    assert result["drivers"][0]["person_id"] == 1
    assert result["drivers"][1]["person_id"] == 2


# ─── Test 4: list_pending_onboarding — respects limit param ──────────────────

def test_list_pending_onboarding_respects_limit():
    """The limit parameter is passed through to the SQL query."""
    db = MagicMock()
    db.execute.return_value.fetchall.return_value = []

    list_pending_onboarding(db, limit=5)

    call_args = db.execute.call_args
    # Verify 'limit' value was passed as a bind parameter
    assert call_args is not None
    bound_params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("params", {})
    # The second positional arg to db.execute is the params dict
    params = call_args[0][1]
    assert params.get("limit") == 5


# ─── Test 5: get_bgc_status — order_id present ───────────────────────────────

def test_get_bgc_status_with_order_id():
    """Returns fadv_report_id and status when BGC has been submitted."""
    person = _make_person(person_id=5, full_name="Nuraynie Mohammed")
    rec = _make_record(
        person_id=5,
        fadv_report_id="FADV-XYZ-789",
        fadv_status="clear",
        fadv_initiated_at=datetime(2026, 4, 10, tzinfo=timezone.utc),
        fadv_result_at=datetime(2026, 4, 12, tzinfo=timezone.utc),
    )
    db = _mock_db(person, rec)

    result = get_bgc_status(db, 5)

    assert result["bgc_submitted"] is True
    assert result["fadv_report_id"] == "FADV-XYZ-789"
    assert result["fadv_status"] == "clear"
    assert result["initiated_at"] is not None
    assert result["result_at"] is not None


# ─── Test 6: get_bgc_status — fadv_bgc_order_id is null ─────────────────────

def test_get_bgc_status_not_submitted():
    """Returns 'Not submitted yet' when fadv_report_id is null."""
    person = _make_person(person_id=7, full_name="Seude Hassan")
    rec = _make_record(
        person_id=7,
        fadv_report_id=None,
        fadv_status=None,
        fadv_initiated_at=None,
        fadv_result_at=None,
    )
    db = _mock_db(person, rec)

    result = get_bgc_status(db, 7)

    assert result["bgc_submitted"] is False
    assert result["fadv_report_id"] is None
    assert result["fadv_status"] == "Not submitted yet"


# ─── Test 7: get_onboarding_status — driver not found ─────────────────────────

def test_get_onboarding_status_unknown_person():
    """Returns an error dict when person_id does not exist."""
    db = _mock_db(person=None, record=None)

    result = get_onboarding_status(db, 9999)

    assert "error" in result


# ─── Test 8: get_cc_status — invite sent but no profile yet ──────────────────

def test_get_cc_status_invite_sent_no_profile():
    """Returns invite_sent=True and cc_profile_active=False when invite sent but cc_id not set."""
    person = _make_person(person_id=3, full_name="Kalkidan Tesfaye")
    rec = _make_record(
        person_id=3,
        cc_invite_sent_at=datetime(2026, 4, 15, tzinfo=timezone.utc),
        cc_id=None,
    )
    db = _mock_db(person, rec)

    result = get_cc_status(db, 3)

    assert result["invite_sent"] is True
    assert result["cc_profile_active"] is False
    assert result["cc_id"] is None
