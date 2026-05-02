"""
backend/routes/admin_scorecard.py
===================================
Admin + public endpoints for Phase 10 scorecard cron.

Routers
-------
router       → registered under /admin prefix (auth-gated)
public_router → registered at root (no auth — public unsubscribe)

Routes
------
POST /admin/scorecard/send-now          [auth required]
    Manual trigger. Fires run_scorecard_cron() synchronously.
    Returns {"ok": true, "sent": int, "skipped": int, "errors": int, "week_iso": str}.
    Idempotent — drivers who already got a card this week are skipped.

GET  /api/public/scorecard/unsubscribe/{person_id}   [no auth]
    Email unsubscribe link — sets unsubscribed_scorecard=True on alert_profile.
    Returns plain text confirmation.

POST /api/scorecard/unsubscribe/{person_id}          [no auth]
    Driver-facing unsubscribe (frontend page + Twilio STOP webhook).
    Returns {"ok": true, "unsubscribed": true}.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.services.scorecard_cron import opt_out_driver, run_scorecard_cron

logger = logging.getLogger("zpay.admin_scorecard")

# ── Auth-gated router (mounted under /admin) ──────────────────────────────────
router = APIRouter(tags=["admin-scorecard"])

# ── Public router (mounted at root — no auth) ─────────────────────────────────
public_router = APIRouter(tags=["scorecard-public"])


# ═══════════════════════════════════════════════════════════════════════════════
# Auth dependency
# ═══════════════════════════════════════════════════════════════════════════════

def _require_admin(request: Request) -> bool:
    """Verify the request has a valid session cookie."""
    from backend.middleware.auth import COOKIE_NAME, verify_session
    from fastapi import HTTPException

    cookie = request.cookies.get(COOKIE_NAME)
    user = verify_session(cookie) if cookie else None
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# Admin: manual trigger
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/scorecard/send-now")
def trigger_scorecard_send(
    request: Request,
    db: Session = Depends(get_db),
    _auth: bool = Depends(_require_admin),
) -> JSONResponse:
    """Manually fire the weekly scorecard cron.

    Idempotent — drivers who already received a card this week are skipped.

    Returns
    -------
    {
        "ok": true,
        "week_iso": "2026-W18",
        "sent": 12,
        "skipped": 3,
        "errors": 0
    }
    """
    from backend.services.scorecard_cron import _compute_week_iso

    logger.info("[admin-scorecard] Manual send-now triggered")
    week_iso = _compute_week_iso()
    result = run_scorecard_cron(db_override=db)
    return JSONResponse({"ok": True, "week_iso": week_iso, **result})


# ═══════════════════════════════════════════════════════════════════════════════
# Public: email unsubscribe (GET — link from email)
# ═══════════════════════════════════════════════════════════════════════════════

@public_router.get("/api/public/scorecard/unsubscribe/{person_id}")
def email_unsubscribe_get(
    person_id: int,
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    """Handle the unsubscribe link from scorecard emails.

    Covered by /api/public prefix in PUBLIC_PREFIXES — no session required.
    """
    opt_out_driver(person_id=person_id, db=db)
    logger.info("[admin-scorecard] Email unsubscribe person_id=%d", person_id)
    return PlainTextResponse(
        "You've been unsubscribed from weekly scorecard emails. "
        "Contact your dispatcher to re-subscribe.",
        status_code=200,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Public: POST unsubscribe (frontend page + Twilio STOP webhook)
# ═══════════════════════════════════════════════════════════════════════════════

@public_router.post("/api/scorecard/unsubscribe/{person_id}")
def scorecard_unsubscribe_post(
    person_id: int,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Driver unsubscribe — called by frontend and Twilio STOP webhook."""
    opt_out_driver(person_id=person_id, db=db)
    logger.info("[admin-scorecard] POST unsubscribe person_id=%d", person_id)
    return JSONResponse({"ok": True, "unsubscribed": True})
