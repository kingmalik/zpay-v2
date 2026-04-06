from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session
from starlette.templating import Jinja2Templates

from backend.db import get_db
from backend.db.models import Ride, Person, DriverBalance

router = APIRouter(prefix="/alerts", tags=["alerts"])


def _templates(request: Request) -> Jinja2Templates:
    t = getattr(request.app.state, "templates", None)
    if t is not None:
        return t
    base = Path(__file__).resolve().parents[1]
    return Jinja2Templates(directory=str(base / "templates"))


@router.get("", name="alerts_page")
def alerts_page(request: Request, db: Session = Depends(get_db)):
    """Render the Alerts dashboard page."""
    unmatched_rates = (
        db.query(func.count(Ride.ride_id))
        .filter(Ride.z_rate == 0)
        .scalar() or 0
    )
    withheld_balances = (
        db.query(func.count(func.distinct(DriverBalance.person_id)))
        .filter(DriverBalance.carried_over > 0)
        .scalar() or 0
    )
    cutoff = datetime.now(timezone.utc) - timedelta(days=60)
    active_driver_ids = (
        db.query(Person.person_id).filter(Person.active == True).subquery()  # noqa: E712
    )
    recent_driver_ids = (
        db.query(Ride.person_id).filter(Ride.ride_start_ts >= cutoff).distinct().subquery()
    )
    inactive_drivers = (
        db.query(func.count(active_driver_ids.c.person_id))
        .filter(active_driver_ids.c.person_id.notin_(
            db.query(recent_driver_ids.c.person_id)
        ))
        .scalar() or 0
    )
    total = int(unmatched_rates) + int(withheld_balances) + int(inactive_drivers)
    return _templates(request).TemplateResponse(
        request,
        "alerts.html",
        {
            "unmatched_rates": int(unmatched_rates),
            "withheld_balances": int(withheld_balances),
            "inactive_drivers": int(inactive_drivers),
            "total": total,
        },
    )


@router.get("/data")
def alerts_data(db: Session = Depends(get_db)):
    """Return counts for each alert condition."""

    # 1. Rides with no rate set (z_rate = 0)
    unmatched_rates = (
        db.query(func.count(Ride.ride_id))
        .filter(Ride.z_rate == 0)
        .scalar()
        or 0
    )

    # 2. Drivers with a withheld (carried-over) balance > 0
    withheld_balances = (
        db.query(func.count(func.distinct(DriverBalance.person_id)))
        .filter(DriverBalance.carried_over > 0)
        .scalar()
        or 0
    )

    # 3. Drivers (active=True in Person) with no rides in the last 60 days
    cutoff = datetime.now(timezone.utc) - timedelta(days=60)
    active_driver_ids = (
        db.query(Person.person_id)
        .filter(Person.active == True)  # noqa: E712
        .subquery()
    )
    recent_driver_ids = (
        db.query(Ride.person_id)
        .filter(Ride.ride_start_ts >= cutoff)
        .distinct()
        .subquery()
    )
    inactive_drivers = (
        db.query(func.count(active_driver_ids.c.person_id))
        .filter(active_driver_ids.c.person_id.notin_(
            db.query(recent_driver_ids.c.person_id)
        ))
        .scalar()
        or 0
    )

    total = int(unmatched_rates) + int(withheld_balances) + int(inactive_drivers)

    return JSONResponse({
        "unmatched_rates": int(unmatched_rates),
        "withheld_balances": int(withheld_balances),
        "inactive_drivers": int(inactive_drivers),
        "total": total,
    })
