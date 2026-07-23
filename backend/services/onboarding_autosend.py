"""
Onboarding step-link autosend — S6 punch-list item 2.

Today an operator manually copies the driver-facing training link
(/training/{token}) and contract link (/contract/{token}) and pastes them
into a text or email by hand once a driver reaches that step. This module
does the same thing automatically, called from
onboarding_automation.check_and_advance().

HARD CONSTRAINT (standing law — driver-facing sends require explicit
approval): every real send here is gated behind ONBOARDING_AUTOSEND=1,
which defaults OFF. With the flag off (the default), calls here always
log-and-return a dry-run action instead of touching Twilio/Gmail — same
shape as onboarding_automation's own dry_run parameter, but this is a
SEPARATE, stricter gate that applies even when a caller passes dry_run=False.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("zpay.onboarding-autosend")

# Matches services/scorecard_card.py's _DEFAULT_BASE / PUBLIC_BASE_URL pattern.
_DEFAULT_BASE = "https://frontend-ruddy-ten-82.vercel.app"


def _autosend_enabled() -> bool:
    return os.environ.get("ONBOARDING_AUTOSEND", "0") == "1"


def _base_url() -> str:
    return os.environ.get("PUBLIC_BASE_URL", os.environ.get("FRONTEND_URL", _DEFAULT_BASE)).rstrip("/")


def build_training_link(invite_token: str) -> str:
    return f"{_base_url()}/training/{invite_token}"


def build_contract_link(invite_token: str) -> str:
    return f"{_base_url()}/contract/{invite_token}"


def _already_sent(record, action_name: str) -> bool:
    """Idempotency guard — check_and_advance can run every compliance-sync
    cycle (every 6h); without this a driver would get re-texted/re-emailed
    the same link forever until they complete the step."""
    log: list[dict] = getattr(record, "automation_log", None) or []
    return any(
        entry.get("action") == action_name and entry.get("executed")
        for entry in log
    )


def send_step_link(
    person,
    record,
    link: str,
    step_name: str,
    action_name: str,
    dry_run: bool,
    now: str,
) -> dict[str, Any] | None:
    """Send (or dry-run-log) a driver-facing onboarding step link via
    email and/or SMS, whichever contact info is on file.

    Returns an automation-log-shaped action dict, or None if there's
    nothing to send to (no email or phone on file) or it was already sent.
    """
    if _already_sent(record, action_name):
        return None

    to_email = (person.email or "").strip()
    to_phone = (person.phone or "").strip()
    if not to_email and not to_phone:
        return None

    driver_first_name = (person.full_name or "Driver").split()[0]
    subject = f"Z-Pay — {step_name} link"
    body = (
        f"Hi {driver_first_name},\n\n"
        f"Please complete your {step_name.lower()} using the link below:\n\n"
        f"{link}\n\n"
        f"Thanks,\nMaz Services"
    )
    sms_body = f"Maz Services: please complete your {step_name.lower()} here: {link}"

    action: dict[str, Any] = {
        "step": step_name,
        "step_name": step_name,
        "action": action_name,
        "description": f"Send {person.full_name or 'driver'} their {step_name.lower()} link",
        "dry_run": dry_run,
        "timestamp": now,
        "data": {"link": link, "to_email": to_email or None, "to_phone": to_phone or None},
        "executed": False,
        "error": None,
    }

    autosend_enabled = _autosend_enabled()
    if dry_run or not autosend_enabled:
        if not autosend_enabled:
            logger.info(
                "[autosend] ONBOARDING_AUTOSEND disabled — would send %s link to person_id=%s: %s",
                step_name, getattr(person, "person_id", "?"), link,
            )
        return action

    errors: list[str] = []
    sent_any = False

    if to_email:
        try:
            from backend.services.email_service import send_plain_email
            send_plain_email(to=to_email, subject=subject, body=body, company="maz")
            sent_any = True
        except Exception as exc:
            errors.append(f"email: {exc}")
            logger.error("[autosend] Failed to email %s link to person_id=%s: %s", step_name, getattr(person, "person_id", "?"), exc)

    if to_phone:
        try:
            from backend.services import notification_service
            notification_service.send_sms(to_phone, sms_body)
            sent_any = True
        except Exception as exc:
            errors.append(f"sms: {exc}")
            logger.error("[autosend] Failed to text %s link to person_id=%s: %s", step_name, getattr(person, "person_id", "?"), exc)

    action["executed"] = sent_any
    if errors:
        action["error"] = "; ".join(errors)

    return action
