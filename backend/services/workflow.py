"""
Payroll batch workflow service — gate checks and stage transitions.
"""
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.db.models import (
    PayrollBatch, Ride, Person, BatchWorkflowLog, EmailSendLog, DriverBalance, ZRateService,
)

STAGE_ORDER = [
    "uploaded",
    "rates_review",
    "payroll_review",
    "approved",
    "export_ready",
    "stubs_sending",
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


def check_gate(db: Session, batch: PayrollBatch, target: str) -> tuple[bool, list[str], list[str]]:
    """
    Check if the batch can advance to `target`. Returns (can_advance, blockers, warnings).
    """
    current = batch.status
    blockers: list[str] = []
    warnings: list[str] = []

    # Validate target is the next stage
    expected_next = next_stage(current)
    if expected_next != target:
        return False, [f"Cannot advance from '{current}' to '{target}'. Next stage is '{expected_next}'."]

    bid = batch.payroll_batch_id

    if target == "payroll_review":
        # Gate: no rides with z_rate == 0, EXCEPT canceled_trip rides.
        # FA/Acumen pays Maz full partner rate on canceled trips, but the driver
        # gets $0. Those rides correctly have z_rate=0 with z_rate_source='canceled_trip'.
        zero_count = (
            db.query(func.count(Ride.ride_id))
            .filter(
                Ride.payroll_batch_id == bid,
                Ride.z_rate == 0,
                Ride.z_rate_source != "canceled_trip",
            )
            .scalar()
        )
        if zero_count and zero_count > 0:
            services = (
                db.query(Ride.service_name)
                .filter(
                    Ride.payroll_batch_id == bid,
                    Ride.z_rate == 0,
                    Ride.z_rate_source != "canceled_trip",
                )
                .distinct()
                .limit(10)
                .all()
            )
            names = ", ".join(s[0] for s in services if s[0])
            blockers.append(f"{zero_count} rides with z_rate=0: {names}")

        # Warning: ED batch with zero deductions — pay_summary/gross data may be missing
        if (batch.source or "").lower() == "maz":
            ride_count, total_deductions = (
                db.query(
                    func.count(Ride.ride_id),
                    func.coalesce(func.sum(Ride.gross_pay - Ride.net_pay), 0),
                )
                .filter(Ride.payroll_batch_id == bid)
                .one()
            )
            if ride_count and ride_count > 0 and float(total_deductions) == 0:
                warnings.append(
                    f"All {ride_count} EverDriven rides show gross_pay = net_pay (zero WUD/RAD deductions). "
                    f"If this batch has deductions, the PDF may not have been parsed correctly — "
                    f"profit calculations will be overstated."
                )

        # Warning: suspected late cancellations (EverDriven net_pay 40–55% of default_rate)
        if (batch.source or "").lower() == "maz":
            lc_rows = (
                db.query(Ride.service_name, func.count(Ride.ride_id).label("cnt"))
                .join(ZRateService, ZRateService.z_rate_service_id == Ride.z_rate_service_id)
                .filter(
                    Ride.payroll_batch_id == bid,
                    Ride.z_rate_service_id.isnot(None),
                    ZRateService.default_rate > 0,
                    (Ride.net_pay / ZRateService.default_rate) >= 0.40,
                    (Ride.net_pay / ZRateService.default_rate) <= 0.55,
                )
                .group_by(Ride.service_name)
                .all()
            )
            if lc_rows:
                total_lc = sum(r.cnt for r in lc_rows)
                svc_names = ", ".join(r.service_name for r in lc_rows[:5] if r.service_name)
                warnings.append(
                    f"{total_lc} ride(s) may be late cancellations "
                    f"(net_pay 40–55% of route rate): {svc_names}. "
                    f"Verify in EverDriven before advancing."
                )

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

    elif target == "export_ready":
        # Auto-advance from approved — no gate
        # User will trigger Paychex CSV export action in this stage
        pass

    elif target == "stubs_sending":
        # Gate: Paychex CSV must have been exported before sending stubs
        # EXCEPT for Maz/EverDriven batches — mom submits those directly to Paychex
        # without using the Z-Pay CSV export, so this gate would always block.
        source = (batch.source or "").lower()
        if source != "maz" and not batch.paychex_exported_at:
            blockers.append("Paychex CSV has not been exported yet")

    elif target == "complete":
        # Gate: All stubs must have been sent before marking complete
        # This is verified implicitly by reaching stubs_sending stage.
        # Paychex export is already required by stubs_sending gate.
        pass

    can_advance = len(blockers) == 0
    return can_advance, blockers, warnings


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

    can_advance, blockers, _ = check_gate(db, batch, target)

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

    # Auto-advance from approved → export_ready (no gate needed)
    if target == "approved":
        return advance_batch(db, batch, triggered_by="system", notes="Auto-advanced after approval")

    return True, target, blockers


def reopen_batch(db: Session, batch: PayrollBatch, triggered_by: str = "user") -> tuple[bool, str]:
    """Reopen an approved batch back to payroll_review. Only works before stubs are sent."""
    if batch.status not in ("approved", "export_ready", "stubs_sending"):
        return False, f"Cannot reopen from '{batch.status}'"

    old_status = batch.status
    batch.status = "payroll_review"
    batch.finalized_at = None
    # If we're reopening, the Paychex export is implicitly undone too —
    # clear the timestamp so the UI shows a clean state on the next cycle.
    batch.paychex_exported_at = None

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
