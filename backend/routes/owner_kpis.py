"""
S8 — Owner KPIs.

One read-only endpoint feeding the owner's daily/weekly/monthly texts
(delivered via the external brief pipeline) and the meeting one-pager.
Money semantics mirror payroll_history exactly: revenue = partner_gross_total
when set else sum(ride.gross_pay); cost = sum(ride.z_rate); profit = the diff.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import (
    OnboardingFile,
    OnboardingRecord,
    PaychexJob,
    PayrollBatch,
    Person,
    Ride,
    RideIntake,
    RouteBackup,
    RouteRoster,
    TripNotification,
)

router = APIRouter(prefix="/api/data/owner", tags=["owner-kpis"])

WEEKLY_WINDOW_DAYS = 7
MONTHLY_WINDOW_DAYS = 28
COMPLIANCE_HORIZON_DAYS = 60

# ── Family-hours proxy (T6) — deliberately crude, direction over precision ──
CALL_MINUTES = 4              # est. operator minutes per dispatch call
ASSISTED_STEP_MINUTES = 60    # est. operator minutes per manual onboarding step
PAYCHEX_JOB_CAP_MINUTES = 120  # orphaned/hung jobs must not skew the estimate

# OnboardingRecord step-status columns counted as "assisted" when 'manual'.
_ONBOARDING_STEP_COLS = (
    "consent_status", "priority_email_status", "brandon_email_status",
    "bgc_status", "drug_test_status", "contract_status", "files_status",
    "paychex_status", "training_status", "maz_training_status",
    "maz_contract_status",
)


def _family_hours(db: Session, since_dt: datetime, until: date) -> dict:
    """Weekly operator-hours estimate — the north-star 'mom's time' metric.

    Proxy: dispatch calls × 4 min + Paychex bot session wall-time +
    manual onboarding steps × 60 min. Crude by design (T6): the target is
    ≤30 min/day and we need the direction of the line, not payroll-grade
    accuracy.
    """
    calls = _trip_counts(db, since_dt.date(), until)["calls_made"]
    call_minutes = calls * CALL_MINUTES

    payroll_minutes = 0.0
    jobs = (
        db.query(PaychexJob)
        .filter(PaychexJob.created_at >= since_dt, PaychexJob.finished_at.isnot(None))
        .all()
    )
    for j in jobs:
        dur = (j.finished_at - j.created_at).total_seconds() / 60
        payroll_minutes += min(max(dur, 0), PAYCHEX_JOB_CAP_MINUTES)

    assisted_steps = 0
    records = (
        db.query(OnboardingRecord)
        .filter(OnboardingRecord.started_at >= since_dt)
        .all()
    )
    for rec in records:
        assisted_steps += sum(
            1 for col in _ONBOARDING_STEP_COLS if getattr(rec, col, None) == "manual"
        )
    onboarding_minutes = assisted_steps * ASSISTED_STEP_MINUTES

    total_minutes = call_minutes + payroll_minutes + onboarding_minutes
    return {
        "call_minutes": round(call_minutes, 1),
        "payroll_minutes": round(payroll_minutes, 1),
        "onboarding_minutes": round(onboarding_minutes, 1),
        "total_hours": round(total_minutes / 60, 1),
        "per_day_minutes": round(total_minutes / WEEKLY_WINDOW_DAYS, 1),
    }


def _batch_money(db: Session, since: date) -> dict:
    """Revenue/cost/margin over batches whose week_end falls in the window,
    using payroll_history's exact profit semantics."""
    batches = (
        db.query(PayrollBatch)
        .filter(PayrollBatch.week_end.isnot(None), PayrollBatch.week_end >= since)
        .all()
    )
    revenue = 0.0
    cost = 0.0
    drivers: set[int] = set()
    per_batch = []
    for b in batches:
        rows = (
            db.query(
                func.coalesce(func.sum(Ride.gross_pay), 0),
                func.coalesce(func.sum(Ride.z_rate), 0),
            )
            .filter(Ride.payroll_batch_id == b.payroll_batch_id, Ride.removed_at.is_(None))
            .one()
        )
        gross = float(b.partner_gross_total) if b.partner_gross_total is not None else float(rows[0])
        z_cost = float(rows[1])
        revenue += gross
        cost += z_cost
        driver_ids = (
            db.query(Ride.person_id)
            .filter(Ride.payroll_batch_id == b.payroll_batch_id, Ride.removed_at.is_(None))
            .distinct()
            .all()
        )
        drivers.update(pid for (pid,) in driver_ids)
        per_batch.append({
            "batch_id": b.payroll_batch_id,
            "company": b.company_name,
            "week_end": b.week_end.isoformat() if b.week_end else None,
            "revenue": round(gross, 2),
            "cost": round(z_cost, 2),
            "margin": round(gross - z_cost, 2),
        })
    margin = round(revenue - cost, 2)
    return {
        "revenue": round(revenue, 2),
        "cost": round(cost, 2),
        "margin": margin,
        "margin_pct": round((margin / revenue) * 100, 1) if revenue else None,
        "drivers_paid": len(drivers),
        "batches": per_batch,
    }


def _trip_counts(db: Session, since: date, until: date) -> dict:
    trips = (
        db.query(TripNotification)
        .filter(TripNotification.trip_date >= since, TripNotification.trip_date <= until)
        .all()
    )
    total = len(trips)
    nudged = sum(1 for t in trips if t.accept_sms_at or t.start_sms_at)
    called = sum(1 for t in trips if t.accept_call_at or t.start_call_at)
    escalated = sum(1 for t in trips if t.accept_escalated_at or t.start_escalated_at)
    completed = sum(1 for t in trips if t.completed_at or (t.trip_status or "").lower() == "completed")
    touched = sum(
        1 for t in trips
        if t.accept_sms_at or t.start_sms_at or t.accept_call_at or t.start_call_at
    )
    return {
        "trips": total,
        "completed": completed,
        "nudges_sent": nudged,
        "calls_made": called,
        "escalations": escalated,
        "zero_touch": total - touched,
        "zero_touch_pct": round(((total - touched) / total) * 100, 1) if total else None,
    }


@router.get("/kpis")
def owner_kpis(db: Session = Depends(get_db)):
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    week_ago = today - timedelta(days=WEEKLY_WINDOW_DAYS)
    month_ago = today - timedelta(days=MONTHLY_WINDOW_DAYS)

    # ── Daily: yesterday's dispatch scorecard ────────────────────────────────
    daily = _trip_counts(db, yesterday, yesterday)
    daily["date"] = yesterday.isoformat()
    daily["open_intakes"] = db.query(RideIntake).filter(RideIntake.status == "draft").count()

    # ── Weekly: money + acceptance + growth signal ──────────────────────────
    weekly = _batch_money(db, week_ago)
    weekly["window_days"] = WEEKLY_WINDOW_DAYS
    weekly["dispatch"] = _trip_counts(db, week_ago, today)
    decided_since = datetime.now(timezone.utc) - timedelta(days=WEEKLY_WINDOW_DAYS)
    weekly["rides_taken"] = (
        db.query(RideIntake)
        .filter(RideIntake.status == "taken", RideIntake.decided_at >= decided_since)
        .count()
    )
    weekly["rides_passed"] = (
        db.query(RideIntake)
        .filter(RideIntake.status == "passed", RideIntake.decided_at >= decided_since)
        .count()
    )
    weekly["family_hours"] = _family_hours(db, decided_since, today)

    # ── Monthly: trend + resilience + extraction + compliance ───────────────
    monthly = _batch_money(db, month_ago)
    monthly["window_days"] = MONTHLY_WINDOW_DAYS
    active_rosters = db.query(RouteRoster).filter(RouteRoster.active.is_(True)).all()
    with_backup = {
        rid for (rid,) in db.query(RouteBackup.roster_id).distinct().all()
    }
    covered = sum(1 for r in active_rosters if r.roster_id in with_backup)
    monthly["backup_coverage_pct"] = (
        round((covered / len(active_rosters)) * 100, 1) if active_rosters else None
    )
    active_drivers = db.query(Person).filter(Person.active.is_(True), Person.status == "active")
    n_active = active_drivers.count()
    monthly["active_drivers"] = n_active
    monthly["revenue_per_driver"] = (
        round(monthly["revenue"] / monthly["drivers_paid"], 2) if monthly["drivers_paid"] else None
    )
    with_home = active_drivers.filter(Person.home_area.isnot(None), Person.home_area != "").count()
    with_lang = active_drivers.filter(Person.language.isnot(None)).count()
    monthly["extraction"] = {
        "home_area_pct": round((with_home / n_active) * 100, 1) if n_active else None,
        "language_pct": round((with_lang / n_active) * 100, 1) if n_active else None,
    }
    horizon = today + timedelta(days=COMPLIANCE_HORIZON_DAYS)
    monthly["compliance_expiring_60d"] = (
        db.query(OnboardingFile)
        .filter(OnboardingFile.expires_at.isnot(None),
                OnboardingFile.expires_at >= datetime.now(timezone.utc),
                OnboardingFile.expires_at <= datetime.combine(horizon, datetime.min.time(), tzinfo=timezone.utc))
        .count()
    )

    return JSONResponse({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "daily": daily,
        "weekly": weekly,
        "monthly": monthly,
    })
