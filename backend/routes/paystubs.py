"""
Paystub Archive API
===================
All endpoints under /api/paystubs

GET  /api/paystubs/person/{person_id}
    List all archived stubs for a driver, newest first.

GET  /api/paystubs/{paystub_id}/pdf
    Serve the PDF inline (or as attachment with ?download=1).

POST /api/paystubs/regenerate
    Body: {person_id, batch_id}
    Rebuild the PDF from current ride data and persist.

POST /api/paystubs/{paystub_id}/email
    Body: {to: "override@email.com"}  (optional — defaults to person's email)
    Re-send the archived PDF via Gmail.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from backend.db import get_db, SessionLocal
from backend.db.models import PayrollBatch, Person, PaystubArchive, EmailSendLog, Ride
from backend.services.paystub_archive import (
    get_paystub_file,
    regenerate_paystub_from_data,
    save_pdf_to_archive,
    _build_paystub_pdf,
    _build_payweek,
)
from backend.utils.roles import require_role
from backend.utils.week_label import canonical_week_num

_BACKFILL_ELIGIBLE_STATUSES = {"complete", "stubs_sending", "export_ready"}

_logger = logging.getLogger("zpay.paystubs")

router = APIRouter(prefix="/api/paystubs", tags=["paystubs"])

# Also expose a minimal /api/data/people/{person_id} for the stubs page header.
# (A full people-detail JSON endpoint can be added to api_data.py in a future PR.)
people_router = APIRouter(prefix="/api/data", tags=["paystubs-people"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _batch_label(batch: PayrollBatch) -> str:
    """Return a human-readable label like 'W16 — Apr 18–24 2026'."""
    if not batch:
        return "Unknown"
    wnum = canonical_week_num(batch.period_start, batch.batch_ref)
    if batch.period_start and batch.period_end:
        s = batch.period_start.strftime("%b %-d")
        e = batch.period_end.strftime("%-d %Y")
        date_range = f"{s}–{e}"
    elif batch.period_start:
        date_range = batch.period_start.strftime("%b %-d %Y")
    else:
        date_range = ""

    if wnum:
        return f"W{wnum} — {date_range}" if date_range else f"W{wnum}"
    return date_range or f"Batch {batch.payroll_batch_id}"


def _stub_to_dict(row: PaystubArchive, batch: Optional[PayrollBatch]) -> dict:
    return {
        "paystub_id":            row.paystub_id,
        "batch_id":              row.payroll_batch_id,
        "batch_label":           _batch_label(batch) if batch else f"Batch {row.payroll_batch_id}",
        "generated_at":          row.generated_at.isoformat() if row.generated_at else None,
        "sent_at":               row.sent_at.isoformat() if row.sent_at else None,
        "recipient_email":       row.recipient_email,
        "total_pay":             float(row.total_pay) if row.total_pay is not None else None,
        "ride_count":            row.ride_count,
        "status":                "sent" if row.sent_at else "preview",
        "regenerated_from_data": row.regenerated_from_data,
    }


# ── GET /api/paystubs/person/{person_id} ─────────────────────────────────────

@router.get("/person/{person_id}")
def list_stubs_for_driver(
    person_id: int,
    db: Session = Depends(get_db),
):
    """
    Return all archived stubs for a driver, newest batch first.

    Response: [{paystub_id, batch_id, batch_label, generated_at, sent_at,
                recipient_email, total_pay, ride_count, status}]
    """
    rows = (
        db.query(PaystubArchive)
        .filter(PaystubArchive.person_id == person_id)
        .order_by(PaystubArchive.generated_at.desc())
        .all()
    )

    # Bulk-load batches to avoid N+1
    batch_ids = {r.payroll_batch_id for r in rows}
    batches_by_id: dict[int, PayrollBatch] = {}
    if batch_ids:
        for b in db.query(PayrollBatch).filter(
            PayrollBatch.payroll_batch_id.in_(batch_ids)
        ).all():
            batches_by_id[b.payroll_batch_id] = b

    # Sort by batch period_start desc (most recent week first)
    def _sort_key(r: PaystubArchive):
        b = batches_by_id.get(r.payroll_batch_id)
        if b and b.period_start:
            return b.period_start
        return r.generated_at.date() if r.generated_at else None  # type: ignore[union-attr]

    rows_sorted = sorted(rows, key=lambda r: (_sort_key(r) or ""), reverse=True)

    return [_stub_to_dict(r, batches_by_id.get(r.payroll_batch_id)) for r in rows_sorted]


# ── GET /api/paystubs/{paystub_id}/pdf ───────────────────────────────────────

@router.get("/{paystub_id}/pdf")
def serve_pdf(
    paystub_id: int,
    download: int = Query(0, description="Set to 1 to force download instead of inline view"),
    db: Session = Depends(get_db),
):
    """
    Stream the stored PDF.

    - Inline by default (opens in browser PDF viewer).
    - ?download=1 forces Content-Disposition: attachment.
    """
    try:
        _abs_path, pdf_bytes, _email, _generated_at = get_paystub_file(db, paystub_id)
    except FileNotFoundError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)

    row = db.get(PaystubArchive, paystub_id)
    batch = db.get(PayrollBatch, row.payroll_batch_id) if row else None
    filename = (
        f"paystub_{row.person_id}_batch{row.payroll_batch_id}.pdf"
        if row
        else f"paystub_{paystub_id}.pdf"
    )

    disposition = "attachment" if download else "inline"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "Cache-Control": "private, no-store",
        },
    )


# ── POST /api/paystubs/regenerate ────────────────────────────────────────────

@router.post("/regenerate")
def regenerate_stub(
    body: dict,
    db: Session = Depends(get_db),
):
    """
    Rebuild the PDF from current ride data (useful after rate corrections).

    Body: {"person_id": int, "batch_id": int}
    Response: {"paystub_id": int, "regenerated_from_data": true}
    """
    person_id = body.get("person_id")
    batch_id  = body.get("batch_id")
    if not person_id or not batch_id:
        return JSONResponse(
            {"error": "person_id and batch_id are required"},
            status_code=422,
        )

    try:
        _pdf_bytes, paystub_id = regenerate_paystub_from_data(db, int(person_id), int(batch_id))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        _logger.exception("Regenerate failed person=%s batch=%s", person_id, batch_id)
        return JSONResponse({"error": f"PDF generation failed: {exc}"}, status_code=500)

    return {"paystub_id": paystub_id, "regenerated_from_data": True}


# ── POST /api/paystubs/{paystub_id}/email ────────────────────────────────────

@router.post("/{paystub_id}/email")
def resend_stub(
    paystub_id: int,
    body: dict,
    db: Session = Depends(get_db),
):
    """
    Re-email an archived stub.

    Body: {"to": "override@email.com"}  — 'to' is optional.
    If omitted, sends to the person's current email on file.

    Logs the send to email_send_log as a resend.
    Response: {"ok": true, "to": "email@used.com"}
    """
    row = db.get(PaystubArchive, paystub_id)
    if not row:
        return JSONResponse({"error": "Stub not found"}, status_code=404)

    try:
        abs_path, pdf_bytes, _stored_email, _generated_at = get_paystub_file(db, paystub_id)
    except FileNotFoundError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)

    # Resolve recipient — override > stored email > person's current email
    to_email: Optional[str] = body.get("to") or row.recipient_email
    if not to_email:
        person = db.get(Person, row.person_id)
        to_email = person.email if person else None
    if not to_email:
        return JSONResponse({"error": "No email address available for this driver"}, status_code=422)

    # Load batch for company / payweek context
    batch = db.get(PayrollBatch, row.payroll_batch_id)
    company  = batch.company_name if batch else "Z-Pay"
    payweek  = _build_payweek_from_batch(batch)
    person   = db.get(Person, row.person_id)
    driver_name = person.full_name if person else "Driver"

    try:
        from backend.services.email_service import send_paystub
        send_paystub(
            to_email=to_email,
            driver_name=driver_name,
            company=company,
            payweek=payweek,
            pdf_path=abs_path,
            person_id=row.person_id,
            payroll_batch_id=row.payroll_batch_id,
            week_start="",
            week_end="",
            total_pay=str(row.total_pay or ""),
            ride_count=row.ride_count or 0,
            db=db,
        )
    except Exception as exc:
        _logger.exception("Re-email failed for stub %s to %s", paystub_id, to_email)
        return JSONResponse({"error": f"Email send failed: {exc}"}, status_code=500)

    # Update sent_at + recipient on the archive row
    from datetime import datetime, timezone
    row.sent_at = datetime.now(timezone.utc)
    row.recipient_email = to_email
    db.commit()

    return {"ok": True, "to": to_email}


# ── GET /api/data/people/{person_id} (minimal — for stubs page header) ────────

@people_router.get("/people/{person_id}")
def get_person_mini(person_id: int, db: Session = Depends(get_db)):
    """Return minimal person data needed by the stubs page header."""
    person = db.get(Person, person_id)
    if not person:
        return JSONResponse({"error": "Person not found"}, status_code=404)
    return {
        "id":    person.person_id,
        "name":  person.full_name,
        "email": person.email,
        "phone": person.phone,
    }


# ── POST /api/paystubs/admin/backfill ────────────────────────────────────────

@router.post("/admin/backfill", dependencies=[Depends(require_role("admin"))])
def admin_backfill(
    request: Request,
    dry_run: int = Query(0, description="1 = dry run (no writes), 0 = real run"),
    batch_id: Optional[int] = Query(None, description="Limit to a single batch_id"),
):
    """
    Admin endpoint: regenerate paystub PDFs for all eligible (person_id, batch_id)
    pairs and persist them to the Railway persistent volume via the paystub_archive table.

    Query params:
      - dry_run=1   Print what would happen; write nothing.
      - batch_id=N  Limit to a single batch (useful for targeted re-runs).

    Idempotent: skips pairs that already have an archive row.
    Skips batches with no payable rides (z_rate > 0).

    Useful after data corrections or for future re-runs without shelling into Railway.
    Requires admin role.
    """
    import time

    t_start = time.monotonic()
    is_dry = bool(dry_run)

    with SessionLocal() as db:
        # 1. Eligible batches
        bq = db.query(PayrollBatch).filter(
            PayrollBatch.status.in_(_BACKFILL_ELIGIBLE_STATUSES)
        )
        if batch_id is not None:
            bq = bq.filter(PayrollBatch.payroll_batch_id == batch_id)
        batches = bq.order_by(PayrollBatch.period_start.asc()).all()

        # 2. Pre-load existing archive keys
        existing_keys: set[tuple[int, int]] = set()
        for row in db.query(PaystubArchive.person_id, PaystubArchive.payroll_batch_id).all():
            existing_keys.add((row.person_id, row.payroll_batch_id))

        # 3. Pre-load email send log for best-guess sent_at
        send_log: dict[tuple[int, int], object] = {}
        for row in db.query(EmailSendLog).filter(EmailSendLog.status == "sent").all():
            key = (row.person_id, row.payroll_batch_id)
            if key not in send_log or row.sent_at > send_log[key]:
                send_log[key] = row.sent_at

        total_written = 0
        total_skipped = 0
        total_errors  = 0
        batch_summary: list[dict] = []

        for batch in batches:
            bid = batch.payroll_batch_id

            person_ids = [
                row.person_id
                for row in db.query(Ride.person_id)
                .filter(Ride.payroll_batch_id == bid, Ride.z_rate > 0)
                .distinct()
                .all()
            ]

            if not person_ids:
                batch_summary.append({
                    "batch_id": bid,
                    "status": "skipped_empty",
                    "written": 0,
                    "skipped": 0,
                    "errors": 0,
                })
                continue

            company  = batch.company_name or "Z-Pay"
            payweek  = _build_payweek(batch)

            bw = bs = be = 0

            for pid in person_ids:
                key = (pid, bid)

                if key in existing_keys:
                    bs += 1
                    total_skipped += 1
                    continue

                person = db.get(Person, pid)
                if not person:
                    be += 1
                    total_errors += 1
                    continue

                rides = (
                    db.query(Ride)
                    .filter(
                        Ride.payroll_batch_id == bid,
                        Ride.person_id == pid,
                        Ride.z_rate > 0,
                    )
                    .order_by(Ride.ride_start_ts.asc())
                    .all()
                )

                total_pay_val = sum(float(r.z_rate or 0) for r in rides)

                if is_dry:
                    bw += 1
                    total_written += 1
                    continue

                try:
                    pdf_bytes = _build_paystub_pdf(person, rides, company, payweek)
                    best_sent_at = send_log.get(key)

                    archive_id = save_pdf_to_archive(
                        db,
                        person_id=pid,
                        batch_id=bid,
                        pdf_bytes=pdf_bytes,
                        recipient_email=person.email,
                        sent=bool(best_sent_at),
                        regenerated=True,
                        total_pay=total_pay_val,
                        ride_count=len(rides),
                    )

                    if best_sent_at:
                        pa_row = db.get(PaystubArchive, archive_id)
                        if pa_row and pa_row.sent_at is None:
                            pa_row.sent_at = best_sent_at
                            db.commit()

                    existing_keys.add(key)
                    bw += 1
                    total_written += 1

                except Exception as exc:
                    _logger.error("Backfill error person=%d batch=%d: %s", pid, bid, exc)
                    be += 1
                    total_errors += 1

            batch_summary.append({
                "batch_id":  bid,
                "source":    batch.source,
                "period":    f"{batch.period_start} → {batch.period_end}",
                "status":    "dry_run" if is_dry else "done",
                "written":   bw,
                "skipped":   bs,
                "errors":    be,
            })

    elapsed = round(time.monotonic() - t_start, 2)

    return {
        "dry_run":       is_dry,
        "batches_total": len(batches),
        "written":       total_written,
        "skipped":       total_skipped,
        "errors":        total_errors,
        "elapsed_s":     elapsed,
        "batches":       batch_summary,
    }


def _build_payweek_from_batch(batch: Optional[PayrollBatch]) -> str:
    if batch is None:
        return "payweek"
    if batch.week_start and batch.week_end:
        return f"{batch.week_start.strftime('%m/%d/%Y')} - {batch.week_end.strftime('%m/%d/%Y')}"
    if batch.period_start and batch.period_end:
        return f"{batch.period_start.strftime('%m/%d/%Y')} - {batch.period_end.strftime('%m/%d/%Y')}"
    return "payweek"
