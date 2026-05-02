"""
Tests for backend/routes/ops_dashboard.py

Run with:
    PYTHONPATH=. pytest backend/tests/test_ops_dashboard.py -v

Uses SQLite in-memory via FastAPI TestClient — no Postgres needed.

Covered cases
-------------
 1. /dashboard returns correct top-level shape
 2. live_trips only contains unaccepted + accepted-not-started (not started/completed)
 3. alerts_feed filtered to last 60 minutes only (older events excluded)
 4. driver_concurrency flags drivers with >2 active accepted trips
 5. scheduler_liveness.is_stale = True when last_cycle is > 15 min old
 6. scheduler_liveness.is_stale = False for a fresh cycle
 7. pause-monitor sets monitor_paused flag
 8. mute-all mutes drivers with unaccepted trips today
 9. trip-explain returns correct bucket for unaccepted trip
10. chronic-non-tappers returns drivers with >5 un-accepted trips this week
11. run-cycle-now returns stub 200 response
12. dashboard live_trips urgent flag set when pickup < 15min and unaccepted
"""

from __future__ import annotations

import sys
import os
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ── Lightweight SQLite models mirror ──────────────────────────────────────────

from sqlalchemy import (
    create_engine, Column, Integer, Text, Boolean, Date,
    DateTime, JSON, ForeignKey, BigInteger, Index
)
from sqlalchemy.orm import declarative_base, Session, relationship
from sqlalchemy.sql import text as sa_text

_Base = declarative_base()

UTC = timezone.utc


class _Person(_Base):
    __tablename__ = "person"
    person_id = Column(Integer, primary_key=True)
    full_name = Column(Text, nullable=False)
    phone = Column(Text, nullable=True)
    active = Column(Boolean, default=True)
    alert_profile = Column(JSON, nullable=True)


class _TripNotification(_Base):
    __tablename__ = "trip_notification"
    id = Column(Integer, primary_key=True, autoincrement=True)
    person_id = Column(Integer, ForeignKey("person.person_id"), nullable=False)
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
    overdue_alerted_at = Column(DateTime(timezone=True), nullable=True)
    original_pickup_dt = Column(DateTime(timezone=True), nullable=True)
    arrived_at_pickup = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    snoozed_until = Column(DateTime(timezone=True), nullable=True)
    manually_resolved_at = Column(DateTime(timezone=True), nullable=True)
    manually_resolved_by = Column(Integer, nullable=True)
    last_escalated_at = Column(DateTime(timezone=True), nullable=True)
    dedup_suppressed = Column(Boolean, default=False)
    dedup_primary_notif_id = Column(Integer, nullable=True)
    dispatch_severity = Column(Text, default="normal")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    person = relationship("_Person", foreign_keys=[person_id])


class _NotificationEvent(_Base):
    __tablename__ = "notification_event"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trip_notification_id = Column(Integer, ForeignKey("trip_notification.id"), nullable=False)
    event_type = Column(Text, nullable=False)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    created_by_person_id = Column(Integer, nullable=True)
    trip_notification = relationship("_TripNotification", foreign_keys=[trip_notification_id])


# ── Engine + session factory ───────────────────────────────────────────────────

def _make_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    _Base.metadata.create_all(engine)
    return engine


def _session(engine) -> Session:
    return Session(bind=engine)


# ── Seed helpers ──────────────────────────────────────────────────────────────

_TODAY = date.today()
_NOW = datetime.now(UTC)


def _add_person(db: Session, *, person_id: int = 1, name: str = "Test Driver") -> _Person:
    p = _Person(person_id=person_id, full_name=name, active=True)
    db.add(p)
    db.flush()
    return p


def _add_notif(
    db: Session,
    *,
    person_id: int = 1,
    trip_ref: str = "T001",
    source: str = "firstalt",
    trip_date: date | None = None,
    pickup_time: str = "08:30",
    accepted_at: datetime | None = None,
    started_at: datetime | None = None,
    accept_sms_at: datetime | None = None,
    accept_escalated_at: datetime | None = None,
    manually_resolved_at: datetime | None = None,
    dedup_suppressed: bool = False,
) -> _TripNotification:
    n = _TripNotification(
        person_id=person_id,
        trip_date=trip_date or _TODAY,
        source=source,
        trip_ref=trip_ref,
        pickup_time=pickup_time,
        accepted_at=accepted_at,
        started_at=started_at,
        accept_sms_at=accept_sms_at,
        accept_escalated_at=accept_escalated_at,
        manually_resolved_at=manually_resolved_at,
        dedup_suppressed=dedup_suppressed,
        dedup_primary_notif_id=None,
    )
    db.add(n)
    db.flush()
    return n


def _add_event(
    db: Session,
    *,
    notif_id: int,
    event_type: str = "accept_sms",
    created_at: datetime | None = None,
) -> _NotificationEvent:
    ev = _NotificationEvent(
        trip_notification_id=notif_id,
        event_type=event_type,
        payload={},
        created_at=created_at or _NOW,
    )
    db.add(ev)
    db.flush()
    return ev


# ── Patch helpers (swap real models for test models) ──────────────────────────

import backend.routes.ops_dashboard as _mod


def _patch_db(db: Session):
    """Return a context-manager that swaps the real ORM models for test models."""
    return patch.multiple(
        _mod,
        TripNotification=_TripNotification,
        NotificationEvent=_NotificationEvent,
        Person=_Person,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestLiveTrips:
    """Test 2: live_trips only contains unaccepted + accepted-not-started trips."""

    def test_excludes_started_trips(self):
        engine = _make_engine()
        db = _session(engine)
        _add_person(db, person_id=1, name="Alice")
        _add_person(db, person_id=2, name="Bob")
        _add_person(db, person_id=3, name="Carol")

        # Unaccepted — should appear
        _add_notif(db, person_id=1, trip_ref="U001")
        # Accepted-not-started — should appear
        _add_notif(db, person_id=2, trip_ref="A001", accepted_at=_NOW - timedelta(minutes=30))
        # Started — should NOT appear
        _add_notif(db, person_id=3, trip_ref="S001", accepted_at=_NOW - timedelta(hours=1), started_at=_NOW)
        db.commit()

        with _patch_db(db):
            trips = _mod._live_trips(db)

        trip_refs = {t["trip_ref"] for t in trips}
        assert "U001" in trip_refs, "Unaccepted trip should appear in live_trips"
        assert "A001" in trip_refs, "Accepted-not-started trip should appear in live_trips"
        assert "S001" not in trip_refs, "Started trip must NOT appear in live_trips"

    def test_excludes_manually_resolved(self):
        engine = _make_engine()
        db = _session(engine)
        _add_person(db, person_id=1, name="Alice")
        _add_notif(db, person_id=1, trip_ref="R001", manually_resolved_at=_NOW)
        db.commit()

        with _patch_db(db):
            trips = _mod._live_trips(db)

        assert all(t["trip_ref"] != "R001" for t in trips), "Manually resolved trip must be excluded"

    def test_excludes_dedup_suppressed(self):
        engine = _make_engine()
        db = _session(engine)
        _add_person(db, person_id=1, name="Alice")
        _add_notif(db, person_id=1, trip_ref="D001", dedup_suppressed=True)
        db.commit()

        with _patch_db(db):
            trips = _mod._live_trips(db)

        assert all(t["trip_ref"] != "D001" for t in trips), "Dedup-suppressed trip must be excluded"


class TestAlertsFeed:
    """Test 3: alerts_feed filtered to last 60 minutes."""

    def test_excludes_old_events(self):
        engine = _make_engine()
        db = _session(engine)
        _add_person(db, person_id=1, name="Alice")
        notif = _add_notif(db, person_id=1, trip_ref="A001")

        # Recent event — within 60 min
        _add_event(db, notif_id=notif.id, event_type="accept_sms", created_at=_NOW - timedelta(minutes=30))
        # Old event — 90 min ago, should be excluded
        _add_event(db, notif_id=notif.id, event_type="accept_call", created_at=_NOW - timedelta(minutes=90))
        db.commit()

        with _patch_db(db):
            feed = _mod._alerts_feed(db)

        event_types = [e["event_type"] for e in feed]
        assert "accept_sms" in event_types, "Recent event must be in alerts_feed"
        assert "accept_call" not in event_types, "Old event (90 min) must be excluded from alerts_feed"

    def test_channel_mapping_sms(self):
        engine = _make_engine()
        db = _session(engine)
        _add_person(db, person_id=1, name="Alice")
        notif = _add_notif(db, person_id=1, trip_ref="A002")
        _add_event(db, notif_id=notif.id, event_type="accept_sms", created_at=_NOW - timedelta(minutes=5))
        db.commit()

        with _patch_db(db):
            feed = _mod._alerts_feed(db)

        sms_event = next((e for e in feed if e["event_type"] == "accept_sms"), None)
        assert sms_event is not None
        assert sms_event["channel"] == "sms"


class TestDriverConcurrency:
    """Test 4: driver_concurrency flags drivers with >2 active trips."""

    def test_flags_driver_with_three_active_trips(self):
        engine = _make_engine()
        db = _session(engine)
        _add_person(db, person_id=1, name="Heavy Driver")
        _add_person(db, person_id=2, name="Normal Driver")

        # Driver 1: 3 accepted-not-started trips
        for i in range(3):
            _add_notif(
                db, person_id=1, trip_ref=f"H00{i}",
                accepted_at=_NOW - timedelta(minutes=30 + i),
            )
        # Driver 2: 1 accepted trip — not flagged
        _add_notif(db, person_id=2, trip_ref="N001", accepted_at=_NOW - timedelta(minutes=20))
        db.commit()

        with _patch_db(db):
            conc = _mod._driver_concurrency(db)

        driver1 = next((c for c in conc if c["person_id"] == 1), None)
        driver2 = next((c for c in conc if c["person_id"] == 2), None)

        assert driver1 is not None, "Driver with 3 active trips must appear"
        assert driver1["flagged"] is True, "Driver with >2 active trips must be flagged"
        assert driver2 is not None, "Driver with 1 active trip must appear (it's >= 1)"
        assert driver2["flagged"] is False, "Driver with 1 active trip must NOT be flagged"


class TestSchedulerLiveness:
    """Tests 5 & 6: scheduler_liveness.is_stale logic."""

    def test_is_stale_when_last_cycle_over_15min(self):
        stale_time = (_NOW - timedelta(minutes=20)).isoformat()
        mock_status = {
            "enabled": True,
            "last_run": stale_time,
        }
        with (
            patch("backend.routes.ops_dashboard.get_status", return_value=mock_status, create=True),
            patch("backend.routes.ops_dashboard._HOT_INTERVAL_SECONDS", 60, create=True),
            patch("backend.routes.ops_dashboard._ADAPTIVE_CADENCE", True, create=True),
        ):
            # Import fresh to use patched get_status
            from backend.services import trip_monitor as tm
            with patch.object(tm, "_last_run_info", {"last_run": stale_time, "summary": None, "error": None}):
                with patch.object(tm, "_scheduler", MagicMock()):
                    liveness = _mod._scheduler_liveness()

        assert liveness["is_stale"] is True, "Should be stale when last cycle was 20 min ago"

    def test_not_stale_when_last_cycle_recent(self):
        fresh_time = (_NOW - timedelta(minutes=2)).isoformat()
        mock_status = {
            "enabled": True,
            "last_run": fresh_time,
        }
        with (
            patch("backend.routes.ops_dashboard.get_status", return_value=mock_status, create=True),
            patch("backend.routes.ops_dashboard._HOT_INTERVAL_SECONDS", 60, create=True),
            patch("backend.routes.ops_dashboard._ADAPTIVE_CADENCE", True, create=True),
        ):
            from backend.services import trip_monitor as tm
            with patch.object(tm, "_last_run_info", {"last_run": fresh_time, "summary": None, "error": None}):
                with patch.object(tm, "_scheduler", MagicMock()):
                    liveness = _mod._scheduler_liveness()

        assert liveness["is_stale"] is False, "Should NOT be stale when last cycle was 2 min ago"


class TestPauseMonitor:
    """Test 7: pause-monitor sets the in-memory flag."""

    def test_pause_monitor_sets_flag(self):
        import asyncio
        import json
        _mod._monitor_paused = False
        result = asyncio.run(_mod.pause_monitor())
        parsed = json.loads(result.body)
        assert parsed["monitor_paused"] is True
        assert _mod._monitor_paused is True
        # Reset for other tests
        _mod._monitor_paused = False


class TestMuteAll:
    """Test 8: mute-all mutes all drivers with unaccepted trips today."""

    def test_mute_all_sets_alert_profile(self):
        import asyncio
        import json
        engine = _make_engine()
        db = _session(engine)
        _add_person(db, person_id=1, name="Alice")
        _add_person(db, person_id=2, name="Bob")
        _add_notif(db, person_id=1, trip_ref="U001")  # unaccepted
        _add_notif(db, person_id=2, trip_ref="U002")  # unaccepted
        db.commit()

        mock_request = MagicMock()
        with _patch_db(db):
            result = asyncio.run(_mod.mute_all(mock_request, db))

        parsed = json.loads(result.body)
        assert parsed["ok"] is True
        assert parsed["muted_count"] == 2

        # Verify alert_profile was written
        db.expire_all()
        p1 = db.query(_Person).filter(_Person.person_id == 1).first()
        p2 = db.query(_Person).filter(_Person.person_id == 2).first()
        assert p1.alert_profile is not None
        assert "muted_until" in p1.alert_profile
        assert p2.alert_profile is not None


class TestTripExplain:
    """Test 9: trip-explain returns correct bucket."""

    def test_unaccepted_sms_sent_bucket(self):
        engine = _make_engine()
        db = _session(engine)
        _add_person(db, person_id=1, name="Alice")
        notif = _add_notif(
            db, person_id=1, trip_ref="X001",
            accept_sms_at=_NOW - timedelta(minutes=10),
        )
        db.commit()

        with _patch_db(db):
            result = _mod.trip_explain(notif.id, db)

        import json
        parsed = json.loads(result.body)
        assert parsed["bucket"] == "unaccepted_sms_sent"
        assert parsed["driver"] == "Alice"

    def test_not_found_returns_404(self):
        engine = _make_engine()
        db = _session(engine)
        db.commit()

        with _patch_db(db):
            result = _mod.trip_explain(99999, db)

        assert result.status_code == 404


class TestChronicNonTappers:
    """Test 10: chronic-non-tappers returns drivers with >5 non-accepted this week."""

    def test_returns_offenders_above_threshold(self):
        engine = _make_engine()
        db = _session(engine)
        _add_person(db, person_id=1, name="Chronic Carl")
        _add_person(db, person_id=2, name="Good Gail")

        # Carl: 6 trips with accept_sms but no accepted_at
        for i in range(6):
            _add_notif(
                db, person_id=1, trip_ref=f"C00{i}",
                accept_sms_at=_NOW - timedelta(hours=i),
            )
        # Gail: 3 trips — below threshold
        for i in range(3):
            _add_notif(
                db, person_id=2, trip_ref=f"G00{i}",
                accept_sms_at=_NOW - timedelta(hours=i),
            )
        db.commit()

        with _patch_db(db):
            result = _mod.chronic_non_tappers(week=None, db=db)

        import json
        parsed = json.loads(result.body)
        offenders = {o["person_id"] for o in parsed["offenders"]}
        assert 1 in offenders, "Carl (6 non-taps) must appear as offender"
        assert 2 not in offenders, "Gail (3 non-taps) must NOT appear as offender"

    def test_empty_result_when_no_offenders(self):
        engine = _make_engine()
        db = _session(engine)
        db.commit()

        with _patch_db(db):
            result = _mod.chronic_non_tappers(week=None, db=db)

        import json
        parsed = json.loads(result.body)
        assert parsed["offenders"] == []


class TestRunCycleNowStub:
    """Test 11: run-cycle-now returns stub 200."""

    def test_stub_returns_ok(self):
        import asyncio
        import json
        result = asyncio.run(_mod.run_cycle_now())
        parsed = json.loads(result.body)
        assert parsed["ok"] is True
        assert parsed["status"] == "stub"


class TestUrgentFlag:
    """Test 12: is_urgent set when pickup < 15 min and unaccepted."""

    def test_urgent_flag_for_imminent_pickup(self):
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Los_Angeles")
        now_local = datetime.now(tz)
        # Pickup 10 minutes from now
        imminent = now_local + timedelta(minutes=10)
        pickup_str = f"{imminent.hour:02d}:{imminent.minute:02d}"

        engine = _make_engine()
        db = _session(engine)
        _add_person(db, person_id=1, name="Alice")
        _add_notif(db, person_id=1, trip_ref="URGENT", pickup_time=pickup_str)
        db.commit()

        with _patch_db(db):
            trips = _mod._live_trips(db)

        urgent_trips = [t for t in trips if t["trip_ref"] == "URGENT"]
        assert len(urgent_trips) == 1
        assert urgent_trips[0]["is_urgent"] is True, "Trip 10 min away and unaccepted must be flagged urgent"

    def test_not_urgent_when_accepted(self):
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Los_Angeles")
        now_local = datetime.now(tz)
        imminent = now_local + timedelta(minutes=5)
        pickup_str = f"{imminent.hour:02d}:{imminent.minute:02d}"

        engine = _make_engine()
        db = _session(engine)
        _add_person(db, person_id=1, name="Alice")
        _add_notif(
            db, person_id=1, trip_ref="ACC",
            pickup_time=pickup_str,
            accepted_at=_NOW - timedelta(minutes=30),
        )
        db.commit()

        with _patch_db(db):
            trips = _mod._live_trips(db)

        acc_trips = [t for t in trips if t["trip_ref"] == "ACC"]
        assert len(acc_trips) == 1
        assert acc_trips[0]["is_urgent"] is False, "Accepted trip must NOT be flagged urgent even if pickup is imminent"


class TestTripHeatmap:
    """
    Tests for GET /ops-dashboard/heatmap.

    13. Response has correct shape (days/hours/matrix/peak_count keys).
    14. Trip in today's window lands in the correct day + hour bucket.
    15. Trip outside the 7-day window is excluded from the matrix.
    16. peak_count equals the max cell value.
    17. Rows with unparseable pickup_time are skipped gracefully.
    """

    def test_response_shape(self):
        engine = _make_engine()
        db = _session(engine)
        db.commit()

        with _patch_db(db):
            result = _mod.trip_heatmap(db)

        import json
        parsed = json.loads(result.body)
        assert "days" in parsed
        assert "hours" in parsed
        assert "matrix" in parsed
        assert "peak_count" in parsed
        assert "window_start" in parsed
        assert "window_end" in parsed
        assert len(parsed["days"]) == 7
        assert len(parsed["hours"]) == 24
        assert len(parsed["matrix"]) == 7
        assert all(len(row) == 24 for row in parsed["matrix"])

    def test_trip_lands_in_correct_bucket(self):
        engine = _make_engine()
        db = _session(engine)
        _add_person(db, person_id=1, name="Alice")
        # Today, pickup at 08:00
        _add_notif(db, person_id=1, trip_ref="H001", pickup_time="08:00", trip_date=_TODAY)
        db.commit()

        with _patch_db(db):
            result = _mod.trip_heatmap(db)

        import json
        parsed = json.loads(result.body)
        # Today is the last day (index 6)
        assert parsed["matrix"][6][8] >= 1, "Trip at 08:00 today must land in day_idx=6, hour=8"

    def test_trip_outside_window_excluded(self):
        engine = _make_engine()
        db = _session(engine)
        _add_person(db, person_id=1, name="Alice")
        # 8 days ago — outside the 7-day window
        old_date = _TODAY - timedelta(days=8)
        _add_notif(db, person_id=1, trip_ref="OLD", pickup_time="09:00", trip_date=old_date)
        db.commit()

        with _patch_db(db):
            result = _mod.trip_heatmap(db)

        import json
        parsed = json.loads(result.body)
        total = sum(cell for row in parsed["matrix"] for cell in row)
        assert total == 0, "Trip 8 days ago must not appear in the 7-day window"

    def test_peak_count_matches_max_cell(self):
        engine = _make_engine()
        db = _session(engine)
        _add_person(db, person_id=1, name="Alice")
        _add_person(db, person_id=2, name="Bob")
        _add_person(db, person_id=3, name="Carol")
        # 3 trips at 07:00 today → peak should be 3
        _add_notif(db, person_id=1, trip_ref="P001", pickup_time="07:00", trip_date=_TODAY)
        _add_notif(db, person_id=2, trip_ref="P002", pickup_time="07:00", trip_date=_TODAY)
        _add_notif(db, person_id=3, trip_ref="P003", pickup_time="07:00", trip_date=_TODAY)
        db.commit()

        with _patch_db(db):
            result = _mod.trip_heatmap(db)

        import json
        parsed = json.loads(result.body)
        assert parsed["peak_count"] == 3
        assert parsed["matrix"][6][7] == 3

    def test_unparseable_pickup_time_skipped(self):
        engine = _make_engine()
        db = _session(engine)
        _add_person(db, person_id=1, name="Alice")
        # pickup_time that can't be parsed as an hour
        _add_notif(db, person_id=1, trip_ref="BAD", pickup_time="not-a-time", trip_date=_TODAY)
        db.commit()

        with _patch_db(db):
            # Should not raise
            result = _mod.trip_heatmap(db)

        import json
        parsed = json.loads(result.body)
        assert parsed["peak_count"] == 0, "Unparseable pickup_time must be skipped"
