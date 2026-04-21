import os
import logging
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

logger = logging.getLogger("zpay.whatsapp")

_dry_run_val = os.environ.get("MONITOR_DRY_RUN", "0").lower().strip()
_dry_run = _dry_run_val in ("1", "true", "yes")

# Disabled for process lifetime if WhatsApp sender is not configured or returns 400
_whatsapp_disabled: bool = not bool(os.environ.get("TWILIO_WHATSAPP_NUMBER", "").strip())


def _get_client():
    sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    if not sid or not token:
        logger.warning("Twilio credentials not configured — WhatsApp disabled")
        return None
    from twilio.rest import Client
    return Client(sid, token)


def send_whatsapp(to: str, message: str) -> str | None:
    global _whatsapp_disabled

    if _whatsapp_disabled:
        logger.debug("WhatsApp disabled (no sender configured) — skipping message to %s", to)
        return None

    if not to:
        logger.error("WhatsApp send: no recipient")
        return None

    if _dry_run:
        logger.info("[DRY RUN] WhatsApp to %s: %s", to, message[:120])
        return "dry-run-wa"

    from_number = os.environ.get("TWILIO_WHATSAPP_NUMBER", "")
    if not from_number:
        logger.debug("TWILIO_WHATSAPP_NUMBER not set — WhatsApp disabled")
        _whatsapp_disabled = True
        return None

    from_wa = f"whatsapp:{from_number}" if not from_number.startswith("whatsapp:") else from_number
    to_wa = f"whatsapp:{to}" if not to.startswith("whatsapp:") else to

    client = _get_client()
    if not client:
        return None

    try:
        msg = client.messages.create(body=message, from_=from_wa, to=to_wa)
        logger.info("WhatsApp sent to %s — SID: %s", to, msg.sid)
        return msg.sid
    except Exception as e:
        err_str = str(e)
        if "could not find a Channel" in err_str or "400" in err_str:
            _whatsapp_disabled = True
            logger.warning(
                "WhatsApp sender not linked (400 — could not find a Channel) — "
                "disabling WhatsApp for this process. Set up a WhatsApp sender in Twilio to restore."
            )
        else:
            logger.error("WhatsApp failed to %s: %s", to, e)
        return None


def parse_incoming(form_data: dict) -> dict:
    return {
        "from": form_data.get("From", "").replace("whatsapp:", ""),
        "body": (form_data.get("Body") or "").strip(),
        "profile_name": form_data.get("ProfileName", ""),
        "message_sid": form_data.get("MessageSid", ""),
    }


def build_bot_reply(body: str, from_phone: str = "") -> str | None:
    cmd = body.lower().strip()

    if cmd == "help":
        return (
            "Z-Pay WhatsApp Bot\n\n"
            "Commands:\n"
            "• *status* — today's ride summary\n"
            "• *drivers* — unassigned rides count\n"
            "• *help* — this list\n\n"
            "To report a pay issue, just describe it (e.g. 'wrong pay', 'missing ride', 'rate issue')."
        )

    if cmd == "status":
        return _status_reply()

    if cmd == "drivers":
        return _drivers_reply()

    # Check for dispute patterns before falling through
    from backend.services.dispute_service import detect_dispute_type, create_dispute
    dispute_type = detect_dispute_type(body)
    if dispute_type:
        try:
            record = create_dispute(from_phone, body, dispute_type)
            label = dispute_type.replace("_", " ").title()
            return (
                f"✅ *Dispute Logged — {label}*\n\n"
                f"Reference ID: #{record['id']}\n"
                f"Message: \"{body[:120]}\"\n\n"
                f"Malik has been notified and will review this shortly."
            )
        except Exception as e:
            logger.error("Dispute creation failed: %s", e)
            return "We received your message but couldn't log it. Please try again or call directly."

    return None


def _status_reply() -> str:
    try:
        from backend.db import SessionLocal
        from backend.db.models import Ride, PayrollBatch
        from sqlalchemy import func

        tz = ZoneInfo(os.environ.get("MONITOR_TIMEZONE", "America/Los_Angeles"))
        today = datetime.now(tz).date()

        db = SessionLocal()
        try:
            ride_count = (
                db.query(func.count(Ride.ride_id))
                .join(PayrollBatch, Ride.payroll_batch_id == PayrollBatch.payroll_batch_id)
                .filter(PayrollBatch.period_start <= today, PayrollBatch.period_end >= today)
                .scalar()
            ) or 0
            return f"*Z-Pay Status — {today}*\n\nTotal rides in active batch: {ride_count}"
        finally:
            db.close()
    except Exception as e:
        logger.error("WhatsApp status reply failed: %s", e)
        return "Status unavailable — check Railway logs."


def _drivers_reply() -> str:
    try:
        from backend.services.firstalt_service import get_trips
        from backend.services.everdriven_service import get_runs
        from backend.db import SessionLocal
        from backend.db.models import Person
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(os.environ.get("MONITOR_TIMEZONE", "America/Los_Angeles"))
        today = datetime.now(tz).date()

        unassigned = 0
        try:
            fa_trips = get_trips(today)
            unassigned += sum(
                1 for t in fa_trips
                if not t.get("driverId")
            )
        except Exception:
            pass
        try:
            ed_runs = get_runs(today)
            unassigned += sum(
                1 for r in ed_runs
                if not r.get("driverGUID") and not r.get("driverId")
            )
        except Exception:
            pass

        return f"*Unassigned Rides — {today}*\n\n{unassigned} ride(s) need a driver."
    except Exception as e:
        logger.error("WhatsApp drivers reply failed: %s", e)
        return "Driver data unavailable — check Railway logs."
