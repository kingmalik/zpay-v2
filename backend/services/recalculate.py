from __future__ import annotations

from datetime import datetime, date
from decimal import Decimal
from typing import Optional

from sqlalchemy import func
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
      - company_name (NOT NULL, default '') — NOT part of the lookup key, see below
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

    `company_name` is accepted for backwards compatibility (callers still
    pass it) but is intentionally NOT part of the ZRateService filter below.
    Batches and rate rows carry inconsistent company_name spellings for the
    same partner ("FirstAlt" / "Acumen International" / "Acumen", "EverDriven"
    / "everDriven") — `source` (acumen|maz) is the real company key. As of
    migration s14 there is exactly one ACTIVE z_rate_service row per (source,
    service_name) — duplicates are soft-merged (active=false), never deleted,
    so the filter below excludes them explicitly rather than relying on them
    being gone. The ride-count/lowest-id tie-break further below only matters
    for a DB that hasn't run that migration yet.
    """

    # Normalize NULL-ish inputs to match your schema's NOT NULL defaults
    source = (source or "").strip()
    company_name = (company_name or "").strip()
    service_name = (service_name or "").strip()

    candidates = (
        db.query(ZRateService)
        .filter(
            ZRateService.source == source,
            ZRateService.service_name == service_name,
            # Soft-merged duplicates (migration s14) are deactivated, not
            # deleted — never price off one of those.
            ZRateService.active.is_(True),
        )
        .all()
    )

    if not candidates:
        return None, "NONE", None, None

    if len(candidates) == 1:
        svc = candidates[0]
    else:
        # Pre-migration duplicate rows for this (source, service_name): prefer
        # whichever row the most rides already point at, then lowest id.
        candidate_ids = [c.z_rate_service_id for c in candidates]
        ride_counts = dict(
            db.query(Ride.z_rate_service_id, func.count(Ride.ride_id))
            .filter(Ride.z_rate_service_id.in_(candidate_ids))
            .group_by(Ride.z_rate_service_id)
            .all()
        )
        candidates.sort(key=lambda c: (-ride_counts.get(c.z_rate_service_id, 0), c.z_rate_service_id))
        svc = candidates[0]

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
            ride_dt = getattr(r, "ride_start_ts", None) or getattr(r, "ride_start_ts", None)

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
