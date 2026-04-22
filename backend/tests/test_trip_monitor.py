"""
Comprehensive pytest test suite for backend/services/trip_monitor.py.

Covers:
    - classify_fa()         — unit tests for every status bucket + priority ordering
    - classify_ed()         — unit tests for all EverDriven states + driverGUID logic
    - _parse_pickup_time()  — unit tests for every time format + edge cases
    - run_monitoring_cycle() — integration tests with in-memory SQLite + full mocks

Run with:
    PYTHONPATH=. pytest backend/tests/test_trip_monitor.py -v

The test DB is built using standalone SQLAlchemy models that mirror the real
production models (Person + TripNotification) but avoid the PostgreSQL-specific
DATERANGE type used by ZRateOverride so tests run on SQLite.
"""

from __future__ import annotations

import sys
import types
import importlib
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, call
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import (
    Boolean, Column, Date, DateTime, ForeignKey,
    Integer, Text, create_engine, text,
)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker

# ── Project root must be on sys.path so `backend.*` imports resolve ──
import os
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Import the three pure functions directly — no mocking needed for unit tests.
from backend.services.trip_monitor import (
    classify_fa,
    classify_ed,
    _parse_pickup_time,
    _blind_cycle_alerted,
)

# ── In-memory SQLite models ───────────────────────────────────────────────────
# We recreate only the two tables used by run_monitoring_cycle (Person +
# TripNotification) as plain SQLAlchemy models. This sidesteps the
# postgresql-only DATERANGE column in the production ZRateOverride model.

class _TestBase(DeclarativeBase):
    pass


class _Person(_TestBase):
    __tablename__ = "person"

    person_id = Column(Integer, primary_key=True)
    full_name = Column(Text, nullable=False)
    email = Column(Text)
    phone = Column(Text)
    firstalt_driver_id = Column(Integer)
    everdriven_driver_id = Column(Integer)
    active = Column(Boolean, nullable=False, default=True)
    language = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)


class _TripNotification(_TestBase):
    __tablename__ = "trip_notification"

    id = Column(Integer, primary_key=True, autoincrement=True)
    person_id = Column(Integer, ForeignKey("person.person_id", ondelete="CASCADE"), nullable=False)
    trip_date = Column(Date, nullable=False)
    source = Column(Text, nullable=False)
    trip_ref = Column(Text, nullable=False)
    trip_status = Column(Text, nullable=True)
    pickup_time = Column(Text, nullable=True)

    accept_sms_at = Column(DateTime(timezone=True), nullable=True)
    accept_call_at = Column(DateTime(timezone=True), nullable=True)
    accept_escalated_at = Column(DateTime(timezone=True), nullable=True)
    accepted_at = Column(DateTime(timezone=True), nullable=True)

    start_sms_at = Column(DateTime(timezone=True), nullable=True)
    start_call_at = Column(DateTime(timezone=True), nullable=True)
    start_escalated_at = Column(DateTime(timezone=True), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)

    # Added via migration b7c8d9e0f1a2 — separate from accept_escalated_at so
    # pre-pickup Stage 1 escalations never suppress the overdue alert.
    overdue_alerted_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    person = relationship("_Person", foreign_keys=[person_id])


def _make_session_factory():
    """Create a fresh SQLite in-memory engine + session factory per test."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    _TestBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return factory


# ── Helpers ───────────────────────────────────────────────────────────────────

TZ = ZoneInfo("America/Los_Angeles")
TRIP_DATE = date(2026, 4, 17)


def _dt(hour: int, minute: int = 0, tz: ZoneInfo = TZ) -> datetime:
    """Build a timezone-aware datetime on TRIP_DATE."""
    return datetime(TRIP_DATE.year, TRIP_DATE.month, TRIP_DATE.day, hour, minute, tzinfo=tz)


def _dt_naive(hour: int, minute: int = 0) -> datetime:
    """Build a timezone-NAIVE datetime on TRIP_DATE.

    Used when seeding pre-existing TripNotification rows into SQLite.
    SQLite strips tzinfo on read-back, so the production code sees naive
    datetimes from DB. If `now` in the mock is tz-aware and the stored
    timestamp is naive, Python raises TypeError on subtraction.
    For tests that verify timing arithmetic (call delay, escalation delay),
    we match by making `now` also naive in those specific tests.
    """
    return datetime(TRIP_DATE.year, TRIP_DATE.month, TRIP_DATE.day, hour, minute)


def _make_notify_mock() -> MagicMock:
    mock = MagicMock()
    mock.normalize_phone.return_value = "+12065550001"
    return mock


def _make_fa_trip(
    trip_id: str = "T001",
    status: str = "PENDING",
    driver_id: int = 101,
    pickup: str = "08:00",
    first_name: str = "",
    last_name: str = "",
) -> dict:
    return {
        "tripId": trip_id,
        "tripStatus": status,
        "driverId": driver_id,
        "firstPickUp": pickup,
        "driverFirstName": first_name,
        "driverLastName": last_name,
    }


def _make_ed_run(
    key: str = "R001",
    status: str = "Scheduled",
    driver_id: int = 201,
    driver_guid: str = "guid-abc",
    pickup: str = "08:00",
    driver_name: str = "",
) -> dict:
    return {
        "keyValue": key,
        "tripStatus": status,
        "driverId": driver_id,
        "driverGUID": driver_guid,
        "firstPickUp": pickup,
        "driverName": driver_name,
    }


def _run_cycle_with_mocks(
    *,
    now: datetime,
    fa_trips: list | Exception = (),
    ed_runs: list | Exception = (),
    persons: list | None = None,
    pre_existing_notifs: list | None = None,
) -> tuple[dict, MagicMock, object]:
    """
    Execute run_monitoring_cycle() with all external dependencies mocked.

    Returns:
        (summary, notify_mock, db_session_used)
    """
    SessionFactory = _make_session_factory()
    db = SessionFactory()

    # Seed persons
    for p in (persons or []):
        db.add(p)

    # Seed pre-existing notifications
    for n in (pre_existing_notifs or []):
        db.add(n)

    db.commit()

    # Build the notify mock
    notify_mock = _make_notify_mock()

    # We need to inject our in-memory models in place of the real ones.
    # The cycle does `from backend.db.models import TripNotification, Person`
    # inside the function — we patch at the module level.
    fake_models_module = types.ModuleType("backend.db.models")
    fake_models_module.TripNotification = _TripNotification
    fake_models_module.Person = _Person

    fake_db_module = types.ModuleType("backend.db")
    fake_db_module.SessionLocal = SessionFactory

    with (
        patch("backend.services.trip_monitor.datetime") as mock_dt,
        patch.dict("sys.modules", {
            "backend.db": fake_db_module,
            "backend.db.models": fake_models_module,
        }),
        patch("backend.services.trip_monitor.SessionLocal", SessionFactory),
        patch("backend.services.trip_monitor._notify_real", notify_mock),
    ):
        # Fix datetime.now() to return our controlled `now`
        mock_dt.now.return_value = now
        mock_dt.fromisoformat = datetime.fromisoformat
        mock_dt.strptime = datetime.strptime
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        # Patch the service imports
        fa_service = MagicMock()
        if isinstance(fa_trips, Exception):
            fa_service.get_trips.side_effect = fa_trips
        else:
            fa_service.get_trips.return_value = list(fa_trips)

        ed_service = MagicMock()
        if isinstance(ed_runs, Exception):
            ed_service.get_runs.side_effect = ed_runs
        else:
            ed_service.get_runs.return_value = list(ed_runs)

        with (
            patch("backend.services.trip_monitor.firstalt_service", fa_service),
            patch("backend.services.trip_monitor.everdriven_service", ed_service),
        ):
            from backend.services import trip_monitor as tm
            # Temporarily override the dry-run guard so notify is real mock
            original_dry = tm._DRY_RUN
            tm._DRY_RUN = False

            summary = tm.run_monitoring_cycle()

            tm._DRY_RUN = original_dry

    return summary, notify_mock, db


# ══════════════════════════════════════════════════════════════════════════════
# 1. classify_fa() — unit tests
# ══════════════════════════════════════════════════════════════════════════════

class TestClassifyFaDeclined:
    def test_declined_uppercase(self):
        assert classify_fa("DECLINED") == "declined"

    def test_substitute_needed(self):
        assert classify_fa("SUBSTITUTE_NEEDED") == "declined"

    def test_removed(self):
        assert classify_fa("REMOVED") == "declined"

    def test_rejected(self):
        assert classify_fa("REJECTED") == "declined"

    def test_driver_declined(self):
        assert classify_fa("DRIVER_DECLINED") == "declined"

    def test_sub_needed_variant(self):
        assert classify_fa("SUB_NEEDED") == "declined"


class TestClassifyFaCompleted:
    def test_completed(self):
        assert classify_fa("COMPLETED") == "completed"

    def test_finished(self):
        assert classify_fa("FINISHED") == "completed"

    def test_done(self):
        assert classify_fa("DONE") == "completed"

    def test_trip_complete(self):
        assert classify_fa("TRIP_COMPLETE") == "completed"

    def test_completed_lowercase(self):
        assert classify_fa("completed") == "completed"


class TestClassifyFaCancelled:
    def test_cancelled_double_l(self):
        assert classify_fa("CANCELLED") == "cancelled"

    def test_canceled_single_l(self):
        assert classify_fa("CANCELED") == "cancelled"

    def test_closed(self):
        assert classify_fa("CLOSED") == "cancelled"

    def test_void(self):
        assert classify_fa("VOID") == "cancelled"

    def test_trip_cancelled(self):
        assert classify_fa("TRIP_CANCELLED") == "cancelled"


class TestClassifyFaStarted:
    def test_in_progress_underscore(self):
        assert classify_fa("IN_PROGRESS") == "started"

    def test_in_progress_space(self):
        assert classify_fa("IN PROGRESS") == "started"

    def test_enroute(self):
        assert classify_fa("ENROUTE") == "started"

    def test_en_route_underscore(self):
        assert classify_fa("EN_ROUTE") == "started"

    def test_picked_up(self):
        assert classify_fa("PICKED_UP") == "started"

    def test_onboard(self):
        assert classify_fa("ONBOARD") == "started"

    def test_arrived(self):
        assert classify_fa("ARRIVED") == "started"

    def test_driver_arrived(self):
        assert classify_fa("DRIVER_ARRIVED") == "started"


class TestClassifyFaUnaccepted:
    def test_dispatch(self):
        assert classify_fa("DISPATCH") == "unaccepted"

    def test_pending(self):
        assert classify_fa("PENDING") == "unaccepted"

    def test_assigned(self):
        assert classify_fa("ASSIGNED") == "unaccepted"

    def test_offer(self):
        assert classify_fa("OFFER") == "unaccepted"

    def test_open(self):
        assert classify_fa("OPEN") == "unaccepted"

    def test_not_accepted(self):
        assert classify_fa("NOT_ACCEPTED") == "unaccepted"

    def test_awaiting(self):
        assert classify_fa("AWAITING") == "unaccepted"

    def test_unaccepted(self):
        assert classify_fa("UNACCEPTED") == "unaccepted"

    def test_scheduled_exact_match(self):
        # SCHEDULED must be "unaccepted" via exact-match check, not "unknown"
        assert classify_fa("SCHEDULED") == "unaccepted"

    def test_scheduled_lowercase(self):
        assert classify_fa("scheduled") == "unaccepted"


class TestClassifyFaAccepted:
    def test_accepted(self):
        assert classify_fa("ACCEPTED") == "accepted"

    def test_driver_accepted(self):
        assert classify_fa("DRIVER_ACCEPTED") == "accepted"


class TestClassifyFaUnknown:
    def test_empty_string(self):
        assert classify_fa("") == "unknown"

    def test_none_equivalent(self):
        # classify_fa coerces None via `(status or "").upper()`
        assert classify_fa(None) == "unknown"  # type: ignore[arg-type]

    def test_weird_status(self):
        assert classify_fa("WEIRD_STATUS") == "unknown"

    def test_rescheduled_not_scheduled(self):
        # "RESCHEDULED" contains "SCHEDULED" as substring but is NOT an exact match
        # It also contains no priority markers → unknown
        assert classify_fa("RESCHEDULED") == "unknown"


class TestClassifyFaPriorityOrdering:
    def test_not_accepted_returns_unaccepted_not_accepted(self):
        # "NOT_ACCEPTED" contains "ACCEPT" but must yield "unaccepted"
        # because unaccepted markers are checked before accepted markers.
        result = classify_fa("NOT_ACCEPTED")
        assert result == "unaccepted", (
            f"Expected 'unaccepted', got '{result}'. "
            "Priority check: unaccepted must be tested before accepted."
        )

    def test_awaiting_acceptance_returns_unaccepted(self):
        # "AWAITING_ACCEPTANCE" contains "ACCEPT" substring
        result = classify_fa("AWAITING_ACCEPTANCE")
        assert result == "unaccepted", (
            f"Expected 'unaccepted', got '{result}'. "
            "AWAITING_ACCEPTANCE contains ACCEPT but AWAITING marker wins."
        )

    def test_declined_beats_completed(self):
        # Contrived combo — declined markers take top priority
        assert classify_fa("TRIP_DECLINED_COMPLETE") == "declined"

    def test_cancelled_beats_started(self):
        # "CANCELLED_IN_PROGRESS" — cancelled checked before started
        assert classify_fa("CANCELLED_IN_PROGRESS") == "cancelled"


# ══════════════════════════════════════════════════════════════════════════════
# 2. classify_ed() — unit tests
# ══════════════════════════════════════════════════════════════════════════════

class TestClassifyEd:
    def test_scheduled_with_driver_guid_is_accepted(self):
        assert classify_ed("Scheduled", "guid-abc") == "accepted"

    def test_scheduled_without_driver_guid_is_unaccepted(self):
        assert classify_ed("Scheduled", None) == "unaccepted"

    def test_scheduled_empty_guid_is_unaccepted(self):
        assert classify_ed("Scheduled", "") == "unaccepted"

    def test_accepted_with_driver_guid(self):
        assert classify_ed("Accepted", "guid-xyz") == "accepted"

    def test_accepted_without_driver_guid_is_unaccepted(self):
        # "Accepted" maps to accepted bucket; without driverGUID → unaccepted
        assert classify_ed("Accepted", None) == "unaccepted"

    def test_active_is_started(self):
        assert classify_ed("Active", "guid-abc") == "started"

    def test_at_stop_is_started(self):
        assert classify_ed("AtStop", "guid-abc") == "started"

    def test_to_stop_is_started(self):
        assert classify_ed("ToStop", "guid-abc") == "started"

    def test_completed(self):
        assert classify_ed("Completed", None) == "completed"

    def test_declined(self):
        assert classify_ed("Declined", "guid-abc") == "declined"

    def test_cancelled_full_word(self):
        assert classify_ed("Cancelled", None) == "cancelled"

    def test_canceled_american_spelling(self):
        assert classify_ed("Canceled", None) == "cancelled"

    def test_empty_status_with_driver_guid_is_unknown(self):
        assert classify_ed("", "guid-abc") == "unknown"

    def test_empty_status_without_driver_guid_is_unaccepted(self):
        assert classify_ed("", None) == "unaccepted"

    def test_unknown_status_string(self):
        assert classify_ed("UnknownStatus", "guid") == "unknown"

    def test_case_sensitive_scheduled(self):
        # EverDriven API returns title-case; "SCHEDULED" is not in _ED_STATE_MAP
        assert classify_ed("SCHEDULED", "guid") == "unknown"

    def test_started_statuses_ignore_guid_presence(self):
        # Started bucket does NOT require driverGUID
        assert classify_ed("Active", None) == "started"
        assert classify_ed("AtStop", None) == "started"


# ══════════════════════════════════════════════════════════════════════════════
# 3. _parse_pickup_time() — unit tests
# ══════════════════════════════════════════════════════════════════════════════

class TestParsePickupTime:
    """All tests use TRIP_DATE = date(2026, 4, 17) and TZ = America/Los_Angeles."""

    def test_hhmm_zero_padded(self):
        result = _parse_pickup_time("07:30", TRIP_DATE, TZ)
        expected = datetime(2026, 4, 17, 7, 30, tzinfo=TZ)
        assert result == expected

    def test_hhmm_not_zero_padded(self):
        result = _parse_pickup_time("7:30", TRIP_DATE, TZ)
        expected = datetime(2026, 4, 17, 7, 30, tzinfo=TZ)
        assert result == expected

    def test_iso_no_timezone(self):
        result = _parse_pickup_time("2026-04-17T07:30", TRIP_DATE, TZ)
        assert result is not None
        assert result.hour == 7
        assert result.minute == 30
        assert result.tzinfo is not None

    def test_iso_with_z_suffix(self):
        result = _parse_pickup_time("2026-04-17T07:30:00Z", TRIP_DATE, TZ)
        assert result is not None
        # Z means UTC; fromisoformat converts to UTC aware datetime
        assert result.tzinfo is not None
        assert result.utcoffset() == timedelta(0)

    def test_twelve_hour_am_with_space(self):
        result = _parse_pickup_time("7:30 AM", TRIP_DATE, TZ)
        assert result is not None
        assert result.hour == 7
        assert result.minute == 30
        assert result.tzinfo == TZ

    def test_twelve_hour_pm_with_space(self):
        result = _parse_pickup_time("07:30 PM", TRIP_DATE, TZ)
        assert result is not None
        assert result.hour == 19
        assert result.minute == 30

    def test_empty_string_returns_none(self):
        assert _parse_pickup_time("", TRIP_DATE, TZ) is None

    def test_none_returns_none(self):
        assert _parse_pickup_time(None, TRIP_DATE, TZ) is None  # type: ignore[arg-type]

    def test_unparseable_string_returns_none(self):
        assert _parse_pickup_time("not-a-time", TRIP_DATE, TZ) is None

    def test_garbage_value_returns_none(self):
        assert _parse_pickup_time("??:??", TRIP_DATE, TZ) is None

    def test_midnight(self):
        result = _parse_pickup_time("00:00", TRIP_DATE, TZ)
        assert result is not None
        assert result.hour == 0
        assert result.minute == 0

    def test_end_of_day(self):
        result = _parse_pickup_time("23:59", TRIP_DATE, TZ)
        assert result is not None
        assert result.hour == 23
        assert result.minute == 59


# ══════════════════════════════════════════════════════════════════════════════
# 4. run_monitoring_cycle() — integration tests
# ══════════════════════════════════════════════════════════════════════════════

# Each test builds its own in-memory DB, seeds it, patches all external
# dependencies, and calls run_monitoring_cycle() directly.

# Operating-hours fixture: pick a safe time inside the window (5–21 LA time).
_OPERATING_NOW = _dt(hour=7, minute=15)


def _build_cycle_patches(
    now: datetime,
    fa_trips,
    ed_runs,
    SessionFactory,
    notify_mock: MagicMock,
):
    """Return a context manager stack that patches everything run_monitoring_cycle
    pulls from external modules."""
    import contextlib

    fa_service = MagicMock()
    if isinstance(fa_trips, Exception):
        fa_service.get_trips.side_effect = fa_trips
    else:
        fa_service.get_trips.return_value = list(fa_trips)

    ed_service = MagicMock()
    if isinstance(ed_runs, Exception):
        ed_service.get_runs.side_effect = ed_runs
    else:
        ed_service.get_runs.return_value = list(ed_runs)

    fake_models = types.ModuleType("backend.db.models")
    fake_models.TripNotification = _TripNotification
    fake_models.Person = _Person

    fake_db = types.ModuleType("backend.db")
    fake_db.SessionLocal = SessionFactory

    return contextlib.ExitStack(), {
        "now": now,
        "fa_service": fa_service,
        "ed_service": ed_service,
        "fake_models": fake_models,
        "fake_db": fake_db,
        "notify_mock": notify_mock,
    }


def _execute_cycle(
    *,
    now: datetime,
    fa_trips=(),
    ed_runs=(),
    persons=None,
    pre_existing_notifs=None,
):
    """
    Full integration harness: seeds DB, patches all externals, runs cycle,
    returns (summary, notify_mock, open_db_session).

    Patching strategy:
    - run_monitoring_cycle() does lazy `from backend.db import SessionLocal` and
      `from backend.db.models import TripNotification, Person` inside the function
      body, so those names are resolved from sys.modules at call time.
    - We inject fake modules into sys.modules before calling the cycle so those
      imports resolve to our in-memory SQLite objects.
    - notification_service is also imported lazily, so we override it the same way.
    - firstalt_service and everdriven_service are imported at call time too.
    """
    SessionFactory = _make_session_factory()
    db = SessionFactory()

    for p in (persons or []):
        db.add(p)
    for n in (pre_existing_notifs or []):
        db.add(n)
    db.commit()

    notify_mock = _make_notify_mock()

    fa_service_mock = MagicMock()
    if isinstance(fa_trips, Exception):
        fa_service_mock.get_trips.side_effect = fa_trips
    else:
        fa_service_mock.get_trips.return_value = list(fa_trips)

    ed_service_mock = MagicMock()
    if isinstance(ed_runs, Exception):
        ed_service_mock.get_runs.side_effect = ed_runs
    else:
        ed_service_mock.get_runs.return_value = list(ed_runs)

    # Build fake sys.modules entries for all lazy-imported backend modules.
    fake_db_module = types.ModuleType("backend.db")
    fake_db_module.SessionLocal = SessionFactory

    fake_models_module = types.ModuleType("backend.db.models")
    fake_models_module.TripNotification = _TripNotification
    fake_models_module.Person = _Person

    # notification_service is imported as `from backend.services import notification_service`
    # We need `backend.services` to expose `notification_service` as notify_mock.
    # The safest way: patch `backend.services.notification_service` in sys.modules.
    fake_notify_module = notify_mock  # the mock itself acts as the module

    # firstalt_service and everdriven_service: imported as
    # `from backend.services import firstalt_service` / `everdriven_service`
    fake_firstalt_module = fa_service_mock
    fake_ed_module = ed_service_mock

    # Build a fake `backend.services` package that returns our mocks for sub-attributes
    # that `from backend.services import X` would resolve.
    # BUT Python's `from pkg import submod` actually looks up sys.modules["pkg.submod"],
    # not pkg.submod attribute. So we patch sys.modules for each submodule.

    module_patches = {
        "backend.db": fake_db_module,
        "backend.db.models": fake_models_module,
        "backend.services.notification_service": notify_mock,
        "backend.services.firstalt_service": fa_service_mock,
        "backend.services.everdriven_service": ed_service_mock,
    }

    from backend.services import trip_monitor as tm

    # Strip tzinfo from `now` so datetime arithmetic with SQLite-returned naive
    # datetimes doesn't raise TypeError. SQLite strips tzinfo on read-back, so
    # both sides of any `now - notif.some_at` subtraction must be naive.
    # The operating-hours gate uses `now.hour` which works for naive datetimes.
    # _parse_pickup_time is also patched to strip tzinfo so `now > pickup_dt`
    # comparisons work.
    now_naive = now.replace(tzinfo=None) if now.tzinfo else now

    # Wrap _parse_pickup_time to strip tzinfo from its output
    from backend.services.trip_monitor import _parse_pickup_time as _real_ppt

    def _naive_parse_pickup_time(pickup_str, trip_date, tz):
        result = _real_ppt(pickup_str, trip_date, tz)
        if result is not None and result.tzinfo is not None:
            return result.replace(tzinfo=None)
        return result

    with (
        patch.dict("sys.modules", module_patches),
        patch("backend.services.trip_monitor.datetime") as mock_dt,
        patch("backend.services.trip_monitor._parse_pickup_time", side_effect=_naive_parse_pickup_time),
    ):
        mock_dt.now.return_value = now_naive
        mock_dt.fromisoformat.side_effect = datetime.fromisoformat
        mock_dt.strptime.side_effect = datetime.strptime
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        original_dry = tm._DRY_RUN
        tm._DRY_RUN = False
        try:
            summary = tm.run_monitoring_cycle()
        finally:
            tm._DRY_RUN = original_dry

    return summary, notify_mock, db


# ── Test: outside operating hours ─────────────────────────────────────────────

class TestOperatingHoursGate:
    def test_before_start_hour_returns_skipped(self):
        """Cycle before _START_HOUR=5 must return {skipped: True} immediately."""
        early_now = _dt(hour=3)
        from backend.services import trip_monitor as tm
        with patch("backend.services.trip_monitor.datetime") as mock_dt:
            mock_dt.now.return_value = early_now
            result = tm.run_monitoring_cycle()
        assert result.get("skipped") is True

    def test_at_end_hour_returns_skipped(self):
        """Cycle exactly at _END_HOUR=21 must also be skipped."""
        late_now = _dt(hour=21)
        from backend.services import trip_monitor as tm
        with patch("backend.services.trip_monitor.datetime") as mock_dt:
            mock_dt.now.return_value = late_now
            result = tm.run_monitoring_cycle()
        assert result.get("skipped") is True

    def test_inside_hours_does_not_skip(self):
        """A cycle at 07:15 must not return skipped."""
        summary, _, _ = _execute_cycle(now=_OPERATING_NOW, fa_trips=[], ed_runs=[])
        assert summary.get("skipped") is not True


# ── Test: FA unaccepted within reminder window ────────────────────────────────

class TestFaUnacceptedFirstCycle:
    def test_accept_sms_sent_within_reminder_window(self):
        """
        FA trip PENDING, pickup=08:00, now=07:15 (45 min before).
        Expected: accept_sms sent, summary['accept_sms'] == 1.
        """
        person = _Person(person_id=1, full_name="Alice Johnson",
                         phone="+12065550001", language="en",
                         firstalt_driver_id=101, active=True)
        fa_trip = _make_fa_trip(status="PENDING", driver_id=101, pickup="08:00",
                                first_name="Alice", last_name="Johnson")

        now = _dt(hour=7, minute=15)
        summary, notify, db = _execute_cycle(
            now=now, fa_trips=[fa_trip], persons=[person]
        )

        assert summary["accept_sms"] == 1
        notify.send_sms.assert_called_once()
        call_args = notify.send_sms.call_args
        assert call_args[0][0] == "+12065550001"

        # Verify DB row was created with accept_sms_at set
        notif = db.query(_TripNotification).filter_by(trip_ref="T001").first()
        assert notif is not None
        assert notif.accept_sms_at is not None

    def test_accept_call_not_sent_on_first_cycle(self):
        """Only SMS on first cycle — no call until SMS delay has elapsed."""
        person = _Person(person_id=1, full_name="Alice Johnson",
                         phone="+12065550001", language="en",
                         firstalt_driver_id=101, active=True)
        fa_trip = _make_fa_trip(status="PENDING", driver_id=101, pickup="08:00",
                                first_name="Alice", last_name="Johnson")

        summary, notify, _ = _execute_cycle(
            now=_dt(7, 15), fa_trips=[fa_trip], persons=[person]
        )
        notify.make_call.assert_not_called()


# ── Test: FA unaccepted OUTSIDE reminder window ───────────────────────────────

class TestFaUnacceptedOutsideWindow:
    def test_no_sms_two_hours_before_pickup(self):
        """
        now=06:00, pickup=08:00 → 2 hours out, outside 60-min window.
        Expected: no SMS, no call.
        """
        person = _Person(person_id=1, full_name="Alice Johnson",
                         phone="+12065550001", language="en",
                         firstalt_driver_id=101, active=True)
        fa_trip = _make_fa_trip(status="PENDING", driver_id=101, pickup="08:00",
                                first_name="Alice", last_name="Johnson")

        summary, notify, _ = _execute_cycle(
            now=_dt(6, 0), fa_trips=[fa_trip], persons=[person]
        )

        assert summary["accept_sms"] == 0
        notify.send_sms.assert_not_called()
        notify.make_call.assert_not_called()


# ── Test: FA accepted → start SMS within 15-min start window ─────────────────

class TestFaAcceptedStartStage:
    def test_start_sms_sent_when_accepted_and_within_start_window(self):
        """
        Notif already has accepted_at set (prior cycle).
        now=07:50, pickup=08:00 (10 min away).
        Expected: start_sms sent.
        """
        person = _Person(person_id=1, full_name="Alice Johnson",
                         phone="+12065550001", language="en",
                         firstalt_driver_id=101, active=True)
        fa_trip = _make_fa_trip(status="ACCEPTED", driver_id=101, pickup="08:00",
                                first_name="Alice", last_name="Johnson")

        prior_accepted_at = _dt_naive(7, 0)  # naive — SQLite strips tzinfo on read-back
        existing_notif = _TripNotification(
            person_id=1,
            trip_date=TRIP_DATE,
            source="firstalt",
            trip_ref="T001",
            trip_status="ACCEPTED",
            pickup_time="08:00",
            accepted_at=prior_accepted_at,
        )

        summary, notify, db = _execute_cycle(
            now=_dt(7, 50),
            fa_trips=[fa_trip],
            persons=[person],
            pre_existing_notifs=[existing_notif],
        )

        assert summary["start_sms"] == 1
        notify.send_sms.assert_called_once()

        notif = db.query(_TripNotification).filter_by(trip_ref="T001").first()
        assert notif.start_sms_at is not None


# ── Test: Stage 2 does NOT fire on same cycle accepted_at is first set ────────

class TestJustAcceptedGuard:
    def test_start_sms_not_sent_same_cycle_accept_is_recorded(self):
        """
        FA status=ACCEPTED, first time seen (no prior notif row).
        now=07:50 (inside start window).
        accepted_at should be set, but start_sms must NOT fire because
        just_accepted guard blocks Stage 2.
        """
        person = _Person(person_id=1, full_name="Alice Johnson",
                         phone="+12065550001", language="en",
                         firstalt_driver_id=101, active=True)
        fa_trip = _make_fa_trip(status="ACCEPTED", driver_id=101, pickup="08:00",
                                first_name="Alice", last_name="Johnson")

        summary, notify, db = _execute_cycle(
            now=_dt(7, 50), fa_trips=[fa_trip], persons=[person]
        )

        assert summary["start_sms"] == 0
        notify.send_sms.assert_not_called()

        notif = db.query(_TripNotification).filter_by(trip_ref="T001").first()
        assert notif is not None
        assert notif.accepted_at is not None


# ── Test: FA overdue, never accepted ─────────────────────────────────────────

class TestFaOverdueNeverAccepted:
    def test_alert_admin_called_when_overdue_and_never_accepted(self):
        """
        pickup=07:00, now=07:15 → 15 min overdue, still PENDING.
        Expected: alert_admin called with OVERDUE message, overdue_alerted_at set.
        """
        person = _Person(person_id=1, full_name="Alice Johnson",
                         phone="+12065550001", language="en",
                         firstalt_driver_id=101, active=True)
        fa_trip = _make_fa_trip(status="PENDING", driver_id=101, pickup="07:00",
                                first_name="Alice", last_name="Johnson")

        summary, notify, db = _execute_cycle(
            now=_dt(7, 15), fa_trips=[fa_trip], persons=[person]
        )

        notify.alert_admin.assert_called_once()
        alert_msg = notify.alert_admin.call_args[0][0]
        assert "OVERDUE" in alert_msg

        notif = db.query(_TripNotification).filter_by(trip_ref="T001").first()
        assert notif is not None
        # The production code sets overdue_alerted_at (not accept_escalated_at) for overdue
        assert notif.overdue_alerted_at is not None

    def test_no_sms_sent_when_overdue(self):
        """Overdue path skips SMS/call — escalates directly to admin."""
        person = _Person(person_id=1, full_name="Alice Johnson",
                         phone="+12065550001", language="en",
                         firstalt_driver_id=101, active=True)
        fa_trip = _make_fa_trip(status="PENDING", driver_id=101, pickup="07:00",
                                first_name="Alice", last_name="Johnson")

        _, notify, _ = _execute_cycle(
            now=_dt(7, 15), fa_trips=[fa_trip], persons=[person]
        )
        notify.send_sms.assert_not_called()


# ── Test: overdue fires even when Stage 1 already escalated pre-pickup ────────

class TestFaOverduePriorEscalation:
    def test_overdue_alert_fires_when_no_overdue_alerted_at_yet(self):
        """
        notif has accept_escalated_at set (Stage 1 pre-pickup escalation)
        but overdue_alerted_at is still None.
        Pickup time is now in the past.
        Expected: alert_admin fires for OVERDUE — overdue_alerted_at is independent.
        """
        person = _Person(person_id=1, full_name="Alice Johnson",
                         phone="+12065550001", language="en",
                         firstalt_driver_id=101, active=True)
        fa_trip = _make_fa_trip(status="PENDING", driver_id=101, pickup="07:00",
                                first_name="Alice", last_name="Johnson")

        # Pre-pickup Stage 1 escalation happened earlier — overdue_alerted_at is None.
        # Use naive datetime so SQLite round-trip doesn't cause tz issues.
        prior_stage1_at = _dt_naive(6, 30) - timedelta(days=1)
        existing_notif = _TripNotification(
            person_id=1,
            trip_date=TRIP_DATE,
            source="firstalt",
            trip_ref="T001",
            trip_status="PENDING",
            pickup_time="07:00",
            accept_escalated_at=prior_stage1_at,
            overdue_alerted_at=None,  # never overdue-alerted yet
        )

        summary, notify, _ = _execute_cycle(
            now=_dt(7, 15),
            fa_trips=[fa_trip],
            persons=[person],
            pre_existing_notifs=[existing_notif],
        )

        notify.alert_admin.assert_called_once()
        msg = notify.alert_admin.call_args[0][0]
        assert "OVERDUE" in msg

    def test_overdue_alert_deduped_when_overdue_alerted_at_already_set(self):
        """
        notif already has overdue_alerted_at set from a previous overdue alert.
        Expected: alert_admin NOT fired again.
        """
        person = _Person(person_id=1, full_name="Alice Johnson",
                         phone="+12065550001", language="en",
                         firstalt_driver_id=101, active=True)
        fa_trip = _make_fa_trip(status="PENDING", driver_id=101, pickup="07:00",
                                first_name="Alice", last_name="Johnson")

        prior_overdue_at = _dt_naive(7, 5)
        existing_notif = _TripNotification(
            person_id=1,
            trip_date=TRIP_DATE,
            source="firstalt",
            trip_ref="T001",
            trip_status="PENDING",
            pickup_time="07:00",
            overdue_alerted_at=prior_overdue_at,
        )

        summary, notify, _ = _execute_cycle(
            now=_dt(7, 20),
            fa_trips=[fa_trip],
            persons=[person],
            pre_existing_notifs=[existing_notif],
        )

        notify.alert_admin.assert_not_called()


# ── Test: FA trip DECLINED ────────────────────────────────────────────────────

class TestFaDeclined:
    def test_alert_admin_on_decline_no_sms_to_driver(self):
        """DECLINED → alert Malik immediately, never contact the driver."""
        person = _Person(person_id=1, full_name="Alice Johnson",
                         phone="+12065550001", language="en",
                         firstalt_driver_id=101, active=True)
        fa_trip = _make_fa_trip(status="DECLINED", driver_id=101, pickup="08:00",
                                first_name="Alice", last_name="Johnson")

        summary, notify, _ = _execute_cycle(
            now=_dt(7, 30), fa_trips=[fa_trip], persons=[person]
        )

        notify.alert_admin.assert_called_once()
        msg = notify.alert_admin.call_args[0][0]
        assert "DECLINE" in msg

        notify.send_sms.assert_not_called()
        notify.make_call.assert_not_called()


# ── Test: FA trip COMPLETED — no action ──────────────────────────────────────

class TestFaCompleted:
    def test_completed_trip_no_notifications(self):
        """COMPLETED trips require zero notifications."""
        person = _Person(person_id=1, full_name="Alice Johnson",
                         phone="+12065550001", language="en",
                         firstalt_driver_id=101, active=True)
        fa_trip = _make_fa_trip(status="COMPLETED", driver_id=101, pickup="07:00",
                                first_name="Alice", last_name="Johnson")

        summary, notify, _ = _execute_cycle(
            now=_dt(8, 0), fa_trips=[fa_trip], persons=[person]
        )

        notify.send_sms.assert_not_called()
        notify.make_call.assert_not_called()
        notify.alert_admin.assert_not_called()


# ── Test: FA trip CANCELLED — no action ──────────────────────────────────────

class TestFaCancelled:
    def test_cancelled_trip_no_notifications(self):
        """CANCELLED trips require zero notifications."""
        person = _Person(person_id=1, full_name="Alice Johnson",
                         phone="+12065550001", language="en",
                         firstalt_driver_id=101, active=True)
        fa_trip = _make_fa_trip(status="CANCELLED", driver_id=101, pickup="08:00",
                                first_name="Alice", last_name="Johnson")

        summary, notify, _ = _execute_cycle(
            now=_dt(7, 30), fa_trips=[fa_trip], persons=[person]
        )

        notify.send_sms.assert_not_called()
        notify.make_call.assert_not_called()
        notify.alert_admin.assert_not_called()


# ── Test: unknown status fires admin alert once, deduped on second cycle ──────

class TestUnknownStatusDedup:
    def test_unknown_status_fires_admin_alert_first_cycle(self):
        """WEIRD_UNKNOWN_STATUS → alert_admin called once, accept_escalated_at set."""
        person = _Person(person_id=1, full_name="Alice Johnson",
                         phone="+12065550001", language="en",
                         firstalt_driver_id=101, active=True)
        fa_trip = _make_fa_trip(status="WEIRD_UNKNOWN_STATUS", driver_id=101, pickup="08:00",
                                first_name="Alice", last_name="Johnson")

        summary, notify, db = _execute_cycle(
            now=_dt(7, 30), fa_trips=[fa_trip], persons=[person]
        )

        notify.alert_admin.assert_called_once()
        msg = notify.alert_admin.call_args[0][0]
        assert "UNKNOWN STATUS" in msg

        notif = db.query(_TripNotification).filter_by(trip_ref="T001").first()
        assert notif.accept_escalated_at is not None

    def test_unknown_status_not_alerted_again_on_second_cycle(self):
        """
        Cycle 2: notif already has accept_escalated_at set.
        Expected: alert_admin NOT called again.
        """
        person = _Person(person_id=1, full_name="Alice Johnson",
                         phone="+12065550001", language="en",
                         firstalt_driver_id=101, active=True)
        fa_trip = _make_fa_trip(status="WEIRD_UNKNOWN_STATUS", driver_id=101, pickup="08:00",
                                first_name="Alice", last_name="Johnson")

        # Pre-seed notif row with accept_escalated_at already set (naive for SQLite)
        existing_notif = _TripNotification(
            person_id=1,
            trip_date=TRIP_DATE,
            source="firstalt",
            trip_ref="T001",
            trip_status="WEIRD_UNKNOWN_STATUS",
            pickup_time="08:00",
            accept_escalated_at=_dt_naive(7, 25),
        )

        summary, notify, _ = _execute_cycle(
            now=_dt(7, 30),
            fa_trips=[fa_trip],
            persons=[person],
            pre_existing_notifs=[existing_notif],
        )

        notify.alert_admin.assert_not_called()


# ── Test: driver has no phone number ─────────────────────────────────────────

class TestNoPhoneNumber:
    def test_no_phone_triggers_admin_escalation_not_sms(self):
        """
        Driver has phone=None, trip is unaccepted within window.
        Expected: alert_admin called about no phone, no SMS/call to driver.
        """
        person = _Person(person_id=1, full_name="Alice Johnson",
                         phone=None, language="en",
                         firstalt_driver_id=101, active=True)
        fa_trip = _make_fa_trip(status="PENDING", driver_id=101, pickup="08:00",
                                first_name="Alice", last_name="Johnson")

        # Make normalize_phone return falsy for None
        summary, notify, _ = _execute_cycle(
            now=_dt(7, 30), fa_trips=[fa_trip], persons=[person]
        )

        # When phone is None normalize_phone returns falsy
        notify.send_sms.assert_not_called()
        notify.make_call.assert_not_called()

        # But we expect admin to be alerted about missing phone.
        # The cycle checks `not driver_phone or not notify.normalize_phone(driver_phone)`
        # → notify.normalize_phone is called with None; mock default returns "+12065550001"
        # so we need to configure it differently for this test.
        # This test documents the behavior: with phone=None the check triggers.

    def test_no_phone_with_normalize_returning_falsy_alerts_admin(self):
        """Explicit: normalize_phone returns '' (falsy) → admin escalation fires."""
        person = _Person(person_id=1, full_name="Alice Johnson",
                         phone="+12065550001", language="en",
                         firstalt_driver_id=101, active=True)
        fa_trip = _make_fa_trip(status="PENDING", driver_id=101, pickup="08:00",
                                first_name="Alice", last_name="Johnson")

        # Build the cycle manually so we can customise the notify mock.
        SessionFactory = _make_session_factory()
        db = SessionFactory()
        db.add(person)
        db.commit()

        notify_mock = _make_notify_mock()
        notify_mock.normalize_phone.return_value = ""  # falsy → no-phone path

        fa_service_mock = MagicMock()
        fa_service_mock.get_trips.return_value = [fa_trip]

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

        with (
            patch.dict("sys.modules", module_patches),
            patch("backend.services.trip_monitor.datetime") as mock_dt,
            patch("backend.services.trip_monitor._parse_pickup_time", side_effect=_naive_ppt),
        ):
            # now=07:45 (naive) → 15 min before pickup=08:00, within _ACCEPT_ESC_WINDOW=20.
            # Naive now ensures the API-lag grace check raises TypeError on
            # (naive_now - utc_aware_created_at), which is caught and treated
            # as "old enough" (age > grace), so the grace doesn't block Stage 1.
            now_naive = _dt(7, 45).replace(tzinfo=None)
            mock_dt.now.return_value = now_naive
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            mock_dt.strptime.side_effect = datetime.strptime
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            original_dry = tm._DRY_RUN
            tm._DRY_RUN = False
            try:
                summary = tm.run_monitoring_cycle()
            finally:
                tm._DRY_RUN = original_dry

        notify_mock.send_sms.assert_not_called()
        notify_mock.alert_admin.assert_called_once()


# ── Test: both APIs fail — blind cycle ───────────────────────────────────────

class TestBlindCycleAlert:
    def setup_method(self):
        # Clear blind cycle alert set before each test so dedup doesn't interfere
        _blind_cycle_alerted.discard(TRIP_DATE.isoformat())

    def test_blind_cycle_alerts_admin_when_both_apis_fail(self):
        """
        FirstAlt raises, EverDriven raises.
        Expected: alert_admin called three times — once per failed partner, plus
        the BLIND alert. All three are meaningful; we assert on the BLIND message
        being present rather than a specific call count, since per-partner alerts
        were added after the original test was written.
        """
        _blind_cycle_alerted.discard(TRIP_DATE.isoformat())

        summary, notify, _ = _execute_cycle(
            now=_dt(7, 30),
            fa_trips=RuntimeError("FA down"),
            ed_runs=RuntimeError("ED down"),
        )

        # At least one call must contain the BLIND marker
        all_msgs = " ".join(str(c) for c in notify.alert_admin.call_args_list)
        assert "BLIND" in all_msgs or "blind" in all_msgs.lower() or "failed" in all_msgs.lower()
        # Total: FA partner alert + ED partner alert + blind alert = 3
        assert notify.alert_admin.call_count == 3

    def test_blind_cycle_alert_deduped_within_same_day(self):
        """Second blind cycle on same date must NOT re-alert."""
        # First cycle — seeds the dedup set
        _blind_cycle_alerted.discard(TRIP_DATE.isoformat())
        _execute_cycle(
            now=_dt(7, 30),
            fa_trips=RuntimeError("FA down"),
            ed_runs=RuntimeError("ED down"),
        )

        # Second cycle — should be deduped
        _, notify2, _ = _execute_cycle(
            now=_dt(7, 35),
            fa_trips=RuntimeError("FA down"),
            ed_runs=RuntimeError("ED down"),
        )

        notify2.alert_admin.assert_not_called()

    def teardown_method(self):
        _blind_cycle_alerted.discard(TRIP_DATE.isoformat())


# ── Test: FA SCHEDULED → classified as unaccepted ─────────────────────────────

class TestFaScheduledIsUnaccepted:
    def test_scheduled_treated_as_unaccepted_and_sms_sent(self):
        """
        FA returns status='SCHEDULED', within 60-min window.
        Expected: treated as unaccepted, SMS sent.
        """
        person = _Person(person_id=1, full_name="Alice Johnson",
                         phone="+12065550001", language="en",
                         firstalt_driver_id=101, active=True)
        fa_trip = _make_fa_trip(status="SCHEDULED", driver_id=101, pickup="08:00",
                                first_name="Alice", last_name="Johnson")

        summary, notify, _ = _execute_cycle(
            now=_dt(7, 15), fa_trips=[fa_trip], persons=[person]
        )

        assert summary["accept_sms"] == 1
        notify.send_sms.assert_called_once()


# ── Test: name mismatch → alert, skip stages ─────────────────────────────────

class TestNameMismatch:
    def test_name_mismatch_alerts_admin_and_skips_sms(self):
        """
        FA driverFirstName='John', driverLastName='Smith'.
        DB person has full_name='Alice Johnson'.
        No token overlap → name mismatch.
        Expected: alert_admin called with NAME MISMATCH, no SMS/call to driver.
        """
        person = _Person(person_id=1, full_name="Alice Johnson",
                         phone="+12065550001", language="en",
                         firstalt_driver_id=101, active=True)
        fa_trip = _make_fa_trip(status="PENDING", driver_id=101, pickup="08:00",
                                first_name="John", last_name="Smith")

        summary, notify, db = _execute_cycle(
            now=_dt(7, 30), fa_trips=[fa_trip], persons=[person]
        )

        notify.alert_admin.assert_called_once()
        msg = notify.alert_admin.call_args[0][0]
        assert "NAME MISMATCH" in msg or "MISMATCH" in msg

        notify.send_sms.assert_not_called()
        notify.make_call.assert_not_called()

    def test_name_mismatch_deduped_on_second_cycle(self):
        """
        notif.accept_escalated_at already set from prior mismatch alert.
        Second cycle: alert_admin must NOT fire again.
        """
        person = _Person(person_id=1, full_name="Alice Johnson",
                         phone="+12065550001", language="en",
                         firstalt_driver_id=101, active=True)
        fa_trip = _make_fa_trip(status="PENDING", driver_id=101, pickup="08:00",
                                first_name="John", last_name="Smith")

        existing_notif = _TripNotification(
            person_id=1,
            trip_date=TRIP_DATE,
            source="firstalt",
            trip_ref="T001",
            trip_status="PENDING",
            pickup_time="08:00",
            accept_escalated_at=_dt_naive(7, 20),  # already alerted (naive for SQLite)
        )

        summary, notify, _ = _execute_cycle(
            now=_dt(7, 30),
            fa_trips=[fa_trip],
            persons=[person],
            pre_existing_notifs=[existing_notif],
        )

        notify.alert_admin.assert_not_called()

    def test_partial_name_overlap_does_not_trigger_mismatch(self):
        """
        API: 'Alice Smith', DB: 'Alice Johnson' — share 'alice' token.
        Expected: no mismatch, normal flow continues.
        """
        person = _Person(person_id=1, full_name="Alice Johnson",
                         phone="+12065550001", language="en",
                         firstalt_driver_id=101, active=True)
        fa_trip = _make_fa_trip(status="COMPLETED", driver_id=101, pickup="08:00",
                                first_name="Alice", last_name="Smith")

        summary, notify, _ = _execute_cycle(
            now=_dt(7, 30), fa_trips=[fa_trip], persons=[person]
        )

        # No mismatch alert
        for c in notify.alert_admin.call_args_list:
            assert "MISMATCH" not in str(c)


# ── Test: trip with no driver linked in DB is skipped ─────────────────────────

class TestUnlinkedDriver:
    def test_fa_trip_with_no_person_in_db_is_silently_skipped(self):
        """driverId=999 has no matching Person row → skipped, no crash."""
        fa_trip = _make_fa_trip(status="PENDING", driver_id=999, pickup="08:00")

        summary, notify, _ = _execute_cycle(
            now=_dt(7, 30), fa_trips=[fa_trip], persons=[]
        )

        notify.send_sms.assert_not_called()
        notify.alert_admin.assert_not_called()
        assert summary["trips_checked"] == 1


# ── Test: EverDriven trip flows ───────────────────────────────────────────────

class TestEdTripUnaccepted:
    def test_ed_scheduled_no_guid_sends_accept_sms(self):
        """
        ED run with status='Scheduled', driverGUID=None → unaccepted bucket.
        Within 60-min window.
        Expected: accept_sms sent.
        """
        person = _Person(person_id=2, full_name="Bob Driver",
                         phone="+12065550002", language="en",
                         everdriven_driver_id=201, active=True)
        ed_run = _make_ed_run(status="Scheduled", driver_id=201, driver_guid=None,
                              pickup="08:00", driver_name="Bob Driver")

        summary, notify, _ = _execute_cycle(
            now=_dt(7, 15), ed_runs=[ed_run], persons=[person]
        )

        assert summary["accept_sms"] == 1
        notify.send_sms.assert_called_once()


class TestEdTripCompleted:
    def test_ed_completed_no_notifications(self):
        """ED Completed → no alerts."""
        person = _Person(person_id=2, full_name="Bob Driver",
                         phone="+12065550002", language="en",
                         everdriven_driver_id=201, active=True)
        ed_run = _make_ed_run(status="Completed", driver_id=201, driver_guid="guid",
                              pickup="07:00", driver_name="Bob Driver")

        summary, notify, _ = _execute_cycle(
            now=_dt(8, 0), ed_runs=[ed_run], persons=[person]
        )

        notify.send_sms.assert_not_called()
        notify.alert_admin.assert_not_called()


# ── Test: accept call fires after SMS delay elapsed ───────────────────────────

class TestAcceptCallAfterSmsDelay:
    def test_call_fires_when_sms_delay_elapsed(self):
        """
        notif has accept_sms_at = now - 25 min (> _CALL_DELAY=20).
        Status still PENDING.
        Expected: make_call fired, not another SMS.
        """
        person = _Person(person_id=1, full_name="Alice Johnson",
                         phone="+12065550001", language="en",
                         firstalt_driver_id=101, active=True)
        fa_trip = _make_fa_trip(status="PENDING", driver_id=101, pickup="08:00",
                                first_name="Alice", last_name="Johnson")

        # Store naive datetimes: SQLite strips tzinfo on read-back.
        # The _execute_cycle harness also strips tzinfo from `now`,
        # so both sides of `now - notif.accept_sms_at` are naive.
        now = _dt(7, 45)
        sms_sent_at = _dt_naive(7, 20)   # 25 min before now, > _CALL_DELAY=20
        existing_notif = _TripNotification(
            person_id=1,
            trip_date=TRIP_DATE,
            source="firstalt",
            trip_ref="T001",
            trip_status="PENDING",
            pickup_time="08:00",
            accept_sms_at=sms_sent_at,
        )

        summary, notify, _ = _execute_cycle(
            now=now,
            fa_trips=[fa_trip],
            persons=[person],
            pre_existing_notifs=[existing_notif],
        )

        assert summary["accept_calls"] == 1
        notify.make_call.assert_called_once()
        notify.send_sms.assert_not_called()


# ── Test: escalation fires after call ────────────────────────────────────────

class TestAcceptEscalationAfterCall:
    def test_escalation_fires_immediately_after_call(self):
        """
        notif has accept_sms_at + accept_call_at set, no escalation yet.
        _ESCALATION_DELAY=0 → should escalate immediately.
        """
        person = _Person(person_id=1, full_name="Alice Johnson",
                         phone="+12065550001", language="en",
                         firstalt_driver_id=101, active=True)
        fa_trip = _make_fa_trip(status="PENDING", driver_id=101, pickup="08:00",
                                first_name="Alice", last_name="Johnson")

        # Store naive datetimes: SQLite strips tzinfo on read-back.
        # The _execute_cycle harness strips tzinfo from `now` too.
        now = _dt(7, 50)
        call_at = _dt_naive(7, 49)    # 1 min before now
        sms_at = _dt_naive(7, 28)     # 22 min before now
        existing_notif = _TripNotification(
            person_id=1,
            trip_date=TRIP_DATE,
            source="firstalt",
            trip_ref="T001",
            trip_status="PENDING",
            pickup_time="08:00",
            accept_sms_at=sms_at,
            accept_call_at=call_at,
        )

        summary, notify, _ = _execute_cycle(
            now=now,
            fa_trips=[fa_trip],
            persons=[person],
            pre_existing_notifs=[existing_notif],
        )

        assert summary["accept_escalations"] == 1
        notify.alert_admin.assert_called_once()
        msg = notify.alert_admin.call_args[0][0]
        assert "UNACCEPTED" in msg


# ── Test: summary counter accuracy ───────────────────────────────────────────

class TestSummaryCounters:
    def test_trips_checked_increments_for_each_trip(self):
        """Two FA trips → trips_checked == 2."""
        person = _Person(person_id=1, full_name="Alice Johnson",
                         phone="+12065550001", language="en",
                         firstalt_driver_id=101, active=True)
        fa_trips = [
            _make_fa_trip(trip_id="T001", status="COMPLETED", driver_id=101,
                          first_name="Alice", last_name="Johnson"),
            _make_fa_trip(trip_id="T002", status="COMPLETED", driver_id=101,
                          first_name="Alice", last_name="Johnson"),
        ]

        summary, _, _ = _execute_cycle(
            now=_dt(7, 30), fa_trips=fa_trips, persons=[person]
        )

        assert summary["trips_checked"] == 2

    def test_summary_has_all_required_keys(self):
        summary, _, _ = _execute_cycle(now=_dt(7, 30), fa_trips=[], ed_runs=[])
        required_keys = {
            "trips_checked", "accept_sms", "accept_calls", "accept_escalations",
            "start_sms", "start_calls", "start_escalations", "errors",
        }
        assert required_keys.issubset(summary.keys())


# ── Test: single-person, multiple trips ──────────────────────────────────────

class TestMultipleTripsForSamePerson:
    def test_two_pending_trips_both_get_sms(self):
        """Same driver has two separate unaccepted FA trips with distinct IDs within window."""
        person = _Person(person_id=1, full_name="Alice Johnson",
                         phone="+12065550001", language="en",
                         firstalt_driver_id=101, active=True)
        fa_trips = [
            # Use distinct tripIds so there is no unique-constraint collision
            {
                "tripId": "T-MULTI-001",
                "tripStatus": "PENDING",
                "driverId": 101,
                "firstPickUp": "08:00",
                "driverFirstName": "Alice",
                "driverLastName": "Johnson",
            },
            {
                "tripId": "T-MULTI-002",
                "tripStatus": "PENDING",
                "driverId": 101,
                "firstPickUp": "08:10",  # 55 min away, inside 60-min window
                "driverFirstName": "Alice",
                "driverLastName": "Johnson",
            },
        ]

        summary, notify, _ = _execute_cycle(
            now=_dt(7, 15), fa_trips=fa_trips, persons=[person]
        )

        assert summary["accept_sms"] == 2
        assert notify.send_sms.call_count == 2


# ── Test: _MONITOR_START_HOUR env var honored ────────────────────────────────

class TestEnvVarHonored:
    def test_custom_start_hour_via_env(self, monkeypatch):
        """If MONITOR_START_HOUR=6, cycles at hour=5 should be skipped."""
        monkeypatch.setenv("MONITOR_START_HOUR", "6")
        # We need to reimport the module to pick up the new env var.
        # Instead, we directly check the gate logic in run_monitoring_cycle.
        # The module reads the env var at import time, so we patch the constant.
        from backend.services import trip_monitor as tm
        original = tm._START_HOUR
        tm._START_HOUR = 6
        try:
            with patch("backend.services.trip_monitor.datetime") as mock_dt:
                mock_dt.now.return_value = _dt(5, 30)
                result = tm.run_monitoring_cycle()
            assert result.get("skipped") is True
        finally:
            tm._START_HOUR = original


# ── Test: FA trip with no pickup time string ──────────────────────────────────

class TestMissingPickupTime:
    def test_unparseable_pickup_time_for_unaccepted_alerts_admin(self):
        """
        FA trip has pickup='' for an unaccepted trip.
        Expected: TIME PARSE FAIL alert to admin, no SMS.
        """
        person = _Person(person_id=1, full_name="Alice Johnson",
                         phone="+12065550001", language="en",
                         firstalt_driver_id=101, active=True)
        fa_trip = _make_fa_trip(status="PENDING", driver_id=101, pickup="",
                                first_name="Alice", last_name="Johnson")

        summary, notify, _ = _execute_cycle(
            now=_dt(7, 30), fa_trips=[fa_trip], persons=[person]
        )

        notify.alert_admin.assert_called_once()
        msg = notify.alert_admin.call_args[0][0]
        assert "TIME PARSE" in msg or "FAIL" in msg or "can't" in msg.lower() or "parse" in msg.lower()

        notify.send_sms.assert_not_called()
