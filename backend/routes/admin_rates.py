from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from backend.utils.roles import require_role
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.templating import Jinja2Templates
from fastapi import BackgroundTasks


from sqlalchemy import func, or_, and_

from backend.db import get_db
from backend.db.models import Ride, ZRateService, ZRateOverride, PayrollBatch

router = APIRouter(prefix="/rates", tags=["admin-rates"], dependencies=[Depends(require_role("admin"))])


def _templates(request: Request) -> Jinja2Templates:
    """
    Prefer app.state.templates (set in app.py), fallback to backend/templates.
    """
    t = getattr(request.app.state, "templates", None)
    if t is not None:
        return t
    base = Path(__file__).resolve().parents[1]  # backend/
    return Jinja2Templates(directory=str(base / "templates"))


_FALLBACK_FA = 49.72
_FALLBACK_ED = 44.86


@router.get("/review", name="rate_review")
def rate_review(request: Request, db: Session = Depends(get_db)):
    """Show only rides that were backfilled with generic placeholder rates (or still z_rate=0)."""
    flagged = (
        db.query(
            Ride.service_name,
            PayrollBatch.source,
            PayrollBatch.company_name,
            func.count(Ride.ride_id).label("ride_count"),
            func.avg(Ride.z_rate).label("avg_z_rate"),
            func.avg(Ride.net_pay).label("avg_net_pay"),
            func.avg(Ride.miles).label("avg_miles"),
        )
        .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
        .filter(
            or_(
                Ride.z_rate == 0,
                and_(PayrollBatch.source == "acumen", Ride.z_rate == _FALLBACK_FA),
                and_(PayrollBatch.source == "maz",    Ride.z_rate == _FALLBACK_ED),
            )
        )
        .group_by(Ride.service_name, PayrollBatch.source, PayrollBatch.company_name)
        .order_by(func.count(Ride.ride_id).desc())
        .all()
    )

    routes = [
        {
            "service_name": r.service_name or "—",
            "source": r.source,
            "company_name": r.company_name,
            "ride_count": int(r.ride_count or 0),
            "current_rate": round(float(r.avg_z_rate or 0), 2),
            "partner_pays": round(float(r.avg_net_pay or 0), 2),
            "miles": round(float(r.avg_miles or 0), 1),
        }
        for r in flagged
    ]

    return _templates(request).TemplateResponse(
        request,
        "admin/rate_review.html",
        {"routes": routes, "total": len(routes)},
    )


@router.post("/review/apply", name="rate_review_apply")
def apply_review_rate(
    request: Request,
    service_name: str = Form(...),
    source: str = Form(...),
    new_rate: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        rate = Decimal(new_rate)
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=400, detail="Invalid rate")

    # Update only rides that still have a fallback/unset rate for this service+source
    subq = db.query(PayrollBatch.payroll_batch_id).filter(
        PayrollBatch.source == source
    ).subquery()
    db.query(Ride).filter(
        Ride.service_name == service_name,
        Ride.payroll_batch_id.in_(subq),
        or_(
            Ride.z_rate == 0,
            Ride.z_rate == _FALLBACK_FA,
            Ride.z_rate == _FALLBACK_ED,
        ),
    ).update({"z_rate": float(rate)}, synchronize_session=False)

    # Update z_rate_service default_rate
    svc = (
        db.query(ZRateService)
        .filter(ZRateService.service_name == service_name, ZRateService.source == source)
        .one_or_none()
    )
    if svc:
        svc.default_rate = rate
        db.add(svc)

    db.commit()
    return RedirectResponse(url="/admin/rates/review", status_code=303)


@router.get("")
def rates_list(
    request: Request,
    source: str = "",
    company_name: str = "",
    db: Session = Depends(get_db),
):
    q = db.query(ZRateService).order_by(ZRateService.service_name.asc())

    # If you used '' as defaults (recommended), this works great.
    # If your DB stores NULLs, you may need coalesce logic in SQL, but keep it simple for now.
    q = q.filter(ZRateService.source == source, ZRateService.company_name == company_name)

    services = q.all()

    unmatched_services = (
        db.query(Ride.service_name, func.count(Ride.ride_id).label("count"))
        .filter(Ride.z_rate == 0, Ride.service_name.isnot(None))
        .group_by(Ride.service_name)
        .order_by(func.count(Ride.ride_id).desc())
        .all()
    )

    return _templates(request).TemplateResponse(
        request,
        "admin/rates_list.html",
        {
            "source": source,
            "company_name": company_name,
            "services": services,
            "unmatched_services": unmatched_services,
        },
    )


@router.post("/{service_id}/set-default")
def set_default_rate(
    service_id: int,
    source: str = Form(""),
    company_name: str = Form(""),
    default_rate: str = Form(""),
    db: Session = Depends(get_db),
):
    svc = (
        db.query(ZRateService)
        .filter(ZRateService.z_rate_service_id == service_id)
        .one_or_none()
    )
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")

    try:
        svc.default_rate = Decimal(default_rate) if default_rate.strip() else None
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=400, detail="Invalid default_rate")

    db.add(svc)
    db.commit()

    return RedirectResponse(
        url=f"/admin/rates?source={source}&company_name={company_name}",
        status_code=303,
    )


@router.get("/{service_id}/overrides")
def overrides_page(
    request: Request,
    service_id: int,
    db: Session = Depends(get_db),
):
    svc = (
        db.query(ZRateService)
        .filter(ZRateService.z_rate_service_id == service_id)
        .one_or_none()
    )
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")

    overrides = (
        db.query(ZRateOverride)
        .filter(ZRateOverride.z_rate_service_id == service_id)
        .order_by(ZRateOverride.effective_during.asc())
        .all()
    )

    return _templates(request).TemplateResponse(
        request,
        "admin/rate_overrides.html",
        {"svc": svc, "overrides": overrides},
    )


@router.post("/{service_id}/overrides/add")
def add_override(
    service_id: int,
    effective_start: date = Form(...),
    effective_end: date = Form(...),
    rate: str = Form(...),
    currency: str = Form("USD"),
    note: str = Form(""),
    db: Session = Depends(get_db),
):
    if effective_end < effective_start:
        raise HTTPException(status_code=400, detail="End date must be on/after start date")

    try:
        rate_dec = Decimal(rate)
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=400, detail="Invalid rate")

    ov = ZRateOverride(
        z_rate_service_id=service_id,
        effective_during=f"[{effective_start},{effective_end}]",
        override_rate=rate_dec,
        active=True,
        reason=(note.strip() or None),
    )

    try:
        db.add(ov)
        db.commit()
    except IntegrityError:
        db.rollback()
        # Most likely overlap constraint violation (once you add it)
        raise HTTPException(
            status_code=409,
            detail="Override overlaps an existing override for this service.",
        )

    return RedirectResponse(url=f"/admin/rates/{service_id}/overrides", status_code=303)

@router.post("/new")
def create_service(
    source: str = Form(""),
    company_name: str = Form(""),
    service_name: str = Form(...),
    default_rate: str = Form(...),
    db: Session = Depends(get_db),
):
    """Create a new ZRateService entry for a previously unmatched service."""
    try:
        rate_dec = Decimal(default_rate) if default_rate.strip() else Decimal("0")
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=400, detail="Invalid default_rate")

    import re
    service_key = re.sub(r"[^a-z0-9_]", "_", service_name.strip().lower())

    svc = ZRateService(
        source=source,
        company_name=company_name,
        service_name=service_name.strip(),
        service_key=service_key,
        default_rate=rate_dec,
        active=True,
    )
    try:
        db.add(svc)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A rate entry for this service already exists.",
        )

    return RedirectResponse(
        url=f"/admin/rates?source={source}&company_name={company_name}",
        status_code=303,
    )


@router.post("/recalculate")
def recalculate(
    background: BackgroundTasks,
    source: str = Form(""),
    company_name: str = Form(""),
    payroll_batch_id: str = Form(""),  # optional
    db: Session = Depends(get_db),
):
    from backend.services.recalculate import recalc_rates_and_summary 
    # fire-and-forget after response (so UI doesn't hang)
    background.add_task(
        recalc_rates_and_summary,
        source=source,
        company_name=company_name,
        payroll_batch_id=int(payroll_batch_id) if payroll_batch_id.strip() else None,
    )
    return RedirectResponse(
        url=f"/admin/rates?source={source}&company_name={company_name}",
        status_code=303,
    )