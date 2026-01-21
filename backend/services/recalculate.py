from __future__ import annotations

from datetime import datetime, date
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from backend.db import SessionLocal
from backend.db.models import Ride, PayrollBatch, ZRateService, ZRateOverride


def _as_date(dt: Optional[datetime | date]) -> Optional[date]:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.date()
    return dt

def _col(model, *names):
    """Return the first attribute on model that exists (or None)."""
    for n in names:
        if hasattr(model, n):
            return getattr(model, n)
    return None

def _resolve_rate_for_ride_local(
    db: Session,
    *,
    source: str,
    company_name: str,
    service_name: str,
    ride_date: Optional[datetime | date],
    currency: str = "USD",
):
    """
    Resolver that matches your current schema:

    z_rate_service:
      - source (NOT NULL, default '')
      - company_name (NOT NULL, default '')
      - service_name
      - default_rate (numeric)

    z_rate_override:
      - z_rate_service_id (FK)
      - effective_during (DATERANGE)
      - override_rate (numeric)
      - active (bool, default true)

    Rules:
      1) If ride_date is provided and an active override range contains the ride day -> use override_rate
      2) Else use svc.default_rate
      3) If no svc -> (None, "NONE", None, None)
    """

    # Normalize NULL-ish inputs to match your schema's NOT NULL defaults
    source = (source or "").strip()
    company_name = (company_name or "").strip()
    service_name = (service_name or "").strip()

    svc = (
        db.query(ZRateService)
        .filter(
            ZRateService.source == source,
            ZRateService.company_name == company_name,
            ZRateService.service_name == service_name,
        )
        .one_or_none()
    )

    if not svc:
        return None, "NONE", None, None

    d = _as_date(ride_date)

    if d is not None:
        # Override: effective_during @> d AND active = true
        # Order by most recent range start (lower(effective_during)) so newest override wins.
        ov = (
            db.query(ZRateOverride)
            .filter(
                ZRateOverride.z_rate_service_id == svc.z_rate_service_id,
                ZRateOverride.active.is_(True),
                ZRateOverride.effective_during.op("@>")(d),
            )
            .order_by(func.lower(ZRateOverride.effective_during).desc())
            .first()
        )

        if ov and ov.override_rate is not None:
            ov_id = getattr(ov, "z_rate_override_id", None) or getattr(ov, "id", None)
            # Return Decimal for money-ish values (safer than float); caller can cast if needed.
            return Decimal(str(ov.override_rate)), "OVERRIDE", svc.z_rate_service_id, ov_id

    # Default
    if svc.default_rate is None:
        return None, "SERVICE_DEFAULT_NONE", svc.z_rate_service_id, None

    return Decimal(str(svc.default_rate)), "SERVICE_DEFAULT", svc.z_rate_service_id, None

def recalc_rates_and_summary(*, source: str, company_name: str, payroll_batch_id: int | None = None):
    """
    Re-price rides for (source, company_name) optionally limited to a payroll_batch_id.
    """
    db: Session = SessionLocal()
    try:
        q = (
            db.query(Ride)
            .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
            .filter(PayrollBatch.source == source, PayrollBatch.company_name == company_name)
        )
        if payroll_batch_id is not None:
            q = q.filter(Ride.payroll_batch_id == payroll_batch_id)

        rides = q.all()

        for r in rides:
            ride_dt = getattr(r, "ride_start_ts", None) or getattr(r, "ride_date_ts", None)

            rate, rate_source, svc_id, ov_id = _resolve_rate_for_ride_local(
                db,
                source=source,
                company_name=company_name,
                service_name=r.service_name or "",
                ride_date=ride_dt,
                currency=getattr(r, "currency", "USD") or "USD",
            )

            r.z_rate = rate or 0
            r.z_rate_source = rate_source
            r.z_rate_service_id = svc_id
            r.z_rate_override_id = ov_id

        db.commit()
    finally:
        db.close()
