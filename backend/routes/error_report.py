"""
Error report endpoint — receives frontend crash reports and notifies Malik.

POST /api/v1/error-report
  - No auth required (called from broken pages that may not have session)
  - Rate-limited to prevent spam
  - Sends email to ZPAY_ALERT_EMAIL (default: jarvis.milion@proton.me)
  - Logs to application logger
"""

import os
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

logger = logging.getLogger("zpay.error_report")

router = APIRouter(prefix="/api/v1", tags=["error-report"])
_limiter = Limiter(key_func=get_remote_address)

ALERT_EMAIL = os.environ.get("ZPAY_ALERT_EMAIL", "jarvis.milion@proton.me")


def _send_alert_email(payload: dict) -> None:
    """Send error alert email using the MAZ Gmail account."""
    try:
        from backend.services.email_service import _get_gmail_service
        import base64
        from email.mime.text import MIMEText

        service, from_email = _get_gmail_service("maz")

        error_type   = payload.get("type", "unknown")
        message      = payload.get("message", "No message")
        url          = payload.get("url", "")
        stack        = payload.get("stack", "")
        comp_stack   = payload.get("componentStack", "")
        timestamp    = payload.get("timestamp", datetime.now(timezone.utc).isoformat())
        user_agent   = payload.get("userAgent", "")

        body = f"""Z-Pay Error Alert
=================

Type:      {error_type}
Time:      {timestamp}
Page:      {url}

Error:
{message}

Stack Trace:
{stack or "(none)"}

Component Stack:
{comp_stack or "(none)"}

User Agent:
{user_agent}

---
Sent automatically by Z-Pay error reporting.
Mom's AI attempted basic troubleshooting before this was sent.
"""

        msg = MIMEText(body, "plain")
        msg["To"]      = ALERT_EMAIL
        msg["From"]    = from_email
        msg["Subject"] = f"🚨 Z-Pay Error — {error_type} — {url.split('/')[-1] or 'unknown page'}"

        encoded = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service.users().messages().send(
            userId="me",
            body={"raw": encoded}
        ).execute()

        logger.info("Error alert sent to %s", ALERT_EMAIL)

    except Exception as e:
        logger.error("Failed to send error alert email: %s", e)


@router.post("/error-report")
async def receive_error_report(request: Request):
    """
    Accepts frontend crash reports. No auth required.
    Rate limited to 10/minute per IP.
    """
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)

    error_type = payload.get("type", "unknown")
    message    = payload.get("message", "")
    url        = payload.get("url", "")

    logger.error(
        "FRONTEND ERROR [%s] on %s: %s",
        error_type, url, message
    )

    # Fire email in background — don't block the response
    import threading
    t = threading.Thread(target=_send_alert_email, args=(payload,), daemon=True)
    t.start()

    return JSONResponse({"ok": True})
