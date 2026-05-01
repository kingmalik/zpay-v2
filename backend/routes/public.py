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
from backend.db.models import Person
from backend.services.driver_scorecard import (
    AXIS_LABELS,
    compute_driver_scorecard,
)

router = APIRouter(tags=["public"])

# ── Rate limiting ──────────────────────────────────────────────────────────────
# Uses the same Limiter instance that app.state.limiter is set to (auth.py).
# The shared app-level exception handler covers 429 formatting.
_limiter = Limiter(key_func=get_remote_address)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_iso_week(w: str):
    """Parse 'YYYY-Www' → Monday date. Mirrors api_data._parse_iso_week."""
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
    Excluded:  weight, weighted_score, normalized_value — internal scoring
               mechanics that drivers don't need and shouldn't see.
    """
    return {
        "label": AXIS_LABELS.get(axis_key, axis_key),
        "value_pct": round(ax.raw_value * 100, 1) if ax.available else None,
        "available": ax.available,
        "sample_size": ax.sample_size,
    }


# ── Route ──────────────────────────────────────────────────────────────────────

def _scorecard_response(person_id: int, db: Session) -> JSONResponse:
    """Core logic, extracted for direct test calls (no HTTP/limiter layer).

    Safe fields returned
    --------------------
    - first_name only (no last name)
    - current_tier + composite_score
    - per-axis breakdown (label + raw percentage) — NO weights
    - last 4 weeks composite trend (week_iso + composite_score + tier)

    Excluded (never leave this function)
    -------------------------------------
    - paycheck_code / paycheck_code_maz
    - person_id / internal DB IDs
    - override events
    - anything money-related
    """
    # ── Driver must exist (active OR inactive — drivers share old links) ───────
    person = db.query(Person).filter(Person.person_id == person_id).first()
    if not person:
        return JSONResponse({"error": "Driver not found"}, status_code=404)

    # First name only — no last name in public response
    first_name = (person.full_name or "").split()[0] if person.full_name else "Driver"

    # ── Current week ───────────────────────────────────────────────────────────
    week_start = _current_pt_week_start()
    sc = compute_driver_scorecard(person_id, week_start, db)

    axes_public = {
        k: _axis_to_public(k, ax)
        for k, ax in sc.axes.items()
        if ax.available
    }

    # ── Last 4 weeks trend ─────────────────────────────────────────────────────
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
    """Driver-facing scorecard endpoint — unauthenticated, rate-limited.

    Delegates to _scorecard_response() which contains all the safe-field logic.
    """
    return _scorecard_response(person_id, db)
