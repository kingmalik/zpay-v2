"""
Webhooks — external integrations (Adobe Sign, etc).

All webhook handlers live here and are registered WITHOUT a prefix
so they remain at the top level (e.g., /webhooks/adobe-sign).
"""

import logging
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
      2. Parses the event payload to find AGREEMENT_ACTION_COMPLETED events.
      3. Looks up the driver by drug_test_agreement_id.
      4. Sets person.drug_test_signed_at = now() and updates the OnboardingRecord status.
      5. Always returns 200 (Adobe retries aggressively on 5xx).

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
        # Look up the person by drug_test_agreement_id
        person = (
            db.query(Person)
            .filter(Person.drug_test_agreement_id == agreement_id)
            .first()
        )

        if not person:
            _logger.warning(
                "[adobe-webhook] No person found with drug_test_agreement_id=%s",
                agreement_id,
            )
            return JSONResponse({"ok": True}, status_code=200)

        person_id = person.person_id
        _logger.info(
            "[adobe-webhook] Found person_id=%d for agreement_id=%s",
            person_id,
            agreement_id,
        )

        # Update person.drug_test_signed_at
        person.drug_test_signed_at = now
        db.commit()

        # Find and update the related OnboardingRecord
        rec = db.query(OnboardingRecord).filter(
            OnboardingRecord.person_id == person_id
        ).first()

        if rec:
            # Only update ed_drug_test_status if it's pending (EverDriven flow)
            if hasattr(rec, "ed_drug_test_status") and rec.ed_drug_test_status in (
                "pending",
                None,
            ):
                rec.ed_drug_test_status = "completed"
                db.commit()
                _logger.info(
                    "[adobe-webhook] Updated OnboardingRecord id=%d: ed_drug_test_status='completed'",
                    rec.id,
                )
            else:
                _logger.info(
                    "[adobe-webhook] Skipped OnboardingRecord id=%d: ed_drug_test_status already=%r",
                    rec.id,
                    rec.ed_drug_test_status if hasattr(rec, "ed_drug_test_status") else "N/A",
                )
        else:
            _logger.warning(
                "[adobe-webhook] No OnboardingRecord found for person_id=%d",
                person_id,
            )

        _logger.info(
            "[adobe-webhook] Successfully processed: person_id=%d agreement_id=%s drug_test_signed_at=%s",
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
