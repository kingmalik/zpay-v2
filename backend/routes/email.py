"""
Email routes:
  POST /email/send-one   — send pay stub to a single driver
  POST /email/send-all   — send pay stubs to all drivers in a batch/week
  POST /email/set-email  — update a driver's email address
"""

from pathlib import Path
from datetime import date, datetime
from decimal import Decimal
import re

from fastapi import APIRouter, Depends, Form, Query
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

from backend.db import get_db
from backend.db.models import Person, Ride, PayrollBatch
from backend.services.email_service import send_paystub

router = APIRouter(prefix="/email", tags=["email"])

OUT_DIR = Path("/data/out")

COMPANY_COLORS = {
    "Acumen International": (0.55, 0.15, 0.15),
    "everDriven": (0.18, 0.24, 0.60),
}


def _safe_slug(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "unknown"


def _fmt_date(d) -> str:
    if d is None:
        return ""
    if isinstance(d, (datetime, date)):
        return d.strftime("%m/%d/%Y")
    return str(d)[:10]


def _generate_pdf(person: Person, rides: list, company: str, payweek: str) -> Path:
    """Generate a pay stub PDF and return its path."""
    full_name = (person.full_name or "unknown").strip()
    driver_slug = _safe_slug(full_name)
    payweek_slug = _safe_slug(payweek)

    out_dir = OUT_DIR / payweek_slug
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / f"{driver_slug}.pdf"

    c = canvas.Canvas(str(pdf_path), pagesize=letter)
    width, height = letter

    header_color = COMPANY_COLORS.get(company, (0.15, 0.15, 0.15))
    HEADER_HEIGHT = 48
    c.setFillColorRGB(*header_color)
    c.rect(0, height - HEADER_HEIGHT, width, HEADER_HEIGHT, stroke=0, fill=1)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 18)
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

    return pdf_path


def _build_payweek(batch: PayrollBatch) -> str:
    if batch and batch.week_start and batch.week_end:
        return f"{batch.week_start.strftime('%m/%d/%Y')} - {batch.week_end.strftime('%m/%d/%Y')}"
    if batch and batch.period_start and batch.period_end:
        return f"{batch.period_start.strftime('%m/%d/%Y')} - {batch.period_end.strftime('%m/%d/%Y')}"
    return "payweek"


# ── Update driver email ────────────────────────────────────────────────────────

@router.post("/set-email")
def set_driver_email(
    person_id: int = Form(...),
    email: str = Form(...),
    redirect_url: str = Form("/people"),
    db: Session = Depends(get_db),
):
    from backend.utils.redirect import safe_redirect
    clean_email = email.strip()
    if clean_email:
        from email_validator import validate_email, EmailNotValidError
        try:
            valid = validate_email(clean_email, check_deliverability=False)
            clean_email = valid.normalized
        except EmailNotValidError:
            return RedirectResponse(url=safe_redirect(redirect_url) + "&email_error=invalid_email", status_code=303)

    person = db.get(Person, person_id)
    if person:
        person.email = clean_email or None
        db.commit()
    return RedirectResponse(url=safe_redirect(redirect_url), status_code=303)


# ── Send single pay stub ───────────────────────────────────────────────────────

@router.post("/send-one")
def send_one(
    person_id: int = Form(...),
    batch_id: int = Form(...),
    company: str = Form(...),
    week_start: str = Form(""),
    week_end: str = Form(""),
    redirect_url: str = Form("/people"),
    db: Session = Depends(get_db),
):
    from backend.utils.redirect import safe_redirect
    redirect_url = safe_redirect(redirect_url)
    person = db.get(Person, person_id)
    if not person:
        return JSONResponse({"error": "Driver not found"}, status_code=404)
    if not person.email:
        return RedirectResponse(
            url=redirect_url + "&email_error=no_email", status_code=303
        )

    batch = db.get(PayrollBatch, batch_id)
    payweek = _build_payweek(batch)

    # Fetch rides for this driver/batch/week
    q = db.query(Ride).filter(
        Ride.payroll_batch_id == batch_id,
        Ride.person_id == person_id,
    )
    if week_start and week_end:
        try:
            ws = datetime.fromisoformat(week_start)
            we = datetime.fromisoformat(week_end)
            q = q.filter(
                Ride.ride_start_ts >= ws,
                Ride.ride_start_ts <= we.replace(hour=23, minute=59, second=59),
            )
        except ValueError:
            pass
    rides = q.order_by(Ride.ride_start_ts.asc()).all()

    pdf_path = _generate_pdf(person, rides, company, payweek)
    total_pay = sum(float(r.z_rate or 0) for r in rides)
    try:
        send_paystub(
            to_email=person.email,
            driver_name=person.full_name,
            company=company,
            payweek=payweek,
            pdf_path=pdf_path,
            person_id=person_id,
            payroll_batch_id=batch_id,
            week_start=week_start,
            week_end=week_end,
            total_pay=f"{total_pay:.2f}",
            ride_count=len(rides),
            db=db,
        )
    except Exception as exc:
        return RedirectResponse(url=redirect_url + f"&email_error={str(exc)[:80]}", status_code=303)

    return RedirectResponse(url=redirect_url + "&emailed=1", status_code=303)


# ── Send all pay stubs for a batch/week ───────────────────────────────────────

@router.post("/send-all")
def send_all(
    batch_id: int = Form(...),
    company: str = Form(...),
    week_start: str = Form(""),
    week_end: str = Form(""),
    redirect_url: str = Form("/people"),
    db: Session = Depends(get_db),
):
    from backend.utils.redirect import safe_redirect
    redirect_url = safe_redirect(redirect_url)
    batch = db.get(PayrollBatch, batch_id)
    payweek = _build_payweek(batch)

    # Get all drivers in this batch/week
    q = db.query(Person).join(Ride, Ride.person_id == Person.person_id).filter(
        Ride.payroll_batch_id == batch_id
    )

    ws_dt = we_dt = None
    if week_start and week_end:
        try:
            ws_dt = datetime.fromisoformat(week_start)
            we_dt = datetime.fromisoformat(week_end).replace(hour=23, minute=59, second=59)
            q = q.filter(
                Ride.ride_start_ts >= ws_dt,
                Ride.ride_start_ts <= we_dt,
            )
        except ValueError:
            pass

    people = q.distinct().all()

    sent = 0
    skipped = 0
    for person in people:
        if not person.email:
            skipped += 1
            continue

        ride_q = db.query(Ride).filter(
            Ride.payroll_batch_id == batch_id,
            Ride.person_id == person.person_id,
        )
        if ws_dt and we_dt:
            ride_q = ride_q.filter(
                Ride.ride_start_ts >= ws_dt,
                Ride.ride_start_ts <= we_dt,
            )
        rides = ride_q.order_by(Ride.ride_start_ts.asc()).all()

        pdf_path = _generate_pdf(person, rides, company, payweek)
        total_pay = sum(float(r.z_rate or 0) for r in rides)
        try:
            send_paystub(
                to_email=person.email,
                driver_name=person.full_name,
                company=company,
                payweek=payweek,
                pdf_path=pdf_path,
                person_id=person.person_id,
                payroll_batch_id=batch_id,
                week_start=week_start,
                week_end=week_end,
                total_pay=f"{total_pay:.2f}",
                ride_count=len(rides),
                db=db,
            )
            sent += 1
        except Exception as exc:
            import logging
            logging.getLogger("zpay.email").warning(
                "Failed to send pay stub to %s <%s>: %s",
                person.full_name, person.email, exc,
            )
            skipped += 1

    # Build a human-readable summary for the flash message
    summary = f"emailed={sent}&skipped={skipped}"
    return RedirectResponse(
        url=f"{redirect_url}&{summary}",
        status_code=303,
    )
