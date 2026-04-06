"""Admin settings — email scheduling, send history, Paychex sync."""

import csv
import os
from pathlib import Path
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from backend.utils.roles import require_role
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, desc
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import PayrollBatch, Ride, Person, EmailSendLog

router = APIRouter(prefix="/admin", tags=["admin-settings"], dependencies=[Depends(require_role("admin"))])

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


# ── Paychex Worker ID Sync ─────────────────────────────────────────────────

def _normalize_name(name: str) -> str:
    """Normalize a name for fuzzy matching."""
    name = name.strip().lower()
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        name = f"{parts[1]} {parts[0]}"
    return name.replace(".", "").replace("  ", " ")


def _load_paychex_csv() -> dict:
    """Load Paychex workers from the CSV bundled in the repo."""
    csv_path = Path(__file__).resolve().parents[2] / "data" / "paychex_workers.csv"
    if not csv_path.exists():
        return {}
    workers = {}
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            workers[row["paychex_id"].strip()] = row["name"].strip()
    return workers


@router.get("/paychex-sync")
async def paychex_sync_page(request: Request, db: Session = Depends(get_db)):
    """Show current Paychex ID mapping status and allow sync."""
    paychex = _load_paychex_csv()
    paychex_norm = {_normalize_name(name): (pid, name) for pid, name in paychex.items()}

    persons = db.query(Person).filter(Person.active == True).all()

    matched = []
    unmatched = []
    already_set = []

    for person in persons:
        zpay_name = person.full_name or ""
        zpay_norm = _normalize_name(zpay_name)

        if person.paycheck_code:
            px_name = paychex.get(person.paycheck_code, "")
            already_set.append({
                "person_id": person.person_id,
                "zpay_name": zpay_name,
                "paychex_id": person.paycheck_code,
                "paychex_name": px_name,
            })
            continue

        # Try exact normalized match
        if zpay_norm in paychex_norm:
            pid, px_name = paychex_norm[zpay_norm]
            matched.append({
                "person_id": person.person_id,
                "zpay_name": zpay_name,
                "paychex_id": pid,
                "paychex_name": px_name,
            })
            continue

        # Try partial match (first + last)
        zpay_parts = zpay_norm.split()
        found = False
        for norm_name, (pid, px_name) in paychex_norm.items():
            px_parts = norm_name.split()
            if len(zpay_parts) >= 2 and len(px_parts) >= 2:
                if zpay_parts[0] == px_parts[0] and zpay_parts[-1] == px_parts[-1]:
                    matched.append({
                        "person_id": person.person_id,
                        "zpay_name": zpay_name,
                        "paychex_id": pid,
                        "paychex_name": px_name,
                    })
                    found = True
                    break

        if not found:
            unmatched.append({
                "person_id": person.person_id,
                "zpay_name": zpay_name,
            })

    applied = request.query_params.get("applied", "")

    return _templates.TemplateResponse(request, "admin/paychex_sync.html", {
        "matched": sorted(matched, key=lambda x: x["zpay_name"]),
        "unmatched": sorted(unmatched, key=lambda x: x["zpay_name"]),
        "already_set": sorted(already_set, key=lambda x: x["zpay_name"]),
        "paychex_count": len(paychex),
        "applied": applied,
    })


@router.post("/paychex-sync/apply")
async def paychex_sync_apply(request: Request, db: Session = Depends(get_db)):
    """Apply all matched Paychex codes to the database."""
    paychex = _load_paychex_csv()
    paychex_norm = {_normalize_name(name): (pid, name) for pid, name in paychex.items()}

    persons = db.query(Person).filter(Person.active == True, Person.paycheck_code.is_(None)).all()
    updated = 0

    for person in persons:
        zpay_norm = _normalize_name(person.full_name or "")

        pid = None
        if zpay_norm in paychex_norm:
            pid = paychex_norm[zpay_norm][0]
        else:
            zpay_parts = zpay_norm.split()
            for norm_name, (px_id, _) in paychex_norm.items():
                px_parts = norm_name.split()
                if len(zpay_parts) >= 2 and len(px_parts) >= 2:
                    if zpay_parts[0] == px_parts[0] and zpay_parts[-1] == px_parts[-1]:
                        pid = px_id
                        break

        if pid:
            person.paycheck_code = pid
            updated += 1

    db.commit()
    return RedirectResponse(url=f"/admin/paychex-sync?applied={updated}", status_code=302)
