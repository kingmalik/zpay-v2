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

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import PayrollBatch, Person, PaystubArchive, EmailSendLog
from backend.services.paystub_archive import (
    get_paystub_file,
    regenerate_paystub_from_data,
    save_pdf_to_archive,
)
from backend.utils.week_label import canonical_week_num

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


def _build_payweek_from_batch(batch: Optional[PayrollBatch]) -> str:
    if batch is None:
        return "payweek"
    if batch.week_start and batch.week_end:
        return f"{batch.week_start.strftime('%m/%d/%Y')} - {batch.week_end.strftime('%m/%d/%Y')}"
    if batch.period_start and batch.period_end:
        return f"{batch.period_start.strftime('%m/%d/%Y')} - {batch.period_end.strftime('%m/%d/%Y')}"
    return "payweek"
