"""
Webhooks — external integrations (Adobe Sign, FADV).

All webhook handlers live here and are registered WITHOUT a prefix
so they remain at the top level (e.g., /webhooks/adobe-sign).
"""

import logging
import hmac
import hashlib
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import Person, OnboardingRecord

_logger = logging.getLogger("zpay.webhooks")

# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------

# FADV webhook processing is disabled by default until FADV_CLIENT_ID/SECRET
# are provisioned and the FADV portal webhook URL is configured.
# TODO: set FADV_WEBHOOK_ENABLED=true in Railway once:
#   1. FADV_CLIENT_ID and FADV_CLIENT_SECRET are set
#   2. FADV portal is configured to POST to /webhooks/fadv
_FADV_WEBHOOK_ENABLED = os.environ.get("FADV_WEBHOOK_ENABLED", "false").strip().lower() == "true"

router = APIRouter(tags=["webhooks"])


# ---------------------------------------------------------------------------
# POST /webhooks/adobe-sign — Adobe Sign event webhook
# ---------------------------------------------------------------------------

@router.post("/webhooks/adobe-sign")
async def adobe_sign_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Webhook endpoint for Adobe Sign events.

    Adobe Sign POSTs JSON payloads when agreements transition. This handler:
      1. Checks for Adobe's verification challenge header (x-adobesign-clientid)
         and echoes it back if present (required for webhook validation).
      2. Validates HMAC-SHA256 signature if ADOBE_SIGN_WEBHOOK_SECRET is configured.
      3. Parses the event payload to find AGREEMENT_ACTION_COMPLETED events.
      4. Looks up the driver by drug_test_agreement_id.
      5. Sets person.drug_test_signed_at = now() and updates the OnboardingRecord status.
      6. Always returns 200 (Adobe retries aggressively on 5xx).

    Expected payload structure (AGREEMENT_ACTION_COMPLETED event):
    {
        "event": "AGREEMENT_ACTION_COMPLETED",
        "agreement": {
            "id": "<agreementId>",
            "status": "SIGNED"
        },
        ...
    }
    """
    now = datetime.now(timezone.utc)

    # Adobe Sign webhook verification challenge
    client_id = request.headers.get("x-adobesign-clientid")
    if client_id:
        _logger.info("[adobe-webhook] Verification challenge from Adobe: %s", client_id)
        return JSONResponse(
            {"xAdobeSignClientId": client_id},
            status_code=200,
        )

    # Read raw body for signature verification
    raw_body = await request.body()

    # Validate HMAC signature if secret is configured
    webhook_secret = os.environ.get("ADOBE_SIGN_WEBHOOK_SECRET", "").strip()
    if webhook_secret:
        signature_header = request.headers.get("X-AdobeSign-SignatureKey", "")
        if signature_header:
            expected_signature = hmac.new(
                webhook_secret.encode("utf-8"),
                raw_body,
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(signature_header, expected_signature):
                _logger.warning(
                    "[adobe-webhook] HMAC signature mismatch. Header=%s, Expected=%s",
                    signature_header[:16] + "...",
                    expected_signature[:16] + "...",
                )
        else:
            _logger.warning("[adobe-webhook] Missing X-AdobeSign-SignatureKey header")
    else:
        _logger.debug("[adobe-webhook] ADOBE_SIGN_WEBHOOK_SECRET not configured — signature validation skipped (backwards compat)")

    try:
        body = await request.json()
    except Exception as exc:
        _logger.warning("[adobe-webhook] Failed to parse JSON body: %s", exc)
        return JSONResponse({"ok": True}, status_code=200)

    event_type = body.get("event")
    if event_type != "AGREEMENT_ACTION_COMPLETED":
        # Ignore events we don't care about
        _logger.debug("[adobe-webhook] Ignoring event type: %s", event_type)
        return JSONResponse({"ok": True}, status_code=200)

    # Extract agreement ID from nested structure
    agreement_id = body.get("agreement", {}).get("id")
    if not agreement_id:
        _logger.warning(
            "[adobe-webhook] AGREEMENT_ACTION_COMPLETED event missing agreement.id: %s",
            body,
        )
        return JSONResponse({"ok": True}, status_code=200)

    _logger.info("[adobe-webhook] AGREEMENT_ACTION_COMPLETED: agreement_id=%s", agreement_id)

    try:
        # Look up the onboarding record by drug_test_agreement_id (new location)
        rec = (
            db.query(OnboardingRecord)
            .filter(OnboardingRecord.drug_test_agreement_id == agreement_id)
            .first()
        )

        if not rec:
            # Fallback: look up by person table (for backwards compat with old data)
            person = (
                db.query(Person)
                .filter(Person.drug_test_agreement_id == agreement_id)
                .first()
            )
            if not person:
                _logger.warning(
                    "[adobe-webhook] No person/onboarding found with drug_test_agreement_id=%s",
                    agreement_id,
                )
                return JSONResponse({"ok": True}, status_code=200)

            person_id = person.person_id
            rec = db.query(OnboardingRecord).filter(
                OnboardingRecord.person_id == person_id
            ).first()

            if not rec:
                _logger.warning(
                    "[adobe-webhook] No OnboardingRecord found for person_id=%d (backwards compat lookup)",
                    person_id,
                )
                return JSONResponse({"ok": True}, status_code=200)
        else:
            person_id = rec.person_id
            person = db.query(Person).filter(Person.person_id == person_id).first()

        _logger.info(
            "[adobe-webhook] Found onboarding_id=%d person_id=%d for agreement_id=%s",
            rec.id,
            person_id,
            agreement_id,
        )

        # Update onboarding_record.drug_test_signed_at
        rec.drug_test_signed_at = now
        db.commit()

        partner = getattr(rec, "partner", "firstalt") or "firstalt"

        if partner == "everdriven":
            # EverDriven flow — advance ed_drug_test_status
            if hasattr(rec, "ed_drug_test_status") and rec.ed_drug_test_status in (
                "pending",
                "sent",
                None,
            ):
                rec.ed_drug_test_status = "complete"
                db.commit()
                _logger.info(
                    "[adobe-webhook] ED: updated OnboardingRecord id=%d: ed_drug_test_status='complete'",
                    rec.id,
                )
            else:
                _logger.info(
                    "[adobe-webhook] ED: skipped ed_drug_test_status update for onboarding_id=%d: status already=%r",
                    rec.id,
                    rec.ed_drug_test_status if hasattr(rec, "ed_drug_test_status") else "N/A",
                )
        else:
            # FirstAlt/Acumen flow — advance consent_status
            if hasattr(rec, "consent_status") and rec.consent_status in (
                "pending",
                "sent",
                None,
            ):
                rec.consent_status = "signed"
                db.commit()
                _logger.info(
                    "[adobe-webhook] FA: updated OnboardingRecord id=%d: consent_status='signed'",
                    rec.id,
                )
            else:
                _logger.info(
                    "[adobe-webhook] FA: skipped consent_status update for onboarding_id=%d: status already=%r",
                    rec.id,
                    rec.consent_status if hasattr(rec, "consent_status") else "N/A",
                )

        _logger.info(
            "[adobe-webhook] Successfully processed: onboarding_id=%d person_id=%d agreement_id=%s drug_test_signed_at=%s",
            rec.id,
            person_id,
            agreement_id,
            now.isoformat(),
        )

    except Exception as exc:
        _logger.error(
            "[adobe-webhook] Error processing agreement_id=%s: %s",
            agreement_id,
            exc,
            exc_info=True,
        )
        try:
            db.rollback()
        except Exception:
            pass

    # Always return 200 — don't let Adobe think we failed
    return JSONResponse({"ok": True}, status_code=200)


# ---------------------------------------------------------------------------
# POST /webhooks/fadv — First Advantage BGC status webhook
# ---------------------------------------------------------------------------

# FADV status → internal status mapping
_FADV_STATUS_MAP: dict[str, str] = {
    "CLEAR": "clear",
    "CONSIDER": "consider",
    "SUSPENDED": "suspended",
    "PENDING": "pending",
    "IN_PROCESS": "initiated",
    "INITIATED": "initiated",
    "COMPLETE": "clear",          # some FADV accounts use COMPLETE instead of CLEAR
    "REVIEW": "consider",
    "CANCELED": "suspended",
}


@router.post("/webhooks/fadv")
async def fadv_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Webhook endpoint for First Advantage (FADV) background check status updates.

    FADV POSTs JSON payloads when a background check status changes. This handler:
      1. Feature-flag guard — returns 200 immediately if FADV_WEBHOOK_ENABLED != 'true'.
      2. Validates HMAC-SHA256 signature if FADV_WEBHOOK_SECRET is configured.
      3. Parses the event to find the report ID and new status.
      4. Looks up the OnboardingRecord by fadv_report_id.
      5. Updates fadv_status (and fadv_result_at for terminal statuses).
      6. Auto-advances bgc_status to 'manual' if FADV clears (prompt admin to confirm).
      7. Always returns 200 (FADV retries on 5xx/non-200).

    Feature flag: set FADV_WEBHOOK_ENABLED=true in Railway env vars to enable.
    TODO: enable once FADV_CLIENT_ID, FADV_CLIENT_SECRET, and FADV portal webhook
          URL are configured and credentials have been provisioned.

    Expected payload structure (from FADV portal documentation):
    {
        "reportId": "<report_id>",
        "referenceId": "zpay-<person_id>",
        "status": "CLEAR" | "CONSIDER" | "SUSPENDED" | "PENDING" | "IN_PROCESS",
        "completedAt": "<ISO timestamp>",
        ...
    }
    """
    now = datetime.now(timezone.utc)

    # Feature flag guard
    if not _FADV_WEBHOOK_ENABLED:
        _logger.debug(
            "[fadv-webhook] Feature flag disabled (FADV_WEBHOOK_ENABLED != 'true') — skipping"
        )
        return JSONResponse({"ok": True, "skipped": True, "reason": "feature_flag_disabled"}, status_code=200)

    # Read raw body for signature verification
    raw_body = await request.body()

    # Validate HMAC signature if secret is configured
    webhook_secret = os.environ.get("FADV_WEBHOOK_SECRET", "").strip()
    if webhook_secret:
        signature_header = request.headers.get("X-FADV-Signature", "") or request.headers.get("X-Signature", "")
        if signature_header:
            expected_sig = hmac.new(
                webhook_secret.encode("utf-8"),
                raw_body,
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(signature_header, expected_sig):
                _logger.warning(
                    "[fadv-webhook] HMAC signature mismatch — possible spoofed payload"
                )
                # Still return 200 (log the warning but don't surface rejection to FADV)
        else:
            _logger.debug("[fadv-webhook] No signature header present — FADV_WEBHOOK_SECRET set but header absent")
    else:
        _logger.debug("[fadv-webhook] FADV_WEBHOOK_SECRET not set — signature validation skipped")

    try:
        body = await request.json()
    except Exception as exc:
        _logger.warning("[fadv-webhook] Failed to parse JSON body: %s", exc)
        return JSONResponse({"ok": True}, status_code=200)

    # Extract report ID and status from payload
    # FADV payload shape may vary — support common field names
    report_id = (
        body.get("reportId")
        or body.get("report_id")
        or body.get("orderId")
        or body.get("order_id")
    )
    raw_status = (
        body.get("status")
        or body.get("orderStatus")
        or body.get("reportStatus")
        or ""
    ).upper().strip()

    if not report_id:
        _logger.warning("[fadv-webhook] Payload missing reportId: %s", list(body.keys()))
        return JSONResponse({"ok": True}, status_code=200)

    if not raw_status:
        _logger.warning("[fadv-webhook] Payload missing status for report_id=%s", report_id)
        return JSONResponse({"ok": True}, status_code=200)

    internal_status = _FADV_STATUS_MAP.get(raw_status, raw_status.lower())
    _logger.info(
        "[fadv-webhook] Received status update: report_id=%s raw_status=%s internal=%s",
        report_id,
        raw_status,
        internal_status,
    )

    try:
        rec = (
            db.query(OnboardingRecord)
            .filter(OnboardingRecord.fadv_report_id == report_id)
            .first()
        )

        if not rec:
            # Fallback: try referenceId which we set as "zpay-<person_id>"
            reference_id = body.get("referenceId") or body.get("reference_id") or ""
            if reference_id.startswith("zpay-"):
                try:
                    person_id = int(reference_id.split("-", 1)[1])
                    rec = (
                        db.query(OnboardingRecord)
                        .filter(OnboardingRecord.person_id == person_id)
                        .first()
                    )
                except (ValueError, IndexError):
                    pass

        if not rec:
            _logger.warning(
                "[fadv-webhook] No OnboardingRecord found for report_id=%s — skipping",
                report_id,
            )
            return JSONResponse({"ok": True}, status_code=200)

        # Only update if the status actually changed (idempotent)
        if rec.fadv_status == internal_status:
            _logger.info(
                "[fadv-webhook] Status unchanged (%s) for onboarding_id=%d — no-op",
                internal_status,
                rec.id,
            )
            return JSONResponse({"ok": True}, status_code=200)

        prev_status = rec.fadv_status
        rec.fadv_status = internal_status

        # Stamp result timestamp for terminal statuses
        if internal_status in ("clear", "consider", "suspended"):
            rec.fadv_result_at = now
            # Auto-advance BGC to 'manual' if FADV cleared — admin confirms before marking complete
            if internal_status == "clear" and getattr(rec, "bgc_status", "pending") in ("pending", "sent"):
                rec.bgc_status = "manual"
                _logger.info(
                    "[fadv-webhook] BGC auto-advanced to 'manual' for onboarding_id=%d (FADV clear)",
                    rec.id,
                )

        db.commit()
        _logger.info(
            "[fadv-webhook] Updated onboarding_id=%d fadv_status %s → %s",
            rec.id,
            prev_status,
            internal_status,
        )

    except Exception as exc:
        _logger.error(
            "[fadv-webhook] Error processing report_id=%s: %s",
            report_id,
            exc,
            exc_info=True,
        )
        try:
            db.rollback()
        except Exception:
            pass

    # Always return 200
    return JSONResponse({"ok": True}, status_code=200)
