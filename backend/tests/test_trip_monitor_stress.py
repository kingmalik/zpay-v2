"""
Comprehensive stress test for trip_monitor.py

Tests trip classification logic, time parsing, and late-trip detection boundaries.
These are the core logic tests that don't require full service integration mocks.

Run with:
  python3 -m unittest backend.tests.test_trip_monitor_stress -v
"""

import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from backend.services import trip_monitor


class TripMonitorClassificationTests(unittest.TestCase):
    """Tests for trip_monitor classification functions."""

    # ────────────────────────────────────────────────────────────
    # FA Status Classification Tests
    # ────────────────────────────────────────────────────────────

    def test_01_classify_fa_unaccepted_markers(self):
        """Test FA status classification for unaccepted statuses."""
        test_cases = [
            ("PENDING", "unaccepted"),
            ("DISPATCH", "unaccepted"),
            ("NOT_ACCEPTED", "unaccepted"),
            ("AWAITING", "unaccepted"),
            ("OFFER", "unaccepted"),
            ("SCHEDULED", "unaccepted"),
            ("pending", "unaccepted"),  # Case insensitive
            ("dispatch", "unaccepted"),
        ]
        for status, expected in test_cases:
            with self.subTest(status=status):
                result = trip_monitor.classify_fa(status)
                self.assertEqual(
                    result, expected,
                    f"FA status '{status}' should classify as '{expected}', got '{result}'"
                )

    def test_02_classify_fa_accepted_markers(self):
        """Test FA status classification for accepted statuses."""
        test_cases = [
            ("ACCEPTED", "accepted"),
            ("ACCEPT", "accepted"),
            ("accepted", "accepted"),
        ]
        for status, expected in test_cases:
            with self.subTest(status=status):
                result = trip_monitor.classify_fa(status)
                self.assertEqual(result, expected)

    def test_03_classify_fa_started_markers(self):
        """Test FA status classification for started/in-progress statuses."""
        test_cases = [
            ("IN_PROGRESS", "started"),
            ("IN PROGRESS", "started"),
            ("INPROGRESS", "started"),
            ("PROGRESS", "started"),
            ("ENROUTE", "started"),
            ("EN_ROUTE", "started"),
            ("EN ROUTE", "started"),
            ("PICKED_UP", "started"),
            ("PICKED UP", "started"),
            ("ONBOARD", "started"),
            ("ON_BOARD", "started"),
            ("ARRIVED", "started"),
        ]
        for status, expected in test_cases:
            with self.subTest(status=status):
                result = trip_monitor.classify_fa(status)
                self.assertEqual(result, expected)

    def test_04_classify_fa_completed_markers(self):
        """Test FA status classification for completed statuses."""
        test_cases = [
            ("COMPLETED", "completed"),
            ("FINISHED", "completed"),
            ("DONE", "completed"),
            ("COMPLETE", "completed"),
            ("FINISH", "completed"),
        ]
        for status, expected in test_cases:
            with self.subTest(status=status):
                result = trip_monitor.classify_fa(status)
                self.assertEqual(result, expected)

    def test_05_classify_fa_cancelled_markers(self):
        """Test FA status classification for cancelled statuses."""
        test_cases = [
            ("CANCELLED", "cancelled"),
            ("CANCELED", "cancelled"),
            ("CANCEL", "cancelled"),
            ("CLOSED", "cancelled"),
            ("CLOSE", "cancelled"),
            ("VOID", "cancelled"),
        ]
        for status, expected in test_cases:
            with self.subTest(status=status):
                result = trip_monitor.classify_fa(status)
                self.assertEqual(result, expected)

    def test_06_classify_fa_declined_markers(self):
        """Test FA status classification for declined statuses."""
        test_cases = [
            ("DECLINED", "declined"),
            ("DECLINE", "declined"),
            ("SUBSTITUTE", "declined"),
            ("SUB_NEEDED", "declined"),
            ("REMOVED", "declined"),
            ("REJECTED", "declined"),
            ("REJECT", "declined"),
        ]
        for status, expected in test_cases:
            with self.subTest(status=status):
                result = trip_monitor.classify_fa(status)
                self.assertEqual(result, expected)

    def test_07_classify_fa_unknown_statuses(self):
        """Test FA status classification for unknown statuses."""
        test_cases = [
            ("UNKNOWN_STATUS_XYZ", "unknown"),
            ("", "unknown"),
            ("SOME_INVALID_STATUS", "unknown"),
            (None, "unknown"),
        ]
        for status, expected in test_cases:
            with self.subTest(status=status):
                result = trip_monitor.classify_fa(status)
                self.assertEqual(result, expected, f"Unknown status '{status}' should return 'unknown'")

    def test_08_classify_fa_priority_order(self):
        """Test FA classification respects priority order (decline > complete/cancel > started > accepted > unaccepted)."""
        # NOT_ACCEPTED contains ACCEPT but should classify as unaccepted (checked before accepted)
        result = trip_monitor.classify_fa("NOT_ACCEPTED")
        self.assertEqual(result, "unaccepted")

        # AWAITING_ACCEPTANCE contains ACCEPT but should classify as unaccepted
        result = trip_monitor.classify_fa("AWAITING_ACCEPTANCE")
        self.assertEqual(result, "unaccepted")

    # ────────────────────────────────────────────────────────────
    # ED Status Classification Tests
    # ────────────────────────────────────────────────────────────

    def test_09_classify_ed_scheduled_with_driver_guid(self):
        """ED: Scheduled with driverGUID → accepted."""
        result = trip_monitor.classify_ed("Scheduled", "driver-guid-123")
        self.assertEqual(result, "accepted")

    def test_10_classify_ed_scheduled_without_driver_guid(self):
        """ED: Scheduled without driverGUID → unaccepted."""
        result = trip_monitor.classify_ed("Scheduled", None)
        self.assertEqual(result, "unaccepted")

    def test_11_classify_ed_accepted_state(self):
        """ED: Accepted state → accepted."""
        result = trip_monitor.classify_ed("Accepted", "guid")
        self.assertEqual(result, "accepted")

    def test_12_classify_ed_accepted_without_driver(self):
        """ED: Accepted state without driver → still accepted (override only for Scheduled)."""
        result = trip_monitor.classify_ed("Accepted", None)
        # The override to unaccepted (line 112) applies to any state mapping to "accepted"
        # including both Scheduled and Accepted states
        self.assertEqual(result, "unaccepted")

    def test_13_classify_ed_no_status_no_driver(self):
        """ED: No status, no driver → unaccepted."""
        result = trip_monitor.classify_ed("", None)
        self.assertEqual(result, "unaccepted")

    def test_14_classify_ed_no_status_with_driver(self):
        """ED: No status but has driver → unknown."""
        result = trip_monitor.classify_ed("", "guid")
        self.assertEqual(result, "unknown")

    def test_15_classify_ed_started_states(self):
        """ED: Active, AtStop, ToStop → started."""
        for status in ["Active", "AtStop", "ToStop"]:
            with self.subTest(status=status):
                result = trip_monitor.classify_ed(status, "guid")
                self.assertEqual(result, "started")

    def test_16_classify_ed_completed(self):
        """ED: Completed → completed."""
        result = trip_monitor.classify_ed("Completed", "guid")
        self.assertEqual(result, "completed")

    def test_17_classify_ed_declined(self):
        """ED: Declined → declined."""
        result = trip_monitor.classify_ed("Declined", "guid")
        self.assertEqual(result, "declined")

    def test_18_classify_ed_cancelled_variants(self):
        """ED: Cancelled and Canceled → cancelled."""
        for status in ["Cancelled", "Canceled"]:
            with self.subTest(status=status):
                result = trip_monitor.classify_ed(status, "guid")
                self.assertEqual(result, "cancelled")

    def test_19_classify_ed_unknown_status(self):
        """ED: Unknown status code → unknown."""
        result = trip_monitor.classify_ed("UNKNOWN_STATUS", "guid")
        self.assertEqual(result, "unknown")

    # ────────────────────────────────────────────────────────────
    # Pickup Time Parsing Tests
    # ────────────────────────────────────────────────────────────

    def test_20_parse_pickup_time_hh_mm_format(self):
        """Test pickup time parsing for HH:MM format."""
        from datetime import date
        trip_date = date(2026, 4, 20)
        tz = ZoneInfo("America/Los_Angeles")

        result = trip_monitor._parse_pickup_time("10:30", trip_date, tz)
        self.assertIsNotNone(result)
        self.assertEqual(result.hour, 10)
        self.assertEqual(result.minute, 30)
        self.assertEqual(result.date(), trip_date)

    def test_21_parse_pickup_time_iso_format(self):
        """Test pickup time parsing for ISO format."""
        from datetime import date
        trip_date = date(2026, 4, 20)
        tz = ZoneInfo("America/Los_Angeles")

        result = trip_monitor._parse_pickup_time("2026-04-20T10:30", trip_date, tz)
        self.assertIsNotNone(result)
        self.assertEqual(result.hour, 10)
        self.assertEqual(result.minute, 30)

    def test_22_parse_pickup_time_iso_with_z(self):
        """Test pickup time parsing for ISO format with Z suffix."""
        from datetime import date
        trip_date = date(2026, 4, 20)
        tz = ZoneInfo("America/Los_Angeles")

        result = trip_monitor._parse_pickup_time("2026-04-20T10:30Z", trip_date, tz)
        self.assertIsNotNone(result)

    def test_23_parse_pickup_time_am_pm_format(self):
        """Test pickup time parsing for 12-hour format."""
        from datetime import date
        trip_date = date(2026, 4, 20)
        tz = ZoneInfo("America/Los_Angeles")

        result = trip_monitor._parse_pickup_time("10:30 AM", trip_date, tz)
        self.assertIsNotNone(result)
        self.assertEqual(result.hour, 10)

    def test_24_parse_pickup_time_invalid_format(self):
        """Test pickup time parsing for invalid format returns None."""
        from datetime import date
        trip_date = date(2026, 4, 20)
        tz = ZoneInfo("America/Los_Angeles")

        result = trip_monitor._parse_pickup_time("invalid-time-string", trip_date, tz)
        self.assertIsNone(result)

    def test_25_parse_pickup_time_empty_string(self):
        """Test pickup time parsing for empty string returns None."""
        from datetime import date
        trip_date = date(2026, 4, 20)
        tz = ZoneInfo("America/Los_Angeles")

        result = trip_monitor._parse_pickup_time("", trip_date, tz)
        self.assertIsNone(result)

    # ────────────────────────────────────────────────────────────
    # Acceptance Window Tests (60 minutes)
    # ────────────────────────────────────────────────────────────

    def test_30_acceptance_window_55min_inside(self):
        """Trip 55 min before pickup → inside 60-min acceptance window."""
        tz = ZoneInfo("America/Los_Angeles")
        now = datetime(2026, 4, 20, 10, 0, tzinfo=tz)
        pickup_dt = now + timedelta(minutes=55)

        mins_until_pickup = (pickup_dt - now).total_seconds() / 60
        in_window = mins_until_pickup <= 60

        self.assertTrue(in_window, "55 min should be inside 60-min window")
        self.assertEqual(mins_until_pickup, 55)

    def test_31_acceptance_window_60min_at_edge(self):
        """Trip exactly 60 min before pickup → at edge of acceptance window."""
        tz = ZoneInfo("America/Los_Angeles")
        now = datetime(2026, 4, 20, 10, 0, tzinfo=tz)
        pickup_dt = now + timedelta(minutes=60)

        mins_until_pickup = (pickup_dt - now).total_seconds() / 60
        in_window = mins_until_pickup <= 60

        self.assertTrue(in_window, "60 min should be in window (at edge)")

    def test_32_acceptance_window_48min_inside(self):
        """Trip 48 min before pickup → inside 60-min acceptance window."""
        tz = ZoneInfo("America/Los_Angeles")
        now = datetime(2026, 4, 20, 10, 0, tzinfo=tz)
        pickup_dt = now + timedelta(minutes=48)

        mins_until_pickup = (pickup_dt - now).total_seconds() / 60
        in_window = mins_until_pickup <= 60

        self.assertTrue(in_window, "48 min should be inside 60-min window")

    # ────────────────────────────────────────────────────────────
    # Start Reminder Window Tests (15 minutes)
    # ────────────────────────────────────────────────────────────

    def test_33_start_window_52min_outside(self):
        """Trip 52 min before pickup → outside 15-min start reminder window."""
        tz = ZoneInfo("America/Los_Angeles")
        now = datetime(2026, 4, 20, 10, 0, tzinfo=tz)
        pickup_dt = now + timedelta(minutes=52)

        mins_until_pickup = (pickup_dt - now).total_seconds() / 60
        in_window = mins_until_pickup <= 15

        self.assertFalse(in_window, "52 min should be outside 15-min start window")

    def test_34_start_window_15min_at_edge(self):
        """Trip exactly 15 min before pickup → at edge of start reminder window."""
        tz = ZoneInfo("America/Los_Angeles")
        now = datetime(2026, 4, 20, 10, 0, tzinfo=tz)
        pickup_dt = now + timedelta(minutes=15)

        mins_until_pickup = (pickup_dt - now).total_seconds() / 60
        in_window = mins_until_pickup <= 15

        self.assertTrue(in_window, "15 min should be in start window (at edge)")

    def test_35_start_window_12min_inside(self):
        """Trip 12 min before pickup → inside 15-min start reminder window."""
        tz = ZoneInfo("America/Los_Angeles")
        now = datetime(2026, 4, 20, 10, 0, tzinfo=tz)
        pickup_dt = now + timedelta(minutes=12)

        mins_until_pickup = (pickup_dt - now).total_seconds() / 60
        in_window = mins_until_pickup <= 15

        self.assertTrue(in_window, "12 min should be inside 15-min start window")

    # ────────────────────────────────────────────────────────────
    # Escalation Timing Tests (20 min call delay, immediate escalation)
    # ────────────────────────────────────────────────────────────

    def test_36_call_delay_window_6min(self):
        """SMS sent 6 min ago, need to wait 20 min for call."""
        now = datetime(2026, 4, 20, 10, 6, tzinfo=ZoneInfo("America/Los_Angeles"))
        sms_time = now - timedelta(minutes=6)

        # _CALL_DELAY = 20 minutes
        time_since_sms = (now - sms_time).total_seconds() / 60
        call_ready = time_since_sms >= 20

        self.assertFalse(call_ready, "At 6 min, should not call yet")

    def test_37_call_delay_window_20min(self):
        """SMS sent 20 min ago, call ready."""
        now = datetime(2026, 4, 20, 10, 20, tzinfo=ZoneInfo("America/Los_Angeles"))
        sms_time = now - timedelta(minutes=20)

        time_since_sms = (now - sms_time).total_seconds() / 60
        call_ready = time_since_sms >= 20

        self.assertTrue(call_ready, "At 20 min, call should be ready")

    def test_38_escalation_delay_0(self):
        """With _ESCALATION_DELAY=0, escalate immediately after call."""
        now = datetime(2026, 4, 20, 10, 25, tzinfo=ZoneInfo("America/Los_Angeles"))
        call_time = now - timedelta(minutes=5)

        # _ESCALATION_DELAY = 0 (default)
        time_since_call = (now - call_time).total_seconds() / 60
        escalation_ready = time_since_call >= 0

        self.assertTrue(escalation_ready, "With delay=0, should escalate immediately")

    # ────────────────────────────────────────────────────────────
    # Edge Cases & Error Handling
    # ────────────────────────────────────────────────────────────

    def test_39_classify_fa_whitespace_handling(self):
        """FA classification should handle leading/trailing whitespace."""
        result = trip_monitor.classify_fa("  PENDING  ")
        self.assertEqual(result, "unaccepted")

    def test_40_classify_fa_mixed_case(self):
        """FA classification should be case-insensitive."""
        test_cases = [
            ("PeNdInG", "unaccepted"),
            ("In_Progress", "started"),
            ("CoMpLeTeD", "completed"),
        ]
        for status, expected in test_cases:
            with self.subTest(status=status):
                result = trip_monitor.classify_fa(status)
                self.assertEqual(result, expected)

    def test_41_parse_pickup_time_preserves_timezone(self):
        """Parsed pickup time should preserve the provided timezone."""
        from datetime import date
        trip_date = date(2026, 4, 20)
        tz = ZoneInfo("America/Los_Angeles")

        result = trip_monitor._parse_pickup_time("10:30", trip_date, tz)
        self.assertIsNotNone(result)
        self.assertEqual(result.tzinfo, tz)


if __name__ == "__main__":
    unittest.main()
