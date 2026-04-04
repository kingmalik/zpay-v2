"""Auto-reconciliation — compare expected revenue (net_pay) vs driver cost (z_rate) per batch."""

from fastapi import APIRouter, Request, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db.db import get_db
from backend.db.models import PayrollBatch, Ride

router = APIRouter(tags=["reconciliation"])


@router.get("/reconciliation")
async def reconciliation_page(
    request: Request,
    source: str = "",
    company_name: str = "",
    db: Session = Depends(get_db),
):
    templates = request.app.state.templates

    # Per batch: revenue (sum net_pay), cost (sum z_rate), rides
    q = db.query(
        PayrollBatch.payroll_batch_id,
        PayrollBatch.batch_ref,
        PayrollBatch.source,
        PayrollBatch.company_name,
        PayrollBatch.week_start,
        PayrollBatch.week_end,
        func.sum(Ride.net_pay).label("total_revenue"),
        func.sum(Ride.z_rate).label("total_cost"),
        func.sum(Ride.net_pay - Ride.z_rate).label("total_profit"),
        func.count(Ride.ride_id).label("ride_count"),
    ).outerjoin(Ride, Ride.payroll_batch_id == PayrollBatch.payroll_batch_id)

    if source:
        q = q.filter(PayrollBatch.source == source)
    if company_name:
        q = q.filter(PayrollBatch.company_name.ilike(f"%{company_name}%"))

    q = q.group_by(
        PayrollBatch.payroll_batch_id,
        PayrollBatch.batch_ref,
        PayrollBatch.source,
        PayrollBatch.company_name,
        PayrollBatch.week_start,
        PayrollBatch.week_end,
    ).order_by(PayrollBatch.week_start.desc().nullslast())

    rows = q.all()

    # Build reconciliation data
    batches = []
    total_matched = 0
    total_mismatched = 0
    largest_discrepancy = 0.0

    for row in rows:
        revenue = float(row.total_revenue or 0)
        cost = float(row.total_cost or 0)
        profit = float(row.total_profit or 0)

        # Check for zero-rate rides (cost == 0 but rides exist means uncosted)
        has_zero_rates = cost == 0 and row.ride_count > 0
        # Mismatch if any rides have zero cost or if profit margin is negative
        is_match = not has_zero_rates and profit >= 0

        abs_diff = abs(profit)
        if not is_match and abs_diff > largest_discrepancy:
            largest_discrepancy = abs_diff

        if is_match:
            total_matched += 1
        else:
            total_mismatched += 1

        # Build label
        week_label = ""
        if row.week_start:
            week_label = row.week_start.strftime("%-m/%-d")
            if row.week_end:
                week_label += f" — {row.week_end.strftime('%-m/%-d')}"

        batches.append({
            "id": row.payroll_batch_id,
            "batch_ref": row.batch_ref or f"Batch #{row.payroll_batch_id}",
            "week_label": week_label or "—",
            "source": row.source,
            "company_name": row.company_name,
            "revenue": revenue,
            "cost": cost,
            "profit": profit,
            "is_match": is_match,
            "has_zero_rates": has_zero_rates,
            "ride_count": row.ride_count,
        })

    return templates.TemplateResponse("reconciliation.html", {
        "request": request,
        "batches": batches,
        "source": source,
        "company_name": company_name,
        "total_matched": total_matched,
        "total_mismatched": total_mismatched,
        "largest_discrepancy": largest_discrepancy,
        "total_batches": len(batches),
    })
