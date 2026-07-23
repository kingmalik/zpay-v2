"""
S5 — Assignment Helper + Coverage API.

Endpoints for ranking drivers on new-ride emails, standing route rosters +
backups, and call-out coverage solving. See MASTER-PLAN-2026-07 S5 for the
frozen API contract these mirror exactly — field names matter, the frontend
is built against this shape.

Auth: read endpoints require any authenticated session (global AuthMiddleware
already gates every /api/data/* path); writes mirror the existing
/api/data/rides/{id}/assign and /api/data/people/{id}/language precedent —
no additional require_role restriction beyond being logged in.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import Person, RideIntake, RouteBackup, RouteRoster
from backend.services.assignment_service import DriverSuggestion, PricingResult, suggest_drivers
from backend.services.coverage_service import backup_candidates, find_coverage, sync_rosters
from backend.services.ride_intake_service import build_reply_draft, parse_intake

router = APIRouter(prefix="/api/data/assignment", tags=["assignment"])


def _suggestion_dict(s: DriverSuggestion) -> dict:
    return {
        "person_id": s.person_id,
        "name": s.name,
        "tier": s.tier,
        "score": s.score,
        "reasons": list(s.reasons),
        "familiar_rides": s.familiar_rides,
        "load_recent": s.load_recent,
        "home_area": s.home_area,
    }


def _pricing_dict(p: PricingResult) -> dict:
    return {
        "predicted_rate": p.predicted_rate,
        "margin": p.margin,
        "margin_pct": p.margin_pct,
        "unprofitable": p.unprofitable,
        "evidence": p.evidence,
        "manual_review": p.manual_review,
        "pass_through_suggestion": p.pass_through_suggestion,
    }


def _driver_dict(person_id: Optional[int], name_lookup: dict) -> Optional[dict]:
    if person_id is None:
        return None
    return {"person_id": person_id, "name": name_lookup.get(person_id, "Unknown")}


def _roster_dict(db: Session, roster: RouteRoster) -> dict:
    people_ids = {b.person_id for b in roster.backups}
    if roster.primary_person_id:
        people_ids.add(roster.primary_person_id)
    names = {
        p.person_id: p.full_name
        for p in db.query(Person).filter(Person.person_id.in_(people_ids)).all()
    } if people_ids else {}

    return {
        "roster_id": roster.roster_id,
        "source": roster.source,
        "school": roster.route_school,
        "direction": roster.route_direction,
        "number": roster.route_number,
        "is_odt": roster.route_is_odt,
        "service_name_sample": roster.service_name_sample,
        "primary": _driver_dict(roster.primary_person_id, names),
        "backups": [
            {"person_id": b.person_id, "name": names.get(b.person_id, "Unknown"), "rank": b.rank}
            for b in sorted(roster.backups, key=lambda b: b.rank)
        ],
        "last_seen_ride_ts": roster.last_seen_ride_ts.isoformat() if roster.last_seen_ride_ts else None,
        "active": roster.active,
    }


def _intake_dict(intake: RideIntake) -> dict:
    return {
        "intake_id": intake.intake_id,
        "created_at": intake.created_at.isoformat() if intake.created_at else None,
        "status": intake.status,
        "parsed": intake.parsed or {},
        "decision_reason": intake.decision_reason,
    }


@router.post("/intake")
async def create_intake(request: Request, db: Session = Depends(get_db)):
    """Parse a new-ride email, rank drivers, predict pricing, draft a reply."""
    body = await request.json()
    raw_text = (body.get("raw_text") or "").strip()
    if not raw_text:
        raise HTTPException(status_code=400, detail="raw_text required")

    parsed = parse_intake(raw_text)

    suggestions, pricing = suggest_drivers(
        db,
        school=parsed.get("school"),
        direction=parsed.get("direction"),
        miles=parsed.get("miles"),
        net_pay=parsed.get("net_pay"),
        wheelchair=bool(parsed.get("wheelchair")),
        is_odt=bool(parsed.get("is_odt")),
    )
    reply_draft = build_reply_draft(parsed)

    intake = RideIntake(raw_text=raw_text, parsed=parsed, status="draft", reply_draft=reply_draft)
    db.add(intake)
    db.commit()
    db.refresh(intake)

    return JSONResponse({
        "intake_id": intake.intake_id,
        "parsed": parsed,
        "suggestions": [_suggestion_dict(s) for s in suggestions],
        "pricing": _pricing_dict(pricing),
        "reply_draft": reply_draft,
    })


@router.get("/intakes")
def list_intakes(status: Optional[str] = Query(None), db: Session = Depends(get_db)):
    q = db.query(RideIntake)
    if status:
        q = q.filter(RideIntake.status == status)
    intakes = q.order_by(RideIntake.created_at.desc()).all()
    return JSONResponse({"intakes": [_intake_dict(i) for i in intakes]})


@router.post("/intake/{intake_id}/decision")
async def decide_intake(intake_id: int, request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    decision = (body.get("decision") or "").strip().lower()
    reason = body.get("reason")
    if decision not in ("take", "pass"):
        raise HTTPException(status_code=400, detail="decision must be 'take' or 'pass'")

    intake = db.query(RideIntake).filter(RideIntake.intake_id == intake_id).first()
    if not intake:
        raise HTTPException(status_code=404, detail="Intake not found")

    intake.status = "taken" if decision == "take" else "passed"
    intake.decision_reason = reason
    intake.decided_at = datetime.now(timezone.utc)
    intake.reply_draft = build_reply_draft(intake.parsed or {}, decision_hint=decision)
    db.commit()
    db.refresh(intake)

    return JSONResponse(_intake_dict(intake))


@router.get("/suggest")
def suggest(
    school: Optional[str] = Query(None),
    direction: Optional[str] = Query(None),
    miles: Optional[float] = Query(None),
    net_pay: Optional[float] = Query(None),
    wheelchair: bool = Query(False),
    db: Session = Depends(get_db),
):
    suggestions, pricing = suggest_drivers(
        db, school=school, direction=direction, miles=miles, net_pay=net_pay, wheelchair=wheelchair,
    )
    return JSONResponse({
        "suggestions": [_suggestion_dict(s) for s in suggestions],
        "pricing": _pricing_dict(pricing),
    })


@router.get("/rosters")
def list_rosters(db: Session = Depends(get_db)):
    rosters = db.query(RouteRoster).order_by(RouteRoster.route_school, RouteRoster.route_direction).all()
    return JSONResponse({"rosters": [_roster_dict(db, r) for r in rosters]})


@router.post("/rosters/sync")
def sync_rosters_endpoint(db: Session = Depends(get_db)):
    result = sync_rosters(db)
    return JSONResponse(result)


@router.get("/rosters/{roster_id}/backup-candidates")
def roster_backup_candidates(roster_id: int, db: Session = Depends(get_db)):
    roster = db.query(RouteRoster).filter(RouteRoster.roster_id == roster_id).first()
    if not roster:
        raise HTTPException(status_code=404, detail="Roster not found")
    candidates = backup_candidates(db, roster_id)
    return JSONResponse({"candidates": [_suggestion_dict(c) for c in candidates]})


@router.put("/rosters/{roster_id}/backups")
async def set_roster_backups(roster_id: int, request: Request, db: Session = Depends(get_db)):
    roster = db.query(RouteRoster).filter(RouteRoster.roster_id == roster_id).first()
    if not roster:
        raise HTTPException(status_code=404, detail="Roster not found")

    body = await request.json()
    backups = body.get("backups", [])

    db.query(RouteBackup).filter(RouteBackup.roster_id == roster_id).delete()
    db.flush()
    for entry in backups:
        person_id = entry.get("person_id")
        rank = entry.get("rank")
        if person_id is None or rank is None:
            continue
        db.add(RouteBackup(roster_id=roster_id, person_id=int(person_id), rank=int(rank)))
    db.commit()
    db.refresh(roster)

    return JSONResponse(_roster_dict(db, roster))


@router.get("/coverage")
def coverage(
    roster_id: int = Query(...),
    date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    roster = db.query(RouteRoster).filter(RouteRoster.roster_id == roster_id).first()
    if not roster:
        raise HTTPException(status_code=404, detail="Roster not found")

    if date:
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    else:
        target_date = datetime.now(timezone.utc).date()

    result = find_coverage(db, roster_id, target_date)
    return JSONResponse(result)


@router.get("/home-gaps")
def home_gaps(db: Session = Depends(get_db)):
    from sqlalchemy import func

    from backend.db.models import Ride

    people = (
        db.query(Person)
        .filter(Person.active.is_(True))
        .filter(Person.status == "active")
        .filter((Person.home_area.is_(None)) | (Person.home_area == ""))
        .all()
    )
    ride_counts = dict(
        db.query(Ride.person_id, func.count(Ride.ride_id))
        .filter(Ride.person_id.in_([p.person_id for p in people]))
        .group_by(Ride.person_id)
        .all()
    ) if people else {}

    drivers = sorted(
        (
            {"person_id": p.person_id, "name": p.full_name, "recent_rides": ride_counts.get(p.person_id, 0)}
            for p in people
        ),
        key=lambda d: d["recent_rides"],
        reverse=True,
    )
    return JSONResponse({"drivers": drivers})
