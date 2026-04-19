"""
Operational JSON endpoints: today's dispatch snapshot + system health check.
Mounted at /api/data/ops/* via app.py.
"""

from datetime import date

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.db import get_db
from backend.db.models import Person, Ride, PayrollBatch, TripNotification

router = APIRouter(tags=["ops"])


@router.get("/today")
def api_today(db: Session = Depends(get_db)):
    today = date.today()

    notifs = (
        db.query(TripNotification, Person)
        .join(Person, Person.person_id == TripNotification.person_id)
        .filter(TripNotification.trip_date == today)
        .all()
    )

    fa = {"total": 0, "accepted": 0, "not_accepted": 0, "started": 0, "not_started": 0, "escalations": 0}
    ed = {"total": 0, "accepted": 0, "not_accepted": 0, "started": 0, "not_started": 0, "escalations": 0}

    for notif, _ in notifs:
        src = ed if (notif.source or "").lower() == "maz" else fa
        src["total"] += 1
        if notif.accepted_at:
            src["accepted"] += 1
            if notif.started_at:
                src["started"] += 1
            else:
                src["not_started"] += 1
        else:
            src["not_accepted"] += 1
        if notif.accept_escalated_at or notif.start_escalated_at:
            src["escalations"] += 1

    total_today = fa["total"] + ed["total"]

    try:
        from backend.routes.dashboard import _build_stats
        stats = _build_stats(db)
        avg_rides_per_day = float(stats.get("avg_rides_per_day", 0))
    except Exception:
        avg_rides_per_day = 0.0

    goal = 300

    return JSONResponse({
        "fa": fa,
        "ed": ed,
        "total_today": total_today,
        "avg_rides_per_day": avg_rides_per_day,
        "goal": goal,
        "goal_pct": round(min(avg_rides_per_day / goal * 100, 100), 1) if goal else 0,
    })


@router.get("/health")
def api_health(db: Session = Depends(get_db)):
    try:
        issues = []

        zero_rate_batches = (
            db.query(
                PayrollBatch.payroll_batch_id,
                PayrollBatch.source,
                PayrollBatch.company_name,
                PayrollBatch.week_start,
                func.count(Ride.ride_id).label("zero_count"),
            )
            .join(Ride, Ride.payroll_batch_id == PayrollBatch.payroll_batch_id)
            .filter(Ride.z_rate == 0)
            .group_by(
                PayrollBatch.payroll_batch_id,
                PayrollBatch.source,
                PayrollBatch.company_name,
                PayrollBatch.week_start,
            )
            .all()
        )
        for row in zero_rate_batches:
            week = row.week_start.strftime("%-m/%-d/%Y") if row.week_start else "unknown week"
            issues.append({
                "severity": "error",
                "type": "zero_rate",
                "title": f"{row.zero_count} ride(s) with $0 driver rate",
                "detail": f"{row.company_name or row.source} — week of {week}",
                "batch_id": row.payroll_batch_id,
            })

        loss_batches = (
            db.query(
                PayrollBatch.payroll_batch_id,
                PayrollBatch.source,
                PayrollBatch.company_name,
                PayrollBatch.week_start,
                func.sum(Ride.net_pay).label("revenue"),
                func.sum(Ride.z_rate).label("cost"),
            )
            .join(Ride, Ride.payroll_batch_id == PayrollBatch.payroll_batch_id)
            .group_by(
                PayrollBatch.payroll_batch_id,
                PayrollBatch.source,
                PayrollBatch.company_name,
                PayrollBatch.week_start,
            )
            .having(func.sum(Ride.z_rate) > func.sum(Ride.net_pay))
            .all()
        )
        for row in loss_batches:
            week = row.week_start.strftime("%-m/%-d/%Y") if row.week_start else "unknown week"
            revenue = float(row.revenue or 0)
            cost = float(row.cost or 0)
            gap = round(cost - revenue, 2)
            issues.append({
                "severity": "error",
                "type": "negative_margin",
                "title": f"Paying out ${gap} more than received",
                "detail": f"{row.company_name or row.source} — week of {week}",
                "batch_id": row.payroll_batch_id,
            })

        no_code = (
            db.query(func.count(Person.person_id))
            .filter(Person.active == True)
            .filter((Person.paycheck_code == None) | (Person.paycheck_code == ""))
            .scalar()
        ) or 0
        if no_code > 0:
            issues.append({
                "severity": "warning",
                "type": "missing_paycheck_code",
                "title": f"{no_code} active driver(s) missing paycheck code",
                "detail": "These drivers cannot be included in Paychex export",
                "batch_id": None,
            })

        errors = [i for i in issues if i["severity"] == "error"]
        warnings = [i for i in issues if i["severity"] == "warning"]

        return JSONResponse({
            "ok": len(issues) == 0,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "issues": issues,
        })

    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
