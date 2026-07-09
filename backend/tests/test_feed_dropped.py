"""
Tests for trip_monitor._flag_feed_dropped_trips (S2 feed-dropped observability)

Run with:
    PYTHONPATH=. pytest backend/tests/test_feed_dropped.py -x -v

Real in-memory SQLite (StaticPool) — exercises the actual queries.
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.db.models import Base, NotificationEvent, Person, TripNotification
from backend.services import trip_monitor


NOW = datetime(2026, 7, 9, 14, 0, tzinfo=timezone.utc)
TODAY = date(2026, 7, 9)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # SQLite has no NOW() — shim it for server_default=text("NOW()") columns.
    @event.listens_for(engine, "connect")
    def _register_now(dbapi_conn, _rec):
        dbapi_conn.create_function(
            "NOW", 0, lambda: datetime.now(timezone.utc).isoformat()
        )
    # Only the three tables this pass touches — full create_all trips over
    # Postgres-only column types (DATERANGE) on SQLite.
    Base.metadata.create_all(
        engine,
        tables=[Person.__table__, TripNotification.__table__, NotificationEvent.__table__],
    )
    session = sessionmaker(bind=engine)()
    trip_monitor._feed_missing_streak.clear()
    yield session
    session.close()


def _seed_notif(db, trip_ref: str = "111", source: str = "firstalt", **overrides):
    person = Person(full_name="Test Driver", active=True)
    db.add(person)
    db.flush()
    fields = {
        "person_id": person.person_id,
        "trip_date": TODAY,
        "source": source,
        "trip_ref": trip_ref,
        "trip_status": "SCHEDULED",
        "accept_sms_at": NOW,
        **overrides,
    }
    notif = TripNotification(**fields)
    db.add(notif)
    db.commit()
    return notif


def _events(db, notif):
    return (
        db.query(NotificationEvent)
        .filter(
            NotificationEvent.trip_notification_id == notif.id,
            NotificationEvent.event_type == "feed_dropped",
        )
        .all()
    )


def _run(db, all_trips, fa_ok=True, ed_ok=True):
    summary: dict = {}
    trip_monitor._flag_feed_dropped_trips(db, NOW, TODAY, all_trips, fa_ok, ed_ok, summary)
    db.commit()
    return summary


def test_trip_present_in_feed_is_not_flagged(db):
    notif = _seed_notif(db)
    feed = [{"source": "firstalt", "trip_ref": "111"}]
    _run(db, feed)
    _run(db, feed)
    assert _events(db, notif) == []


def test_missing_trip_flagged_only_after_two_consecutive_cycles(db):
    notif = _seed_notif(db)
    summary1 = _run(db, [])
    assert _events(db, notif) == []          # streak 1 — jitter grace
    assert "feed_dropped" not in summary1
    summary2 = _run(db, [])
    events = _events(db, notif)
    assert len(events) == 1                   # streak 2 — stamped
    assert events[0].payload["missed_cycles"] == 2
    assert summary2["feed_dropped"] == 1


def test_stamp_is_idempotent_across_further_cycles(db):
    notif = _seed_notif(db)
    for _ in range(4):
        _run(db, [])
    assert len(_events(db, notif)) == 1


def test_reappearing_trip_resets_streak(db):
    notif = _seed_notif(db)
    _run(db, [])                                              # miss 1
    _run(db, [{"source": "firstalt", "trip_ref": "111"}])     # back — reset
    _run(db, [])                                              # miss 1 again
    assert _events(db, notif) == []


def test_failed_source_fetch_is_never_scanned(db):
    notif = _seed_notif(db)
    _run(db, [], fa_ok=False)
    _run(db, [], fa_ok=False)
    assert _events(db, notif) == []


def test_accepted_or_resolved_trips_are_ignored(db):
    accepted = _seed_notif(db, trip_ref="222", accepted_at=NOW)
    resolved = _seed_notif(db, trip_ref="333", manually_resolved_at=NOW)
    _run(db, [])
    _run(db, [])
    assert _events(db, accepted) == []
    assert _events(db, resolved) == []


def test_trip_without_sms_is_ignored(db):
    notif = _seed_notif(db, trip_ref="444", accept_sms_at=None)
    _run(db, [])
    _run(db, [])
    assert _events(db, notif) == []
