"""
FirstAlt driver compliance sync — runs on startup + every 6 hours.

Fetches the live driver profile for every active Person that has a
firstalt_driver_id and updates:
  - person.phone  (if missing in Z-Pay but present in FirstAlt)
  - person.firstalt_compliance (JSON column) with key compliance fields

Alerts admin when:
  - registrationExpiry is within 30 days or already expired
  - hasPendingDocs flips True (new docs appeared)
  - eligibilityStatus is not ELIGIBLE

Alert deduplication is stored inside the firstalt_compliance JSON blob so
no extra DB columns are needed:
  - _reg_expiry_alerted_week  — ISO week string of last expiry alert (YYYY-WW)
  - _pending_docs_alerted     — bool, reset to False when hasPendingDocs → False
  - _ineligible_alerted       — bool, reset to False when status → ELIGIBLE
"""

import logging
import threading
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("zpay.firstalt-compliance")

_compliance_thread: threading.Thread | None = None
_stop_event = threading.Event()

_SYNC_INTERVAL_SECONDS = 6 * 3600  # 6 hours


def sync_driver_compliance(db_session) -> dict:
    """
    Main sync function.  Fetches live compliance data for every active
    Person with a firstalt_driver_id and updates the DB.

    Returns a summary dict with counts for logging/dashboard.
    """
    from backend.db.models import Person
    from backend.services import firstalt_service
    from backend.services import notification_service as notify

    summary = {
        "synced": 0,
        "phone_filled": 0,
        "reg_expiry_alerts": 0,
        "pending_docs_alerts": 0,
        "ineligible_alerts": 0,
        "errors": [],
    }

    try:
        persons = (
            db_session.query(Person)
            .filter(Person.active == True)
            .filter(Person.firstalt_driver_id.isnot(None))
            .all()
        )
    except Exception as exc:
        logger.error("[compliance] DB query failed: %s", exc)
        summary["errors"].append(str(exc))
        return summary

    now_utc = datetime.now(timezone.utc)

    for person in persons:
        try:
            profile = firstalt_service.get_driver_profile(person.firstalt_driver_id)
        except Exception as exc:
            logger.warning(
                "[compliance] get_driver_profile failed for person_id=%d fa_id=%s: %s",
                person.person_id, person.firstalt_driver_id, exc,
            )
            summary["errors"].append(f"person_id={person.person_id}: {exc}")
            continue

        # ── Phone backfill ──────────────────────────────────────────────
        if not person.phone:
            fa_phone = (
                profile.get("phone")
                or profile.get("mobilePhone")
                or profile.get("phoneNumber")
                or ""
            ).strip()
            if fa_phone:
                person.phone = fa_phone
                summary["phone_filled"] += 1
                logger.info(
                    "[compliance] Filled phone for person_id=%d from FirstAlt: %s",
                    person.person_id, fa_phone,
                )

        # ── Extract compliance fields ───────────────────────────────────
        eligibility = (
            profile.get("eligibilityStatus")
            or profile.get("driverStatus")
            or ""
        ).upper().strip()

        has_pending_docs = bool(
            profile.get("hasPendingDocs")
            or profile.get("pendingDocuments")
            or (
                isinstance(profile.get("pendingDocumentCount"), int)
                and profile["pendingDocumentCount"] > 0
            )
        )

        onboarding_pct = (
            profile.get("driverOnboardingPercentage")
            or profile.get("onboardingPercentage")
            or 0
        )

        docs_approved = (
            profile.get("totalOnboardingDocumentsApproved")
            or profile.get("documentsApproved")
            or 0
        )

        docs_required = (
            profile.get("totalOnboardingDocumentsRequired")
            or profile.get("documentsRequired")
            or 0
        )

        reg_expiry_raw = (
            profile.get("registrationExpiry")
            or profile.get("vehicleRegistrationExpiry")
            or profile.get("regExpiry")
            or ""
        )

        photo_url = (
            profile.get("photoUrl")
            or profile.get("driverPhotoUrl")
            or profile.get("profilePhoto")
            or ""
        )

        driver_photo = profile.get("driverPhoto") or {}

        onboarding_status = (
            profile.get("onBoardingStatus")
            or profile.get("onboardingStatus")
            or ""
        )

        ack_driver_agreement = bool(
            profile.get("ackDriverAgreement")
            or profile.get("driverAgreementAcknowledged")
        )

        firstalt_agreement_file_id = (
            profile.get("firstAltAgreementFileId")
            or profile.get("agreementFileId")
        )

        # ── Load previous compliance state ──────────────────────────────
        prev_compliance: dict = person.firstalt_compliance or {}

        new_compliance: dict = {
            "eligibilityStatus": eligibility,
            "hasPendingDocs": has_pending_docs,
            "driverOnboardingPercentage": onboarding_pct,
            "totalOnboardingDocumentsApproved": docs_approved,
            "totalOnboardingDocumentsRequired": docs_required,
            "registrationExpiry": reg_expiry_raw,
            "photoUrl": photo_url,
            "driverPhoto": driver_photo,
            "onBoardingStatus": onboarding_status,
            "ackDriverAgreement": ack_driver_agreement,
            "firstAltAgreementFileId": firstalt_agreement_file_id,
            "syncedAt": now_utc.isoformat(),
            # Preserve dedup tracking fields from previous state
            "_reg_expiry_alerted_week": prev_compliance.get("_reg_expiry_alerted_week"),
            "_pending_docs_alerted": prev_compliance.get("_pending_docs_alerted", False),
            "_ineligible_alerted": prev_compliance.get("_ineligible_alerted", False),
        }

        driver_name = person.full_name or f"Driver #{person.person_id}"

        # ── Registration expiry alert (once per week) ───────────────────
        if reg_expiry_raw:
            reg_expiry_dt = _parse_date(reg_expiry_raw)
            if reg_expiry_dt is not None:
                days_left = (reg_expiry_dt.date() - now_utc.date()).days
                if days_left <= 30:
                    current_week = now_utc.strftime("%Y-%W")
                    last_alerted_week = new_compliance.get("_reg_expiry_alerted_week") or ""
                    if current_week != last_alerted_week:
                        status_word = "EXPIRED" if days_left < 0 else f"expires in {days_left} days"
                        try:
                            notify.alert_admin(
                                f"REG EXPIRY — {driver_name} registration {status_word} "
                                f"({reg_expiry_raw}). FirstAlt driver ID: {person.firstalt_driver_id}.",
                                spoken_message=(
                                    f"{driver_name}'s vehicle registration {status_word}. "
                                    f"Registration date: {reg_expiry_raw}."
                                ),
                            )
                            new_compliance["_reg_expiry_alerted_week"] = current_week
                            summary["reg_expiry_alerts"] += 1
                            logger.info(
                                "[compliance] Reg expiry alert sent for person_id=%d days_left=%d",
                                person.person_id, days_left,
                            )
                        except Exception as exc:
                            logger.error("[compliance] Reg expiry alert failed: %s", exc)

        # ── Pending docs alert (fires when flips True from False) ───────
        prev_pending = bool(prev_compliance.get("hasPendingDocs", False))
        prev_pending_alerted = bool(prev_compliance.get("_pending_docs_alerted", False))

        if has_pending_docs and not prev_pending_alerted:
            try:
                notify.alert_admin(
                    f"PENDING DOCS — {driver_name} has new pending documents in FirstAlt "
                    f"(FA driver ID: {person.firstalt_driver_id}). Check their profile.",
                    spoken_message=(
                        f"{driver_name} has new pending documents in FirstAlt. "
                        f"Check their profile."
                    ),
                )
                new_compliance["_pending_docs_alerted"] = True
                summary["pending_docs_alerts"] += 1
                logger.info(
                    "[compliance] Pending docs alert sent for person_id=%d",
                    person.person_id,
                )
            except Exception as exc:
                logger.error("[compliance] Pending docs alert failed: %s", exc)
        elif not has_pending_docs:
            # Reset so we alert again next time docs appear
            new_compliance["_pending_docs_alerted"] = False

        # ── Ineligibility alert ─────────────────────────────────────────
        is_eligible = "ELIGIBLE" in eligibility
        prev_ineligible_alerted = bool(prev_compliance.get("_ineligible_alerted", False))

        if eligibility and not is_eligible and not prev_ineligible_alerted:
            try:
                notify.alert_admin(
                    f"INELIGIBLE DRIVER — {driver_name} status in FirstAlt is '{eligibility}'. "
                    f"FA driver ID: {person.firstalt_driver_id}. Check immediately.",
                    spoken_message=(
                        f"{driver_name} is showing as {eligibility} in FirstAlt. "
                        f"Check their status immediately."
                    ),
                )
                new_compliance["_ineligible_alerted"] = True
                summary["ineligible_alerts"] += 1
                logger.info(
                    "[compliance] Ineligible alert sent for person_id=%d status=%s",
                    person.person_id, eligibility,
                )
            except Exception as exc:
                logger.error("[compliance] Ineligible alert failed: %s", exc)
        elif is_eligible:
            # Driver is back to eligible — reset so next ineligibility triggers a new alert
            new_compliance["_ineligible_alerted"] = False

        # ── Persist ─────────────────────────────────────────────────────
        person.firstalt_compliance = new_compliance
        summary["synced"] += 1

        # ── Onboarding automation ────────────────────────────────────────
        # After updating compliance, check if any onboarding steps can advance
        try:
            from backend.db.models import OnboardingRecord
            from backend.services.onboarding_automation import check_and_advance
            onb = db_session.query(OnboardingRecord).filter_by(person_id=person.person_id).first()
            if onb and onb.automation_live and not onb.completed_at:
                actions = check_and_advance(onb, person, db_session, dry_run=False)
                if actions:
                    executed = [a for a in actions if a.get("executed")]
                    logger.info(
                        "[compliance] Auto-advanced %d onboarding step(s) for person_id=%d",
                        len(executed), person.person_id,
                    )
        except Exception as exc:
            logger.warning("[compliance] Onboarding automation check failed for person_id=%d: %s", person.person_id, exc)

    try:
        db_session.commit()
    except Exception as exc:
        logger.error("[compliance] DB commit failed: %s", exc)
        db_session.rollback()
        summary["errors"].append(f"commit: {exc}")

    logger.info(
        "[compliance] Sync complete — synced=%d phone_filled=%d "
        "reg_alerts=%d pending_alerts=%d ineligible_alerts=%d errors=%d",
        summary["synced"],
        summary["phone_filled"],
        summary["reg_expiry_alerts"],
        summary["pending_docs_alerts"],
        summary["ineligible_alerts"],
        len(summary["errors"]),
    )
    return summary


def _parse_date(raw: str) -> datetime | None:
    """Try common date formats; return UTC datetime or None."""
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(raw.split("T")[0], fmt.split("T")[0])
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


# ── Background thread management ─────────────────────────────────────

def _compliance_loop() -> None:
    """Run sync_driver_compliance once immediately, then every 6 hours."""
    from backend.db import SessionLocal

    logger.info("[compliance] Background thread started")

    while not _stop_event.is_set():
        db = SessionLocal()
        try:
            sync_driver_compliance(db)
        except Exception as exc:
            logger.exception("[compliance] Unhandled error in sync: %s", exc)
        finally:
            db.close()

        # Sleep in small increments so stop_event is checked promptly
        for _ in range(_SYNC_INTERVAL_SECONDS):
            if _stop_event.is_set():
                break
            _stop_event.wait(timeout=1)

    logger.info("[compliance] Background thread stopped")


def start_compliance_sync() -> None:
    """Start the compliance sync background thread (idempotent)."""
    global _compliance_thread
    if _compliance_thread is not None and _compliance_thread.is_alive():
        logger.warning("[compliance] Thread already running")
        return
    _stop_event.clear()
    _compliance_thread = threading.Thread(
        target=_compliance_loop,
        name="firstalt-compliance-sync",
        daemon=True,
    )
    _compliance_thread.start()
    logger.info("[compliance] Compliance sync thread started")


def stop_compliance_sync() -> None:
    """Signal the compliance sync thread to stop."""
    _stop_event.set()
    logger.info("[compliance] Compliance sync thread stop requested")
