"""
Tests for the Phase B auto-driver-checkin agent layer.

These tests pin the safety contract:
  1. compose_driver_checkin returns a non-empty string even without an API key
     (static fallback) — never returns None.
  2. handle_flagged_trip defaults to dry-run (DRIVER_AUTOCHECKIN_ENABLED unset
     or != "1") — no WhatsApp send happens, sent=False, dry_run=True.
  3. handle_flagged_trip writes a paper-trail row via route_dispatch_alert
     regardless of dry-run / send outcome.
  4. handle_flagged_trip refuses to send when the driver has no number,
     even with the env flag enabled.
  5. handle_flagged_trip with the env flag enabled AND a driver number calls
     send_whatsapp once with the drafted message.

The Anthropic client is patched out everywhere so no real API calls fire.
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


class TestComposeDriverCheckin:
    def test_returns_string_without_api_key(self):
        from backend.services.dispatch_agent import compose_driver_checkin
        with patch.dict(os.environ, {}, clear=True):
            draft = compose_driver_checkin(
                driver_first_name="Amanuel",
                trip_label="8am Maplewood pickup",
                minutes_until_pickup=15,
                reason="hasn't tapped accept",
            )
        assert isinstance(draft, str)
        assert len(draft) > 0

    def test_fallback_mentions_trip_label(self):
        from backend.services.dispatch_agent import compose_driver_checkin
        with patch.dict(os.environ, {}, clear=True):
            draft = compose_driver_checkin(
                driver_first_name="Yonas",
                trip_label="3pm Scenic Hill dropoff",
                minutes_until_pickup=-10,
                reason="pickup time passed",
            )
        # Fallback should at least mention the trip
        assert "Scenic Hill" in draft or "dropoff" in draft

    def test_never_returns_none_even_on_api_error(self):
        from backend.services.dispatch_agent import compose_driver_checkin
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
            with patch("anthropic.Anthropic", side_effect=Exception("network down")):
                draft = compose_driver_checkin(
                    driver_first_name="Test",
                    trip_label="test trip",
                    minutes_until_pickup=5,
                    reason="testing",
                )
        assert isinstance(draft, str)
        assert len(draft) > 0


class TestHandleFlaggedTripDryRunDefault:
    """The locked safety rule: no driver-facing message unless env explicitly flips."""

    def test_dry_run_when_env_unset(self):
        from backend.services.dispatch_agent import handle_flagged_trip
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("backend.services.ops_alert.route_dispatch_alert"),
        ):
            result = handle_flagged_trip(
                db=MagicMock(),
                driver_first_name="Amanuel",
                driver_whatsapp_number="+15555550100",
                trip_label="8am Maplewood pickup",
                trip_id="FA-12345",
                notif_id=42,
                minutes_until_pickup=15,
                reason="hasn't tapped accept",
            )
        assert result["dry_run"] is True
        assert result["sent"] is False
        assert result["send_sid"] is None

    def test_dry_run_when_env_is_zero(self):
        from backend.services.dispatch_agent import handle_flagged_trip
        with (
            patch.dict(os.environ, {"DRIVER_AUTOCHECKIN_ENABLED": "0"}),
            patch("backend.services.ops_alert.route_dispatch_alert"),
        ):
            result = handle_flagged_trip(
                db=MagicMock(),
                driver_first_name="Amanuel",
                driver_whatsapp_number="+15555550100",
                trip_label="trip",
                trip_id=None,
                notif_id=None,
                minutes_until_pickup=None,
                reason="testing",
            )
        assert result["dry_run"] is True
        assert result["sent"] is False

    def test_dry_run_does_not_send_whatsapp(self):
        from backend.services.dispatch_agent import handle_flagged_trip
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("backend.services.ops_alert.route_dispatch_alert"),
            patch("backend.services.whatsapp_service.send_whatsapp") as mock_send,
        ):
            handle_flagged_trip(
                db=MagicMock(),
                driver_first_name="Amanuel",
                driver_whatsapp_number="+15555550100",
                trip_label="trip",
                trip_id="FA-1",
                notif_id=1,
                minutes_until_pickup=5,
                reason="testing",
            )
        mock_send.assert_not_called()


class TestHandleFlaggedTripPaperTrail:
    def test_paper_trail_fires_in_dry_run(self):
        from backend.services.dispatch_agent import handle_flagged_trip
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("backend.services.ops_alert.route_dispatch_alert") as mock_log,
        ):
            handle_flagged_trip(
                db=MagicMock(),
                driver_first_name="Amanuel",
                driver_whatsapp_number=None,
                trip_label="trip",
                trip_id="FA-99",
                notif_id=7,
                minutes_until_pickup=10,
                reason="reason",
            )
        mock_log.assert_called_once()
        kwargs = mock_log.call_args.kwargs
        assert kwargs.get("severity") == "silent"
        assert "[DRY-RUN]" in kwargs.get("title", "")
        assert kwargs.get("trip_id") == "FA-99"
        assert kwargs.get("notif_id") == 7

    def test_paper_trail_failure_does_not_raise(self):
        from backend.services.dispatch_agent import handle_flagged_trip
        with (
            patch.dict(os.environ, {}, clear=True),
            patch(
                "backend.services.ops_alert.route_dispatch_alert",
                side_effect=Exception("db down"),
            ),
        ):
            # Must not raise even when paper trail itself fails.
            result = handle_flagged_trip(
                db=MagicMock(),
                driver_first_name="Amanuel",
                driver_whatsapp_number=None,
                trip_label="trip",
                trip_id=None,
                notif_id=None,
                minutes_until_pickup=None,
                reason="r",
            )
            assert result["dry_run"] is True


class TestHandleFlaggedTripEnabled:
    """Behavior when DRIVER_AUTOCHECKIN_ENABLED=1 (i.e. Malik has approved)."""

    def test_enabled_with_no_phone_does_not_send(self):
        from backend.services.dispatch_agent import handle_flagged_trip
        with (
            patch.dict(os.environ, {"DRIVER_AUTOCHECKIN_ENABLED": "1"}),
            patch("backend.services.ops_alert.route_dispatch_alert"),
            patch("backend.services.whatsapp_service.send_whatsapp") as mock_send,
        ):
            result = handle_flagged_trip(
                db=MagicMock(),
                driver_first_name="Amanuel",
                driver_whatsapp_number=None,
                trip_label="trip",
                trip_id=None,
                notif_id=None,
                minutes_until_pickup=None,
                reason="r",
            )
        mock_send.assert_not_called()
        assert result["sent"] is False
        assert result["dry_run"] is False
        assert "no whatsapp number" in (result["error"] or "")

    def test_enabled_with_phone_sends_once(self):
        from backend.services.dispatch_agent import handle_flagged_trip
        with (
            patch.dict(os.environ, {"DRIVER_AUTOCHECKIN_ENABLED": "1"}),
            patch("backend.services.ops_alert.route_dispatch_alert"),
            patch(
                "backend.services.whatsapp_service.send_whatsapp",
                return_value="WA_SID_TEST",
            ) as mock_send,
        ):
            result = handle_flagged_trip(
                db=MagicMock(),
                driver_first_name="Amanuel",
                driver_whatsapp_number="+15555550100",
                trip_label="trip",
                trip_id="FA-1",
                notif_id=1,
                minutes_until_pickup=5,
                reason="r",
            )
        mock_send.assert_called_once()
        # Confirm the drafted message was passed
        args, _ = mock_send.call_args
        assert args[0] == "+15555550100"
        assert isinstance(args[1], str)
        assert len(args[1]) > 0
        assert result["sent"] is True
        assert result["send_sid"] == "WA_SID_TEST"
        assert result["dry_run"] is False
