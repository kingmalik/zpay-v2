"""
Twilio <Gather> webhook — Phase 3 (#14).

When Z-Pay calls Malik and he presses a digit, Twilio POSTs here.
The query param `notif_id` identifies which TripNotification to act on.

Keypad actions:
  1 — Mark trip handled (sets manually_resolved_at, stops all future escalation)
  2 — Mute this driver's admin alerts until end of today (Pacific)
  9 — Snooze ALL active trip alerts for 30 minutes

The response is always a <Response><Say>...</Say></Response> TwiML so Malik
hears confirmation before the call ends.

Registration: POST /api/twilio/voice-gather
              POST /api/twilio/voice-gather/fallback  (Twilio no-input timeout)

Security note: Twilio-signed requests are verified via X-Twilio-Signature when
TWILIO_AUTH_TOKEN is set. The endpoint is otherwise publicly reachable (Twilio
cannot send cookies / JWT), so we validate origin via signature only.

Validation is skipped in test mode (MONITOR_DRY_RUN=1) to allow unit tests
to call the endpoint without valid Twilio credentials.
"""

from __future__ import annotations

import logging
import os
import xml.sax.saxutils
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import NotificationEvent, Person, TripNotification

logger = logging.getLogger("zpay.twilio_gather")

router = APIRouter(prefix="/api/twilio", tags=["twilio"])

_DRY_RUN = os.environ.get("MONITOR_DRY_RUN", "0").lower().strip() in ("1", "true", "yes")

# ── TwiML helpers ─────────────────────────────────────────────────────────────

def _twiml_say(message: str) -> Response:
    """Wrap a message in TwiML <Say> and return it as a text/xml response."""
    safe = xml.sax.saxutils.escape(message)
    twiml = (
        "<Response>"
        f'<Say voice="Polly.Matthew" language="en-US">{safe}</Say>'
        "</Response>"
    )
    return Response(content=twiml, media_type="text/xml")


# ── Twilio signature verification ─────────────────────────────────────────────

def _verify_twilio_signature(request: Request, form_data: dict) -> bool:
    """Return True if the request carries a valid Twilio signature.

    Skipped entirely in dry-run / test mode.
    """
    if _DRY_RUN:
        return True

    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    if not auth_token:
        logger.warning("[twilio_gather] TWILIO_AUTH_TOKEN not set — skipping signature check")
        return True  # Fail-open: if token is missing we can't verify anyway

    try:
        from twilio.request_validator import RequestValidator  # type: ignore[import]
        validator = RequestValidator(auth_token)

        url = str(request.url)
        sig = request.headers.get("X-Twilio-Signature", "")
        return validator.validate(url, form_data, sig)
    except Exception as exc:
        logger.warning("[twilio_gather] Signature verification error: %s", exc)
        return False


# ── Audit helper ──────────────────────────────────────────────────────────────

def _write_gather_event(
    db: Session,
    notif_id: int,
    event_type: str,
    digit: str,
    payload: dict | None = None,
) -> None:
    ev = NotificationEvent(
        trip_notification_id=notif_id,
        event_type=event_type,
        payload={**(payload or {}), "digit": digit, "channel": "voice_gather"},
    )
    db.add(ev)
    db.flush()


# ── Main gather endpoint ──────────────────────────────────────────────────────

@router.post("/voice-gather")
async def voice_gather(
    request: Request,
    notif_id: int = Query(..., description="TripNotification.id the call was about"),
    db: Session = Depends(get_db),
) -> Response:
    """
    Handle digit press from Twilio <Gather>.

    Twilio POSTs the form-encoded body with `Digits` field.
    """
    form = dict(await request.form())
    digit = str(form.get("Digits", "")).strip()

    # Signature check
    if not _verify_twilio_signature(request, form):
        logger.warning("[twilio_gather] Invalid Twilio signature — rejecting")
        return _twiml_say("Verification failed. Goodbye.")

    notif = db.query(TripNotification).filter(TripNotification.id == notif_id).first()
    if not notif:
        logger.warning("[twilio_gather] notif_id=%d not found", notif_id)
        return _twiml_say("Trip not found. Goodbye.")

    now_utc = datetime.now(timezone.utc)

    if digit == "1":
        # Mark trip handled — stops all further escalation
        if not notif.manually_resolved_at:
            notif.manually_resolved_at = now_utc
            _write_gather_event(db, notif_id, "manually_resolved", digit,
                                {"source": "voice_gather_press_1"})
            db.commit()
            logger.info("[twilio_gather] notif=%d marked handled via press-1", notif_id)
        return _twiml_say(
            "Got it. This trip has been marked as handled. "
            "You will not be called again for it."
        )

    if digit == "2":
        # Mute this driver's admin alerts until midnight Pacific
        person = db.query(Person).filter(Person.person_id == notif.person_id).first()
        if person is None:
            return _twiml_say("Driver not found. Goodbye.")

        from zoneinfo import ZoneInfo
        tz_name = os.environ.get("MONITOR_TIMEZONE", "America/Los_Angeles")
        tz = ZoneInfo(tz_name)
        now_local = datetime.now(tz)
        # End-of-day = midnight tonight in the monitor timezone
        midnight_local = (now_local + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        mute_until_utc = midnight_local.astimezone(timezone.utc)

        profile = dict(person.alert_profile or {})
        profile["muted_until"] = mute_until_utc.isoformat()
        profile["muted_reason"] = "voice_gather_press_2"
        person.alert_profile = profile

        _write_gather_event(db, notif_id, "muted", digit, {
            "muted_until": mute_until_utc.isoformat(),
            "person_id": notif.person_id,
        })
        db.commit()

        driver_first = ((person.full_name or "Driver").split()[0]).title()
        logger.info(
            "[twilio_gather] driver person_id=%d muted until %s via press-2",
            notif.person_id, mute_until_utc.isoformat(),
        )
        return _twiml_say(
            f"{driver_first}'s admin alerts have been muted until midnight tonight. "
            "You will not be called about this driver for the rest of today."
        )

    if digit == "9":
        # Snooze ALL active (non-resolved) trips for 30 minutes
        snooze_until = now_utc + timedelta(minutes=30)
        today_date = datetime.now(timezone.utc).date()

        active_notifs = (
            db.query(TripNotification)
            .filter(
                TripNotification.trip_date == today_date,
                TripNotification.manually_resolved_at.is_(None),
            )
            .all()
        )
        snoozed_count = 0
        for n in active_notifs:
            # Only extend — don't shorten an existing longer snooze
            if n.snoozed_until is None or n.snoozed_until < snooze_until:
                n.snoozed_until = snooze_until
                snoozed_count += 1
                _write_gather_event(db, n.id, "snoozed", digit, {
                    "snooze_until": snooze_until.isoformat(),
                    "source": "voice_gather_press_9_bulk",
                })

        db.commit()
        logger.info(
            "[twilio_gather] bulk snooze 30min via press-9 — %d trips snoozed until %s",
            snoozed_count, snooze_until.isoformat(),
        )
        return _twiml_say(
            f"All {snoozed_count} active trips have been snoozed for 30 minutes. "
            "You will not be called again until then."
        )

    # Unknown digit or no-input
    logger.info("[twilio_gather] unrecognized digit=%r for notif=%d", digit, notif_id)
    return _twiml_say(
        "I did not recognize that input. "
        "Press 1 to mark this trip handled, "
        "press 2 to mute this driver, "
        "or press 9 to snooze all alerts for 30 minutes."
    )


@router.post("/voice-gather/fallback")
async def voice_gather_fallback(request: Request) -> Response:
    """Called by Twilio when the gather times out (no digit pressed)."""
    return _twiml_say(
        "No input received. Your alerts remain active. Goodbye."
    )
