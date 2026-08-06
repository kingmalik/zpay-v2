"""
School address book — S10 Season Assignment Board.

One school row per distinct school name (deduped on a normalized key: lower-
cased, single-spaced). Address/city/district are filled once by mom via the
`/schools` PATCH endpoint and back-filled onto every season_ride pooled at
that school forever (docs/SEASON-BOARD-PLAN.md §Business rule 7).

Sidedness for the back-fill (plan doc): IB rides run TO school in the
morning, so the school sits on the DROPOFF side. OB rides run home FROM
school in the afternoon, so the school sits on the PICKUP side.
"""
from __future__ import annotations

import re
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db.models import School, SeasonRide


def _normalize(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().lower()


def get_or_create_school(db: Session, display_name: str) -> School:
    """Find the school row for `display_name`, creating it if new.

    Dedupe key is the normalized (lower/single-spaced) name — FA's casing
    drifts ("Risalah ES" vs "risalah es") but it's the same school.
    """
    if not display_name or not display_name.strip():
        raise ValueError("display_name is required")

    normalized = _normalize(display_name)
    existing = db.query(School).filter(School.name == normalized).first()
    if existing is not None:
        return existing

    school = School(name=normalized, display_name=display_name.strip())
    db.add(school)
    db.flush()
    return school


def apply_school_address(
    db: Session,
    school_id: int,
    address: Optional[str] = None,
    city: Optional[str] = None,
    district: Optional[str] = None,
) -> School:
    """Set address/city/district on a school and back-fill NULL fields on
    every season_ride at that school.

    IB rides: school is the dropoff side -> fills dropoff_address/city.
    OB rides: school is the pickup side -> fills pickup_address/city.
    Only NULL fields are touched — a ride with its own address already
    entered is never overwritten.
    """
    school = db.query(School).filter(School.school_id == school_id).first()
    if school is None:
        raise ValueError(f"school {school_id} not found")

    if address is not None:
        school.address = address
    if city is not None:
        school.city = city
    if district is not None:
        school.district = district
    db.flush()

    rides = db.query(SeasonRide).filter(SeasonRide.school_id == school_id).all()
    for ride in rides:
        if ride.route_direction == "IB":
            if address is not None and ride.dropoff_address is None:
                ride.dropoff_address = address
            if city is not None and ride.dropoff_city is None:
                ride.dropoff_city = city
        elif ride.route_direction == "OB":
            if address is not None and ride.pickup_address is None:
                ride.pickup_address = address
            if city is not None and ride.pickup_city is None:
                ride.pickup_city = city

    db.flush()
    return school


def schools_overview(db: Session) -> list[dict]:
    """List every school with its ride_count and whether it still needs an
    address filled in (surfaced first by the /schools UI)."""
    counts = dict(
        db.query(SeasonRide.school_id, func.count(SeasonRide.season_ride_id))
        .filter(SeasonRide.school_id.isnot(None))
        .group_by(SeasonRide.school_id)
        .all()
    )

    schools = db.query(School).order_by(School.display_name).all()
    out = []
    for school in schools:
        out.append({
            "school_id": school.school_id,
            "name": school.name,
            "display_name": school.display_name,
            "address": school.address,
            "city": school.city,
            "district": school.district,
            "notes": school.notes,
            "ride_count": counts.get(school.school_id, 0),
            "needs_address": school.address is None,
        })
    out.sort(key=lambda s: (not s["needs_address"], s["display_name"].lower()))
    return out
