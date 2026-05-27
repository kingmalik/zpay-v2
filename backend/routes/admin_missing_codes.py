"""
Admin — Missing Paychex Codes endpoint.

Returns drivers who had at least one ride in the last 30 days but are
missing their Acumen paycheck_code, their Maz paycheck_code_maz, or both.

Endpoint: GET /api/data/admin/missing-paychex-codes
Auth:      admin only (require_role("admin"))
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.db import get_db
from backend.db.models import Person, Ride
from backend.utils.roles import require_role

router = APIRouter(prefix="/api/data/admin", tags=["admin"])


@router.get(
    "/missing-paychex-codes",
    dependencies=[Depends(require_role("admin"))],
)
def get_missing_paychex_codes(db: Session = Depends(get_db)) -> JSONResponse:
    """
    Returns three groups of active drivers who had rides in the last 30 days:
      - missing_acumen: have Acumen rides but no paycheck_code
      - missing_maz:    have Maz rides but no paycheck_code_maz
      - missing_both:   missing both codes
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    # Count rides per driver per source in the last 30 days
    acumen_counts = (
        db.query(Ride.person_id, func.count(Ride.ride_id).label("cnt"))
        .filter(
            Ride.source == "firstalt",
            Ride.ride_start_ts >= cutoff,
            Ride.removed_at.is_(None),
        )
        .group_by(Ride.person_id)
        .all()
    )

    maz_counts = (
        db.query(Ride.person_id, func.count(Ride.ride_id).label("cnt"))
        .filter(
            Ride.source == "everdriven",
            Ride.ride_start_ts >= cutoff,
            Ride.removed_at.is_(None),
        )
        .group_by(Ride.person_id)
        .all()
    )

    # Build lookup dicts: person_id -> ride_count
    acumen_map: dict[int, int] = {r.person_id: r.cnt for r in acumen_counts}
    maz_map: dict[int, int] = {r.person_id: r.cnt for r in maz_counts}

    # Fetch person rows for anyone who appeared in either group
    relevant_ids = set(acumen_map) | set(maz_map)
    if not relevant_ids:
        return JSONResponse({
            "missing_acumen": [],
            "missing_maz": [],
            "missing_both": [],
        })

    persons = (
        db.query(Person)
        .filter(Person.person_id.in_(relevant_ids))
        .all()
    )

    missing_acumen: list[dict] = []
    missing_maz: list[dict] = []
    missing_both: list[dict] = []

    for p in persons:
        in_acumen = p.person_id in acumen_map
        in_maz = p.person_id in maz_map
        no_acumen_code = not p.paycheck_code
        no_maz_code = not p.paycheck_code_maz

        # Total rides in last 30d across both sources
        rides_last_30d = acumen_map.get(p.person_id, 0) + maz_map.get(p.person_id, 0)

        row: dict = {
            "person_id": p.person_id,
            "name": p.full_name,
            "rides_last_30d": rides_last_30d,
            "paycheck_code": p.paycheck_code,
            "paycheck_code_maz": p.paycheck_code_maz,
        }

        if in_acumen and no_acumen_code and in_maz and no_maz_code:
            missing_both.append(row)
        elif in_acumen and no_acumen_code:
            missing_acumen.append({**row, "paycheck_code_maz": p.paycheck_code_maz})
        elif in_maz and no_maz_code:
            missing_maz.append({**row, "paycheck_code": p.paycheck_code})

    # Sort by name for stable display
    for lst in (missing_acumen, missing_maz, missing_both):
        lst.sort(key=lambda x: x["name"].lower())

    return JSONResponse({
        "missing_acumen": missing_acumen,
        "missing_maz": missing_maz,
        "missing_both": missing_both,
    })
