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
  GET  /dispatch/manage/reliability      → driver reliability scores (last 90 days)
  GET  /dispatch/manage/weekly-load      → ride counts per driver for a week
"""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import Person, DriverPromise, DriverBlackout, TripNotification, Ride
from backend.routes.dispatch_assign import _build_driver_list
from backend.services import maps_service

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
# Driver Reliability (last 90 days from TripNotification)
# ---------------------------------------------------------------------------

@router.get("/reliability")
def driver_reliability(db: Session = Depends(get_db)):
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
