"""
Dispatch Simulation routes — read-only sandbox board.
No database writes. Loads live driver/trip data from the same source as
the main dispatch page, seeds a heuristic geo cache, then scores drivers
using the existing maps_service.score_drivers() logic.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.routes.dispatch import (
    _fetch_dispatch_data,
    _load_db_persons,
    _auto_link_drivers,
    _auto_create_persons,
    _build_driver_cards,
)
from backend.services import maps_service

router = APIRouter(prefix="/dispatch", tags=["dispatch"])

_templates = None


def _get_templates() -> Jinja2Templates:
    global _templates
    if _templates is None:
        templates_dir = Path(__file__).resolve().parents[1] / "templates"
        _templates = Jinja2Templates(directory=str(templates_dir))
    return _templates


# ---------------------------------------------------------------------------
# Heuristic cache seeding — avoids real Maps API calls during simulation
# ---------------------------------------------------------------------------

def _sim_estimate_minutes(origin: str, destination: str):
    """Return a heuristic drive-time estimate in minutes without hitting Maps API."""
    if not origin or not destination:
        return None
    o, d = origin.strip().lower(), destination.strip().lower()
    if o == d:
        return 2.0
    CITIES = ["seattle", "bellevue", "redmond", "kirkland", "renton", "kent", "auburn"]
    oc = next((c for c in CITIES if c in o), None)
    dc = next((c for c in CITIES if c in d), None)
    # Same zip/street suffix
    if o.split()[-1] == d.split()[-1]:
        return 12.0
    if oc and oc == dc:
        return 15.0
    if oc and dc:
        return 28.0
    return 20.0


def _seed_cache(addresses: list[str]) -> None:
    """Pre-populate maps_service._geo_cache with heuristic estimates."""
    seen = list({a.strip().lower() for a in addresses if a and a.strip()})
    for orig in seen:
        for dest in seen:
            if orig == dest:
                continue
            key = f"{orig}|{dest}"
            if key not in maps_service._geo_cache:
                maps_service._geo_cache[key] = _sim_estimate_minutes(orig, dest)


# ---------------------------------------------------------------------------
# GET /dispatch/simulate
# ---------------------------------------------------------------------------

@router.get("/simulate", name="dispatch_simulate_page")
async def dispatch_simulate_page(
    request: Request,
    db: Session = Depends(get_db),
):
    target_date = date.today()

    data = await _fetch_dispatch_data(target_date, force_refresh=False)

    db_persons = _load_db_persons(db)
    _auto_link_drivers(data, db_persons, db)
    _auto_create_persons(data, db_persons, db)
    db_persons = _load_db_persons(db)

    drivers, unassigned, _dashboard = _build_driver_cards(data, db_persons, source=None)

    return _get_templates().TemplateResponse(
        request,
        "dispatch_simulate.html",
        {
            "drivers":    drivers,
            "unassigned": unassigned,
            "sim_date":   target_date.isoformat(),
        },
    )


# ---------------------------------------------------------------------------
# POST /dispatch/simulate/optimize
# ---------------------------------------------------------------------------

@router.post("/simulate/optimize", name="dispatch_simulate_optimize")
async def dispatch_simulate_optimize(request: Request):
    """
    Accept the current board state and return scored recommendations for
    each unassigned trip.  No DB writes, no real Maps API calls.

    Request JSON:
      {
        "drivers": [{"person_id": N, "name": "...", "address": "...", "trips": [...]}],
        "trips_to_optimize": [{"name": "...", "pickup_time": "HH:MM",
                               "dropoff_time": "HH:MM", "pickup_address": "..."}]
      }

    Response JSON:
      {
        "suggestions": [
          {
            "trip_name": "...",
            "recommendations": [
              {"person_id": N, "name": "...", "tier": N, "tier_label": "...", "reason": "..."},
              ...
            ]
          },
          ...
        ]
      }
    """
    body = await request.json()
    drivers: list[dict] = body.get("drivers", [])
    trips_to_optimize: list[dict] = body.get("trips_to_optimize", [])

    if not trips_to_optimize:
        return JSONResponse({"suggestions": []})

    # Collect all addresses so we can seed the geo cache
    all_addresses: list[str] = []
    for d in drivers:
        if d.get("address"):
            all_addresses.append(d["address"])
        for t in d.get("trips", []):
            for field in ("lastDropoffAddress", "dropoffAddress", "dropOff", "pickupAddress"):
                if t.get(field):
                    all_addresses.append(t[field])
    for t in trips_to_optimize:
        if t.get("pickup_address"):
            all_addresses.append(t["pickup_address"])

    _seed_cache(all_addresses)

    suggestions = []
    for trip in trips_to_optimize:
        trip_name     = trip.get("name") or "Unnamed trip"
        pickup_addr   = trip.get("pickup_address") or ""
        pickup_time   = trip.get("pickup_time") or ""
        dropoff_time  = trip.get("dropoff_time") or ""

        scored = maps_service.score_drivers(
            drivers,
            pickup_addr,
            pickup_time,
            dropoff_time,
        )

        top3 = scored[:3]
        recommendations = [
            {
                "person_id": r["person_id"],
                "name":      r["name"],
                "tier":      r["tier"],
                "tier_label": r["tier_label"],
                "reason":    r["reason"],
            }
            for r in top3
        ]

        suggestions.append({
            "trip_name":       trip_name,
            "recommendations": recommendations,
        })

    return JSONResponse({"suggestions": suggestions})
