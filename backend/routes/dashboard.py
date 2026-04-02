"""
Dashboard route — serves the main Z-Pay dashboard at /.
Pulls high-level stats from the DB without duplicating summary logic.
"""
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, cast, Date, distinct
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import Ride, Person, PayrollBatch

router = APIRouter(tags=["dashboard"])

_templates = None


def templates():
    global _templates
    if _templates is None:
        templates_dir = Path(__file__).resolve().parents[1] / "templates"
        _templates = Jinja2Templates(directory=str(templates_dir))
    return _templates


def _build_stats(db: Session) -> dict:
    row = db.query(
        func.sum(Ride.net_pay).label("total_revenue"),
        func.sum(Ride.z_rate).label("total_cost"),
        func.sum(Ride.net_pay - Ride.z_rate).label("total_profit"),
        func.count(Ride.ride_id).label("total_rides"),
    ).one()

    total_revenue = float(row.total_revenue or 0)
    total_cost = float(row.total_cost or 0)
    total_profit = float(row.total_profit or 0)
    total_rides = int(row.total_rides or 0)
    avg_profit = round(total_profit / total_rides, 2) if total_rides else 0.0

    active_drivers = db.query(func.count(distinct(Ride.person_id))).scalar() or 0

    # Acumen vs Maz split (by company source field)
    acumen_rides = (
        db.query(func.count(Ride.ride_id))
        .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
        .filter(PayrollBatch.source == "acumen")
        .scalar() or 0
    )
    maz_rides = (
        db.query(func.count(Ride.ride_id))
        .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
        .filter(PayrollBatch.source == "maz")
        .scalar() or 0
    )

    acumen_revenue = (
        db.query(func.sum(Ride.net_pay))
        .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
        .filter(PayrollBatch.source == "acumen")
        .scalar() or 0
    )
    maz_revenue = (
        db.query(func.sum(Ride.net_pay))
        .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
        .filter(PayrollBatch.source == "maz")
        .scalar() or 0
    )

    return {
        "total_revenue": round(total_revenue, 2),
        "total_cost": round(total_cost, 2),
        "total_profit": round(total_profit, 2),
        "total_rides": total_rides,
        "active_drivers": active_drivers,
        "avg_profit_per_ride": avg_profit,
        "acumen_rides": acumen_rides,
        "maz_rides": maz_rides,
        "acumen_revenue": round(float(acumen_revenue), 2),
        "maz_revenue": round(float(maz_revenue), 2),
    }


def _build_recent_batches(db: Session, limit: int = 10):
    batches = (
        db.query(PayrollBatch)
        .order_by(PayrollBatch.uploaded_at.desc())
        .limit(limit)
        .all()
    )
    rows = []
    for b in batches:
        rides_q = db.query(
            func.count(Ride.ride_id).label("ride_count"),
            func.sum(Ride.net_pay).label("total_net_pay"),
            func.sum(Ride.z_rate).label("total_z_rate"),
            func.sum(Ride.net_pay - Ride.z_rate).label("total_profit"),
        ).filter(Ride.payroll_batch_id == b.payroll_batch_id).one()

        total_net_pay = float(rides_q.total_net_pay or 0)
        total_z_rate = float(rides_q.total_z_rate or 0)
        total_profit = float(rides_q.total_profit or 0)

        rows.append({
            "batch_id": b.payroll_batch_id,
            "company_name": b.company_name,
            "source": b.source or "",
            "period_start": b.period_start.strftime("%-m/%-d/%Y") if b.period_start else "—",
            "period_end": b.period_end.strftime("%-m/%-d/%Y") if b.period_end else "—",
            "ride_count": int(rides_q.ride_count or 0),
            "total_net_pay": total_net_pay,
            "total_z_rate": total_z_rate,
            "total_profit": total_profit,
        })
    return rows


@router.get("/", response_class=HTMLResponse, name="dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):
    try:
        stats = _build_stats(db)
        recent_batches = _build_recent_batches(db)
    except Exception:
        stats = {
            "total_revenue": 0, "total_cost": 0, "total_profit": 0,
            "total_rides": 0, "active_drivers": 0, "avg_profit_per_ride": 0,
            "acumen_rides": 0, "maz_rides": 0,
            "acumen_revenue": 0, "maz_revenue": 0,
        }
        recent_batches = []

    return templates().TemplateResponse(
        request,
        "dashboard.html",
        {
            "stats": stats,
            "recent_batches": recent_batches,
        },
    )
