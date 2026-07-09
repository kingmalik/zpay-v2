"""
Phase 2 dispatch operator-override endpoints.

  POST /dispatch/notifications/{id}/snooze    — snooze escalation for N minutes
  POST /dispatch/notifications/{id}/resolve   — manually resolve (stop escalation)
  GET  /dispatch/notifications/{id}/events    — audit event log for one notification
  POST /dispatch/persons/{id}/mute            — mute admin alerts for a driver
  POST /dispatch/persons/{id}/unmute          — clear mute for a driver
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import NotificationEvent, Person, TripNotification

router = APIRouter(prefix="/dispatch", tags=["dispatch-overrides"])

# ---------------------------------------------------------------------------
# Pydantic request bodies
# ---------------------------------------------------------------------------


class SnoozeBody(BaseModel):
    minutes: int = Field(..., ge=1, le=1440, description="Minutes to snooze (1–1440)")


class MuteBody(BaseModel):
    minutes: int = Field(..., ge=1, le=10080, description="Minutes to mute (1–10080 = 1 week)")
    reason: str = Field("", max_length=200, description="Optional human note shown in the UI")


VALID_DISPOSITIONS = ("answered", "no_answer", "ghosted", "wrong_number")


class DispositionBody(BaseModel):
    disposition: str = Field(..., description="One of: answered, no_answer, ghosted, wrong_number")
    note: str = Field("", max_length=200, description="Optional note (e.g. 'said he's 5 min out')")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _write_event(
    db: Session,
    trip_notification_id: int,
    event_type: str,
    payload: Optional[dict] = None,
    created_by_person_id: Optional[int] = None,
) -> NotificationEvent:
    """Insert one notification_event row and flush (caller commits)."""
    ev = NotificationEvent(
        trip_notification_id=trip_notification_id,
        event_type=event_type,
        payload=payload,
        created_by_person_id=created_by_person_id,
    )
    db.add(ev)
    db.flush()
    return ev


def _notif_or_404(db: Session, notif_id: int) -> TripNotification:
    notif = db.query(TripNotification).filter(TripNotification.id == notif_id).first()
    if not notif:
        raise HTTPException(status_code=404, detail=f"TripNotification {notif_id} not found")
    return notif


def _person_or_404(db: Session, person_id: int) -> Person:
    person = db.query(Person).filter(Person.person_id == person_id).first()
    if not person:
        raise HTTPException(status_code=404, detail=f"Person {person_id} not found")
    return person


def _notif_to_dict(notif: TripNotification) -> dict:
    return {
        "id": notif.id,
        "person_id": notif.person_id,
        "trip_ref": notif.trip_ref,
        "source": notif.source,
        "pickup_time": notif.pickup_time,
        "trip_status": notif.trip_status,
        "snoozed_until": notif.snoozed_until.isoformat() if notif.snoozed_until else None,
        "manually_resolved_at": (
            notif.manually_resolved_at.isoformat() if notif.manually_resolved_at else None
        ),
        "manually_resolved_by": notif.manually_resolved_by,
        "last_escalated_at": (
            notif.last_escalated_at.isoformat() if notif.last_escalated_at else None
        ),
        "dedup_suppressed": notif.dedup_suppressed,
        "dedup_primary_notif_id": notif.dedup_primary_notif_id,
    }


# ---------------------------------------------------------------------------
# Notification endpoints
# ---------------------------------------------------------------------------


@router.post("/notifications/{notif_id}/snooze")
async def snooze_notification(
    notif_id: int,
    body: SnoozeBody,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Set snoozed_until = now + minutes. Monitor skips re-escalation until then."""
    notif = _notif_or_404(db, notif_id)

    if notif.manually_resolved_at:
        raise HTTPException(status_code=409, detail="Notification is already resolved")

    now = datetime.now(timezone.utc)
    notif.snoozed_until = now + timedelta(minutes=body.minutes)

    _write_event(
        db,
        notif.id,
        "snoozed",
        {"minutes": body.minutes, "snoozed_until": notif.snoozed_until.isoformat()},
    )
    db.commit()
    db.refresh(notif)
    return JSONResponse({"ok": True, "notification": _notif_to_dict(notif)})


@router.post("/notifications/{notif_id}/resolve")
async def resolve_notification(
    notif_id: int,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Mark notification as manually resolved. Stops all further escalation."""
    notif = _notif_or_404(db, notif_id)

    if notif.manually_resolved_at:
        # Idempotent — already resolved, just return current state
        return JSONResponse({"ok": True, "already_resolved": True, "notification": _notif_to_dict(notif)})

    now = datetime.now(timezone.utc)
    notif.manually_resolved_at = now

    _write_event(db, notif.id, "manually_resolved", {"resolved_at": now.isoformat()})
    db.commit()
    db.refresh(notif)
    return JSONResponse({"ok": True, "notification": _notif_to_dict(notif)})


@router.post("/notifications/{notif_id}/disposition")
async def record_call_disposition(
    notif_id: int,
    body: DispositionBody,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Record the outcome of the dispatcher's manual call — one tap on the card.

    S2 exception-queue feature: 'answered' / 'no_answer' / 'ghosted' /
    'wrong_number'. Writes an immutable notification_event row; 'ghosted'
    feeds the chronic-tier signal, 'wrong_number' is a People-page data flag.
    Does NOT stop escalation — pair with /resolve or /snooze for that.
    """
    if body.disposition not in VALID_DISPOSITIONS:
        raise HTTPException(
            status_code=422,
            detail=f"disposition must be one of {', '.join(VALID_DISPOSITIONS)}",
        )

    notif = _notif_or_404(db, notif_id)

    ev = _write_event(
        db,
        notif.id,
        "call_disposition",
        {"disposition": body.disposition, "note": body.note or None},
    )
    db.commit()
    return JSONResponse({
        "ok": True,
        "event_id": ev.id,
        "disposition": body.disposition,
        "notification": _notif_to_dict(notif),
    })


@router.get("/notifications/{notif_id}/events")
async def list_notification_events(
    notif_id: int,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Return the audit event log for a single trip notification."""
    # 404 if the notification doesn't exist
    _notif_or_404(db, notif_id)

    events = (
        db.query(NotificationEvent)
        .filter(NotificationEvent.trip_notification_id == notif_id)
        .order_by(NotificationEvent.created_at.asc())
        .all()
    )
    return JSONResponse({
        "notif_id": notif_id,
        "events": [
            {
                "id": ev.id,
                "event_type": ev.event_type,
                "payload": ev.payload,
                "created_at": ev.created_at.isoformat() if ev.created_at else None,
                "created_by_person_id": ev.created_by_person_id,
            }
            for ev in events
        ],
    })


# ---------------------------------------------------------------------------
# Driver mute endpoints
# ---------------------------------------------------------------------------


@router.post("/persons/{person_id}/mute")
async def mute_driver(
    person_id: int,
    body: MuteBody,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Mute admin alert escalations for a driver for N minutes.

    Driver-facing SMS and calls are not affected — only the admin call/text
    that fires when the driver hasn't responded is suppressed.
    """
    person = _person_or_404(db, person_id)

    now = datetime.now(timezone.utc)
    muted_until = now + timedelta(minutes=body.minutes)

    person.alert_profile = {
        "muted_until": muted_until.isoformat(),
        "muted_reason": body.reason or None,
    }

    # Log against the most-recent active notification for this driver today, if any.
    # Falls back to the first notif found so the event is always anchored.
    from datetime import date as _date
    today = now.date()
    recent_notif = (
        db.query(TripNotification)
        .filter(
            TripNotification.person_id == person_id,
            TripNotification.trip_date == today,
        )
        .order_by(TripNotification.id.desc())
        .first()
    )

    if recent_notif:
        _write_event(
            db,
            recent_notif.id,
            "mute",
            {
                "minutes": body.minutes,
                "muted_until": muted_until.isoformat(),
                "reason": body.reason or None,
            },
        )

    db.commit()

    return JSONResponse({
        "ok": True,
        "person_id": person_id,
        "muted_until": muted_until.isoformat(),
        "muted_reason": body.reason or None,
    })


@router.post("/persons/{person_id}/unmute")
async def unmute_driver(
    person_id: int,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Clear the mute on a driver — admin alerts resume immediately."""
    person = _person_or_404(db, person_id)

    was_muted = bool(person.alert_profile and person.alert_profile.get("muted_until"))
    person.alert_profile = None

    if was_muted:
        from datetime import date as _date
        today = datetime.now(timezone.utc).date()
        recent_notif = (
            db.query(TripNotification)
            .filter(
                TripNotification.person_id == person_id,
                TripNotification.trip_date == today,
            )
            .order_by(TripNotification.id.desc())
            .first()
        )
        if recent_notif:
            _write_event(db, recent_notif.id, "unmuted", {"cleared_at": datetime.now(timezone.utc).isoformat()})

    db.commit()
    return JSONResponse({"ok": True, "person_id": person_id, "was_muted": was_muted})
