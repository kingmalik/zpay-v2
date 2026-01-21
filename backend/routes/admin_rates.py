from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.templating import Jinja2Templates
from fastapi import BackgroundTasks


from backend.db import get_db
from backend.db.models import ZRateService, ZRateOverride  # make sure ZRateOverride exists

router = APIRouter(prefix="/rates", tags=["admin-rates"])


def _templates(request: Request) -> Jinja2Templates:
    """
    Prefer app.state.templates (set in app.py), fallback to backend/templates.
    """
    t = getattr(request.app.state, "templates", None)
    if t is not None:
        return t
    base = Path(__file__).resolve().parents[1]  # backend/
    return Jinja2Templates(directory=str(base / "templates"))


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
    return _templates(request).TemplateResponse(
        "admin/rates_list.html",
        {
            "request": request,
            "source": source,
            "company_name": company_name,
            "services": services,
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
        .order_by(ZRateOverride.effective_start.asc())
        .all()
    )

    return _templates(request).TemplateResponse(
        "admin/rate_overrides.html",
        {"request": request, "svc": svc, "overrides": overrides},
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
        effective_start=effective_start,
        effective_end=effective_end,
        rate=rate_dec,
        currency=currency or "USD",
        active=True,
        note=(note.strip() or None),
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