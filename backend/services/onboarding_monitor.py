"""
Onboarding progress monitor — checks driver onboarding status
and auto-triggers next onboarding steps when conditions are met.

APScheduler background job (same pattern as trip_monitor.py).
Runs every 30 minutes while MONITOR_ENABLED=1 is set.

Auto-trigger chain:
    1. consent signed  → auto-email Donna at Concentra (drug test consent)
    2. bgc clear + drug test clear + firstalt training clear + files clear
       → auto-send partner contract (or mark manual)
    3. all 10 steps done → completed_at = now()
"""

import os
import logging
import base64
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders

from backend.utils.test_mode import redirect_email, test_subject

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
    # TEST MODE: redirect recipient and prefix subject
    to_email = redirect_email(to_email)
    subject = test_subject(subject)

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


def _auto_send_donna_email(rec, driver_name: str, driver_phone: str) -> bool:
    """
    Auto-send signed drug test consent to Donna at Concentra.
    Triggered when consent_status transitions to signed/complete.
    """
    to_email = os.environ.get("DONNA_EMAIL", "").strip()
    if not to_email:
        logger.warning(
            "[onboarding-monitor] DONNA_EMAIL not set — cannot auto-notify Concentra "
            "for onboarding_id=%d",
            rec.id,
        )
        return False

    subject = f"Drug Test Consent — {driver_name}"
    body = (
        f"Hi Donna,\n\n"
        f"Attached is the signed drug test consent form for {driver_name} "
        f"({driver_phone or 'no phone on file'}). "
        f"Please proceed with scheduling their drug test.\n\n"
        f"Thank you.\n"
        f"— MAZ Services"
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
            "[onboarding-monitor] ADOBE_SIGN_INTEGRATION_KEY not set — marking contract as MANUAL "
            "for onboarding_id=%d. Admin must send Acumen contract via email.",
            rec.id,
        )
        rec.contract_status = "manual"
        rec.notes = (getattr(rec, "notes", None) or "") + " [MANUAL] Contract: Adobe Sign unavailable — send via email. "
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

        # Create tracking row so the Adobe Sign webhook can find this envelope
        # and mark it "signed" when the driver completes signing.
        doc = OnboardingDocument(
            onboarding_id=rec.id,
            doc_type="acumen_contract",
            envelope_id=envelope_id,
            status="sent",
            sent_at=now,
            signer_email=person.email,
        )
        # Add doc to the same SQLAlchemy session that rec belongs to
        from sqlalchemy.orm import object_session
        _session = object_session(rec)
        if _session is not None:
            _session.add(doc)

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
        rec.priority_email_status,   # firstalt invite
        rec.bgc_status,
        rec.consent_status,          # drug test consent
        rec.drug_test_status,
        rec.training_status,         # firstalt training
        rec.files_status,
        rec.contract_status,         # partner contract
        rec.maz_training_status if hasattr(rec, "maz_training_status") else "pending",
        rec.maz_contract_status if hasattr(rec, "maz_contract_status") else "pending",
        rec.paychex_status,
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
        "donna_emails_sent": 0,
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

                # ── Check 1: Consent signed → auto-email Donna at Concentra ──
                # Fires when consent transitions to signed/complete and drug_test is still pending
                if (
                    rec.consent_status in ("signed", "complete")
                    and rec.drug_test_status == "pending"
                ):
                    donna_ok = _auto_send_donna_email(rec, driver_name, driver_phone)
                    if donna_ok:
                        summary["donna_emails_sent"] += 1

                # ── Check 2: BGC + Drug Test + Training + Files → partner contract ──
                _bgc_clear = rec.bgc_status in ("complete", "manual", "skipped")
                _drug_clear = rec.drug_test_status == "complete"
                _files_clear = rec.files_status == "complete"
                _training_clear = rec.training_status in ("complete", "manual")
                if (
                    _bgc_clear
                    and _drug_clear
                    and _files_clear
                    and _training_clear
                    and rec.contract_status == "pending"
                ):
                    success = _auto_send_contract(rec, person)
                    if success:
                        summary["contracts_sent"] += 1

                # ── Check 3: All 10 steps complete? ──
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
            "[onboarding-monitor] Cycle complete — checked=%d donna=%d contracts=%d completed=%d errors=%d",
            summary["records_checked"],
            summary["donna_emails_sent"],
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
