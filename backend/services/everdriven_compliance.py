"""
EverDriven driver compliance sync — runs every 6 hours (1-hour offset from FA job).
Polls Contractor Compliance for every Person with an everdriven_driver_id.
Alerts on: declined docs, expiring docs (14-day window).
Prerequisites: person.cc_compliance JSON column (Alembic migration needed).
"""

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger("zpay.everdriven-compliance")

_compliance_thread: threading.Thread | None = None
_stop_event = threading.Event()

_SYNC_INTERVAL_SECONDS = 6 * 3600
_STARTUP_DELAY_SECONDS = 3600   # 1-hour offset so FA and ED don't hit DB together
_EXPIRY_WARN_DAYS = 14

# TODO: Confirm actual CC API endpoint and auth before enabling
_CC_BASE_URL = os.environ.get("CONTRACTOR_COMPLIANCE_BASE_URL", "https://app.contractorcompliance.io/api")
_CC_API_KEY = os.environ.get("CONTRACTOR_COMPLIANCE_API_KEY", "")


def _get_cc_id(person) -> str | None:
    # TODO: replace with person.contractor_compliance_id once that column is added
    raw = getattr(person, "everdriven_driver_id", None)
    return str(raw) if raw is not None else None


def _fetch_cc_documents(cc_id: str) -> list[dict[str, Any]]:
    # TODO: Confirm actual CC API endpoint and auth before enabling.
    # Endpoint pattern is a stub — real endpoint/auth header/response shape TBD.
    url = f"{_CC_BASE_URL}/contractors/{cc_id}/documents"
    headers = {"X-Api-Key": _CC_API_KEY, "Accept": "application/json"}
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, list):
        return data
    return data.get("data") or data.get("documents") or []


def _parse_date(raw: str) -> datetime | None:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(raw.split("T")[0], fmt.split("T")[0])
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def sync_driver_compliance(db_session) -> dict:
    from backend.db.models import Person
    from backend.services import notification_service as notify

    if not _CC_API_KEY:
        logger.warning("[ed-compliance] CONTRACTOR_COMPLIANCE_API_KEY not set — skipping sync")
        return {"skipped": True, "reason": "no_api_key"}

    summary = {"synced": 0, "declined_alerts": 0, "expiry_alerts": 0, "all_approved": 0, "errors": []}

    try:
        persons = (
            db_session.query(Person)
            .filter(Person.active == True)
            .filter(Person.everdriven_driver_id.isnot(None))
            .all()
        )
    except Exception as exc:
        logger.error("[ed-compliance] DB query failed: %s", exc)
        summary["errors"].append(str(exc))
        return summary

    now_utc = datetime.now(timezone.utc)

    for person in persons:
        cc_id = _get_cc_id(person)
        if not cc_id:
            continue

        try:
            docs = _fetch_cc_documents(cc_id)
        except Exception as exc:
            logger.warning("[ed-compliance] fetch failed person_id=%d cc_id=%s: %s", person.person_id, cc_id, exc)
            summary["errors"].append(f"person_id={person.person_id}: {exc}")
            continue

        # Classify documents
        # TODO: Confirm field names in actual CC API response (documentName, status, expirationDate)
        declined_docs: list[str] = []
        expiring_docs: list[tuple[str, int]] = []
        approved_count = 0

        for doc in docs:
            name = doc.get("documentName") or doc.get("name") or "Unknown"
            status = (doc.get("status") or doc.get("documentStatus") or "").upper()
            expiry_raw = doc.get("expirationDate") or doc.get("expiry") or ""

            if status == "DECLINED":
                declined_docs.append(name)
            if status == "APPROVED":
                approved_count += 1
            if expiry_raw:
                expiry_dt = _parse_date(expiry_raw)
                if expiry_dt and (expiry_dt.date() - now_utc.date()).days <= _EXPIRY_WARN_DAYS:
                    expiring_docs.append((name, (expiry_dt.date() - now_utc.date()).days))

        all_approved = len(docs) > 0 and approved_count == len(docs)
        prev: dict = getattr(person, "cc_compliance", None) or {}

        new_compliance: dict = {
            "rawDocuments": docs,
            "totalDocuments": len(docs),
            "approvedCount": approved_count,
            "declinedCount": len(declined_docs),
            "declinedDocs": declined_docs,
            "expiringDocs": [{"name": n, "daysLeft": d} for n, d in expiring_docs],
            "allApproved": all_approved,
            "syncedAt": now_utc.isoformat(),
            "_declined_alerted": prev.get("_declined_alerted", False),
            "_expiry_alerted_week": prev.get("_expiry_alerted_week"),
        }

        driver_name = person.full_name or f"Driver #{person.person_id}"

        # Declined docs alert (fires on first occurrence, resets when cleared)
        if declined_docs and not prev.get("_declined_alerted", False):
            doc_list = ", ".join(declined_docs)
            try:
                notify.alert_admin(
                    f"CC DECLINED DOCS — {driver_name} has declined documents in Contractor Compliance: "
                    f"{doc_list}. EverDriven driver ID: {person.everdriven_driver_id}.",
                    spoken_message=f"{driver_name} has declined documents in Contractor Compliance: {doc_list}.",
                )
                new_compliance["_declined_alerted"] = True
                summary["declined_alerts"] += 1
                logger.info("[ed-compliance] Declined docs alert sent person_id=%d docs=%s", person.person_id, doc_list)
            except Exception as exc:
                logger.error("[ed-compliance] Declined docs alert failed: %s", exc)
        elif not declined_docs:
            new_compliance["_declined_alerted"] = False

        # Expiring docs alert (once per week)
        if expiring_docs:
            current_week = now_utc.strftime("%Y-%W")
            if current_week != (new_compliance.get("_expiry_alerted_week") or ""):
                expiry_lines = "; ".join(
                    f"{n} ({'EXPIRED' if d < 0 else f'expires in {d}d'})" for n, d in expiring_docs
                )
                try:
                    notify.alert_admin(
                        f"CC DOC EXPIRY — {driver_name}: {expiry_lines}. "
                        f"EverDriven driver ID: {person.everdriven_driver_id}.",
                        spoken_message=f"{driver_name} has documents expiring in Contractor Compliance: {expiry_lines}.",
                    )
                    new_compliance["_expiry_alerted_week"] = current_week
                    summary["expiry_alerts"] += 1
                    logger.info("[ed-compliance] Expiry alert sent person_id=%d", person.person_id)
                except Exception as exc:
                    logger.error("[ed-compliance] Expiry alert failed: %s", exc)

        # All docs approved — optionally advance onboarding
        if all_approved:
            summary["all_approved"] += 1
            try:
                from backend.db.models import OnboardingRecord
                from backend.services.onboarding_automation import check_and_advance
                onb = db_session.query(OnboardingRecord).filter_by(person_id=person.person_id).first()
                if onb and onb.automation_live and not onb.completed_at:
                    actions = check_and_advance(onb, person, db_session, dry_run=False)
                    executed = [a for a in (actions or []) if a.get("executed")]
                    if executed:
                        logger.info("[ed-compliance] Auto-advanced %d onboarding step(s) person_id=%d", len(executed), person.person_id)
            except Exception as exc:
                logger.warning("[ed-compliance] Onboarding automation check failed person_id=%d: %s", person.person_id, exc)

        # Persist — NOTE: person.cc_compliance column must exist (Alembic migration needed)
        try:
            person.cc_compliance = new_compliance
            summary["synced"] += 1
        except Exception as exc:
            logger.warning("[ed-compliance] cc_compliance persist failed person_id=%d (column missing?): %s", person.person_id, exc)

    try:
        db_session.commit()
    except Exception as exc:
        logger.error("[ed-compliance] DB commit failed: %s", exc)
        db_session.rollback()
        summary["errors"].append(f"commit: {exc}")

    logger.info(
        "[ed-compliance] Sync complete — synced=%d declined_alerts=%d expiry_alerts=%d all_approved=%d errors=%d",
        summary["synced"], summary["declined_alerts"], summary["expiry_alerts"], summary["all_approved"], len(summary["errors"]),
    )
    return summary


def _compliance_loop() -> None:
    from backend.db import SessionLocal
    logger.info("[ed-compliance] Thread started — waiting 1h before first sync")
    for _ in range(_STARTUP_DELAY_SECONDS):
        if _stop_event.is_set():
            break
        _stop_event.wait(timeout=1)
    while not _stop_event.is_set():
        db = SessionLocal()
        try:
            sync_driver_compliance(db)
        except Exception as exc:
            logger.exception("[ed-compliance] Unhandled error in sync: %s", exc)
        finally:
            db.close()
        for _ in range(_SYNC_INTERVAL_SECONDS):
            if _stop_event.is_set():
                break
            _stop_event.wait(timeout=1)
    logger.info("[ed-compliance] Thread stopped")


def start_compliance_sync() -> None:
    """Start the EverDriven compliance sync background thread (idempotent)."""
    global _compliance_thread
    if _compliance_thread is not None and _compliance_thread.is_alive():
        logger.warning("[ed-compliance] Thread already running")
        return
    _stop_event.clear()
    _compliance_thread = threading.Thread(target=_compliance_loop, name="everdriven-compliance-sync", daemon=True)
    _compliance_thread.start()
    logger.info("[ed-compliance] Compliance sync thread started")


def stop_compliance_sync() -> None:
    """Signal the EverDriven compliance sync thread to stop."""
    _stop_event.set()
    logger.info("[ed-compliance] Compliance sync thread stop requested")
