from __future__ import annotations
from decimal import Decimal
from pathlib import Path
import statistics

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import Ride, ZRateService, Person, PayrollBatch

router = APIRouter(prefix="/rates", tags=["rates"])

_templates = None
def templates():
    global _templates
    if _templates is None:
        templates_dir = Path(__file__).resolve().parents[1] / "templates"
        _templates = Jinja2Templates(directory=str(templates_dir))
    return _templates


@router.get("/unmatched", name="rates_unmatched")
def rates_unmatched(
    request: Request,
    payroll_batch_id: int | None = None,
    db: Session = Depends(get_db),
):
    """Show all rides with z_rate=0 grouped by service name."""
    q = (
        db.query(Ride, Person, PayrollBatch)
        .join(Person, Person.person_id == Ride.person_id)
        .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
        .filter(Ride.z_rate == 0)
    )
    if payroll_batch_id:
        q = q.filter(Ride.payroll_batch_id == payroll_batch_id)

    rows = q.order_by(Ride.ride_start_ts).all()

    # Group by service_name, collect per-ride details
    groups: dict[str, dict] = {}
    for ride, person, batch in rows:
        key = ride.service_name or "(unknown)"
        if key not in groups:
            groups[key] = {
                "service_name": key,
                "ride_ids": [],
                "ride_count": 0,
                "total_net_pay": Decimal("0"),
                "source": ride.source,
                "z_rate_service_id": ride.z_rate_service_id,
                "rides": [],
            }
        groups[key]["ride_ids"].append(ride.ride_id)
        groups[key]["ride_count"] += 1
        groups[key]["total_net_pay"] += ride.net_pay or Decimal("0")
        groups[key]["rides"].append({
            "ride_id": ride.ride_id,
            "driver_name": person.full_name,
            "net_pay": ride.net_pay or Decimal("0"),
            "miles": ride.miles or Decimal("0"),
            "date": ride.ride_start_ts,
            "source": ride.source,
            "company": batch.company_name,
        })

    unmatched = sorted(groups.values(), key=lambda g: -g["total_net_pay"])

    # --- Outlier detection: rides with z_rate > 0 that deviate >50% from per-service median ---
    # Fetch all rides with z_rate > 0, grouped by service_name
    rated_q = (
        db.query(Ride, Person, PayrollBatch)
        .join(Person, Person.person_id == Ride.person_id)
        .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
        .filter(Ride.z_rate > 0)
    )
    if payroll_batch_id:
        rated_q = rated_q.filter(Ride.payroll_batch_id == payroll_batch_id)

    rated_rows = rated_q.order_by(Ride.ride_start_ts).all()

    # Build per-service list of z_rate values for median calculation
    service_rates: dict[str, list[float]] = {}
    for ride, _person, _batch in rated_rows:
        key = ride.service_name or "(unknown)"
        service_rates.setdefault(key, []).append(float(ride.z_rate))

    # Compute median per service
    service_median: dict[str, float] = {
        svc: statistics.median(rates)
        for svc, rates in service_rates.items()
        if rates
    }

    # Collect outlier rides (deviation > 50% from median)
    outlier_rides: list[dict] = []
    for ride, person, batch in rated_rows:
        key = ride.service_name or "(unknown)"
        median = service_median.get(key)
        if median is None or median == 0:
            continue
        rate = float(ride.z_rate)
        deviation = abs(rate - median) / median
        if deviation > 0.50:
            outlier_rides.append({
                "ride_id": ride.ride_id,
                "service_name": key,
                "driver_name": person.full_name,
                "date": ride.ride_start_ts,
                "net_pay": ride.net_pay or Decimal("0"),
                "z_rate": Decimal(str(rate)),
                "median_rate": Decimal(str(median)),
                "deviation_pct": round(deviation * 100, 1),
                "source": ride.source,
                "company": batch.company_name,
                "z_rate_source": ride.z_rate_source,
            })

    # Sort outliers by deviation descending so the most extreme show first
    outlier_rides.sort(key=lambda r: -r["deviation_pct"])

    return templates().TemplateResponse(
        request,
        "rates_unmatched.html",
        {
            "unmatched": unmatched,
            "outlier_rides": outlier_rides,
            "payroll_batch_id": payroll_batch_id,
            "total_rides": len(rows),
        },
    )


@router.post("/set", name="rates_set")
def rates_set(
    request: Request,
    service_name: str = Form(...),
    rate: float = Form(...),
    scope: str = Form(...),          # "permanent" | "onetime"
    ride_ids: str = Form(...),       # comma-separated ride IDs
    payroll_batch_id: int | None = Form(None),
    redirect_url: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Set a rate for an unmatched service. Updates the rides immediately."""
    new_rate = Decimal(str(rate))
    ids = [int(x) for x in ride_ids.split(",") if x.strip().isdigit()]

    if scope == "permanent":
        # Update or create the z_rate_service row
        svc = (
            db.query(ZRateService)
            .filter(ZRateService.service_name == service_name)
            .first()
        )
        if svc:
            svc.default_rate = new_rate
            db.add(svc)
        else:
            # Determine source from any of the rides
            sample_ride = db.query(Ride).filter(Ride.ride_id.in_(ids)).first()
            src = (sample_ride.source or "acumen") if sample_ride else "acumen"
            # Try to get company name from batch
            company = ""
            if sample_ride and sample_ride.payroll_batch_id:
                from backend.db.models import PayrollBatch
                batch = db.query(PayrollBatch).get(sample_ride.payroll_batch_id)
                if batch:
                    company = batch.company_name or ""
            svc = ZRateService(
                source=src,
                company_name=company,
                service_key=service_name.lower().replace(" ", "-")[:80],
                service_name=service_name,
                default_rate=new_rate,
                active=True,
            )
            db.add(svc)
            db.flush()

        # Update rides with this service_name — scoped to same source to prevent
        # Acumen rates leaking into Maz rides and vice versa.
        source_filter = svc.source if svc and svc.source else None
        rides_q = db.query(Ride).filter(Ride.service_name == service_name)
        if source_filter:
            rides_q = rides_q.filter(Ride.source == source_filter)
        all_rides = rides_q.all()
        for r in all_rides:
            r.z_rate = new_rate
            r.z_rate_source = "service_default"
            if svc and svc.z_rate_service_id:
                r.z_rate_service_id = svc.z_rate_service_id
        db.add_all(all_rides)
    else:
        # One-time: just update these specific rides
        batch_rides = db.query(Ride).filter(Ride.ride_id.in_(ids)).all()
        for r in batch_rides:
            r.z_rate = new_rate
            r.z_rate_source = "onetime"
        db.add_all(batch_rides)

    db.commit()

    # Honour explicit redirect_url (e.g. back to driver's ride page)
    if redirect_url:
        from backend.utils.redirect import safe_redirect
        return RedirectResponse(url=safe_redirect(redirect_url), status_code=303)

    # Fall back: unmatched page filtered to same batch
    redirect = "/rates/unmatched"
    if payroll_batch_id:
        redirect += f"?payroll_batch_id={payroll_batch_id}"
    return RedirectResponse(url=redirect, status_code=303)
