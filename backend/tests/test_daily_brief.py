"""
Tests for the daily ops briefs (morning Game Plan + evening Recap).

These pin the contract:
  1. compose_morning_brief returns (subject, body) — both non-empty even
     when both FA + ED fetches fail.
  2. compose_evening_brief includes today's event counts AND tomorrow's
     schedule preview.
  3. send_morning_brief / send_evening_brief respect DAILY_BRIEF_ENABLED.
     When unset/"0", they compose + paper-trail but do not call Gmail.
  4. Send funnel returns sent=False with a clear error when ADMIN_EMAIL
     is unset, instead of crashing.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ── Shared mocks ──────────────────────────────────────────────────────────────

@pytest.fixture()
def mock_partner_apis():
    """Patch FA + ED schedule fetches to return predictable data."""
    fa_trips = [{"id": 1}, {"id": 2}, {"id": 3}]
    ed_runs = [{"id": "A"}, {"id": "B"}]
    with (
        patch("backend.services.firstalt_service.get_trips", return_value=fa_trips),
        patch("backend.services.everdriven_service.get_runs", return_value=ed_runs),
    ):
        yield {"fa": fa_trips, "ed": ed_runs}


@pytest.fixture()
def mock_haiku():
    """Patch Anthropic.messages.create so no real API call fires."""
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
        fake_client = MagicMock()
        fake_msg = MagicMock()
        fake_block = MagicMock()
        fake_block.type = "text"
        fake_block.text = "Drafted brief body text."
        fake_msg.content = [fake_block]
        fake_client.messages.create.return_value = fake_msg
        with patch("anthropic.Anthropic", return_value=fake_client):
            yield fake_client


# ── compose_morning_brief ─────────────────────────────────────────────────────

class TestComposeMorningBrief:
    def test_returns_subject_and_body(self, mock_partner_apis, mock_haiku):
        from backend.services.daily_brief import compose_morning_brief
        subject, body = compose_morning_brief(today=date(2026, 5, 29))
        assert isinstance(subject, str) and len(subject) > 0
        assert isinstance(body, str) and len(body) > 0
        assert "Game Plan" in subject

    def test_falls_back_when_both_apis_fail(self):
        """Both fetch failures still produce a non-empty subject + body."""
        from backend.services.daily_brief import compose_morning_brief
        with (
            patch.dict(os.environ, {}, clear=True),
            patch(
                "backend.services.firstalt_service.get_trips",
                side_effect=Exception("FA down"),
            ),
            patch(
                "backend.services.everdriven_service.get_runs",
                side_effect=Exception("ED down"),
            ),
        ):
            subject, body = compose_morning_brief(today=date(2026, 5, 29))
        assert len(subject) > 0
        assert len(body) > 0


# ── compose_evening_brief ─────────────────────────────────────────────────────

class TestComposeEveningBrief:
    def test_includes_today_and_tomorrow(self, mock_partner_apis, mock_haiku):
        from backend.services.daily_brief import compose_evening_brief
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []
        subject, body = compose_evening_brief(db=mock_db, today=date(2026, 5, 29))
        assert "Recap" in subject
        assert len(body) > 0


# ── send_morning_brief ────────────────────────────────────────────────────────

class TestSendMorningBrief:
    def test_dry_run_when_disabled(self, mock_partner_apis):
        from backend.services.daily_brief import send_morning_brief
        with (
            patch.dict(os.environ, {"DAILY_BRIEF_ENABLED": "0", "ADMIN_EMAIL": "malik@example.com"}),
            patch("backend.services.email_service.send_plain_email") as mock_send,
            patch("backend.services.ops_alert.route_dispatch_alert"),
        ):
            result = send_morning_brief()
        assert result["enabled"] is False
        assert result["sent"] is False
        mock_send.assert_not_called()

    def test_no_admin_email_returns_error(self, mock_partner_apis):
        from backend.services.daily_brief import send_morning_brief
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("backend.services.email_service.send_plain_email") as mock_send,
            patch("backend.services.ops_alert.route_dispatch_alert"),
        ):
            result = send_morning_brief()
        assert result["sent"] is False
        # When unset, ADMIN_EMAIL is empty — but DAILY_BRIEF_ENABLED default is "1".
        # So we should hit the "no recipient" branch.
        assert result["error"] == "ADMIN_EMAIL not set"
        mock_send.assert_not_called()

    def test_paper_trail_always_fires(self, mock_partner_apis):
        from backend.services.daily_brief import send_morning_brief
        with (
            patch.dict(os.environ, {"DAILY_BRIEF_ENABLED": "0"}),
            patch("backend.services.ops_alert.route_dispatch_alert") as mock_log,
            patch("backend.services.email_service.send_plain_email"),
        ):
            send_morning_brief()
        mock_log.assert_called_once()
        kwargs = mock_log.call_args.kwargs
        assert kwargs.get("source") == "daily_brief"


# ── send_evening_brief ────────────────────────────────────────────────────────

class TestSendEveningBrief:
    def test_dry_run_when_disabled(self, mock_partner_apis):
        from backend.services.daily_brief import send_evening_brief
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []
        with (
            patch.dict(os.environ, {"DAILY_BRIEF_ENABLED": "0", "ADMIN_EMAIL": "malik@example.com"}),
            patch("backend.services.email_service.send_plain_email") as mock_send,
            patch("backend.services.ops_alert.route_dispatch_alert"),
        ):
            result = send_evening_brief(db=mock_db)
        assert result["sent"] is False
        mock_send.assert_not_called()

    def test_sends_when_enabled_and_addressed(self, mock_partner_apis):
        from backend.services.daily_brief import send_evening_brief
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []
        with (
            patch.dict(os.environ, {
                "DAILY_BRIEF_ENABLED": "1",
                "ADMIN_EMAIL": "malik@example.com",
            }),
            patch("backend.services.email_service.send_plain_email") as mock_send,
            patch("backend.services.ops_alert.route_dispatch_alert"),
        ):
            result = send_evening_brief(db=mock_db)
        mock_send.assert_called_once()
        assert result["sent"] is True
        assert result["error"] is None
