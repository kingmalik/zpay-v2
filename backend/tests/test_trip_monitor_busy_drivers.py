"""
Regression tests for the busy_drivers concurrent-trip suppression logic
introduced in commits 505f33b and 045c69d (2026-04-22).

Behaviour under test
--------------------
A `busy_drivers` set is built at the start of every monitoring cycle from
trips that have `is_started=True` AND a linked `person`.  Any other trip for
that same person which is still in the `accepted` bucket (Stage 2) or in the
`unaccepted/accepted` overdue bucket is suppressed — the driver is physically
mid-ride and cannot pick up the next student yet.

Summary counter `start_suppressed_concurrent` is incremented for each
suppressed Stage-2 attempt.

All tests use the same in-memory SQLite infrastructure and mocking pattern
established in test_trip_monitor.py.  Do not invent new patterns — reuse
_execute_cycle(), _make_fa_trip(), etc. directly from this module or reproduce
them locally where the existing helpers are unavailable.
"""

from __future__ import annotations

import sys
import types
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import (
    Boolean, Column, Date, DateTime, ForeignKey,
    Integer, Text, create_engine,
)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker

# ── Project root on sys.path ────────────────────────────────────────────────
import os
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ── Reuse the in-memory models from the sibling test module ─────────────────
# We import only the model classes and helper constants/functions; the actual
# test infrastructure (engine creation, patching) is re-implemented here so
# this file is self-contained and can run in isolation.

from backend.tests.test_trip_monitor import (  # noqa: E402
    _TestBase,
    _Person,
    _TripNotification,
    _make_session_factory,
    _execute_cycle,
    _make_fa_trip,
    _make_ed_run,
    _make_notify_mock,
    _dt,
    _dt_naive,
    TZ,
    TRIP_DATE,
)


# ─────────────────────────────────────────────────────────────────────────────
# Cross-file contamination guard
# ─────────────────────────────────────────────────────────────────────────────
# test_notification_service.py imports the REAL notification_service module,
# which Python then caches as an attribute on the `backend.services` namespace
# package. When `_execute_cycle` patches sys.modules["backend.services.
# notification_service"] with a mock, `from backend.services import
# notification_service` inside _run_monitoring_cycle_impl would still resolve
# to the package ATTRIBUTE (the real module) rather than sys.modules.
#
# This autouse fixture removes that attribute before each test so the
# sys.modules patch wins — matching the teardown pattern already implemented
# in test_notification_service.py's `notify` fixture.

@pytest.fixture(autouse=True)
def _clear_notification_service_pkg_attr():
    """Ensure `backend.services.notification_service` is not cached as a
    package attribute before each test so patch.dict on sys.modules wins.
    """
    import importlib
    try:
        services_pkg = importlib.import_module("backend.services")
        if hasattr(services_pkg, "notification_service"):
            delattr(services_pkg, "notification_service")
    except Exception:
        pass
    yield
    # Teardown: leave clean for the next test too.
    try:
        services_pkg = importlib.import_module("backend.services")
        if hasattr(services_pkg, "notification_service"):
            delattr(services_pkg, "notification_service")
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Scenario helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_person(
    person_id: int = 1,
    full_name: str = "Faize Kaifa",
    phone: str = "+12065550011",
    fa_id: int | None = 101,
    ed_id: int | None = None,
) -> _Person:
    return _Person(
        person_id=person_id,
        full_name=full_name,
        phone=phone,
        language="en",
        firstalt_driver_id=fa_id,
        everdriven_driver_id=ed_id,
        active=True,
    )


def _make_accepted_notif(
    person_id: int,
    trip_ref: str,
    pickup_time: str,
    source: str = "firstalt",
    accepted_at: datetime | None = None,
) -> _TripNotification:
    """Pre-existing TripNotification with accepted_at set (prior cycle).
    Uses naive datetime so SQLite round-trip doesn't explode on tz arithmetic.
    """
    return _TripNotification(
        person_id=person_id,
        trip_date=TRIP_DATE,
        source=source,
        trip_ref=trip_ref,
        trip_status="ACCEPTED",
        pickup_time=pickup_time,
        accepted_at=accepted_at or _dt_naive(7, 0),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Faize Kaifa pattern — Stage 2 suppressed while mid-drop on trip A
# ─────────────────────────────────────────────────────────────────────────────

class TestBusyDriversStage2Suppressed:
    """Driver mid-drop on trip A (ToStop / started); trip B is accepted and
    within the start-reminder window.  Stage 2 must NOT fire an SMS or call
    for trip B.
    """

    def test_stage2_sms_suppressed_and_counter_incremented(self):
        """
        Setup:
          Trip A — FA status=IN_PROGRESS (started bucket for FA), driver_id=101, pickup=07:55
          Trip B — FA status=ACCEPTED, driver_id=101, pickup=08:05
          now=08:00  → Trip B is 5 min away, inside _START_REMINDER_MINUTES=15

        Expected:
          - No send_sms call
          - No make_call call
          - summary["start_suppressed_concurrent"] == 1

        Note: ToStop is an EverDriven status; for FA trips use IN_PROGRESS/ENROUTE.
        """
        person = _make_person()

        trip_a = _make_fa_trip(
            trip_id="T-A-001",
            status="IN_PROGRESS",  # FA started status → classify_fa → "started"
            driver_id=101,
            pickup="07:55",
            first_name="Faize",
            last_name="Kaifa",
        )
        trip_b = _make_fa_trip(
            trip_id="T-B-001",
            status="ACCEPTED",
            driver_id=101,
            pickup="08:05",
            first_name="Faize",
            last_name="Kaifa",
        )

        # Trip B already has accepted_at set so Stage 2 fires (not just_accepted).
        notif_b = _make_accepted_notif(
            person_id=1,
            trip_ref="T-B-001",
            pickup_time="08:05",
        )

        summary, notify, _ = _execute_cycle(
            now=_dt(8, 0),
            fa_trips=[trip_a, trip_b],
            persons=[person],
            pre_existing_notifs=[notif_b],
        )

        notify.send_sms.assert_not_called()
        notify.make_call.assert_not_called()
        assert summary["start_suppressed_concurrent"] == 1

    def test_stage2_suppressed_even_when_past_start_window(self):
        """Stage 2 suppression fires before the reminder-window check, so even a
        trip that would normally be past its start window still gets suppressed
        and does NOT produce a stale/overdue start alert.
        """
        person = _make_person()

        # Trip A is started (ENROUTE is a valid FA started status).
        trip_a = _make_fa_trip(
            trip_id="T-A-002",
            status="ENROUTE",
            driver_id=101,
            pickup="07:45",
            first_name="Faize",
            last_name="Kaifa",
        )
        # Trip B is accepted; pickup was 7 min ago — past the start window.
        trip_b = _make_fa_trip(
            trip_id="T-B-002",
            status="ACCEPTED",
            driver_id=101,
            pickup="07:53",
            first_name="Faize",
            last_name="Kaifa",
        )
        notif_b = _make_accepted_notif(
            person_id=1,
            trip_ref="T-B-002",
            pickup_time="07:53",
        )

        summary, notify, _ = _execute_cycle(
            now=_dt(8, 0),
            fa_trips=[trip_a, trip_b],
            persons=[person],
            pre_existing_notifs=[notif_b],
        )

        notify.send_sms.assert_not_called()
        notify.make_call.assert_not_called()
        assert summary["start_suppressed_concurrent"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# 2. Nawal Reshid pattern — Overdue branch also suppressed while driver is busy
# ─────────────────────────────────────────────────────────────────────────────

class TestBusyDriversOverdueSuppressed:
    """Driver running trip A (started); trip B pickup is past pickup + overdue-grace.
    The OVERDUE alert branch must NOT fire while the driver is mid-drop.
    """

    def test_overdue_alert_suppressed_when_driver_is_busy(self):
        """
        Setup:
          Trip A — FA status=IN_PROGRESS, pickup=07:55 (started, driver is busy)
          Trip B — FA status=ACCEPTED, pickup=07:40
          now=08:00  → Trip B is 20 min past pickup (> _OVERDUE_GRACE=15)

        Expected:
          - alert_admin NOT called for OVERDUE
          - summary["start_suppressed_concurrent"] unchanged (overdue path
            uses `continue` before Stage 2, not the suppression counter)
        """
        person = _make_person(full_name="Nawal Reshid")

        trip_a = _make_fa_trip(
            trip_id="T-A-NR",
            status="IN_PROGRESS",   # FA started status
            driver_id=101,
            pickup="07:55",
            first_name="Nawal",
            last_name="Reshid",
        )
        # Trip B is accepted but overdue.
        trip_b = _make_fa_trip(
            trip_id="T-B-NR",
            status="ACCEPTED",
            driver_id=101,
            pickup="07:40",
            first_name="Nawal",
            last_name="Reshid",
        )
        notif_b = _make_accepted_notif(
            person_id=1,
            trip_ref="T-B-NR",
            pickup_time="07:40",
        )

        summary, notify, _ = _execute_cycle(
            now=_dt(8, 0),
            fa_trips=[trip_a, trip_b],
            persons=[person],
            pre_existing_notifs=[notif_b],
        )

        # No overdue alert must have fired.
        for call_args in notify.alert_admin.call_args_list:
            msg = str(call_args)
            assert "OVERDUE" not in msg, (
                f"alert_admin was called with OVERDUE while driver is busy: {msg}"
            )

    def test_overdue_alert_suppressed_with_everdriven_trip(self):
        """Same guard applies to EverDriven trips (ED path feeds the same busy_drivers set)."""
        person = _make_person(fa_id=None, ed_id=201)

        # Trip A is ED started (ToStop = "started" bucket for ED).
        run_a = _make_ed_run(
            key="R-A-ED",
            status="ToStop",
            driver_id=201,
            driver_guid="guid-201",
            pickup="07:55",
            driver_name="Nawal Reshid",
        )
        # Trip B is ED accepted but overdue (Scheduled + GUID = accepted).
        run_b = _make_ed_run(
            key="R-B-ED",
            status="Scheduled",
            driver_id=201,
            driver_guid="guid-201",
            pickup="07:38",
            driver_name="Nawal Reshid",
        )
        notif_b = _make_accepted_notif(
            person_id=1,
            trip_ref="R-B-ED",
            pickup_time="07:38",
            source="everdriven",
        )

        summary, notify, _ = _execute_cycle(
            now=_dt(8, 0),
            ed_runs=[run_a, run_b],
            persons=[person],
            pre_existing_notifs=[notif_b],
        )

        for call_args in notify.alert_admin.call_args_list:
            msg = str(call_args)
            assert "OVERDUE" not in msg, (
                f"alert_admin fired OVERDUE for busy ED driver: {msg}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Lone driver (negative test) — overdue MUST fire with no concurrent trip
# ─────────────────────────────────────────────────────────────────────────────

class TestOverdueFiredWithNoConcurrentTrip:
    """Guard must not suppress legitimate overdue alerts for drivers running
    a single trip with no concurrent in-progress run.
    """

    def test_overdue_fires_when_no_concurrent_trip(self):
        """
        Setup:
          Single FA trip, status=ACCEPTED, pickup=07:40
          now=08:00  → 20 min overdue, no other trips for this driver

        Expected:
          - alert_admin called with OVERDUE message
          - overdue_alerted_at set in DB
        """
        person = _make_person(full_name="Lone Driver")

        fa_trip = _make_fa_trip(
            trip_id="T-LONE-001",
            status="ACCEPTED",
            driver_id=101,
            pickup="07:40",
            first_name="Lone",
            last_name="Driver",
        )
        notif = _make_accepted_notif(
            person_id=1,
            trip_ref="T-LONE-001",
            pickup_time="07:40",
        )

        summary, notify, db = _execute_cycle(
            now=_dt(8, 0),
            fa_trips=[fa_trip],
            persons=[person],
            pre_existing_notifs=[notif],
        )

        notify.alert_admin.assert_called_once()
        msg = notify.alert_admin.call_args[0][0]
        assert "OVERDUE" in msg

        db_notif = db.query(_TripNotification).filter_by(trip_ref="T-LONE-001").first()
        assert db_notif is not None
        assert db_notif.overdue_alerted_at is not None

    def test_suppressed_counter_is_zero_for_lone_driver(self):
        """Single-trip driver — busy_drivers set is empty; suppression counter stays 0."""
        person = _make_person(full_name="Lone Driver")

        fa_trip = _make_fa_trip(
            trip_id="T-LONE-002",
            status="ACCEPTED",
            driver_id=101,
            pickup="07:40",
            first_name="Lone",
            last_name="Driver",
        )
        notif = _make_accepted_notif(
            person_id=1,
            trip_ref="T-LONE-002",
            pickup_time="07:40",
        )

        summary, _, _ = _execute_cycle(
            now=_dt(8, 0),
            fa_trips=[fa_trip],
            persons=[person],
            pre_existing_notifs=[notif],
        )

        assert summary["start_suppressed_concurrent"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 4. Three-trip back-to-back chain — all queued trips suppressed in one cycle
# ─────────────────────────────────────────────────────────────────────────────

class TestThreeTripChain:
    """Driver has 08:00 (started), 08:15 (accepted), 08:30 (accepted).
    A single cycle must suppress BOTH 08:15 and 08:30.
    """

    def test_both_queued_trips_suppressed_in_single_cycle(self):
        person = _make_person()

        # Trip at 08:00 is started (en route, mid-drop). ARRIVED is a valid FA started status.
        trip_0800 = _make_fa_trip(
            trip_id="T-0800",
            status="ARRIVED",   # FA started status → classify_fa → "started"
            driver_id=101,
            pickup="08:00",
            first_name="Faize",
            last_name="Kaifa",
        )
        # Trip at 08:15 is accepted, within start window.
        trip_0815 = _make_fa_trip(
            trip_id="T-0815",
            status="ACCEPTED",
            driver_id=101,
            pickup="08:15",
            first_name="Faize",
            last_name="Kaifa",
        )
        # Trip at 08:30 is also accepted, within window.
        trip_0830 = _make_fa_trip(
            trip_id="T-0830",
            status="ACCEPTED",
            driver_id=101,
            pickup="08:30",
            first_name="Faize",
            last_name="Kaifa",
        )

        notif_0815 = _make_accepted_notif(
            person_id=1, trip_ref="T-0815", pickup_time="08:15",
        )
        notif_0830 = _make_accepted_notif(
            person_id=1, trip_ref="T-0830", pickup_time="08:30",
        )

        summary, notify, _ = _execute_cycle(
            now=_dt(8, 8),   # 08:08 — trip 0800 started; 0815 is 7 min away, 0830 is 22 min away
            fa_trips=[trip_0800, trip_0815, trip_0830],
            persons=[person],
            pre_existing_notifs=[notif_0815, notif_0830],
        )

        notify.send_sms.assert_not_called()
        notify.make_call.assert_not_called()
        assert summary["start_suppressed_concurrent"] == 2

    def test_summary_key_present_even_with_no_suppression(self):
        """start_suppressed_concurrent must always be present in the summary dict."""
        person = _make_person()
        fa_trip = _make_fa_trip(
            trip_id="T-NOSUP",
            status="COMPLETED",
            driver_id=101,
            first_name="Faize",
            last_name="Kaifa",
        )

        summary, _, _ = _execute_cycle(
            now=_dt(8, 0),
            fa_trips=[fa_trip],
            persons=[person],
        )

        assert "start_suppressed_concurrent" in summary
        assert summary["start_suppressed_concurrent"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 5. Driver finishes trip A between cycles — trip B becomes eligible
# ─────────────────────────────────────────────────────────────────────────────

class TestBusyDriversAcrossCycles:
    """Cycle 1: driver on trip A (ToStop) → trip B suppressed.
    Cycle 2: trip A is now Completed → busy_drivers is empty → trip B fires.
    """

    def test_trip_b_eligible_after_trip_a_completes(self):
        """Two separate run_monitoring_cycle() invocations sharing the same DB."""
        SessionFactory = _make_session_factory()
        db = SessionFactory()

        person = _make_person()
        db.add(person)

        notif_b = _make_accepted_notif(
            person_id=1, trip_ref="T-B-CYCLE", pickup_time="08:05",
        )
        db.add(notif_b)
        db.commit()

        notify_mock = _make_notify_mock()

        fa_service_mock = MagicMock()
        ed_service_mock = MagicMock()
        ed_service_mock.get_runs.return_value = []

        fake_db_module = types.ModuleType("backend.db")
        fake_db_module.SessionLocal = SessionFactory

        fake_models_module = types.ModuleType("backend.db.models")
        fake_models_module.TripNotification = _TripNotification
        fake_models_module.Person = _Person

        module_patches = {
            "backend.db": fake_db_module,
            "backend.db.models": fake_models_module,
            "backend.services.notification_service": notify_mock,
            "backend.services.firstalt_service": fa_service_mock,
            "backend.services.everdriven_service": ed_service_mock,
        }

        from backend.services import trip_monitor as tm
        from backend.services.trip_monitor import _parse_pickup_time as _real_ppt

        def _naive_ppt(pickup_str, trip_date, tz):
            result = _real_ppt(pickup_str, trip_date, tz)
            if result is not None and result.tzinfo is not None:
                return result.replace(tzinfo=None)
            return result

        # ── Cycle 1: Trip A is IN_PROGRESS (started), Trip B is Accepted ──────────────────
        trip_a_cycle1 = _make_fa_trip(
            trip_id="T-A-CYCLE",
            status="IN_PROGRESS",  # FA started status
            driver_id=101,
            pickup="07:55",
            first_name="Faize",
            last_name="Kaifa",
        )
        trip_b_cycle1 = _make_fa_trip(
            trip_id="T-B-CYCLE",
            status="ACCEPTED",
            driver_id=101,
            pickup="08:05",
            first_name="Faize",
            last_name="Kaifa",
        )

        fa_service_mock.get_trips.return_value = [trip_a_cycle1, trip_b_cycle1]
        now1 = _dt(8, 0).replace(tzinfo=None)

        with (
            patch.dict("sys.modules", module_patches),
            patch("backend.services.trip_monitor.datetime") as mock_dt1,
            patch("backend.services.trip_monitor._parse_pickup_time", side_effect=_naive_ppt),
        ):
            mock_dt1.now.return_value = now1
            mock_dt1.fromisoformat.side_effect = datetime.fromisoformat
            mock_dt1.strptime.side_effect = datetime.strptime
            mock_dt1.side_effect = lambda *a, **kw: datetime(*a, **kw)

            original_dry = tm._DRY_RUN
            tm._DRY_RUN = False
            try:
                summary1 = tm.run_monitoring_cycle()
            finally:
                tm._DRY_RUN = original_dry

        # Cycle 1: Trip B must be suppressed.
        assert summary1["start_suppressed_concurrent"] == 1
        notify_mock.send_sms.assert_not_called()

        # ── Cycle 2: Trip A now Completed, Trip B still Accepted ───────────
        trip_a_cycle2 = _make_fa_trip(
            trip_id="T-A-CYCLE",
            status="COMPLETED",
            driver_id=101,
            pickup="07:55",
            first_name="Faize",
            last_name="Kaifa",
        )
        trip_b_cycle2 = _make_fa_trip(
            trip_id="T-B-CYCLE",
            status="ACCEPTED",
            driver_id=101,
            pickup="08:05",
            first_name="Faize",
            last_name="Kaifa",
        )

        fa_service_mock.get_trips.return_value = [trip_a_cycle2, trip_b_cycle2]
        now2 = _dt(8, 8).replace(tzinfo=None)   # 3 min past pickup=08:05

        with (
            patch.dict("sys.modules", module_patches),
            patch("backend.services.trip_monitor.datetime") as mock_dt2,
            patch("backend.services.trip_monitor._parse_pickup_time", side_effect=_naive_ppt),
        ):
            mock_dt2.now.return_value = now2
            mock_dt2.fromisoformat.side_effect = datetime.fromisoformat
            mock_dt2.strptime.side_effect = datetime.strptime
            mock_dt2.side_effect = lambda *a, **kw: datetime(*a, **kw)

            original_dry = tm._DRY_RUN
            tm._DRY_RUN = False
            try:
                summary2 = tm.run_monitoring_cycle()
            finally:
                tm._DRY_RUN = original_dry

        # Cycle 2: Trip B no longer suppressed — start SMS must fire.
        assert summary2["start_suppressed_concurrent"] == 0
        notify_mock.send_sms.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# 6. Start-reminder timing boundary — SMS fires at pickup, not before
# ─────────────────────────────────────────────────────────────────────────────

class TestStartReminderTimingBoundary:
    """Validate that the start-reminder window gate uses _START_REMINDER_MINUTES
    correctly and that busy_drivers suppression does NOT accidentally mask
    legitimate single-driver alerts outside the window.
    """

    def test_no_sms_before_start_reminder_window(self):
        """
        _START_REMINDER_MINUTES=15.
        now=08:45, pickup=09:00 → 15 min exactly.  With the default the SMS
        should fire at exactly 15 min or fewer.  Set now so we are 20 min out
        (before the window) and verify nothing fires.
        """
        from backend.services import trip_monitor as tm
        original_reminder = tm._START_REMINDER_MINUTES
        tm._START_REMINDER_MINUTES = 0   # window=0 → only at or past pickup

        try:
            person = _make_person(full_name="Timing Driver")

            fa_trip = _make_fa_trip(
                trip_id="T-TIMING-001",
                status="ACCEPTED",
                driver_id=101,
                pickup="09:00",
                first_name="Timing",
                last_name="Driver",
            )
            notif = _make_accepted_notif(
                person_id=1, trip_ref="T-TIMING-001", pickup_time="09:00",
            )

            # 5 min before pickup — if window=0, no SMS
            summary, notify, _ = _execute_cycle(
                now=_dt(8, 55),
                fa_trips=[fa_trip],
                persons=[person],
                pre_existing_notifs=[notif],
            )

            notify.send_sms.assert_not_called()
            assert summary["start_sms"] == 0
        finally:
            tm._START_REMINDER_MINUTES = original_reminder

    def test_sms_fires_at_or_past_pickup_when_window_is_zero(self):
        """With _START_REMINDER_MINUTES=0, SMS fires when now >= pickup."""
        from backend.services import trip_monitor as tm
        original_reminder = tm._START_REMINDER_MINUTES
        tm._START_REMINDER_MINUTES = 0

        try:
            person = _make_person(full_name="Timing Driver")

            fa_trip = _make_fa_trip(
                trip_id="T-TIMING-002",
                status="ACCEPTED",
                driver_id=101,
                pickup="09:00",
                first_name="Timing",
                last_name="Driver",
            )
            notif = _make_accepted_notif(
                person_id=1, trip_ref="T-TIMING-002", pickup_time="09:00",
            )

            # Exactly at pickup time → window=0 → mins_until_pickup=0 → 0 <= 0 → fires
            summary, notify, _ = _execute_cycle(
                now=_dt(9, 0),
                fa_trips=[fa_trip],
                persons=[person],
                pre_existing_notifs=[notif],
            )

            assert summary["start_sms"] == 1
            notify.send_sms.assert_called_once()
        finally:
            tm._START_REMINDER_MINUTES = original_reminder


# ─────────────────────────────────────────────────────────────────────────────
# 7. busy_drivers set only built from trips with a linked person
# ─────────────────────────────────────────────────────────────────────────────

class TestBusyDriversRequiresLinkedPerson:
    """A trip that has `person=None` (no matching DB row) and is_started=True
    must NOT enter the busy_drivers set.  If it did, the set comprehension
    would raise AttributeError on `.person_id`.

    Verify the guard works by confirming a legitimate overdue alert fires for
    another driver even though an unlinked started trip is also present.
    """

    def test_unlinked_started_trip_does_not_pollute_busy_set(self):
        """
        Setup:
          Trip X — FA ToStop, driver_id=999 (unlinked — no Person row)
          Trip Y — FA ACCEPTED, driver_id=101 (linked), pickup=07:40, 20 min overdue

        Expected:
          - No crash (the unlinked ToStop trip does NOT enter busy_drivers)
          - Overdue alert fires for driver 101 because they are NOT in busy_drivers
        """
        linked_person = _make_person(full_name="Nawal Reshid")

        # Unlinked started trip — driverId=999 has no Person in DB.
        unlinked_started = _make_fa_trip(
            trip_id="T-UNLINKED",
            status="IN_PROGRESS",  # FA started status
            driver_id=999,
            pickup="07:50",
            first_name="Ghost",
            last_name="Driver",
        )
        # Linked accepted overdue trip.
        linked_accepted = _make_fa_trip(
            trip_id="T-LINKED-OD",
            status="ACCEPTED",
            driver_id=101,
            pickup="07:40",
            first_name="Nawal",
            last_name="Reshid",
        )
        notif_linked = _make_accepted_notif(
            person_id=1, trip_ref="T-LINKED-OD", pickup_time="07:40",
        )

        summary, notify, db = _execute_cycle(
            now=_dt(8, 0),
            fa_trips=[unlinked_started, linked_accepted],
            persons=[linked_person],   # only person_id=1 is in DB; 999 is absent
            pre_existing_notifs=[notif_linked],
        )

        # Overdue alert must fire for the linked driver (they are NOT busy).
        overdue_calls = [
            c for c in notify.alert_admin.call_args_list
            if "OVERDUE" in str(c)
        ]
        assert len(overdue_calls) == 1, (
            "Expected exactly one OVERDUE alert for the linked driver; "
            f"got {len(overdue_calls)}"
        )

    def test_person_none_trip_does_not_crash_cycle(self):
        """An unlinked started trip must not cause the cycle to crash or raise."""
        unlinked = _make_fa_trip(
            trip_id="T-NOCRASH",
            status="IN_PROGRESS",  # FA started status
            driver_id=888,
            pickup="08:00",
        )

        # No persons, no pre-existing notifs — cycle should complete cleanly.
        summary, notify, _ = _execute_cycle(
            now=_dt(8, 5),
            fa_trips=[unlinked],
            persons=[],
        )

        # No exceptions (would have raised before we got here).
        assert "errors" in summary
        # No notifications — the unlinked trip is skipped, not crashed.
        notify.send_sms.assert_not_called()
        notify.alert_admin.assert_not_called()
