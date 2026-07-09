"""Partner-payment reconciliation core (S1.5).

FA TPA (June 2026) §6b: Acumen must verify every payment, and payment
disputes must be raised IN WRITING within 14 days of the payment or the
claim is waived. This module diffs what a partner actually deposited
(PartnerPayment rows) against what each batch says they owed us
(sum of ride.net_pay), and computes the dispute clock per batch.

Enforcement starts at RECON_ENFORCE_SINCE (default 2026-07-01, the TPA
era) — the ~51 historical batches with no recorded deposits are reported
as 'untracked' instead of screaming 'unpaid' forever.

Used by:
  - backend/routes/api_data.py      (reconciliation page JSON)
  - backend/routes/partner_payments.py (deposit CRUD)
  - backend/services/health_monitor.py (partner_reconciliation check)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db.models import PartnerPayment

DISPUTE_WINDOW_DAYS = 14   # FA TPA §6b — written dispute deadline after payment
AT_RISK_DAYS = 5           # red-alert threshold before the dispute window closes
UNPAID_YELLOW_DAYS = 21    # no deposit recorded this long after week_end → yellow
MATCH_TOLERANCE = 0.01     # penny tolerance on deposited-vs-expected


def enforce_since() -> date:
    raw = os.getenv("RECON_ENFORCE_SINCE", "2026-07-01")
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return date(2026, 7, 1)


@dataclass(frozen=True)
class BatchPaymentStatus:
    payment_status: str                # untracked | unpaid | match | underpaid | overpaid
    deposited: float
    delta: float                       # deposited - expected
    first_deposit_date: Optional[date]
    dispute_deadline: Optional[date]   # first deposit + 14d (underpaid/overpaid only)
    dispute_days_left: Optional[int]   # negative = window already closed
    disputed: bool


def payment_summary_by_batch(db: Session) -> dict[int, dict]:
    """Aggregate PartnerPayment rows per linked batch."""
    rows = (
        db.query(
            PartnerPayment.payroll_batch_id,
            func.coalesce(func.sum(PartnerPayment.amount), 0).label("deposited"),
            func.min(PartnerPayment.deposit_date).label("first_deposit_date"),
            func.count(PartnerPayment.partner_payment_id).label("payment_count"),
            func.max(PartnerPayment.disputed_at).label("last_disputed_at"),
        )
        .filter(PartnerPayment.payroll_batch_id.isnot(None))
        .group_by(PartnerPayment.payroll_batch_id)
        .all()
    )
    return {
        int(r.payroll_batch_id): {
            "deposited": float(r.deposited or 0),
            "first_deposit_date": r.first_deposit_date,
            "payment_count": int(r.payment_count or 0),
            "disputed": r.last_disputed_at is not None,
        }
        for r in rows
    }


def classify_batch_payment(
    expected: float,
    summary: Optional[dict],
    week_end: Optional[date],
    today: Optional[date] = None,
) -> BatchPaymentStatus:
    """Compute payment status + dispute clock for one batch."""
    today = today or date.today()
    cutoff = enforce_since()

    deposited = float(summary["deposited"]) if summary else 0.0
    first_deposit = summary["first_deposit_date"] if summary else None
    disputed = bool(summary["disputed"]) if summary else False
    delta = round(deposited - expected, 2)

    # Pre-TPA batches with no recorded deposits are historical, not violations.
    if summary is None and (week_end is None or week_end < cutoff):
        return BatchPaymentStatus(
            payment_status="untracked",
            deposited=0.0,
            delta=round(-expected, 2),
            first_deposit_date=None,
            dispute_deadline=None,
            dispute_days_left=None,
            disputed=False,
        )

    if summary is None:
        return BatchPaymentStatus(
            payment_status="unpaid",
            deposited=0.0,
            delta=round(-expected, 2),
            first_deposit_date=None,
            dispute_deadline=None,
            dispute_days_left=None,
            disputed=False,
        )

    if abs(delta) <= MATCH_TOLERANCE:
        status = "match"
        deadline = None
        days_left = None
    else:
        status = "underpaid" if delta < 0 else "overpaid"
        deadline = (
            first_deposit + timedelta(days=DISPUTE_WINDOW_DAYS)
            if first_deposit
            else None
        )
        days_left = (deadline - today).days if deadline else None

    return BatchPaymentStatus(
        payment_status=status,
        deposited=round(deposited, 2),
        delta=delta,
        first_deposit_date=first_deposit,
        dispute_deadline=deadline,
        dispute_days_left=days_left,
        disputed=disputed,
    )


def find_reconciliation_problems(db: Session, today: Optional[date] = None) -> dict:
    """Scan TPA-era batches for reconciliation problems (health check).

    Returns {"red": [...], "yellow": [...]} — each entry a short dict
    describing the batch and why it tripped.
    """
    from backend.db.models import PayrollBatch, Ride  # local import avoids cycles

    today = today or date.today()
    cutoff = enforce_since()

    rows = (
        db.query(
            PayrollBatch.payroll_batch_id,
            PayrollBatch.batch_ref,
            PayrollBatch.source,
            PayrollBatch.week_end,
            func.coalesce(func.sum(Ride.net_pay), 0).label("expected"),
        )
        .outerjoin(Ride, Ride.payroll_batch_id == PayrollBatch.payroll_batch_id)
        .filter(PayrollBatch.week_end >= cutoff)
        .group_by(
            PayrollBatch.payroll_batch_id,
            PayrollBatch.batch_ref,
            PayrollBatch.source,
            PayrollBatch.week_end,
        )
        .all()
    )
    summaries = payment_summary_by_batch(db)

    red: list[dict] = []
    yellow: list[dict] = []

    for row in rows:
        expected = float(row.expected or 0)
        if expected <= 0:
            continue
        status = classify_batch_payment(
            expected, summaries.get(row.payroll_batch_id), row.week_end, today
        )
        entry = {
            "batch_id": row.payroll_batch_id,
            "batch_ref": row.batch_ref or f"Batch #{row.payroll_batch_id}",
            "source": row.source,
            "expected": round(expected, 2),
            "deposited": status.deposited,
            "delta": status.delta,
            "payment_status": status.payment_status,
            "dispute_days_left": status.dispute_days_left,
        }

        if status.payment_status == "unpaid":
            days_out = (today - row.week_end).days if row.week_end else 0
            if days_out > UNPAID_YELLOW_DAYS:
                yellow.append({**entry, "reason": f"no deposit {days_out}d after week end"})
        elif status.payment_status == "underpaid" and not status.disputed:
            if status.dispute_days_left is not None and status.dispute_days_left <= AT_RISK_DAYS:
                red.append({
                    **entry,
                    "reason": (
                        f"underpaid ${-status.delta:,.2f}, dispute window "
                        f"{'CLOSED' if status.dispute_days_left < 0 else f'closes in {status.dispute_days_left}d'}"
                        " — FA TPA §6b waives the claim after 14 days"
                    ),
                })
            else:
                yellow.append({**entry, "reason": f"underpaid ${-status.delta:,.2f}, not yet disputed"})
        elif status.payment_status == "overpaid":
            yellow.append({**entry, "reason": f"overpaid ${status.delta:,.2f} — verify allocation"})

    return {"red": red, "yellow": yellow}
