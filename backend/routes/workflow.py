"""
Workflow API endpoints for the guided payroll workflow.
All routes under /api/data/workflow/* return JSON.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.db import get_db
from backend.db.models import (
    PayrollBatch, Ride, Person, EmailSendLog, ZRateService, BatchWorkflowLog,
)
from backend.services.workflow import (
    STAGE_ORDER, advance_batch, reopen_batch, check_gate, next_stage,
)
from backend.routes.summary import _build_summary

router = APIRouter(prefix="/api/data/workflow", tags=["workflow"])


# ── Rate management helpers ──────────────────────────────────────────────────

@router.post("/rates/create")
async def workflow_create_rate(request=None, db: Session = Depends(get_db)):
    """Create a new z_rate_service and apply it to matching rides."""
    import re
    from decimal import Decimal

    body = await request.json()
    service_name = body.get("service_name", "").strip()
    source = body.get("source", "")
    company_name = body.get("company_name", "")
    rate = body.get("default_rate")

    if not service_name or not rate:
        return JSONResponse({"error": "service_name and default_rate required"}, status_code=400)

    # Check if already exists
    existing = db.query(ZRateService).filter(ZRateService.service_name == service_name).first()
    if existing:
        existing.default_rate = Decimal(str(rate))
        svc = existing
    else:
        svc = ZRateService(
            service_key=re.sub(r"[^a-z0-9]+", "_", service_name.lower()).strip("_"),
            service_name=service_name,
            source=source,
            company_name=company_name,
            default_rate=Decimal(str(rate)),
        )
        db.add(svc)
        db.flush()

    # Update all rides matching this service_name with z_rate=0
    updated = (
        db.query(Ride)
        .filter(Ride.service_name == service_name, Ride.z_rate == 0)
        .update({
            "z_rate": float(rate),
            "z_rate_service_id": svc.z_rate_service_id,
        }, synchronize_session=False)
    )
    db.commit()

    return JSONResponse({"ok": True, "service_id": svc.z_rate_service_id, "rides_updated": updated})


@router.post("/rates/apply-batch/{batch_id}")
def workflow_apply_batch_rates(batch_id: int, db: Session = Depends(get_db)):
    """Re-apply z_rate_service rates to all z_rate=0 rides in a batch."""
    unpriced = (
        db.query(Ride)
        .filter(Ride.payroll_batch_id == batch_id, Ride.z_rate == 0)
        .all()
    )

    updated = 0
    for ride in unpriced:
        svc = (
            db.query(ZRateService)
            .filter(ZRateService.service_name == ride.service_name)
            .first()
        )
        if svc and float(svc.default_rate) > 0:
            ride.z_rate = float(svc.default_rate)
            ride.z_rate_service_id = svc.z_rate_service_id
            updated += 1

    db.commit()
    return JSONResponse({"ok": True, "rides_updated": updated})


def _display_company(raw: str) -> str:
    co = (raw or "").lower()
    if "ever" in co:
        return "EverDriven"
    return "FirstAlt"


def _batch_summary(db: Session, batch: PayrollBatch) -> dict:
    """Build a summary dict for a single batch."""
    bid = batch.payroll_batch_id

    ride_stats = db.query(
        func.count(Ride.ride_id).label("rides"),
        func.coalesce(func.sum(Ride.net_pay), 0).label("revenue"),
        func.coalesce(func.sum(Ride.z_rate), 0).label("cost"),
        func.count(Ride.ride_id).filter(Ride.z_rate == 0).label("unpriced"),
    ).filter(Ride.payroll_batch_id == bid).one()

    # Driver count
    driver_count = (
        db.query(func.count(func.distinct(Ride.person_id)))
        .filter(Ride.payroll_batch_id == bid)
        .scalar() or 0
    )

    # Email send stats
    sent_count = (
        db.query(func.count(EmailSendLog.id))
        .filter(EmailSendLog.payroll_batch_id == bid, EmailSendLog.status == "sent")
        .scalar() or 0
    )
    failed_count = (
        db.query(func.count(EmailSendLog.id))
        .filter(EmailSendLog.payroll_batch_id == bid, EmailSendLog.status == "failed")
        .scalar() or 0
    )

    return {
        "batch_id": bid,
        "source": batch.source,
        "company": _display_company(batch.company_name or ""),
        "company_raw": batch.company_name,
        "batch_ref": batch.batch_ref,
        "status": batch.status,
        "period_start": batch.period_start.isoformat() if batch.period_start else None,
        "period_end": batch.period_end.isoformat() if batch.period_end else None,
        "week_start": batch.week_start.isoformat() if batch.week_start else None,
        "week_end": batch.week_end.isoformat() if batch.week_end else None,
        "uploaded_at": batch.uploaded_at.isoformat() if batch.uploaded_at else None,
        "finalized_at": batch.finalized_at.isoformat() if batch.finalized_at else None,
        "paychex_exported_at": batch.paychex_exported_at.isoformat() if batch.paychex_exported_at else None,
        "rides": int(ride_stats.rides or 0),
        "revenue": round(float(ride_stats.revenue or 0), 2),
        "cost": round(float(ride_stats.cost or 0), 2),
        "margin": round(float((ride_stats.revenue or 0) - (ride_stats.cost or 0)), 2),
        "unpriced_rides": int(ride_stats.unpriced or 0),
        "driver_count": driver_count,
        "stubs_sent": sent_count,
        "stubs_failed": failed_count,
    }


# ── Active batches ───────────────────────────────────────────────────────────

@router.get("/active")
def workflow_active(db: Session = Depends(get_db)):
    """All batches not yet complete, ordered by most recent first."""
    batches = (
        db.query(PayrollBatch)
        .filter(PayrollBatch.status != "complete")
        .order_by(PayrollBatch.uploaded_at.desc())
        .all()
    )
    return JSONResponse({
        "batches": [_batch_summary(db, b) for b in batches],
    })


# ── Single batch status ─────────────────────────────────────────────────────

@router.get("/{batch_id}/status")
def workflow_status(batch_id: int, db: Session = Depends(get_db)):
    batch = db.query(PayrollBatch).filter(PayrollBatch.payroll_batch_id == batch_id).first()
    if not batch:
        return JSONResponse({"error": "Batch not found"}, status_code=404)

    summary = _batch_summary(db, batch)

    # Check what's blocking the next advance
    nxt = next_stage(batch.status)
    blockers = []
    if nxt:
        _, blockers = check_gate(db, batch, nxt)

    # Get workflow log
    logs = (
        db.query(BatchWorkflowLog)
        .filter(BatchWorkflowLog.payroll_batch_id == batch_id)
        .order_by(BatchWorkflowLog.created_at.asc())
        .all()
    )

    return JSONResponse({
        **summary,
        "next_stage": nxt,
        "blockers": blockers,
        "stage_index": STAGE_ORDER.index(batch.status) if batch.status in STAGE_ORDER else 0,
        "stages": STAGE_ORDER,
        "logs": [
            {
                "from": log.from_status,
                "to": log.to_status,
                "by": log.triggered_by,
                "notes": log.notes,
                "at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
    })


# ── Advance batch ───────────────────────────────────────────────────────────

@router.post("/{batch_id}/advance")
async def workflow_advance(batch_id: int, request=None, db: Session = Depends(get_db)):
    batch = db.query(PayrollBatch).filter(PayrollBatch.payroll_batch_id == batch_id).first()
    if not batch:
        return JSONResponse({"error": "Batch not found"}, status_code=404)

    force = False
    notes = None
    if request:
        try:
            body = await request.json()
            force = body.get("force", False)
            notes = body.get("notes")
        except Exception:
            pass

    success, new_status, blockers = advance_batch(db, batch, triggered_by="user", force=force, notes=notes)

    if not success:
        return JSONResponse({
            "ok": False,
            "status": batch.status,
            "blockers": blockers,
        }, status_code=400)

    return JSONResponse({
        "ok": True,
        "status": new_status,
        "blockers": blockers,
    })


# ── Reopen batch ─────────────────────────────────────────────────────────────

@router.post("/{batch_id}/reopen")
def workflow_reopen(batch_id: int, db: Session = Depends(get_db)):
    batch = db.query(PayrollBatch).filter(PayrollBatch.payroll_batch_id == batch_id).first()
    if not batch:
        return JSONResponse({"error": "Batch not found"}, status_code=404)

    success, status = reopen_batch(db, batch)
    if not success:
        return JSONResponse({"ok": False, "error": status}, status_code=400)

    return JSONResponse({"ok": True, "status": status})


# ── Rates check ──────────────────────────────────────────────────────────────

@router.get("/{batch_id}/rates-check")
def workflow_rates_check(batch_id: int, db: Session = Depends(get_db)):
    """Get rides with z_rate=0, grouped by service name, with suggested rates."""
    batch = db.query(PayrollBatch).filter(PayrollBatch.payroll_batch_id == batch_id).first()
    if not batch:
        return JSONResponse({"error": "Batch not found"}, status_code=404)

    # Get unpriced rides grouped by service_name
    unpriced = (
        db.query(
            Ride.service_name,
            func.count(Ride.ride_id).label("count"),
            func.sum(Ride.net_pay).label("total_net_pay"),
            func.array_agg(func.distinct(Person.full_name)).label("drivers"),
        )
        .join(Person, Person.person_id == Ride.person_id)
        .filter(Ride.payroll_batch_id == batch_id, Ride.z_rate == 0)
        .group_by(Ride.service_name)
        .order_by(func.count(Ride.ride_id).desc())
        .all()
    )

    groups = []
    for row in unpriced:
        service_name = row.service_name or "Unknown"

        # Look for existing rate in z_rate_service
        existing_rate = (
            db.query(ZRateService)
            .filter(ZRateService.service_name == service_name)
            .first()
        )

        suggested_rate = float(existing_rate.default_rate) if existing_rate else None

        groups.append({
            "service_name": service_name,
            "count": int(row.count),
            "total_net_pay": round(float(row.total_net_pay or 0), 2),
            "drivers": list(row.drivers) if row.drivers else [],
            "suggested_rate": suggested_rate,
            "service_id": existing_rate.z_rate_service_id if existing_rate else None,
        })

    total_unpriced = sum(g["count"] for g in groups)

    return JSONResponse({
        "batch_id": batch_id,
        "total_unpriced": total_unpriced,
        "groups": groups,
    })


# ── Payroll preview with validation warnings ─────────────────────────────────

@router.get("/{batch_id}/payroll-preview")
def workflow_payroll_preview(batch_id: int, db: Session = Depends(get_db)):
    batch = db.query(PayrollBatch).filter(PayrollBatch.payroll_batch_id == batch_id).first()
    if not batch:
        return JSONResponse({"error": "Batch not found"}, status_code=404)

    data = _build_summary(db, batch_id=batch_id, auto_save=False)
    rows = data["rows"]
    totals = data["totals"]

    # Build validation warnings
    warnings = []

    # Drivers missing paycheck_code
    person_ids = [r["person_id"] for r in rows if not r["withheld"]]
    if person_ids:
        missing_pay_code = (
            db.query(Person)
            .filter(
                Person.person_id.in_(person_ids),
                (Person.paycheck_code.is_(None)) | (Person.paycheck_code == ""),
            )
            .all()
        )
        if missing_pay_code:
            names = [p.full_name for p in missing_pay_code[:5]]
            warnings.append({
                "severity": "warning",
                "title": f"{len(missing_pay_code)} drivers missing Paychex code",
                "description": f"Won't be included in Paychex CSV: {', '.join(names)}" + ("..." if len(missing_pay_code) > 5 else ""),
                "type": "missing_pay_code",
                "count": len(missing_pay_code),
            })

    # Drivers missing email
    all_person_ids = [r["person_id"] for r in rows]
    if all_person_ids:
        missing_email = (
            db.query(Person)
            .filter(
                Person.person_id.in_(all_person_ids),
                (Person.email.is_(None)) | (Person.email == ""),
            )
            .all()
        )
        if missing_email:
            names = [p.full_name for p in missing_email[:5]]
            warnings.append({
                "severity": "info",
                "title": f"{len(missing_email)} drivers missing email",
                "description": f"Won't receive paystub: {', '.join(names)}" + ("..." if len(missing_email) > 5 else ""),
                "type": "missing_email",
                "count": len(missing_email),
            })

    # Negative margins (z_rate > net_pay) — possible data entry error
    for r in rows:
        if r["net_pay"] < 0:
            warnings.append({
                "severity": "error",
                "title": f"Negative net pay for {r['person']}",
                "description": f"Net pay: ${r['net_pay']:.2f}",
                "type": "negative_net",
            })

    # Rides with z_rate > net_pay per ride (aggregate check)
    negative_margin_rides = (
        db.query(func.count(Ride.ride_id))
        .filter(Ride.payroll_batch_id == batch_id, Ride.z_rate > Ride.net_pay, Ride.net_pay > 0)
        .scalar() or 0
    )
    if negative_margin_rides > 0:
        warnings.append({
            "severity": "warning",
            "title": f"{negative_margin_rides} rides with negative margin",
            "description": "Driver rate exceeds company rate — check rate assignments",
            "type": "negative_margin",
            "count": negative_margin_rides,
        })

    # Format rows for frontend
    drivers_out = []
    withheld_out = []
    for r in rows:
        entry = {
            "id": r["person_id"],
            "name": r["person"],
            "pay_code": r["code"],
            "days": r["days"],
            "net_pay": r["net_pay"],
            "carried_over": r["from_last_period"],
            "pay_this_period": r["pay_this_period"],
            "status": "withheld" if r["withheld"] else "paid",
            "withheld_amount": r["withheld_amount"],
        }
        if r["withheld"]:
            withheld_out.append(entry)
        else:
            drivers_out.append(entry)

    total_withheld = sum(r["withheld_amount"] for r in rows if r["withheld"])

    return JSONResponse({
        "batch_id": batch_id,
        "company": _display_company(batch.company_name or ""),
        "period_start": batch.period_start.isoformat() if batch.period_start else None,
        "period_end": batch.period_end.isoformat() if batch.period_end else None,
        "drivers": drivers_out,
        "withheld": withheld_out,
        "totals": totals,
        "warnings": warnings,
        "stats": {
            "driver_count": len(rows),
            "total_pay": totals["pay_this_period"],
            "withheld_amount": round(total_withheld, 2),
            "withheld_count": len(withheld_out),
        },
    })


# ── Stubs status ─────────────────────────────────────────────────────────────

@router.get("/{batch_id}/stubs-status")
def workflow_stubs_status(batch_id: int, db: Session = Depends(get_db)):
    batch = db.query(PayrollBatch).filter(PayrollBatch.payroll_batch_id == batch_id).first()
    if not batch:
        return JSONResponse({"error": "Batch not found"}, status_code=404)

    # All drivers in this batch
    drivers = (
        db.query(Person)
        .join(Ride, Ride.person_id == Person.person_id)
        .filter(Ride.payroll_batch_id == batch_id)
        .distinct()
        .all()
    )

    # Email send logs for this batch
    logs = (
        db.query(EmailSendLog)
        .filter(EmailSendLog.payroll_batch_id == batch_id)
        .all()
    )
    log_map = {log.person_id: log for log in logs}

    results = []
    counts = {"sent": 0, "failed": 0, "no_email": 0, "pending": 0}

    for person in drivers:
        log = log_map.get(person.person_id)
        if not person.email:
            status = "no_email"
            counts["no_email"] += 1
        elif log and log.status == "sent":
            status = "sent"
            counts["sent"] += 1
        elif log and log.status == "failed":
            status = "failed"
            counts["failed"] += 1
        else:
            status = "pending"
            counts["pending"] += 1

        results.append({
            "person_id": person.person_id,
            "name": person.full_name,
            "email": person.email,
            "status": status,
            "error": log.error_message if log and log.status == "failed" else None,
            "sent_at": log.sent_at.isoformat() if log and log.sent_at else None,
        })

    return JSONResponse({
        "batch_id": batch_id,
        "drivers": results,
        "counts": counts,
        "total": len(results),
    })


# ── Send stubs (bulk) ────────────────────────────────────────────────────────

@router.post("/{batch_id}/send-stubs")
def workflow_send_stubs(batch_id: int, db: Session = Depends(get_db)):
    """Send paystubs to all unsent drivers in the batch."""
    from backend.routes.email import _generate_pdf, _build_payweek
    from backend.services.email_service import send_paystub

    batch = db.query(PayrollBatch).filter(PayrollBatch.payroll_batch_id == batch_id).first()
    if not batch:
        return JSONResponse({"error": "Batch not found"}, status_code=404)

    payweek = _build_payweek(batch)
    company = batch.company_name or ""

    # Get drivers who haven't been sent yet
    already_sent = (
        db.query(EmailSendLog.person_id)
        .filter(EmailSendLog.payroll_batch_id == batch_id, EmailSendLog.status == "sent")
        .subquery()
    )

    drivers = (
        db.query(Person)
        .join(Ride, Ride.person_id == Person.person_id)
        .filter(
            Ride.payroll_batch_id == batch_id,
            Person.email.isnot(None),
            Person.email != "",
            ~Person.person_id.in_(db.query(already_sent.c.person_id)),
        )
        .distinct()
        .all()
    )

    sent = 0
    failed = 0
    for person in drivers:
        rides = (
            db.query(Ride)
            .filter(Ride.payroll_batch_id == batch_id, Ride.person_id == person.person_id)
            .order_by(Ride.ride_start_ts.asc())
            .all()
        )

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
                week_start=batch.week_start.isoformat() if batch.week_start else "",
                week_end=batch.week_end.isoformat() if batch.week_end else "",
                total_pay=f"{total_pay:.2f}",
                ride_count=len(rides),
                db=db,
            )
            sent += 1
        except Exception as exc:
            import logging
            logging.getLogger("zpay.workflow").warning(
                "Failed to send stub to %s <%s>: %s",
                person.full_name, person.email, exc,
            )
            # Log failure
            db.add(EmailSendLog(
                payroll_batch_id=batch_id,
                person_id=person.person_id,
                status="failed",
                error_message=str(exc)[:200],
            ))
            db.commit()
            failed += 1

    return JSONResponse({
        "ok": True,
        "sent": sent,
        "failed": failed,
        "total_drivers": len(drivers),
    })


# ── Retry single stub ────────────────────────────────────────────────────────

@router.post("/{batch_id}/retry-stub/{person_id}")
def workflow_retry_stub(batch_id: int, person_id: int, db: Session = Depends(get_db)):
    from backend.routes.email import _generate_pdf, _build_payweek
    from backend.services.email_service import send_paystub

    batch = db.query(PayrollBatch).filter(PayrollBatch.payroll_batch_id == batch_id).first()
    if not batch:
        return JSONResponse({"error": "Batch not found"}, status_code=404)

    person = db.query(Person).filter(Person.person_id == person_id).first()
    if not person or not person.email:
        return JSONResponse({"error": "Driver not found or no email"}, status_code=404)

    # Delete old failed log
    db.query(EmailSendLog).filter(
        EmailSendLog.payroll_batch_id == batch_id,
        EmailSendLog.person_id == person_id,
        EmailSendLog.status == "failed",
    ).delete()
    db.commit()

    payweek = _build_payweek(batch)
    rides = (
        db.query(Ride)
        .filter(Ride.payroll_batch_id == batch_id, Ride.person_id == person_id)
        .order_by(Ride.ride_start_ts.asc())
        .all()
    )

    pdf_path = _generate_pdf(person, rides, batch.company_name or "", payweek)
    total_pay = sum(float(r.z_rate or 0) for r in rides)

    try:
        send_paystub(
            to_email=person.email,
            driver_name=person.full_name,
            company=batch.company_name or "",
            payweek=payweek,
            pdf_path=pdf_path,
            person_id=person_id,
            payroll_batch_id=batch_id,
            week_start=batch.week_start.isoformat() if batch.week_start else "",
            week_end=batch.week_end.isoformat() if batch.week_end else "",
            total_pay=f"{total_pay:.2f}",
            ride_count=len(rides),
            db=db,
        )
        return JSONResponse({"ok": True, "status": "sent"})
    except Exception as exc:
        db.add(EmailSendLog(
            payroll_batch_id=batch_id,
            person_id=person_id,
            status="failed",
            error_message=str(exc)[:200],
        ))
        db.commit()
        return JSONResponse({"ok": False, "error": str(exc)[:200]}, status_code=500)
