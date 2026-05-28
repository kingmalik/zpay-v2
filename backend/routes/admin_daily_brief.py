"""
backend/routes/admin_daily_brief.py
====================================
Manual triggers + preview endpoints for the daily ops briefs.

Routes (all auth required):
  POST /admin/daily-brief/morning
      Fires today's Game Plan email now. Honors DAILY_BRIEF_ENABLED.

  POST /admin/daily-brief/evening
      Fires today's Recap + tomorrow preview email now. Honors DAILY_BRIEF_ENABLED.

  GET  /admin/daily-brief/preview/morning
      Composes the morning brief WITHOUT sending. Returns subject + body
      so the format can be inspected before the cron job goes live.

  GET  /admin/daily-brief/preview/evening
      Composes the evening brief WITHOUT sending.

Used by:
  - Manual smoke-test from /admin during initial setup
  - The APScheduler cron jobs in trip_monitor.py call the underlying
    service functions directly (not these routes) to avoid HTTP overhead.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.db import get_db

logger = logging.getLogger("zpay.admin_daily_brief")

router = APIRouter(prefix="/daily-brief", tags=["admin-daily-brief"])


# ── POST /admin/daily-brief/morning ───────────────────────────────────────────

@router.post("/morning")
def fire_morning(db: Session = Depends(get_db)) -> JSONResponse:
    """Send the morning Game Plan email now."""
    from backend.services.daily_brief import send_morning_brief
    to = os.environ.get("ADMIN_EMAIL", "").strip() or None
    result = send_morning_brief(to=to)
    return JSONResponse(result)


# ── POST /admin/daily-brief/evening ───────────────────────────────────────────

@router.post("/evening")
def fire_evening(db: Session = Depends(get_db)) -> JSONResponse:
    """Send the evening Recap + tomorrow preview email now."""
    from backend.services.daily_brief import send_evening_brief
    to = os.environ.get("ADMIN_EMAIL", "").strip() or None
    result = send_evening_brief(db=db, to=to)
    return JSONResponse(result)


# ── GET /admin/daily-brief/preview/morning ────────────────────────────────────

@router.get("/preview/morning")
def preview_morning() -> JSONResponse:
    """
    Compose the morning brief WITHOUT sending. Always read-only — no DB
    writes, no Gmail call, no Twilio. Safe to hit repeatedly.
    """
    from backend.services.daily_brief import compose_morning_brief
    subject, body = compose_morning_brief()
    return JSONResponse({
        "subject": subject,
        "body": body,
        "sent": False,
        "note": "Preview only. POST to /admin/daily-brief/morning to actually send.",
    })


# ── GET /admin/daily-brief/preview/evening ────────────────────────────────────

@router.get("/preview/evening")
def preview_evening(db: Session = Depends(get_db)) -> JSONResponse:
    """Compose the evening brief WITHOUT sending."""
    from backend.services.daily_brief import compose_evening_brief
    subject, body = compose_evening_brief(db=db)
    return JSONResponse({
        "subject": subject,
        "body": body,
        "sent": False,
        "note": "Preview only. POST to /admin/daily-brief/evening to actually send.",
    })
