"""
Tests for the API-key health watchdog.

Pin the safety contract:
  1. Each check function returns a KeyCheckResult — never None, never raises.
  2. Missing env vars produce ok=False with a clear reason and a reauth_url.
  3. _maybe_alert only fires on OK→DEAD transitions:
       - First observation (None → anything): no alert
       - OK → OK: no alert
       - DEAD → DEAD: no alert (do not re-page a known-dead key)
       - OK → DEAD: alert fires exactly once
       - DEAD → OK: no alert (recovery is good news, not a page)
  4. run_watchdog_cycle returns a structured summary.
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


# ── Reset transition cache between tests ──────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_state():
    import backend.services.key_health as kh
    kh._last_state.clear()
    yield
    kh._last_state.clear()


# ── Individual check functions ────────────────────────────────────────────────

class TestAnthropicCheck:
    def test_missing_key(self):
        from backend.services.key_health import check_anthropic
        with patch.dict(os.environ, {}, clear=True):
            r = check_anthropic()
        assert r.ok is False
        assert "not set" in r.detail
        assert r.reauth_url and "console.anthropic.com" in r.reauth_url

    def test_org_disabled(self):
        from backend.services.key_health import check_anthropic
        fake_client = MagicMock()
        fake_client.messages.count_tokens.side_effect = Exception(
            "Error code: 400 — This organization has been disabled."
        )
        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}),
            patch("anthropic.Anthropic", return_value=fake_client),
        ):
            r = check_anthropic()
        assert r.ok is False
        assert "Org disabled" in r.detail

    def test_ok(self):
        from backend.services.key_health import check_anthropic
        fake_client = MagicMock()
        fake_client.messages.count_tokens.return_value = MagicMock()
        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}),
            patch("anthropic.Anthropic", return_value=fake_client),
        ):
            r = check_anthropic()
        assert r.ok is True


class TestElevenLabsCheck:
    def test_missing_key(self):
        from backend.services.key_health import check_elevenlabs
        with patch.dict(os.environ, {}, clear=True):
            r = check_elevenlabs()
        assert r.ok is False
        assert r.reauth_url and "elevenlabs.io" in r.reauth_url

    def test_401(self):
        from backend.services.key_health import check_elevenlabs
        fake_resp = MagicMock(status_code=401)
        with (
            patch.dict(os.environ, {"ELEVENLABS_API_KEY": "k"}),
            patch("requests.get", return_value=fake_resp),
        ):
            r = check_elevenlabs()
        assert r.ok is False
        assert "401" in r.detail

    def test_ok(self):
        from backend.services.key_health import check_elevenlabs
        fake_resp = MagicMock(status_code=200)
        with (
            patch.dict(os.environ, {"ELEVENLABS_API_KEY": "k"}),
            patch("requests.get", return_value=fake_resp),
        ):
            r = check_elevenlabs()
        assert r.ok is True


class TestGmailCheck:
    def test_invalid_grant_returns_dead(self):
        from backend.services.key_health import check_gmail_maz
        fake_resp = MagicMock(status_code=400, text='{"error":"invalid_grant"}')
        with (
            patch.dict(os.environ, {
                "GMAIL_REFRESH_TOKEN_MAZ": "rt",
                "GOOGLE_OAUTH_CLIENT_ID": "cid",
                "GOOGLE_OAUTH_CLIENT_SECRET": "csec",
            }),
            patch("requests.post", return_value=fake_resp),
        ):
            r = check_gmail_maz()
        assert r.ok is False
        assert "expired" in r.detail.lower() or "revoked" in r.detail.lower()
        assert r.reauth_url and "gmail-reauth" in r.reauth_url

    def test_ok(self):
        from backend.services.key_health import check_gmail_acumen
        fake_resp = MagicMock(status_code=200)
        fake_resp.json.return_value = {"access_token": "abc"}
        with (
            patch.dict(os.environ, {
                "GMAIL_REFRESH_TOKEN_ACUMEN": "rt",
                "GOOGLE_OAUTH_CLIENT_ID": "cid",
                "GOOGLE_OAUTH_CLIENT_SECRET": "csec",
            }),
            patch("requests.post", return_value=fake_resp),
        ):
            r = check_gmail_acumen()
        assert r.ok is True


# ── Transition logic ──────────────────────────────────────────────────────────

class TestTransitionAlerts:
    def _result(self, name: str, ok: bool):
        from backend.services.key_health import KeyCheckResult
        return KeyCheckResult(name=name, ok=ok, detail="x", reauth_url="https://example.com")

    def test_first_observation_does_not_alert(self):
        from backend.services.key_health import _maybe_alert
        with patch("backend.services.ops_alert.route_dispatch_alert") as mock:
            assert _maybe_alert(self._result("anthropic", True)) is False
            mock.assert_not_called()

    def test_ok_then_ok_does_not_alert(self):
        from backend.services.key_health import _maybe_alert
        _maybe_alert(self._result("k", True))  # observation 1
        with patch("backend.services.ops_alert.route_dispatch_alert") as mock:
            assert _maybe_alert(self._result("k", True)) is False
            mock.assert_not_called()

    def test_dead_then_dead_does_not_alert(self):
        from backend.services.key_health import _maybe_alert
        _maybe_alert(self._result("k", False))  # observation 1: now known-dead
        with patch("backend.services.ops_alert.route_dispatch_alert") as mock:
            assert _maybe_alert(self._result("k", False)) is False
            mock.assert_not_called()

    def test_ok_then_dead_alerts_once(self):
        from backend.services.key_health import _maybe_alert
        _maybe_alert(self._result("k", True))  # baseline: OK
        with patch("backend.services.ops_alert.route_dispatch_alert") as mock:
            assert _maybe_alert(self._result("k", False)) is True
            mock.assert_called_once()
            kwargs = mock.call_args.kwargs
            assert kwargs.get("severity") == "urgent"
            assert "KEY DEAD" in kwargs.get("title", "")

    def test_dead_then_ok_does_not_alert(self):
        """Recovery is silent — we don't page on good news."""
        from backend.services.key_health import _maybe_alert
        _maybe_alert(self._result("k", False))  # baseline: dead
        with patch("backend.services.ops_alert.route_dispatch_alert") as mock:
            assert _maybe_alert(self._result("k", True)) is False
            mock.assert_not_called()


# ── Aggregator ────────────────────────────────────────────────────────────────

class TestRunWatchdogCycle:
    def test_returns_summary_shape(self):
        from backend.services.key_health import run_watchdog_cycle
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("backend.services.ops_alert.route_dispatch_alert"),
        ):
            summary = run_watchdog_cycle()
        assert set(summary.keys()) >= {
            "ran_at", "checked", "ok", "dead", "alerts_fired", "results",
        }
        # With env cleared, every check returns dead.
        assert summary["dead"] == summary["checked"]
        assert summary["ok"] == 0
        # No baseline → first observation never alerts even though all dead.
        assert summary["alerts_fired"] == 0
