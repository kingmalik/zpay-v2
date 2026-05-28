"""
Severity-aware operator alert router — Phase 3.

Legacy trip-monitor severity model (LOW/MED/HIGH/CRITICAL):
  LOW      (>30 min to pickup, info-only) → ntfy push only. No voice.
  MED      (<15 min, accept-stage)        → ntfy push only. No voice.
  HIGH     (pickup passed, no progress)   → SMS + ntfy + Twilio voice.
  CRITICAL (both APIs blind / system)     → SMS + ntfy + Twilio voice + WhatsApp.

Phase 3 dispatch severity model (critical/urgent/normal/silent):
  critical → SMS via Twilio + ntfy + internal ops_event_log
  urgent   → ntfy + internal ops_event_log (NO SMS)
  normal   → internal ops_event_log only
  silent   → internal ops_event_log only; ntfy push skipped during
             quiet hours (21:00–07:00 PT)

The internal `ops_event_log` table is the paper trail for every alert
regardless of severity tier. It replaced the Discord webhook on 2026-05-28
per owner decision — no outside chat apps.  The /ops/live page reads this
table to render a scrollable event timeline.

ntfy fires for critical + urgent + silent-outside-quiet-hours.

ntfy plumbing reuses HEALTH_NTFY_TOPIC / HEALTH_NTFY_SERVER already wired for
the health monitor. If those env vars are absent the ntfy leg is silently skipped
(non-fatal — DB log + SMS path still runs).

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


def _log_event(
    severity: DispatchSeverity,
    title: str,
    message: str,
    trip_id: str | None = None,
    notif_id: int | None = None,
    source: str | None = None,
) -> bool:
    """Persist the alert to ops_event_log so /ops/live can render a timeline.

    Replaces the prior Discord webhook (removed 2026-05-28). Non-fatal — logs
    a warning and returns False if the DB write fails so it never blocks the
    real-time alert path (ntfy/SMS).
    """
    try:
        from backend.db import SessionLocal
        from backend.db.models import OpsEventLog

        with SessionLocal() as db:
            row = OpsEventLog(
                severity=str(severity),
                title=title,
                message=message,
                trip_id=trip_id,
                notif_id=notif_id,
                source=source or "ops_alert",
            )
            db.add(row)
            db.commit()
        return True
    except Exception as exc:
        logger.warning("[ops_alert] ops_event_log write failed: %s", exc)
        return False


def route_dispatch_alert(
    severity: DispatchSeverity,
    title: str,
    message: str,
    spoken_message: str | None = None,
    sms_already_sent: bool = False,
    notif_id: int | None = None,
    trip_id: str | None = None,
    source: str | None = None,
) -> None:
    """Fan-out a Phase 3 dispatch alert based on severity tier.

    Routing matrix:
      critical → SMS via Twilio + ntfy + ops_event_log
      urgent   → ntfy + ops_event_log (NO SMS)
      normal   → ops_event_log only
      silent   → ops_event_log only; ntfy push skipped during quiet hours
                 (21:00–07:00 PT)

    The internal ops_event_log table always fires — it is the permanent
    paper trail regardless of tier or time of day, and replaces the prior
    Discord webhook (removed 2026-05-28).  ntfy and SMS are the real-time
    wake-up channels.

    sms_already_sent: set True when the call site already called alert_admin /
    notify.alert_admin before route_dispatch_alert so that critical severity
    does not fire a second duplicate SMS.  This is the case in trip_monitor
    where existing alert_admin calls predate Phase 3 and must be preserved
    for backward-compatibility with tests and monitoring guarantees.

    notif_id: when provided, passed to alert_admin so the outbound voice call
    includes the Gather press-1/2/9 menu (requires BACKEND_PUBLIC_URL). Also
    persisted on the ops_event_log row for cross-reference.

    trip_id: free-text trip identifier (FA dispatch ID, ED ride ID, etc.) —
    persisted on ops_event_log only. Pass None for system-level events.

    source: free-text origin label (e.g. "trip_monitor", "dispatch_agent",
    "manual_test"). Defaults to "ops_alert" inside _log_event when unset.
    """
    sev = (severity or "normal").lower()  # type: ignore[assignment]

    logger.info("[ops_alert] dispatch severity=%s title=%r", sev, title)

    # Paper trail always fires (replaces Discord — internal-only).
    # Wrapped defensively: a DB outage must NEVER block the real-time
    # alert path (ntfy/SMS). _log_event already swallows its own exceptions,
    # this outer guard is belt-and-suspenders for unexpected re-raises.
    try:
        _log_event(
            severity=sev,  # type: ignore[arg-type]
            title=title,
            message=message,
            trip_id=trip_id,
            notif_id=notif_id,
            source=source,
        )
    except Exception as exc:
        logger.warning("[ops_alert] paper-trail write surfaced exception: %s", exc)

    # Determine whether ntfy should fire
    _push_ntfy_now = False
    if sev in ("critical", "urgent"):
        _push_ntfy_now = True
    elif sev == "silent":
        # ntfy fires for silent only outside quiet hours
        from backend.services.quiet_hours import in_quiet_hours
        _push_ntfy_now = not in_quiet_hours()
    # normal → no ntfy (DB-log only)

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
            alert_admin(message, spoken_message=spoken_message or message, notif_id=notif_id)
        except Exception as exc:
            logger.error("[ops_alert] alert_admin (critical) failed: %s", exc)
