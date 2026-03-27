from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import PayrollBatch, Ride, Person, DriverBalance

router = APIRouter(prefix="/payroll", tags=["payroll_history"])

_templates = None


def templates():
    global _templates
    if _templates is None:
        templates_dir = Path(__file__).resolve().parents[1] / "templates"
        _templates = Jinja2Templates(directory=str(templates_dir))
    return _templates


def _fmt_date(d):
    if d is None:
        return "—"
    return d.strftime("%-m/%-d/%Y")


# ── Batch list ────────────────────────────────────────────────────────────────

@router.get("/history", name="payroll_history")
def payroll_history(request: Request, db: Session = Depends(get_db)):
    """
    Lists all PayrollBatches ordered by date desc, with per-batch summary.
    """
    batches_raw = (
        db.query(PayrollBatch)
        .order_by(PayrollBatch.period_start.desc().nullslast(), PayrollBatch.uploaded_at.desc())
        .all()
    )

    # Aggregate rides per batch in one query
    ride_agg = (
        db.query(
            Ride.payroll_batch_id,
            func.count(Ride.ride_id).label("ride_count"),
            func.coalesce(func.sum(Ride.z_rate), 0).label("total_z_rate"),
            func.coalesce(func.sum(Ride.net_pay), 0).label("total_net_pay"),
        )
        .group_by(Ride.payroll_batch_id)
        .all()
    )
    agg_map = {row.payroll_batch_id: row for row in ride_agg}

    # Withheld totals: sum of carried_over per batch
    withheld_agg = (
        db.query(
            DriverBalance.payroll_batch_id,
            func.coalesce(func.sum(DriverBalance.carried_over), 0).label("total_withheld"),
            func.count(DriverBalance.driver_balance_id).label("withheld_drivers"),
        )
        .group_by(DriverBalance.payroll_batch_id)
        .all()
    )
    withheld_map = {row.payroll_batch_id: row for row in withheld_agg}

    batch_rows = []
    for b in batches_raw:
        agg = agg_map.get(b.payroll_batch_id)
        wh = withheld_map.get(b.payroll_batch_id)
        ride_count = int(agg.ride_count) if agg else 0
        total_z_rate = round(float(agg.total_z_rate), 2) if agg else 0.0
        total_net_pay = round(float(agg.total_net_pay), 2) if agg else 0.0
        total_withheld = round(float(wh.total_withheld), 2) if wh else 0.0
        withheld_drivers = int(wh.withheld_drivers) if wh else 0
        total_paid_out = round(total_z_rate - total_withheld, 2)

        batch_rows.append({
            "batch_id": b.payroll_batch_id,
            "company_name": b.company_name,
            "source": b.source,
            "batch_ref": b.batch_ref or "—",
            "period_start": _fmt_date(b.period_start),
            "period_end": _fmt_date(b.period_end),
            "uploaded_at": b.uploaded_at.strftime("%-m/%-d/%Y") if b.uploaded_at else "—",
            "ride_count": ride_count,
            "total_z_rate": total_z_rate,
            "total_net_pay": total_net_pay,
            "total_withheld": total_withheld,
            "withheld_drivers": withheld_drivers,
            "total_paid_out": total_paid_out,
        })

    return templates().TemplateResponse(
        request,
        "payroll_history.html",
        {"batch_rows": batch_rows},
    )


# ── Batch detail ──────────────────────────────────────────────────────────────

@router.get("/history/{batch_id}", name="payroll_history_detail")
def payroll_history_detail(batch_id: int, request: Request, db: Session = Depends(get_db)):
    """
    Per-driver breakdown for a single PayrollBatch.
    """
    batch = db.query(PayrollBatch).filter(PayrollBatch.payroll_batch_id == batch_id).first()
    if batch is None:
        from fastapi.responses import HTMLResponse
        return HTMLResponse("<h2>Batch not found</h2>", status_code=404)

    # Per-driver ride aggregates for this batch
    driver_agg = (
        db.query(
            Person.person_id,
            Person.full_name.label("driver"),
            Person.external_id.label("code"),
            func.count(Ride.ride_id).label("ride_count"),
            func.coalesce(func.sum(Ride.gross_pay), 0).label("gross_pay"),
            func.coalesce(func.sum(Ride.z_rate), 0).label("z_rate_total"),
            func.coalesce(func.sum(Ride.net_pay), 0).label("net_pay_total"),
        )
        .join(Ride, Ride.person_id == Person.person_id)
        .filter(Ride.payroll_batch_id == batch_id)
        .group_by(Person.person_id, Person.full_name, Person.external_id)
        .order_by(Person.full_name.asc())
        .all()
    )

    # DriverBalance records for THIS batch (withheld amounts)
    balance_records = (
        db.query(DriverBalance)
        .filter(DriverBalance.payroll_batch_id == batch_id)
        .all()
    )
    balance_map = {b.person_id: round(float(b.carried_over or 0), 2) for b in balance_records}

    driver_rows = []
    total_rides = 0
    total_gross = 0.0
    total_z_rate = 0.0
    total_net_pay = 0.0
    total_withheld = 0.0
    total_paid_out = 0.0

    for d in driver_agg:
        gross = round(float(d.gross_pay), 2)
        z_rate = round(float(d.z_rate_total), 2)
        net_pay = round(float(d.net_pay_total), 2)
        withheld = balance_map.get(d.person_id, 0.0)
        # paid_out = what the driver actually received this batch
        paid_out = round(z_rate - withheld, 2)
        is_withheld = withheld > 0

        driver_rows.append({
            "person_id": d.person_id,
            "driver": d.driver or "—",
            "code": d.code or "—",
            "ride_count": int(d.ride_count),
            "gross_pay": gross,
            "z_rate": z_rate,
            "net_pay": net_pay,
            "withheld": withheld,
            "paid_out": paid_out,
            "is_withheld": is_withheld,
        })

        total_rides += int(d.ride_count)
        total_gross += gross
        total_z_rate += z_rate
        total_net_pay += net_pay
        total_withheld += withheld
        total_paid_out += paid_out

    totals = {
        "rides": total_rides,
        "gross_pay": round(total_gross, 2),
        "z_rate": round(total_z_rate, 2),
        "net_pay": round(total_net_pay, 2),
        "withheld": round(total_withheld, 2),
        "paid_out": round(total_paid_out, 2),
    }

    return templates().TemplateResponse(
        request,
        "payroll_history_detail.html",
        {
            "batch": batch,
            "batch_id": batch_id,
            "period_start": _fmt_date(batch.period_start),
            "period_end": _fmt_date(batch.period_end),
            "uploaded_at": batch.uploaded_at.strftime("%-m/%-d/%Y") if batch.uploaded_at else "—",
            "driver_rows": driver_rows,
            "totals": totals,
        },
    )
