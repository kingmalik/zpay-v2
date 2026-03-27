from pathlib import Path
from datetime import date

from fastapi import APIRouter, Depends, Request, Query
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, cast, Date, case
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import Person, Ride, PayrollBatch

router = APIRouter(prefix="/analytics", tags=["analytics"])

_templates = None


def templates():
    global _templates
    if _templates is None:
        templates_dir = Path(__file__).resolve().parents[1] / "templates"
        _templates = Jinja2Templates(directory=str(templates_dir))
    return _templates


def _get_companies(db: Session) -> list[str]:
    rows = (
        db.query(PayrollBatch.company_name)
        .distinct()
        .order_by(PayrollBatch.company_name.asc())
        .all()
    )
    return [r[0] for r in rows]


def _get_batches(db: Session, company: str | None = None):
    q = db.query(PayrollBatch).order_by(PayrollBatch.period_start.desc())
    if company:
        q = q.filter(PayrollBatch.company_name == company)
    return q.all()


def _build_analytics(
    db: Session,
    company: str | None = None,
    batch_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
) -> dict:
    ride_date = func.coalesce(cast(Ride.ride_start_ts, Date))

    # Base query with profit computed inline
    base_q = (
        db.query(Ride, Person, PayrollBatch)
        .join(Person, Person.person_id == Ride.person_id)
        .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
    )
    if company:
        base_q = base_q.filter(PayrollBatch.company_name == company)
    if batch_id:
        base_q = base_q.filter(PayrollBatch.payroll_batch_id == batch_id)
    if start:
        base_q = base_q.filter(func.coalesce(cast(Ride.ride_start_ts, Date)) >= start)
    if end:
        base_q = base_q.filter(func.coalesce(cast(Ride.ride_start_ts, Date)) <= end)

    # ── Top-level summary ─────────────────────────────────────────────────────
    summary_q = (
        db.query(
            func.sum(Ride.net_pay).label("total_revenue"),
            func.sum(Ride.z_rate).label("total_cost"),
            func.sum(Ride.net_pay - Ride.z_rate).label("total_profit"),
            func.count(Ride.ride_id).label("total_rides"),
            func.sum(Ride.gross_pay).label("total_gross"),
        )
        .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
    )
    if company:
        summary_q = summary_q.filter(PayrollBatch.company_name == company)
    if batch_id:
        summary_q = summary_q.filter(PayrollBatch.payroll_batch_id == batch_id)
    if start:
        summary_q = summary_q.filter(func.coalesce(cast(Ride.ride_start_ts, Date)) >= start)
    if end:
        summary_q = summary_q.filter(func.coalesce(cast(Ride.ride_start_ts, Date)) <= end)

    s = summary_q.one()
    total_revenue = float(s.total_revenue or 0)
    total_cost = float(s.total_cost or 0)
    total_profit = float(s.total_profit or 0)
    total_rides = int(s.total_rides or 0)
    margin_pct = (total_profit / total_revenue * 100) if total_revenue else 0.0

    summary = {
        "total_revenue": round(total_revenue, 2),
        "total_cost": round(total_cost, 2),
        "total_profit": round(total_profit, 2),
        "margin_pct": round(margin_pct, 1),
        "total_rides": total_rides,
    }

    # ── Per-ride profitability (for top/bottom 10) ────────────────────────────
    ride_profit_q = (
        db.query(
            Ride.ride_id,
            Ride.service_name,
            Person.full_name.label("driver"),
            func.coalesce(cast(Ride.ride_start_ts, Date)).label("ride_date"),
            Ride.gross_pay,
            Ride.net_pay,
            Ride.z_rate,
            (Ride.net_pay - Ride.z_rate).label("profit"),
            PayrollBatch.company_name,
        )
        .join(Person, Person.person_id == Ride.person_id)
        .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
    )
    if company:
        ride_profit_q = ride_profit_q.filter(PayrollBatch.company_name == company)
    if batch_id:
        ride_profit_q = ride_profit_q.filter(PayrollBatch.payroll_batch_id == batch_id)
    if start:
        ride_profit_q = ride_profit_q.filter(func.coalesce(cast(Ride.ride_start_ts, Date)) >= start)
    if end:
        ride_profit_q = ride_profit_q.filter(func.coalesce(cast(Ride.ride_start_ts, Date)) <= end)

    all_ride_rows = ride_profit_q.all()

    def ride_to_dict(r):
        net = float(r.net_pay or 0)
        z = float(r.z_rate or 0)
        profit = net - z
        margin = (profit / net * 100) if net else 0.0
        return {
            "service_name": r.service_name or "—",
            "driver": r.driver or "—",
            "ride_date": r.ride_date.strftime("%-m/%-d/%Y") if r.ride_date else "—",
            "gross_pay": round(float(r.gross_pay or 0), 2),
            "net_pay": round(net, 2),
            "z_rate": round(z, 2),
            "profit": round(profit, 2),
            "margin_pct": round(margin, 1),
            "company": r.company_name or "—",
        }

    ride_dicts = [ride_to_dict(r) for r in all_ride_rows]
    sorted_by_profit = sorted(ride_dicts, key=lambda x: x["profit"], reverse=True)
    top_rides = sorted_by_profit[:10]
    bottom_rides = sorted(ride_dicts, key=lambda x: x["profit"])[:10]

    # ── Profit by company ─────────────────────────────────────────────────────
    company_q = (
        db.query(
            PayrollBatch.company_name,
            func.sum(Ride.net_pay).label("revenue"),
            func.sum(Ride.z_rate).label("cost"),
            func.sum(Ride.net_pay - Ride.z_rate).label("profit"),
            func.count(Ride.ride_id).label("rides"),
        )
        .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
        .group_by(PayrollBatch.company_name)
        .order_by(PayrollBatch.company_name.asc())
    )
    if company:
        company_q = company_q.filter(PayrollBatch.company_name == company)
    if batch_id:
        company_q = company_q.filter(PayrollBatch.payroll_batch_id == batch_id)
    if start:
        company_q = company_q.filter(func.coalesce(cast(Ride.ride_start_ts, Date)) >= start)
    if end:
        company_q = company_q.filter(func.coalesce(cast(Ride.ride_start_ts, Date)) <= end)

    company_rows = []
    for r in company_q.all():
        rev = float(r.revenue or 0)
        cost = float(r.cost or 0)
        prof = float(r.profit or 0)
        margin = (prof / rev * 100) if rev else 0.0
        company_rows.append({
            "company": r.company_name,
            "revenue": round(rev, 2),
            "cost": round(cost, 2),
            "profit": round(prof, 2),
            "margin_pct": round(margin, 1),
            "rides": int(r.rides or 0),
        })

    # ── Profit by pay period ──────────────────────────────────────────────────
    period_q = (
        db.query(
            PayrollBatch.payroll_batch_id,
            PayrollBatch.company_name,
            PayrollBatch.period_start,
            PayrollBatch.period_end,
            func.sum(Ride.net_pay).label("revenue"),
            func.sum(Ride.z_rate).label("cost"),
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
    )
    if company:
        period_q = period_q.filter(PayrollBatch.company_name == company)
    if batch_id:
        period_q = period_q.filter(PayrollBatch.payroll_batch_id == batch_id)

    period_rows = []
    for r in period_q.all():
        rev = float(r.revenue or 0)
        cost = float(r.cost or 0)
        prof = float(r.profit or 0)
        margin = (prof / rev * 100) if rev else 0.0

        def fmt_date(d):
            return d.strftime("%-m/%-d/%Y") if d else "—"

        period_rows.append({
            "batch_id": r.payroll_batch_id,
            "company": r.company_name,
            "period_start": fmt_date(r.period_start),
            "period_end": fmt_date(r.period_end),
            "revenue": round(rev, 2),
            "cost": round(cost, 2),
            "profit": round(prof, 2),
            "margin_pct": round(margin, 1),
            "rides": int(r.rides or 0),
        })

    # ── Driver earnings stats ─────────────────────────────────────────────────
    driver_stats_q = (
        db.query(
            Person.full_name.label("driver"),
            func.count(Ride.ride_id).label("total_rides"),
            func.sum(Ride.z_rate).label("total_earnings"),
            func.avg(Ride.z_rate).label("avg_per_ride"),
            func.count(func.distinct(Ride.payroll_batch_id)).label("active_weeks"),
            func.sum(Ride.net_pay - Ride.z_rate).label("total_profit"),
            func.avg(Ride.net_pay - Ride.z_rate).label("avg_profit_per_ride"),
        )
        .join(Ride, Ride.person_id == Person.person_id)
        .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
        .group_by(Person.person_id, Person.full_name)
        .order_by(func.sum(Ride.z_rate).desc())
    )
    if company:
        driver_stats_q = driver_stats_q.filter(PayrollBatch.company_name == company)
    if batch_id:
        driver_stats_q = driver_stats_q.filter(PayrollBatch.payroll_batch_id == batch_id)
    if start:
        driver_stats_q = driver_stats_q.filter(func.coalesce(cast(Ride.ride_start_ts, Date)) >= start)
    if end:
        driver_stats_q = driver_stats_q.filter(func.coalesce(cast(Ride.ride_start_ts, Date)) <= end)

    driver_stats = []
    for i, r in enumerate(driver_stats_q.all(), 1):
        total_earn = float(r.total_earnings or 0)
        avg_earn = float(r.avg_per_ride or 0)
        total_profit = float(r.total_profit or 0)
        avg_profit = float(r.avg_profit_per_ride or 0)
        driver_stats.append({
            "rank": i,
            "driver": r.driver or "—",
            "total_rides": int(r.total_rides or 0),
            "total_earnings": round(total_earn, 2),
            "avg_per_ride": round(avg_earn, 2),
            "active_weeks": int(r.active_weeks or 0),
            "total_profit": round(total_profit, 2),
            "avg_profit_per_ride": round(avg_profit, 2),
        })

    return {
        "summary": summary,
        "top_rides": top_rides,
        "bottom_rides": bottom_rides,
        "company_rows": company_rows,
        "period_rows": period_rows,
        "driver_stats": driver_stats,
    }


@router.get("/", name="analytics_page")
def analytics_page(
    request: Request,
    company: str | None = Query(None),
    batch_id: int | None = Query(None),
    start: date | None = Query(None),
    end: date | None = Query(None),
    db: Session = Depends(get_db),
):
    companies = _get_companies(db)
    selected_company = company  # None = all companies

    batches = _get_batches(db, company=selected_company)

    data = _build_analytics(db, company=selected_company, batch_id=batch_id, start=start, end=end)

    zero_rate_count = db.query(func.count(Ride.ride_id)).filter(Ride.z_rate == 0).scalar() or 0

    return templates().TemplateResponse(
        request,
        "analytics.html",
        {
            "companies": companies,
            "selected_company": selected_company,
            "batches": batches,
            "selected_batch_id": batch_id,
            "start": start,
            "end": end,
            "zero_rate_count": zero_rate_count,
            **data,
        },
    )
