from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import csv
import io
import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, JSONResponse
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
    _wants_json = (
        "application/json" in request.headers.get("content-type", "")
        or "application/json" in request.headers.get("accept", "")
    )

    # Rates are discrete set numbers per route — never averaged across trips.
    # These rides are flagged because z_rate is 0 or a fallback constant.
    # current_rate comes from ZRateService.default_rate (the actual set rate),
    # not from an avg of ride z_rates.  Use MAX for partner_pays and miles:
    # a route's pay and distance are fixed per contract, not a distribution.
    flagged = (
        db.query(
            Ride.service_name,
            PayrollBatch.source,
            PayrollBatch.company_name,
            func.count(Ride.ride_id).label("ride_count"),
            func.max(Ride.net_pay).label("route_net_pay"),
            func.max(Ride.miles).label("route_miles"),
            func.max(ZRateService.default_rate).label("set_rate"),
        )
        .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
        .outerjoin(
            ZRateService,
            and_(
                ZRateService.service_name == Ride.service_name,
                ZRateService.source == PayrollBatch.source,
            )
        )
        .filter(
            PayrollBatch.status.notin_(["complete"]),
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
            "current_rate": round(float(r.set_rate or 0), 2),
            "partner_pays": round(float(r.route_net_pay or 0), 2),
            "miles": round(float(r.route_miles or 0), 1),
        }
        for r in flagged
    ]

    if _wants_json:
        try:
            return JSONResponse({"routes": routes, "total": len(routes)})
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

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
    company_name: str = Form(""),
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

    # Upsert z_rate_service so the rate is remembered for future payroll batches
    svc = (
        db.query(ZRateService)
        .filter(
            ZRateService.service_name == service_name,
            ZRateService.source == source,
            ZRateService.company_name == company_name,
        )
        .one_or_none()
    )
    if svc:
        svc.default_rate = rate
        db.add(svc)
    else:
        service_key = re.sub(r"[^a-z0-9_]", "_", service_name.strip().lower())
        # Ensure key uniqueness by appending source if needed
        existing_key = db.query(ZRateService).filter(ZRateService.service_key == service_key).one_or_none()
        if existing_key:
            service_key = f"{service_key}_{re.sub(r'[^a-z0-9_]', '_', source.lower())}"
        svc = ZRateService(
            source=source,
            company_name=company_name,
            service_name=service_name.strip(),
            service_key=service_key,
            default_rate=rate,
            active=True,
        )
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
    _wants_json = (
        "application/json" in request.headers.get("content-type", "")
        or "application/json" in request.headers.get("accept", "")
    )

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

    if _wants_json:
        try:
            services_out = [
                {
                    "id": s.z_rate_service_id,
                    "service_name": s.service_name,
                    "service_key": s.service_key,
                    "source": s.source,
                    "company_name": s.company_name,
                    "default_rate": float(s.default_rate) if s.default_rate is not None else None,
                    "active": s.active,
                }
                for s in services
            ]
            unmatched_out = [
                {"service_name": r.service_name, "count": int(r.count)}
                for r in unmatched_services
            ]
            return JSONResponse({
                "source": source,
                "company_name": company_name,
                "services": services_out,
                "unmatched_services": unmatched_out,
            })
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

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


@router.post("/backfill-zero-rates")
def backfill_zero_rates(db: Session = Depends(get_db)):
    """One-time endpoint: run fix_unmatched_rates logic inside Railway environment."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
    import importlib
    import io
    from contextlib import redirect_stdout

    # Capture stdout from the script
    f = io.StringIO()
    try:
        spec = importlib.util.spec_from_file_location(
            "fix_unmatched_rates",
            os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "fix_unmatched_rates.py")
        )
        mod = importlib.util.module_from_spec(spec)
        with redirect_stdout(f):
            spec.loader.exec_module(mod)
            exit_code = mod.main()
        output = f.getvalue()
        return JSONResponse({"status": "done", "exit_code": exit_code, "output": output})
    except Exception as e:
        return JSONResponse({"status": "error", "error": str(e), "output": f.getvalue()}, status_code=500)


@router.post("/import-csv")
async def import_rates_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Bulk-upsert rates from a CSV file into ZRateService.

    Required columns: service_name, default_rate, source, company_name
    Optional column:  late_cancellation_rate

    Upserts on (source, company_name, service_name) — existing rows get their
    default_rate (and late_cancellation_rate if provided) updated.
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Upload must be a .csv file")

    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    required = {"service_name", "default_rate", "source", "company_name"}
    if reader.fieldnames is None or not required.issubset({f.strip().lower() for f in reader.fieldnames}):
        raise HTTPException(
            status_code=400,
            detail=f"CSV must have columns: {', '.join(sorted(required))}",
        )

    inserted = updated = skipped = 0
    errors: list[str] = []

    for i, row in enumerate(reader, start=2):
        norm = {k.strip().lower(): (v or "").strip() for k, v in row.items()}
        svc_name = norm.get("service_name", "")
        src = norm.get("source", "")
        co = norm.get("company_name", "")
        rate_raw = norm.get("default_rate", "")
        lc_raw = norm.get("late_cancellation_rate", "")

        if not svc_name or not rate_raw:
            errors.append(f"Row {i}: missing service_name or default_rate — skipped")
            skipped += 1
            continue

        try:
            rate_dec = Decimal(rate_raw)
        except (InvalidOperation, ValueError):
            errors.append(f"Row {i}: invalid default_rate '{rate_raw}' — skipped")
            skipped += 1
            continue

        lc_dec: Decimal | None = None
        if lc_raw:
            try:
                lc_dec = Decimal(lc_raw)
            except (InvalidOperation, ValueError):
                errors.append(f"Row {i}: invalid late_cancellation_rate '{lc_raw}' — ignored")

        existing = (
            db.query(ZRateService)
            .filter(
                ZRateService.source == src,
                ZRateService.company_name == co,
                ZRateService.service_name == svc_name,
            )
            .one_or_none()
        )

        if existing:
            existing.default_rate = rate_dec
            if lc_dec is not None:
                existing.late_cancellation_rate = lc_dec
            db.add(existing)
            updated += 1
        else:
            service_key = re.sub(r"[^a-z0-9_]", "_", svc_name.lower())
            key_conflict = db.query(ZRateService).filter(ZRateService.service_key == service_key).one_or_none()
            if key_conflict:
                suffix = re.sub(r"[^a-z0-9_]", "_", src.lower()) if src else str(i)
                service_key = f"{service_key}_{suffix}"
            db.add(ZRateService(
                source=src,
                company_name=co,
                service_name=svc_name,
                service_key=service_key,
                default_rate=rate_dec,
                late_cancellation_rate=lc_dec,
                active=True,
            ))
            inserted += 1

    db.commit()
    return JSONResponse({
        "status": "ok",
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    })


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


@router.post("/fix-gross-pay/{payroll_batch_id}")
def fix_gross_pay_for_batch(
    payroll_batch_id: int,
    db: Session = Depends(get_db),
):
    """
    One-shot cleanup: set gross_pay = z_rate for all rides in a batch.
    Idempotent—running twice is a no-op (same result).

    This fixes the ingest bug where FA gross_pay was incorrectly copied from
    the Excel partner_pay column instead of being set to z_rate (driver pay).

    INVARIANT: gross_pay must always equal z_rate per payroll_laws.md
    """
    try:
        # Update all rides in the batch where gross_pay != z_rate
        count = db.query(Ride).filter(
            Ride.payroll_batch_id == payroll_batch_id,
            Ride.gross_pay != Ride.z_rate,
        ).update(
            {Ride.gross_pay: Ride.z_rate},
            synchronize_session=False,
        )
        db.commit()

        return JSONResponse({
            "ok": True,
            "payroll_batch_id": payroll_batch_id,
            "rides_fixed": count,
            "message": f"Set gross_pay = z_rate for {count} ride(s).",
        })
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error fixing gross_pay: {str(e)}",
        )


@router.post("/set-partner-gross/{payroll_batch_id}")
def set_partner_gross_total(
    payroll_batch_id: int,
    partner_gross: float = None,
    db: Session = Depends(get_db),
):
    """
    Manually set partner_gross_total on a payroll batch so that
    payroll history shows correct profit instead of $0.

    Required when the ED PDF's per-ride Gross column reflects driver-gross
    (not partner billing), which makes GREATEST(gross_pay, net_pay) equal
    driver_cost, collapsing profit to $0.

    Usage:
        POST /admin/rates/set-partner-gross/{batch_id}?partner_gross=1854.00

    Setting partner_gross=0 clears the override (reverts to sum(gross_pay)).

    The value should come from the cashiering receipt total on the ED PDF
    (the "Gross" total in the Summary section, which is the partner billing figure).
    """
    try:
        batch = db.query(PayrollBatch).filter(
            PayrollBatch.payroll_batch_id == payroll_batch_id
        ).first()
        if not batch:
            raise HTTPException(status_code=404, detail=f"Batch {payroll_batch_id} not found")

        if partner_gross is None:
            raise HTTPException(
                status_code=400,
                detail="partner_gross query param is required (e.g. ?partner_gross=1854.00)",
            )

        old_value = float(batch.partner_gross_total) if batch.partner_gross_total is not None else None

        # 0 means clear the override
        if partner_gross == 0:
            batch.partner_gross_total = None
            db.commit()
            return JSONResponse({
                "ok": True,
                "payroll_batch_id": payroll_batch_id,
                "partner_gross_total": None,
                "old_value": old_value,
                "message": "partner_gross_total cleared — will fall back to sum(gross_pay).",
            })

        from decimal import Decimal as _Dec
        batch.partner_gross_total = _Dec(str(partner_gross))
        db.commit()

        # Quick sanity: compute driver_cost so caller sees the resulting margin
        from sqlalchemy import func as _f
        agg = db.query(
            _f.sum(Ride.z_rate).label("driver_cost"),
            _f.count(Ride.ride_id).label("rides"),
        ).filter(Ride.payroll_batch_id == payroll_batch_id).first()

        driver_cost = float(agg.driver_cost or 0)
        ride_count = int(agg.rides or 0)
        profit = round(partner_gross - driver_cost, 2)
        margin_pct = round(profit / partner_gross * 100, 1) if partner_gross else 0

        return JSONResponse({
            "ok": True,
            "payroll_batch_id": payroll_batch_id,
            "partner_gross_total": float(batch.partner_gross_total),
            "old_value": old_value,
            "driver_cost": round(driver_cost, 2),
            "profit": profit,
            "margin_pct": margin_pct,
            "rides": ride_count,
            "message": (
                f"partner_gross_total set to ${partner_gross:.2f}. "
                f"Computed margin: ${profit:.2f} ({margin_pct}%) across {ride_count} rides."
            ),
        })
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error setting partner_gross_total: {str(e)}",
        )