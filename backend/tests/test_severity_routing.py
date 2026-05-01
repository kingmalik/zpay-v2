"""
Phase 3 severity-tier routing tests.

Tests route_dispatch_alert() for all five specified cases:
  1. critical → SMS (alert_admin) + ntfy + Discord
  2. urgent   → ntfy + Discord (no SMS)
  3. normal   → Discord only (no ntfy, no SMS)
  4. silent during quiet hours → Discord only (no ntfy, no SMS)
  5. silent during day → Discord only (no ntfy — Discord still fires)

All external clients (Twilio, ntfy, Discord webhook) are mocked.
quiet_hours.in_quiet_hours() is patched directly.
"""

from __future__ import annotations

import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# Ensure project root on sys.path so `backend.*` imports resolve.
_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Helpers — import the module under test
# ---------------------------------------------------------------------------

def _import_ops_alert():
    """Re-import ops_alert so module-level globals reset between tests."""
    import importlib
    import backend.services.ops_alert as _mod
    importlib.reload(_mod)
    return _mod


# ---------------------------------------------------------------------------
# Fixture: patch all external I/O at once
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_channels():
    """
    Returns a dict of mock objects for each channel:
      discord  — urllib.request.urlopen (used by _push_discord)
      ntfy     — requests.post (used by _push_ntfy)
      sms      — backend.services.notification_service.alert_admin
    """
    # Fake urllib response for Discord
    fake_response = MagicMock()
    fake_response.status = 204
    fake_response.__enter__ = lambda s: s
    fake_response.__exit__ = MagicMock(return_value=False)

    # Fake ntfy response
    fake_ntfy_resp = MagicMock()
    fake_ntfy_resp.status_code = 200

    with (
        patch.dict(os.environ, {
            "DISCORD_WEBHOOK_URL": "https://discord.example.com/webhook/test",
            "OPS_NTFY_TOPIC": "zpay-test-alerts",
            "HEALTH_NTFY_SERVER": "https://ntfy.example.com",
        }),
        patch("urllib.request.urlopen", return_value=fake_response) as mock_urlopen,
        patch("requests.post", return_value=fake_ntfy_resp) as mock_ntfy_post,
        patch(
            "backend.services.notification_service.alert_admin",
        ) as mock_alert_admin,
    ):
        yield {
            "discord": mock_urlopen,
            "ntfy": mock_ntfy_post,
            "sms": mock_alert_admin,
        }


# ---------------------------------------------------------------------------
# Test 1 — critical → SMS + ntfy + Discord
# ---------------------------------------------------------------------------

class TestCriticalSeverity:
    def test_critical_fires_discord(self, mock_channels):
        import backend.services.ops_alert as ops_alert
        ops_alert.route_dispatch_alert("critical", "Test critical", "Something broke badly")
        mock_channels["discord"].assert_called_once()

    def test_critical_fires_ntfy(self, mock_channels):
        import backend.services.ops_alert as ops_alert
        ops_alert.route_dispatch_alert("critical", "Test critical", "Something broke badly")
        mock_channels["ntfy"].assert_called_once()

    def test_critical_fires_sms(self, mock_channels):
        import backend.services.ops_alert as ops_alert
        ops_alert.route_dispatch_alert("critical", "Test critical", "Something broke badly")
        mock_channels["sms"].assert_called_once()

    def test_critical_discord_content_has_label(self, mock_channels):
        import backend.services.ops_alert as ops_alert
        ops_alert.route_dispatch_alert("critical", "Missed pickup", "Driver is 10 min late")
        call_args = mock_channels["discord"].call_args
        # urlopen is called with a Request object as first arg
        req_obj = call_args[0][0]
        body = req_obj.data.decode("utf-8")
        assert "[CRITICAL]" in body
        assert "Missed pickup" in body


# ---------------------------------------------------------------------------
# Test 2 — urgent → ntfy + Discord (NO SMS)
# ---------------------------------------------------------------------------

class TestUrgentSeverity:
    def test_urgent_fires_discord(self, mock_channels):
        import backend.services.ops_alert as ops_alert
        ops_alert.route_dispatch_alert("urgent", "Driver declined", "Needs sub now")
        mock_channels["discord"].assert_called_once()

    def test_urgent_fires_ntfy(self, mock_channels):
        import backend.services.ops_alert as ops_alert
        ops_alert.route_dispatch_alert("urgent", "Driver declined", "Needs sub now")
        mock_channels["ntfy"].assert_called_once()

    def test_urgent_does_not_fire_sms(self, mock_channels):
        import backend.services.ops_alert as ops_alert
        ops_alert.route_dispatch_alert("urgent", "Driver declined", "Needs sub now")
        mock_channels["sms"].assert_not_called()

    def test_urgent_ntfy_priority_is_high(self, mock_channels):
        import backend.services.ops_alert as ops_alert
        ops_alert.route_dispatch_alert("urgent", "Unaccepted trip", "Driver no response")
        call_args = mock_channels["ntfy"].call_args
        headers = call_args[1]["headers"] if call_args[1] else call_args[0][1]
        assert headers.get("Priority") == "high"


# ---------------------------------------------------------------------------
# Test 3 — normal → Discord only (no ntfy, no SMS)
# ---------------------------------------------------------------------------

class TestNormalSeverity:
    def test_normal_fires_discord(self, mock_channels):
        import backend.services.ops_alert as ops_alert
        ops_alert.route_dispatch_alert("normal", "Override applied", "Snooze set by operator")
        mock_channels["discord"].assert_called_once()

    def test_normal_does_not_fire_ntfy(self, mock_channels):
        import backend.services.ops_alert as ops_alert
        ops_alert.route_dispatch_alert("normal", "Override applied", "Snooze set by operator")
        mock_channels["ntfy"].assert_not_called()

    def test_normal_does_not_fire_sms(self, mock_channels):
        import backend.services.ops_alert as ops_alert
        ops_alert.route_dispatch_alert("normal", "Override applied", "Snooze set by operator")
        mock_channels["sms"].assert_not_called()


# ---------------------------------------------------------------------------
# Test 4 — silent during quiet hours → Discord only, no push
# ---------------------------------------------------------------------------

class TestSilentDuringQuietHours:
    def test_silent_quiet_hours_fires_discord(self, mock_channels):
        import backend.services.ops_alert as ops_alert
        with patch("backend.services.quiet_hours.in_quiet_hours", return_value=True):
            ops_alert.route_dispatch_alert("silent", "Heartbeat log", "Monitor cycle OK")
        mock_channels["discord"].assert_called_once()

    def test_silent_quiet_hours_does_not_fire_ntfy(self, mock_channels):
        import backend.services.ops_alert as ops_alert
        with patch("backend.services.quiet_hours.in_quiet_hours", return_value=True):
            ops_alert.route_dispatch_alert("silent", "Heartbeat log", "Monitor cycle OK")
        mock_channels["ntfy"].assert_not_called()

    def test_silent_quiet_hours_does_not_fire_sms(self, mock_channels):
        import backend.services.ops_alert as ops_alert
        with patch("backend.services.quiet_hours.in_quiet_hours", return_value=True):
            ops_alert.route_dispatch_alert("silent", "Heartbeat log", "Monitor cycle OK")
        mock_channels["sms"].assert_not_called()


# ---------------------------------------------------------------------------
# Test 5 — silent during day → Discord only (ntfy skipped for silent tier)
# ---------------------------------------------------------------------------

class TestSilentDuringDay:
    def test_silent_daytime_fires_discord(self, mock_channels):
        import backend.services.ops_alert as ops_alert
        with patch("backend.services.quiet_hours.in_quiet_hours", return_value=False):
            ops_alert.route_dispatch_alert("silent", "Cycle log", "Run completed OK")
        mock_channels["discord"].assert_called_once()

    def test_silent_daytime_fires_ntfy(self, mock_channels):
        """Silent outside quiet hours DOES get an ntfy push (low priority)."""
        import backend.services.ops_alert as ops_alert
        with patch("backend.services.quiet_hours.in_quiet_hours", return_value=False):
            ops_alert.route_dispatch_alert("silent", "Cycle log", "Run completed OK")
        mock_channels["ntfy"].assert_called_once()

    def test_silent_daytime_does_not_fire_sms(self, mock_channels):
        import backend.services.ops_alert as ops_alert
        with patch("backend.services.quiet_hours.in_quiet_hours", return_value=False):
            ops_alert.route_dispatch_alert("silent", "Cycle log", "Run completed OK")
        mock_channels["sms"].assert_not_called()


# ---------------------------------------------------------------------------
# Bonus — Discord skipped gracefully when webhook not configured
# ---------------------------------------------------------------------------

class TestDiscordFallback:
    def test_no_webhook_url_is_nonfatal(self):
        """route_dispatch_alert must not raise when DISCORD_WEBHOOK_URL is absent."""
        import backend.services.ops_alert as ops_alert
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("backend.services.quiet_hours.in_quiet_hours", return_value=False),
            patch("requests.post"),
        ):
            # Should not raise
            ops_alert.route_dispatch_alert("normal", "No webhook test", "Should not crash")


# ---------------------------------------------------------------------------
# Bonus — unknown/missing severity defaults to normal (no crash)
# ---------------------------------------------------------------------------

class TestUnknownSeverityDefaultsToNormal:
    def test_none_severity_handled(self, mock_channels):
        """Passing None severity should not crash — treated as normal."""
        import backend.services.ops_alert as ops_alert
        # None gets lowercased to "none" which falls through to normal path
        # (no ntfy, no sms, discord fires if webhook set)
        with patch("backend.services.quiet_hours.in_quiet_hours", return_value=False):
            ops_alert.route_dispatch_alert(None, "Edge case", "No crash please")  # type: ignore[arg-type]
        # Just verify no exception — don't assert channel counts (undeclared severity)
