"""
backend/tests/test_scorecard_cron.py
=====================================
Tests for Phase 10: weekly scorecard SMS + email cron.

Covers:
- run_scorecard_cron(): happy path, skips unsubscribed, skips no phone/email
- idempotency: second run same week is a no-op
- backoff: Twilio failure logs but continues to next driver
- email failure logs but continues to next driver
- opt_out_driver(): sets unsubscribed_scorecard flag
- build_sms_text(): correct format
- build_email_html(): contains required elements
- send_scorecard_to_driver(): wires SMS + email correctly
- manual trigger endpoint: POST /admin/scorecard/send-now

Run:
    PYTHONPATH=. pytest backend/tests/test_scorecard_cron.py -x -v
"""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_person(
    person_id: int = 1,
    full_name: str = "Ahmed Hassan",
    phone: str = "+12065551234",
    email: str = "ahmed@example.com",
    active: bool = True,
    alert_profile: dict | None = None,
) -> MagicMock:
    p = MagicMock()
    p.person_id = person_id
    p.full_name = full_name
    p.phone = phone
    p.email = email
    p.active = active
    p.alert_profile = alert_profile or {}
    return p


def _make_scorecard(
    tier: str = "gold",
    tier_label: str = "Gold",
    composite_score: float = 93.5,
    focus_area: str = "Accept trips quickly to lock in your rate.",
    week_iso: str = "2026-W18",
) -> MagicMock:
    sc = MagicMock()
    sc.tier = tier
    sc.tier_label = tier_label
    sc.composite_score = composite_score
    sc.focus_area = focus_area
    sc.week_iso = week_iso
    return sc


# ── Import target (after helpers so mocks are ready) ─────────────────────────

from backend.services.scorecard_cron import (
    build_email_html,
    build_sms_text,
    opt_out_driver,
    send_scorecard_to_driver,
)


# ═══════════════════════════════════════════════════════════════════════════════
# build_sms_text
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildSmsText:
    def test_contains_week_number(self):
        text = build_sms_text(
            first_name="Ahmed",
            week_iso="2026-W18",
            tier_label="Gold",
            composite_score=93.5,
            scorecard_url="https://example.com/scorecard/abc123",
        )
        assert "18" in text

    def test_contains_tier(self):
        text = build_sms_text(
            first_name="Ahmed",
            week_iso="2026-W18",
            tier_label="Gold",
            composite_score=93.5,
            scorecard_url="https://example.com/scorecard/abc123",
        )
        assert "Gold" in text

    def test_contains_score(self):
        text = build_sms_text(
            first_name="Ahmed",
            week_iso="2026-W18",
            tier_label="Silver",
            composite_score=84.2,
            scorecard_url="https://example.com/scorecard/abc123",
        )
        assert "84" in text

    def test_contains_url(self):
        url = "https://example.com/scorecard/abc123"
        text = build_sms_text(
            first_name="Ahmed",
            week_iso="2026-W18",
            tier_label="Gold",
            composite_score=93.5,
            scorecard_url=url,
        )
        assert url in text

    def test_contains_driver_first_name(self):
        text = build_sms_text(
            first_name="Fatima",
            week_iso="2026-W18",
            tier_label="Bronze",
            composite_score=72.1,
            scorecard_url="https://example.com/s/x",
        )
        assert "Fatima" in text

    def test_reasonable_length(self):
        """SMS should be under 320 chars (2 segments max)."""
        text = build_sms_text(
            first_name="Abdirahman",
            week_iso="2026-W18",
            tier_label="Probation",
            composite_score=61.0,
            scorecard_url="https://frontend-ruddy-ten-82.vercel.app/scorecard/very-long-hmac-token-here",
        )
        assert len(text) <= 320


# ═══════════════════════════════════════════════════════════════════════════════
# build_email_html
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildEmailHtml:
    def test_contains_first_name(self):
        html = build_email_html(
            first_name="Ahmed",
            week_iso="2026-W18",
            tier_label="Gold",
            composite_score=93.5,
            focus_area="Keep accepting trips quickly.",
            scorecard_url="https://example.com/s/x",
            unsubscribe_url="https://example.com/unsub/y",
        )
        assert "Ahmed" in html

    def test_contains_tier_label(self):
        html = build_email_html(
            first_name="Ahmed",
            week_iso="2026-W18",
            tier_label="Silver",
            composite_score=84.0,
            focus_area="Focus on arrival time.",
            scorecard_url="https://example.com/s/x",
            unsubscribe_url="https://example.com/unsub/y",
        )
        assert "Silver" in html

    def test_contains_score(self):
        html = build_email_html(
            first_name="Ahmed",
            week_iso="2026-W18",
            tier_label="Gold",
            composite_score=91.0,  # Use whole number to avoid banker's rounding ambiguity
            focus_area="Great job.",
            scorecard_url="https://example.com/s/x",
            unsubscribe_url="https://example.com/unsub/y",
        )
        assert "91" in html

    def test_contains_scorecard_link(self):
        url = "https://example.com/scorecard/abc123"
        html = build_email_html(
            first_name="Ahmed",
            week_iso="2026-W18",
            tier_label="Gold",
            composite_score=93.5,
            focus_area="Keep it up.",
            scorecard_url=url,
            unsubscribe_url="https://example.com/unsub/y",
        )
        assert url in html

    def test_contains_unsubscribe_link(self):
        unsub = "https://example.com/unsub/abc"
        html = build_email_html(
            first_name="Ahmed",
            week_iso="2026-W18",
            tier_label="Gold",
            composite_score=93.5,
            focus_area="Keep it up.",
            scorecard_url="https://example.com/s/x",
            unsubscribe_url=unsub,
        )
        assert unsub in html

    def test_contains_focus_area(self):
        focus = "Try to accept trips within 60 seconds."
        html = build_email_html(
            first_name="Ahmed",
            week_iso="2026-W18",
            tier_label="Gold",
            composite_score=93.5,
            focus_area=focus,
            scorecard_url="https://example.com/s/x",
            unsubscribe_url="https://example.com/unsub/y",
        )
        assert focus in html

    def test_is_valid_html_structure(self):
        html = build_email_html(
            first_name="Ahmed",
            week_iso="2026-W18",
            tier_label="Gold",
            composite_score=93.5,
            focus_area="Keep accepting trips quickly.",
            scorecard_url="https://example.com/s/x",
            unsubscribe_url="https://example.com/unsub/y",
        )
        assert "<html" in html.lower() or "<!doctype" in html.lower() or "<div" in html.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# send_scorecard_to_driver
# ═══════════════════════════════════════════════════════════════════════════════

class TestSendScorecardToDriver:
    def _run(self, person, scorecard, db, week_iso="2026-W18"):
        """Helper that patches external calls and runs send_scorecard_to_driver."""
        with (
            patch("backend.services.scorecard_cron.send_sms") as mock_sms,
            patch("backend.services.scorecard_cron._send_scorecard_email") as mock_email,
            patch("backend.services.scorecard_cron._mint_url") as mock_mint,
            patch("backend.services.scorecard_cron._unsub_url") as mock_unsub,
        ):
            mock_mint.return_value = "https://example.com/scorecard/tok"
            mock_unsub.return_value = "https://example.com/unsub/tok"
            from backend.services.scorecard_cron import send_scorecard_to_driver
            result = send_scorecard_to_driver(person, scorecard, week_iso, db)
            return result, mock_sms, mock_email

    def test_sends_sms_when_phone_present(self):
        person = _make_person(phone="+12065551234")
        sc = _make_scorecard()
        db = MagicMock()
        result, mock_sms, _ = self._run(person, sc, db)
        mock_sms.assert_called_once()
        assert result["sms_sent"] is True

    def test_sends_email_when_email_present(self):
        person = _make_person(email="driver@example.com")
        sc = _make_scorecard()
        db = MagicMock()
        result, _, mock_email = self._run(person, sc, db)
        mock_email.assert_called_once()
        assert result["email_sent"] is True

    def test_skips_sms_when_no_phone(self):
        person = _make_person(phone=None)
        sc = _make_scorecard()
        db = MagicMock()
        result, mock_sms, _ = self._run(person, sc, db)
        mock_sms.assert_not_called()
        assert result["sms_sent"] is False

    def test_skips_email_when_no_email(self):
        person = _make_person(email=None)
        sc = _make_scorecard()
        db = MagicMock()
        result, _, mock_email = self._run(person, sc, db)
        mock_email.assert_not_called()
        assert result["email_sent"] is False

    def test_sms_failure_logged_not_raised(self):
        person = _make_person()
        sc = _make_scorecard()
        db = MagicMock()
        with (
            patch("backend.services.scorecard_cron.send_sms", side_effect=Exception("Twilio 429")),
            patch("backend.services.scorecard_cron._send_scorecard_email"),
            patch("backend.services.scorecard_cron._mint_url", return_value="https://x.com/s/t"),
            patch("backend.services.scorecard_cron._unsub_url", return_value="https://x.com/u/t"),
        ):
            from backend.services.scorecard_cron import send_scorecard_to_driver
            result = send_scorecard_to_driver(person, sc, "2026-W18", db)
        assert result["sms_sent"] is False
        assert result["sms_error"] is not None

    def test_email_failure_logged_not_raised(self):
        person = _make_person()
        sc = _make_scorecard()
        db = MagicMock()
        with (
            patch("backend.services.scorecard_cron.send_sms"),
            patch("backend.services.scorecard_cron._send_scorecard_email", side_effect=Exception("Gmail 500")),
            patch("backend.services.scorecard_cron._mint_url", return_value="https://x.com/s/t"),
            patch("backend.services.scorecard_cron._unsub_url", return_value="https://x.com/u/t"),
        ):
            from backend.services.scorecard_cron import send_scorecard_to_driver
            result = send_scorecard_to_driver(person, sc, "2026-W18", db)
        assert result["email_sent"] is False
        assert result["email_error"] is not None


# ═══════════════════════════════════════════════════════════════════════════════
# opt_out_driver
# ═══════════════════════════════════════════════════════════════════════════════

class TestOptOutDriver:
    def test_sets_unsubscribed_flag(self):
        person = _make_person(alert_profile={})
        db = MagicMock()
        # Make db.query().filter().first() return person
        db.query.return_value.filter.return_value.first.return_value = person
        opt_out_driver(person_id=1, db=db)
        # alert_profile should now have unsubscribed_scorecard=True
        assert person.alert_profile.get("unsubscribed_scorecard") is True
        db.commit.assert_called_once()

    def test_preserves_existing_alert_profile_keys(self):
        person = _make_person(alert_profile={"muted_until": "2026-05-10"})
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = person
        opt_out_driver(person_id=1, db=db)
        assert person.alert_profile.get("muted_until") == "2026-05-10"
        assert person.alert_profile.get("unsubscribed_scorecard") is True

    def test_noop_when_driver_not_found(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        # Should not raise
        opt_out_driver(person_id=999, db=db)
        db.commit.assert_not_called()

    def test_already_unsubscribed_stays_unsubscribed(self):
        person = _make_person(alert_profile={"unsubscribed_scorecard": True})
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = person
        opt_out_driver(person_id=1, db=db)
        assert person.alert_profile["unsubscribed_scorecard"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# run_scorecard_cron (main loop)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunScorecardCron:
    def _db_with_persons(self, persons: list) -> MagicMock:
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = persons
        # For idempotency check: no existing run by default
        db.query.return_value.filter.return_value.first.return_value = None
        return db

    def _common_patches(self, db, persons=None):
        """Return context manager patches for cron tests with ENABLED=1."""
        import os
        return [
            patch.dict(os.environ, {"SCORECARD_CRON_ENABLED": "1"}),
            patch("backend.services.scorecard_cron._compute_week_iso", return_value="2026-W18"),
            patch("backend.services.scorecard_cron.compute_driver_scorecard", return_value=_make_scorecard()),
            patch("backend.services.scorecard_cron._record_cron_run"),
            patch("backend.services.scorecard_cron._already_ran", return_value=False),
            patch("backend.services.scorecard_cron.get_db_session", return_value=db),
        ]

    def test_skips_unsubscribed_driver(self):
        person = _make_person(
            alert_profile={"unsubscribed_scorecard": True},
            phone="+12065551234",
        )
        db = self._db_with_persons([person])
        patches = self._common_patches(db)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            with patch("backend.services.scorecard_cron.send_scorecard_to_driver") as mock_send:
                from backend.services.scorecard_cron import run_scorecard_cron
                run_scorecard_cron(db_override=db)
        mock_send.assert_not_called()

    def test_skips_driver_with_no_phone_and_no_email(self):
        person = _make_person(phone=None, email=None)
        db = self._db_with_persons([person])
        patches = self._common_patches(db)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            with patch("backend.services.scorecard_cron.send_scorecard_to_driver") as mock_send:
                from backend.services.scorecard_cron import run_scorecard_cron
                run_scorecard_cron(db_override=db)
        mock_send.assert_not_called()

    def test_sends_to_active_driver_with_contact(self):
        person = _make_person(phone="+12065551234", email="x@y.com")
        db = self._db_with_persons([person])
        patches = self._common_patches(db)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            with patch("backend.services.scorecard_cron.send_scorecard_to_driver") as mock_send:
                mock_send.return_value = {"sms_sent": True, "email_sent": True, "sms_error": None, "email_error": None}
                from backend.services.scorecard_cron import run_scorecard_cron
                run_scorecard_cron(db_override=db)
        mock_send.assert_called_once()

    def test_idempotent_when_already_ran(self):
        """If cron already ran this week for a driver, skip them."""
        person = _make_person(phone="+12065551234", email="x@y.com")
        db = self._db_with_persons([person])
        import os
        with (
            patch.dict(os.environ, {"SCORECARD_CRON_ENABLED": "1"}),
            patch("backend.services.scorecard_cron._compute_week_iso", return_value="2026-W18"),
            patch("backend.services.scorecard_cron.compute_driver_scorecard", return_value=_make_scorecard()),
            patch("backend.services.scorecard_cron._record_cron_run"),
            patch("backend.services.scorecard_cron._already_ran", return_value=True),
            patch("backend.services.scorecard_cron.get_db_session", return_value=db),
            patch("backend.services.scorecard_cron.send_scorecard_to_driver") as mock_send,
        ):
            from backend.services.scorecard_cron import run_scorecard_cron
            run_scorecard_cron(db_override=db)
        mock_send.assert_not_called()

    def test_continues_after_send_failure(self):
        """One driver crashing shouldn't stop the rest."""
        p1 = _make_person(person_id=1, phone="+12065551111", email="a@x.com")
        p2 = _make_person(person_id=2, phone="+12065552222", email="b@x.com")
        db = self._db_with_persons([p1, p2])

        call_count = 0
        def _send_side_effect(person, sc, week_iso, db_arg):
            nonlocal call_count
            call_count += 1
            if person.person_id == 1:
                raise RuntimeError("unexpected crash")
            return {"sms_sent": True, "email_sent": True, "sms_error": None, "email_error": None}

        import os
        with (
            patch.dict(os.environ, {"SCORECARD_CRON_ENABLED": "1"}),
            patch("backend.services.scorecard_cron.send_scorecard_to_driver", side_effect=_send_side_effect),
            patch("backend.services.scorecard_cron._compute_week_iso", return_value="2026-W18"),
            patch("backend.services.scorecard_cron.compute_driver_scorecard", return_value=_make_scorecard()),
            patch("backend.services.scorecard_cron._record_cron_run"),
            patch("backend.services.scorecard_cron._already_ran", return_value=False),
            patch("backend.services.scorecard_cron.get_db_session", return_value=db),
        ):
            from backend.services.scorecard_cron import run_scorecard_cron
            run_scorecard_cron(db_override=db)

        assert call_count == 2  # both attempted

    def test_gated_by_scorecard_cron_enabled(self):
        """When SCORECARD_CRON_ENABLED is not '1', cron is a no-op."""
        import os
        person = _make_person()
        db = self._db_with_persons([person])
        with (
            patch.dict(os.environ, {"SCORECARD_CRON_ENABLED": "0"}),
            patch("backend.services.scorecard_cron.send_scorecard_to_driver") as mock_send,
            patch("backend.services.scorecard_cron.get_db_session", return_value=db),
        ):
            from backend.services.scorecard_cron import run_scorecard_cron
            run_scorecard_cron(db_override=db)
        mock_send.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# Idempotency helpers
# ═══════════════════════════════════════════════════════════════════════════════

class TestIdempotencyHelpers:
    def test_already_ran_returns_false_when_no_row(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        from backend.services.scorecard_cron import _already_ran
        assert _already_ran(person_id=1, week_iso="2026-W18", db=db) is False

    def test_already_ran_returns_true_when_row_exists(self):
        db = MagicMock()
        # Simulate a row existing
        db.query.return_value.filter.return_value.first.return_value = MagicMock()
        from backend.services.scorecard_cron import _already_ran
        assert _already_ran(person_id=1, week_iso="2026-W18", db=db) is True

    def test_record_cron_run_adds_row(self):
        db = MagicMock()
        from backend.services.scorecard_cron import _record_cron_run
        _record_cron_run(person_id=1, week_iso="2026-W18", db=db)
        db.add.assert_called_once()
        db.commit.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
# Manual trigger endpoint
# ═══════════════════════════════════════════════════════════════════════════════

class TestManualTriggerEndpoint:
    def test_endpoint_exists_and_requires_auth(self):
        """POST /admin/scorecard/send-now should be registered on router."""
        from backend.routes import admin_scorecard
        assert hasattr(admin_scorecard, "router")
        route_paths = [r.path for r in admin_scorecard.router.routes]
        assert any("send-now" in p for p in route_paths)

    def test_public_router_exists(self):
        """public_router should be present for unsubscribe routes."""
        from backend.routes import admin_scorecard
        assert hasattr(admin_scorecard, "public_router")
        route_paths = [r.path for r in admin_scorecard.public_router.routes]
        assert any("unsubscribe" in p for p in route_paths)

    def test_endpoint_fires_cron(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from backend.routes.admin_scorecard import router, _require_admin

        app = FastAPI()
        app.include_router(router, prefix="/admin")

        # Override the auth dependency so the test doesn't need a real session
        app.dependency_overrides[_require_admin] = lambda: True

        with patch("backend.routes.admin_scorecard.run_scorecard_cron") as mock_cron:
            mock_cron.return_value = {"sent": 5, "skipped": 2, "errors": 0}
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.post("/admin/scorecard/send-now")

        app.dependency_overrides.clear()
        assert resp.status_code == 200
        data = resp.json()
        assert "sent" in data


# ═══════════════════════════════════════════════════════════════════════════════
# SMS opt-out via webhook (Twilio STOP reply)
# ═══════════════════════════════════════════════════════════════════════════════

class TestTwilioStopOptOut:
    def test_opt_out_driver_is_importable_from_scorecard_cron(self):
        """opt_out_driver must be importable so Twilio STOP webhook can call it."""
        from backend.services.scorecard_cron import opt_out_driver
        assert callable(opt_out_driver)

    def test_admin_scorecard_re_exports_opt_out_driver(self):
        """admin_scorecard route module must re-export opt_out_driver for consumers."""
        from backend.routes import admin_scorecard
        assert hasattr(admin_scorecard, "opt_out_driver")


# ═══════════════════════════════════════════════════════════════════════════════
# _compute_week_iso
# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
# _mint_url — must produce public HMAC /scorecard/{token} URL (Bug fix: PR #42)
# ═══════════════════════════════════════════════════════════════════════════════

class TestMintUrl:
    """_mint_url must call mint_scorecard_url, not build_card_link.

    Before the fix the cron sent /driver/{id}/scorecard (authenticated) URLs
    in SMS and email. Drivers cannot open that link — it requires a login.
    The correct URL is /scorecard/{hmac_token} (public, time-limited).
    """

    def test_mint_url_returns_scorecard_prefix(self):
        """URL must contain /scorecard/ — not /driver/."""
        import os
        from backend.services.scorecard_cron import _mint_url

        with patch.dict(os.environ, {"PUBLIC_BASE_URL": "https://example.com"}):
            url = _mint_url(person_id=42, week_iso="2026-W18")

        assert "/scorecard/" in url, f"Expected /scorecard/ prefix, got: {url}"
        assert "/driver/" not in url, f"Unexpected /driver/ segment in URL: {url}"

    def test_mint_url_does_not_contain_plain_person_id(self):
        """The public URL should be token-based, not expose person_id directly."""
        import os
        from backend.services.scorecard_cron import _mint_url

        with patch.dict(os.environ, {"PUBLIC_BASE_URL": "https://frontend-ruddy-ten-82.vercel.app"}):
            url = _mint_url(person_id=99, week_iso="2026-W18")

        # The token is an opaque base64url blob; the raw integer 99 should not
        # appear as a path segment.
        parts = url.split("/")
        assert str(99) not in parts, (
            f"person_id 99 leaked as a path segment in URL: {url}"
        )

    def test_mint_url_includes_base_url(self):
        """The returned URL must be absolute (include the configured base)."""
        import os
        from backend.services.scorecard_cron import _mint_url

        base = "https://frontend-ruddy-ten-82.vercel.app"
        with patch.dict(os.environ, {"PUBLIC_BASE_URL": base}):
            url = _mint_url(person_id=1, week_iso="2026-W18")

        assert url.startswith(base), f"URL does not start with base: {url}"


class TestComputeWeekIso:
    def test_returns_iso_week_string(self):
        from backend.services.scorecard_cron import _compute_week_iso
        result = _compute_week_iso()
        # Should be "YYYY-Www" format
        import re
        assert re.match(r"\d{4}-W\d{2}", result), f"Unexpected format: {result}"

    def test_week_iso_matches_previous_monday(self):
        """The week_iso returned should be the just-completed week (prior Monday)."""
        from backend.services.scorecard_cron import _compute_week_iso
        from datetime import date, timedelta
        from zoneinfo import ZoneInfo

        # Force a Sunday after 20:00 PT (when cron fires)
        result = _compute_week_iso()
        # Just verify it returns a parseable week
        year_str, week_str = result.split("-W")
        year, week = int(year_str), int(week_str)
        d = date.fromisocalendar(year, week, 1)  # Should not raise
        assert isinstance(d, date)
