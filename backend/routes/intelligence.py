from pathlib import Path
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import Ride, Person, PayrollBatch, DriverBalance
from backend.routes.insights import _build_snapshot
from backend.routes.analytics import _get_companies

router = APIRouter(prefix="/intelligence", tags=["intelligence"])

_templates = None


def templates():
    global _templates
    if _templates is None:
        templates_dir = Path(__file__).resolve().parents[1] / "templates"
        _templates = Jinja2Templates(directory=str(templates_dir))
    return _templates


# ---------------------------------------------------------------------------
# Section 2 — Alerts
# ---------------------------------------------------------------------------

def _build_alerts(db: Session) -> list[dict]:
    alerts = []

    # 1. Rides with z_rate == 0
    zero_rate_count = (
        db.query(func.count(Ride.ride_id))
        .filter(Ride.z_rate == 0)
        .scalar()
        or 0
    )
    if zero_rate_count > 0:
        alerts.append({
            "type": "danger",
            "message": f"{zero_rate_count} rides have no rate assigned",
            "url": "/admin/rates",
        })

    # 2. Pay weeks present in one source but not the other
    acumen_weeks = set(
        r[0]
        for r in db.query(PayrollBatch.week_start)
        .filter(PayrollBatch.source == "acumen", PayrollBatch.week_start.isnot(None))
        .distinct()
        .all()
    )
    maz_weeks = set(
        r[0]
        for r in db.query(PayrollBatch.week_start)
        .filter(PayrollBatch.source == "maz", PayrollBatch.week_start.isnot(None))
        .distinct()
        .all()
    )
    acumen_missing = maz_weeks - acumen_weeks
    if acumen_missing:
        alerts.append({
            "type": "warning",
            "message": f"Acumen missing {len(acumen_missing)} weeks that EverDriven has uploaded",
            "url": "/upload",
        })

    # 3. Drivers withheld (carried_over > 0) for 2+ batches
    withheld_subq = (
        db.query(DriverBalance.person_id)
        .filter(DriverBalance.carried_over > 0)
        .group_by(DriverBalance.person_id)
        .having(func.count(DriverBalance.payroll_batch_id) >= 2)
        .subquery()
    )
    withheld_count = (
        db.query(func.count())
        .select_from(withheld_subq)
        .scalar()
        or 0
    )
    if withheld_count > 0:
        alerts.append({
            "type": "warning",
            "message": f"{withheld_count} drivers withheld for 2+ weeks",
            "url": "/summary",
        })

    return alerts


# ---------------------------------------------------------------------------
# Section 3 — Trends
# ---------------------------------------------------------------------------

def _build_trends(db: Session) -> tuple[list[dict], dict]:
    # Gather per-(source, week_start) aggregates from payroll_batch + rides
    rows = (
        db.query(
            PayrollBatch.source,
            PayrollBatch.week_start,
            PayrollBatch.week_end,
            func.sum(Ride.net_pay).label("revenue"),
            func.sum(Ride.net_pay - Ride.z_rate).label("profit"),
            func.count(Ride.ride_id).label("rides"),
        )
        .join(Ride, Ride.payroll_batch_id == PayrollBatch.payroll_batch_id)
        .filter(PayrollBatch.week_start.isnot(None))
        .group_by(PayrollBatch.source, PayrollBatch.week_start, PayrollBatch.week_end)
        .all()
    )

    # Index by (source, week_start)
    data: dict[tuple, dict] = {}
    all_week_starts: set = set()
    for r in rows:
        key = (r.source, r.week_start)
        data[key] = {
            "revenue": float(r.revenue or 0),
            "profit": float(r.profit or 0),
            "rides": int(r.rides or 0),
            "week_end": r.week_end,
        }
        all_week_starts.add(r.week_start)

    # Last 8 distinct week_starts, descending, then flip to ascending for display
    sorted_weeks = sorted(all_week_starts, reverse=True)[:8]
    sorted_weeks = sorted(sorted_weeks)  # oldest first

    trends = []
    for ws in sorted_weeks:
        acumen = data.get(("acumen", ws), {})
        maz = data.get(("maz", ws), {})
        total_rides = acumen.get("rides", 0) + maz.get("rides", 0)
        week_label = ws.strftime("%-m/%-d") if hasattr(ws, "strftime") else str(ws)
        trends.append({
            "week_label": week_label,
            "acumen_revenue": round(acumen.get("revenue", 0.0), 2),
            "acumen_profit": round(acumen.get("profit", 0.0), 2),
            "maz_revenue": round(maz.get("revenue", 0.0), 2),
            "maz_profit": round(maz.get("profit", 0.0), 2),
            "total_rides": total_rides,
        })

    # Projection: average last 4 weeks total revenue/profit, scale to full month
    projection = _build_projection(trends)

    # Comparison: recent 4 weeks vs prior 4 weeks
    comparison = _build_comparison(trends)

    return trends, projection, comparison


def _build_comparison(trends: list[dict]) -> dict:
    """Compare the most recent 4 weeks against the prior 4 weeks."""
    recent = trends[-4:] if len(trends) >= 4 else trends
    prior = trends[-8:-4] if len(trends) >= 8 else []

    def totals(weeks):
        rev = sum(w["acumen_revenue"] + w["maz_revenue"] for w in weeks)
        profit = sum(w["acumen_profit"] + w["maz_profit"] for w in weeks)
        return round(rev, 2), round(profit, 2)

    recent_revenue, recent_profit = totals(recent)
    prior_revenue, prior_profit = totals(prior)

    def pct_change(new_val, old_val):
        if old_val == 0:
            return None
        return round((new_val - old_val) / abs(old_val) * 100, 1)

    return {
        "recent_revenue": recent_revenue,
        "recent_profit": recent_profit,
        "prior_revenue": prior_revenue,
        "prior_profit": prior_profit,
        "revenue_change_pct": pct_change(recent_revenue, prior_revenue),
        "profit_change_pct": pct_change(recent_profit, prior_profit),
    }


def _build_projection(trends: list[dict]) -> dict:
    last_4 = trends[-4:] if len(trends) >= 4 else trends
    basis_weeks = len(last_4)

    if basis_weeks == 0:
        today = date.today()
        return {
            "month_name": today.strftime("%B"),
            "projected_revenue": 0.0,
            "projected_profit": 0.0,
            "basis_weeks": 0,
        }

    avg_revenue = sum(w["acumen_revenue"] + w["maz_revenue"] for w in last_4) / basis_weeks
    avg_profit = sum(w["acumen_profit"] + w["maz_profit"] for w in last_4) / basis_weeks

    # Estimate total weeks in current month (approx 4.33 weeks per month)
    today = date.today()
    import calendar
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    total_weeks_in_month = days_in_month / 7.0

    projected_revenue = round(avg_revenue * total_weeks_in_month, 2)
    projected_profit = round(avg_profit * total_weeks_in_month, 2)

    return {
        "month_name": today.strftime("%B"),
        "projected_revenue": projected_revenue,
        "projected_profit": projected_profit,
        "basis_weeks": basis_weeks,
    }


# ---------------------------------------------------------------------------
# Section 4 — Driver Performance
# ---------------------------------------------------------------------------

def _build_driver_performance(db: Session) -> tuple[list[dict], list[dict], list[dict]]:
    # All drivers with rides in last 30 days, ordered by profit
    driver_rows = (
        db.query(
            Person.full_name.label("name"),
            PayrollBatch.company_name.label("company"),
            func.count(Ride.ride_id).label("rides"),
            func.sum(Ride.net_pay - Ride.z_rate).label("profit"),
        )
        .join(Ride, Ride.person_id == Person.person_id)
        .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
        .filter(Ride.ride_start_ts >= text("now() - interval '30 days'"))
        .group_by(Person.full_name, PayrollBatch.company_name)
        .order_by(func.sum(Ride.net_pay - Ride.z_rate).desc())
        .all()
    )

    def to_dict(r) -> dict:
        return {
            "name": r.name,
            "rides": int(r.rides or 0),
            "profit": round(float(r.profit or 0), 2),
            "company": r.company,
        }

    all_drivers = [to_dict(r) for r in driver_rows]
    top_drivers = all_drivers[:10]
    bottom_drivers = all_drivers[-10:] if len(all_drivers) >= 10 else list(reversed(all_drivers))
    # bottom should be ordered worst first
    bottom_drivers = list(reversed(bottom_drivers))

    # Inactive drivers: Person with no rides in last 30 days, limit 15
    active_person_ids_subq = (
        db.query(Ride.person_id)
        .filter(Ride.ride_start_ts >= text("now() - interval '30 days'"))
        .distinct()
        .subquery()
    )

    last_ride_subq = (
        db.query(
            Ride.person_id,
            func.max(Ride.ride_start_ts).label("last_ride"),
        )
        .group_by(Ride.person_id)
        .subquery()
    )

    inactive_rows = (
        db.query(
            Person.full_name.label("name"),
            last_ride_subq.c.last_ride,
        )
        .outerjoin(last_ride_subq, last_ride_subq.c.person_id == Person.person_id)
        .filter(Person.person_id.notin_(
            db.query(active_person_ids_subq.c.person_id)
        ))
        .order_by(last_ride_subq.c.last_ride.desc().nullslast())
        .limit(15)
        .all()
    )

    def fmt_last_ride(ts) -> str:
        if ts is None:
            return "Never"
        if hasattr(ts, "strftime"):
            return ts.strftime("%-m/%-d/%Y")
        return str(ts)

    inactive_drivers = [
        {"name": r.name, "last_ride": fmt_last_ride(r.last_ride)}
        for r in inactive_rows
    ]

    return top_drivers, bottom_drivers, inactive_drivers


# ---------------------------------------------------------------------------
# Section 5 — Route Profitability
# ---------------------------------------------------------------------------

def _build_routes(db: Session, company: str | None = None) -> list[dict]:
    q = (
        db.query(
            Ride.service_name,
            func.count(Ride.ride_id).label("rides"),
            func.sum(Ride.net_pay).label("revenue"),
            func.sum(Ride.z_rate).label("cost"),
            func.sum(Ride.net_pay - Ride.z_rate).label("profit"),
        )
        .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
        .group_by(Ride.service_name)
        .order_by(func.sum(Ride.net_pay - Ride.z_rate).desc())
    )
    if company:
        q = q.filter(PayrollBatch.company_name == company)

    routes = []
    for r in q.all():
        revenue = float(r.revenue or 0)
        profit = float(r.profit or 0)
        margin_pct = round(profit / revenue * 100, 1) if revenue else 0.0
        routes.append({
            "service_name": r.service_name or "—",
            "rides": int(r.rides or 0),
            "revenue": round(revenue, 2),
            "cost": round(float(r.cost or 0), 2),
            "profit": round(profit, 2),
            "margin_pct": margin_pct,
        })
    return routes


# ---------------------------------------------------------------------------
# Snapshot mapping helpers
# ---------------------------------------------------------------------------

def _map_snapshot(raw: dict) -> dict:
    """Map _build_snapshot output keys to the intelligence data contract."""
    return {
        "revenue": raw.get("total_revenue", 0.0),
        "cost": raw.get("total_cost", 0.0),
        "profit": raw.get("total_profit", 0.0),
        "rides": raw.get("total_rides", 0),
        "active_drivers": raw.get("active_drivers", 0),
        "avg_profit": raw.get("avg_profit_per_ride", 0.0),
        "margin_pct": raw.get("margin_pct", 0.0),
    }


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

@router.get("/", name="intelligence_page")
def intelligence_page(
    request: Request,
    company: str | None = Query(None),
    db: Session = Depends(get_db),
):
    companies = _get_companies(db)

    # Section 1 — Company Snapshots
    raw_acumen = _build_snapshot(db, company="Acumen International")
    raw_maz = _build_snapshot(db, company="everDriven")
    snapshot_acumen = _map_snapshot(raw_acumen)
    snapshot_maz = _map_snapshot(raw_maz)

    # Section 2 — Alerts
    alerts = _build_alerts(db)

    # Section 3 — Trends
    trends, projection, comparison = _build_trends(db)

    # Section 4 — Driver Performance
    top_drivers, bottom_drivers, inactive_drivers = _build_driver_performance(db)

    # Section 5 — Route Profitability
    routes = _build_routes(db, company=company)

    return templates().TemplateResponse(
        request,
        "intelligence.html",
        {
            "companies": companies,
            "selected_company": company,
            # Section 1
            "snapshot_acumen": snapshot_acumen,
            "snapshot_maz": snapshot_maz,
            # Section 2
            "alerts": alerts,
            # Section 3
            "trends": trends,
            "projection": projection,
            "comparison": comparison,
            # Section 4
            "top_drivers": top_drivers,
            "bottom_drivers": bottom_drivers,
            "inactive_drivers": inactive_drivers,
            # Section 5
            "routes": routes,
        },
    )


@router.post("/generate-insights", name="intelligence_generate_insights")
async def generate_insights(
    request: Request,
    company: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return JSONResponse({"narrative": ""})
