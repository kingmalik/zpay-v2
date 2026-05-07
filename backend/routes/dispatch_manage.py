# DEPRECATED — router removed from app.py (2026-05-01 walk-through cleanup). DispatchAgent chat migrated to /dispatch page. DB tables DriverBlackout, DriverPromise, DispatchSessionLog to be dropped in next migration PR when confirmed safe.
"""
Dispatch Manage routes — /dispatch/manage/*

Endpoints for the unified dispatch management board:
  POST /dispatch/manage/cover-search     → find coverage for an existing trip
  GET  /dispatch/manage/promises         → list driver promises
  POST /dispatch/manage/promises         → create promise
  PUT  /dispatch/manage/promises/{id}    → fulfill promise
  DELETE /dispatch/manage/promises/{id}  → delete promise
  GET  /dispatch/manage/blackouts        → list blackouts
  POST /dispatch/manage/blackouts        → create blackout
  DELETE /dispatch/manage/blackouts/{id} → delete blackout
  GET  /dispatch/manage/reliability      → driver reliability scores
                                           ?window=rolling90 (default) → last 90 days
                                           ?window=weekly&week=YYYY-WW → scorecard week
  GET  /dispatch/manage/weekly-load      → ride counts per driver for a week
"""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

import json

from backend.db import get_db
from backend.db.models import Person, DriverPromise, DriverBlackout, TripNotification, Ride, DispatchSessionLog
from backend.routes.dispatch_assign import _build_driver_list
from backend.services import maps_service
from backend.services.driver_scorecard import compute_all_active_drivers, DriverScorecard

PT = ZoneInfo("America/Los_Angeles")

router = APIRouter(prefix="/dispatch/manage", tags=["dispatch-manage"])


# ---------------------------------------------------------------------------
# Cover Search
# ---------------------------------------------------------------------------

@router.post("/cover-search")
async def cover_search(request: Request, db: Session = Depends(get_db)):
    """
    Find drivers who can cover a specific trip.
    Body: {
      exclude_person_id: int,
      pickup_address: str,
      pickup_time: str (HH:MM),
      dropoff_time: str (HH:MM),
      ride_date: str (YYYY-MM-DD),
      service_name: str,
      minutes_until_pickup: int  (for emergency mode)
    }
    """
    body = await request.json()
    exclude_id = body.get("exclude_person_id")
    pickup_address = body.get("pickup_address", "")
    pickup_time = body.get("pickup_time", "")
    dropoff_time = body.get("dropoff_time", "")
    ride_date_str = body.get("ride_date", date.today().isoformat())
    minutes_until = body.get("minutes_until_pickup")

    try:
        target_date = date.fromisoformat(ride_date_str)
    except ValueError:
        target_date = date.today()

    drivers = _build_driver_list(target_date, db)

    # Exclude the driver who needs coverage
    drivers = [d for d in drivers if d.get("person_id") != exclude_id]

    scored = maps_service.score_drivers(
        drivers,
        pickup_address=pickup_address,
        pickup_time_str=pickup_time,
        dropoff_time_str=dropoff_time,
    )

    # For emergency mode: only keep tier 1-2 drivers (can physically make it)
    if minutes_until is not None and minutes_until < 60:
        scored = [r for r in scored if r["tier"] <= 2] or scored[:3]

    non_conflict = [r for r in scored if r["tier"] < 5]
    results = (non_conflict[:6] if non_conflict else scored[:3])

    return JSONResponse({
        "recommendations": results,
        "no_drivers": len(results) == 0,
        "emergency": minutes_until is not None and minutes_until < 60,
    })


# ---------------------------------------------------------------------------
# Driver Promises
# ---------------------------------------------------------------------------

@router.get("/promises")
def list_promises(db: Session = Depends(get_db)):
    rows = (
        db.query(DriverPromise, Person.full_name)
        .join(Person, DriverPromise.person_id == Person.person_id)
        .order_by(DriverPromise.fulfilled_at.asc().nullsfirst(), DriverPromise.promised_at.desc())
        .all()
    )
    return JSONResponse([
        {
            "id": p.id,
            "person_id": p.person_id,
            "driver_name": name,
            "description": p.description,
            "promised_at": p.promised_at.isoformat() if p.promised_at else None,
            "fulfilled_at": p.fulfilled_at.isoformat() if p.fulfilled_at else None,
            "fulfilled_ride_ref": p.fulfilled_ride_ref,
            "notes": p.notes,
        }
        for p, name in rows
    ])


@router.post("/promises")
async def create_promise(request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    person_id = body.get("person_id")
    description = body.get("description", "").strip()
    notes = body.get("notes", "").strip() or None

    if not person_id or not description:
        return JSONResponse({"error": "person_id and description required"}, status_code=400)

    person = db.query(Person).filter(Person.person_id == person_id).first()
    if not person:
        return JSONResponse({"error": "Driver not found"}, status_code=404)

    promise = DriverPromise(
        person_id=person_id,
        description=description,
        notes=notes,
        promised_at=datetime.now(timezone.utc),
    )
    db.add(promise)
    db.commit()
    db.refresh(promise)

    return JSONResponse({"ok": True, "id": promise.id, "driver_name": person.full_name})


@router.put("/promises/{promise_id}")
async def fulfill_promise(promise_id: int, request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    promise = db.query(DriverPromise).filter(DriverPromise.id == promise_id).first()
    if not promise:
        return JSONResponse({"error": "Promise not found"}, status_code=404)

    promise.fulfilled_at = datetime.now(timezone.utc)
    promise.fulfilled_ride_ref = body.get("ride_ref", "").strip() or None
    db.commit()

    return JSONResponse({"ok": True})


@router.delete("/promises/{promise_id}")
def delete_promise(promise_id: int, db: Session = Depends(get_db)):
    promise = db.query(DriverPromise).filter(DriverPromise.id == promise_id).first()
    if not promise:
        return JSONResponse({"error": "Promise not found"}, status_code=404)
    db.delete(promise)
    db.commit()
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# Driver Blackouts
# ---------------------------------------------------------------------------

@router.get("/blackouts")
def list_blackouts(db: Session = Depends(get_db)):
    rows = (
        db.query(DriverBlackout, Person.full_name)
        .join(Person, DriverBlackout.person_id == Person.person_id)
        .order_by(DriverBlackout.start_date.asc())
        .all()
    )
    return JSONResponse([
        {
            "id": b.id,
            "person_id": b.person_id,
            "driver_name": name,
            "start_date": b.start_date.isoformat(),
            "end_date": b.end_date.isoformat(),
            "reason": b.reason,
            "recurring": b.recurring,
            "recurring_days": b.recurring_days,
            "created_at": b.created_at.isoformat() if b.created_at else None,
        }
        for b, name in rows
    ])


@router.post("/blackouts")
async def create_blackout(request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    person_id = body.get("person_id")
    start_date_str = body.get("start_date", "")
    end_date_str = body.get("end_date", "")
    reason = body.get("reason", "").strip() or None
    recurring = bool(body.get("recurring", False))
    recurring_days = body.get("recurring_days") or None

    if not person_id or not start_date_str or not end_date_str:
        return JSONResponse({"error": "person_id, start_date, end_date required"}, status_code=400)

    try:
        start_date = date.fromisoformat(start_date_str)
        end_date = date.fromisoformat(end_date_str)
    except ValueError:
        return JSONResponse({"error": "Invalid date format"}, status_code=400)

    person = db.query(Person).filter(Person.person_id == person_id).first()
    if not person:
        return JSONResponse({"error": "Driver not found"}, status_code=404)

    blackout = DriverBlackout(
        person_id=person_id,
        start_date=start_date,
        end_date=end_date,
        reason=reason,
        recurring=recurring,
        recurring_days=recurring_days,
        created_at=datetime.now(timezone.utc),
    )
    db.add(blackout)
    db.commit()
    db.refresh(blackout)

    return JSONResponse({"ok": True, "id": blackout.id, "driver_name": person.full_name})


@router.delete("/blackouts/{blackout_id}")
def delete_blackout(blackout_id: int, db: Session = Depends(get_db)):
    blackout = db.query(DriverBlackout).filter(DriverBlackout.id == blackout_id).first()
    if not blackout:
        return JSONResponse({"error": "Blackout not found"}, status_code=404)
    db.delete(blackout)
    db.commit()
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# Driver Reliability
#
# GET /dispatch/manage/reliability
#   ?window=rolling90  (default) — last 90 days from TripNotification, returns
#                                   a dict keyed by person_id (original shape,
#                                   used by the existing dispatch manage page).
#   ?window=weekly&week=YYYY-WW  — weekly scorecard via driver_scorecard service.
#                                   Returns a JSON list, one row per driver who
#                                   had rides that week, sorted by composite_score
#                                   descending. Drivers with no activity are omitted.
# ---------------------------------------------------------------------------

def _parse_iso_week(week_str: str) -> date:
    """Parse 'YYYY-WW' into the Monday date of that ISO week.

    Raises ValueError on bad format.
    """
    parts = week_str.split("-W")
    if len(parts) != 2:
        raise ValueError(f"Invalid week format: {week_str!r}")
    year_str, week_num_str = parts
    if not year_str.isdigit() or not week_num_str.isdigit():
        raise ValueError(f"Invalid week format: {week_str!r}")
    year = int(year_str)
    week_num = int(week_num_str)
    if not (1 <= week_num <= 53):
        raise ValueError(f"Week number out of range: {week_num}")
    return date.fromisocalendar(year, week_num, 1)  # Monday = day 1


def _current_pt_week_start() -> date:
    """Return the Monday of the current ISO week in Pacific Time."""
    now_pt = datetime.now(PT)
    today_pt = now_pt.date()
    # ISO weekday: Monday=1 … Sunday=7
    return today_pt - timedelta(days=today_pt.weekday())


def _scorecard_to_dict(sc: DriverScorecard) -> dict:
    """Serialize a DriverScorecard to the weekly-window response shape."""
    axes_out = {}
    for axis_name, ax in sc.axes.items():
        axes_out[axis_name] = {
            "raw": round(ax.raw_value, 4),
            "normalized": round(ax.normalized_value, 4),
            "weighted": round(ax.weighted_score, 4),
            "sample_size": ax.sample_size,
            "available": ax.available,
        }

    return {
        "person_id": sc.person_id,
        "driver_name": sc.driver_name,
        "week_iso": sc.week_iso,
        "total_trips": sc.total_trips,
        "tier": sc.tier,
        "tier_label": sc.tier_label,
        "composite_score": sc.composite_score,
        "axes": axes_out,
        "wow_delta": sc.week_over_week_delta,
        "headline_metric": sc.headline_metric,
        "focus_area": sc.focus_area,
        "low_sample": sc.low_sample,
        "escalation_count": sc.escalation_count,
        "self_serve_pct": sc.self_serve_pct,
        "revenue_impact": sc.revenue_impact,
        "revenue_impact_per_trip": sc.revenue_impact_per_trip,
        "revenue_rank": sc.revenue_rank,
    }


@router.get("/reliability")
def driver_reliability(
    window: Optional[str] = None,
    week: Optional[str] = None,
    db: Session = Depends(get_db),
):
    # ── Validate window param ─────────────────────────────────────────────────
    effective_window = window or "rolling90"
    if effective_window not in ("rolling90", "weekly", "30d"):
        return JSONResponse(
            {"error": "window must be 'rolling90', 'weekly', or '30d'"},
            status_code=400,
        )

    # ── Weekly path ───────────────────────────────────────────────────────────
    if effective_window == "weekly":
        if week is not None:
            try:
                week_start = _parse_iso_week(week)
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
        else:
            week_start = _current_pt_week_start()

        scorecards = compute_all_active_drivers(week_start, db)

        # Omit drivers with no activity this week
        active = [sc for sc in scorecards if sc.tier != "no_activity"]

        # Sort by escalations DESC (most escalations first = who needs coaching).
        # Tiebreaker: self_serve_pct ascending (lower % = more urgent).
        active.sort(
            key=lambda sc: (
                -(sc.escalation_count),
                sc.self_serve_pct if sc.self_serve_pct is not None else 100.0,
            ),
        )

        # Load week-over-week deltas from scorecard_cache (Phase 4).
        # Falls back gracefully if table is empty (no cache yet).
        wow_map: dict[int, object] = {}
        try:
            from backend.services.scorecard_cache_service import get_fleet_trend
            wow_map = get_fleet_trend(week_start, db)
        except Exception as exc:
            import logging
            logging.getLogger("zpay.dispatch_manage").warning(
                "[reliability] WoW delta load failed (cache may be empty): %s", exc
            )

        rows_out = []
        for sc in active:
            d = _scorecard_to_dict(sc)
            delta = wow_map.get(sc.person_id)
            if delta is not None:
                d["wow_escalation_delta"] = delta.escalation_delta
                d["wow_composite_delta"] = delta.composite_delta
            else:
                d["wow_escalation_delta"] = None
                d["wow_composite_delta"] = None
            rows_out.append(d)

        return JSONResponse(rows_out)

    # ── 30-day rolling average path (Phase 4) ─────────────────────────────────
    if effective_window == "30d":
        if week is not None:
            try:
                week_start = _parse_iso_week(week)
                # Advance one week so "30d before this week" is what we average
                week_start = week_start + timedelta(days=7)
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
        else:
            week_start = _current_pt_week_start() + timedelta(days=7)

        from backend.services.scorecard_cache_service import get_rolling_30d
        from backend.db.models import Person as PersonModel

        active_persons = (
            db.query(PersonModel)
            .filter(PersonModel.active.is_(True))
            .all()
        )

        out = []
        for person in active_persons:
            rolling = get_rolling_30d(person.person_id, week_start, db)
            if rolling["weeks_found"] == 0:
                continue  # no cache data — skip
            out.append({
                "person_id": person.person_id,
                "driver_name": person.full_name,
                "window": "30d",
                "weeks_found": rolling["weeks_found"],
                "total_trips": rolling["total_trips"],
                "self_serve_pct": rolling["self_serve_pct"],
                "on_time_pct": rolling["on_time_pct"],
                "escalation_count": rolling["escalation_count"],
                "composite_score": rolling["composite_score"],
            })

        # Sort by avg escalation count DESC
        out.sort(key=lambda r: -(r["escalation_count"] or 0))
        return JSONResponse(out)

    # ── Rolling-90 path (original behavior, unchanged) ────────────────────────
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)

    rows = (
        db.query(
            TripNotification.person_id,
            func.count().label("total"),
            func.count(TripNotification.accepted_at).label("accepted"),
            func.count(TripNotification.started_at).label("started"),
            func.count(TripNotification.accept_escalated_at).label("escalated"),
        )
        .filter(TripNotification.trip_date >= cutoff.date())
        .group_by(TripNotification.person_id)
        .all()
    )

    result = {}
    for row in rows:
        total = row.total or 1  # avoid div/0
        accepted = row.accepted or 0
        started = row.started or 0
        escalated = row.escalated or 0
        acceptance_rate = round(accepted / total * 100)
        started_rate = round(started / total * 100)
        escalation_rate = round(escalated / total * 100)

        # Tier: 1=excellent, 2=good, 3=ok, 4=poor
        if acceptance_rate >= 90 and escalation_rate <= 5:
            tier = 1
        elif acceptance_rate >= 75 and escalation_rate <= 15:
            tier = 2
        elif acceptance_rate >= 60:
            tier = 3
        else:
            tier = 4

        result[row.person_id] = {
            "total_trips": row.total,
            "acceptance_rate": acceptance_rate,
            "started_rate": started_rate,
            "escalation_rate": escalation_rate,
            "tier": tier,
        }

    return JSONResponse(result)


# ---------------------------------------------------------------------------
# Weekly Load
# ---------------------------------------------------------------------------

@router.get("/weekly-load")
def weekly_load(week_start: Optional[str] = None, db: Session = Depends(get_db)):
    if week_start:
        try:
            ws = date.fromisoformat(week_start)
        except ValueError:
            ws = date.today() - timedelta(days=date.today().weekday())
    else:
        ws = date.today() - timedelta(days=date.today().weekday())

    we = ws + timedelta(days=6)

    rows = (
        db.query(
            Ride.person_id,
            Person.full_name,
            func.count(Ride.ride_id).label("ride_count"),
            func.sum(Ride.gross_pay).label("gross_pay"),
        )
        .join(Person, Ride.person_id == Person.person_id)
        .filter(
            func.date(Ride.ride_start_ts) >= ws,
            func.date(Ride.ride_start_ts) <= we,
        )
        .group_by(Ride.person_id, Person.full_name)
        .order_by(func.count(Ride.ride_id).desc())
        .all()
    )

    counts = [r.ride_count for r in rows]
    avg = sum(counts) / len(counts) if counts else 0

    return JSONResponse({
        "week_start": ws.isoformat(),
        "week_end": we.isoformat(),
        "average": round(avg, 1),
        "drivers": [
            {
                "person_id": r.person_id,
                "name": r.full_name,
                "ride_count": r.ride_count,
                "gross_pay": float(r.gross_pay or 0),
                "vs_avg": round(r.ride_count - avg, 1),
            }
            for r in rows
        ],
    })


# ---------------------------------------------------------------------------
# Driver list with tier badges — Phase 11
#
# GET /dispatch/manage/drivers
#   ?tier=all          (default) → all active drivers with current-week tier
#   ?tier=gold|silver|bronze|probation|no_activity → filtered
#
# Sorted: Gold first (tier_order asc), then composite_score desc within tier.
# ---------------------------------------------------------------------------

_TIER_ORDER: dict[str, int] = {
    "gold": 1,
    "silver": 2,
    "bronze": 3,
    "probation": 4,
    "no_activity": 5,
}

_VALID_TIER_FILTERS = frozenset({"all", "gold", "silver", "bronze", "probation", "no_activity"})


@router.get("/drivers")
def list_drivers_with_tier(
    tier: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Return all active drivers enriched with their current ISO-week scorecard tier."""
    effective_tier = (tier or "all").lower()
    if effective_tier not in _VALID_TIER_FILTERS:
        return JSONResponse(
            {"error": f"tier must be one of: {', '.join(sorted(_VALID_TIER_FILTERS))}"},
            status_code=400,
        )

    week_start = _current_pt_week_start()
    scorecards = compute_all_active_drivers(week_start, db)

    rows = scorecards if effective_tier == "all" else [s for s in scorecards if s.tier == effective_tier]

    rows = sorted(
        rows,
        key=lambda s: (
            _TIER_ORDER.get(s.tier, 99),
            -(s.composite_score if s.composite_score is not None else -1),
        ),
    )

    return JSONResponse([
        {
            "person_id": s.person_id,
            "driver_name": s.driver_name,
            "tier": s.tier,
            "tier_label": s.tier_label,
            "composite_score": s.composite_score,
            "week_iso": s.week_iso,
            "total_trips": s.total_trips,
        }
        for s in rows
    ])


# ---------------------------------------------------------------------------
# Leave Coverage
# ---------------------------------------------------------------------------

@router.post("/leave-coverage")
async def leave_coverage(request: Request, db: Session = Depends(get_db)):
    """
    Analyze coverage needs for a driver taking extended leave.
    Body: { person_id, start_date, end_date }
    Returns: routes the driver normally runs + suggested cover drivers + hire flags.
    """
    body = await request.json()
    person_id = body.get("person_id")
    start_date_str = body.get("start_date", "")
    end_date_str = body.get("end_date", "")

    if not person_id:
        return JSONResponse({"error": "person_id required"}, status_code=400)
    try:
        start_date = date.fromisoformat(start_date_str)
        end_date = date.fromisoformat(end_date_str)
    except (ValueError, TypeError):
        return JSONResponse({"error": "Invalid date range"}, status_code=400)

    if end_date <= start_date:
        return JSONResponse({"error": "end_date must be after start_date"}, status_code=400)

    weeks = max(1, round((end_date - start_date).days / 7))
    history_cutoff = start_date - timedelta(weeks=8)

    # Driver's routes from last 8 weeks
    driver_routes = (
        db.query(
            Ride.service_name,
            func.count(Ride.ride_id).label("ride_count"),
        )
        .filter(
            Ride.person_id == person_id,
            func.date(Ride.ride_start_ts) >= history_cutoff,
            func.date(Ride.ride_start_ts) < start_date,
            Ride.service_name.isnot(None),
            Ride.service_name != "",
        )
        .group_by(Ride.service_name)
        .order_by(func.count(Ride.ride_id).desc())
        .all()
    )

    if not driver_routes:
        return JSONResponse({"error": "No recent ride history found for this driver"}, status_code=404)

    driver = db.query(Person).filter(Person.person_id == person_id).first()
    driver_name = driver.full_name if driver else "Unknown"

    # Drivers with blackouts overlapping the leave period
    blacked_out_ids = {
        r[0] for r in db.query(DriverBlackout.person_id)
        .filter(
            DriverBlackout.start_date <= end_date.isoformat(),
            DriverBlackout.end_date >= start_date.isoformat(),
        )
        .all()
    }

    six_months_ago = start_date - timedelta(weeks=26)
    routes_out = []

    for route_row in driver_routes:
        service_name = route_row.service_name
        history_count = route_row.ride_count
        ride_count_estimate = max(1, round(history_count / 8 * weeks))

        # Other active drivers who've done this route in last 6 months
        candidates = (
            db.query(
                Ride.person_id,
                Person.full_name,
                func.count(Ride.ride_id).label("cnt"),
            )
            .join(Person, Ride.person_id == Person.person_id)
            .filter(
                Ride.service_name == service_name,
                Ride.person_id != person_id,
                func.date(Ride.ride_start_ts) >= six_months_ago,
                Person.active.is_(True),
            )
            .group_by(Ride.person_id, Person.full_name)
            .order_by(func.count(Ride.ride_id).desc())
            .all()
        )

        alternatives = [
            {
                "person_id": c.person_id,
                "name": c.full_name,
                "history_count": c.cnt,
                "has_conflicts": c.person_id in blacked_out_ids,
            }
            for c in candidates
        ]

        available = [a for a in alternatives if not a["has_conflicts"]]
        suggested_cover = available[0] if available else None

        routes_out.append({
            "service_name": service_name,
            "ride_count_estimate": ride_count_estimate,
            "history_count": history_count,
            "suggested_cover": suggested_cover,
            "alternatives": alternatives[:5],
            "hire_needed": suggested_cover is None,
        })

    hire_needed_count = sum(1 for r in routes_out if r["hire_needed"])

    return JSONResponse({
        "driver_name": driver_name,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "weeks": weeks,
        "routes": routes_out,
        "hire_needed_count": hire_needed_count,
        "covered_count": len(routes_out) - hire_needed_count,
    })


# ---------------------------------------------------------------------------
# Dispatch Session Log
# ---------------------------------------------------------------------------

@router.post("/session-log")
async def save_session_log(request: Request, db: Session = Depends(get_db)):
    """Save a completed dispatch planning session for historical reference.
    Read-only archive — never affects live dispatch data.
    """
    body = await request.json()
    session_date = body.get("date")
    changes = body.get("changes", [])
    if not session_date or not changes:
        return JSONResponse({"ok": True, "skipped": True})
    log = DispatchSessionLog(
        session_date=date.fromisoformat(session_date),
        changes_json=json.dumps(changes),
        change_count=len(changes),
    )
    db.add(log)
    db.commit()
    return JSONResponse({"ok": True, "id": log.id})
