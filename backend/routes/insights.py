from pathlib import Path
import json

from fastapi import APIRouter, Depends, Request, Query
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import Person, Ride, PayrollBatch

router = APIRouter(prefix="/insights", tags=["insights"])

_templates = None


def templates():
    global _templates
    if _templates is None:
        templates_dir = Path(__file__).resolve().parents[1] / "templates"
        _templates = Jinja2Templates(directory=str(templates_dir))
    return _templates


def _build_snapshot(db: Session, company: str | None = None) -> dict:
    """
    Gather a compact data snapshot to feed to Claude for narrative insights.
    Returns a dict with key metrics.
    """
    # Total-level aggregates
    base_q = (
        db.query(
            func.sum(Ride.net_pay).label("total_revenue"),
            func.sum(Ride.z_rate).label("total_cost"),
            func.sum(Ride.net_pay - Ride.z_rate).label("total_profit"),
            func.count(Ride.ride_id).label("total_rides"),
            func.count(func.distinct(Ride.person_id)).label("active_drivers"),
        )
        .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
    )
    if company:
        base_q = base_q.filter(PayrollBatch.company_name == company)
    s = base_q.one()

    total_revenue = float(s.total_revenue or 0)
    total_cost = float(s.total_cost or 0)
    total_profit = float(s.total_profit or 0)
    total_rides = int(s.total_rides or 0)
    active_drivers = int(s.active_drivers or 0)
    margin_pct = round(total_profit / total_revenue * 100, 1) if total_revenue else 0.0

    # Top 5 drivers by profit (net_pay - z_rate)
    top_driver_q = (
        db.query(
            Person.full_name.label("driver"),
            func.count(Ride.ride_id).label("rides"),
            func.sum(Ride.z_rate).label("total_cost"),
            func.sum(Ride.net_pay).label("total_revenue"),
            func.sum(Ride.net_pay - Ride.z_rate).label("total_profit"),
        )
        .join(Ride, Ride.person_id == Person.person_id)
        .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
        .group_by(Person.person_id, Person.full_name)
        .order_by(func.sum(Ride.net_pay - Ride.z_rate).desc())
        .limit(5)
    )
    if company:
        top_driver_q = top_driver_q.filter(PayrollBatch.company_name == company)

    top_drivers = []
    for r in top_driver_q.all():
        rev = float(r.total_revenue or 0)
        prof = float(r.total_profit or 0)
        margin = round(prof / rev * 100, 1) if rev else 0.0
        top_drivers.append({
            "driver": r.driver,
            "rides": int(r.rides),
            "total_cost": round(float(r.total_cost or 0), 2),
            "total_profit": round(prof, 2),
            "margin_pct": margin,
        })

    # Top 5 routes by profit
    top_route_q = (
        db.query(
            Ride.service_name,
            func.count(Ride.ride_id).label("ride_count"),
            func.sum(Ride.net_pay).label("revenue"),
            func.sum(Ride.z_rate).label("cost"),
            func.sum(Ride.net_pay - Ride.z_rate).label("profit"),
        )
        .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
        .group_by(Ride.service_name)
        .order_by(func.sum(Ride.net_pay - Ride.z_rate).desc())
        .limit(5)
    )
    if company:
        top_route_q = top_route_q.filter(PayrollBatch.company_name == company)

    top_routes = []
    for r in top_route_q.all():
        rev = float(r.revenue or 0)
        prof = float(r.profit or 0)
        margin = round(prof / rev * 100, 1) if rev else 0.0
        top_routes.append({
            "service": r.service_name or "—",
            "ride_count": int(r.ride_count),
            "profit": round(prof, 2),
            "margin_pct": margin,
        })

    # Bottom 5 routes by profit (least profitable / loss routes)
    bottom_route_q = (
        db.query(
            Ride.service_name,
            func.count(Ride.ride_id).label("ride_count"),
            func.sum(Ride.net_pay).label("revenue"),
            func.sum(Ride.z_rate).label("cost"),
            func.sum(Ride.net_pay - Ride.z_rate).label("profit"),
        )
        .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
        .group_by(Ride.service_name)
        .order_by(func.sum(Ride.net_pay - Ride.z_rate).asc())
        .limit(5)
    )
    if company:
        bottom_route_q = bottom_route_q.filter(PayrollBatch.company_name == company)

    bottom_routes = []
    for r in bottom_route_q.all():
        rev = float(r.revenue or 0)
        prof = float(r.profit or 0)
        margin = round(prof / rev * 100, 1) if rev else 0.0
        bottom_routes.append({
            "service": r.service_name or "—",
            "ride_count": int(r.ride_count),
            "profit": round(prof, 2),
            "margin_pct": margin,
        })

    # Keep top_services for backwards compat (by ride volume)
    top_service_q = (
        db.query(
            Ride.service_name,
            func.count(Ride.ride_id).label("ride_count"),
            func.sum(Ride.net_pay).label("revenue"),
            func.sum(Ride.net_pay - Ride.z_rate).label("profit"),
        )
        .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
        .group_by(Ride.service_name)
        .order_by(func.count(Ride.ride_id).desc())
        .limit(5)
    )
    if company:
        top_service_q = top_service_q.filter(PayrollBatch.company_name == company)

    top_services = [
        {
            "service": r.service_name or "—",
            "ride_count": int(r.ride_count),
            "revenue": round(float(r.revenue or 0), 2),
            "profit": round(float(r.profit or 0), 2),
        }
        for r in top_service_q.all()
    ]

    # Recent 5 pay periods
    period_q = (
        db.query(
            PayrollBatch.company_name,
            PayrollBatch.period_start,
            PayrollBatch.period_end,
            func.sum(Ride.net_pay - Ride.z_rate).label("profit"),
            func.count(Ride.ride_id).label("rides"),
        )
        .join(Ride, Ride.payroll_batch_id == PayrollBatch.payroll_batch_id)
        .group_by(
            PayrollBatch.payroll_batch_id,
            PayrollBatch.company_name,
            PayrollBatch.period_start,
            PayrollBatch.period_end,
        )
        .order_by(PayrollBatch.period_start.desc().nullslast())
        .limit(5)
    )
    if company:
        period_q = period_q.filter(PayrollBatch.company_name == company)

    def fmt(d):
        return d.strftime("%-m/%-d/%Y") if d else "—"

    recent_periods = [
        {
            "company": r.company_name or "—",
            "period_start": fmt(r.period_start),
            "period_end": fmt(r.period_end),
            "profit": round(float(r.profit or 0), 2),
            "rides": int(r.rides),
        }
        for r in period_q.all()
    ]

    avg_profit_per_ride = round(total_profit / total_rides, 2) if total_rides else 0.0

    return {
        "total_revenue": round(total_revenue, 2),
        "total_cost": round(total_cost, 2),
        "total_profit": round(total_profit, 2),
        "margin_pct": margin_pct,
        "total_rides": total_rides,
        "active_drivers": active_drivers,
        "avg_profit_per_ride": avg_profit_per_ride,
        "top_drivers": top_drivers,
        "top_routes": top_routes,
        "bottom_routes": bottom_routes,
        "top_services": top_services,
        "recent_periods": recent_periods,
        "company_filter": company or "All companies",
    }


def _call_claude(snapshot: dict) -> str:
    """
    Call the Anthropic API with the snapshot and return narrative insights.
    Falls back gracefully if the API key is missing.
    """
    try:
        import anthropic

        client = anthropic.Anthropic()

        prompt = f"""You are a sharp business analyst for a transportation company that operates two fleets (Acumen/FirstAlt and Maz/EverDriven).
Your job is to analyze profitability — not just revenue or cost — and surface actionable intelligence.

Data snapshot (JSON):
{json.dumps(snapshot, indent=2)}

Guidelines:
- Lead with the single most important profit insight
- Call out which drivers generate the most profit vs. which drivers eat margin
- Identify the most and least profitable routes by name — explain what that pattern means
- Flag any routes where the business is losing money (profit < 0) — these are risks
- Compare the two companies (Acumen vs. Maz) if both are present — which is more profitable?
- Note the avg profit per ride and whether any segment is significantly above or below it
- End with one concrete, actionable recommendation to improve profitability
- Be specific — use exact dollar figures and percentages from the data
- Keep total response under 400 words
- Use plain prose paragraphs, no bullet lists or markdown headers"""

        message = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()

    except ImportError:
        return "Anthropic SDK not installed. Add `anthropic` to requirements.txt and restart."
    except Exception as exc:  # noqa: BLE001
        return f"Could not generate insights: {exc}"


@router.get("/", name="insights_page")
def insights_page(
    request: Request,
    company: str | None = Query(None),
    db: Session = Depends(get_db),
):
    from backend.db.models import PayrollBatch as PB  # local import to avoid circular

    companies = (
        db.query(PB.company_name)
        .distinct()
        .order_by(PB.company_name.asc())
        .all()
    )
    companies = [r[0] for r in companies]

    snapshot = _build_snapshot(db, company=company)
    narrative = _call_claude(snapshot)

    return templates().TemplateResponse(
        request,
        "insights.html",
        {
            "companies": companies,
            "selected_company": company,
            "snapshot": snapshot,
            "narrative": narrative,
        },
    )
