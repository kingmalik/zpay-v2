"""
Trip acceptance monitor routes — dashboard, data API, manual trigger.
"""

from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import TripNotification, Person

router = APIRouter(prefix="/dispatch/monitor", tags=["monitor"])

_templates = None
def _get_templates():
    global _templates
    if _templates is None:
        templates_dir = Path(__file__).resolve().parents[1] / "templates"
        _templates = Jinja2Templates(directory=str(templates_dir))
    return _templates


@router.get("/", response_class=HTMLResponse)
async def monitor_page(request: Request, db: Session = Depends(get_db)):
    from backend.services.trip_monitor import get_status
    status = get_status()

    today = date.today()
    notifs = (
        db.query(TripNotification, Person)
        .join(Person, Person.person_id == TripNotification.person_id)
        .filter(TripNotification.trip_date == today)
        .order_by(TripNotification.pickup_time.asc())
        .all()
    )

    rows = []
    for notif, person in notifs:
        rows.append({
            "id": notif.id,
            "driver": person.full_name,
            "phone": person.phone or "",
            "source": notif.source,
            "trip_ref": notif.trip_ref,
            "pickup_time": notif.pickup_time or "",
            "trip_status": notif.trip_status or "",
            # Accept stage
            "accept_sms": notif.accept_sms_at.strftime("%-I:%M %p") if notif.accept_sms_at else None,
            "accept_call": notif.accept_call_at.strftime("%-I:%M %p") if notif.accept_call_at else None,
            "accept_escalated": notif.accept_escalated_at.strftime("%-I:%M %p") if notif.accept_escalated_at else None,
            "accepted": notif.accepted_at.strftime("%-I:%M %p") if notif.accepted_at else None,
            # Start stage
            "start_sms": notif.start_sms_at.strftime("%-I:%M %p") if notif.start_sms_at else None,
            "start_call": notif.start_call_at.strftime("%-I:%M %p") if notif.start_call_at else None,
            "start_escalated": notif.start_escalated_at.strftime("%-I:%M %p") if notif.start_escalated_at else None,
            "started": notif.started_at.strftime("%-I:%M %p") if notif.started_at else None,
        })

    # Stats
    total = len(rows)
    unaccepted = sum(1 for r in rows if not r["accepted"])
    not_started = sum(1 for r in rows if r["accepted"] and not r["started"])
    all_good = sum(1 for r in rows if r["started"])
    sms_sent = sum(1 for r in rows if r["accept_sms"] or r["start_sms"])
    calls_made = sum(1 for r in rows if r["accept_call"] or r["start_call"])
    escalations = sum(1 for r in rows if r["accept_escalated"] or r["start_escalated"])

    return _get_templates().TemplateResponse(
        request,
        "monitor.html",
        {
            "status": status,
            "rows": rows,
            "stats": {
                "total": total,
                "unaccepted": unaccepted,
                "not_started": not_started,
                "all_good": all_good,
                "sms_sent": sms_sent,
                "calls_made": calls_made,
                "escalations": escalations,
            },
        },
    )


@router.get("/data")
async def monitor_data(db: Session = Depends(get_db)):
    from backend.services.trip_monitor import get_status
    status = get_status()

    today = date.today()
    notifs = (
        db.query(TripNotification, Person)
        .join(Person, Person.person_id == TripNotification.person_id)
        .filter(TripNotification.trip_date == today)
        .order_by(TripNotification.pickup_time.asc())
        .all()
    )

    rows = []
    for notif, person in notifs:
        rows.append({
            "driver": person.full_name,
            "phone": person.phone or "",
            "source": notif.source,
            "trip_ref": notif.trip_ref,
            "pickup_time": notif.pickup_time or "",
            "trip_status": notif.trip_status or "",
            "accepted": bool(notif.accepted_at),
            "started": bool(notif.started_at),
            "accept_sms": bool(notif.accept_sms_at),
            "accept_call": bool(notif.accept_call_at),
            "accept_escalated": bool(notif.accept_escalated_at),
            "start_sms": bool(notif.start_sms_at),
            "start_call": bool(notif.start_call_at),
            "start_escalated": bool(notif.start_escalated_at),
        })

    return JSONResponse({
        "status": status,
        "rows": rows,
        "stats": {
            "total": len(rows),
            "unaccepted": sum(1 for r in rows if not r["accepted"]),
            "not_started": sum(1 for r in rows if r["accepted"] and not r["started"]),
        },
    })


@router.post("/run-now")
async def run_now():
    from backend.services.trip_monitor import run_monitoring_cycle
    summary = run_monitoring_cycle()
    return JSONResponse({"ok": True, "summary": summary})


@router.post("/toggle")
async def toggle_monitor():
    from backend.services.trip_monitor import _scheduler, start_monitor, stop_monitor
    if _scheduler:
        stop_monitor()
        return JSONResponse({"enabled": False})
    else:
        start_monitor()
        return JSONResponse({"enabled": True})


@router.get("/history")
async def monitor_history(days: int = 7, db: Session = Depends(get_db)):
    cutoff = date.today() - timedelta(days=days)
    notifs = (
        db.query(TripNotification, Person)
        .join(Person, Person.person_id == TripNotification.person_id)
        .filter(TripNotification.trip_date >= cutoff)
        .order_by(TripNotification.trip_date.desc(), TripNotification.pickup_time.asc())
        .all()
    )
    rows = []
    for notif, person in notifs:
        rows.append({
            "date": notif.trip_date.isoformat(),
            "driver": person.full_name,
            "source": notif.source,
            "pickup_time": notif.pickup_time or "",
            "accepted": bool(notif.accepted_at),
            "started": bool(notif.started_at),
            "escalated": bool(notif.accept_escalated_at or notif.start_escalated_at),
        })
    return JSONResponse({"history": rows, "days": days})
