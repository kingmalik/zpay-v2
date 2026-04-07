from pathlib import Path
from datetime import date

from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, cast, Date
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import Person, Ride, PayrollBatch

router = APIRouter(prefix="/pareto", tags=["pareto"])

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


def _pareto_cutoff(rows: list[dict], key: str) -> list[dict]:
    """
    Given a list of dicts already sorted descending by `key`,
    attach cumulative_pct and is_cutoff to each row.
    is_cutoff is True on the row where cumulative % first crosses 80%.
    """
    total = sum(r[key] for r in rows)
    if total <= 0:
        for r in rows:
            r["individual_pct"] = 0.0
            r["cumulative_pct"] = 0.0
            r["is_cutoff"] = False
        return rows

    running = 0.0
    cutoff_marked = False
    for r in rows:
        val = r[key]
        individual_pct = (val / total * 100) if total else 0.0
        running += individual_pct
        r["individual_pct"] = round(individual_pct, 1)
        r["cumulative_pct"] = round(running, 1)
        if not cutoff_marked and running >= 80.0:
            r["is_cutoff"] = True
            cutoff_marked = True
        else:
            r["is_cutoff"] = False
    return rows


def _build_pareto(db: Session, company: str | None = None) -> dict:

    # ── 1. Drivers by profit generated (net_pay - z_rate) ──────────────────────
    driver_q = (
        db.query(
            Person.person_id,
            Person.full_name.label("driver"),
            func.count(Ride.ride_id).label("rides"),
            func.sum(Ride.net_pay - Ride.z_rate).label("profit"),
        )
        .join(Ride, Ride.person_id == Person.person_id)
        .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
        .group_by(Person.person_id, Person.full_name)
        .order_by(func.sum(Ride.net_pay - Ride.z_rate).desc())
    )
    if company:
        driver_q = driver_q.filter(PayrollBatch.company_name == company)

    total_driver_count = (
        db.query(func.count(Person.person_id.distinct()))
        .join(Ride, Ride.person_id == Person.person_id)
        .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
    )
    if company:
        total_driver_count = total_driver_count.filter(
            PayrollBatch.company_name == company
        )
    total_drivers = total_driver_count.scalar() or 0

    driver_rows = []
    for i, r in enumerate(driver_q.all(), 1):
        driver_rows.append(
            {
                "rank": i,
                "driver": r.driver or "—",
                "rides": int(r.rides or 0),
                "profit": round(float(r.profit or 0), 2),
            }
        )

    driver_rows = _pareto_cutoff(driver_rows, "profit")

    # How many drivers are in the 80% zone?
    drivers_at_80 = sum(1 for r in driver_rows if r["cumulative_pct"] <= 80.0 or r["is_cutoff"])
    driver_pct_of_fleet = round(drivers_at_80 / total_drivers * 100, 1) if total_drivers else 0.0

    driver_summary = {
        "drivers_at_80": drivers_at_80,
        "total_drivers": total_drivers,
        "driver_pct_of_fleet": driver_pct_of_fleet,
    }

    # ── 1b. Least profitable drivers (ascending by profit) ──────────────────────
    least_profitable_rows = sorted(
        [
            {
                "rank": i,
                "driver": r["driver"],
                "rides": r["rides"],
                "profit": r["profit"],
            }
            for i, r in enumerate(
                sorted(driver_rows, key=lambda x: x["profit"]), 1
            )
        ],
        key=lambda x: x["profit"],
    )

    # ── 2. Services by ride count and by profit ─────────────────────────────────
    service_q = (
        db.query(
            Ride.service_name,
            func.count(Ride.ride_id).label("ride_count"),
            func.sum(Ride.net_pay - Ride.z_rate).label("profit"),
        )
        .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
        .group_by(Ride.service_name)
    )
    if company:
        service_q = service_q.filter(PayrollBatch.company_name == company)

    raw_services = service_q.all()

    # Build two separate ranked lists: by volume and by profit
    service_by_volume = sorted(
        [
            {
                "service": r.service_name or "—",
                "ride_count": int(r.ride_count or 0),
                "profit": round(float(r.profit or 0), 2),
            }
            for r in raw_services
        ],
        key=lambda x: x["ride_count"],
        reverse=True,
    )
    service_by_volume = _pareto_cutoff(service_by_volume, "ride_count")

    service_by_profit = sorted(
        [
            {
                "service": r.service_name or "—",
                "ride_count": int(r.ride_count or 0),
                "profit": round(float(r.profit or 0), 2),
            }
            for r in raw_services
        ],
        key=lambda x: x["profit"],
        reverse=True,
    )
    service_by_profit = _pareto_cutoff(service_by_profit, "profit")

    total_services = len(raw_services)

    services_vol_at_80 = sum(
        1 for r in service_by_volume if r["cumulative_pct"] <= 80.0 or r["is_cutoff"]
    )
    services_profit_at_80 = sum(
        1 for r in service_by_profit if r["cumulative_pct"] <= 80.0 or r["is_cutoff"]
    )

    service_summary = {
        "total_services": total_services,
        "services_vol_at_80": services_vol_at_80,
        "services_profit_at_80": services_profit_at_80,
        "vol_pct_of_services": round(services_vol_at_80 / total_services * 100, 1)
        if total_services
        else 0.0,
        "profit_pct_of_services": round(services_profit_at_80 / total_services * 100, 1)
        if total_services
        else 0.0,
    }

    # ── 3. Pay periods by profit ────────────────────────────────────────────────
    period_q = (
        db.query(
            PayrollBatch.payroll_batch_id,
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
    )
    if company:
        period_q = period_q.filter(PayrollBatch.company_name == company)

    def fmt_date(d):
        return d.strftime("%-m/%-d/%Y") if d else "—"

    period_rows_raw = period_q.all()

    # Only count periods with positive profit for Pareto (negative periods skew it)
    period_rows = sorted(
        [
            {
                "batch_id": r.payroll_batch_id,
                "company": r.company_name or "—",
                "period_start": fmt_date(r.period_start),
                "period_end": fmt_date(r.period_end),
                "profit": round(float(r.profit or 0), 2),
                "rides": int(r.rides or 0),
            }
            for r in period_rows_raw
        ],
        key=lambda x: x["profit"],
        reverse=True,
    )

    # Pareto on profit (only meaningful for positive values; we still include negatives
    # in the list but the cutoff logic will place them past 80%)
    period_rows = _pareto_cutoff(period_rows, "profit")

    total_periods = len(period_rows)
    periods_at_80 = sum(
        1 for r in period_rows if r["cumulative_pct"] <= 80.0 or r["is_cutoff"]
    )

    period_summary = {
        "total_periods": total_periods,
        "periods_at_80": periods_at_80,
        "period_pct": round(periods_at_80 / total_periods * 100, 1)
        if total_periods
        else 0.0,
    }

    return {
        "driver_rows": driver_rows,
        "least_profitable_rows": least_profitable_rows,
        "driver_summary": driver_summary,
        "service_by_volume": service_by_volume,
        "service_by_profit": service_by_profit,
        "service_summary": service_summary,
        "period_rows": period_rows,
        "period_summary": period_summary,
    }


@router.get("/", name="pareto_page")
def pareto_page(
    request: Request,
    company: str | None = Query(None),
    db: Session = Depends(get_db),
):
    _wants_json = (
        "application/json" in request.headers.get("content-type", "")
        or "application/json" in request.headers.get("accept", "")
    )

    companies = _get_companies(db)
    data = _build_pareto(db, company=company)

    if _wants_json:
        try:
            return JSONResponse({
                "companies": companies,
                "selected_company": company,
                **data,
            })
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    return templates().TemplateResponse(
        request,
        "pareto.html",
        {
            "companies": companies,
            "selected_company": company,
            **data,
        },
    )
