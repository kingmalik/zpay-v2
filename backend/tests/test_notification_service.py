"""
Tests for backend/services/notification_service.py and call_scripts.py.

Coverage:
  - normalize_phone(): US 10/11-digit, formatted, E.164, intl (+251/+291),
    trash inputs.
  - AMD response parsing: synchronous Twilio call returns answered_by which
    must be logged.
  - Twilio rate-limit retry: 429/503 → backoff up to 3 retries.
  - Opt-out (21610): SMS suppressed, denylist persisted.
  - alert_admin de-dup: identical messages within 60s suppressed.
  - Daily counter: bumps + reset semantics.
  - call_scripts: trip_ref interpolation + apostrophe-safe names.
"""

from __future__ import annotations

import importlib
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root on sys.path so `backend.*` imports resolve.
_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ── Twilio fake exception (avoid hard dep on the real package) ───────────────
class _FakeTwilioRestException(Exception):
    def __init__(self, status: int, code: int | None = None, msg: str = ""):
        super().__init__(msg or f"twilio {status}/{code}")
        self.status = status
        self.code = code
        self.msg = msg


def _install_fake_twilio() -> None:
    """Install a stub `twilio` package so notification_service can import it."""
    if "twilio" in sys.modules:
        return
    twilio_mod = types.ModuleType("twilio")
    twilio_base_mod = types.ModuleType("twilio.base")
    twilio_base_exc_mod = types.ModuleType("twilio.base.exceptions")
    twilio_base_exc_mod.TwilioRestException = _FakeTwilioRestException
    twilio_rest_mod = types.ModuleType("twilio.rest")
    twilio_rest_mod.Client = MagicMock()  # not actually instantiated in tests
    sys.modules["twilio"] = twilio_mod
    sys.modules["twilio.base"] = twilio_base_mod
    sys.modules["twilio.base.exceptions"] = twilio_base_exc_mod
    sys.modules["twilio.rest"] = twilio_rest_mod


_install_fake_twilio()


@pytest.fixture
def notify(tmp_path, monkeypatch):
    """
    Import notification_service and reset its process-global state in-place
    so tests are isolated without invalidating the module reference cached
    on the parent `backend.services` package (other test suites rely on it).
    """
    monkeypatch.setenv("ZPAY_OPTOUT_PATH", str(tmp_path / "optout.json"))
    monkeypatch.setenv("MONITOR_DRY_RUN", "0")
    monkeypatch.delenv("TEST_MODE", raising=False)

    # Detect whether `backend.services.notification_service` was already
    # bound as a package attribute BEFORE this fixture ran. If not, we
    # must un-bind it on teardown so other test suites that monkeypatch
    # sys.modules can still substitute their own mock module.
    services_pkg = importlib.import_module("backend.services")
    had_attr_before = hasattr(services_pkg, "notification_service")
    had_resilience_attr_before = hasattr(services_pkg, "notification_resilience")

    mod = importlib.import_module("backend.services.notification_service")
    from backend.services import notification_resilience as resilience

    # Snapshot module-global state for restoration on teardown.
    snapshot = {
        ("mod", "_client"): mod._client,
        ("mod", "_account_probed"): mod._account_probed,
        ("mod", "_dry_run"): mod._dry_run,
        ("res", "_optout_set"): set(resilience._optout_set),
        ("res", "_optout_loaded"): resilience._optout_loaded,
        ("res", "_admin_alert_dedup"): dict(resilience._admin_alert_dedup),
        ("res", "_call_count_today"): resilience._call_count_today,
        ("res", "_sms_count_today"): resilience._sms_count_today,
        ("res", "_counter_date"): resilience._counter_date,
    }
    # Reset for a clean-room test
    mod._client = None
    mod._account_probed = False
    mod._dry_run = False
    resilience.reset_optout_for_test()
    resilience.reset_admin_dedup_for_test()
    resilience.reset_counters_for_test()

    yield mod

    # Restore so other test suites see the original module state.
    for (owner, name), value in snapshot.items():
        target = mod if owner == "mod" else resilience
        setattr(target, name, value)

    # If the package attribute didn't exist before our import_module call,
    # remove it now so other suites' `patch.dict("sys.modules", ...)` swaps
    # actually win when trip_monitor does `from backend.services import
    # notification_service`. Python's `from-import` looks up the package
    # attribute first, then falls back to sys.modules.
    for attr_name, had_before in (("notification_service", had_attr_before),
                                  ("notification_resilience", had_resilience_attr_before)):
        if not had_before and hasattr(services_pkg, attr_name):
            try:
                delattr(services_pkg, attr_name)
            except AttributeError:
                pass


# ── normalize_phone ─────────────────────────────────────────────────────────

class TestNormalizePhone:
    @pytest.mark.parametrize("raw,expected", [
        # US 10-digit
        ("2065551234", "+12065551234"),
        ("4255550000", "+14255550000"),
        # US 11-digit with leading 1
        ("12065551234", "+12065551234"),
        # Already E.164
        ("+12065551234", "+12065551234"),
        # Formatted US
        ("(206) 555-1234", "+12065551234"),
        ("206-555-1234", "+12065551234"),
        ("206.555.1234", "+12065551234"),
        ("206 555 1234", "+12065551234"),
        # Intl E.164 — Ethiopia (+251) and Eritrea (+291)
        ("+251911234567", "+251911234567"),
        ("+2917123456", "+2917123456"),
        # Whitespace tolerance
        ("  +12065551234  ", "+12065551234"),
    ])
    def test_valid(self, notify, raw, expected):
        assert notify.normalize_phone(raw) == expected

    @pytest.mark.parametrize("raw", [
        None,
        "",
        "   ",
        "abc",
        "555",            # too short
        "12345",          # too short
        "+",              # plus only
        "+123",           # too short
    ])
    def test_invalid_returns_none(self, notify, raw):
        assert notify.normalize_phone(raw) is None


# ── AMD response parsing ────────────────────────────────────────────────────

class TestAMDResponseParsing:
    def test_make_call_passes_machine_detection_and_logs_answered_by(self, notify, caplog):
        """
        make_call must request synchronous AMD and log the answered_by field
        from the Twilio response.
        """
        # Configure env so the call attempt proceeds
        os_env = {
            "TWILIO_ACCOUNT_SID": "ACfake",
            "TWILIO_AUTH_TOKEN": "tokenfake",
            "TWILIO_FROM_NUMBER": "+15005550006",
        }
        with patch.dict(os.environ, os_env, clear=False):
            # Stub the twilio client + its calls.create response
            fake_call = MagicMock()
            fake_call.sid = "CAfake123"
            fake_call.answered_by = "machine_end_beep"
            fake_call.status = "completed"
            fake_call.duration = "12"

            client = MagicMock()
            client.calls.create.return_value = fake_call
            # Bypass real twilio Client construction + suspension probe
            notify._client = client
            notify._account_probed = True

            with caplog.at_level("INFO", logger="zpay.notify"):
                sid = notify.make_call("+12065551234", "Hello", language="en")

            assert sid == "CAfake123"
            kwargs = client.calls.create.call_args.kwargs
            assert kwargs["machine_detection"] == "Enable"
            assert kwargs["machine_detection_timeout"] == 6
            assert kwargs["to"] == "+12065551234"
            # Log line must include answered_by for audit
            log_text = " ".join(r.getMessage() for r in caplog.records)
            assert "answered_by=machine_end_beep" in log_text
            assert "CAfake123" in log_text

    def test_make_call_handles_human_answer(self, notify, caplog):
        os_env = {
            "TWILIO_ACCOUNT_SID": "ACfake",
            "TWILIO_AUTH_TOKEN": "tokenfake",
            "TWILIO_FROM_NUMBER": "+15005550006",
        }
        with patch.dict(os.environ, os_env, clear=False):
            fake_call = MagicMock()
            fake_call.sid = "CAhuman"
            fake_call.answered_by = "human"
            fake_call.status = "completed"
            fake_call.duration = "20"

            client = MagicMock()
            client.calls.create.return_value = fake_call
            notify._client = client
            notify._account_probed = True

            with caplog.at_level("INFO", logger="zpay.notify"):
                notify.make_call("+12065551234", "Hi", language="en")

            log_text = " ".join(r.getMessage() for r in caplog.records)
            assert "answered_by=human" in log_text


# ── Rate-limit retry / opt-out ──────────────────────────────────────────────

class TestRateLimitAndOptOut:
    def _setup(self, notify, monkeypatch, send_returns):
        """Build a Twilio client whose messages.create yields `send_returns` in sequence."""
        monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACfake")
        monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tokenfake")
        monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15005550006")
        client = MagicMock()
        client.messages.create.side_effect = send_returns
        notify._client = client
        notify._account_probed = True
        return client

    def test_retries_on_429_then_succeeds(self, notify, monkeypatch, caplog):
        """429 once → backoff → success."""
        from backend.services import notification_resilience as resilience
        sleeps: list[float] = []
        monkeypatch.setattr(resilience.time, "sleep", lambda s: sleeps.append(s))

        ok = MagicMock(sid="SMok")
        client = self._setup(notify, monkeypatch, [
            _FakeTwilioRestException(status=429, code=20429, msg="rate limit"),
            ok,
        ])
        with caplog.at_level("WARNING", logger="zpay.notify"):
            sid = notify.send_sms("+12065551234", "test")
        assert sid == "SMok"
        # First retry uses 1s backoff
        assert 1.0 in sleeps
        assert client.messages.create.call_count == 2

    def test_retries_three_times_then_gives_up_on_503(self, notify, monkeypatch):
        from backend.services import notification_resilience as resilience
        sleeps: list[float] = []
        monkeypatch.setattr(resilience.time, "sleep", lambda s: sleeps.append(s))

        client = self._setup(notify, monkeypatch, [
            _FakeTwilioRestException(status=503, msg="unavail"),
            _FakeTwilioRestException(status=503, msg="unavail"),
            _FakeTwilioRestException(status=503, msg="unavail"),
            _FakeTwilioRestException(status=503, msg="unavail"),
        ])
        sid = notify.send_sms("+12065551234", "test")
        assert sid is None
        # 1 initial + 3 retries = 4 attempts
        assert client.messages.create.call_count == 4
        # Backoffs applied: 1, 2, 4
        assert sleeps == [1.0, 2.0, 4.0]

    def test_opt_out_21610_adds_to_denylist(self, notify, monkeypatch, tmp_path):
        client = self._setup(notify, monkeypatch, [
            _FakeTwilioRestException(status=400, code=21610, msg="opted out"),
        ])
        sid = notify.send_sms("+12065551234", "test")
        assert sid is None
        assert notify.is_opted_out("+12065551234") is True
        # Denylist should be persisted on disk
        path = os.environ["ZPAY_OPTOUT_PATH"]
        assert os.path.exists(path)

    def test_subsequent_send_to_optout_short_circuits(self, notify, monkeypatch):
        notify.add_optout("+12065559999")
        # No twilio client setup — if it tries to call the SDK, MagicMock would still return,
        # but the contract is: short-circuit BEFORE creating a client.
        client = MagicMock()
        notify._client = client
        notify._account_probed = True

        sid = notify.send_sms("+12065559999", "test")
        assert sid is None
        client.messages.create.assert_not_called()


# ── Admin alert dedup ───────────────────────────────────────────────────────

class TestAdminAlertDedup:
    def test_identical_alert_within_60s_suppressed(self, notify, monkeypatch, caplog):
        monkeypatch.setenv("ADMIN_PHONE", "+12065550000")
        monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACfake")
        monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tokenfake")
        monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15005550006")

        client = MagicMock()
        client.messages.create.return_value = MagicMock(sid="SMok")
        client.calls.create.return_value = MagicMock(
            sid="CAok", answered_by="human", status="completed", duration="5"
        )
        notify._client = client
        notify._account_probed = True

        # Pin datetime.now to 10:00 AM PT so quiet-hours gate (22:00–07:00) never fires.
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from unittest.mock import patch as _patch
        daytime_dt = datetime(2026, 4, 29, 10, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
        with _patch("backend.services.notification_service.datetime") as mock_dt:
            mock_dt.now.return_value = daytime_dt

            notify.alert_admin("disk full at /var/log")
            notify.alert_admin("disk full at /var/log")  # dup, must suppress

        # SMS sent only once (admin SMS is the only client.messages.create caller here)
        assert client.messages.create.call_count == 1
        assert client.calls.create.call_count == 1

    def test_different_message_not_suppressed(self, notify, monkeypatch):
        monkeypatch.setenv("ADMIN_PHONE", "+12065550000")
        monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACfake")
        monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tokenfake")
        monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15005550006")

        client = MagicMock()
        client.messages.create.return_value = MagicMock(sid="SMok")
        client.calls.create.return_value = MagicMock(
            sid="CAok", answered_by="human", status="completed", duration="5"
        )
        notify._client = client
        notify._account_probed = True

        notify.alert_admin("incident A")
        notify.alert_admin("incident B")
        assert client.messages.create.call_count == 2


# ── Daily counters ──────────────────────────────────────────────────────────

class TestDailyCounters:
    def test_counter_bumps_on_send(self, notify, monkeypatch):
        monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACfake")
        monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tokenfake")
        monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15005550006")
        client = MagicMock()
        client.messages.create.return_value = MagicMock(sid="A")
        client.calls.create.return_value = MagicMock(
            sid="B", answered_by="human", status="completed", duration="5"
        )
        notify._client = client
        notify._account_probed = True

        before = notify.get_daily_counts()
        notify.send_sms("+12065551234", "x")
        notify.make_call("+12065551234", "y")
        after = notify.get_daily_counts()
        assert after["sms"] == before["sms"] + 1
        assert after["calls"] == before["calls"] + 1

    def test_counter_resets_on_new_pacific_day(self, notify, monkeypatch):
        # Force the date pointer ahead — the bump should detect rollover and reset
        from backend.services import notification_resilience as resilience
        resilience._counter_date = "1999-01-01"
        resilience._sms_count_today = 99
        resilience._call_count_today = 99
        n = resilience.bump_counter("sms")
        assert n == 1
        assert resilience._call_count_today == 0


# ── call_scripts: trip_ref + apostrophe-safe names ─────────────────────────

class TestCallScripts:
    def test_call_includes_trip_ref_when_provided(self):
        from backend.services.call_scripts import get_call_script
        out = get_call_script("en", "accept",
                              driver_name="Faiz", pickup_time="8:30",
                              trip_ref="T-12345")
        assert "Faiz" in out
        assert "8:30" in out
        assert "T-12345" in out
        assert "${" not in out  # no leftover placeholders

    def test_call_omits_trip_ref_clause_when_missing(self):
        from backend.services.call_scripts import get_call_script
        out = get_call_script("en", "accept",
                              driver_name="Faiz", pickup_time="8:30")
        assert "Faiz" in out
        assert "trip reference" not in out.lower()

    def test_apostrophe_in_name_xml_encoded(self):
        """
        Apostrophes in driver names must be XML-encoded (&apos;) so the
        rendered output is valid inside a TwiML <Say> element.
        The old literal-apostrophe expectation is superseded by Commit 4
        (XML-encode all interpolated values).
        """
        import xml.dom.minidom
        from backend.services.call_scripts import get_call_script
        out = get_call_script("en", "accept",
                              driver_name="M'hand", pickup_time="8:30")
        # Apostrophe must be encoded as &apos; in the TwiML output
        assert "&apos;" in out, f"Expected &apos; encoding, got: {out}"
        # Must also be valid XML
        xml_doc = f"<Response><Say>{out}</Say></Response>"
        xml.dom.minidom.parseString(xml_doc)  # raises if invalid

    def test_single_token_name_works(self):
        from backend.services.call_scripts import get_call_script
        out = get_call_script("en", "accept",
                              driver_name="Aisha", pickup_time="8:30")
        assert "Aisha" in out

    def test_control_chars_stripped_from_name(self):
        from backend.services.call_scripts import get_call_script
        out = get_call_script("en", "accept",
                              driver_name="Bad\x00<script>", pickup_time="8:30")
        assert "<" not in out
        assert ">" not in out
        assert "\x00" not in out

    def test_unknown_language_falls_back_to_en(self):
        from backend.services.call_scripts import get_call_script
        out = get_call_script("xx", "accept",
                              driver_name="Faiz", pickup_time="8:30")
        assert "Maz dispatch" in out

    def test_sms_no_leftover_placeholders(self):
        from backend.services.call_scripts import get_sms_script
        out = get_sms_script("en", "accept",
                             driver_name="Faiz", pickup_time="8:30")
        assert "${" not in out
        assert "Faiz" in out


# ══════════════════════════════════════════════════════════════════════════════
# Admin quiet-hours gate (Commit 3)
# ══════════════════════════════════════════════════════════════════════════════

class TestAdminQuietHours:
    """
    When the PT clock is in [22, 7) the admin voice call must be suppressed
    but the admin SMS must still go through.

    Strategy: patch module-level variables directly (no importlib.reload which
    leaves persistent side-effects on subsequent tests that import the same
    module).
    """

    def test_admin_in_quiet_hours_returns_true_at_2330(self):
        """_admin_in_quiet_hours() returns True when clock is 23:30 PT."""
        from unittest.mock import patch
        from datetime import datetime
        from zoneinfo import ZoneInfo
        import backend.services.notification_service as ns

        quiet_hour_dt = datetime(2026, 4, 29, 23, 30,
                                 tzinfo=ZoneInfo("America/Los_Angeles"))

        with (
            patch.object(ns, "_ADMIN_QUIET_START", 22),
            patch.object(ns, "_ADMIN_QUIET_END", 7),
            patch.object(ns, "_NOTIFY_TZ", ZoneInfo("America/Los_Angeles")),
            patch("backend.services.notification_service.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = quiet_hour_dt
            result = ns._admin_in_quiet_hours()

        assert result is True, "Expected _admin_in_quiet_hours() to return True at 23:30"

    def test_make_call_returns_none_for_admin_during_quiet_hours(self):
        """
        make_call() to the admin phone during quiet hours must return None
        (call suppressed) rather than attempting a Twilio call.
        """
        from unittest.mock import patch
        from datetime import datetime
        from zoneinfo import ZoneInfo
        import os
        import backend.services.notification_service as ns

        admin_phone = "+12065559999"
        quiet_hour_dt = datetime(2026, 4, 29, 23, 30,
                                 tzinfo=ZoneInfo("America/Los_Angeles"))

        with (
            patch.dict(os.environ, {"ADMIN_PHONE": admin_phone}),
            patch.object(ns, "_ADMIN_QUIET_START", 22),
            patch.object(ns, "_ADMIN_QUIET_END", 7),
            patch.object(ns, "_NOTIFY_TZ", ZoneInfo("America/Los_Angeles")),
            patch("backend.services.notification_service.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = quiet_hour_dt
            result = ns.make_call(admin_phone, "Test spoken message")

        assert result is None, (
            f"Expected make_call to return None during quiet hours, got {result!r}"
        )

    def test_call_suppressed_during_quiet_hours_but_sms_still_fires(self):
        """
        alert_admin() during quiet hours must fire SMS but NOT a voice call.

        Patches module-level variables directly so no reload side-effects bleed
        into other tests.  The real make_call() runs so the quiet-hours gate
        is exercised; Twilio client is mocked so no HTTP calls are made.
        """
        from unittest.mock import patch, MagicMock
        from datetime import datetime
        from zoneinfo import ZoneInfo
        import os
        import backend.services.notification_service as ns

        admin_phone = "+12065559999"
        quiet_hour_dt = datetime(2026, 4, 29, 23, 30,
                                 tzinfo=ZoneInfo("America/Los_Angeles"))

        sent_sms = []
        placed_calls = []

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = (
            lambda **kw: sent_sms.append(kw) or MagicMock(sid="sms-sid")
        )
        mock_client.calls.create.side_effect = (
            lambda **kw: placed_calls.append(kw) or MagicMock(sid="call-sid")
        )

        with (
            patch.dict(os.environ, {
                "ADMIN_PHONE": admin_phone,
                "TWILIO_ACCOUNT_SID": "ACtest",
                "TWILIO_AUTH_TOKEN": "test_token",
                "TWILIO_FROM_NUMBER": "+15005550006",
            }),
            patch.object(ns, "_ADMIN_QUIET_START", 22),
            patch.object(ns, "_ADMIN_QUIET_END", 7),
            patch.object(ns, "_NOTIFY_TZ", ZoneInfo("America/Los_Angeles")),
            patch("backend.services.notification_service.datetime") as mock_dt,
            patch("backend.services.notification_service._get_client", return_value=mock_client),
            patch("backend.services.notification_service._probe_account_status_once"),
            patch("backend.services.notification_service.admin_alert_should_send", return_value=True),
        ):
            mock_dt.now.return_value = quiet_hour_dt
            ns.alert_admin("Test quiet hours", spoken_message="Test spoken")

        assert len(sent_sms) == 1, f"Expected 1 SMS, got {len(sent_sms)}"
        assert len(placed_calls) == 0, (
            f"Expected 0 Twilio calls during quiet hours, got {len(placed_calls)}: {placed_calls}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# XML-encoding in call scripts (Commit 4)
# ══════════════════════════════════════════════════════════════════════════════

class TestCallScriptXmlEncoding:
    def test_ampersand_in_driver_name_is_xml_encoded(self):
        """
        Driver name containing '&' must produce &amp; in the script output.
        The rendered string must also be valid XML inside a TwiML <Say> element.
        """
        import xml.dom.minidom
        from backend.services.call_scripts import get_call_script

        result = get_call_script(
            "en", "accept",
            driver_name="A & B Logistics",
            pickup_time="07:00",
        )

        assert "A &amp; B Logistics" in result, (
            f"Expected &amp; encoding, got: {result}"
        )

        # Must parse as valid XML inside a <Say> wrapper
        xml_doc = f"<Response><Say>{result}</Say></Response>"
        try:
            xml.dom.minidom.parseString(xml_doc)
        except Exception as e:
            pytest.fail(f"TwiML XML parse failed: {e}\nContent: {result}")
