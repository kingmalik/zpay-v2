"""
Payroll batch workflow service — gate checks and stage transitions.
"""
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.db.models import (
    PayrollBatch, Ride, Person, BatchWorkflowLog, EmailSendLog, DriverBalance,
)

STAGE_ORDER = [
    "uploaded",
    "rates_review",
    "payroll_review",
    "approved",
    "stubs_sending",
    "export_ready",
    "complete",
]


def next_stage(current: str) -> str | None:
    """Return the next stage in the pipeline, or None if already complete."""
    try:
        idx = STAGE_ORDER.index(current)
        if idx + 1 < len(STAGE_ORDER):
            return STAGE_ORDER[idx + 1]
    except ValueError:
        pass
    return None


def check_gate(db: Session, batch: PayrollBatch, target: str) -> tuple[bool, list[str]]:
    """
    Check if the batch can advance to `target`. Returns (can_advance, blocking_reasons).
    """
    current = batch.status
    blockers: list[str] = []

    # Validate target is the next stage
    expected_next = next_stage(current)
    if expected_next != target:
        return False, [f"Cannot advance from '{current}' to '{target}'. Next stage is '{expected_next}'."]

    bid = batch.payroll_batch_id

    if target == "payroll_review":
        # Gate: no rides with z_rate == 0
        zero_count = (
            db.query(func.count(Ride.ride_id))
            .filter(Ride.payroll_batch_id == bid, Ride.z_rate == 0)
            .scalar()
        )
        if zero_count and zero_count > 0:
            # Get unique service names for context
            services = (
                db.query(Ride.service_name)
                .filter(Ride.payroll_batch_id == bid, Ride.z_rate == 0)
                .distinct()
                .limit(10)
                .all()
            )
            names = ", ".join(s[0] for s in services if s[0])
            blockers.append(f"{zero_count} rides with z_rate=0: {names}")

    elif target == "approved":
        # Block if any non-withheld driver is missing a paycheck_code — they'd be
        # silently skipped from the Paychex CSV with no error surfaced.
        from sqlalchemy import text as _text
        from backend.routes.summary import _build_summary
        override_rows = db.execute(
            _text("SELECT person_id FROM payroll_withheld_override WHERE batch_id = :b"),
            {"b": bid},
        ).fetchall()
        override_ids = {r[0] for r in override_rows} or None
        manual_rows = db.execute(
            _text("SELECT person_id FROM payroll_manual_withhold"),
        ).fetchall()
        manual_withhold_ids = {r[0] for r in manual_rows} or None
        summary = _build_summary(db, batch_id=bid, auto_save=False,
                                  override_ids=override_ids,
                                  manual_withhold_ids=manual_withhold_ids)
        paying_ids = [r["person_id"] for r in summary["rows"] if not r["withheld"]]
        if paying_ids:
            missing = (
                db.query(Person)
                .filter(
                    Person.person_id.in_(paying_ids),
                    (Person.paycheck_code.is_(None)) | (Person.paycheck_code == ""),
                )
                .all()
            )
            if missing:
                names = ", ".join(p.full_name for p in missing[:5])
                suffix = "..." if len(missing) > 5 else ""
                blockers.append(
                    f"{len(missing)} driver(s) missing Paychex code — "
                    f"they won't appear in the CSV: {names}{suffix}. "
                    f"Add codes or withhold them before approving."
                )

    elif target == "stubs_sending":
        # Auto-advance from approved — no gate
        pass

    elif target == "export_ready":
        # Gate: all eligible drivers must have stubs sent before Paychex export
        # Gate: all eligible drivers have email sent, no email on file,
        # or were withheld (carried-over balance > 0 for this batch — no paystub needed)
        drivers_in_batch = (
            db.query(Ride.person_id)
            .filter(Ride.payroll_batch_id == bid)
            .distinct()
            .subquery()
        )
        withheld_ids_subq = (
            db.query(DriverBalance.person_id).filter(
                DriverBalance.payroll_batch_id == bid,
                DriverBalance.carried_over > 0,
            )
        )
        # Drivers with email, not withheld, who haven't been sent a paystub for this batch
        unsent = (
            db.query(func.count(Person.person_id))
            .filter(
                Person.person_id.in_(db.query(drivers_in_batch.c.person_id)),
                Person.email.isnot(None),
                Person.email != "",
                ~Person.person_id.in_(withheld_ids_subq),
            )
            .filter(
                ~Person.person_id.in_(
                    db.query(EmailSendLog.person_id).filter(
                        EmailSendLog.payroll_batch_id == bid,
                        EmailSendLog.status == "sent",
                    )
                )
            )
            .scalar()
        )
        if unsent and unsent > 0:
            blockers.append(f"{unsent} drivers with email still unsent")

    elif target == "complete":
        # Gate: Paychex CSV must have been downloaded/exported before closing out
        source = (batch.source or "").lower()
        if source != "maz" and not batch.paychex_exported_at:
            blockers.append("Paychex CSV has not been exported yet")

    can_advance = len(blockers) == 0
    return can_advance, blockers


def advance_batch(
    db: Session,
    batch: PayrollBatch,
    triggered_by: str = "user",
    force: bool = False,
    notes: str | None = None,
) -> tuple[bool, str, list[str]]:
    """
    Attempt to advance the batch to the next stage.
    Returns (success, new_status, blockers).
    """
    target = next_stage(batch.status)
    if not target:
        return False, batch.status, ["Batch is already complete"]

    can_advance, blockers = check_gate(db, batch, target)

    if not can_advance and not force:
        return False, batch.status, blockers

    old_status = batch.status
    batch.status = target

    # Side effects for specific transitions
    if target == "approved":
        # Run payroll with auto_save to commit withheld balances
        # Load any force-pay overrides so they're respected when saving
        from backend.routes.summary import _build_summary
        from sqlalchemy import text as _text
        override_rows = db.execute(
            _text("SELECT person_id FROM payroll_withheld_override WHERE batch_id = :b"),
            {"b": batch.payroll_batch_id},
        ).fetchall()
        override_ids = {r[0] for r in override_rows} or None
        from sqlalchemy import text as _text2
        manual_rows = db.execute(_text2("SELECT person_id FROM payroll_manual_withhold")).fetchall()
        manual_withhold_ids = {r[0] for r in manual_rows} or None
        _build_summary(db, batch_id=batch.payroll_batch_id, auto_save=True, override_ids=override_ids, manual_withhold_ids=manual_withhold_ids)
        batch.finalized_at = datetime.now(timezone.utc)

    # Log the transition
    log_notes = notes
    if force and blockers:
        log_notes = f"Force-advanced. Blockers: {'; '.join(blockers)}" + (f" | {notes}" if notes else "")

    db.add(BatchWorkflowLog(
        payroll_batch_id=batch.payroll_batch_id,
        from_status=old_status,
        to_status=target,
        triggered_by=triggered_by,
        notes=log_notes,
    ))
    db.commit()

    # Auto-advance from approved → stubs_sending (no gate needed)
    if target == "approved":
        return advance_batch(db, batch, triggered_by="system", notes="Auto-advanced after approval")

    return True, target, blockers


def reopen_batch(db: Session, batch: PayrollBatch, triggered_by: str = "user") -> tuple[bool, str]:
    """Reopen an approved batch back to payroll_review. Only works before stubs are sent."""
    if batch.status not in ("approved", "export_ready"):
        return False, f"Cannot reopen from '{batch.status}'"

    old_status = batch.status
    batch.status = "payroll_review"
    batch.finalized_at = None

    # Clear driver balances for this batch (undo the payroll run)
    db.query(DriverBalance).filter(
        DriverBalance.payroll_batch_id == batch.payroll_batch_id
    ).delete()

    db.add(BatchWorkflowLog(
        payroll_batch_id=batch.payroll_batch_id,
        from_status=old_status,
        to_status="payroll_review",
        triggered_by=triggered_by,
        notes="Batch reopened",
    ))
    db.commit()
    return True, "payroll_review"
