"""
Ops Dashboard routes — unified live ops aggregation endpoint.

Prefix: /api/data/ops-dashboard (registered in app.py)
All responses are JSON, consumed by the Next.js /ops page.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta, date as _date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from backend.db import get_db, SessionLocal
from backend.db.models import (
    NotificationEvent,
    OpsEventLog,
    Person,
    TripNotification,
)

_logger = logging.getLogger("zpay.ops-dashboard")

router = APIRouter(prefix="/ops-dashboard", tags=["ops-dashboard"])

# ── In-memory pause flag ───────────────────────────────────────────────────────
# Simple process-level flag — single Railway instance, so this is safe.
_monitor_paused: bool = False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_dt(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _partner_health_from_db() -> dict:
    """
    Derive FA and ED partner health from the health_check table.
    Returns green/yellow/red for each partner plus last_ok_at.
    Falls back to 'unknown' if the table is absent or checks missing.
    """
    try:
        with SessionLocal() as db:
            rows = db.execute(
                text("""
                    SELECT check_name, status, last_ok_at, consecutive_failures
                    FROM health_check
                    WHERE check_name IN ('firstalt_freshness', 'everdriven_freshness')
                """)
            ).fetchall()
            data: dict[str, dict] = {}
            for row in rows:
                check_name, status, last_ok_at, consec = row
                data[check_name] = {
                    "status": status or "unknown",
                    "last_contact_at": last_ok_at.isoformat() if last_ok_at else None,
                    "consecutive_failures": int(consec or 0),
                }
            return {
                "fa": data.get("firstalt_freshness", {"status": "unknown", "last_contact_at": None, "consecutive_failures": 0}),
                "ed": data.get("everdriven_freshness", {"status": "unknown", "last_contact_at": None, "consecutive_failures": 0}),
            }
    except Exception as exc:
        _logger.warning("partner_health_from_db failed: %s", exc)
        return {
            "fa": {"status": "unknown", "last_contact_at": None, "consecutive_failures": 0},
            "ed": {"status": "unknown", "last_contact_at": None, "consecutive_failures": 0},
        }


def _scheduler_liveness() -> dict:
    """
    Derive scheduler liveness from trip_monitor in-memory state.
    is_stale = True if last cycle > 15 min ago.
    """
    try:
        from backend.services.trip_monitor import get_status, _HOT_INTERVAL_SECONDS, _COLD_INTERVAL_SECONDS, _ADAPTIVE_CADENCE
        status = get_status()
        last_run_str = status.get("last_run")
        now = datetime.now(timezone.utc)
        is_stale = False
        next_cycle_in_seconds: int | None = None

        if last_run_str:
            try:
                last_run_dt = datetime.fromisoformat(last_run_str)
                if last_run_dt.tzinfo is None:
                    last_run_dt = last_run_dt.replace(tzinfo=timezone.utc)
                age_seconds = (now - last_run_dt).total_seconds()
                is_stale = age_seconds > 15 * 60

                # Estimate next cycle based on adaptive vs legacy mode
                if _ADAPTIVE_CADENCE:
                    interval_s = _HOT_INTERVAL_SECONDS
                else:
                    interval_minutes = int(os.environ.get("MONITOR_INTERVAL_MINUTES", "5"))
                    interval_s = interval_minutes * 60

                next_cycle_in_seconds = max(0, int(interval_s - age_seconds))
            except Exception:
                pass
        else:
            is_stale = bool(status.get("enabled"))

        return {
            "last_cycle_at": last_run_str,
            "next_cycle_in_seconds": next_cycle_in_seconds,
            "is_stale": is_stale,
            "enabled": status.get("enabled", False),
        }
    except Exception as exc:
        _logger.warning("scheduler_liveness failed: %s", exc)
        return {
            "last_cycle_at": None,
            "next_cycle_in_seconds": None,
            "is_stale": False,
            "enabled": False,
        }


def _live_trips(db: Session) -> list[dict]:
    """
    Return unaccepted + accepted-but-not-started trips for today,
    sorted by pickup_time ascending (urgency order).
    Red-flagged when pickup < 15 min away and not accepted.
    """
    from zoneinfo import ZoneInfo
    tz_name = os.environ.get("MONITOR_TIMEZONE", "America/Los_Angeles")
    tz = ZoneInfo(tz_name)
    now_local = datetime.now(tz)
    today = now_local.date()

    notifs_persons = (
        db.query(TripNotification, Person)
        .join(Person, Person.person_id == TripNotification.person_id)
        .filter(
            TripNotification.trip_date == today,
            TripNotification.manually_resolved_at.is_(None),
            TripNotification.dedup_suppressed.is_(False),
        )
        .order_by(TripNotification.pickup_time.asc())
        .all()
    )

    trips: list[dict] = []
    for notif, person in notifs_persons:
        is_accepted = notif.accepted_at is not None
        is_started = notif.started_at is not None

        # Skip completed / fully started / snoozed trips
        if is_started:
            continue

        # Compute urgency: minutes until pickup
        minutes_until: int | None = None
        is_urgent = False
        if notif.pickup_time:
            try:
                # pickup_time is stored as "HH:MM" or "HH:MM:SS" string
                parts = notif.pickup_time.strip().split(":")
                pickup_hour = int(parts[0])
                pickup_min = int(parts[1]) if len(parts) > 1 else 0
                pickup_dt = now_local.replace(
                    hour=pickup_hour, minute=pickup_min, second=0, microsecond=0
                )
                delta = (pickup_dt - now_local).total_seconds() / 60
                minutes_until = int(delta)
                is_urgent = (not is_accepted) and minutes_until < 15
            except Exception:
                pass

        state = "unaccepted" if not is_accepted else "accepted_not_started"

        trips.append({
            "notif_id": notif.id,
            "driver": person.full_name,
            "person_id": person.person_id,
            "source": notif.source,
            "trip_ref": notif.trip_ref,
            "pickup_time": notif.pickup_time or "",
            "minutes_until_pickup": minutes_until,
            "state": state,
            "trip_status": notif.trip_status or "",
            "is_urgent": is_urgent,
            "accepted_at": _format_dt(notif.accepted_at),
            "snoozed_until": _format_dt(getattr(notif, "snoozed_until", None)),
            "dispatch_severity": getattr(notif, "dispatch_severity", "normal"),
            "escalated_at": _format_dt(notif.accept_escalated_at or notif.start_escalated_at),
        })

    # Sort urgent (unaccepted + imminent) first, then by minutes_until ascending
    def sort_key(t: dict) -> tuple:
        urgent = 0 if t["is_urgent"] else 1
        mins = t["minutes_until_pickup"] if t["minutes_until_pickup"] is not None else 9999
        return (urgent, mins)

    trips.sort(key=sort_key)
    return trips


def _alerts_feed(db: Session) -> list[dict]:
    """
    Return NotificationEvent rows from the last 60 minutes,
    enriched with driver name and source.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=60)

    rows = (
        db.query(NotificationEvent, TripNotification, Person)
        .join(TripNotification, TripNotification.id == NotificationEvent.trip_notification_id)
        .join(Person, Person.person_id == TripNotification.person_id)
        .filter(NotificationEvent.created_at >= cutoff)
        .order_by(NotificationEvent.created_at.desc())
        .limit(200)
        .all()
    )

    feed: list[dict] = []
    for ev, notif, person in rows:
        payload = ev.payload or {}
        # Derive channel from event_type
        event_type = ev.event_type or ""
        if "sms" in event_type or "whatsapp" in event_type:
            channel = "sms"
        elif "call" in event_type or "voice" in event_type:
            channel = "call"
        elif "discord" in event_type or "escalat" in event_type:
            channel = "discord"
        else:
            channel = "system"

        # Derive status from payload or event type
        if "delivered" in event_type:
            status = "delivered"
        elif "failed" in event_type:
            status = "failed"
        elif "mute" in event_type or "snooze" in event_type or "resolve" in event_type:
            status = "operator"
        else:
            status = "sent"

        feed.append({
            "event_id": ev.id,
            "created_at": _format_dt(ev.created_at),
            "driver": person.full_name,
            "person_id": person.person_id,
            "trip_ref": notif.trip_ref,
            "source": notif.source,
            "event_type": event_type,
            "channel": channel,
            "status": status,
            "payload_summary": {k: v for k, v in payload.items() if k in ("sid", "to", "error", "muted_until", "reason")},
        })

    return feed


def _driver_concurrency(db: Session) -> list[dict]:
    """
    Return drivers who have more than 1 active trip right now.
    Active = accepted but not started, for today.
    """
    from zoneinfo import ZoneInfo
    tz_name = os.environ.get("MONITOR_TIMEZONE", "America/Los_Angeles")
    tz = ZoneInfo(tz_name)
    today = datetime.now(tz).date()

    # Count accepted-not-started trips per person
    counts = (
        db.query(TripNotification.person_id, func.count(TripNotification.id).label("active_count"))
        .filter(
            TripNotification.trip_date == today,
            TripNotification.accepted_at.isnot(None),
            TripNotification.started_at.is_(None),
            TripNotification.manually_resolved_at.is_(None),
        )
        .group_by(TripNotification.person_id)
        .having(func.count(TripNotification.id) >= 1)
        .all()
    )

    if not counts:
        return []

    person_ids = [row.person_id for row in counts]
    persons = (
        db.query(Person)
        .filter(Person.person_id.in_(person_ids))
        .all()
    )
    person_map = {p.person_id: p.full_name for p in persons}

    result: list[dict] = []
    for row in counts:
        result.append({
            "person_id": row.person_id,
            "driver": person_map.get(row.person_id, f"Driver #{row.person_id}"),
            "active_trips": row.active_count,
            "flagged": row.active_count > 2,
        })

    result.sort(key=lambda r: r["active_trips"], reverse=True)
    return result


# ── GET /ops-dashboard/dashboard ──────────────────────────────────────────────

@router.get("/dashboard")
def ops_dashboard(db: Session = Depends(get_db)) -> JSONResponse:
    """Single aggregation endpoint for the /ops page."""
    now = datetime.now(timezone.utc)

    try:
        live_trips = _live_trips(db)
    except Exception as exc:
        _logger.error("ops_dashboard: live_trips failed: %s", exc)
        live_trips = []

    try:
        alerts = _alerts_feed(db)
    except Exception as exc:
        _logger.error("ops_dashboard: alerts_feed failed: %s", exc)
        alerts = []

    try:
        concurrency = _driver_concurrency(db)
    except Exception as exc:
        _logger.error("ops_dashboard: driver_concurrency failed: %s", exc)
        concurrency = []

    partner_health = _partner_health_from_db()
    scheduler = _scheduler_liveness()

    return JSONResponse({
        "live_trips": live_trips,
        "alerts_feed": alerts,
        "driver_concurrency": concurrency,
        "partner_health": partner_health,
        "scheduler_liveness": scheduler,
        "monitor_paused": _monitor_paused,
        "active_trip_count": len(live_trips),
        "generated_at": now.isoformat(),
    })


# ── GET /ops-dashboard/chronic-non-tappers ────────────────────────────────────

@router.get("/chronic-non-tappers")
def chronic_non_tappers(
    week: str | None = None,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Drivers who had accept_sms sent but never accepted (needed escalation)
    more than 5 times this week. Uses TripNotification rows directly.

    week param: ISO week string YYYY-WW (e.g. 2026-18). Defaults to current week.
    """
    from zoneinfo import ZoneInfo
    tz_name = os.environ.get("MONITOR_TIMEZONE", "America/Los_Angeles")
    tz = ZoneInfo(tz_name)
    now_local = datetime.now(tz)

    if week:
        try:
            year_str, week_str = week.split("-")
            year, week_num = int(year_str), int(week_str)
            from datetime import date
            # ISO week Monday
            week_start = date.fromisocalendar(year, week_num, 1)
            week_end = date.fromisocalendar(year, week_num, 7)
        except Exception:
            week_start = now_local.date()
            week_end = now_local.date()
    else:
        # Current ISO week
        iso = now_local.date().isocalendar()
        from datetime import date
        week_start = date.fromisocalendar(iso.year, iso.week, 1)
        week_end = date.fromisocalendar(iso.year, iso.week, 7)

    # Drivers who had accept_sms_at set but never accepted (chronic non-tappers)
    rows = (
        db.query(
            TripNotification.person_id,
            func.count(TripNotification.id).label("non_tap_count"),
        )
        .filter(
            TripNotification.trip_date >= week_start,
            TripNotification.trip_date <= week_end,
            TripNotification.accept_sms_at.isnot(None),
            TripNotification.accepted_at.is_(None),
        )
        .group_by(TripNotification.person_id)
        .having(func.count(TripNotification.id) > 5)
        .all()
    )

    if not rows:
        return JSONResponse({"week": f"{week_start.isoformat()}/{week_end.isoformat()}", "offenders": []})

    person_ids = [r.person_id for r in rows]
    persons = db.query(Person).filter(Person.person_id.in_(person_ids)).all()
    person_map = {p.person_id: p.full_name for p in persons}

    offenders = [
        {
            "person_id": r.person_id,
            "driver": person_map.get(r.person_id, f"Driver #{r.person_id}"),
            "non_tap_count": r.non_tap_count,
        }
        for r in sorted(rows, key=lambda x: x.non_tap_count, reverse=True)
    ]

    return JSONResponse({
        "week": f"{week_start.isoformat()}/{week_end.isoformat()}",
        "offenders": offenders,
    })


# ── POST /ops-dashboard/pause-monitor ─────────────────────────────────────────

@router.post("/pause-monitor")
async def pause_monitor() -> JSONResponse:
    """
    Sets an in-memory pause flag. The trip_monitor scheduler continues to
    run its cycle, but this flag can be read by the frontend to indicate
    a soft pause (operator acknowledged).

    For a hard scheduler stop, use POST /dispatch/monitor/toggle.
    """
    global _monitor_paused
    _monitor_paused = True
    _logger.info("ops_dashboard: monitor_paused set to True")
    return JSONResponse({"ok": True, "monitor_paused": True})


# ── POST /ops-dashboard/run-cycle-now ─────────────────────────────────────────

@router.post("/run-cycle-now")
async def run_cycle_now() -> JSONResponse:
    """
    Trigger an immediate trip_monitor cycle.

    STUB: The dispatch/monitor/run-now endpoint already provides this.
    Forwarding there would create a double cycle if both are called.
    Implemented as a stub to avoid race condition with the adaptive
    hot/cold scheduler — use POST /dispatch/monitor/run-now directly.
    """
    _logger.info("ops_dashboard: run-cycle-now called (stub — use /dispatch/monitor/run-now)")
    return JSONResponse({
        "ok": True,
        "status": "stub",
        "note": "Use POST /dispatch/monitor/run-now for immediate cycle trigger. This stub avoids race conditions with the adaptive hot/cold scheduler.",
    })


# ── POST /ops-dashboard/mute-all ──────────────────────────────────────────────

@router.post("/mute-all")
async def mute_all(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    """
    Mute all active drivers (with unaccepted trips today) for 30 minutes.
    Writes alert_profile.muted_until on each driver's Person row.
    """
    from zoneinfo import ZoneInfo
    tz_name = os.environ.get("MONITOR_TIMEZONE", "America/Los_Angeles")
    tz = ZoneInfo(tz_name)
    now_local = datetime.now(tz)
    today = now_local.date()

    muted_until = datetime.now(timezone.utc) + timedelta(minutes=30)

    # Find all persons with unaccepted trips today
    person_ids_q = (
        db.query(TripNotification.person_id)
        .filter(
            TripNotification.trip_date == today,
            TripNotification.accepted_at.is_(None),
            TripNotification.manually_resolved_at.is_(None),
        )
        .distinct()
        .all()
    )

    person_ids = [row.person_id for row in person_ids_q]

    if not person_ids:
        return JSONResponse({"ok": True, "muted_count": 0, "muted_until": muted_until.isoformat()})

    persons = db.query(Person).filter(Person.person_id.in_(person_ids)).all()

    muted_names: list[str] = []
    for person in persons:
        person.alert_profile = {
            "muted_until": muted_until.isoformat(),
            "muted_reason": "mute-all from /ops dashboard",
        }
        muted_names.append(person.full_name)

    db.commit()
    _logger.info("ops_dashboard: mute-all applied to %d drivers until %s", len(persons), muted_until.isoformat())

    return JSONResponse({
        "ok": True,
        "muted_count": len(persons),
        "muted_until": muted_until.isoformat(),
        "muted_drivers": muted_names,
    })


# ── GET /ops-dashboard/trip-explain/{notif_id} ────────────────────────────────

@router.get("/trip-explain/{notif_id}")
def trip_explain(notif_id: int, db: Session = Depends(get_db)) -> JSONResponse:
    """
    Return a human-readable explanation of a trip's current state.
    Used by the info icon on each live-trip row.
    """
    notif = db.query(TripNotification).filter(TripNotification.id == notif_id).first()
    if not notif:
        return JSONResponse({"error": "Trip not found"}, status_code=404)

    person = db.query(Person).filter(Person.person_id == notif.person_id).first()
    driver_name = person.full_name if person else f"Driver #{notif.person_id}"

    # Determine bucket
    is_accepted = notif.accepted_at is not None
    is_started = notif.started_at is not None
    is_escalated = bool(notif.accept_escalated_at or notif.start_escalated_at)
    is_snoozed = bool(notif.snoozed_until and datetime.now(timezone.utc) < (
        notif.snoozed_until if notif.snoozed_until.tzinfo else notif.snoozed_until.replace(tzinfo=timezone.utc)
    ))

    if is_started:
        bucket = "started"
        reason = f"{driver_name} has tapped Start. Trip is in progress."
    elif is_accepted and is_escalated:
        bucket = "accepted_escalated"
        reason = f"{driver_name} accepted but hasn't started. Admin was alerted."
    elif is_accepted:
        bucket = "accepted_not_started"
        reason = f"{driver_name} accepted the trip but hasn't tapped Start yet."
    elif is_snoozed:
        bucket = "snoozed"
        reason = f"Alert snoozed until {notif.snoozed_until.isoformat()}. Monitor will resume after snooze."
    elif is_escalated:
        bucket = "unaccepted_escalated"
        reason = f"{driver_name} hasn't accepted. SMS and call fired. Admin escalated."
    elif notif.accept_call_at:
        bucket = "unaccepted_called"
        reason = f"{driver_name} hasn't accepted. SMS and call fired, waiting."
    elif notif.accept_sms_at:
        bucket = "unaccepted_sms_sent"
        reason = f"{driver_name} was texted but hasn't accepted yet."
    else:
        bucket = "unaccepted_pending"
        reason = f"{driver_name} assigned but not yet in SMS window."

    # Last event
    last_event = db.query(NotificationEvent).filter(
        NotificationEvent.trip_notification_id == notif_id
    ).order_by(NotificationEvent.created_at.desc()).first()

    return JSONResponse({
        "notif_id": notif_id,
        "driver": driver_name,
        "trip_ref": notif.trip_ref,
        "source": notif.source,
        "pickup_time": notif.pickup_time or "",
        "trip_status": notif.trip_status or "",
        "bucket": bucket,
        "reason": reason,
        "last_event": {
            "event_type": last_event.event_type,
            "created_at": _format_dt(last_event.created_at),
            "payload": last_event.payload or {},
        } if last_event else None,
        "timeline": {
            "accept_sms_at": _format_dt(notif.accept_sms_at),
            "accept_call_at": _format_dt(notif.accept_call_at),
            "accept_escalated_at": _format_dt(notif.accept_escalated_at),
            "accepted_at": _format_dt(notif.accepted_at),
            "start_sms_at": _format_dt(notif.start_sms_at),
            "start_call_at": _format_dt(notif.start_call_at),
            "start_escalated_at": _format_dt(notif.start_escalated_at),
            "started_at": _format_dt(notif.started_at),
        },
    })


# ── GET /ops-dashboard/heatmap ────────────────────────────────────────────────

@router.get("/heatmap")
def trip_heatmap(db: Session = Depends(get_db)) -> JSONResponse:
    """
    Return a 7-day × 24-hour trip volume matrix for the heatmap widget.

    Each cell = count of TripNotification rows whose pickup_time falls in that
    hour bucket and whose trip_date falls in the trailing 7 calendar days
    (inclusive of today).

    Response shape:
    {
      "days": ["Mon", "Tue", ...],      // 7 labels, oldest→newest
      "hours": [0, 1, ..., 23],
      "matrix": [[int, ...], ...],      // matrix[day_idx][hour] = count
      "peak_count": int,                // max cell value (for color scaling)
      "window_start": "YYYY-MM-DD",
      "window_end": "YYYY-MM-DD",
    }

    pickup_time is stored as "HH:MM" or "HH:MM:SS" in local time.
    We parse the hour component only — no timezone conversion needed
    since the string is already in local (PDT) time.
    """
    from zoneinfo import ZoneInfo
    tz_name = os.environ.get("MONITOR_TIMEZONE", "America/Los_Angeles")
    tz = ZoneInfo(tz_name)
    today: _date = datetime.now(tz).date()

    # Build 7-day window: [today-6 ... today] (7 days inclusive)
    window_start = today - timedelta(days=6)
    window_end = today

    # Fetch all trip_notification rows in the window that have a pickup_time
    rows = (
        db.query(TripNotification.trip_date, TripNotification.pickup_time)
        .filter(
            TripNotification.trip_date >= window_start,
            TripNotification.trip_date <= window_end,
            TripNotification.pickup_time.isnot(None),
        )
        .all()
    )

    # Build a 7-row × 24-col matrix, initialized to zero.
    # day_index 0 = window_start (oldest), 6 = today (newest).
    matrix: list[list[int]] = [[0] * 24 for _ in range(7)]

    for trip_date, pickup_time in rows:
        if not pickup_time:
            continue
        # Parse hour from "HH:MM" or "HH:MM:SS" or "H:MM"
        try:
            hour = int(str(pickup_time).strip().split(":")[0])
            if not (0 <= hour <= 23):
                continue
        except (ValueError, AttributeError, IndexError):
            continue

        day_delta = (trip_date - window_start).days
        if 0 <= day_delta <= 6:
            matrix[day_delta][hour] += 1

    # Day labels: short weekday name for each date in the window
    DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    days = []
    for i in range(7):
        d = window_start + timedelta(days=i)
        days.append(DAY_NAMES[d.weekday()])

    peak_count = max((cell for row in matrix for cell in row), default=0)

    return JSONResponse({
        "days": days,
        "hours": list(range(24)),
        "matrix": matrix,
        "peak_count": peak_count,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
    })


# ── GET /ops-dashboard/event-log ──────────────────────────────────────────────

@router.get("/event-log")
def event_log(
    limit: int = 100,
    severity: str | None = None,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Recent ops_event_log entries — the internal paper trail that replaced
    Discord. Returns newest-first, hard-capped at 500 rows.

    Query params:
      limit     1..500 (clamped). Default 100.
      severity  Optional filter — critical/urgent/normal/silent.

    Response: { events: [...], generated_at: iso }
    """
    capped_limit = max(1, min(500, limit))

    q = db.query(OpsEventLog).order_by(OpsEventLog.created_at.desc())
    if severity:
        q = q.filter(OpsEventLog.severity == severity.lower())

    rows = q.limit(capped_limit).all()

    events = [
        {
            "id": r.id,
            "severity": r.severity,
            "title": r.title,
            "message": r.message,
            "trip_id": r.trip_id,
            "notif_id": r.notif_id,
            "source": r.source,
            "created_at": _format_dt(r.created_at),
        }
        for r in rows
    ]

    return JSONResponse({
        "events": events,
        "count": len(events),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    })
