"""
Severity-aware operator alert router — Phase 3.

Legacy trip-monitor severity model (LOW/MED/HIGH/CRITICAL):
  LOW      (>30 min to pickup, info-only) → ntfy push only. No voice.
  MED      (<15 min, accept-stage)        → ntfy push only. No voice.
  HIGH     (pickup passed, no progress)   → SMS + ntfy + Twilio voice.
  CRITICAL (both APIs blind / system)     → SMS + ntfy + Twilio voice + WhatsApp.

Phase 3 dispatch severity model (critical/urgent/normal/silent):
  critical → SMS via Twilio + ntfy + Discord
  urgent   → ntfy + Discord (NO SMS)
  normal   → Discord only
  silent   → Discord only; real-time push (ntfy) skipped during quiet hours (21:00–07:00 PT)

Discord always fires as a paper trail (all tiers).
ntfy fires for critical + urgent + silent-outside-quiet-hours.

ntfy plumbing reuses HEALTH_NTFY_TOPIC / HEALTH_NTFY_SERVER already wired for
the health monitor. If those env vars are absent the ntfy leg is silently skipped
(non-fatal — Discord/SMS path still runs).

Discord plumbing uses DISCORD_WEBHOOK_URL.  If unset the Discord leg is silently
skipped (non-fatal).

Optionally set OPS_NTFY_TOPIC to route ops alerts to a separate topic.
Falls back to HEALTH_NTFY_TOPIC when unset.
"""

from __future__ import annotations

import logging
import os
from typing import Literal

logger = logging.getLogger("zpay.ops_alert")

Severity = Literal["low", "med", "high", "critical"]

# Phase 3 dispatch severity tier
DispatchSeverity = Literal["critical", "urgent", "normal", "silent"]

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


def _push_ntfy(
    title: str,
    body: str,
    severity: Severity,
    ntfy_priority: str | None = None,
    ntfy_tags: str | None = None,
) -> bool:
    """Send a push notification via ntfy.sh (or self-hosted HEALTH_NTFY_SERVER).

    `ntfy_priority` and `ntfy_tags` override the severity-derived defaults when
    provided (used by Phase 3 dispatch severity tiers which have their own mapping).

    Returns True if the server responded 2xx, False otherwise (non-fatal).
    """
    topic = _ntfy_topic()
    if not topic:
        logger.debug("[ops_alert] ntfy skipped — OPS_NTFY_TOPIC/HEALTH_NTFY_TOPIC not set")
        return False

    server = os.environ.get("HEALTH_NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    priority = ntfy_priority if ntfy_priority is not None else _NTFY_PRIORITY.get(severity, "default")
    tags = ntfy_tags if ntfy_tags is not None else _NTFY_TAGS.get(severity, "warning")

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


# ── Phase 3: Dispatch severity tier routing ───────────────────────────────────

# ntfy priority for dispatch severity tiers
_DISPATCH_NTFY_PRIORITY: dict[str, str] = {
    "critical": "urgent",
    "urgent": "high",
    "normal": "default",
    "silent": "low",
}

# ntfy tags for dispatch severity tiers
_DISPATCH_NTFY_TAGS: dict[str, str] = {
    "critical": "sos,rotating_light",
    "urgent": "rotating_light",
    "normal": "bell",
    "silent": "mute",
}


def _push_discord(title: str, message: str, severity: DispatchSeverity) -> bool:
    """POST a message to the configured Discord webhook URL.

    Uses DISCORD_WEBHOOK_URL env var. Non-fatal — returns False and logs a
    warning if the webhook is not configured or the request fails.
    """
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url:
        logger.debug("[ops_alert] Discord skipped — DISCORD_WEBHOOK_URL not set")
        return False

    # Emoji prefix by tier so messages are scannable in the channel
    _prefix: dict[str, str] = {
        "critical": "[CRITICAL]",
        "urgent": "[URGENT]",
        "normal": "[NORMAL]",
        "silent": "[SILENT]",
    }
    prefix = _prefix.get(severity, "[INFO]")
    content = f"**{prefix} {title}**\n{message}"

    try:
        import urllib.request
        import json as _json
        payload = _json.dumps({"content": content}).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            ok = resp.status < 300
        if not ok:
            logger.warning("[ops_alert] Discord webhook returned non-2xx for severity=%s", severity)
        return ok
    except Exception as exc:
        logger.warning("[ops_alert] Discord push failed: %s", exc)
        return False


def route_dispatch_alert(
    severity: DispatchSeverity,
    title: str,
    message: str,
    spoken_message: str | None = None,
    sms_already_sent: bool = False,
) -> None:
    """Fan-out a Phase 3 dispatch alert based on severity tier.

    Routing matrix:
      critical → SMS via Twilio + ntfy + Discord
      urgent   → ntfy + Discord (NO SMS)
      normal   → Discord only
      silent   → Discord only; ntfy push skipped during quiet hours (21:00–07:00 PT)

    Discord always fires — it is the permanent paper trail regardless of tier
    or time of day.  ntfy and SMS are the real-time wake-up channels.

    sms_already_sent: set True when the call site already called alert_admin /
    notify.alert_admin before route_dispatch_alert so that critical severity
    does not fire a second duplicate SMS.  This is the case in trip_monitor
    where existing alert_admin calls predate Phase 3 and must be preserved
    for backward-compatibility with tests and monitoring guarantees.
    """
    sev = (severity or "normal").lower()  # type: ignore[assignment]

    logger.info("[ops_alert] dispatch severity=%s title=%r", sev, title)

    # Discord always fires (paper trail)
    _push_discord(title=title, message=message, severity=sev)  # type: ignore[arg-type]

    # Determine whether ntfy should fire
    _push_ntfy_now = False
    if sev in ("critical", "urgent"):
        _push_ntfy_now = True
    elif sev == "silent":
        # ntfy fires for silent only outside quiet hours
        from backend.services.quiet_hours import in_quiet_hours
        _push_ntfy_now = not in_quiet_hours()
    # normal → no ntfy (Discord-only)

    if _push_ntfy_now:
        _push_ntfy(
            title=title,
            body=message,
            severity=sev,  # type: ignore[arg-type]
            ntfy_priority=_DISPATCH_NTFY_PRIORITY.get(sev, "default"),
            ntfy_tags=_DISPATCH_NTFY_TAGS.get(sev, "bell"),
        )

    # SMS only for critical — and only when the caller hasn't already sent it
    if sev == "critical" and not sms_already_sent:
        try:
            from backend.services.notification_service import alert_admin
            alert_admin(message, spoken_message=spoken_message or message)
        except Exception as exc:
            logger.error("[ops_alert] alert_admin (critical) failed: %s", exc)
