"""
Trip monitor observability endpoints — `/trip-monitor/today` (rich daily view)
and `/trip-monitor/health` (fast liveness probe).

Auth-gated by AuthMiddleware (no PUBLIC_PREFIXES entry). The legacy dispatch
monitor lives at `/dispatch/monitor/*` in dispatch_monitor.py — left untouched.
"""

from __future__ import annotations

from datetime import datetime, date
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import Person, TripNotification

router = APIRouter(prefix="/trip-monitor", tags=["trip-monitor"])


# Trip statuses that mean a driver is currently mid-ride and physically
# cannot start another. Mirrors the busy_drivers logic in trip_monitor.py
# so concurrent_active counts match what the cycle uses for suppression.
_ACTIVE_TRIP_STATUSES = (
    "ToStop",
    "ToPickup",
    "OnTrip",
    "Active",
    "AtStop",
    "IN_PROGRESS",
)


def _fmt_pdt(dt: datetime | None, tz: ZoneInfo) -> str | None:
    """Format a UTC-stored timestamp as 'HH:MM' in PDT — None-safe."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        # DB column is timestamp WITH timezone, but be defensive
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(tz).strftime("%H:%M")


def _fmt_pdt_full(dt: datetime | None, tz: ZoneInfo) -> str | None:
    """Format as 'YYYY-MM-DD HH:MM' in PDT."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M")


def _stages_fired(notif: TripNotification) -> list[str]:
    """Ordered list of which stages fired, for UI chips."""
    fired: list[str] = []
    if notif.accept_sms_at:
        fired.append("accept_sms")
    if notif.accept_call_at:
        fired.append("accept_call")
    if notif.accept_escalated_at:
        fired.append("accept_esc")
    if notif.start_sms_at:
        fired.append("start_sms")
    if notif.start_call_at:
        fired.append("start_call")
    if notif.start_escalated_at:
        fired.append("start_esc")
    if notif.overdue_alerted_at:
        fired.append("overdue")
    return fired


def _was_contacted(notif: TripNotification) -> bool:
    """True if any contact-stage timestamp is set."""
    return bool(
        notif.accept_sms_at
        or notif.accept_call_at
        or notif.accept_escalated_at
        or notif.start_sms_at
        or notif.start_call_at
        or notif.start_escalated_at
        or notif.overdue_alerted_at
    )


@router.get("/today")
def trip_monitor_today(db: Session = Depends(get_db)) -> JSONResponse:
    """
    Rich snapshot of today's monitor activity:
      - Last cycle metadata (when, how many trips, errors, full summary dict).
      - Aggregated totals across all today's trip_notification rows.
      - Per-contact detail for every driver the monitor reached out to today.
    """
    from backend.services.trip_monitor import _last_run_info, _TZ_NAME

    tz = ZoneInfo(_TZ_NAME)
    now = datetime.now(tz)
    today: date = now.date()

    # ── Last cycle ───────────────────────────────────────────────
    last_run_raw = _last_run_info.get("last_run")
    last_summary = _last_run_info.get("summary")
    # Summary may be the string "Skipped — outside operating hours" when the
    # cycle no-op'd. Normalize to a dict so frontend types stay sane.
    summary_dict: dict[str, Any] | None
    if isinstance(last_summary, dict):
        summary_dict = last_summary
    else:
        summary_dict = None

    last_cycle: dict[str, Any] = {
        "ran_at": last_run_raw,
        "trips_checked": (summary_dict or {}).get("trips_checked", 0) if summary_dict else 0,
        "errors": (summary_dict or {}).get("errors", []) if summary_dict else [],
        "summary": summary_dict if summary_dict is not None else {"note": last_summary},
    }

    # ── Today's notifications ────────────────────────────────────
    notifs = (
        db.query(TripNotification, Person)
        .join(Person, Person.person_id == TripNotification.person_id)
        .filter(TripNotification.trip_date == today)
        .order_by(TripNotification.pickup_time.asc().nullslast())
        .all()
    )

    # Totals across ALL today's rows (not just contacted).
    totals: dict[str, int] = {
        "accept_sms": 0,
        "accept_calls": 0,
        "accept_escalations": 0,
        "start_sms": 0,
        "start_calls": 0,
        "start_escalations": 0,
        "overdue_alerts": 0,
        "declines": 0,
        "name_mismatches": 0,
        "unknown_status_alerts": 0,
        "start_suppressed_concurrent": 0,
    }
    for notif, _person in notifs:
        if notif.accept_sms_at:
            totals["accept_sms"] += 1
        if notif.accept_call_at:
            totals["accept_calls"] += 1
        if notif.accept_escalated_at:
            totals["accept_escalations"] += 1
        if notif.start_sms_at:
            totals["start_sms"] += 1
        if notif.start_call_at:
            totals["start_calls"] += 1
        if notif.start_escalated_at:
            totals["start_escalations"] += 1
        if notif.overdue_alerted_at:
            totals["overdue_alerts"] += 1

    # Cycle-only counters — only the latest cycle knows these (they aren't
    # persisted per-row). Pull from the last summary if present.
    if summary_dict is not None:
        totals["declines"] = int(summary_dict.get("declines", 0) or 0)
        totals["name_mismatches"] = int(summary_dict.get("name_mismatches", 0) or 0)
        totals["unknown_status_alerts"] = int(
            summary_dict.get("unknown_status_alerts", 0) or 0
        )
        totals["start_suppressed_concurrent"] = int(
            summary_dict.get("start_suppressed_concurrent", 0) or 0
        )

    # ── Per-person concurrent-active counts ──────────────────────
    # For each person who got a contact today, count OTHER trips today
    # whose trip_status is in the active set.
    contacted_person_ids = {
        notif.person_id for notif, _ in notifs if _was_contacted(notif)
    }
    concurrent_by_person: dict[int, int] = {pid: 0 for pid in contacted_person_ids}
    for notif, _ in notifs:
        if notif.person_id in concurrent_by_person:
            if (notif.trip_status or "") in _ACTIVE_TRIP_STATUSES:
                concurrent_by_person[notif.person_id] += 1

    # ── Build contacts list ──────────────────────────────────────
    contacts: list[dict[str, Any]] = []
    for notif, person in notifs:
        if not _was_contacted(notif):
            continue

        # Subtract 1 if THIS trip is itself counted in the active total —
        # the field describes OTHER concurrent trips.
        active_count = concurrent_by_person.get(person.person_id, 0)
        if (notif.trip_status or "") in _ACTIVE_TRIP_STATUSES and active_count > 0:
            active_count -= 1

        contacts.append({
            "driver_name": person.full_name,
            "person_id": person.person_id,
            "trip_ref": notif.trip_ref,
            "source": notif.source,
            "trip_status": notif.trip_status or "",
            "pickup_time_pdt": _fmt_pdt_full(
                _coerce_pickup_dt(notif.pickup_time, today, tz), tz
            ) if notif.pickup_time else None,
            "pickup_time_raw": notif.pickup_time or None,
            "accept_sms_at": _fmt_pdt(notif.accept_sms_at, tz),
            "accept_call_at": _fmt_pdt(notif.accept_call_at, tz),
            "accept_escalated_at": _fmt_pdt(notif.accept_escalated_at, tz),
            "accepted_at_pdt": _fmt_pdt(notif.accepted_at, tz),
            "start_sms_at_pdt": _fmt_pdt(notif.start_sms_at, tz),
            "start_call_at_pdt": _fmt_pdt(notif.start_call_at, tz),
            "start_escalated_at_pdt": _fmt_pdt(notif.start_escalated_at, tz),
            "started_at_pdt": _fmt_pdt(notif.started_at, tz),
            "overdue_alerted_at_pdt": _fmt_pdt(notif.overdue_alerted_at, tz),
            "stages_fired": _stages_fired(notif),
            "concurrent_active": active_count,
        })

    return JSONResponse({
        "current_time_pdt": now.isoformat(),
        "today_pdt": today.isoformat(),
        "last_cycle": last_cycle,
        "totals_today": totals,
        "contacts": contacts,
    })


def _coerce_pickup_dt(pickup_str: str | None, trip_date: date, tz: ZoneInfo) -> datetime | None:
    """Best-effort parse for display only (full PDT timestamp). Mirrors the
    cycle parser's tolerance but never raises — falls back to None on any
    parse failure so the UI just shows the raw string."""
    if not pickup_str:
        return None
    try:
        if len(pickup_str) <= 5 and ":" in pickup_str:
            h, m = pickup_str.split(":")
            return datetime(
                trip_date.year, trip_date.month, trip_date.day,
                int(h), int(m), tzinfo=tz,
            )
        if "T" in pickup_str:
            dt = datetime.fromisoformat(pickup_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz)
            return dt
        for fmt in ("%I:%M %p", "%I:%M%p"):
            try:
                t = datetime.strptime(pickup_str, fmt)
                return datetime(
                    trip_date.year, trip_date.month, trip_date.day,
                    t.hour, t.minute, tzinfo=tz,
                )
            except ValueError:
                continue
    except (ValueError, TypeError):
        return None
    return None


@router.get("/health")
def trip_monitor_health() -> JSONResponse:
    """
    Fast liveness probe — designed for monitoring tools and the dashboard
    status strip. No DB query.
    """
    from backend.services.trip_monitor import (
        _INTERVAL,
        _START_HOUR,
        _END_HOUR,
        _TZ_NAME,
        _last_run_info,
        _scheduler,
        check_liveness,
    )

    tz = ZoneInfo(_TZ_NAME)
    now = datetime.now(tz)
    in_hours = _START_HOUR <= now.hour < _END_HOUR

    liveness = check_liveness()  # sets healthy/stale_minutes; may alert

    last_run_raw = _last_run_info.get("last_run")
    last_cycle_seconds_ago: float | None = None
    if last_run_raw:
        try:
            last_dt = datetime.fromisoformat(last_run_raw)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=tz)
            last_cycle_seconds_ago = (now - last_dt).total_seconds()
        except (ValueError, TypeError):
            last_cycle_seconds_ago = None

    summary = _last_run_info.get("summary")
    errors_in_last_cycle = (
        len(summary.get("errors", [])) if isinstance(summary, dict) else 0
    )

    stale_threshold_seconds = _INTERVAL * 3 * 60
    stale = (
        last_cycle_seconds_ago is not None
        and last_cycle_seconds_ago > stale_threshold_seconds
        and in_hours
    )

    return JSONResponse({
        "scheduler_alive": _scheduler is not None,
        "last_cycle_seconds_ago": (
            round(last_cycle_seconds_ago, 1) if last_cycle_seconds_ago is not None else None
        ),
        "stale": bool(stale),
        "errors_in_last_cycle": errors_in_last_cycle,
        "operating_hours": in_hours,
        "interval_minutes": _INTERVAL,
        "operating_window_pdt": f"{_START_HOUR:02d}:00-{_END_HOUR:02d}:00",
        "current_time_pdt": now.isoformat(),
        "liveness_healthy": bool(liveness.get("healthy", True)),
    })
