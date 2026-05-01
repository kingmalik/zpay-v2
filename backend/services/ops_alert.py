"""
Severity-aware operator alert router — Phase 3.

Severity model:
  LOW      (>30 min to pickup, info-only) → ntfy push only. No voice.
  MED      (<15 min, accept-stage)        → ntfy push only. No voice.
  HIGH     (pickup passed, no progress)   → SMS + ntfy + Twilio voice.
  CRITICAL (both APIs blind / system)     → SMS + ntfy + Twilio voice + WhatsApp.

ntfy plumbing reuses HEALTH_NTFY_TOPIC / HEALTH_NTFY_SERVER already wired for
the health monitor. If those env vars are absent the ntfy leg is silently skipped
(non-fatal — voice/SMS path still runs for HIGH/CRITICAL).

Optionally set OPS_NTFY_TOPIC to route ops alerts to a separate topic.
Falls back to HEALTH_NTFY_TOPIC when unset.
"""

from __future__ import annotations

import logging
import os
from typing import Literal

logger = logging.getLogger("zpay.ops_alert")

Severity = Literal["low", "med", "high", "critical"]

# ntfy priority mapping
_NTFY_PRIORITY: dict[str, str] = {
    "low": "low",
    "med": "default",
    "high": "high",
    "critical": "urgent",
}

# ntfy tags by severity
_NTFY_TAGS: dict[str, str] = {
    "low": "information_source",
    "med": "warning",
    "high": "rotating_light",
    "critical": "sos",
}


def _ntfy_topic() -> str:
    """OPS_NTFY_TOPIC if set, otherwise falls back to HEALTH_NTFY_TOPIC."""
    return (
        os.environ.get("OPS_NTFY_TOPIC", "").strip()
        or os.environ.get("HEALTH_NTFY_TOPIC", "").strip()
    )


def _push_ntfy(title: str, body: str, severity: Severity) -> bool:
    """Send a push notification via ntfy.sh (or self-hosted HEALTH_NTFY_SERVER).

    Returns True if the server responded 2xx, False otherwise (non-fatal).
    """
    topic = _ntfy_topic()
    if not topic:
        logger.debug("[ops_alert] ntfy skipped — OPS_NTFY_TOPIC/HEALTH_NTFY_TOPIC not set")
        return False

    server = os.environ.get("HEALTH_NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    priority = _NTFY_PRIORITY.get(severity, "default")
    tags = _NTFY_TAGS.get(severity, "warning")

    try:
        import requests as _requests  # type: ignore[import]
        r = _requests.post(
            f"{server}/{topic}",
            data=body.encode("utf-8"),
            headers={
                "Title": title,
                "Priority": priority,
                "Tags": tags,
            },
            timeout=5,
        )
        ok = r.status_code < 300
        if not ok:
            logger.warning("[ops_alert] ntfy returned %d for topic=%s", r.status_code, topic)
        return ok
    except Exception as exc:
        logger.warning("[ops_alert] ntfy push failed: %s", exc)
        return False


def route_alert(
    severity: Severity,
    title: str,
    message: str,
    spoken_message: str | None = None,
) -> None:
    """Fan-out an alert to the appropriate channels based on severity.

    LOW  → ntfy push only.
    MED  → ntfy push only.
    HIGH → ntfy push + SMS + Twilio voice call to admin.
    CRITICAL → ntfy push + SMS + Twilio voice + WhatsApp.

    All Twilio operations respect existing quiet-hours gates and dedup logic
    inside notification_service (alert_admin handles both SMS + voice).
    """
    severity = severity.lower()  # type: ignore[assignment]

    logger.info("[ops_alert] severity=%s title=%r", severity, title)

    # ntfy fires for every severity level
    _push_ntfy(title=title, body=message, severity=severity)  # type: ignore[arg-type]

    if severity in ("low", "med"):
        # Notification-only — do NOT wake Malik via voice/SMS
        return

    # HIGH and CRITICAL: alert via SMS + voice
    try:
        from backend.services.notification_service import alert_admin
        alert_admin(message, spoken_message=spoken_message or message)
    except Exception as exc:
        logger.error("[ops_alert] alert_admin (HIGH+) failed: %s", exc)

    if severity == "critical":
        # WhatsApp as final belt-and-suspenders
        try:
            from backend.services.notification_service import send_whatsapp_alert
            send_whatsapp_alert(f"CRITICAL: {title}\n{message}")
        except Exception as exc:
            logger.error("[ops_alert] WhatsApp (CRITICAL) failed: %s", exc)
