"""
Onboarding automation engine for Acumen International (FirstAlt partner).

Each step that can be automated has two modes:
  - dry_run=True  → returns a preview of what would happen, nothing is executed
  - dry_run=False → executes the action for real

Call check_and_advance() from:
  - The compliance sync (after each driver profile update)
  - The /automation/run API endpoint (manual trigger)
  - The /automation/preview endpoint (always dry_run=True)
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("zpay.onboarding-automation")

BRANDON_EMAIL = "Branden.Seeberger@firststudentinc.com"
BRANDON_NAME = "Brandon"


def check_and_advance(record, person, db, dry_run: bool = True) -> list[dict]:
    """
    Inspect the onboarding record + FirstAlt compliance data and advance
    any steps that can be automated.

    Returns a list of action dicts:
      {
        "step": int,
        "step_name": str,
        "action": str,
        "description": str,
        "executed": bool,   # True if actually ran (dry_run=False)
        "dry_run": bool,
        "timestamp": str,
        "data": dict,       # relevant data for preview (email body, etc.)
        "error": str|None,
      }
    """
    actions: list[dict] = []
    compliance: dict = person.firstalt_compliance or {}
    now = datetime.now(timezone.utc).isoformat()

    # ── Step 1: FirstAlt invite — create driver in FirstAlt portal ──────────
    if (record.priority_email_status or "pending") == "pending":
        action = _step1_create_firstalt(person, db, record, dry_run, now)
        if action:
            actions.append(action)

    # ── Step 2: BGC — email Brandon when photo + DL ready ───────────────────
    if (record.bgc_status or "pending") == "pending" and person.firstalt_driver_id:
        action = _step2_bgc_email(person, db, record, compliance, dry_run, now)
        if action:
            actions.append(action)

    # ── Step 5: FirstAlt training — auto-complete when onboarding done ───────
    if (record.training_status or "pending") == "pending" and person.firstalt_driver_id:
        action = _step5_training(person, db, record, compliance, dry_run, now)
        if action:
            actions.append(action)

    # ── Step 6: Documents — auto-complete when all approved ──────────────────
    if (record.files_status or "pending") == "pending" and person.firstalt_driver_id:
        action = _step6_documents(person, db, record, compliance, dry_run, now)
        if action:
            actions.append(action)

    # ── Step 7: Acumen contract — auto-complete when ackDriverAgreement=True ─
    if (record.contract_status or "pending") == "pending" and person.firstalt_driver_id:
        action = _step7_acumen_contract(person, db, record, compliance, dry_run, now)
        if action:
            actions.append(action)

    # Persist log entries if not dry run
    if not dry_run and actions:
        existing_log: list = record.automation_log or []
        existing_log.extend(actions)
        record.automation_log = existing_log
        try:
            db.commit()
        except Exception as exc:
            logger.error("[automation] Failed to persist log: %s", exc)
            db.rollback()

    return actions


# ── Step implementations ─────────────────────────────────────────────────────

def _step1_create_firstalt(person, db, record, dry_run: bool, now: str) -> dict | None:
    name = person.full_name or ""
    email = person.email or ""
    phone = person.phone or ""

    if not name or not email:
        return None  # not enough info yet

    action: dict[str, Any] = {
        "step": 1,
        "step_name": "FirstAlt Invite",
        "action": "create_firstalt_driver",
        "description": f"Create {name} in FirstAlt SP Guardian portal and send them the app invite",
        "dry_run": dry_run,
        "timestamp": now,
        "data": {"name": name, "email": email, "phone": phone},
        "executed": False,
        "error": None,
    }

    if dry_run:
        return action

    try:
        from backend.services import firstalt_service
        result = firstalt_service.create_driver(name=name, email=email, phone=phone)
        if result and result.get("success"):
            driver_id = result.get("driver_id")
            if driver_id:
                person.firstalt_driver_id = int(driver_id)
            record.priority_email_status = "complete"
            db.commit()
            action["executed"] = True
            action["data"]["firstalt_driver_id"] = driver_id
            logger.info("[automation] Step 1 complete for person_id=%d fa_id=%s", person.person_id, driver_id)
        else:
            action["error"] = result.get("error", "Unknown error from FirstAlt") if result else "No response"
    except Exception as exc:
        action["error"] = str(exc)
        logger.error("[automation] Step 1 failed for person_id=%d: %s", person.person_id, exc)

    return action


def _step2_bgc_email(person, db, record, compliance: dict, dry_run: bool, now: str) -> dict | None:
    # Check trigger conditions
    photo_images = _get_photo_images(compliance)
    docs_approved = int(compliance.get("totalOnboardingDocumentsApproved") or 0)
    has_photo = len(photo_images) > 0
    has_docs = docs_approved >= 1
    has_basic_info = bool(person.full_name and person.phone)

    if not (has_photo and has_docs and has_basic_info):
        return None  # not ready yet

    email_body = _build_brandon_email(person)

    action: dict[str, Any] = {
        "step": 2,
        "step_name": "BGC",
        "action": "email_brandon_bgc",
        "description": f"Email Brandon at FirstAlt to run background check for {person.full_name}",
        "dry_run": dry_run,
        "timestamp": now,
        "data": {
            "to": BRANDON_EMAIL,
            "subject": f"New Driver Onboarding — {person.full_name}",
            "body": email_body,
            "trigger_reason": f"Photo uploaded, {docs_approved} doc(s) approved in FirstAlt",
        },
        "executed": False,
        "error": None,
    }

    if dry_run:
        return action

    try:
        from backend.services import notification_service
        notification_service.send_email(
            to=BRANDON_EMAIL,
            subject=f"New Driver Onboarding — {person.full_name}",
            body=email_body,
        )
        record.bgc_status = "sent"
        record.brandon_email_status = "complete"
        db.commit()
        action["executed"] = True
        logger.info("[automation] Step 2 BGC email sent for person_id=%d", person.person_id)
    except Exception as exc:
        action["error"] = str(exc)
        logger.error("[automation] Step 2 email failed for person_id=%d: %s", person.person_id, exc)

    return action


def _step5_training(person, db, record, compliance: dict, dry_run: bool, now: str) -> dict | None:
    onboarding_status = (compliance.get("onBoardingStatus") or "").upper()
    pct = float(compliance.get("driverOnboardingPercentage") or 0)

    # Training is marked done when FirstAlt shows onboarding is complete
    # or when percentage hits 100 (all docs + training done)
    if onboarding_status != "ONBOARDING_DONE" and pct < 100:
        return None

    action: dict[str, Any] = {
        "step": 5,
        "step_name": "FirstAlt Training",
        "action": "mark_training_complete",
        "description": f"FirstAlt shows onboarding {pct:.0f}% — training marked complete",
        "dry_run": dry_run,
        "timestamp": now,
        "data": {"onBoardingStatus": onboarding_status, "driverOnboardingPercentage": pct},
        "executed": False,
        "error": None,
    }

    if dry_run:
        return action

    try:
        record.training_status = "complete"
        db.commit()
        action["executed"] = True
        logger.info("[automation] Step 5 training complete for person_id=%d", person.person_id)
    except Exception as exc:
        action["error"] = str(exc)

    return action


def _step6_documents(person, db, record, compliance: dict, dry_run: bool, now: str) -> dict | None:
    approved = int(compliance.get("totalOnboardingDocumentsApproved") or 0)
    required = int(compliance.get("totalOnboardingDocumentsRequired") or 0)

    if required == 0 or approved < required:
        return None

    action: dict[str, Any] = {
        "step": 6,
        "step_name": "Documents",
        "action": "mark_documents_complete",
        "description": f"All {approved}/{required} documents approved in FirstAlt",
        "dry_run": dry_run,
        "timestamp": now,
        "data": {"approved": approved, "required": required},
        "executed": False,
        "error": None,
    }

    if dry_run:
        return action

    try:
        record.files_status = "complete"
        db.commit()
        action["executed"] = True
        logger.info("[automation] Step 6 docs complete for person_id=%d", person.person_id)
    except Exception as exc:
        action["error"] = str(exc)

    return action


def _step7_acumen_contract(person, db, record, compliance: dict, dry_run: bool, now: str) -> dict | None:
    ack = bool(compliance.get("ackDriverAgreement"))
    agreement_file_id = compliance.get("firstAltAgreementFileId")

    if not ack:
        return None

    action: dict[str, Any] = {
        "step": 7,
        "step_name": "Acumen Contract",
        "action": "mark_contract_signed",
        "description": f"Driver Agreement acknowledged in FirstAlt (file ID: {agreement_file_id})",
        "dry_run": dry_run,
        "timestamp": now,
        "data": {"ackDriverAgreement": ack, "firstAltAgreementFileId": agreement_file_id},
        "executed": False,
        "error": None,
    }

    if dry_run:
        return action

    try:
        record.contract_status = "signed"
        db.commit()
        action["executed"] = True
        logger.info("[automation] Step 7 contract signed for person_id=%d", person.person_id)
    except Exception as exc:
        action["error"] = str(exc)

    return action


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_photo_images(compliance: dict) -> list:
    driver_photo = compliance.get("driverPhoto") or {}
    if isinstance(driver_photo, dict):
        return driver_photo.get("images") or []
    photo_url = compliance.get("photoUrl") or ""
    return [photo_url] if photo_url else []


def _build_brandon_email(person) -> str:
    name = person.full_name or "N/A"
    email = person.email or "N/A"
    phone = person.phone or "N/A"
    address = person.home_address or "N/A"

    vehicle_parts = [
        str(person.vehicle_year) if person.vehicle_year else None,
        person.vehicle_color,
        person.vehicle_make,
        person.vehicle_model,
    ]
    vehicle = " ".join(p for p in vehicle_parts if p) or "N/A"
    plate = person.vehicle_plate or "N/A"

    return f"""Hi {BRANDON_NAME},

Please find the details below for a new driver we are onboarding with Acumen International. Kindly initiate the background check at your earliest convenience.

DRIVER INFORMATION
------------------
Name:           {name}
Email:          {email}
Phone:          {phone}
Address:        {address}

VEHICLE INFORMATION
-------------------
Vehicle:        {vehicle}
License Plate:  {plate}

Please let us know if you need any additional information or documentation.

Thank you,
Acumen International
"""
