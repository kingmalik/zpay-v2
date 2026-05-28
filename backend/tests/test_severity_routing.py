"""
Phase 3 severity-tier routing tests.

Updated 2026-05-28: Discord webhook removed in favor of internal
`ops_event_log` table. Tests now assert against the DB-log path rather
than urllib.request.urlopen.

Tests route_dispatch_alert() for all five specified cases:
  1. critical → SMS (alert_admin) + ntfy + ops_event_log
  2. urgent   → ntfy + ops_event_log (no SMS)
  3. normal   → ops_event_log only (no ntfy, no SMS)
  4. silent during quiet hours → ops_event_log only (no ntfy, no SMS)
  5. silent during day → ops_event_log + ntfy (low priority), no SMS

All external clients (Twilio, ntfy, DB session) are mocked.
quiet_hours.in_quiet_hours() is patched directly.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root on sys.path so `backend.*` imports resolve.
_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Fixture: patch all external I/O at once
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_channels():
    """
    Returns a dict of mock objects for each channel:
      log_event — backend.services.ops_alert._log_event (DB-backed)
      ntfy      — requests.post (used by _push_ntfy)
      sms       — backend.services.notification_service.alert_admin
    """
    fake_ntfy_resp = MagicMock()
    fake_ntfy_resp.status_code = 200

    with (
        patch.dict(os.environ, {
            "OPS_NTFY_TOPIC": "zpay-test-alerts",
            "HEALTH_NTFY_SERVER": "https://ntfy.example.com",
        }),
        patch("backend.services.ops_alert._log_event", return_value=True) as mock_log_event,
        patch("requests.post", return_value=fake_ntfy_resp) as mock_ntfy_post,
        patch(
            "backend.services.notification_service.alert_admin",
        ) as mock_alert_admin,
    ):
        yield {
            "log_event": mock_log_event,
            "ntfy": mock_ntfy_post,
            "sms": mock_alert_admin,
        }


# ---------------------------------------------------------------------------
# Test 1 — critical → SMS + ntfy + ops_event_log
# ---------------------------------------------------------------------------

class TestCriticalSeverity:
    def test_critical_writes_event_log(self, mock_channels):
        import backend.services.ops_alert as ops_alert
        ops_alert.route_dispatch_alert("critical", "Test critical", "Something broke badly")
        mock_channels["log_event"].assert_called_once()

    def test_critical_fires_ntfy(self, mock_channels):
        import backend.services.ops_alert as ops_alert
        ops_alert.route_dispatch_alert("critical", "Test critical", "Something broke badly")
        mock_channels["ntfy"].assert_called_once()

    def test_critical_fires_sms(self, mock_channels):
        import backend.services.ops_alert as ops_alert
        ops_alert.route_dispatch_alert("critical", "Test critical", "Something broke badly")
        mock_channels["sms"].assert_called_once()

    def test_critical_event_log_captures_title_and_severity(self, mock_channels):
        import backend.services.ops_alert as ops_alert
        ops_alert.route_dispatch_alert("critical", "Missed pickup", "Driver is 10 min late")
        kwargs = mock_channels["log_event"].call_args.kwargs
        assert kwargs.get("severity") == "critical"
        assert kwargs.get("title") == "Missed pickup"
        assert kwargs.get("message") == "Driver is 10 min late"


# ---------------------------------------------------------------------------
# Test 2 — urgent → ntfy + ops_event_log (NO SMS)
# ---------------------------------------------------------------------------

class TestUrgentSeverity:
    def test_urgent_writes_event_log(self, mock_channels):
        import backend.services.ops_alert as ops_alert
        ops_alert.route_dispatch_alert("urgent", "Driver declined", "Needs sub now")
        mock_channels["log_event"].assert_called_once()

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
# Test 3 — normal → ops_event_log only (no ntfy, no SMS)
# ---------------------------------------------------------------------------

class TestNormalSeverity:
    def test_normal_writes_event_log(self, mock_channels):
        import backend.services.ops_alert as ops_alert
        ops_alert.route_dispatch_alert("normal", "Override applied", "Snooze set by operator")
        mock_channels["log_event"].assert_called_once()

    def test_normal_does_not_fire_ntfy(self, mock_channels):
        import backend.services.ops_alert as ops_alert
        ops_alert.route_dispatch_alert("normal", "Override applied", "Snooze set by operator")
        mock_channels["ntfy"].assert_not_called()

    def test_normal_does_not_fire_sms(self, mock_channels):
        import backend.services.ops_alert as ops_alert
        ops_alert.route_dispatch_alert("normal", "Override applied", "Snooze set by operator")
        mock_channels["sms"].assert_not_called()


# ---------------------------------------------------------------------------
# Test 4 — silent during quiet hours → ops_event_log only, no push
# ---------------------------------------------------------------------------

class TestSilentDuringQuietHours:
    def test_silent_quiet_hours_writes_event_log(self, mock_channels):
        import backend.services.ops_alert as ops_alert
        with patch("backend.services.quiet_hours.in_quiet_hours", return_value=True):
            ops_alert.route_dispatch_alert("silent", "Heartbeat log", "Monitor cycle OK")
        mock_channels["log_event"].assert_called_once()

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
# Test 5 — silent during day → ops_event_log + ntfy (low priority), no SMS
# ---------------------------------------------------------------------------

class TestSilentDuringDay:
    def test_silent_daytime_writes_event_log(self, mock_channels):
        import backend.services.ops_alert as ops_alert
        with patch("backend.services.quiet_hours.in_quiet_hours", return_value=False):
            ops_alert.route_dispatch_alert("silent", "Cycle log", "Run completed OK")
        mock_channels["log_event"].assert_called_once()

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
# Bonus — DB write failure is nonfatal (paper trail loss must not block alerts)
# ---------------------------------------------------------------------------

class TestEventLogFallback:
    def test_event_log_failure_is_nonfatal(self):
        """route_dispatch_alert must not raise when ops_event_log write fails."""
        import backend.services.ops_alert as ops_alert
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("backend.services.ops_alert._log_event", side_effect=Exception("db down")),
            patch("backend.services.quiet_hours.in_quiet_hours", return_value=False),
            patch("requests.post"),
        ):
            # Even when the log write raises, the call should not propagate.
            # NOTE: _log_event itself swallows exceptions, so a side_effect on the
            # patch only fires if the wrapper logic is reordered. This guards the
            # contract — exceptions inside _log_event must never reach the caller.
            try:
                ops_alert.route_dispatch_alert("normal", "DB failure test", "Should not crash")
            except Exception as exc:
                pytest.fail(f"route_dispatch_alert raised: {exc}")


# ---------------------------------------------------------------------------
# Bonus — unknown/missing severity defaults to normal (no crash)
# ---------------------------------------------------------------------------

class TestUnknownSeverityDefaultsToNormal:
    def test_none_severity_handled(self, mock_channels):
        """Passing None severity should not crash — treated as normal."""
        import backend.services.ops_alert as ops_alert
        with patch("backend.services.quiet_hours.in_quiet_hours", return_value=False):
            ops_alert.route_dispatch_alert(None, "Edge case", "No crash please")  # type: ignore[arg-type]
        # Just verify no exception.
