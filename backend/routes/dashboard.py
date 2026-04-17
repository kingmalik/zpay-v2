"""
Dashboard route — serves the main Z-Pay dashboard at /.
Pulls high-level stats from the DB without duplicating summary logic.
"""
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime, timezone, timedelta

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
    # ALL
    row = db.query(
        func.sum(Ride.net_pay).label("total_revenue"),
        func.sum(Ride.z_rate).label("total_cost"),
        func.sum(Ride.net_pay - Ride.z_rate - (Ride.gross_pay - Ride.net_pay)).label("total_profit"),
        func.count(Ride.ride_id).label("total_rides"),
    ).one()

    total_revenue = float(row.total_revenue or 0)
    total_cost = float(row.total_cost or 0)
    total_profit = float(row.total_profit or 0)
    total_rides = int(row.total_rides or 0)
    avg_profit = round(total_profit / total_rides, 2) if total_rides else 0.0
    total_margin_pct = round(total_profit / total_revenue * 100, 1) if total_revenue > 0 else 0.0

    active_drivers = db.query(func.count(distinct(Ride.person_id))).scalar() or 0

    # FirstAlt (source="acumen")
    fa_row = db.query(
        func.sum(Ride.net_pay).label("revenue"),
        func.sum(Ride.z_rate).label("cost"),
        func.sum(Ride.net_pay - Ride.z_rate - (Ride.gross_pay - Ride.net_pay)).label("profit"),
        func.count(Ride.ride_id).label("rides"),
    ).join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id
    ).filter(PayrollBatch.source == "acumen").one()

    fa_revenue = float(fa_row.revenue or 0)
    fa_cost = float(fa_row.cost or 0)
    fa_profit = float(fa_row.profit or 0)
    fa_rides = int(fa_row.rides or 0)
    fa_drivers = db.query(func.count(distinct(Ride.person_id))).join(
        PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id
    ).filter(PayrollBatch.source == "acumen").scalar() or 0
    fa_margin_pct = round(fa_profit / fa_revenue * 100, 1) if fa_revenue > 0 else 0.0

    # EverDriven (source="maz")
    ed_row = db.query(
        func.sum(Ride.net_pay).label("revenue"),
        func.sum(Ride.z_rate).label("cost"),
        func.sum(Ride.net_pay - Ride.z_rate - (Ride.gross_pay - Ride.net_pay)).label("profit"),
        func.count(Ride.ride_id).label("rides"),
    ).join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id
    ).filter(PayrollBatch.source == "maz").one()

    ed_revenue = float(ed_row.revenue or 0)
    ed_cost = float(ed_row.cost or 0)
    ed_profit = float(ed_row.profit or 0)
    ed_rides = int(ed_row.rides or 0)
    ed_drivers = db.query(func.count(distinct(Ride.person_id))).join(
        PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id
    ).filter(PayrollBatch.source == "maz").scalar() or 0
    ed_margin_pct = round(ed_profit / ed_revenue * 100, 1) if ed_revenue > 0 else 0.0

    return {
        # ALL
        "total_revenue": round(total_revenue, 2),
        "total_cost": round(total_cost, 2),
        "total_profit": round(total_profit, 2),
        "total_rides": total_rides,
        "active_drivers": active_drivers,
        "avg_profit_per_ride": avg_profit,
        "total_margin_pct": total_margin_pct,
        # FirstAlt
        "fa_revenue": round(fa_revenue, 2),
        "fa_cost": round(fa_cost, 2),
        "fa_profit": round(fa_profit, 2),
        "fa_rides": fa_rides,
        "fa_drivers": fa_drivers,
        "fa_margin_pct": fa_margin_pct,
        # EverDriven
        "ed_revenue": round(ed_revenue, 2),
        "ed_cost": round(ed_cost, 2),
        "ed_profit": round(ed_profit, 2),
        "ed_rides": ed_rides,
        "ed_drivers": ed_drivers,
        "ed_margin_pct": ed_margin_pct,
    }


def _get_school_week_map(db: Session) -> dict:
    """Returns {(source, week_start_date): school_week_num} for all batches.

    EverDriven (maz): week number extracted from batch_ref e.g. "WASO291-OY2026W03" → 3.
    Acumen: week number assigned by rank of sorted week_start (earliest = W1).
    """
    import re
    result: dict = {}

    # EverDriven: parse from batch_ref
    maz_rows = (
        db.query(PayrollBatch.week_start, PayrollBatch.batch_ref)
        .filter(
            PayrollBatch.source == "maz",
            PayrollBatch.week_start.isnot(None),
            PayrollBatch.batch_ref.isnot(None),
        )
        .distinct(PayrollBatch.week_start)
        .all()
    )
    for ws, batch_ref in maz_rows:
        m = re.search(r'W(\d+)$', batch_ref or '')
        if m:
            result[("maz", ws)] = int(m.group(1))

    # Acumen: rank by sorted week_start
    acumen_rows = (
        db.query(PayrollBatch.week_start)
        .filter(PayrollBatch.source == "acumen", PayrollBatch.week_start.isnot(None))
        .distinct()
        .order_by(PayrollBatch.week_start)
        .all()
    )
    for rank, (ws,) in enumerate(acumen_rows, start=1):
        result[("acumen", ws)] = rank

    return result


def _build_ytd_weeks(db: Session, limit: int = 5) -> list[dict]:
    """Last N school weeks — compact week-by-week for dashboard, labelled Week 1 … Week N."""
    from datetime import date
    year = date.today().year

    school_week_map = _get_school_week_map(db)

    # Get finalized batches for current year
    finalized_batches = (
        db.query(PayrollBatch)
        .filter(
            PayrollBatch.finalized_at.isnot(None),
            func.extract("year", PayrollBatch.week_start) == year,
        )
        .order_by(PayrollBatch.week_start.desc())
        .all()
    )

    # Group by school week number
    weeks: dict = {}
    for batch in finalized_batches:
        ws = batch.week_start
        if ws is None:
            continue
        week_num = school_week_map.get((batch.source, ws))
        if week_num is None:
            continue
        if week_num not in weeks:
            weeks[week_num] = {"fa_revenue": 0.0, "fa_profit": 0.0, "ed_revenue": 0.0, "ed_profit": 0.0, "rides": 0}

        rides_q = db.query(
            func.sum(Ride.net_pay).label("revenue"),
            func.sum(Ride.net_pay - Ride.z_rate).label("profit"),
            func.count(Ride.ride_id).label("rides"),
        ).filter(Ride.payroll_batch_id == batch.payroll_batch_id).one()

        rev = float(rides_q.revenue or 0)
        prof = float(rides_q.profit or 0)
        rcount = int(rides_q.rides or 0)

        weeks[week_num]["rides"] += rcount
        if batch.source == "acumen":
            weeks[week_num]["fa_revenue"] += rev
            weeks[week_num]["fa_profit"] += prof
        elif batch.source == "maz":
            weeks[week_num]["ed_revenue"] += rev
            weeks[week_num]["ed_profit"] += prof

    # Sort descending by week_num, take most recent `limit`
    sorted_weeks = sorted(weeks.items(), key=lambda x: x[0], reverse=True)[:limit]

    result = []
    for week_num, data in sorted_weeks:
        result.append({
            "week_label": f"Week {week_num}",
            "fa_revenue": data["fa_revenue"],
            "fa_profit": data["fa_profit"],
            "ed_revenue": data["ed_revenue"],
            "ed_profit": data["ed_profit"],
            "rides": data["rides"],
        })
    return result


def _build_recent_batches(db: Session, limit: int = 5):
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


def _build_chart_data(ytd_weeks: list[dict]) -> dict:
    """Build Chart.js data from YTD weeks."""
    labels = [w["week_label"] for w in reversed(ytd_weeks)]
    fa_revenue = [round(w["fa_revenue"], 2) for w in reversed(ytd_weeks)]
    ed_revenue = [round(w["ed_revenue"], 2) for w in reversed(ytd_weeks)]
    fa_profit = [round(w["fa_profit"], 2) for w in reversed(ytd_weeks)]
    ed_profit = [round(w["ed_profit"], 2) for w in reversed(ytd_weeks)]
    rides = [w["rides"] for w in reversed(ytd_weeks)]
    return {
        "labels": labels,
        "fa_revenue": fa_revenue,
        "ed_revenue": ed_revenue,
        "fa_profit": fa_profit,
        "ed_profit": ed_profit,
        "rides": rides,
    }


@router.get("/", response_class=HTMLResponse, name="dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):
    _wants_json = (
        "application/json" in request.headers.get("content-type", "")
        or "application/json" in request.headers.get("accept", "")
    )

    try:
        stats = _build_stats(db)
        recent_batches = _build_recent_batches(db)
        ytd_weeks = _build_ytd_weeks(db, limit=8)
        chart_data = _build_chart_data(ytd_weeks)
    except Exception:
        stats = {
            "total_revenue": 0, "total_cost": 0, "total_profit": 0,
            "total_rides": 0, "active_drivers": 0, "avg_profit_per_ride": 0,
            "total_margin_pct": 0,
            "fa_revenue": 0, "fa_cost": 0, "fa_profit": 0,
            "fa_rides": 0, "fa_drivers": 0, "fa_margin_pct": 0,
            "ed_revenue": 0, "ed_cost": 0, "ed_profit": 0,
            "ed_rides": 0, "ed_drivers": 0, "ed_margin_pct": 0,
        }
        recent_batches = []
        ytd_weeks = []
        chart_data = {"labels": [], "fa_revenue": [], "ed_revenue": [], "fa_profit": [], "ed_profit": [], "rides": []}

    if _wants_json:
        weekly_data = []
        for item in ytd_weeks:
            weekly_data.append({
                "week": item.get("week_label", ""),
                "label": item.get("week_label", ""),
                "fa_revenue": item.get("fa_revenue", 0),
                "ed_revenue": item.get("ed_revenue", 0),
                "fa_rides": item.get("rides", 0),
                "ed_rides": 0,
                "profit": round(item.get("fa_profit", 0) + item.get("ed_profit", 0), 2),
            })
        total_rides = stats.get("total_rides", 0)
        num_op_weeks = db.query(func.count(distinct(PayrollBatch.week_start))).filter(
            PayrollBatch.finalized_at.isnot(None),
            PayrollBatch.week_start.isnot(None),
        ).scalar() or 1
        avg_rides_per_day = round(total_rides / (num_op_weeks * 5), 1)

        return JSONResponse({
            "revenue": stats.get("total_revenue", 0),
            "cost": stats.get("total_cost", 0),
            "profit": stats.get("total_profit", 0),
            "rides": total_rides,
            "avg_rides_per_day": avg_rides_per_day,
            "margin": stats.get("total_margin_pct", 0),
            "fa": {
                "revenue": stats.get("fa_revenue", 0),
                "profit": stats.get("fa_profit", 0),
                "rides": stats.get("fa_rides", 0),
                "cost": stats.get("fa_cost", 0),
            },
            "ed": {
                "revenue": stats.get("ed_revenue", 0),
                "profit": stats.get("ed_profit", 0),
                "rides": stats.get("ed_rides", 0),
                "cost": stats.get("ed_cost", 0),
            },
            "weekly_data": weekly_data,
        })

    return templates().TemplateResponse(
        request,
        "dashboard.html",
        {
            "stats": stats,
            "recent_batches": recent_batches,
            "ytd_weeks": ytd_weeks,
            "chart_data": chart_data,
        },
    )
