"""
backend/routes/public.py
========================
Unauthenticated read-only endpoints — safe to call without a session cookie.

Routes here bypass AuthMiddleware (prefix is listed in PUBLIC_PREFIXES in
middleware/auth.py). Be paranoid about what you expose: only the fields
listed in each docstring leave this file.

Current routes
--------------
GET /api/public/driver/{person_id}/scorecard
    Driver-facing scorecard card — safe fields only, no money, no internal IDs.
    (Legacy — person_id-based, no token.)

GET /api/public/driver/{person_id}/portal
    Driver self-serve portal — pay, trips, balance, tier. No auth required.
    Returns: first_name, tier, composite_score, current_week pay summary,
             held_balance, recent_weeks history, scorecard_url.
    NEVER exposes: paycheck_code, paycheck_code_maz, internal IDs, route names,
                   gross margins, other drivers' data.

GET /api/public/scorecard/{token}
    HMAC-signed driver scorecard (Phase 9). Token encodes person_id + week_iso + iat.
    Token expires in 14 days. Safe fields only — same exclusion rules as above.
    Used by Phase 10 SMS cron — drivers tap the link from their text message.
    Mint tokens via: backend.services.scorecard_token.mint_token(person_id, week_iso)
"""

from __future__ import annotations

import os
from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import DriverBalance, PayrollBatch, Person, Ride
from backend.services.driver_scorecard import (
    AXIS_LABELS,
    compute_driver_scorecard,
)
from backend.services.scorecard_token import (
    TokenExpiredError,
    TokenInvalidError,
    verify_token,
)
from backend.utils.week_label import week_label as _week_label

router = APIRouter(tags=["public"])

# ── Rate limiting ──────────────────────────────────────────────────────────────
# Uses the same Limiter instance that app.state.limiter is set to (auth.py).
# The shared app-level exception handler covers 429 formatting.
_limiter = Limiter(key_func=get_remote_address)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_iso_week(w: str):
    """Parse 'YYYY-Www' -> Monday date. Mirrors api_data._parse_iso_week."""
    from datetime import date
    import re
    m = re.fullmatch(r"(\d{4})-W(\d{2})", w)
    if not m:
        raise ValueError(f"Invalid week format '{w}', expected YYYY-Www")
    year, week = int(m.group(1)), int(m.group(2))
    return date.fromisocalendar(year, week, 1)


def _current_pt_week_start():
    """Return the most recent Monday in Pacific Time."""
    from datetime import date, datetime
    from zoneinfo import ZoneInfo
    now_pt = datetime.now(ZoneInfo("America/Los_Angeles"))
    today = now_pt.date()
    return today - timedelta(days=today.weekday())


def _axis_to_public(axis_key: str, ax) -> dict:
    """Serialize one AxisScore to the driver-safe public shape.

    Included:  raw (as percentage), label, available, sample_size.
    Excluded:  weight, weighted_score, normalized_value -- internal scoring
               mechanics that drivers don't need and shouldn't see.
    """
    return {
        "label": AXIS_LABELS.get(axis_key, axis_key),
        "value_pct": round(ax.raw_value * 100, 1) if ax.available else None,
        "available": ax.available,
        "sample_size": ax.sample_size,
    }


# ── Scorecard route logic (legacy person_id-based) ────────────────────────────

def _scorecard_response(person_id: int, db: Session) -> JSONResponse:
    """Core logic, extracted for direct test calls (no HTTP/limiter layer).

    Safe fields returned
    --------------------
    - first_name only (no last name)
    - current_tier + composite_score
    - per-axis breakdown (label + raw percentage) -- NO weights
    - last 4 weeks composite trend (week_iso + composite_score + tier)

    Excluded (never leave this function)
    -------------------------------------
    - paycheck_code / paycheck_code_maz
    - person_id / internal DB IDs
    - override events
    - anything money-related
    """
    # -- Driver must exist (active OR inactive -- drivers share old links) -------
    person = db.query(Person).filter(Person.person_id == person_id).first()
    if not person:
        return JSONResponse({"error": "Driver not found"}, status_code=404)

    # First name only -- no last name in public response
    first_name = (person.full_name or "").split()[0] if person.full_name else "Driver"

    # -- Current week -----------------------------------------------------------
    week_start = _current_pt_week_start()
    sc = compute_driver_scorecard(person_id, week_start, db)

    axes_public = {
        k: _axis_to_public(k, ax)
        for k, ax in sc.axes.items()
        if ax.available
    }

    # -- Last 4 weeks trend -----------------------------------------------------
    trend: list[dict] = []
    for weeks_back in range(4, 0, -1):
        hist_start = week_start - timedelta(weeks=weeks_back)
        hist_sc = compute_driver_scorecard(person_id, hist_start, db)
        hist_iso = (
            f"{hist_start.isocalendar().year}-W"
            f"{hist_start.isocalendar().week:02d}"
        )
        trend.append({
            "week_iso": hist_iso,
            "composite_score": hist_sc.composite_score,
            "tier": hist_sc.tier,
        })
    # Append current week
    current_iso = (
        f"{week_start.isocalendar().year}-W"
        f"{week_start.isocalendar().week:02d}"
    )
    trend.append({
        "week_iso": current_iso,
        "composite_score": sc.composite_score,
        "tier": sc.tier,
    })

    return JSONResponse({
        "first_name": first_name,
        "tier": sc.tier,
        "tier_label": sc.tier_label,
        "composite_score": sc.composite_score,
        "low_sample": sc.low_sample,
        "axes": axes_public,
        "trend": trend,
    })


@router.get("/api/public/driver/{person_id}/scorecard")
@_limiter.limit("30/minute")
def public_driver_scorecard(
    request: Request,
    person_id: int,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Driver-facing scorecard endpoint -- unauthenticated, rate-limited.

    Delegates to _scorecard_response() which contains all the safe-field logic.
    """
    return _scorecard_response(person_id, db)


# ── HMAC-token scorecard (Phase 9) ────────────────────────────────────────────

def _hmac_scorecard_response(token: str, db: Session) -> JSONResponse:
    """Core logic for the HMAC-token scorecard endpoint.

    Extracted for direct test calls (no HTTP/limiter layer).

    Token encodes: person_id + week_iso + issued_at.
    Token TTL: 14 days.

    Safe fields returned
    --------------------
    - first_name only (no last name)
    - week_iso (from token -- may not be current week)
    - tier + tier_label + composite_score
    - per-axis breakdown (label + raw %) -- NO weights
    - last 4 weeks composite trend
    - focus_area coaching message when set

    Error codes
    -----------
    - 422 -- token is invalid or expired
    - 404 -- driver not found (unknown person_id in token)
    - 200 -- success (active or inactive drivers both resolve)
    """
    # -- Verify token -----------------------------------------------------------
    try:
        payload = verify_token(token)
    except TokenExpiredError:
        return JSONResponse(
            {"error": "This scorecard link has expired. Ask dispatch for a new one."},
            status_code=422,
        )
    except TokenInvalidError:
        return JSONResponse(
            {"error": "This scorecard link is invalid."},
            status_code=422,
        )

    person_id = payload.person_id
    week_iso = payload.week_iso

    # -- Driver must exist (active OR inactive -- drivers share old SMS links) ---
    person = db.query(Person).filter(Person.person_id == person_id).first()
    if not person:
        return JSONResponse({"error": "Driver not found"}, status_code=404)

    # First name only -- no last name in public response
    first_name = (person.full_name or "").split()[0] if person.full_name else "Driver"

    # -- Parse week from token --------------------------------------------------
    try:
        week_start = _parse_iso_week(week_iso)
    except ValueError:
        return JSONResponse({"error": "Invalid week in token."}, status_code=422)

    # -- Scorecard for the token's week ----------------------------------------
    sc = compute_driver_scorecard(person_id, week_start, db)

    axes_public = {
        k: _axis_to_public(k, ax)
        for k, ax in sc.axes.items()
        if ax.available
    }

    # -- Last 4 weeks trend -----------------------------------------------------
    trend: list[dict] = []
    for weeks_back in range(4, 0, -1):
        hist_start = week_start - timedelta(weeks=weeks_back)
        hist_sc = compute_driver_scorecard(person_id, hist_start, db)
        hist_iso = (
            f"{hist_start.isocalendar().year}-W"
            f"{hist_start.isocalendar().week:02d}"
        )
        trend.append({
            "week_iso": hist_iso,
            "composite_score": hist_sc.composite_score,
            "tier": hist_sc.tier,
        })
    trend.append({
        "week_iso": week_iso,
        "composite_score": sc.composite_score,
        "tier": sc.tier,
    })

    return JSONResponse({
        "first_name": first_name,
        "week_iso": week_iso,
        "tier": sc.tier,
        "tier_label": sc.tier_label,
        "composite_score": sc.composite_score,
        "low_sample": sc.low_sample,
        "axes": axes_public,
        "trend": trend,
        "focus_area": sc.focus_area or None,
    })


@router.get("/api/public/scorecard/{token}")
@_limiter.limit("30/minute")
def public_scorecard_by_token(
    request: Request,
    token: str,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """HMAC-signed driver scorecard endpoint -- unauthenticated, rate-limited.

    Token is signed with SCORECARD_HMAC_SECRET. Expires in 14 days.
    Mint via: backend.services.scorecard_token.mint_token(person_id, week_iso)

    Delegates to _hmac_scorecard_response() for all safe-field logic.
    """
    return _hmac_scorecard_response(token, db)


# ── Portal helpers ─────────────────────────────────────────────────────────────

def _batch_week_label(batch: PayrollBatch, db: Session) -> str:
    """Return 'Week N' for a batch using sequential rank within its source."""
    from sqlalchemy import func as _func
    src = batch.source or ""
    period_start = batch.period_start
    if period_start is None:
        return _week_label(batch.period_start, batch.period_end) or "---"
    count = (
        db.query(_func.count(PayrollBatch.payroll_batch_id))
        .filter(
            PayrollBatch.source == src,
            PayrollBatch.period_start <= period_start,
        )
        .scalar()
    ) or 1
    return f"Week {int(count)}"


def _portal_response(person_id: int, db: Session) -> JSONResponse:
    """Core portal logic -- no HTTP layer, testable directly.

    Safe fields returned
    --------------------
    - first_name only
    - tier + composite_score (from current-week scorecard)
    - current_week: week_label, trips_completed, driver_pay, withheld,
                    withheld_amount, carried_over, paid_this_period
    - held_balance: sum of ALL driver_balance.carried_over rows for this driver
    - recent_weeks: last 3 prior batches (week_label, trips, pay, paid)
    - scorecard_url: link to existing public scorecard page

    NEVER returned
    --------------
    - paycheck_code / paycheck_code_maz
    - person_id beyond the URL
    - service_name / route names
    - net_pay (FA->Maz rate, internal margin data)
    - gross_pay, deduction (internal margin columns)
    - other drivers' data
    """
    from sqlalchemy import func as _func

    person = db.query(Person).filter(Person.person_id == person_id).first()
    if not person:
        return JSONResponse({"error": "Driver not found"}, status_code=404)

    first_name = (person.full_name or "").split()[0] if person.full_name else "Driver"

    # -- Scorecard (tier + score) -----------------------------------------------
    week_start = _current_pt_week_start()
    sc = compute_driver_scorecard(person_id, week_start, db)

    # -- Most recent batches for this driver (up to 4 for current + 3 history) --
    recent_batches = (
        db.query(PayrollBatch)
        .join(Ride, Ride.payroll_batch_id == PayrollBatch.payroll_batch_id)
        .filter(Ride.person_id == person_id)
        .group_by(PayrollBatch.payroll_batch_id)
        .order_by(
            PayrollBatch.week_start.desc().nullslast(),
            PayrollBatch.period_start.desc().nullslast(),
            PayrollBatch.payroll_batch_id.desc(),
        )
        .limit(4)
        .all()
    )

    # -- Current week summary ---------------------------------------------------
    current_week: dict = {
        "week_label": "---",
        "trips_completed": 0,
        "driver_pay": 0.00,
        "withheld": False,
        "withheld_amount": 0.00,
        "carried_over": 0.00,
        "paid_this_period": 0.00,
    }

    if recent_batches:
        latest_batch = recent_batches[0]
        batch_rides = (
            db.query(_func.count(Ride.ride_id), _func.sum(Ride.z_rate))
            .filter(
                Ride.payroll_batch_id == latest_batch.payroll_batch_id,
                Ride.person_id == person_id,
            )
            .first()
        )
        trip_count = int(batch_rides[0] or 0)
        driver_pay = float(batch_rides[1] or 0)

        # Carried-over balance from driver_balance for this batch.
        # carried_over = the combined held amount (_build_summary rolls up prior
        # balances into this field, so it already represents the full held sum
        # for this batch cycle -- not just this week's z_rate).
        balance_row = (
            db.query(DriverBalance)
            .filter(
                DriverBalance.payroll_batch_id == latest_batch.payroll_batch_id,
                DriverBalance.person_id == person_id,
            )
            .first()
        )
        carried_over = float(balance_row.carried_over if balance_row else 0)

        # A driver is "withheld" when the system stored a carried_over balance.
        # withheld_amount = carried_over (the full held amount for this batch).
        # paid_this_period = driver_pay (z_rate) when not withheld.
        is_withheld = carried_over > 0
        paid_this_period = round(driver_pay, 2) if not is_withheld else 0.00
        withheld_amount = round(carried_over, 2) if is_withheld else 0.00

        current_week = {
            "week_label": _batch_week_label(latest_batch, db),
            "trips_completed": trip_count,
            "driver_pay": round(driver_pay, 2),
            "withheld": is_withheld,
            "withheld_amount": withheld_amount,
            "carried_over": round(carried_over, 2),
            "paid_this_period": paid_this_period,
        }

    # -- Total held balance (ALL driver_balance rows for this driver) ------------
    held_result = (
        db.query(_func.sum(DriverBalance.carried_over))
        .filter(DriverBalance.person_id == person_id)
        .scalar()
    )
    held_balance = round(float(held_result or 0), 2)

    # -- Recent weeks (last 3 prior batches, skip the current/latest) -----------
    history_batches = recent_batches[1:4]
    recent_weeks: list[dict] = []
    for batch in history_batches:
        row = (
            db.query(_func.count(Ride.ride_id), _func.sum(Ride.z_rate))
            .filter(
                Ride.payroll_batch_id == batch.payroll_batch_id,
                Ride.person_id == person_id,
            )
            .first()
        )
        trips = int(row[0] or 0)
        pay = round(float(row[1] or 0), 2)

        bal_row = (
            db.query(DriverBalance)
            .filter(
                DriverBalance.payroll_batch_id == batch.payroll_batch_id,
                DriverBalance.person_id == person_id,
            )
            .first()
        )
        carried = float(bal_row.carried_over if bal_row else 0)
        # paid = True when no held balance (carried_over == 0 means pay was released)
        paid = carried == 0

        recent_weeks.append({
            "week_label": _batch_week_label(batch, db),
            "trips": trips,
            "pay": pay,
            "paid": paid,
        })

    return JSONResponse({
        "driver": {
            "name": first_name,
            "tier": sc.tier,
            "composite_score": sc.composite_score,
        },
        "current_week": current_week,
        "held_balance": held_balance,
        "recent_weeks": recent_weeks,
        "scorecard_url": f"/driver/{person_id}/scorecard",
    })


@router.get("/api/public/driver/{person_id}/portal")
@_limiter.limit("30/minute")
def public_driver_portal(
    request: Request,
    person_id: int,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Driver self-serve portal endpoint -- unauthenticated, rate-limited.

    Returns pay summary, tier, held balance, and recent history.
    Delegates to _portal_response() for all safe-field logic.
    """
    return _portal_response(person_id, db)
