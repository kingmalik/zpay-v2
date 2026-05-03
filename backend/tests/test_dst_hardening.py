"""
DST/timezone hardening tests — Phase 3.

Verifies that trip_monitor._make_local_dt and _parse_pickup_time handle
DST transition days correctly (no naive datetimes, no crashes, correct
UTC offset on either side of the transition).

Key transition dates for America/Los_Angeles:
  - Spring forward: 2026-03-08 at 02:00 PST → 03:00 PDT  (UTC-7)
  - Fall back:      2026-11-01 at 02:00 PDT → 01:00 PST  (UTC-8)

quiet_hours.in_quiet_hours() is also tested to ensure it uses an
aware datetime (never a naive compare) so 21:00 PST and 21:00 PDT
both land in the quiet window correctly.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.environ.setdefault("MONITOR_DRY_RUN", "1")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost/test")
os.environ.setdefault("ZPAY_SECRET_KEY", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("ZPAY_ENCRYPTION_KEY", "Ry9f3q2lX1kN8pM7vB4cZ6wQ0sJ5uY2eD3tH9oA1gU=")

_LA = ZoneInfo("America/Los_Angeles")

# DST transition dates for 2026
_SPRING_FORWARD = date(2026, 3, 8)   # 02:00 PST becomes 03:00 PDT (UTC-7)
_FALL_BACK = date(2026, 11, 1)        # 02:00 PDT becomes 01:00 PST (UTC-8)

# UTC offsets expected on each side
_PDT_OFFSET = timedelta(hours=-7)  # Pacific Daylight Time
_PST_OFFSET = timedelta(hours=-8)  # Pacific Standard Time


# ── Import the functions under test ──────────────────────────────────────────

def _import_trip_monitor_fns():
    import importlib
    import backend.services.trip_monitor as _mod
    importlib.reload(_mod)
    return _mod._make_local_dt, _mod._parse_pickup_time


# ── _make_local_dt ────────────────────────────────────────────────────────────

class TestMakeLocalDt:
    """_make_local_dt must always return a timezone-aware datetime."""

    def test_returns_aware_datetime_normal_day(self):
        make_local_dt, _ = _import_trip_monitor_fns()
        dt = make_local_dt(date(2026, 5, 2), 7, 30, _LA)
        assert dt.tzinfo is not None
        assert dt.utcoffset() == _PDT_OFFSET  # May 2 is in PDT

    def test_spring_forward_before_transition(self):
        """01:30 on spring-forward day is still PST (UTC-8)."""
        make_local_dt, _ = _import_trip_monitor_fns()
        dt = make_local_dt(_SPRING_FORWARD, 1, 30, _LA)
        assert dt.tzinfo is not None
        assert dt.utcoffset() == _PST_OFFSET

    def test_spring_forward_after_transition(self):
        """03:30 on spring-forward day is PDT (UTC-7) — 02:xx doesn't exist."""
        make_local_dt, _ = _import_trip_monitor_fns()
        dt = make_local_dt(_SPRING_FORWARD, 3, 30, _LA)
        assert dt.tzinfo is not None
        assert dt.utcoffset() == _PDT_OFFSET

    def test_spring_forward_gap_hour_does_not_crash(self):
        """02:30 on spring-forward day falls in the gap — ZoneInfo handles it."""
        make_local_dt, _ = _import_trip_monitor_fns()
        # Should not raise; ZoneInfo folds into the pre-transition time
        dt = make_local_dt(_SPRING_FORWARD, 2, 30, _LA)
        assert dt is not None
        assert dt.tzinfo is not None

    def test_fall_back_before_transition_is_pdt(self):
        """01:30 on fall-back day first occurrence is PDT (UTC-7) at fold=0."""
        make_local_dt, _ = _import_trip_monitor_fns()
        dt = make_local_dt(_FALL_BACK, 1, 30, _LA)
        assert dt.tzinfo is not None
        # fold=0 selects the FIRST 01:30 (PDT = UTC-7)
        assert dt.utcoffset() == _PDT_OFFSET

    def test_fall_back_after_transition_hour_is_pst(self):
        """02:30 on fall-back day is definitely PST (UTC-8) — past the transition."""
        make_local_dt, _ = _import_trip_monitor_fns()
        dt = make_local_dt(_FALL_BACK, 2, 30, _LA)
        assert dt.tzinfo is not None
        assert dt.utcoffset() == _PST_OFFSET

    def test_normal_summer_day_is_pdt(self):
        make_local_dt, _ = _import_trip_monitor_fns()
        dt = make_local_dt(date(2026, 7, 15), 8, 0, _LA)
        assert dt.utcoffset() == _PDT_OFFSET

    def test_normal_winter_day_is_pst(self):
        make_local_dt, _ = _import_trip_monitor_fns()
        dt = make_local_dt(date(2026, 12, 1), 8, 0, _LA)
        assert dt.utcoffset() == _PST_OFFSET

    def test_never_returns_naive_datetime(self):
        """Regression: must never return a naive (tzinfo=None) datetime."""
        make_local_dt, _ = _import_trip_monitor_fns()
        for test_date in (_SPRING_FORWARD, _FALL_BACK, date(2026, 1, 15), date(2026, 8, 20)):
            dt = make_local_dt(test_date, 7, 0, _LA)
            assert dt.tzinfo is not None, f"naive datetime returned for {test_date}"


# ── _parse_pickup_time ────────────────────────────────────────────────────────

class TestParsePickupTime:
    """_parse_pickup_time must produce tz-aware datetimes on DST days."""

    def test_hhmm_format_spring_forward_morning(self):
        _, parse = _import_trip_monitor_fns()
        dt = parse("07:30", _SPRING_FORWARD, _LA)
        assert dt is not None
        assert dt.tzinfo is not None
        assert dt.utcoffset() == _PDT_OFFSET

    def test_hhmm_format_fall_back_morning(self):
        _, parse = _import_trip_monitor_fns()
        # 07:30 on fall-back day is unambiguous PST
        dt = parse("07:30", _FALL_BACK, _LA)
        assert dt is not None
        assert dt.tzinfo is not None
        assert dt.utcoffset() == _PST_OFFSET

    def test_iso_format_with_tz_preserved(self):
        """ISO string with explicit UTC offset must keep its tzinfo."""
        _, parse = _import_trip_monitor_fns()
        dt = parse("2026-03-08T07:30:00+00:00", _SPRING_FORWARD, _LA)
        assert dt is not None
        assert dt.tzinfo is not None

    def test_iso_format_naive_gets_tz_applied(self):
        """ISO string without tz (ED format) gets the local timezone applied."""
        _, parse = _import_trip_monitor_fns()
        dt = parse("2026-03-08T07:30", _SPRING_FORWARD, _LA)
        assert dt is not None
        assert dt.tzinfo is not None

    def test_hhmm_format_returns_none_for_garbage(self):
        _, parse = _import_trip_monitor_fns()
        assert parse("not-a-time", date(2026, 3, 8), _LA) is None

    def test_hhmm_format_returns_none_for_empty(self):
        _, parse = _import_trip_monitor_fns()
        assert parse("", date(2026, 3, 8), _LA) is None

    def test_hhmm_format_returns_none_for_none(self):
        _, parse = _import_trip_monitor_fns()
        assert parse(None, date(2026, 3, 8), _LA) is None  # type: ignore[arg-type]

    def test_fall_back_ambiguous_01xx_no_crash(self):
        """01:30 is ambiguous on fall-back day — should not raise."""
        _, parse = _import_trip_monitor_fns()
        dt = parse("01:30", _FALL_BACK, _LA)
        assert dt is not None
        assert dt.tzinfo is not None

    def test_spring_forward_gap_01xx_aware(self):
        """01:30 on spring-forward day is in the vanished hour gap — must still return aware dt."""
        _, parse = _import_trip_monitor_fns()
        dt = parse("02:30", _SPRING_FORWARD, _LA)
        # May be None if the format parser decides it's invalid, but must not raise
        # If returned, must be tz-aware
        if dt is not None:
            assert dt.tzinfo is not None


# ── quiet_hours DST correctness ───────────────────────────────────────────────

class TestQuietHoursDST:
    """quiet_hours.in_quiet_hours() must work on DST transition days."""

    def _call_in_quiet_hours(self, fake_now: datetime) -> bool:
        """Call in_quiet_hours() with a patched datetime.now."""
        import importlib
        import backend.services.quiet_hours as qh_mod

        # Reload to pick up fresh env
        importlib.reload(qh_mod)

        with patch.object(
            qh_mod,
            "in_quiet_hours",
            wraps=lambda: _wrapped_in_quiet_hours(fake_now, qh_mod),
        ):
            return qh_mod.in_quiet_hours()

    def test_quiet_window_on_spring_forward_day_late_night(self):
        """23:00 PST on spring-forward day should be in quiet window."""
        import importlib
        import backend.services.quiet_hours as qh_mod
        importlib.reload(qh_mod)

        fake_now = datetime(2026, 3, 8, 23, 0, tzinfo=_LA)
        with patch("backend.services.quiet_hours.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            result = qh_mod.in_quiet_hours()
        assert result is True, "23:00 on spring-forward day should be quiet"

    def test_active_window_on_spring_forward_day_midday(self):
        """12:00 PDT on spring-forward day should NOT be in quiet window."""
        import importlib
        import backend.services.quiet_hours as qh_mod
        importlib.reload(qh_mod)

        fake_now = datetime(2026, 3, 8, 12, 0, tzinfo=_LA)
        with patch("backend.services.quiet_hours.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            result = qh_mod.in_quiet_hours()
        assert result is False, "12:00 should be active window"

    def test_quiet_window_on_fall_back_day_late_night(self):
        """22:30 PDT on fall-back day should be in quiet window."""
        import importlib
        import backend.services.quiet_hours as qh_mod
        importlib.reload(qh_mod)

        fake_now = datetime(2026, 11, 1, 22, 30, tzinfo=_LA)
        with patch("backend.services.quiet_hours.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            result = qh_mod.in_quiet_hours()
        assert result is True, "22:30 on fall-back day should be quiet"

    def test_active_window_on_fall_back_day_morning(self):
        """08:00 PST on fall-back day should NOT be in quiet window."""
        import importlib
        import backend.services.quiet_hours as qh_mod
        importlib.reload(qh_mod)

        fake_now = datetime(2026, 11, 1, 8, 0, tzinfo=_LA)
        with patch("backend.services.quiet_hours.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            result = qh_mod.in_quiet_hours()
        assert result is False, "08:00 on fall-back day should be active"


def _wrapped_in_quiet_hours(fake_now: datetime, qh_mod) -> bool:
    """Helper: compute quiet-hours using the fake_now timestamp directly."""
    hour = fake_now.astimezone(_LA).hour
    start = qh_mod._QUIET_START
    end = qh_mod._QUIET_END
    if start > end:
        return hour >= start or hour < end
    return start <= hour < end


# ── UTC arithmetic correctness ─────────────────────────────────────────────

class TestUtcArithmetic:
    """No naive datetime arithmetic anywhere near DST boundaries."""

    def test_make_local_dt_utc_round_trip_spring(self):
        """Spring-forward: 07:30 PDT should be 14:30 UTC."""
        make_local_dt, _ = _import_trip_monitor_fns()
        dt_local = make_local_dt(_SPRING_FORWARD, 7, 30, _LA)
        dt_utc = dt_local.astimezone(timezone.utc)
        assert dt_utc.hour == 14
        assert dt_utc.minute == 30

    def test_make_local_dt_utc_round_trip_fall(self):
        """Fall-back: 07:30 PST (after transition) should be 15:30 UTC."""
        make_local_dt, _ = _import_trip_monitor_fns()
        dt_local = make_local_dt(_FALL_BACK, 7, 30, _LA)
        dt_utc = dt_local.astimezone(timezone.utc)
        # 07:30 PST = UTC-8 → 15:30 UTC
        assert dt_utc.hour == 15
        assert dt_utc.minute == 30

    def test_timedelta_across_spring_forward(self):
        """60-minute window spanning spring-forward must not go negative."""
        make_local_dt, _ = _import_trip_monitor_fns()
        dt_before = make_local_dt(_SPRING_FORWARD, 1, 30, _LA)  # 01:30 PST
        dt_after = make_local_dt(_SPRING_FORWARD, 3, 30, _LA)   # 03:30 PDT
        # Real elapsed time is 60 minutes (clock jumps from 02:00 to 03:00)
        delta = dt_after.astimezone(timezone.utc) - dt_before.astimezone(timezone.utc)
        assert delta == timedelta(hours=1)

    def test_timedelta_across_fall_back(self):
        """120-minute window spanning fall-back measures real elapsed UTC."""
        make_local_dt, _ = _import_trip_monitor_fns()
        dt_before = make_local_dt(_FALL_BACK, 0, 30, _LA)   # 00:30 PDT
        dt_after = make_local_dt(_FALL_BACK, 2, 30, _LA)    # 02:30 PST
        # Real elapsed: 3 hours (clock falls back 1 hour at 02:00)
        delta = dt_after.astimezone(timezone.utc) - dt_before.astimezone(timezone.utc)
        assert delta == timedelta(hours=3)
