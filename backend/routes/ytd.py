from __future__ import annotations
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from pathlib import Path
from datetime import date

from ..db import get_db
from ..db.models import PayrollBatch, Ride, Person

router = APIRouter(prefix="/ytd", tags=["ytd"])

_templates = None
def templates():
    global _templates
    if _templates is None:
        _templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))
    return _templates


@router.get("/", response_class=HTMLResponse, name="ytd_page")
def ytd_page(request: Request, year: int = None, db: Session = Depends(get_db)):
    _wants_json = (
        "application/json" in request.headers.get("content-type", "")
        or "application/json" in request.headers.get("accept", "")
    )

    if not year:
        year = date.today().year

    base_batches = (
        db.query(PayrollBatch)
        .filter(
            PayrollBatch.finalized_at.isnot(None),
            extract("year", PayrollBatch.period_start) == year,
        )
        .all()
    )
    batch_ids = [b.payroll_batch_id for b in base_batches]

    if not batch_ids:
        if _wants_json:
            return JSONResponse({"year": year, "company_totals": [], "weeks": [], "drivers": [], "no_data": True})
        return templates().TemplateResponse(
            request=request,
            name="ytd.html",
            context={"year": year, "company_totals": [], "weeks": [], "drivers": [], "no_data": True},
        )

    company_rows = (
        db.query(
            PayrollBatch.company_name,
            func.count(Ride.ride_id).label("rides"),
            func.sum(Ride.net_pay).label("revenue"),
            func.sum(Ride.z_rate).label("cost"),
            func.sum(Ride.net_pay - Ride.z_rate).label("profit"),
        )
        .join(Ride, Ride.payroll_batch_id == PayrollBatch.payroll_batch_id)
        .filter(PayrollBatch.payroll_batch_id.in_(batch_ids))
        .group_by(PayrollBatch.company_name)
        .all()
    )
    company_totals = [
        {
            "company": r.company_name,
            "rides": int(r.rides or 0),
            "revenue": round(float(r.revenue or 0), 2),
            "cost": round(float(r.cost or 0), 2),
            "profit": round(float(r.profit or 0), 2),
        }
        for r in company_rows
    ]

    week_rows = (
        db.query(
            PayrollBatch.week_start,
            PayrollBatch.company_name,
            func.count(Ride.ride_id).label("rides"),
            func.sum(Ride.net_pay).label("revenue"),
            func.sum(Ride.net_pay - Ride.z_rate).label("profit"),
        )
        .join(Ride, Ride.payroll_batch_id == PayrollBatch.payroll_batch_id)
        .filter(PayrollBatch.payroll_batch_id.in_(batch_ids))
        .group_by(PayrollBatch.week_start, PayrollBatch.company_name)
        .order_by(PayrollBatch.week_start)
        .all()
    )

    weeks_dict: dict = {}
    for r in week_rows:
        k = r.week_start
        if k not in weeks_dict:
            weeks_dict[k] = {
                "week_start": k,
                "firstalt_revenue": 0.0, "firstalt_profit": 0.0,
                "everdriven_revenue": 0.0, "everdriven_profit": 0.0,
                "rides": 0,
            }
        if (r.company_name or "").lower() == "firstalt":
            weeks_dict[k]["firstalt_revenue"] += float(r.revenue or 0)
            weeks_dict[k]["firstalt_profit"] += float(r.profit or 0)
        else:
            weeks_dict[k]["everdriven_revenue"] += float(r.revenue or 0)
            weeks_dict[k]["everdriven_profit"] += float(r.profit or 0)
        weeks_dict[k]["rides"] += int(r.rides or 0)

    cumulative = 0.0
    weeks = []
    for w in sorted(weeks_dict.values(), key=lambda x: x["week_start"] or date.min):
        cumulative += w["firstalt_profit"] + w["everdriven_profit"]
        w["cumulative_profit"] = round(cumulative, 2)
        for k in ("firstalt_revenue", "firstalt_profit", "everdriven_revenue", "everdriven_profit"):
            w[k] = round(w[k], 2)
        weeks.append(w)

    driver_rows = (
        db.query(
            Person.person_id,
            Person.full_name,
            func.count(Ride.ride_id).label("rides"),
            func.sum(Ride.net_pay).label("revenue"),
            func.sum(Ride.z_rate).label("cost"),
            func.sum(Ride.net_pay - Ride.z_rate).label("profit"),
            func.count(func.distinct(PayrollBatch.payroll_batch_id)).label("weeks_active"),
        )
        .join(Ride, Ride.person_id == Person.person_id)
        .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
        .filter(PayrollBatch.payroll_batch_id.in_(batch_ids))
        .group_by(Person.person_id, Person.full_name)
        .order_by(func.sum(Ride.net_pay - Ride.z_rate).desc())
        .all()
    )
    drivers = [
        {
            "person_id": r.person_id,
            "name": r.full_name or f"Driver #{r.person_id}",
            "rides": int(r.rides or 0),
            "revenue": round(float(r.revenue or 0), 2),
            "cost": round(float(r.cost or 0), 2),
            "profit": round(float(r.profit or 0), 2),
            "weeks_active": int(r.weeks_active or 0),
        }
        for r in driver_rows
    ]

    if _wants_json:
        try:
            weeks_out = []
            for w in weeks:
                ws = w.get("week_start")
                weeks_out.append({
                    **w,
                    "week_start": ws.isoformat() if ws and hasattr(ws, "isoformat") else str(ws) if ws else None,
                })
            return JSONResponse({
                "year": year,
                "company_totals": company_totals,
                "weeks": weeks_out,
                "drivers": drivers,
                "no_data": False,
            })
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    return templates().TemplateResponse(
        request=request,
        name="ytd.html",
        context={
            "year": year,
            "company_totals": company_totals,
            "weeks": weeks,
            "drivers": drivers,
            "no_data": False,
        },
    )
