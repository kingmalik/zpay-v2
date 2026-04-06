"""
Twilio notification service — SMS, phone calls, and admin alerts.

Supports MONITOR_DRY_RUN=1 for testing (logs instead of sending).
"""

import os
import re
import logging

logger = logging.getLogger("zpay.notify")

_dry_run = os.environ.get("MONITOR_DRY_RUN", "0") == "1"
_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    if not sid or not token:
        logger.warning("Twilio credentials not configured — notifications disabled")
        return None
    from twilio.rest import Client
    _client = Client(sid, token)
    return _client


def normalize_phone(raw: str | None) -> str | None:
    """
    Normalize a phone number to E.164 format (+1XXXXXXXXXX).
    Returns None if the input can't be parsed.
    """
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw.strip())
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if raw.strip().startswith("+") and len(digits) >= 10:
        return f"+{digits}"
    logger.warning("Cannot normalize phone number: %s", raw)
    return None


def send_sms(to_phone: str, message: str) -> str | None:
    """
    Send an SMS via Twilio.
    Returns the message SID on success, None on failure.
    """
    phone = normalize_phone(to_phone)
    if not phone:
        logger.error("Invalid phone number for SMS: %s", to_phone)
        return None

    if _dry_run:
        logger.info("[DRY RUN] SMS to %s: %s", phone, message)
        return "dry-run-sms"

    client = _get_client()
    if not client:
        return None

    from_number = os.environ.get("TWILIO_FROM_NUMBER", "")
    if not from_number:
        logger.error("TWILIO_FROM_NUMBER not set")
        return None

    try:
        msg = client.messages.create(
            body=message,
            from_=from_number,
            to=phone,
        )
        logger.info("SMS sent to %s — SID: %s", phone, msg.sid)
        return msg.sid
    except Exception as e:
        logger.error("SMS failed to %s: %s", phone, e)
        return None


def make_call(to_phone: str, spoken_message: str) -> str | None:
    """
    Make a phone call via Twilio with a spoken message.
    Returns the call SID on success, None on failure.
    """
    phone = normalize_phone(to_phone)
    if not phone:
        logger.error("Invalid phone number for call: %s", to_phone)
        return None

    if _dry_run:
        logger.info("[DRY RUN] CALL to %s: %s", phone, spoken_message)
        return "dry-run-call"

    client = _get_client()
    if not client:
        return None

    from_number = os.environ.get("TWILIO_FROM_NUMBER", "")
    if not from_number:
        logger.error("TWILIO_FROM_NUMBER not set")
        return None

    # TwiML for the spoken message
    twiml = (
        '<Response>'
        f'<Say voice="Polly.Matthew" language="en-US">{spoken_message}</Say>'
        '<Pause length="1"/>'
        f'<Say voice="Polly.Matthew" language="en-US">{spoken_message}</Say>'
        '</Response>'
    )

    try:
        call = client.calls.create(
            twiml=twiml,
            from_=from_number,
            to=phone,
        )
        logger.info("Call placed to %s — SID: %s", phone, call.sid)
        return call.sid
    except Exception as e:
        logger.error("Call failed to %s: %s", phone, e)
        return None


def alert_admin(message: str) -> None:
    """
    Alert admin (Malik) via SMS + phone call.
    """
    admin_phone = os.environ.get("ADMIN_PHONE", "")
    if not admin_phone:
        logger.error("ADMIN_PHONE not set — cannot send escalation alert")
        return

    # SMS first
    send_sms(admin_phone, f"Z-PAY ALERT: {message}")

    # Then call
    make_call(admin_phone, f"Z-Pay alert. {message}")
