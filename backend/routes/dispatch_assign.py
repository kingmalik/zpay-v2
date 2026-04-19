"""
Dispatch assignment route — /dispatch/assign

GET  /dispatch/assign          → render the assignment form
POST /dispatch/assign/search   → score drivers and return ranked recommendations
POST /dispatch/assign/confirm  → log a confirmed assignment to dispatch_assignment
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger("zpay.dispatch.assign")

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import Person, DispatchAssignment
from backend.services import firstalt_service, everdriven_service
from backend.services.everdriven_service import EverDrivenAuthError
from backend.services import maps_service

router = APIRouter(prefix="/dispatch", tags=["dispatch"])

_templates: Jinja2Templates | None = None


def _get_templates() -> Jinja2Templates:
    global _templates
    if _templates is None:
        templates_dir = Path(__file__).resolve().parents[1] / "templates"
        _templates = Jinja2Templates(directory=str(templates_dir))
    return _templates


# ---------------------------------------------------------------------------
# Helpers — build the same driver list as dispatch.py
# ---------------------------------------------------------------------------

def _build_driver_list(target_date: date, db: Session) -> list[dict]:
    """Return unified driver dicts with their trips for target_date."""
    # FirstAlt
    fa_trips: list[dict] = []
    try:
        fa_trips = firstalt_service.get_trips(target_date)
    except Exception as _e:
        logger.warning("FirstAlt trip fetch failed for assign: %s", _e)

    # EverDriven
    ed_runs: list[dict] = []
    try:
        ed_runs = everdriven_service.get_runs(target_date)
    except EverDrivenAuthError:
        logger.info("EverDriven not authenticated — skipping ED runs for assign")
    except Exception as _e:
        logger.warning("EverDriven run fetch failed for assign: %s", _e)

    # Build lookup maps
    fa_trip_map: dict[int, list] = {}
    for t in fa_trips:
        did = t.get("driverId")
        if did is not None:
            fa_trip_map.setdefault(did, []).append(t)

    ed_run_map: dict[str, list] = {}
    for r in ed_runs:
        did = r.get("driverId")
        if did is not None:
            ed_run_map.setdefault(str(did), []).append(r)

    # Load persons with dispatch IDs
    db_persons = (
        db.query(Person)
        .filter(
            (Person.firstalt_driver_id.isnot(None)) |
            (Person.everdriven_driver_id.isnot(None))
        )
        .filter(Person.active == True)
        .order_by(Person.full_name.asc())
        .all()
    )

    drivers = []
    for p in db_persons:
        fa_list = fa_trip_map.get(p.firstalt_driver_id, [])
        ed_list = ed_run_map.get(str(p.everdriven_driver_id or ""), [])

        for t in fa_list:
            t["_source"] = "firstalt"
        for r in ed_list:
            r["_source"] = "everdriven"

        all_trips = sorted(
            fa_list + ed_list,
            key=lambda x: x.get("firstPickUp") or "99:99",
        )

        sources = []
        if p.firstalt_driver_id is not None:
            sources.append("firstalt")
        if p.everdriven_driver_id is not None:
            sources.append("everdriven")

        drivers.append({
            "person_id":     p.person_id,
            "name":          p.full_name,
            "email":         p.email or "",
            "phone":         p.phone or "",
            "address":       p.home_address or "",
            "firstalt_id":   p.firstalt_driver_id,
            "everdriven_id": p.everdriven_driver_id,
            "sources":       sources,
            "trips":         all_trips,
            "trip_count":    len(all_trips),
        })

    return drivers


# ---------------------------------------------------------------------------
# GET /dispatch/assign — show the form
# ---------------------------------------------------------------------------

@router.get("/assign", name="dispatch_assign_page")
def dispatch_assign_page(request: Request):
    return _get_templates().TemplateResponse(
        request,
        "dispatch_assign.html",
        {"today": date.today().isoformat()},
    )


# ---------------------------------------------------------------------------
# POST /dispatch/assign/search — score and return top recommendations
# ---------------------------------------------------------------------------

@router.post("/assign/search", name="dispatch_assign_search")
def dispatch_assign_search(
    request: Request,
    pickup_address: str  = Form(...),
    dropoff_address: str = Form(...),
    pickup_time: str     = Form(...),
    dropoff_time: str    = Form(...),
    ride_date: str       = Form(...),
    notes: str           = Form(""),
    db: Session          = Depends(get_db),
):
    try:
        target_date = date.fromisoformat(ride_date)
    except ValueError:
        target_date = date.today()

    drivers = _build_driver_list(target_date, db)

    scored = maps_service.score_drivers(
        drivers,
        pickup_address=pickup_address,
        pickup_time_str=pickup_time,
        dropoff_time_str=dropoff_time,
    )

    # Keep top 5, exclude conflicts unless they're all we have
    non_conflict = [r for r in scored if r["tier"] < 5]
    conflict     = [r for r in scored if r["tier"] == 5]

    recommendations = (non_conflict[:5] if non_conflict else conflict[:3])

    # Return JSON if requested (Next.js frontend)
    accept = request.headers.get("accept", "")
    if "application/json" in accept:
        return JSONResponse({
            "recommendations": recommendations,
            "no_drivers":      len(recommendations) == 0,
        })

    return _get_templates().TemplateResponse(
        request,
        "dispatch_assign.html",
        {
            "today":           date.today().isoformat(),
            "recommendations": recommendations,
            "pickup_address":  pickup_address,
            "dropoff_address": dropoff_address,
            "pickup_time":     pickup_time,
            "dropoff_time":    dropoff_time,
            "ride_date":       ride_date,
            "notes":           notes,
            "no_drivers":      len(recommendations) == 0,
        },
    )


# ---------------------------------------------------------------------------
# POST /dispatch/assign/confirm — log confirmed assignment
# ---------------------------------------------------------------------------

@router.post("/assign/confirm", name="dispatch_assign_confirm")
def dispatch_assign_confirm(
    person_id: int       = Form(...),
    pickup_address: str  = Form(...),
    dropoff_address: str = Form(...),
    pickup_time: str     = Form(...),
    dropoff_time: str    = Form(...),
    ride_date: str       = Form(...),
    source: str          = Form("firstalt"),
    notes: str           = Form(""),
    db: Session          = Depends(get_db),
):
    try:
        assigned_date = date.fromisoformat(ride_date)
    except ValueError:
        assigned_date = date.today()

    person = db.query(Person).filter(Person.person_id == person_id).first()
    if not person:
        return JSONResponse({"error": "Driver not found"}, status_code=404)

    # Determine source from person's IDs
    if person.firstalt_driver_id is not None:
        resolved_source = "firstalt"
    elif person.everdriven_driver_id is not None:
        resolved_source = "everdriven"
    else:
        resolved_source = source

    assignment = DispatchAssignment(
        assigned_date   = assigned_date,
        pickup_address  = pickup_address,
        dropoff_address = dropoff_address,
        pickup_time     = pickup_time,
        dropoff_time    = dropoff_time,
        person_id       = person_id,
        source          = resolved_source,
        notes           = notes or None,
        created_at      = datetime.utcnow(),
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)

    return JSONResponse({
        "ok":            True,
        "assignment_id": assignment.assignment_id,
        "driver_name":   person.full_name,
        "message":       f"{person.full_name} confirmed for {pickup_address} → {dropoff_address} on {ride_date}",
    })
