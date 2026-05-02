"""
Twilio <Gather> webhook handler tests — Phase 3.

Tests all three digit paths (1 / 2 / 9) plus edge cases:
  - press 1 → sets manually_resolved_at, returns TwiML confirmation
  - press 2 → sets alert_profile.muted_until to midnight Pacific, returns TwiML
  - press 9 → bulk-snoozes all today's non-resolved notifications 30 min
  - unknown digit → returns re-prompt TwiML without mutating DB
  - fallback endpoint → returns "no input" TwiML
  - notif not found → 404-style TwiML response, no crash
  - idempotency: press-1 on already-resolved notif does not double-write

All tests run with MONITOR_DRY_RUN=1 so Twilio signature verification is
skipped.  DB is stubbed via unittest.mock — no real Postgres needed.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Ensure project root on sys.path
_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.environ.setdefault("MONITOR_DRY_RUN", "1")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost/test")
os.environ.setdefault("ZPAY_SECRET_KEY", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("ZPAY_ENCRYPTION_KEY", "Ry9f3q2lX1kN8pM7vB4cZ6wQ0sJ5uY2eD3tH9oA1gU=")


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_notif(
    notif_id: int = 1,
    person_id: int = 42,
    manually_resolved_at: datetime | None = None,
    snoozed_until: datetime | None = None,
    trip_date: date | None = None,
) -> MagicMock:
    n = MagicMock()
    n.id = notif_id
    n.person_id = person_id
    n.manually_resolved_at = manually_resolved_at
    n.snoozed_until = snoozed_until
    n.trip_date = trip_date or date.today()
    return n


def _make_person(
    person_id: int = 42,
    full_name: str = "Hassan El-Amin",
    alert_profile: dict | None = None,
) -> MagicMock:
    p = MagicMock()
    p.person_id = person_id
    p.full_name = full_name
    p.alert_profile = alert_profile or {}
    return p


def _build_client(db_mock: MagicMock) -> TestClient:
    """Build a TestClient with the real FastAPI app but a stubbed DB session."""
    from backend.app import app
    from backend.db import get_db

    def _override_db():
        yield db_mock

    app.dependency_overrides[get_db] = _override_db
    client = TestClient(app, raise_server_exceptions=True)
    return client


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def db():
    return MagicMock()


@pytest.fixture()
def client(db):
    from backend.app import app
    from backend.db import get_db

    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


# ── Press-1: mark trip handled ─────────────────────────────────────────────

class TestPress1MarkHandled:
    def _setup_db(self, db: MagicMock, notif: MagicMock) -> None:
        db.query.return_value.filter.return_value.first.return_value = notif
        db.add = MagicMock()
        db.flush = MagicMock()
        db.commit = MagicMock()

    def test_press_1_sets_manually_resolved_at(self, client, db):
        notif = _make_notif(notif_id=10)
        self._setup_db(db, notif)

        resp = client.post(
            "/api/twilio/voice-gather?notif_id=10",
            data={"Digits": "1"},
        )
        assert resp.status_code == 200
        assert notif.manually_resolved_at is not None

    def test_press_1_returns_xml(self, client, db):
        notif = _make_notif(notif_id=10)
        self._setup_db(db, notif)

        resp = client.post(
            "/api/twilio/voice-gather?notif_id=10",
            data={"Digits": "1"},
        )
        assert "text/xml" in resp.headers["content-type"]
        assert "<Response>" in resp.text
        assert "<Say" in resp.text

    def test_press_1_confirmation_message(self, client, db):
        notif = _make_notif(notif_id=10)
        self._setup_db(db, notif)

        resp = client.post(
            "/api/twilio/voice-gather?notif_id=10",
            data={"Digits": "1"},
        )
        assert "handled" in resp.text.lower()

    def test_press_1_idempotent_already_resolved(self, client, db):
        """Second press-1 on already-resolved notif should not overwrite timestamp."""
        already_resolved = datetime(2026, 5, 2, 8, 0, tzinfo=timezone.utc)
        notif = _make_notif(notif_id=10, manually_resolved_at=already_resolved)
        self._setup_db(db, notif)

        client.post(
            "/api/twilio/voice-gather?notif_id=10",
            data={"Digits": "1"},
        )
        # Should NOT overwrite the existing timestamp
        assert notif.manually_resolved_at == already_resolved

    def test_press_1_commits_db(self, client, db):
        notif = _make_notif(notif_id=10)
        self._setup_db(db, notif)

        client.post(
            "/api/twilio/voice-gather?notif_id=10",
            data={"Digits": "1"},
        )
        db.commit.assert_called_once()


# ── Press-2: mute driver today ─────────────────────────────────────────────

class TestPress2MuteDriver:
    def _setup_db(self, db: MagicMock, notif: MagicMock, person: MagicMock) -> None:
        # query() is called twice: once for TripNotification, once for Person
        db.query.return_value.filter.return_value.first.side_effect = [notif, person]
        db.add = MagicMock()
        db.flush = MagicMock()
        db.commit = MagicMock()

    def test_press_2_sets_muted_until(self, client, db):
        notif = _make_notif(notif_id=20, person_id=42)
        person = _make_person(person_id=42)
        self._setup_db(db, notif, person)

        resp = client.post(
            "/api/twilio/voice-gather?notif_id=20",
            data={"Digits": "2"},
        )
        assert resp.status_code == 200
        assert "muted_until" in person.alert_profile

    def test_press_2_muted_until_is_future(self, client, db):
        notif = _make_notif(notif_id=20, person_id=42)
        person = _make_person(person_id=42)
        self._setup_db(db, notif, person)

        client.post(
            "/api/twilio/voice-gather?notif_id=20",
            data={"Digits": "2"},
        )
        from datetime import datetime as _dt
        muted_until_str = person.alert_profile["muted_until"]
        muted_until = _dt.fromisoformat(muted_until_str)
        assert muted_until > datetime.now(timezone.utc)

    def test_press_2_confirmation_contains_driver_name(self, client, db):
        notif = _make_notif(notif_id=20, person_id=42)
        person = _make_person(person_id=42, full_name="Omar Nasser")
        self._setup_db(db, notif, person)

        resp = client.post(
            "/api/twilio/voice-gather?notif_id=20",
            data={"Digits": "2"},
        )
        # First name "Omar" should appear in response
        assert "Omar" in resp.text

    def test_press_2_xml_encode_ampersand_in_name(self, client, db):
        """Driver name containing & must not break TwiML XML."""
        notif = _make_notif(notif_id=20, person_id=42)
        person = _make_person(person_id=42, full_name="Tom & Jerry")
        self._setup_db(db, notif, person)

        resp = client.post(
            "/api/twilio/voice-gather?notif_id=20",
            data={"Digits": "2"},
        )
        assert resp.status_code == 200
        # Raw & must NOT appear in XML body (would break TwiML parser)
        import xml.etree.ElementTree as ET
        ET.fromstring(resp.text)  # raises if not valid XML

    def test_press_2_commits_db(self, client, db):
        notif = _make_notif(notif_id=20, person_id=42)
        person = _make_person(person_id=42)
        self._setup_db(db, notif, person)

        client.post(
            "/api/twilio/voice-gather?notif_id=20",
            data={"Digits": "2"},
        )
        db.commit.assert_called_once()


# ── Press-9: snooze all active trips 30 min ───────────────────────────────

class TestPress9SnoozeAll:
    def _setup_db(
        self,
        db: MagicMock,
        notif: MagicMock,
        active_notifs: list[MagicMock],
    ) -> None:
        # First query → fetch the target notif; second → fetch all active notifs
        def _query_side_effect(model):
            q = MagicMock()
            q.filter.return_value.first.return_value = notif
            q.filter.return_value.all.return_value = active_notifs
            return q

        db.query.side_effect = _query_side_effect
        db.add = MagicMock()
        db.flush = MagicMock()
        db.commit = MagicMock()

    def test_press_9_snoozes_all_active(self, client, db):
        notif = _make_notif(notif_id=30)
        active = [_make_notif(i) for i in range(1, 4)]  # 3 active trips
        self._setup_db(db, notif, active)

        resp = client.post(
            "/api/twilio/voice-gather?notif_id=30",
            data={"Digits": "9"},
        )
        assert resp.status_code == 200
        for n in active:
            assert n.snoozed_until is not None

    def test_press_9_snooze_duration_approx_30min(self, client, db):
        notif = _make_notif(notif_id=30)
        active = [_make_notif(1)]
        self._setup_db(db, notif, active)

        before = datetime.now(timezone.utc)
        client.post(
            "/api/twilio/voice-gather?notif_id=30",
            data={"Digits": "9"},
        )
        after = datetime.now(timezone.utc)

        snoozed = active[0].snoozed_until
        # Should be approximately now + 30 min (within a 5s window)
        expected_low = before + timedelta(minutes=29, seconds=55)
        expected_high = after + timedelta(minutes=30, seconds=5)
        assert expected_low <= snoozed <= expected_high

    def test_press_9_does_not_shorten_existing_snooze(self, client, db):
        """If a notif already has a longer snooze, press-9 should not shorten it."""
        notif = _make_notif(notif_id=30)
        long_snooze = datetime.now(timezone.utc) + timedelta(hours=2)
        already_snoozed = _make_notif(1, snoozed_until=long_snooze)
        self._setup_db(db, notif, [already_snoozed])

        client.post(
            "/api/twilio/voice-gather?notif_id=30",
            data={"Digits": "9"},
        )
        # Should not be shorter than the original long snooze
        assert already_snoozed.snoozed_until >= long_snooze

    def test_press_9_confirmation_mentions_count(self, client, db):
        notif = _make_notif(notif_id=30)
        active = [_make_notif(i) for i in range(1, 4)]
        self._setup_db(db, notif, active)

        resp = client.post(
            "/api/twilio/voice-gather?notif_id=30",
            data={"Digits": "9"},
        )
        # Response should mention "3" (the count of snoozed trips)
        assert "3" in resp.text

    def test_press_9_commits_db(self, client, db):
        notif = _make_notif(notif_id=30)
        self._setup_db(db, notif, [])

        client.post(
            "/api/twilio/voice-gather?notif_id=30",
            data={"Digits": "9"},
        )
        db.commit.assert_called_once()


# ── Unknown digit ─────────────────────────────────────────────────────────

class TestUnknownDigit:
    def _setup_db(self, db: MagicMock, notif: MagicMock) -> None:
        db.query.return_value.filter.return_value.first.return_value = notif

    def test_unknown_digit_returns_reprompt(self, client, db):
        notif = _make_notif(notif_id=5)
        self._setup_db(db, notif)

        resp = client.post(
            "/api/twilio/voice-gather?notif_id=5",
            data={"Digits": "7"},
        )
        assert resp.status_code == 200
        # Should re-prompt with options
        assert "1" in resp.text
        assert "2" in resp.text
        assert "9" in resp.text

    def test_no_digit_returns_reprompt(self, client, db):
        notif = _make_notif(notif_id=5)
        self._setup_db(db, notif)

        resp = client.post(
            "/api/twilio/voice-gather?notif_id=5",
            data={},  # no Digits key
        )
        assert resp.status_code == 200
        assert "<Say" in resp.text

    def test_unknown_digit_does_not_mutate_notif(self, client, db):
        notif = _make_notif(notif_id=5)
        original_resolved = notif.manually_resolved_at
        original_snoozed = notif.snoozed_until
        self._setup_db(db, notif)

        client.post(
            "/api/twilio/voice-gather?notif_id=5",
            data={"Digits": "5"},
        )
        assert notif.manually_resolved_at == original_resolved
        assert notif.snoozed_until == original_snoozed


# ── Notif not found ──────────────────────────────────────────────────────

class TestNotifNotFound:
    def test_missing_notif_returns_twiml_not_exception(self, client, db):
        db.query.return_value.filter.return_value.first.return_value = None

        resp = client.post(
            "/api/twilio/voice-gather?notif_id=9999",
            data={"Digits": "1"},
        )
        assert resp.status_code == 200
        assert "<Say" in resp.text
        assert "text/xml" in resp.headers["content-type"]


# ── Fallback endpoint ────────────────────────────────────────────────────

class TestFallbackEndpoint:
    def test_fallback_returns_twiml(self, client, db):
        resp = client.post("/api/twilio/voice-gather/fallback")
        assert resp.status_code == 200
        assert "text/xml" in resp.headers["content-type"]
        assert "<Say" in resp.text

    def test_fallback_message_mentions_no_input(self, client, db):
        resp = client.post("/api/twilio/voice-gather/fallback")
        assert "no input" in resp.text.lower() or "input" in resp.text.lower()


# ── TwiML validity ───────────────────────────────────────────────────────

class TestTwimlValidity:
    """All responses must be parseable as valid XML."""

    def _setup_db_press_1(self, db, notif):
        db.query.return_value.filter.return_value.first.return_value = notif
        db.add = MagicMock()
        db.flush = MagicMock()
        db.commit = MagicMock()

    def test_press_1_response_is_valid_xml(self, client, db):
        import xml.etree.ElementTree as ET
        notif = _make_notif(notif_id=1)
        self._setup_db_press_1(db, notif)

        resp = client.post(
            "/api/twilio/voice-gather?notif_id=1",
            data={"Digits": "1"},
        )
        ET.fromstring(resp.text)  # raises ParseError if invalid

    def test_fallback_response_is_valid_xml(self, client, db):
        import xml.etree.ElementTree as ET
        resp = client.post("/api/twilio/voice-gather/fallback")
        ET.fromstring(resp.text)
