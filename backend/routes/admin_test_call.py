"""
backend/routes/admin_test_call.py
==================================
Test-phone-call endpoint for end-to-end Twilio verification.

Owner decision 2026-05-28: Phone-ring is the only signal Malik reliably
notices. After Railway env is configured (ADMIN_PHONE, Twilio creds,
BACKEND_PUBLIC_URL), POST this endpoint once to confirm the phone
actually rings + the press-1/2/9 menu reads back.

Routes
------
POST /admin/test-phone-call          [auth required]
    Fires a single alert_admin() invocation with a clearly-labelled
    test message. Returns whether SMS + voice attempts were made.

GET  /admin/test-phone-call/preflight   [auth required]
    Read-only preflight: returns which env vars are missing without
    actually firing a call. Useful for diagnosing setup BEFORE burning
    a Twilio call.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger("zpay.admin_test_call")

router = APIRouter(tags=["admin-test-call"])


# ── Helpers ───────────────────────────────────────────────────────────────────

_REQUIRED_ENV_VARS = (
    "ADMIN_PHONE",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_FROM_NUMBER",
)
_OPTIONAL_ENV_VARS = (
    "BACKEND_PUBLIC_URL",  # required only for the press-1/2/9 voice menu
)


def _env_status() -> dict[str, bool]:
    """Return a dict of var_name → present? for the variables this endpoint needs."""
    return {
        name: bool(os.environ.get(name, "").strip())
        for name in (*_REQUIRED_ENV_VARS, *_OPTIONAL_ENV_VARS)
    }


# ── GET /admin/test-phone-call/preflight ──────────────────────────────────────

@router.get("/test-phone-call/preflight")
def preflight() -> JSONResponse:
    """Check env-var readiness without burning a Twilio call."""
    status = _env_status()
    missing_required = [k for k in _REQUIRED_ENV_VARS if not status.get(k)]
    missing_optional = [k for k in _OPTIONAL_ENV_VARS if not status.get(k)]

    return JSONResponse({
        "ready_to_call": len(missing_required) == 0,
        "missing_required": missing_required,
        "missing_optional_for_menu": missing_optional,
        "env_status": status,
        "note": (
            "ready_to_call=true means a test call will fire. "
            "missing_optional_for_menu means the press-1/2/9 menu will be skipped "
            "but the call itself will still ring and speak the message."
        ),
    })


# ── POST /admin/test-phone-call ───────────────────────────────────────────────

@router.post("/test-phone-call")
def fire_test_call() -> JSONResponse:
    """
    Trigger a single alert_admin() with a test payload.

    The message text is intentionally labelled as a TEST so it cannot be
    confused with a real incident in the timeline or the spoken voice call.
    """
    status = _env_status()
    missing_required = [k for k in _REQUIRED_ENV_VARS if not status.get(k)]
    if missing_required:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "error": "missing required env vars",
                "missing": missing_required,
                "hint": "Run GET /admin/test-phone-call/preflight first.",
            },
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    test_message = (
        "TEST ALERT from Z-Pay. "
        "If you are hearing this, your phone is correctly wired for dispatch alerts. "
        "No action needed."
    )
    spoken_message = (
        "Z-Pay test alert. If you are hearing this, your phone is correctly wired "
        "for dispatch alerts. No action needed. Have a good day."
    )

    try:
        from backend.services.notification_service import alert_admin
        alert_admin(test_message, spoken_message=spoken_message)
        logger.info("[admin_test_call] fired test alert at %s", now_iso)
    except Exception as exc:
        logger.error("[admin_test_call] alert_admin raised: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": f"alert_admin failed: {exc}",
                "fired_at": now_iso,
            },
        )

    # Also write a paper-trail row so the test appears on /ops/live timeline.
    try:
        from backend.services.ops_alert import route_dispatch_alert
        route_dispatch_alert(
            severity="silent",
            title="TEST — Test phone call fired",
            message=f"Manual test alert fired at {now_iso}. "
                    f"Should ring ADMIN_PHONE within ~5 seconds.",
            sms_already_sent=True,
            source="admin_test_call",
        )
    except Exception as exc:
        logger.warning("[admin_test_call] timeline log failed (non-fatal): %s", exc)

    return JSONResponse({
        "ok": True,
        "fired_at": now_iso,
        "message_text": test_message,
        "note": (
            "Phone should ring within ~5 seconds. If it does not, check "
            "Twilio console for delivery errors and confirm ADMIN_PHONE "
            "is in E.164 format (e.g. +12065551234)."
        ),
    })
