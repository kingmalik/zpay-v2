"""
Workflow API endpoints for the guided payroll workflow.
All routes under /api/data/workflow/* return JSON.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.db import get_db
from backend.db.models import (
    PayrollBatch, Ride, Person, EmailSendLog, ZRateService, BatchWorkflowLog, DriverBalance,
)
from backend.services.workflow import (
    STAGE_ORDER, advance_batch, reopen_batch, check_gate, next_stage,
)
from backend.routes.summary import _build_summary
from backend.utils.week_label import week_label as _wl

router = APIRouter(prefix="/api/data/workflow", tags=["workflow"])


def _safe_slug(s: str) -> str:
    import re
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "batch"


def _fmt_period(batch) -> str:
    """Return a filename-safe period string like 'mar17_mar21_2026'."""
    ws = getattr(batch, "week_start", None) or getattr(batch, "period_start", None)
    we = getattr(batch, "week_end", None) or getattr(batch, "period_end", None)
    if ws and we:
        return f"{ws.strftime('%b%d').lower()}_{we.strftime('%b%d_%Y').lower()}"
    if ws:
        return ws.strftime("%Y_%m_%d")
    return f"batch_{batch.payroll_batch_id}"


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
        "week_label": f"Week {(db.query(func.count(PayrollBatch.payroll_batch_id)).filter(PayrollBatch.source == batch.source, PayrollBatch.period_start <= batch.period_start).scalar() or 1)}",
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
    warnings = []
    if nxt:
        _, blockers, warnings = check_gate(db, batch, nxt)

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
        "warnings": warnings,
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


# ── Go back one stage ─────────────────────────────────────────────────────────

@router.post("/{batch_id}/go-back")
def workflow_go_back(batch_id: int, db: Session = Depends(get_db)):
    """Move the batch back one stage in the workflow pipeline."""
    batch = db.query(PayrollBatch).filter(PayrollBatch.payroll_batch_id == batch_id).first()
    if not batch:
        return JSONResponse({"error": "Batch not found"}, status_code=404)

    current = batch.status
    try:
        idx = STAGE_ORDER.index(current)
    except ValueError:
        return JSONResponse({"ok": False, "error": f"Unknown stage: {current}"}, status_code=400)

    if idx == 0:
        return JSONResponse({"ok": False, "error": "Already at the first stage"}, status_code=400)

    prev_stage = STAGE_ORDER[idx - 1]
    old_status = current

    # Cleanup depending on what we're undoing
    if current in ("approved", "export_ready"):
        # Undo payroll run — clear driver balances
        db.query(DriverBalance).filter(
            DriverBalance.payroll_batch_id == batch_id
        ).delete()
        batch.finalized_at = None

    elif current == "stubs_sending":
        # Going back to export_ready — clear email send logs so they can resend fresh
        db.query(EmailSendLog).filter(
            EmailSendLog.payroll_batch_id == batch_id
        ).delete()

    batch.status = prev_stage

    db.add(BatchWorkflowLog(
        payroll_batch_id=batch_id,
        from_status=old_status,
        to_status=prev_stage,
        triggered_by="user",
        notes=f"Went back from {old_status}",
    ))
    db.commit()

    return JSONResponse({"ok": True, "status": prev_stage})


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

    from sqlalchemy import text as _text
    override_rows = db.execute(
        _text("SELECT person_id FROM payroll_withheld_override WHERE batch_id = :b"),
        {"b": batch_id},
    ).fetchall()
    override_ids = {r[0] for r in override_rows}

    manual_withhold_rows = db.execute(
        _text("SELECT person_id, note FROM payroll_manual_withhold"),
    ).fetchall()
    manual_withhold_map = {r[0]: r[1] for r in manual_withhold_rows}

    data = _build_summary(db, batch_id=batch_id, auto_save=False, override_ids=override_ids or None, manual_withhold_ids=set(manual_withhold_map.keys()) or None)
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
                "affected": [
                    {"person_id": p.person_id, "name": p.full_name, "paycheck_code": p.paycheck_code or ""}
                    for p in missing_pay_code
                ],
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
                "affected": [
                    {"person_id": p.person_id, "name": p.full_name, "email": p.email or ""}
                    for p in missing_email
                ],
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
    negative_margin_ride_rows = (
        db.query(Ride.service_name, Ride.z_rate, Ride.net_pay, func.count(Ride.ride_id).label("cnt"))
        .filter(Ride.payroll_batch_id == batch_id, Ride.z_rate > Ride.net_pay, Ride.net_pay > 0)
        .group_by(Ride.service_name, Ride.z_rate, Ride.net_pay)
        .all()
    )
    negative_margin_rides = sum(int(r.cnt) for r in negative_margin_ride_rows)
    if negative_margin_rides > 0:
        neg_details = []
        for r in negative_margin_ride_rows:
            neg_details.append({
                "service_name": r.service_name or "Unknown",
                "z_rate": round(float(r.z_rate or 0), 2),
                "net_pay": round(float(r.net_pay or 0), 2),
                "count": int(r.cnt),
            })
        warnings.append({
            "severity": "warning",
            "title": f"{negative_margin_rides} rides with negative margin",
            "description": "Driver rate exceeds company rate — check rate assignments",
            "type": "negative_margin",
            "count": negative_margin_rides,
            "affected": neg_details,
        })

    # Late cancellation detection (EverDriven / source="maz")
    # Rides canceled within 2 hours get paid at half price.
    # Detect: net_pay is 40-55% of z_rate (both > 0).
    late_cancel_rides = (
        db.query(Ride, Person.full_name)
        .join(Person, Person.person_id == Ride.person_id)
        .filter(
            Ride.payroll_batch_id == batch_id,
            Ride.source == "maz",
            Ride.z_rate > 0,
            Ride.net_pay > 0,
            Ride.net_pay >= Ride.z_rate * 0.40,
            Ride.net_pay <= Ride.z_rate * 0.55,
        )
        .all()
    )
    if late_cancel_rides:
        lc_list = []
        for ride, driver_name in late_cancel_rides:
            z = float(ride.z_rate)
            n = float(ride.net_pay)
            lc_list.append({
                "driver": driver_name,
                "route": ride.service_name or "Unknown",
                "z_rate": round(z, 2),
                "net_pay": round(n, 2),
                "ratio": round(n / z, 2) if z else 0,
            })
        warnings.append({
            "severity": "warning",
            "title": "Late Cancellations Detected",
            "description": f"{len(lc_list)} EverDriven rides appear to be 2-hour cancellations (paid at ~50% of rate)",
            "type": "late_cancellation",
            "count": len(lc_list),
            "rides": lc_list,
        })

    # Net pay change detection — flags routes whose partner pay changed significantly
    # compared to historical averages (signals mileage adjustment).
    current_routes = (
        db.query(
            Ride.service_name,
            Ride.source,
            func.avg(Ride.net_pay).label("current_avg"),
        )
        .filter(Ride.payroll_batch_id == batch_id, Ride.net_pay > 0)
        .group_by(Ride.service_name, Ride.source)
        .all()
    )

    net_pay_changes = []
    for route in current_routes:
        sn, src, cur_avg = route.service_name, route.source, float(route.current_avg or 0)
        if not sn or cur_avg == 0:
            continue

        hist = (
            db.query(
                func.avg(Ride.net_pay).label("hist_avg"),
                func.count(Ride.ride_id).label("hist_count"),
            )
            .filter(
                Ride.service_name == sn,
                Ride.source == src,
                Ride.net_pay > 0,
                Ride.payroll_batch_id != batch_id,
            )
            .one()
        )
        hist_avg = float(hist.hist_avg or 0)
        hist_count = int(hist.hist_count or 0)

        if hist_count < 3 or hist_avg == 0:
            continue

        change_pct = round(((cur_avg - hist_avg) / hist_avg) * 100, 1)
        if abs(change_pct) > 15:
            net_pay_changes.append({
                "route": sn,
                "current_pay": round(cur_avg, 2),
                "historical_avg": round(hist_avg, 2),
                "change_pct": change_pct,
            })

    if net_pay_changes:
        warnings.append({
            "severity": "info",
            "title": "Net Pay Changes Detected",
            "description": f"{len(net_pay_changes)} routes show significant pay changes from partner — possible mileage adjustments",
            "type": "net_pay_change",
            "count": len(net_pay_changes),
            "rides": net_pay_changes,
        })

    # Fetch emails for all drivers in this batch
    all_person_ids = [r["person_id"] for r in rows]
    email_map = {
        p.person_id: p.email or ""
        for p in db.query(Person).filter(Person.person_id.in_(all_person_ids)).all()
    } if all_person_ids else {}

    # Format rows for frontend
    drivers_out = []
    withheld_out = []
    for r in rows:
        entry = {
            "id": r["person_id"],
            "name": r["person"],
            "pay_code": r["code"],
            "email": email_map.get(r["person_id"], ""),
            "days": r["days"],
            "net_pay": r["net_pay"],
            "carried_over": r["from_last_period"],
            "pay_this_period": r["pay_this_period"],
            "status": "withheld" if r["withheld"] else "paid",
            "withheld_amount": r["withheld_amount"],
            "force_pay_override": r["person_id"] in override_ids,
            "manual_withhold_note": manual_withhold_map.get(r["person_id"]),
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


# ── Email template (batch-level) ─────────────────────────────────────────────

@router.get("/{batch_id}/email-template")
def workflow_get_email_template(batch_id: int, db: Session = Depends(get_db)):
    """Return the resolved email template for this batch (batch override → default)."""
    from backend.routes.email_templates import get_template
    tmpl = get_template(db, batch_id=batch_id)
    return JSONResponse(tmpl)


@router.post("/{batch_id}/email-template")
async def workflow_save_email_template(batch_id: int, request: Request, db: Session = Depends(get_db)):
    """Save a batch-level email template override (JSON body: {subject, body})."""
    from backend.db.models import EmailTemplate
    data = await request.json()
    subject = data.get("subject", "").strip()
    body = data.get("body", "").strip()
    tmpl = db.query(EmailTemplate).filter(
        EmailTemplate.scope == "batch",
        EmailTemplate.payroll_batch_id == batch_id,
    ).first()
    if tmpl:
        tmpl.subject = subject
        tmpl.body = body
    else:
        tmpl = EmailTemplate(scope="batch", payroll_batch_id=batch_id, subject=subject, body=body)
        db.add(tmpl)
    db.commit()
    return JSONResponse({"ok": True})


# ── Stubs status ─────────────────────────────────────────────────────────────

@router.get("/{batch_id}/stubs-status")
def workflow_stubs_status(batch_id: int, db: Session = Depends(get_db)):
    batch = db.query(PayrollBatch).filter(PayrollBatch.payroll_batch_id == batch_id).first()
    if not batch:
        return JSONResponse({"error": "Batch not found"}, status_code=404)

    # All drivers in this batch — use a subquery to deduplicate by person_id
    # rather than .distinct() on the full Person object, which fails on PostgreSQL
    # json columns (cc_compliance, firstalt_compliance have no equality operator).
    person_ids_in_batch = (
        db.query(Ride.person_id)
        .filter(Ride.payroll_batch_id == batch_id)
        .distinct()
    )
    drivers = (
        db.query(Person)
        .filter(Person.person_id.in_(person_ids_in_batch))
        .all()
    )

    # Email send logs for this batch
    logs = (
        db.query(EmailSendLog)
        .filter(EmailSendLog.payroll_batch_id == batch_id)
        .all()
    )
    log_map = {log.person_id: log for log in logs}

    # Withheld drivers (carried-over balance > 0) — don't send them paystubs
    from backend.db.models import DriverBalance
    withheld_ids = {
        b.person_id
        for b in db.query(DriverBalance).filter(
            DriverBalance.payroll_batch_id == batch_id,
            DriverBalance.carried_over > 0,
        ).all()
    }

    results = []
    counts = {"sent": 0, "failed": 0, "no_email": 0, "withheld": 0, "pending": 0}

    for person in drivers:
        log = log_map.get(person.person_id)
        if person.person_id in withheld_ids:
            status = "withheld"
            counts["withheld"] += 1
        elif not person.email:
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


# ── Batch summary (JSON) ─────────────────────────────────────────────────────

@router.get("/{batch_id}/batch-summary")
def workflow_batch_summary(batch_id: int, db: Session = Depends(get_db)):
    """Return a structured JSON summary for the frontend summary page."""
    batch = db.query(PayrollBatch).filter(PayrollBatch.payroll_batch_id == batch_id).first()
    if not batch:
        return JSONResponse({"error": "Batch not found"}, status_code=404)

    from backend.db.models import DriverBalance

    week_num = (
        db.query(func.count(PayrollBatch.payroll_batch_id))
        .filter(
            PayrollBatch.source == batch.source,
            PayrollBatch.period_start <= batch.period_start,
        )
        .scalar() or 1
    )
    week_label = f"Week {week_num}"

    # Per-driver ride stats
    driver_rows = (
        db.query(
            Ride.person_id,
            Person.full_name,
            Person.paycheck_code,
            func.count(Ride.ride_id).label("rides"),
            func.coalesce(func.sum(Ride.miles), 0).label("miles"),
            func.coalesce(func.sum(Ride.net_pay), 0).label("partner_paid"),
            func.coalesce(func.sum(Ride.z_rate), 0).label("driver_pay"),
            func.coalesce(func.sum(Ride.deduction), 0).label("deduction"),
        )
        .join(Person, Person.person_id == Ride.person_id)
        .filter(Ride.payroll_batch_id == batch_id)
        .group_by(Ride.person_id, Person.full_name, Person.paycheck_code)
        .order_by(Person.full_name)
        .all()
    )

    # Balance records for this batch (withheld / carried over)
    balance_records = (
        db.query(DriverBalance)
        .filter(DriverBalance.payroll_batch_id == batch_id)
        .all()
    )
    balance_map = {b.person_id: float(b.carried_over or 0) for b in balance_records}

    drivers_out = []
    totals = {
        "rides": 0,
        "miles": 0.0,
        "partner_paid": 0.0,
        "driver_cost": 0.0,
        "withheld": 0.0,
        "payout": 0.0,
        "margin": 0.0,
    }

    for row in driver_rows:
        carried_over = balance_map.get(row.person_id, 0.0)
        is_withheld = carried_over > 0
        partner_paid = round(float(row.partner_paid), 2)
        driver_pay = round(float(row.driver_pay), 2)
        miles = round(float(row.miles), 3)
        deduction = round(float(row.deduction), 2)
        paid_this_period = 0.0 if is_withheld else driver_pay

        drivers_out.append({
            "person_id": row.person_id,
            "name": row.full_name,
            "pay_code": row.paycheck_code or "",
            "rides": int(row.rides),
            "miles": miles,
            "partner_paid": partner_paid,
            "driver_pay": driver_pay,
            "deduction": deduction,
            "withheld_amount": carried_over if is_withheld else 0.0,
            "paid_this_period": paid_this_period,
            "is_withheld": is_withheld,
        })

        totals["rides"] += int(row.rides)
        totals["miles"] = round(totals["miles"] + miles, 3)
        totals["partner_paid"] = round(totals["partner_paid"] + partner_paid, 2)
        totals["driver_cost"] = round(totals["driver_cost"] + driver_pay, 2)
        totals["withheld"] = round(totals["withheld"] + (carried_over if is_withheld else 0.0), 2)
        totals["payout"] = round(totals["payout"] + paid_this_period, 2)
        totals["margin"] = round(totals["partner_paid"] - totals["driver_cost"], 2)

    return JSONResponse({
        "batch": {
            "id": batch_id,
            "company": _display_company(batch.company_name or ""),
            "week_label": week_label,
            "period_start": batch.period_start.isoformat() if batch.period_start else None,
            "period_end": batch.period_end.isoformat() if batch.period_end else None,
            "batch_ref": batch.batch_ref,
            "source": batch.source,
            "status": batch.status,
            "finalized_at": batch.finalized_at.isoformat() if batch.finalized_at else None,
        },
        "totals": totals,
        "drivers": drivers_out,
    })


# ── Export Excel ─────────────────────────────────────────────────────────────

@router.get("/{batch_id}/export-excel")
def workflow_export_excel(batch_id: int, db: Session = Depends(get_db)):
    """Return a two-sheet .xlsx payroll summary for the batch."""
    import io
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from fastapi.responses import StreamingResponse
    from backend.db.models import DriverBalance

    batch = db.query(PayrollBatch).filter(PayrollBatch.payroll_batch_id == batch_id).first()
    if not batch:
        return JSONResponse({"error": "Batch not found"}, status_code=404)

    # ── Per-driver summary ────────────────────────────────────────────────────
    # FA (acumen/FirstAlt) batches → Person.paycheck_code (Acumen client)
    # ED (maz/EverDriven) batches → Person.paycheck_code_maz (Maz client)
    source = (batch.source or "").lower()
    code_col = Person.paycheck_code_maz if source == "maz" else Person.paycheck_code

    driver_rows = (
        db.query(
            Ride.person_id,
            Person.full_name,
            code_col.label("paycheck_code"),
            func.count(Ride.ride_id).label("rides"),
            func.coalesce(func.sum(Ride.miles), 0).label("miles"),
            func.coalesce(func.sum(Ride.net_pay), 0).label("partner_pays"),
            func.coalesce(func.sum(Ride.z_rate), 0).label("driver_pay"),
            func.coalesce(func.sum(Ride.deduction), 0).label("deduction"),
        )
        .join(Person, Person.person_id == Ride.person_id)
        .filter(Ride.payroll_batch_id == batch_id)
        .group_by(Ride.person_id, Person.full_name, code_col)
        .order_by(Person.full_name)
        .all()
    )

    balance_map = {
        b.person_id: float(b.carried_over or 0)
        for b in db.query(DriverBalance).filter(DriverBalance.payroll_batch_id == batch_id).all()
    }

    # ── Build workbook ────────────────────────────────────────────────────────
    wb = openpyxl.Workbook()

    header_font = Font(bold=True, color="FFFFFF")
    # Company-aware colors
    co = (batch.company_name or "").lower()
    if "acumen" in co or "first" in co:
        header_fill = PatternFill("solid", fgColor="4A1525")
        totals_fill = PatternFill("solid", fgColor="9B2C3D")
        totals_font = Font(bold=True, color="FFFFFF")
    elif "maz" in co or "ever" in co:
        header_fill = PatternFill("solid", fgColor="0F1D3A")
        totals_fill = PatternFill("solid", fgColor="1E3A6E")
        totals_font = Font(bold=True, color="FFFFFF")
    else:
        header_fill = PatternFill("solid", fgColor="2563EB")
        totals_fill = PatternFill("solid", fgColor="DBEAFE")
        totals_font = Font(bold=True)
    center = Alignment(horizontal="center")

    def style_header_row(ws, col_count):
        for col in range(1, col_count + 1):
            cell = ws.cell(row=1, column=col)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = center

    # Sheet 1 — Summary
    ws1 = wb.active
    ws1.title = "Summary"

    # Header info with dates
    company = batch.company_name or "Payroll"
    period_str = _fmt_period(batch)
    ws1.append([f"{company} — {period_str}"])
    ws1.cell(row=1, column=1).font = Font(bold=True, size=14)
    ws1.merge_cells(start_row=1, start_column=1, end_row=1, end_column=10)
    if batch.week_start and batch.week_end:
        ws1.append([f"Period: {batch.week_start.strftime('%b %d, %Y')} – {batch.week_end.strftime('%b %d, %Y')}"])
    elif batch.period_start and batch.period_end:
        ws1.append([f"Period: {batch.period_start.strftime('%b %d, %Y')} – {batch.period_end.strftime('%b %d, %Y')}"])
    else:
        ws1.append([""])
    ws1.cell(row=2, column=1).font = Font(italic=True, color="555555")
    ws1.merge_cells(start_row=2, start_column=1, end_row=2, end_column=10)
    ws1.append([])  # blank row

    s1_headers = [
        "Driver Name", "Pay Code", "Rides", "Miles",
        "Partner Pays", "Driver Pay", "Deduction",
        "Withheld (Y/N)", "Carried Over", "Paid This Period",
    ]
    ws1.append(s1_headers)
    header_row_num = ws1.max_row
    for col in range(1, len(s1_headers) + 1):
        cell = ws1.cell(row=header_row_num, column=col)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center

    tot_rides = tot_miles = tot_partner = tot_driver = tot_ded = tot_carried = tot_paid = 0.0

    for row in driver_rows:
        carried = balance_map.get(row.person_id, 0.0)
        is_withheld = carried > 0
        partner_pays = round(float(row.partner_pays), 2)
        driver_pay = round(float(row.driver_pay), 2)
        miles = round(float(row.miles), 3)
        deduction = round(float(row.deduction), 2)
        paid = 0.0 if is_withheld else driver_pay

        ws1.append([
            row.full_name,
            row.paycheck_code or "",
            int(row.rides),
            miles,
            partner_pays,
            driver_pay,
            deduction,
            "Yes" if is_withheld else "No",
            round(carried, 2) if is_withheld else 0.0,
            paid,
        ])

        tot_rides += int(row.rides)
        tot_miles += miles
        tot_partner += partner_pays
        tot_driver += driver_pay
        tot_ded += deduction
        tot_carried += carried if is_withheld else 0.0
        tot_paid += paid

    # Totals row
    totals_row = [
        "TOTALS", "", int(tot_rides), round(tot_miles, 3),
        round(tot_partner, 2), round(tot_driver, 2), round(tot_ded, 2),
        "", round(tot_carried, 2), round(tot_paid, 2),
    ]
    ws1.append(totals_row)
    last_row = ws1.max_row
    for col in range(1, len(s1_headers) + 1):
        cell = ws1.cell(row=last_row, column=col)
        cell.font = totals_font
        cell.fill = totals_fill

    # Auto-fit columns roughly — iterate by index so merged cells don't break us.
    # Start from header_row_num so the merged title/period rows at top don't count.
    for col_idx in range(1, len(s1_headers) + 1):
        letter = openpyxl.utils.get_column_letter(col_idx)
        max_len = max(
            (len(str(ws1.cell(row=r, column=col_idx).value or ""))
             for r in range(header_row_num, ws1.max_row + 1)),
            default=10,
        )
        ws1.column_dimensions[letter].width = min(max_len + 4, 40)

    # (Rides sheet removed — not needed)

    # ── Stream response ───────────────────────────────────────────────────────
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{_safe_slug(batch.company_name or "payroll")}_{_fmt_period(batch)}.xlsx"',
        },
    )


# ── Export PDF ───────────────────────────────────────────────────────────────

@router.get("/{batch_id}/export-pdf")
def workflow_export_pdf(batch_id: int, db: Session = Depends(get_db)):
    """Return a landscape PDF payroll summary for the batch."""
    import io
    from fastapi.responses import StreamingResponse
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, A4
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from backend.db.models import DriverBalance

    batch = db.query(PayrollBatch).filter(PayrollBatch.payroll_batch_id == batch_id).first()
    if not batch:
        return JSONResponse({"error": "Batch not found"}, status_code=404)

    week_num = (
        db.query(func.count(PayrollBatch.payroll_batch_id))
        .filter(
            PayrollBatch.source == batch.source,
            PayrollBatch.period_start <= batch.period_start,
        )
        .scalar() or 1
    )
    week_label = f"Week {week_num}"
    company = _display_company(batch.company_name or "")

    # Company-aware PDF colors
    _co = (batch.company_name or "").lower()
    if "acumen" in _co or "first" in _co:
        pdf_header_color = "#4A1525"
        pdf_totals_color = "#9B2C3D"
    elif "maz" in _co or "ever" in _co:
        pdf_header_color = "#0F1D3A"
        pdf_totals_color = "#1E3A6E"
    else:
        pdf_header_color = "#2563EB"
        pdf_totals_color = "#DBEAFE"
    period_start = batch.period_start.isoformat() if batch.period_start else "—"
    period_end = batch.period_end.isoformat() if batch.period_end else "—"
    batch_ref = batch.batch_ref or f"#{batch_id}"

    # ── Per-driver summary ────────────────────────────────────────────────────
    driver_rows = (
        db.query(
            Ride.person_id,
            Person.full_name,
            func.count(Ride.ride_id).label("rides"),
            func.coalesce(func.sum(Ride.net_pay), 0).label("partner_pays"),
            func.coalesce(func.sum(Ride.z_rate), 0).label("driver_pay"),
        )
        .join(Person, Person.person_id == Ride.person_id)
        .filter(Ride.payroll_batch_id == batch_id)
        .group_by(Ride.person_id, Person.full_name)
        .order_by(Person.full_name)
        .all()
    )

    balance_map = {
        b.person_id: float(b.carried_over or 0)
        for b in db.query(DriverBalance).filter(DriverBalance.payroll_batch_id == batch_id).all()
    }

    # ── Build PDF ─────────────────────────────────────────────────────────────
    buf = io.BytesIO()
    page_size = landscape(A4)
    doc = SimpleDocTemplate(
        buf,
        pagesize=page_size,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("title", parent=styles["Heading1"], alignment=TA_CENTER, fontSize=16)
    sub_style = ParagraphStyle("sub", parent=styles["Normal"], alignment=TA_CENTER, fontSize=10)
    footer_style = ParagraphStyle("footer", parent=styles["Normal"], alignment=TA_RIGHT, fontSize=8, textColor=colors.grey)

    story = []

    # Header block
    story.append(Paragraph(company, title_style))
    story.append(Paragraph(f"{week_label} &nbsp;&nbsp;|&nbsp;&nbsp; {period_start} – {period_end} &nbsp;&nbsp;|&nbsp;&nbsp; Ref: {batch_ref}", sub_style))
    story.append(Spacer(1, 0.5 * cm))

    # Table data
    col_headers = ["Driver Name", "Rides", "Partner Pays", "Driver Pay", "Withheld", "Paid This Period"]
    table_data = [col_headers]

    tot_rides = 0
    tot_partner = 0.0
    tot_driver = 0.0
    tot_withheld = 0.0
    tot_paid = 0.0

    for row in driver_rows:
        carried = balance_map.get(row.person_id, 0.0)
        is_withheld = carried > 0
        partner_pays = round(float(row.partner_pays), 2)
        driver_pay = round(float(row.driver_pay), 2)
        withheld_amt = round(carried, 2) if is_withheld else 0.0
        paid = 0.0 if is_withheld else driver_pay

        table_data.append([
            row.full_name,
            str(int(row.rides)),
            f"${partner_pays:,.2f}",
            f"${driver_pay:,.2f}",
            f"${withheld_amt:,.2f}" if is_withheld else "—",
            f"${paid:,.2f}",
        ])

        tot_rides += int(row.rides)
        tot_partner += partner_pays
        tot_driver += driver_pay
        tot_withheld += withheld_amt
        tot_paid += paid

    # Totals row
    table_data.append([
        "TOTALS",
        str(tot_rides),
        f"${tot_partner:,.2f}",
        f"${tot_driver:,.2f}",
        f"${tot_withheld:,.2f}",
        f"${tot_paid:,.2f}",
    ])

    page_w = page_size[0] - 3 * cm
    col_widths = [page_w * 0.30, page_w * 0.08, page_w * 0.16, page_w * 0.16, page_w * 0.15, page_w * 0.15]

    tbl = Table(table_data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(pdf_header_color)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor(pdf_totals_color)),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F1F5F9")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(tbl)

    story.append(Spacer(1, 0.5 * cm))
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    story.append(Paragraph(f"Generated: {generated_at}", footer_style))

    doc.build(story)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{_safe_slug(batch.company_name or "payroll")}_{_fmt_period(batch)}.pdf"',
        },
    )

# ── Preview stub (dry-run email preview) ─────────────────────────────────────

@router.get("/{batch_id}/preview-stub/{person_id}")
def workflow_preview_stub(batch_id: int, person_id: int, db: Session = Depends(get_db)):
    """Return a JSON preview of the email that would be sent, without sending it."""
    from backend.routes.email import _build_payweek
    from backend.routes.email_templates import get_template, render_template
    from backend.services.email_service import _body_to_html

    batch = db.query(PayrollBatch).filter(PayrollBatch.payroll_batch_id == batch_id).first()
    if not batch:
        return JSONResponse({"error": "Batch not found"}, status_code=404)

    person = db.query(Person).filter(Person.person_id == person_id).first()
    if not person:
        return JSONResponse({"error": "Person not found"}, status_code=404)

    rides = (
        db.query(Ride)
        .filter(Ride.payroll_batch_id == batch_id, Ride.person_id == person_id)
        .order_by(Ride.ride_start_ts.asc())
        .all()
    )

    payweek = _build_payweek(batch)
    company = batch.company_name or ""
    total_pay = sum(float(r.z_rate or 0) for r in rides)

    tmpl = get_template(db, person_id=person_id, batch_id=batch_id)
    from backend.routes.email_templates import build_signature_html
    ctx = {
        "driver_name": person.full_name,
        "first_name": (person.full_name.split() or ["Driver"])[0],
        "week_start": batch.week_start.isoformat() if batch.week_start else payweek,
        "week_end": batch.week_end.isoformat() if batch.week_end else payweek,
        "total_pay": f"{total_pay:.2f}",
        "ride_count": str(len(rides)),
        "company_name": company,
        "signature_html": build_signature_html(company),
    }
    subject, body = render_template(tmpl, ctx)
    html_email = _body_to_html(body, company=company, subject=subject)

    return JSONResponse({
        "subject": subject,
        "body_html": html_email,
        "driver_name": person.full_name,
        "email": person.email or "",
    })


# ── SMTP connectivity test ────────────────────────────────────────────────────

@router.get("/smtp-test")
def smtp_test():
    from backend.services.email_service import _IPv4SMTP
    import smtplib, socket
    results = {}
    # Test IPv4-forced port 587
    try:
        s = _IPv4SMTP("smtp.gmail.com", 587, timeout=10)
        s.ehlo()
        s.starttls()
        s.ehlo()
        s.quit()
        results["587_ipv4"] = "OK"
    except Exception as e:
        results["587_ipv4"] = str(e)
    # Test default port 587
    try:
        s = smtplib.SMTP("smtp.gmail.com", 587, timeout=10)
        s.ehlo(); s.starttls(); s.ehlo(); s.quit()
        results["587_default"] = "OK"
    except Exception as e:
        results["587_default"] = str(e)
    try:
        ip = socket.gethostbyname("smtp.gmail.com")
        results["dns_ipv4"] = ip
    except Exception as e:
        results["dns_ipv4"] = str(e)
    return JSONResponse(results)


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
            # Clear any old failed logs and record success
            db.query(EmailSendLog).filter(
                EmailSendLog.payroll_batch_id == batch_id,
                EmailSendLog.person_id == person.person_id,
                EmailSendLog.status == "failed",
            ).delete()
            db.add(EmailSendLog(
                payroll_batch_id=batch_id,
                person_id=person.person_id,
                status="sent",
            ))
            db.commit()
            sent += 1
        except Exception as exc:
            import logging, traceback
            logging.getLogger("zpay.workflow").error(
                "Failed to send stub to %s <%s>: %s\n%s",
                person.full_name, person.email, exc, traceback.format_exc(),
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


# ── Send single stub (for progress-bar flow) ────────────────────────────────

@router.post("/{batch_id}/send-stub/{person_id}")
def workflow_send_single_stub(batch_id: int, person_id: int, db: Session = Depends(get_db)):
    """Send a paystub to one driver. Used by the frontend progress-bar loop."""
    from backend.routes.email import _generate_pdf, _build_payweek
    from backend.services.email_service import send_paystub

    batch = db.query(PayrollBatch).filter(PayrollBatch.payroll_batch_id == batch_id).first()
    if not batch:
        return JSONResponse({"error": "Batch not found"}, status_code=404)

    person = db.query(Person).filter(Person.person_id == person_id).first()
    if not person:
        return JSONResponse({"ok": False, "status": "not_found", "error": "Driver not found"}, status_code=404)
    if not person.email:
        return JSONResponse({"ok": True, "status": "no_email", "name": person.full_name})

    # Skip withheld drivers — they're not receiving pay this period
    from backend.db.models import DriverBalance
    balance = db.query(DriverBalance).filter(
        DriverBalance.person_id == person_id,
        DriverBalance.payroll_batch_id == batch_id,
    ).first()
    if balance and balance.carried_over and float(balance.carried_over) > 0:
        return JSONResponse({"ok": True, "status": "no_email", "name": person.full_name})

    # Skip if already sent
    already = db.query(EmailSendLog).filter(
        EmailSendLog.payroll_batch_id == batch_id,
        EmailSendLog.person_id == person_id,
        EmailSendLog.status == "sent",
    ).first()
    if already:
        return JSONResponse({"ok": True, "status": "already_sent", "name": person.full_name})

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
        # Clear old failed logs, record success
        db.query(EmailSendLog).filter(
            EmailSendLog.payroll_batch_id == batch_id,
            EmailSendLog.person_id == person_id,
            EmailSendLog.status == "failed",
        ).delete()
        db.add(EmailSendLog(
            payroll_batch_id=batch_id,
            person_id=person_id,
            status="sent",
        ))
        db.commit()
        return JSONResponse({"ok": True, "status": "sent", "name": person.full_name})
    except Exception as exc:
        import logging, traceback
        logging.getLogger("zpay.workflow").error(
            "send-stub failed for person %s: %s\n%s", person_id, exc, traceback.format_exc()
        )
        db.add(EmailSendLog(
            payroll_batch_id=batch_id,
            person_id=person_id,
            status="failed",
            error_message=str(exc)[:200],
        ))
        db.commit()
        return JSONResponse({"ok": False, "status": "failed", "name": person.full_name, "error": str(exc)[:200]})


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

    # Skip withheld drivers — they're not receiving pay this period
    from backend.db.models import DriverBalance
    balance = db.query(DriverBalance).filter(
        DriverBalance.person_id == person_id,
        DriverBalance.payroll_batch_id == batch_id,
    ).first()
    if balance and balance.carried_over and float(balance.carried_over) > 0:
        return JSONResponse({"ok": True, "status": "no_email", "name": person.full_name})

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
        import logging, traceback
        logging.getLogger("zpay.workflow").error(
            "retry-stub failed for person %s: %s\n%s", person_id, exc, traceback.format_exc()
        )
        db.add(EmailSendLog(
            payroll_batch_id=batch_id,
            person_id=person_id,
            status="failed",
            error_message=str(exc)[:200],
        ))
        db.commit()
        return JSONResponse({"ok": False, "error": str(exc)[:200]}, status_code=500)


# ── Direct withheld toggle (for summary page corrections) ────────────────────

@router.post("/{batch_id}/set-withheld/{person_id}")
async def workflow_set_withheld(batch_id: int, person_id: int, request: Request, db: Session = Depends(get_db)):
    """
    Directly flip a driver's withheld status for this batch by editing
    their DriverBalance record. Used from the summary page to correct
    mistakes without re-running the full workflow.

    body: { "withheld": true | false }
    """
    from sqlalchemy import text
    body = await request.json()
    withheld = body.get("withheld", True)

    batch = db.query(PayrollBatch).filter(PayrollBatch.payroll_batch_id == batch_id).first()
    if not batch:
        return JSONResponse({"error": "Batch not found"}, status_code=404)

    # Calculate combined pay for this driver (this week + any carry-in from last batch)
    data = _build_summary(db, batch_id=batch_id, auto_save=False)
    driver_row = next((r for r in data["rows"] if r["person_id"] == person_id), None)
    if not driver_row:
        return JSONResponse({"error": "Driver not in this batch"}, status_code=404)

    combined = round(driver_row["driver_pay"] + driver_row["from_last_period"], 2)

    # Update (or create) DriverBalance record
    existing = db.query(DriverBalance).filter(
        DriverBalance.payroll_batch_id == batch_id,
        DriverBalance.person_id == person_id,
    ).first()

    if withheld:
        # Move driver to withheld: store full combined amount as carry-over
        db.execute(
            text("DELETE FROM payroll_withheld_override WHERE batch_id = :b AND person_id = :p"),
            {"b": batch_id, "p": person_id},
        )
        if existing:
            existing.carried_over = combined
        else:
            db.add(DriverBalance(person_id=person_id, payroll_batch_id=batch_id, carried_over=combined))
    else:
        # Move driver to paid: zero out the balance, mark as force-paid
        db.execute(
            text("INSERT INTO payroll_withheld_override (batch_id, person_id) VALUES (:b, :p) ON CONFLICT DO NOTHING"),
            {"b": batch_id, "p": person_id},
        )
        if existing:
            existing.carried_over = 0
        else:
            db.add(DriverBalance(person_id=person_id, payroll_batch_id=batch_id, carried_over=0))

    db.commit()
    return JSONResponse({"ok": True, "withheld": withheld, "combined": combined})


# ── Withheld override endpoints ─────────────────────────────────────────────

@router.post("/{batch_id}/override-withheld/{person_id}")
def workflow_override_withheld(batch_id: int, person_id: int, db: Session = Depends(get_db)):
    """Force-pay a withheld driver for this batch regardless of the $100 threshold."""
    from sqlalchemy import text
    db.execute(
        text("INSERT INTO payroll_withheld_override (batch_id, person_id) VALUES (:b, :p) ON CONFLICT DO NOTHING"),
        {"b": batch_id, "p": person_id},
    )
    db.commit()
    return JSONResponse({"ok": True})


@router.delete("/{batch_id}/override-withheld/{person_id}")
def workflow_remove_withheld_override(batch_id: int, person_id: int, db: Session = Depends(get_db)):
    """Remove a force-pay override — driver goes back to normal withheld logic."""
    from sqlalchemy import text
    db.execute(
        text("DELETE FROM payroll_withheld_override WHERE batch_id = :b AND person_id = :p"),
        {"b": batch_id, "p": person_id},
    )
    db.commit()
    return JSONResponse({"ok": True})


@router.post("/{batch_id}/manual-withhold/{person_id}")
async def workflow_set_manual_withhold(batch_id: int, person_id: int, request: Request, db: Session = Depends(get_db)):
    """Manually withhold a driver's pay regardless of amount, with a note."""
    from sqlalchemy import text
    body = await request.json()
    note = body.get("note", "").strip()
    db.execute(
        text("INSERT INTO payroll_manual_withhold (person_id, note) VALUES (:p, :n) ON CONFLICT (person_id) DO UPDATE SET note = EXCLUDED.note, created_at = now()"),
        {"p": person_id, "n": note},
    )
    db.commit()
    return JSONResponse({"ok": True})

@router.delete("/{batch_id}/manual-withhold/{person_id}")
def workflow_clear_manual_withhold(batch_id: int, person_id: int, db: Session = Depends(get_db)):
    """Release a manual withhold — driver gets paid normally next batch."""
    from sqlalchemy import text
    db.execute(
        text("DELETE FROM payroll_manual_withhold WHERE person_id = :p"),
        {"p": person_id},
    )
    db.commit()
    return JSONResponse({"ok": True})


# ── Inline edit endpoints ───────────────────────────────────────────────────

@router.patch("/{batch_id}/update-person/{person_id}")
async def workflow_update_person(batch_id: int, person_id: int, request: Request, db: Session = Depends(get_db)):
    """Update a person's paycheck_code or email inline from the review step."""
    body = await request.json()
    person = db.query(Person).filter(Person.person_id == person_id).first()
    if not person:
        return JSONResponse({"error": "Person not found"}, status_code=404)

    if "paycheck_code" in body:
        person.paycheck_code = body["paycheck_code"].strip() or None
    if "email" in body:
        person.email = body["email"].strip() or None

    db.commit()
    return JSONResponse({
        "ok": True,
        "person_id": person.person_id,
        "paycheck_code": person.paycheck_code or "",
        "email": person.email or "",
    })


@router.patch("/{batch_id}/update-ride-rate")
async def workflow_update_ride_rate(batch_id: int, request: Request, db: Session = Depends(get_db)):
    """Update z_rate for rides in a batch matching a service_name.

    ``mode`` controls scope:
      - "default" (default): update ZRateService.default_rate (permanent) and
        every matching ride in this batch.
      - "late_cancellation": save as ZRateService.late_cancellation_rate so
        future late-cancel rides (net_pay 40–55% of default_rate) on this
        route get this rate automatically. Only late-cancel rides in the
        current batch are re-rated; regular rides keep their original rate.
      - "batch_only": update only matching rides in this batch; leave the
        permanent default_rate and late_cancellation_rate untouched.

    Legacy ``batch_only: true`` is still accepted and mapped to mode=batch_only.
    """
    from decimal import Decimal

    body = await request.json()
    service_name = body.get("service_name", "").strip()
    z_rate = body.get("z_rate")
    mode = (body.get("mode") or "").strip().lower()
    if not mode:
        mode = "batch_only" if bool(body.get("batch_only", False)) else "default"

    if mode not in ("default", "late_cancellation", "batch_only"):
        return JSONResponse({"error": f"invalid mode: {mode}"}, status_code=400)

    if not service_name or z_rate is None:
        return JSONResponse({"error": "service_name and z_rate required"}, status_code=400)

    rate_val = float(z_rate)
    if rate_val < 0:
        return JSONResponse({"error": "z_rate cannot be negative"}, status_code=400)

    svc = db.query(ZRateService).filter(ZRateService.service_name == service_name).first()

    if mode == "late_cancellation":
        # Persist as the per-service late-cancellation rate.
        if svc:
            svc.late_cancellation_rate = Decimal(str(rate_val))

        # Re-rate only late-cancellation rides in THIS batch
        # (net_pay is 40–55% of the existing z_rate).
        updated = (
            db.query(Ride)
            .filter(
                Ride.payroll_batch_id == batch_id,
                Ride.service_name == service_name,
                Ride.z_rate > 0,
                Ride.net_pay > 0,
                Ride.net_pay >= Ride.z_rate * 0.40,
                Ride.net_pay <= Ride.z_rate * 0.55,
            )
            .update({"z_rate": rate_val}, synchronize_session=False)
        )
    else:
        # default: update rides in this batch AND every other non-finalized batch
        # for the same service so the permanent rate truly persists across batches.
        # batch_only: only this batch, svc row untouched.
        if mode == "default":
            # Update ALL open/unfinalized batches (do not touch status=complete/approved)
            from backend.db.models import PayrollBatch
            open_batch_ids = [
                row.payroll_batch_id
                for row in db.query(PayrollBatch.payroll_batch_id).filter(
                    PayrollBatch.status.notin_(["complete", "approved"])
                ).all()
            ]
            updated = (
                db.query(Ride)
                .filter(
                    Ride.payroll_batch_id.in_(open_batch_ids),
                    Ride.service_name == service_name,
                )
                .update({"z_rate": rate_val, "z_rate_source": "permanent_override"}, synchronize_session=False)
            )
            # Also update the current batch explicitly in case it was already finalized
            # or not in open_batch_ids (edge case)
            db.query(Ride).filter(
                Ride.payroll_batch_id == batch_id,
                Ride.service_name == service_name,
            ).update({"z_rate": rate_val, "z_rate_source": "permanent_override"}, synchronize_session=False)
            if svc:
                svc.default_rate = Decimal(str(rate_val))
        else:
            # batch_only: only this batch
            updated = (
                db.query(Ride)
                .filter(Ride.payroll_batch_id == batch_id, Ride.service_name == service_name)
                .update({"z_rate": rate_val}, synchronize_session=False)
            )

    db.commit()
    return JSONResponse({"ok": True, "rides_updated": updated, "mode": mode})
