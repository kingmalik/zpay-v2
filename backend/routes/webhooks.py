"""
Webhooks — external integrations (Adobe Sign, etc).

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

        # Update ed_drug_test_status if this is EverDriven flow
        if hasattr(rec, "ed_drug_test_status") and rec.ed_drug_test_status in (
            "pending",
            "sent",
            None,
        ):
            rec.ed_drug_test_status = "complete"
            db.commit()
            _logger.info(
                "[adobe-webhook] Updated OnboardingRecord id=%d: ed_drug_test_status='complete'",
                rec.id,
            )
        else:
            _logger.info(
                "[adobe-webhook] Skipped ed_drug_test_status update for onboarding_id=%d: status already=%r",
                rec.id,
                rec.ed_drug_test_status if hasattr(rec, "ed_drug_test_status") else "N/A",
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
