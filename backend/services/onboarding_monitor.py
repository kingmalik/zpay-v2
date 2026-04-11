"""
Onboarding progress monitor — polls FirstAlt for driver document/status updates
and auto-triggers next onboarding steps when conditions are met.

APScheduler background job (same pattern as trip_monitor.py).
Runs every 30 minutes while MONITOR_ENABLED=1 is set.

Auto-trigger chain:
    1. consent sent    → FirstAlt profile exists → bgc_status = 'manual'
    2. consent signed  → priority_email pending  → auto-email Priority contact
    3. priority done   → brandon_email pending   → auto-email Brandon at FirstAlt
    4. brandon done +
       bgc complete +
       drug test complete +
       files complete +
       training complete  → contract pending → auto-send Adobe Sign contract
    5. all steps done  → completed_at = now()
"""

import os
import logging
import base64
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders

logger = logging.getLogger("zpay.onboarding-monitor")

_scheduler = None
_last_run_info: dict = {"last_run": None, "summary": None, "error": None}


# ── Email helpers ─────────────────────────────────────────────────────────────

def _send_simple_email(
    to_email: str,
    subject: str,
    body: str,
    company: str = "acumen",
) -> None:
    """
    Send a plain-text email via Gmail API (Acumen account).
    Mirrors the pattern in email_service.py / onboarding.py.
    Raises on failure so caller can catch and log.
    """
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request as GRequest
    from googleapiclient.discovery import build

    client_id = os.environ.get("GMAIL_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET", "").strip()
    refresh_token = os.environ.get("GMAIL_REFRESH_TOKEN_ACUMEN", "").strip()
    from_email = os.environ.get("GMAIL_USER_ACUMEN", "").strip()

    if not all([client_id, client_secret, refresh_token, from_email]):
        raise ValueError(
            "Gmail Acumen credentials not fully configured. "
            "Check GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, "
            "GMAIL_REFRESH_TOKEN_ACUMEN, GMAIL_USER_ACUMEN."
        )

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/gmail.send"],
    )
    creds.refresh(GRequest())
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    msg = MIMEMultipart("alternative")
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    service.users().messages().send(userId="me", body={"raw": raw}).execute()


def _auto_send_priority_email(rec, driver_name: str) -> bool:
    """
    Auto-send the Priority transport notification email.
    Returns True on success, False on failure.
    """
    to_email = os.environ.get("PRIORITY_EMAIL", "").strip()
    if not to_email:
        logger.warning(
            "[onboarding-monitor] PRIORITY_EMAIL not set — cannot auto-send Priority email "
            "for onboarding_id=%d",
            rec.id,
        )
        return False

    subject = f"New Driver Onboarding - {driver_name}"
    body = (
        f"Hi,\n\n"
        f"Driver {driver_name} has completed consent and is progressing through onboarding. "
        f"Please prepare route assignment.\n\n"
        f"— Z-Pay Onboarding System"
    )

    try:
        _send_simple_email(to_email=to_email, subject=subject, body=body)
        logger.info(
            "[onboarding-monitor] Priority email sent to %s for driver %s (onboarding_id=%d)",
            to_email,
            driver_name,
            rec.id,
        )
        return True
    except Exception as exc:
        logger.error(
            "[onboarding-monitor] Failed to send Priority email for onboarding_id=%d: %s",
            rec.id,
            exc,
        )
        return False


def _auto_send_brandon_email(rec, driver_name: str) -> bool:
    """
    Auto-send the Brandon (FirstAlt) notification email.
    Returns True on success, False on failure.
    """
    to_email = os.environ.get("BRANDON_EMAIL", "").strip()
    if not to_email:
        logger.warning(
            "[onboarding-monitor] BRANDON_EMAIL not set — cannot auto-send Brandon email "
            "for onboarding_id=%d",
            rec.id,
        )
        return False

    subject = f"New Driver Ready - {driver_name}"
    body = (
        f"Hi Brandon,\n\n"
        f"Driver {driver_name} has completed the consent and priority notification steps. "
        f"Please proceed with FirstAlt setup.\n\n"
        f"— Z-Pay Onboarding System"
    )

    try:
        _send_simple_email(to_email=to_email, subject=subject, body=body)
        logger.info(
            "[onboarding-monitor] Brandon email sent to %s for driver %s (onboarding_id=%d)",
            to_email,
            driver_name,
            rec.id,
        )
        return True
    except Exception as exc:
        logger.error(
            "[onboarding-monitor] Failed to send Brandon email for onboarding_id=%d: %s",
            rec.id,
            exc,
        )
        return False


def _auto_send_donna_email(rec, driver_name: str, driver_phone: str) -> bool:
    """
    Auto-send a notification to Donna at Concentra so she knows a new driver is coming in.
    Triggered after BGC is cleared (bgc_status transitions from 'pending' to 'manual').
    Returns True on success, False on failure.
    """
    to_email = os.environ.get("DONNA_EMAIL", "").strip()
    if not to_email:
        logger.warning(
            "[onboarding-monitor] DONNA_EMAIL not set — cannot auto-notify Concentra "
            "for onboarding_id=%d",
            rec.id,
        )
        return False

    subject = f"New Driver Drug Test — {driver_name}"
    body = (
        f"Hi Donna,\n\n"
        f"A new MAZ Services driver ({driver_name}, {driver_phone or 'no phone on file'}) "
        f"will be coming in for their drug test. Please expect them within the next few days.\n\n"
        f"Thank you."
    )

    try:
        _send_simple_email(to_email=to_email, subject=subject, body=body)
        logger.info(
            "[onboarding-monitor] Donna/Concentra email sent to %s for driver %s (onboarding_id=%d)",
            to_email,
            driver_name,
            rec.id,
        )
        return True
    except Exception as exc:
        logger.error(
            "[onboarding-monitor] Failed to send Donna email for onboarding_id=%d: %s",
            rec.id,
            exc,
        )
        return False


def _auto_send_contract(rec, person) -> bool:
    """
    Auto-send the Acumen contract via Adobe Sign.
    Returns True on success, False on failure.
    """
    adobe_key = os.environ.get("ADOBE_SIGN_INTEGRATION_KEY", "").strip()
    if not adobe_key:
        logger.warning(
            "[onboarding-monitor] ADOBE_SIGN_INTEGRATION_KEY not set — skipping auto-contract "
            "for onboarding_id=%d",
            rec.id,
        )
        return False

    if not person or not person.email:
        logger.warning(
            "[onboarding-monitor] Driver has no email — cannot auto-send contract "
            "for onboarding_id=%d",
            rec.id,
        )
        return False

    try:
        from backend.services import adobe_sign
        from backend.db.models import OnboardingDocument

        result = adobe_sign.send_envelope(
            signer_email=person.email,
            signer_name=person.full_name,
            doc_type="acumen_contract",
        )
        envelope_id = result.get("id")
        now = datetime.now(timezone.utc)

        rec.contract_envelope_id = envelope_id
        rec.contract_status = "sent"

        logger.info(
            "[onboarding-monitor] Contract sent via Adobe Sign — onboarding_id=%d envelope_id=%s",
            rec.id,
            envelope_id,
        )
        return True

    except Exception as exc:
        logger.error(
            "[onboarding-monitor] Failed to auto-send contract for onboarding_id=%d: %s",
            rec.id,
            exc,
        )
        return False


# ── All-complete check ────────────────────────────────────────────────────────

def _check_all_complete(rec) -> bool:
    """Return True if every step is in a terminal state."""
    terminal = {"complete", "signed", "manual", "skipped"}
    steps = [
        rec.consent_status,
        rec.priority_email_status,
        rec.brandon_email_status,
        rec.bgc_status,
        rec.drug_test_status,
        rec.contract_status,
        rec.files_status,
        rec.paychex_status,
        rec.training_status if hasattr(rec, "training_status") else "pending",
    ]
    return all(s in terminal for s in steps)


# ── Main monitor cycle ────────────────────────────────────────────────────────

def run_onboarding_cycle() -> dict:
    """
    Execute one onboarding monitor cycle.
    Called by APScheduler every 30 minutes.
    Returns a summary dict.
    """
    from backend.db import SessionLocal
    from backend.db.models import OnboardingRecord, Person

    db = SessionLocal()
    summary = {
        "records_checked": 0,
        "bgc_marked": 0,
        "training_auto_marked": 0,
        "donna_emails_sent": 0,
        "priority_emails_sent": 0,
        "brandon_emails_sent": 0,
        "contracts_sent": 0,
        "completed": 0,
        "errors": [],
    }

    try:
        # Get all active (incomplete) onboarding records
        active_records = (
            db.query(OnboardingRecord)
            .filter(OnboardingRecord.completed_at.is_(None))
            .all()
        )

        summary["records_checked"] = len(active_records)
        logger.info("[onboarding-monitor] Checking %d active onboarding records", len(active_records))

        for rec in active_records:
            try:
                person = db.query(Person).filter(Person.person_id == rec.person_id).first()
                driver_name = person.full_name if person else f"Driver #{rec.person_id}"
                driver_phone = person.phone if person else ""

                # ── Check 1: BGC + Training — poll FirstAlt profile ──
                bgc_just_cleared = False
                if person and person.firstalt_driver_id and (
                    rec.bgc_status == "pending"
                    or (hasattr(rec, "training_status") and rec.training_status == "pending")
                ):
                    try:
                        from backend.services import firstalt_service
                        profile = firstalt_service.get_driver_profile(person.firstalt_driver_id)
                        if profile:
                            # BGC: if profile exists at all, mark as manual (needs human review)
                            if rec.bgc_status == "pending":
                                rec.bgc_status = "manual"
                                bgc_just_cleared = True
                                summary["bgc_marked"] += 1
                                logger.info(
                                    "[onboarding-monitor] BGC marked manual — onboarding_id=%d driver=%s",
                                    rec.id,
                                    driver_name,
                                )

                            # Training: look for any training/class completion field in the profile
                            if hasattr(rec, "training_status") and rec.training_status == "pending":
                                training_fields = [
                                    "trainingCompleted",
                                    "training_completed",
                                    "classCompleted",
                                    "class_completed",
                                    "trainingStatus",
                                    "training_status",
                                    "orientationCompleted",
                                    "orientation_completed",
                                ]
                                training_done = False
                                for field in training_fields:
                                    val = profile.get(field)
                                    if val in (True, "complete", "completed", "COMPLETED", "passed", "PASSED"):
                                        training_done = True
                                        logger.info(
                                            "[onboarding-monitor] Training auto-detected via profile field '%s'=%r "
                                            "for onboarding_id=%d driver=%s",
                                            field,
                                            val,
                                            rec.id,
                                            driver_name,
                                        )
                                        break

                                if training_done:
                                    rec.training_status = "complete"
                                    summary["training_auto_marked"] += 1
                                else:
                                    # No clear training field found — log and leave as 'manual' for admin
                                    logger.info(
                                        "[onboarding-monitor] No training completion field found in FirstAlt profile "
                                        "for onboarding_id=%d driver=%s — leaving training_status as 'manual' for admin",
                                        rec.id,
                                        driver_name,
                                    )
                                    rec.training_status = "manual"

                    except Exception as exc:
                        logger.warning(
                            "[onboarding-monitor] FirstAlt profile fetch failed for onboarding_id=%d: %s",
                            rec.id,
                            exc,
                        )

                # ── After BGC cleared → auto-notify Donna at Concentra ──
                # Only fires in the same cycle that BGC transitions to 'manual',
                # so it won't re-send on subsequent monitor cycles.
                if bgc_just_cleared:
                    donna_ok = _auto_send_donna_email(rec, driver_name, driver_phone)
                    if donna_ok:
                        summary["donna_emails_sent"] += 1

                # ── Check 2: Consent signed → auto-send Priority email ──
                if (
                    rec.consent_status in ("signed", "complete")
                    and rec.priority_email_status == "pending"
                ):
                    success = _auto_send_priority_email(rec, driver_name)
                    if success:
                        rec.priority_email_status = "complete"
                        summary["priority_emails_sent"] += 1
                    else:
                        rec.priority_email_status = "manual"

                # ── Check 3: Priority done → auto-send Brandon email ──
                if (
                    rec.priority_email_status in ("complete", "manual")
                    and rec.brandon_email_status == "pending"
                ):
                    # Only auto-send if priority was actually completed (not fallen-back to manual)
                    if rec.priority_email_status == "complete":
                        success = _auto_send_brandon_email(rec, driver_name)
                        if success:
                            rec.brandon_email_status = "complete"
                            summary["brandon_emails_sent"] += 1
                        else:
                            rec.brandon_email_status = "manual"

                # ── Check 4: All clearances done → auto-send contract ──
                # Requires: brandon email complete, BGC clear, drug test clear,
                # files uploaded, AND training complete before contract fires.
                _bgc_clear = rec.bgc_status in ("complete", "manual", "skipped")
                _drug_clear = rec.drug_test_status == "complete"
                _files_clear = rec.files_status == "complete"
                _training_clear = (
                    (rec.training_status if hasattr(rec, "training_status") else "pending")
                    == "complete"
                )
                if (
                    rec.brandon_email_status == "complete"
                    and _bgc_clear
                    and _drug_clear
                    and _files_clear
                    and _training_clear
                    and rec.contract_status == "pending"
                ):
                    success = _auto_send_contract(rec, person)
                    if success:
                        summary["contracts_sent"] += 1
                    else:
                        # Leave contract_status as-is on failure so it retries next cycle
                        pass
                elif rec.contract_status == "pending" and not (
                    rec.brandon_email_status == "complete"
                    and _bgc_clear
                    and _drug_clear
                    and _files_clear
                    and _training_clear
                ):
                    logger.debug(
                        "[onboarding-monitor] Contract not yet ready for onboarding_id=%d — "
                        "brandon=%s bgc=%s drug_test=%s files=%s training=%s",
                        rec.id,
                        rec.brandon_email_status,
                        rec.bgc_status,
                        rec.drug_test_status,
                        rec.files_status,
                        rec.training_status if hasattr(rec, "training_status") else "pending",
                    )

                # ── Check 5: All steps complete? ──
                if _check_all_complete(rec):
                    rec.completed_at = datetime.now(timezone.utc)
                    summary["completed"] += 1
                    logger.info(
                        "[onboarding-monitor] Onboarding COMPLETE — onboarding_id=%d driver=%s",
                        rec.id,
                        driver_name,
                    )

            except Exception as exc:
                logger.error(
                    "[onboarding-monitor] Error processing onboarding_id=%d: %s",
                    rec.id,
                    exc,
                )
                summary["errors"].append(f"onboarding_id={rec.id}: {exc}")

        db.commit()

        logger.info(
            "[onboarding-monitor] Cycle complete — checked=%d bgc=%d training_auto=%d donna=%d "
            "priority=%d brandon=%d contracts=%d completed=%d errors=%d",
            summary["records_checked"],
            summary["bgc_marked"],
            summary["training_auto_marked"],
            summary["donna_emails_sent"],
            summary["priority_emails_sent"],
            summary["brandon_emails_sent"],
            summary["contracts_sent"],
            summary["completed"],
            len(summary["errors"]),
        )

    except Exception as exc:
        logger.exception("[onboarding-monitor] Cycle failed: %s", exc)
        summary["errors"].append(str(exc))
        db.rollback()
    finally:
        db.close()

    _last_run_info["last_run"] = datetime.now(timezone.utc).isoformat()
    _last_run_info["summary"] = summary
    _last_run_info["error"] = summary["errors"][-1] if summary["errors"] else None
    return summary


# ── Scheduler management ──────────────────────────────────────────────────────

_scheduler = None


def start_onboarding_monitor():
    global _scheduler
    if _scheduler is not None:
        logger.warning("[onboarding-monitor] Scheduler already running")
        return

    from apscheduler.schedulers.background import BackgroundScheduler
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        run_onboarding_cycle,
        "interval",
        minutes=30,
        id="onboarding_monitor",
        name="Onboarding Progress Monitor",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("Onboarding monitor started (every 30 min)")


def stop_onboarding_monitor():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("[onboarding-monitor] Scheduler stopped")


def get_status() -> dict:
    """Return current monitor status for the dashboard."""
    return {
        "enabled": _scheduler is not None,
        "last_run": _last_run_info.get("last_run"),
        "summary": _last_run_info.get("summary"),
        "error": _last_run_info.get("error"),
        "interval_minutes": 30,
    }
