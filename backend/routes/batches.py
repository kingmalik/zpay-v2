from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import PayrollBatch, Ride

router = APIRouter(prefix="/batches", tags=["batches"])

_templates = None


def templates():
    global _templates
    if _templates is None:
        templates_dir = Path(__file__).resolve().parents[1] / "templates"
        _templates = Jinja2Templates(directory=str(templates_dir))
    return _templates


@router.get("/")
def batches_page(request: Request, db: Session = Depends(get_db)):
    rows = (
        db.query(
            PayrollBatch.payroll_batch_id,
            PayrollBatch.company_name,
            PayrollBatch.source,
            PayrollBatch.period_start,
            PayrollBatch.period_end,
            PayrollBatch.uploaded_at,
            func.count(Ride.ride_id).label("ride_count"),
            func.coalesce(func.sum(Ride.net_pay), 0).label("total_revenue"),
            func.coalesce(func.sum(Ride.z_rate), 0).label("total_cost"),
        )
        .outerjoin(Ride, Ride.payroll_batch_id == PayrollBatch.payroll_batch_id)
        .group_by(
            PayrollBatch.payroll_batch_id,
            PayrollBatch.company_name,
            PayrollBatch.source,
            PayrollBatch.period_start,
            PayrollBatch.period_end,
            PayrollBatch.uploaded_at,
        )
        .order_by(PayrollBatch.uploaded_at.desc())
        .all()
    )

    batches = [
        {
            "payroll_batch_id": r.payroll_batch_id,
            "company_name": r.company_name,
            "source": r.source,
            "period_start": r.period_start,
            "period_end": r.period_end,
            "uploaded_at": r.uploaded_at,
            "ride_count": int(r.ride_count or 0),
            "total_revenue": round(float(r.total_revenue or 0), 2),
            "total_cost": round(float(r.total_cost or 0), 2),
        }
        for r in rows
    ]

    return templates().TemplateResponse(
        request,
        "batches.html",
        {"batches": batches},
    )


@router.post("/{batch_id}/delete")
def delete_batch(batch_id: int, db: Session = Depends(get_db)):
    batch = db.query(PayrollBatch).filter(
        PayrollBatch.payroll_batch_id == batch_id
    ).first()
    if batch:
        db.delete(batch)
        db.commit()
    return RedirectResponse(url="/batches/", status_code=303)
