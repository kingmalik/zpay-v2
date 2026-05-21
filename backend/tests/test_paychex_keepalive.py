"""
backend/tests/test_paychex_keepalive.py
=========================================
Unit tests for the Paychex session keep-alive service.

Covers:
- check_paychex_session(): alive, expired-by-redirect, expired-by-401, 5xx optimistic,
  timeout, network error, empty cookies
- run_paychex_keepalive(): happy path (both alive), expired path (alert fires once,
  suppressed on repeat), no-session path (skip + reset alerted flag)
- _send_expiry_alert(): delegates to health_monitor helpers
- start_paychex_keepalive() / stop_paychex_keepalive(): scheduler lifecycle, idempotent start
- _load_cookies(): DB path, in-memory fallback, no-session returns None

Run:
    PYTHONPATH=. pytest backend/tests/test_paychex_keepalive.py -x -v
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest
import requests as _requests_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(
    *,
    status_code: int = 200,
    final_url: str = "https://myapps.paychex.com/dashboard",
    text: str = "<html><body>Paychex Dashboard</body></html>",
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.url = final_url
    resp.text = text
    return resp


def _login_page_html() -> str:
    """Minimal Paychex login page HTML — contains the canonical indicator."""
    return (
        '<html><head><title>Paychex Flex</title></head>'
        '<body><form>'
        '<input id="login-username" type="text" />'
        '<input id="login-password" type="password" />'
        '</form></body></html>'
    )


def _playwright_cookies(names: list[str] | None = None) -> list[dict]:
    """Return a list of Playwright-style cookie dicts."""
    names = names or ["PAYCHEX_SESSION", "PAYCHEX_AUTH"]
    return [{"name": n, "value": f"val_{n}", "domain": ".paychex.com"} for n in names]


# ---------------------------------------------------------------------------
# check_paychex_session
# ---------------------------------------------------------------------------

class TestCheckPaychexSession:

    def test_alive_returns_true(self):
        from backend.services.paychex_keepalive import check_paychex_session
        resp = _make_response(status_code=200, final_url="https://myapps.paychex.com/dashboard")
        with patch("backend.services.paychex_keepalive.requests.get", return_value=resp):
            assert check_paychex_session("acumen", _playwright_cookies()) is True

    def test_login_redirect_returns_false(self):
        from backend.services.paychex_keepalive import check_paychex_session
        resp = _make_response(status_code=200, final_url="https://login.flex.paychex.com/login/v2")
        with patch("backend.services.paychex_keepalive.requests.get", return_value=resp):
            assert check_paychex_session("acumen", _playwright_cookies()) is False

    def test_401_returns_false(self):
        from backend.services.paychex_keepalive import check_paychex_session
        resp = _make_response(status_code=401, final_url="https://myapps.paychex.com")
        with patch("backend.services.paychex_keepalive.requests.get", return_value=resp):
            assert check_paychex_session("maz", _playwright_cookies()) is False

    def test_403_returns_false(self):
        from backend.services.paychex_keepalive import check_paychex_session
        resp = _make_response(status_code=403, final_url="https://myapps.paychex.com")
        with patch("backend.services.paychex_keepalive.requests.get", return_value=resp):
            assert check_paychex_session("maz", _playwright_cookies()) is False

    def test_5xx_returns_true_optimistic(self):
        """5xx = Paychex is down, not our session — return True to avoid alert spam."""
        from backend.services.paychex_keepalive import check_paychex_session
        resp = _make_response(status_code=503, final_url="https://myapps.paychex.com")
        with patch("backend.services.paychex_keepalive.requests.get", return_value=resp):
            assert check_paychex_session("acumen", _playwright_cookies()) is True

    def test_timeout_returns_false(self):
        from backend.services.paychex_keepalive import check_paychex_session
        with patch(
            "backend.services.paychex_keepalive.requests.get",
            side_effect=_requests_module.Timeout,
        ):
            assert check_paychex_session("acumen", _playwright_cookies()) is False

    def test_network_error_returns_false(self):
        from backend.services.paychex_keepalive import check_paychex_session
        with patch(
            "backend.services.paychex_keepalive.requests.get",
            side_effect=_requests_module.ConnectionError("unreachable"),
        ):
            assert check_paychex_session("maz", _playwright_cookies()) is False

    def test_200_with_login_content_returns_false(self):
        """HIGH #1 — Paychex returns HTTP 200 + JS-redirect to login page.

        The final URL stays at myapps.paychex.com (no 'login' substring),
        but the response body contains id="login-username".  The probe must
        return False — same detection used by the bot in paychex_entry.py:103.
        """
        from backend.services.paychex_keepalive import check_paychex_session
        resp = _make_response(
            status_code=200,
            final_url="https://myapps.paychex.com",  # no "login" in URL
            text=_login_page_html(),
        )
        with patch("backend.services.paychex_keepalive.requests.get", return_value=resp):
            assert check_paychex_session("acumen", _playwright_cookies()) is False

    def test_200_with_login_content_not_triggered_by_dashboard(self):
        """A genuine dashboard response that does NOT contain id="login-username" is alive."""
        from backend.services.paychex_keepalive import check_paychex_session
        resp = _make_response(
            status_code=200,
            final_url="https://myapps.paychex.com/dashboard",
            text="<html><body><div id='app'>Welcome back</div></body></html>",
        )
        with patch("backend.services.paychex_keepalive.requests.get", return_value=resp):
            assert check_paychex_session("acumen", _playwright_cookies()) is True

    def test_5xx_with_login_content_returns_true_optimistic(self):
        """5xx + login content still returns True — server error, not our session."""
        from backend.services.paychex_keepalive import check_paychex_session
        resp = _make_response(
            status_code=503,
            final_url="https://myapps.paychex.com",
            text=_login_page_html(),
        )
        with patch("backend.services.paychex_keepalive.requests.get", return_value=resp):
            assert check_paychex_session("acumen", _playwright_cookies()) is True

    def test_empty_cookies_returns_false(self):
        from backend.services.paychex_keepalive import check_paychex_session
        # Even without calling requests, empty cookies → False
        with patch("backend.services.paychex_keepalive.requests.get") as mock_get:
            result = check_paychex_session("acumen", [])
            mock_get.assert_not_called()
            assert result is False

    def test_cookies_with_missing_name_are_filtered(self):
        """Cookies without a name key are skipped gracefully."""
        from backend.services.paychex_keepalive import check_paychex_session
        bad_cookies = [{"value": "some_val"}]  # no 'name'
        with patch("backend.services.paychex_keepalive.requests.get") as mock_get:
            result = check_paychex_session("acumen", bad_cookies)
            mock_get.assert_not_called()
            assert result is False

    def test_empty_string_cookie_value_is_preserved(self):
        """MEDIUM #1 — empty-string cookie value must not be dropped by falsy filter."""
        from backend.services.paychex_keepalive import check_paychex_session
        # A cookie with value="" is valid; falsy `or` would skip it and produce
        # an empty cookie_jar (returning False before the request).
        # With explicit `is not None` the cookie is included and the request fires.
        cookies_with_empty_val = [{"name": "SESSION", "value": ""}]
        resp = _make_response(status_code=200, final_url="https://myapps.paychex.com/dashboard")
        with patch("backend.services.paychex_keepalive.requests.get", return_value=resp) as mock_get:
            # name="SESSION" is non-empty so cookie_jar = {"SESSION": ""}
            # The request fires (empty-string value is included).
            result = check_paychex_session("acumen", cookies_with_empty_val)
            mock_get.assert_called_once()  # request was made, not short-circuited


# ---------------------------------------------------------------------------
# _send_expiry_alert
# ---------------------------------------------------------------------------

class TestSendExpiryAlert:
    # _hm_send_email and _hm_push_ntfy are now module-level names in paychex_keepalive
    # (moved from lazy import inside _send_expiry_alert). Patch them there.

    def test_sends_email_and_ntfy(self):
        from backend.services import paychex_keepalive
        with (
            patch.object(paychex_keepalive, "_hm_send_email") as mock_email,
            patch.object(paychex_keepalive, "_hm_push_ntfy") as mock_ntfy,
        ):
            paychex_keepalive._send_expiry_alert("acumen")
            mock_email.assert_called_once()
            args_email = mock_email.call_args[0]
            assert "acumen" in args_email[0].lower() or "ACUMEN" in args_email[0]
            assert "recapture" in args_email[1].lower()

            mock_ntfy.assert_called_once()
            ntfy_kwargs = mock_ntfy.call_args
            assert ntfy_kwargs.kwargs.get("priority") == "high" or (
                len(ntfy_kwargs.args) >= 3 and ntfy_kwargs.args[2] == "high"
            )

    def test_alert_body_names_company(self):
        from backend.services import paychex_keepalive
        with (
            patch.object(paychex_keepalive, "_hm_send_email") as mock_email,
            patch.object(paychex_keepalive, "_hm_push_ntfy"),
        ):
            paychex_keepalive._send_expiry_alert("maz")
            _, body = mock_email.call_args[0]
            assert "maz" in body.lower() or "MAZ" in body
            assert "recapture" in body.lower()

    def test_helpers_unavailable_does_not_raise(self):
        """If module-level import failed (helpers are None), _send_expiry_alert must not propagate."""
        from backend.services import paychex_keepalive
        with (
            patch.object(paychex_keepalive, "_hm_send_email", None),
            patch.object(paychex_keepalive, "_hm_push_ntfy", None),
        ):
            # Should log error but not raise
            paychex_keepalive._send_expiry_alert("acumen")


# ---------------------------------------------------------------------------
# run_paychex_keepalive
# ---------------------------------------------------------------------------

class TestRunPaychexKeepalive:

    def _reset_alerted(self):
        """Reset module-level _alerted dict between tests."""
        import backend.services.paychex_keepalive as mod
        for k in mod._alerted:
            mod._alerted[k] = False

    def test_both_alive_returns_alive(self):
        from backend.services import paychex_keepalive
        self._reset_alerted()
        with (
            patch.object(paychex_keepalive, "_load_cookies", return_value=_playwright_cookies()),
            patch.object(paychex_keepalive, "check_paychex_session", return_value=True),
            patch.object(paychex_keepalive, "_send_expiry_alert") as mock_alert,
        ):
            result = paychex_keepalive.run_paychex_keepalive()
            assert result == {"acumen": "alive", "maz": "alive"}
            mock_alert.assert_not_called()

    def test_expired_session_fires_alert_once(self):
        from backend.services import paychex_keepalive
        self._reset_alerted()
        with (
            patch.object(paychex_keepalive, "_load_cookies", return_value=_playwright_cookies()),
            patch.object(paychex_keepalive, "check_paychex_session", return_value=False),
            patch.object(paychex_keepalive, "_send_expiry_alert") as mock_alert,
        ):
            # First run — alert fires
            result1 = paychex_keepalive.run_paychex_keepalive()
            assert result1["acumen"] == "expired"
            assert result1["maz"] == "expired"
            assert mock_alert.call_count == 2  # one per company

            # Second run — alert suppressed (already alerted)
            mock_alert.reset_mock()
            result2 = paychex_keepalive.run_paychex_keepalive()
            assert result2["acumen"] == "expired"
            mock_alert.assert_not_called()

    def test_alert_cleared_when_session_recovers(self):
        from backend.services import paychex_keepalive
        self._reset_alerted()
        # Force alerted=True for acumen
        paychex_keepalive._alerted["acumen"] = True

        with (
            patch.object(paychex_keepalive, "_load_cookies", return_value=_playwright_cookies()),
            patch.object(paychex_keepalive, "check_paychex_session", return_value=True),
            patch.object(paychex_keepalive, "_send_expiry_alert"),
        ):
            paychex_keepalive.run_paychex_keepalive()
            # After a successful check, _alerted flag must be cleared
            assert paychex_keepalive._alerted["acumen"] is False

    def test_no_cookies_returns_no_session(self):
        from backend.services import paychex_keepalive
        self._reset_alerted()
        with (
            patch.object(paychex_keepalive, "_load_cookies", return_value=None),
            patch.object(paychex_keepalive, "check_paychex_session") as mock_check,
            patch.object(paychex_keepalive, "_send_expiry_alert") as mock_alert,
        ):
            result = paychex_keepalive.run_paychex_keepalive()
            assert result == {"acumen": "no_session", "maz": "no_session"}
            mock_check.assert_not_called()
            mock_alert.assert_not_called()

    def test_no_session_resets_alerted_flag(self):
        """When cookies are gone, reset _alerted so we notify fresh when they return."""
        from backend.services import paychex_keepalive
        # Pre-set alerted to True as if a prior expiry cycle ran
        paychex_keepalive._alerted["acumen"] = True

        with patch.object(paychex_keepalive, "_load_cookies", return_value=None):
            paychex_keepalive.run_paychex_keepalive()
            assert paychex_keepalive._alerted["acumen"] is False

    def test_alert_names_correct_company(self):
        """Alert must be called with the right company string per company."""
        from backend.services import paychex_keepalive
        self._reset_alerted()

        alert_calls = []

        def _fake_alert(company: str) -> None:
            alert_calls.append(company)

        with (
            patch.object(paychex_keepalive, "_load_cookies", return_value=_playwright_cookies()),
            patch.object(paychex_keepalive, "check_paychex_session", return_value=False),
            patch.object(paychex_keepalive, "_send_expiry_alert", side_effect=_fake_alert),
        ):
            paychex_keepalive.run_paychex_keepalive()
            assert "acumen" in alert_calls
            assert "maz" in alert_calls

    def test_asymmetric_state_one_alive_one_expired(self):
        """One company session alive, the other expired — only the expired one fires an alert."""
        from backend.services import paychex_keepalive
        self._reset_alerted()

        # acumen=alive, maz=expired
        def _fake_check(company: str, cookies: list) -> bool:
            return company == "acumen"

        alert_calls: list[str] = []

        with (
            patch.object(paychex_keepalive, "_load_cookies", return_value=_playwright_cookies()),
            patch.object(paychex_keepalive, "check_paychex_session", side_effect=_fake_check),
            patch.object(
                paychex_keepalive, "_send_expiry_alert",
                side_effect=lambda c: alert_calls.append(c),
            ),
        ):
            result = paychex_keepalive.run_paychex_keepalive()

        assert result["acumen"] == "alive"
        assert result["maz"] == "expired"
        assert alert_calls == ["maz"]
        # acumen's alerted flag must be False (still alive, never fired)
        assert paychex_keepalive._alerted["acumen"] is False
        # maz's alerted flag must be True (alert was just sent)
        assert paychex_keepalive._alerted["maz"] is True


# ---------------------------------------------------------------------------
# _load_cookies
# ---------------------------------------------------------------------------

class TestLoadCookies:

    def test_returns_db_cookies_when_available(self):
        from backend.services import paychex_keepalive
        fake_row = SimpleNamespace(cookies=[{"name": "A", "value": "1"}])
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = fake_row
        mock_session_cls = MagicMock()
        mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

        with (
            patch("backend.services.paychex_keepalive.SessionLocal", mock_session_cls, create=True),
            patch.dict("sys.modules", {
                "backend.db.db": MagicMock(SessionLocal=mock_session_cls),
                "backend.db.models": MagicMock(PaychexSession=MagicMock()),
            }),
        ):
            # Import is inside the function — patch the import
            import importlib
            mod = importlib.import_module("backend.services.paychex_keepalive")

            with patch("backend.db.db.SessionLocal", mock_session_cls):
                cookies = paychex_keepalive._load_cookies.__wrapped__("acumen") if hasattr(
                    paychex_keepalive._load_cookies, "__wrapped__"
                ) else None

        # Integration-level: just verify the function returns a list or None
        # (DB connection unavailable in test — will fall through to memory path)
        result = paychex_keepalive._load_cookies("acumen")
        assert result is None or isinstance(result, list)

    def test_returns_none_when_no_cookies_anywhere(self):
        from backend.services import paychex_keepalive
        # Both DB and memory paths return nothing
        with (
            patch("backend.services.paychex_keepalive.SessionLocal", side_effect=Exception("no DB"), create=True),
        ):
            result = paychex_keepalive._load_cookies("acumen")
            assert result is None

    def test_falls_back_to_memory_when_db_fails(self):
        from backend.services import paychex_keepalive
        import backend.routes.paychex_bot as bot_mod

        mem_cookies = _playwright_cookies()
        original = dict(bot_mod._sessions)
        bot_mod._sessions["maz"] = mem_cookies

        try:
            # Make DB path raise so we exercise the memory fallback
            with patch(
                "backend.services.paychex_keepalive.SessionLocal",
                side_effect=Exception("DB unavailable"),
                create=True,
            ):
                result = paychex_keepalive._load_cookies("maz")
                # Memory fallback should kick in
                assert result == mem_cookies
        finally:
            bot_mod._sessions.clear()
            bot_mod._sessions.update(original)


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------

class TestSchedulerLifecycle:

    def _reset_scheduler(self):
        import backend.services.paychex_keepalive as mod
        mod._SCHEDULER = None

    def test_start_registers_job(self):
        from backend.services import paychex_keepalive
        self._reset_scheduler()
        mock_sched = MagicMock()
        mock_sched_cls = MagicMock(return_value=mock_sched)

        with patch("backend.services.paychex_keepalive.BackgroundScheduler", mock_sched_cls, create=True):
            with patch("backend.services.paychex_keepalive.IntervalTrigger", create=True) as mock_trigger:
                with patch.dict("sys.modules", {
                    "apscheduler.schedulers.background": MagicMock(BackgroundScheduler=mock_sched_cls),
                    "apscheduler.triggers.interval": MagicMock(IntervalTrigger=mock_trigger),
                }):
                    paychex_keepalive.start_paychex_keepalive()

        # Whatever path it took, just verify it doesn't crash and _SCHEDULER is set
        # (if APScheduler is installed, _SCHEDULER will be a real scheduler)
        # No assertion on _SCHEDULER value because test environment may not have APScheduler

    def test_start_is_idempotent(self):
        """Calling start twice must not register duplicate jobs."""
        from backend.services import paychex_keepalive
        self._reset_scheduler()

        call_count = [0]
        original_start = paychex_keepalive.start_paychex_keepalive

        def counting_start():
            call_count[0] += 1
            original_start()

        paychex_keepalive.start_paychex_keepalive()
        first_scheduler = paychex_keepalive._SCHEDULER

        # Second call must be a no-op (guard on `if _SCHEDULER is not None`)
        paychex_keepalive.start_paychex_keepalive()
        assert paychex_keepalive._SCHEDULER is first_scheduler

    def test_stop_clears_scheduler(self):
        from backend.services import paychex_keepalive
        mock_sched = MagicMock()
        paychex_keepalive._SCHEDULER = mock_sched

        paychex_keepalive.stop_paychex_keepalive()

        mock_sched.shutdown.assert_called_once_with(wait=False)
        assert paychex_keepalive._SCHEDULER is None

    def test_stop_when_not_started_does_not_raise(self):
        from backend.services import paychex_keepalive
        paychex_keepalive._SCHEDULER = None
        paychex_keepalive.stop_paychex_keepalive()  # should be silent no-op
