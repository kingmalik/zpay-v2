"""Recurring ("Permanent") pay-stub adjustments.

Bug (operator report, 2026-09-23): on a driver's paystub page, the operator
adds a manual payment/adjustment and marks it one-time or Permanent.
Permanent ones did not reappear on the next week's batch.

Root cause: "Permanent" was never persisted as a concept anywhere in the
schema. POST /api/data/rides (routes/api_data.py) always wrote a single
`ride` row scoped to the batch it was created on — there was no flag, no
template, nothing for batch generation to read even if it tried to.

Fix: `RecurringAdjustment` (backend/db/models.py) is the template row for a
permanent adjustment, created alongside the concrete `ride` row the moment
the operator picks "Permanent" (routes/api_data.py `api_create_ride`). This
module re-materializes every active template into a fresh `ride` row on
every subsequent batch for that driver + source, until the operator removes
it (active=False — never hard-deleted, so the audit trail survives).
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from decimal import Decimal

import pytz
from sqlalchemy.orm import Session

from backend.db.models import BatchCorrectionLog, PayrollBatch, RecurringAdjustment, Ride

logger = logging.getLogger(__name__)

_LA = pytz.timezone("America/Los_Angeles")


def apply_recurring_adjustments_to_batch(
    db: Session, batch: PayrollBatch, *, corrected_by: str = "system"
) -> int:
    """Materialize every active RecurringAdjustment matching `batch.source`
    into a concrete `ride` row on `batch`.

    Idempotent: a template already applied to this batch (a `ride` row with
    matching recurring_adjustment_id + payroll_batch_id) is skipped, so this
    is safe to call more than once for the same batch (e.g. a re-run).

    Does not commit — caller commits in the same transaction as the rest of
    the batch import, so a failure here rolls back with everything else.

    Returns the number of rides created.
    """
    templates = (
        db.query(RecurringAdjustment)
        .filter(
            RecurringAdjustment.source == batch.source,
            RecurringAdjustment.active.is_(True),
        )
        .all()
    )
    if not templates:
        return 0

    already_applied_ids = {
        row[0]
        for row in db.query(Ride.recurring_adjustment_id)
        .filter(
            Ride.payroll_batch_id == batch.payroll_batch_id,
            Ride.recurring_adjustment_id.isnot(None),
        )
        .all()
    }

    anchor_date = batch.period_start or batch.week_start or batch.period_end or batch.week_end
    ride_ts = (
        _LA.localize(datetime(anchor_date.year, anchor_date.month, anchor_date.day, 8, 0, 0))
        if anchor_date
        else datetime.now(_LA)
    )

    applied = 0
    for tpl in templates:
        if tpl.id in already_applied_ids:
            continue

        ride = Ride(
            payroll_batch_id=batch.payroll_batch_id,
            person_id=tpl.person_id,
            ride_start_ts=ride_ts,
            service_name=tpl.service_name,
            service_ref=tpl.notes or tpl.service_name,
            service_ref_type="manual",
            source="manual",
            source_ref=f"recurring-{tpl.id}-{uuid.uuid4().hex[:12]}",
            z_rate=tpl.driver_pay,
            z_rate_source="manual_recurring",
            recurring_adjustment_id=tpl.id,
            net_pay=Decimal("0"),
            gross_pay=tpl.driver_pay,
            miles=tpl.miles,
            deduction=Decimal("0"),
            spiff=Decimal("0"),
        )
        db.add(ride)
        db.flush()

        db.add(BatchCorrectionLog(
            batch_id=batch.payroll_batch_id,
            person_id=tpl.person_id,
            field="manual_ride_recurring_applied",
            old_value=None,
            new_value=json.dumps({
                "ride_id": ride.ride_id,
                "recurring_adjustment_id": tpl.id,
                "service_name": tpl.service_name,
                "z_rate": float(tpl.driver_pay),
            }),
            reason=tpl.reason,
            corrected_by=corrected_by,
        ))
        applied += 1

    if applied:
        logger.info(
            "[recurring-adjustments] applied %d permanent adjustment(s) to batch %s (source=%s)",
            applied, batch.payroll_batch_id, batch.source,
        )
    return applied
