"""
Paystub Archive Service
=======================
Handles persisting pay stub PDFs to disk + the paystub_archive DB table.

Public API
----------
save_pdf_to_archive(db, person_id, batch_id, pdf_bytes, recipient_email, sent)
    Write bytes to DATA_DIR/paystubs/{batch_id}/{person_id}.pdf,
    upsert the DB row. Returns paystub_id.

regenerate_paystub_from_data(db, person_id, batch_id)
    Rebuild the PDF from current ride data (same logic as the email send path)
    and persist it. Returns (pdf_bytes, paystub_id).

get_paystub_file(db, archive_id)
    Return (absolute_path, bytes, recipient_email, generated_at).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.config import DATA_DIR
from backend.db.models import PaystubArchive, Person, Ride, PayrollBatch

_logger = logging.getLogger("zpay.paystub_archive")

# Paystub storage root — always under DATA_DIR so Railway's persistent volume
# keeps files alive across deploys.
_STUBS_DIR = DATA_DIR / "paystubs"


def _stub_path(batch_id: int, person_id: int) -> Path:
    """Return the absolute path for a stub file (may not exist yet)."""
    d = _STUBS_DIR / str(batch_id)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{person_id}.pdf"


def _relative_path(batch_id: int, person_id: int) -> str:
    """Return the path relative to DATA_DIR stored in the DB row."""
    return f"paystubs/{batch_id}/{person_id}.pdf"


# ── Core persist ──────────────────────────────────────────────────────────────

def save_pdf_to_archive(
    db: Session,
    person_id: int,
    batch_id: int,
    pdf_bytes: bytes,
    recipient_email: Optional[str],
    *,
    sent: bool = False,
    regenerated: bool = False,
    total_pay: Optional[float] = None,
    ride_count: Optional[int] = None,
) -> int:
    """
    Persist *pdf_bytes* to disk and upsert the paystub_archive row.

    Idempotent: if a row already exists for (person_id, batch_id) the file is
    overwritten and the row updated in place.  We never accumulate duplicates.

    Returns the paystub_id.
    """
    abs_path = _stub_path(batch_id, person_id)
    abs_path.write_bytes(pdf_bytes)
    rel_path = _relative_path(batch_id, person_id)

    now = datetime.now(timezone.utc)
    sent_at = now if sent else None

    existing = (
        db.query(PaystubArchive)
        .filter_by(person_id=person_id, payroll_batch_id=batch_id)
        .first()
    )

    if existing:
        existing.file_path             = rel_path
        existing.file_size_bytes       = len(pdf_bytes)
        existing.recipient_email       = recipient_email
        existing.generated_at          = now
        existing.regenerated_from_data = regenerated
        if total_pay is not None:
            existing.total_pay = total_pay
        if ride_count is not None:
            existing.ride_count = ride_count
        # Only advance sent_at — never erase a prior send timestamp
        if sent and existing.sent_at is None:
            existing.sent_at = sent_at
        db.commit()
        return existing.paystub_id  # type: ignore[return-value]

    row = PaystubArchive(
        person_id=person_id,
        payroll_batch_id=batch_id,
        generated_at=now,
        sent_at=sent_at,
        recipient_email=recipient_email,
        file_path=rel_path,
        file_size_bytes=len(pdf_bytes),
        total_pay=total_pay,
        ride_count=ride_count,
        regenerated_from_data=regenerated,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.paystub_id  # type: ignore[return-value]


# ── PDF generation (shared with email.py) ────────────────────────────────────

def _build_paystub_pdf(
    person: Person,
    rides: list,
    company: str,
    payweek: str,
) -> bytes:
    """
    Generate a paystub PDF and return the raw bytes.

    This is a pure function extracted from backend/routes/email.py so both
    the email path and the archive service use identical output.
    """
    import io
    import re
    from decimal import Decimal

    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter

    def _company_banner_color(co: str) -> tuple:
        co = (co or "").lower()
        if "acumen" in co or "first" in co:
            return (0.290, 0.082, 0.145)   # maroon #4A1525
        if "maz" in co or "ever" in co:
            return (0.059, 0.114, 0.227)   # navy  #0F1D3A
        return (0.15, 0.15, 0.15)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    width, height = letter

    header_color = _company_banner_color(company)
    HEADER_HEIGHT = 48
    c.setFillColorRGB(*header_color)
    c.rect(0, height - HEADER_HEIGHT, width, HEADER_HEIGHT, stroke=0, fill=1)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 18)
    full_name = (person.full_name or "unknown").strip()
    c.drawString(40, height - HEADER_HEIGHT + 14, company)
    c.setFillColorRGB(0, 0, 0)

    y = height - HEADER_HEIGHT - 30
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, f"Rides Report: {full_name}")
    y -= 18
    c.setFont("Helvetica", 11)
    c.drawString(50, y, f"Payweek: {payweek}")
    y -= 25

    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "Date")
    c.drawString(130, y, "Service")
    c.drawRightString(380, y, "Miles")
    c.drawRightString(450, y, "Rate")
    c.drawRightString(520, y, "Deduct")
    c.drawRightString(580, y, "Net")
    y -= 14
    c.line(50, y, 580, y)
    y -= 14

    printed_total = Decimal("0")
    c.setFont("Helvetica", 10)

    for r in rides:
        if y < 80:
            c.showPage()
            y = height - 50
            c.setFont("Helvetica", 10)

        dt = r.ride_start_ts
        date_str = dt.strftime("%m/%d/%Y") if dt else ""
        service = (r.service_name or "")[:42]
        miles = float(r.miles or 0)
        rate = Decimal(str(r.z_rate or 0))
        deduction = Decimal(str(r.deduction or 0))
        net = rate - deduction
        printed_total += net

        c.drawString(50, y, date_str)
        c.drawString(130, y, service)
        c.drawRightString(380, y, f"{miles:.0f}")
        c.drawRightString(450, y, f"{rate:.2f}")
        c.drawRightString(520, y, f"{deduction:.2f}")
        c.drawRightString(580, y, f"{net:.2f}")
        y -= 14

    y -= 10
    c.line(50, y, 580, y)
    y -= 16
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(580, y, f"Total Net: {printed_total:.2f}")
    c.save()

    buf.seek(0)
    return buf.read()


def regenerate_paystub_from_data(
    db: Session,
    person_id: int,
    batch_id: int,
) -> tuple[bytes, int]:
    """
    Rebuild the PDF from current ride data and persist to archive.

    Returns (pdf_bytes, paystub_id).
    Raises ValueError if person or batch not found.
    """
    person = db.get(Person, person_id)
    if not person:
        raise ValueError(f"Person {person_id} not found")

    batch = db.get(PayrollBatch, batch_id)
    if not batch:
        raise ValueError(f"Batch {batch_id} not found")

    rides = (
        db.query(Ride)
        .filter(
            Ride.payroll_batch_id == batch_id,
            Ride.person_id == person_id,
            Ride.z_rate > 0,
            Ride.removed_at.is_(None),
        )
        .order_by(Ride.ride_start_ts.asc())
        .all()
    )

    company = batch.company_name or "Z-Pay"
    payweek = _build_payweek(batch)

    pdf_bytes = _build_paystub_pdf(person, rides, company, payweek)
    total_pay = sum(float(r.z_rate or 0) for r in rides)

    paystub_id = save_pdf_to_archive(
        db,
        person_id=person_id,
        batch_id=batch_id,
        pdf_bytes=pdf_bytes,
        recipient_email=person.email,
        sent=False,
        regenerated=True,
        total_pay=total_pay,
        ride_count=len(rides),
    )

    # Freeze z_rate for all rides in this (person, batch) once the stub is
    # persisted. Idempotent — only sets rows where lock is not yet set.
    _lock_z_rate(db, batch_id=batch_id, person_id=person_id)

    return pdf_bytes, paystub_id


def _build_payweek(batch: PayrollBatch) -> str:
    """Mirror the same helper in email.py."""
    if batch.week_start and batch.week_end:
        return f"{batch.week_start.strftime('%m/%d/%Y')} - {batch.week_end.strftime('%m/%d/%Y')}"
    if batch.period_start and batch.period_end:
        return f"{batch.period_start.strftime('%m/%d/%Y')} - {batch.period_end.strftime('%m/%d/%Y')}"
    return "payweek"


def _lock_z_rate(db: Session, *, batch_id: int, person_id: int) -> None:
    """
    Stamp z_rate_locked_at = NOW() on every ride for (person, batch) that
    does not already have a lock.  Idempotent — once the lock is set it
    never moves.
    """
    db.execute(
        text(
            "UPDATE ride"
            " SET z_rate_locked_at = NOW()"
            " WHERE payroll_batch_id = :b"
            "   AND person_id = :p"
            "   AND z_rate_locked_at IS NULL"
        ),
        {"b": batch_id, "p": person_id},
    )
    db.commit()


# ── File retrieval ────────────────────────────────────────────────────────────

def get_paystub_file(
    db: Session,
    archive_id: int,
) -> tuple[Path, bytes, Optional[str], datetime]:
    """
    Return (absolute_path, bytes, recipient_email, generated_at).

    Raises FileNotFoundError if the DB row or the file on disk is missing.
    """
    row = db.get(PaystubArchive, archive_id)
    if not row:
        raise FileNotFoundError(f"Paystub archive entry {archive_id} not found")

    abs_path = DATA_DIR / row.file_path
    if not abs_path.exists():
        raise FileNotFoundError(
            f"Stub file missing from disk: {abs_path}. "
            "Run the backfill script or regenerate via POST /api/paystubs/regenerate."
        )

    return abs_path, abs_path.read_bytes(), row.recipient_email, row.generated_at
