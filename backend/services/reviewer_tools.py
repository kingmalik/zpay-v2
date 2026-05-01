"""
Reviewer mode tools — read-only payroll batch sanity checks.

ALL functions in this module are strictly read-only.  No db.commit(), no
db.add(), no db.delete().  Tests assert this at the call site.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from backend.db.models import DriverBalance, PayrollBatch, Person, Ride


# ─── Internal helpers ──────────────────────────────────────────────────────────

def _batch_source(db: Session, batch_id: int) -> str | None:
    """Return the source ('acumen' / 'maz') of a batch, or None if not found."""
    batch = db.query(PayrollBatch).filter(
        PayrollBatch.payroll_batch_id == batch_id
    ).first()
    return batch.source if batch else None


def _driver_totals_for_batch(
    db: Session, batch_id: int
) -> list[dict[str, Any]]:
    """
    Return one row per driver in the batch with their total z_rate pay
    and ride count.
    """
    rows = db.execute(
        text(
            """
            SELECT
                p.person_id,
                p.full_name,
                p.paycheck_code,
                p.paycheck_code_maz,
                COUNT(r.ride_id)          AS ride_count,
                COALESCE(SUM(r.z_rate), 0) AS total_pay
            FROM ride r
            JOIN person p ON r.person_id = p.person_id
            WHERE r.payroll_batch_id = :batch_id
              AND p.full_name != 'Unassigned'
            GROUP BY p.person_id, p.full_name, p.paycheck_code, p.paycheck_code_maz
            ORDER BY total_pay DESC
            """
        ),
        {"batch_id": batch_id},
    ).fetchall()
    return [dict(r._mapping) for r in rows]


def _prior_batch_id(db: Session, batch_id: int) -> int | None:
    """Return the payroll_batch_id of the batch immediately before batch_id
    with the same source, or None if this is the first."""
    current = db.query(PayrollBatch).filter(
        PayrollBatch.payroll_batch_id == batch_id
    ).first()
    if current is None:
        return None

    prior = (
        db.query(PayrollBatch)
        .filter(
            PayrollBatch.source == current.source,
            PayrollBatch.payroll_batch_id < batch_id,
        )
        .order_by(PayrollBatch.payroll_batch_id.desc())
        .first()
    )
    return prior.payroll_batch_id if prior else None


def _driver_avg_pay_last_n(
    db: Session, person_id: int, source: str, exclude_batch_id: int, n: int = 4
) -> Decimal | None:
    """
    Average weekly z_rate pay for a driver across their last *n* batches
    for the given source, excluding exclude_batch_id.  Returns None if
    fewer than 2 qualifying batches exist (not enough history to compare).
    """
    rows = db.execute(
        text(
            """
            SELECT COALESCE(SUM(r.z_rate), 0) AS weekly_pay
            FROM ride r
            JOIN payroll_batch pb ON r.payroll_batch_id = pb.payroll_batch_id
            WHERE r.person_id      = :person_id
              AND pb.source        = :source
              AND pb.payroll_batch_id != :exclude_batch_id
            GROUP BY pb.payroll_batch_id
            ORDER BY pb.payroll_batch_id DESC
            LIMIT :n
            """
        ),
        {"person_id": person_id, "source": source, "exclude_batch_id": exclude_batch_id, "n": n},
    ).fetchall()

    if len(rows) < 2:
        return None

    total = sum(Decimal(str(r.weekly_pay)) for r in rows)
    return total / len(rows)


# ─── Public tool functions ─────────────────────────────────────────────────────

def review_batch_totals(db: Session, batch_id: int) -> dict[str, Any]:
    """
    Return high-level batch summary: total pay, driver count, paid/withheld
    split, and a week-over-week comparison against the immediately prior batch
    of the same source.

    READ-ONLY — no commits.
    """
    batch = db.query(PayrollBatch).filter(
        PayrollBatch.payroll_batch_id == batch_id
    ).first()

    if batch is None:
        return {"error": f"Batch {batch_id} not found."}

    driver_rows = _driver_totals_for_batch(db, batch_id)

    if not driver_rows:
        return {
            "batch_id": batch_id,
            "source": batch.source,
            "period_start": str(batch.period_start) if batch.period_start else None,
            "period_end": str(batch.period_end) if batch.period_end else None,
            "driver_count": 0,
            "total_pay": "0.00",
            "paid_count": 0,
            "withheld_count": 0,
            "prior_batch_total": None,
            "wow_change_pct": None,
        }

    total_pay = sum(Decimal(str(r["total_pay"])) for r in driver_rows)

    # Paid = has a paycheck_code (FA) or paycheck_code_maz (Maz) and ride total >= 100
    is_maz = batch.source and "maz" in batch.source.lower()
    paid_count = 0
    withheld_count = 0
    for r in driver_rows:
        code = r["paycheck_code_maz"] if is_maz else r["paycheck_code"]
        pay = Decimal(str(r["total_pay"]))
        if code and pay >= Decimal("100"):
            paid_count += 1
        else:
            withheld_count += 1

    # Week-over-week
    prior_id = _prior_batch_id(db, batch_id)
    prior_total = None
    wow_pct = None
    if prior_id:
        prior_rows = _driver_totals_for_batch(db, prior_id)
        if prior_rows:
            prior_total = sum(Decimal(str(r["total_pay"])) for r in prior_rows)
            if prior_total and prior_total != 0:
                wow_pct = float(
                    ((total_pay - prior_total) / prior_total * 100).quantize(Decimal("0.1"))
                )

    return {
        "batch_id": batch_id,
        "source": batch.source,
        "period_start": str(batch.period_start) if batch.period_start else None,
        "period_end": str(batch.period_end) if batch.period_end else None,
        "driver_count": len(driver_rows),
        "total_pay": str(total_pay.quantize(Decimal("0.01"))),
        "paid_count": paid_count,
        "withheld_count": withheld_count,
        "prior_batch_id": prior_id,
        "prior_batch_total": str(prior_total.quantize(Decimal("0.01"))) if prior_total else None,
        "wow_change_pct": wow_pct,
    }


def find_anomalous_drivers(db: Session, batch_id: int) -> dict[str, Any]:
    """
    Return drivers whose this-week pay deviates more than 50% from their
    4-week average, or whose ride count is 0 when their average is > 0.

    READ-ONLY — no commits.
    """
    batch = db.query(PayrollBatch).filter(
        PayrollBatch.payroll_batch_id == batch_id
    ).first()
    if batch is None:
        return {"error": f"Batch {batch_id} not found."}

    driver_rows = _driver_totals_for_batch(db, batch_id)
    source = batch.source or ""

    anomalies: list[dict[str, Any]] = []
    for row in driver_rows:
        this_week = Decimal(str(row["total_pay"]))
        avg = _driver_avg_pay_last_n(db, row["person_id"], source, batch_id)
        if avg is None:
            continue  # not enough history

        if avg == 0:
            continue  # avoid divide-by-zero; driver is new or always $0

        deviation_pct = float(((this_week - avg) / avg * 100).quantize(Decimal("0.1")))
        if abs(deviation_pct) > 50:
            anomalies.append({
                "driver": row["full_name"],
                "person_id": row["person_id"],
                "this_week_pay": str(this_week.quantize(Decimal("0.01"))),
                "four_week_avg": str(avg.quantize(Decimal("0.01"))),
                "deviation_pct": deviation_pct,
                "ride_count": row["ride_count"],
                "flag": "HIGH" if abs(deviation_pct) > 75 else "MEDIUM",
            })

    return {
        "batch_id": batch_id,
        "anomaly_count": len(anomalies),
        "anomalies": sorted(anomalies, key=lambda x: abs(x["deviation_pct"]), reverse=True),
    }


def find_missing_paycheck_codes(db: Session, batch_id: int) -> dict[str, Any]:
    """
    Return drivers who appear in the batch but are missing the paycheck_code
    (FA batch) or paycheck_code_maz (Maz batch) and are NOT marked as withheld
    (i.e., they have earned pay > 0 and would silently be skipped by Paychex).

    READ-ONLY — no commits.
    """
    batch = db.query(PayrollBatch).filter(
        PayrollBatch.payroll_batch_id == batch_id
    ).first()
    if batch is None:
        return {"error": f"Batch {batch_id} not found."}

    is_maz = batch.source and "maz" in batch.source.lower()
    code_col = "paycheck_code_maz" if is_maz else "paycheck_code"

    rows = db.execute(
        text(
            f"""
            SELECT
                p.person_id,
                p.full_name,
                p.{code_col} AS paycheck_code,
                COALESCE(SUM(r.z_rate), 0) AS total_pay,
                COUNT(r.ride_id) AS ride_count
            FROM ride r
            JOIN person p ON r.person_id = p.person_id
            WHERE r.payroll_batch_id = :batch_id
              AND p.full_name        != 'Unassigned'
              AND p.{code_col}       IS NULL
            GROUP BY p.person_id, p.full_name, p.{code_col}
            HAVING COALESCE(SUM(r.z_rate), 0) > 0
            ORDER BY total_pay DESC
            """
        ),
        {"batch_id": batch_id},
    ).fetchall()

    missing = [
        {
            "driver": r.full_name,
            "person_id": r.person_id,
            "total_pay": str(Decimal(str(r.total_pay)).quantize(Decimal("0.01"))),
            "ride_count": r.ride_count,
            "issue": f"Missing {'Maz' if is_maz else 'FA'} Paychex ID — will be skipped by Paychex",
        }
        for r in rows
    ]

    return {
        "batch_id": batch_id,
        "code_field_checked": code_col,
        "missing_count": len(missing),
        "missing": missing,
    }


def find_zero_rides_with_pay(db: Session, batch_id: int) -> dict[str, Any]:
    """
    Return drivers who have 0 rides this week but non-zero pay in the batch.
    This almost always means a manual adjustment was applied.  Flag it so mom
    can confirm it was intentional before paystubs go out.

    READ-ONLY — no commits.
    """
    batch = db.query(PayrollBatch).filter(
        PayrollBatch.payroll_batch_id == batch_id
    ).first()
    if batch is None:
        return {"error": f"Batch {batch_id} not found."}

    # Rides with z_rate = 0 but gross_pay or spiff > 0 count as "no-ride pay"
    # More practically: ride_count = 0 overall but SUM(z_rate) > 0 means manual adj
    rows = db.execute(
        text(
            """
            SELECT
                p.person_id,
                p.full_name,
                COUNT(r.ride_id)           AS ride_count,
                COALESCE(SUM(r.z_rate), 0) AS total_pay
            FROM ride r
            JOIN person p ON r.person_id = p.person_id
            WHERE r.payroll_batch_id = :batch_id
              AND p.full_name        != 'Unassigned'
              AND r.z_rate           = 0
            GROUP BY p.person_id, p.full_name
            HAVING COALESCE(SUM(r.gross_pay + r.spiff), 0) > 0
               OR  (COUNT(r.ride_id) = 0 AND COALESCE(SUM(r.z_rate), 0) > 0)
            ORDER BY total_pay DESC
            """
        ),
        {"batch_id": batch_id},
    ).fetchall()

    # Separately catch drivers whose ONLY entries have z_rate=0 but total_pay > 0
    # via the DriverBalance (carry-forward) table — no rides, but balance entry
    balance_rows = db.execute(
        text(
            """
            SELECT
                p.person_id,
                p.full_name,
                db.carried_over AS carried_pay
            FROM driver_balance db
            JOIN person p ON db.person_id = p.person_id
            WHERE db.payroll_batch_id = :batch_id
              AND db.carried_over     > 0
              AND p.person_id NOT IN (
                  SELECT DISTINCT person_id
                  FROM ride
                  WHERE payroll_batch_id = :batch_id
              )
            ORDER BY carried_pay DESC
            """
        ),
        {"batch_id": batch_id},
    ).fetchall()

    flagged = [
        {
            "driver": r.full_name,
            "person_id": r.person_id,
            "ride_count": r.ride_count,
            "total_pay": str(Decimal(str(r.total_pay)).quantize(Decimal("0.01"))),
            "reason": "Driver has rides with $0 z_rate but gross/spiff pay — check for manual adjustment",
        }
        for r in rows
    ]

    balance_flagged = [
        {
            "driver": r.full_name,
            "person_id": r.person_id,
            "ride_count": 0,
            "total_pay": str(Decimal(str(r.carried_pay)).quantize(Decimal("0.01"))),
            "reason": "No rides this week — carry-forward balance only",
        }
        for r in balance_rows
    ]

    all_flagged = flagged + balance_flagged
    return {
        "batch_id": batch_id,
        "flagged_count": len(all_flagged),
        "flagged": all_flagged,
    }


# ─── Anthropic tool schema ─────────────────────────────────────────────────────

REVIEWER_TOOLS = [
    {
        "name": "review_batch_totals",
        "description": (
            "Get a high-level summary of the batch: total pay, driver count, "
            "how many drivers will be paid vs withheld, and a week-over-week "
            "comparison against the previous batch of the same source."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "batch_id": {"type": "integer", "description": "The payroll_batch_id to review"},
            },
            "required": ["batch_id"],
        },
    },
    {
        "name": "find_anomalous_drivers",
        "description": (
            "Find drivers whose pay this week deviates more than 50% from their "
            "4-week average.  Returns driver names, this-week pay, average, and "
            "deviation percentage.  Requires at least 2 prior batches of history."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "batch_id": {"type": "integer", "description": "The payroll_batch_id to check"},
            },
            "required": ["batch_id"],
        },
    },
    {
        "name": "find_missing_paycheck_codes",
        "description": (
            "Find drivers in the batch who are missing their Paychex ID "
            "(paycheck_code for FA batches, paycheck_code_maz for Maz batches) "
            "and have non-zero pay — meaning Paychex would silently skip them."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "batch_id": {"type": "integer", "description": "The payroll_batch_id to check"},
            },
            "required": ["batch_id"],
        },
    },
    {
        "name": "find_zero_rides_with_pay",
        "description": (
            "Find drivers with $0 in normal rides this week but non-zero pay — "
            "usually from a manual adjustment or carry-forward balance.  "
            "Surfaces these so mom can confirm they are intentional before sending."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "batch_id": {"type": "integer", "description": "The payroll_batch_id to check"},
            },
            "required": ["batch_id"],
        },
    },
]
