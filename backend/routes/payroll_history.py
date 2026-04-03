import re
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


def _clean_batch_ref(raw: str, company_name: str | None = None) -> str:
    """
    Strip the company name prefix from a batch_ref filename and return a
    cleaner display string.

    E.g. "Prod_SP_Acumen International_01092026 (2)(AutoRecovered)"
         -> "01092026 (2)"

    Strategy:
      1. Remove known company name if it appears in the string.
      2. Strip common leading separators/prefixes (Prod_SP_, Prod_, SP_, etc.).
      3. Strip trailing noise like "(AutoRecovered)", ".xlsx", ".pdf".
      4. Collapse multiple spaces and trim.
    """
    s = raw

    # 1. Remove company name substring (case-insensitive)
    if company_name:
        s = re.sub(re.escape(company_name), "", s, flags=re.IGNORECASE)

    # 2. Strip common filename prefixes (e.g. "Prod_SP_", "Prod_", "SP_")
    s = re.sub(r"^(Prod_SP_|Prod_|SP_)+", "", s, flags=re.IGNORECASE)

    # 3. Remove leading/trailing underscores and separators left behind
    s = s.strip("_- ")

    # 4. Remove file extension noise
    s = re.sub(r"\.(xlsx|xls|pdf|csv)$", "", s, flags=re.IGNORECASE)

    # 5. Remove "(AutoRecovered)" tag (and similar parenthetical noise)
    s = re.sub(r"\(AutoRecovered\)", "", s, flags=re.IGNORECASE)

    # 6. Collapse whitespace and trim
    s = re.sub(r"\s{2,}", " ", s).strip("_- ")

    return s if s else raw


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
        # has_withholding_data: True only when DriverBalance rows exist for this batch
        has_withholding_data = wh is not None and int(wh.withheld_drivers) > 0
        total_paid_out = round(total_z_rate - total_withheld, 2)

        raw_ref = b.batch_ref or ""
        total_profit = round(total_net_pay - total_z_rate, 2)
        batch_rows.append({
            "batch_id": b.payroll_batch_id,
            "company_name": b.company_name,
            "source": b.source,
            "batch_ref": raw_ref or "—",
            "batch_ref_display": _clean_batch_ref(raw_ref, b.company_name) if raw_ref else "—",
            "period_start": _fmt_date(b.period_start),
            "period_end": _fmt_date(b.period_end),
            "uploaded_at": b.uploaded_at.strftime("%-m/%-d/%Y") if b.uploaded_at else "—",
            "ride_count": ride_count,
            "total_z_rate": total_z_rate,
            "total_net_pay": total_net_pay,
            "total_profit": total_profit,
            "total_withheld": total_withheld,
            "withheld_drivers": withheld_drivers,
            "has_withholding_data": has_withholding_data,
            "total_paid_out": total_paid_out,
            "finalized_at": b.finalized_at,
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

        profit = round(net_pay - z_rate, 2)
        driver_rows.append({
            "person_id": d.person_id,
            "driver": d.driver or "—",
            "code": d.code or "—",
            "ride_count": int(d.ride_count),
            "gross_pay": gross,
            "z_rate": z_rate,
            "net_pay": net_pay,
            "profit": profit,
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
        "profit": round(total_net_pay - total_z_rate, 2),
        "withheld": round(total_withheld, 2),
        "paid_out": round(total_paid_out, 2),
    }

    has_withholding_data = len(balance_records) > 0
    raw_ref = batch.batch_ref or ""

    return templates().TemplateResponse(
        request,
        "payroll_history_detail.html",
        {
            "batch": batch,
            "batch_id": batch_id,
            "batch_ref_display": _clean_batch_ref(raw_ref, batch.company_name) if raw_ref else "—",
            "period_start": _fmt_date(batch.period_start),
            "period_end": _fmt_date(batch.period_end),
            "uploaded_at": batch.uploaded_at.strftime("%-m/%-d/%Y") if batch.uploaded_at else "—",
            "driver_rows": driver_rows,
            "totals": totals,
            "has_withholding_data": has_withholding_data,
        },
    )
