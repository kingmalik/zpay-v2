"""
Phase 2 — WhatsApp delivery status polling.

Queries Twilio Messages API for the delivery status of WhatsApp messages
sent in the last 30 minutes. Writes notification_event rows for
whatsapp_delivered and whatsapp_failed outcomes. On failure, triggers SMS
fallback via notification_service.

Runs as a scheduled job wired into the trip_monitor scheduler (every 5 min).
Can also be called manually via the /dispatch/monitor/wa-poll endpoint.

Environment variables (all optional — worker no-ops when absent):
  TWILIO_ACCOUNT_SID       — Twilio credentials (shared with notification_service)
  TWILIO_AUTH_TOKEN
  TWILIO_WHATSAPP_NUMBER   — Source WhatsApp number (e.g. +14155238886 or whatsapp:+...)
  OPERATOR_WHATSAPP_PHONE  — Destination number for operator alerts
  WHATSAPP_POLL_WINDOW_MIN — How far back to look for messages (default 30 min)
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger("zpay.whatsapp-poll")

_POLL_WINDOW_MINUTES = int(os.environ.get("WHATSAPP_POLL_WINDOW_MIN", "30"))


def _get_twilio_client():
    """Return a Twilio REST client or None if credentials are absent."""
    sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    if not sid or not token:
        return None
    try:
        from twilio.rest import Client
        return Client(sid, token)
    except ImportError:
        logger.warning("twilio package not installed — WhatsApp polling disabled")
        return None


def _wa_number() -> Optional[str]:
    """Return the configured WhatsApp FROM number in E.164 format (no whatsapp: prefix)."""
    raw = os.environ.get("TWILIO_WHATSAPP_NUMBER", "").strip()
    if not raw:
        return None
    return raw.replace("whatsapp:", "").strip()


def poll_whatsapp_delivery() -> dict:
    """
    Poll Twilio for delivery status of recent WhatsApp messages.

    Returns a summary dict with counts of delivered / failed / pending.
    Side-effects: writes notification_event rows, triggers SMS fallback on failure.
    """
    summary = {
        "checked": 0,
        "delivered": 0,
        "failed": 0,
        "pending": 0,
        "sms_fallbacks": 0,
        "errors": [],
    }

    client = _get_twilio_client()
    if not client:
        logger.debug("[wa-poll] Twilio not configured — skipping")
        return summary

    from_number = _wa_number()
    if not from_number:
        logger.debug("[wa-poll] TWILIO_WHATSAPP_NUMBER not set — skipping")
        return summary

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=_POLL_WINDOW_MINUTES)

    try:
        from_wa = f"whatsapp:{from_number}"
        # Fetch messages sent from our WhatsApp number in the poll window
        messages = client.messages.list(
            from_=from_wa,
            date_sent_after=window_start,
        )
    except Exception as fetch_err:
        logger.warning("[wa-poll] Twilio messages.list failed: %s", fetch_err)
        summary["errors"].append(str(fetch_err))
        return summary

    if not messages:
        logger.debug("[wa-poll] No WhatsApp messages in last %d min", _POLL_WINDOW_MINUTES)
        return summary

    from backend.db import SessionLocal
    from backend.db.models import NotificationEvent, TripNotification

    db = SessionLocal()
    try:
        for msg in messages:
            summary["checked"] += 1
            status = (msg.status or "").lower()  # queued, sent, delivered, read, failed, undelivered

            # Find a notification_event that logged this message being sent
            # We match by SID stored in the payload
            existing_event = (
                db.query(NotificationEvent)
                .filter(
                    NotificationEvent.event_type.in_(["whatsapp_sent", "sms_sent"]),
                )
                .filter(
                    NotificationEvent.payload.op("->>")(  # type: ignore[operator]
                        "whatsapp_sid"
                    )
                    == msg.sid
                )
                .first()
            )

            # If no existing event for this SID, skip — we don't know which notif it belongs to
            if not existing_event:
                if status in ("delivered", "read"):
                    summary["delivered"] += 1
                elif status in ("failed", "undelivered"):
                    summary["failed"] += 1
                else:
                    summary["pending"] += 1
                continue

            notif_id = existing_event.trip_notification_id

            # Check if we already wrote a delivery event for this SID
            already_logged = (
                db.query(NotificationEvent)
                .filter(
                    NotificationEvent.trip_notification_id == notif_id,
                    NotificationEvent.event_type.in_(["whatsapp_delivered", "whatsapp_failed"]),
                    NotificationEvent.payload.op("->>")(  # type: ignore[operator]
                        "whatsapp_sid"
                    )
                    == msg.sid,
                )
                .first()
            )
            if already_logged:
                if status in ("delivered", "read"):
                    summary["delivered"] += 1
                else:
                    summary["pending"] += 1
                continue

            if status in ("delivered", "read"):
                ev = NotificationEvent(
                    trip_notification_id=notif_id,
                    event_type="whatsapp_delivered",
                    payload={
                        "whatsapp_sid": msg.sid,
                        "status": status,
                        "to": msg.to,
                    },
                )
                db.add(ev)
                summary["delivered"] += 1
                logger.info("[wa-poll] WhatsApp delivered — SID %s notif %d", msg.sid, notif_id)

            elif status in ("failed", "undelivered"):
                ev = NotificationEvent(
                    trip_notification_id=notif_id,
                    event_type="whatsapp_failed",
                    payload={
                        "whatsapp_sid": msg.sid,
                        "status": status,
                        "error_code": msg.error_code,
                        "to": msg.to,
                    },
                )
                db.add(ev)
                summary["failed"] += 1
                logger.warning(
                    "[wa-poll] WhatsApp FAILED — SID %s notif %d status %s error_code %s",
                    msg.sid, notif_id, status, msg.error_code,
                )
                # Phase 3: WhatsApp poll detected late/failed → urgent
                try:
                    from backend.services.ops_alert import route_dispatch_alert
                    route_dispatch_alert(
                        "urgent",
                        "WhatsApp delivery failed",
                        f"WhatsApp message SID {msg.sid} to notif {notif_id} "
                        f"failed (status={status}, error_code={msg.error_code}). "
                        f"SMS fallback triggered.",
                    )
                except Exception as _rd_err:
                    logger.warning("[wa-poll] route_dispatch_alert failed: %s", _rd_err)

                # SMS fallback — look up the notification to get the driver phone
                _notif = db.query(TripNotification).filter(
                    TripNotification.id == notif_id
                ).first()
                if _notif:
                    from backend.db.models import Person as _Person
                    _person = db.query(_Person).filter(
                        _Person.person_id == _notif.person_id
                    ).first()
                    if _person and _person.phone:
                        try:
                            from backend.services import notification_service as _notify
                            original_payload = existing_event.payload or {}
                            fallback_msg = original_payload.get(
                                "message",
                                "Action needed on your trip — please check in.",
                            )
                            _notify.send_sms(_person.phone, fallback_msg)
                            _fb_ev = NotificationEvent(
                                trip_notification_id=notif_id,
                                event_type="sms_sent",
                                payload={
                                    "reason": "whatsapp_failed_fallback",
                                    "whatsapp_sid": msg.sid,
                                    "phone": _person.phone,
                                },
                            )
                            db.add(_fb_ev)
                            summary["sms_fallbacks"] += 1
                            logger.info(
                                "[wa-poll] SMS fallback sent to %s for notif %d",
                                _person.phone, notif_id,
                            )
                        except Exception as _sms_err:
                            logger.warning("[wa-poll] SMS fallback failed: %s", _sms_err)
                            summary["errors"].append(f"sms_fallback: {_sms_err}")
            else:
                summary["pending"] += 1

        db.commit()
    except Exception as db_err:
        logger.exception("[wa-poll] DB error: %s", db_err)
        db.rollback()
        summary["errors"].append(str(db_err))
    finally:
        db.close()

    logger.info(
        "[wa-poll] checked=%d delivered=%d failed=%d sms_fallbacks=%d errors=%d",
        summary["checked"], summary["delivered"], summary["failed"],
        summary["sms_fallbacks"], len(summary["errors"]),
    )
    return summary
