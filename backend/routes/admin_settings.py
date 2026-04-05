"""Admin settings — email scheduling and send history."""

import os
from pathlib import Path
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, desc
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import PayrollBatch, Ride, Person, EmailSendLog

router = APIRouter(prefix="/admin", tags=["admin-settings"])

_templates_dir = Path(__file__).resolve().parents[1] / "templates"
_templates = Jinja2Templates(directory=str(_templates_dir))

# Simple in-memory schedule config (persists per deploy, resets on restart)
_schedule_config = {
    "enabled": os.environ.get("ZPAY_EMAIL_SCHEDULE_ENABLED", "false").lower() == "true",
    "day": os.environ.get("ZPAY_EMAIL_SCHEDULE_DAY", "Monday"),
    "time": os.environ.get("ZPAY_EMAIL_SCHEDULE_TIME", "08:00"),
}


@router.get("/email-schedule", response_class=HTMLResponse)
async def email_schedule_page(request: Request, db: Session = Depends(get_db)):
    # Recent send history
    send_logs = (
        db.query(EmailSendLog, Person.full_name, PayrollBatch.batch_ref)
        .outerjoin(Person, Person.person_id == EmailSendLog.person_id)
        .outerjoin(PayrollBatch, PayrollBatch.payroll_batch_id == EmailSendLog.payroll_batch_id)
        .order_by(desc(EmailSendLog.sent_at))
        .limit(50)
        .all()
    )

    logs = []
    for log, name, batch_ref in send_logs:
        logs.append({
            "id": log.id,
            "driver_name": name or "Unknown",
            "batch_name": batch_ref or "—",
            "sent_at": log.sent_at.strftime("%Y-%m-%d %H:%M") if log.sent_at else "—",
            "status": log.status,
            "error": log.error_message,
        })

    # Batches available for sending
    batches = (
        db.query(
            PayrollBatch.payroll_batch_id,
            PayrollBatch.batch_ref,
            PayrollBatch.company_name,
            PayrollBatch.week_start,
            func.count(Ride.ride_id).label("ride_count"),
        )
        .outerjoin(Ride, Ride.payroll_batch_id == PayrollBatch.payroll_batch_id)
        .filter(PayrollBatch.finalized_at.isnot(None))
        .group_by(PayrollBatch.payroll_batch_id, PayrollBatch.batch_ref, PayrollBatch.company_name, PayrollBatch.week_start)
        .order_by(PayrollBatch.week_start.desc())
        .limit(20)
        .all()
    )

    batch_list = []
    for b in batches:
        batch_list.append({
            "id": b.payroll_batch_id,
            "name": b.batch_ref or f"Batch #{b.payroll_batch_id}",
            "company": b.company_name or "—",
            "week_start": b.week_start.strftime("%Y-%m-%d") if b.week_start else "—",
            "rides": b.ride_count,
        })

    # Stats
    total_sent = db.query(func.count(EmailSendLog.id)).filter(EmailSendLog.status == "sent").scalar() or 0
    total_failed = db.query(func.count(EmailSendLog.id)).filter(EmailSendLog.status == "failed").scalar() or 0

    return _templates.TemplateResponse(request, "admin/email_schedule.html", {
        "config": _schedule_config,
        "logs": logs,
        "batches": batch_list,
        "total_sent": total_sent,
        "total_failed": total_failed,
    })


@router.post("/email-schedule/update")
async def update_schedule(
    request: Request,
    enabled: str = Form("off"),
    day: str = Form("Monday"),
    time: str = Form("08:00"),
):
    _schedule_config["enabled"] = enabled == "on"
    _schedule_config["day"] = day
    _schedule_config["time"] = time
    return RedirectResponse(url="/admin/email-schedule", status_code=302)


@router.post("/email-schedule/send-now/{batch_id}")
async def send_now(
    request: Request,
    batch_id: int,
    db: Session = Depends(get_db),
):
    """Manually trigger paystub emails for a specific batch.

    This queues sends for all drivers in the batch who have email addresses.
    Uses the existing email/send route logic — sends are logged for tracking.
    """
    batch = db.query(PayrollBatch).filter(PayrollBatch.payroll_batch_id == batch_id).first()
    if not batch:
        return RedirectResponse(url="/admin/email-schedule", status_code=302)

    # Get all drivers in this batch who have emails
    driver_rides = (
        db.query(
            Person.person_id,
            Person.full_name,
            Person.email,
        )
        .join(Ride, Ride.person_id == Person.person_id)
        .filter(Ride.payroll_batch_id == batch_id)
        .filter(Person.email.isnot(None))
        .filter(Person.email != "")
        .distinct()
        .all()
    )

    sent_count = 0
    for person_id, name, email in driver_rides:
        log = EmailSendLog(
            payroll_batch_id=batch_id,
            person_id=person_id,
            status="pending",
        )
        db.add(log)
        db.flush()

        try:
            # Reuse the core email pipeline from the email route
            from backend.routes.email import _generate_pdf, _build_payweek
            from backend.services.email_service import send_paystub

            payweek = _build_payweek(batch)
            rides = (
                db.query(Ride)
                .filter(Ride.payroll_batch_id == batch_id, Ride.person_id == person_id)
                .order_by(Ride.ride_start_ts.asc())
                .all()
            )
            if not rides:
                log.status = "skipped"
                log.error_message = "No rides found"
                db.commit()
                continue

            pdf_path = _generate_pdf(
                db.query(Person).get(person_id), rides, batch.company_name, payweek
            )
            total_pay = sum(float(r.z_rate or 0) for r in rides)
            ws = str(batch.week_start) if batch.week_start else ""
            we = str(batch.week_end) if batch.week_end else ""

            send_paystub(
                to_email=email,
                driver_name=name,
                company=batch.company_name,
                payweek=payweek,
                pdf_path=pdf_path,
                person_id=person_id,
                payroll_batch_id=batch_id,
                week_start=ws,
                week_end=we,
                total_pay=f"{total_pay:.2f}",
                ride_count=len(rides),
                db=db,
            )
            log.status = "sent"
            log.sent_at = datetime.now(timezone.utc)
            sent_count += 1
        except Exception as e:
            log.status = "failed"
            log.error_message = str(e)[:500]

        db.commit()

    return RedirectResponse(url="/admin/email-schedule", status_code=302)
