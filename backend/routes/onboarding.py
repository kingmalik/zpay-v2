"""
Onboarding routes — driver onboarding automation for Z-Pay.

Prefix: /onboarding
All responses are JSON (pure API — consumed by Next.js frontend).

Steps tracked per driver:
    1. consent_form        — Adobe Sign e-sign
    2. priority_email      — auto-sent to admin@prioritysolutions.org after consent signed
    3. brandon_email       — manual 1-click to brandon@firstalt.com
    4. bgc                 — always manual (background check)
    5. drug_test           — always manual
    6. acumen_contract     — Adobe Sign e-sign
    7. files               — DL + vehicle registration + inspection upload
    8. paychex             — manual Paychex enrollment confirmation
"""

import hmac
import hashlib
import logging
import os
import base64
import secrets
import tempfile
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import Person, OnboardingRecord, OnboardingDocument

_logger = logging.getLogger("zpay.onboarding")

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _record_to_dict(rec: OnboardingRecord, person: Person | None = None) -> dict:
    """Convert an OnboardingRecord (+ optional Person) to a JSON-safe dict."""
    d = {
        "id": rec.id,
        "person_id": rec.person_id,
        # Flat person fields expected by the frontend OnboardingRecord interface
        "person_name": person.full_name if person else None,
        "person_email": person.email if person else None,
        "person_phone": person.phone if person else None,
        "person_language": person.language if person else None,
        "consent_status": rec.consent_status,
        "consent_envelope_id": rec.consent_envelope_id,
        "priority_email_status": rec.priority_email_status,
        "brandon_email_status": rec.brandon_email_status,
        "bgc_status": rec.bgc_status,
        "drug_test_status": rec.drug_test_status,
        "contract_status": rec.contract_status,
        "contract_envelope_id": rec.contract_envelope_id,
        "files_status": rec.files_status,
        "paychex_status": rec.paychex_status,
        "training_status": rec.training_status if hasattr(rec, "training_status") else "pending",
        "notes": rec.notes,
        "started_at": rec.started_at.isoformat() if rec.started_at else None,
        "completed_at": rec.completed_at.isoformat() if rec.completed_at else None,
        "invite_token": rec.invite_token if hasattr(rec, "invite_token") else None,
        "personal_info": rec.personal_info if hasattr(rec, "personal_info") else None,
    }
    if person:
        d["person"] = {
            "person_id": person.person_id,
            "full_name": person.full_name,
            "email": person.email,
            "phone": person.phone,
            "home_address": person.home_address,
            "vehicle_make": person.vehicle_make,
            "vehicle_model": person.vehicle_model,
            "vehicle_year": person.vehicle_year,
            "vehicle_plate": person.vehicle_plate,
            "vehicle_color": person.vehicle_color,
            "firstalt_driver_id": person.firstalt_driver_id,
            "everdriven_driver_id": person.everdriven_driver_id,
            "language": person.language,
        }
    return d


def _check_all_complete(rec: OnboardingRecord) -> bool:
    """Return True if every step is in a terminal state (complete/signed/manual counts as done)."""
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


# ---------------------------------------------------------------------------
# GET /onboarding/ — list all records
# ---------------------------------------------------------------------------

@router.get("/")
def list_onboarding(db: Session = Depends(get_db)):
    """List all onboarding records with person info and step statuses."""
    records = (
        db.query(OnboardingRecord)
        .order_by(OnboardingRecord.started_at.desc())
        .all()
    )
    person_ids = [r.person_id for r in records]
    persons = {p.person_id: p for p in db.query(Person).filter(Person.person_id.in_(person_ids)).all()}

    return JSONResponse([_record_to_dict(r, persons.get(r.person_id)) for r in records])


# ---------------------------------------------------------------------------
# GET /onboarding/{id} — single record
# ---------------------------------------------------------------------------

@router.get("/{onboarding_id}")
def get_onboarding(onboarding_id: int, db: Session = Depends(get_db)):
    """Get a single onboarding record with full detail."""
    rec = db.query(OnboardingRecord).filter(OnboardingRecord.id == onboarding_id).first()
    if not rec:
        return JSONResponse({"error": "Onboarding record not found"}, status_code=404)

    person = db.query(Person).filter(Person.person_id == rec.person_id).first()

    # Also fetch related documents
    docs = (
        db.query(OnboardingDocument)
        .filter(OnboardingDocument.onboarding_id == onboarding_id)
        .all()
    )
    doc_list = [
        {
            "id": d.id,
            "doc_type": d.doc_type,
            "envelope_id": d.envelope_id,
            "status": d.status,
            "sent_at": d.sent_at.isoformat() if d.sent_at else None,
            "signed_at": d.signed_at.isoformat() if d.signed_at else None,
            "signer_email": d.signer_email,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in docs
    ]

    data = _record_to_dict(rec, person)
    data["documents"] = doc_list
    return JSONResponse(data)


# ---------------------------------------------------------------------------
# Background task helpers — auto-triggered on onboarding start
# ---------------------------------------------------------------------------

def _auto_send_consent(rec_id: int) -> None:
    """
    Background task: fire Adobe Sign consent form immediately after onboarding starts.
    Only runs if ADOBE_SIGN_INTEGRATION_KEY is set. Never raises — all errors are logged.
    """
    adobe_key = os.environ.get("ADOBE_SIGN_INTEGRATION_KEY", "").strip()
    if not adobe_key:
        _logger.warning(
            "[auto-consent] ADOBE_SIGN_INTEGRATION_KEY not set — skipping auto-consent for onboarding_id=%d",
            rec_id,
        )
        return

    from backend.db import SessionLocal
    db = SessionLocal()
    try:
        rec = db.query(OnboardingRecord).filter(OnboardingRecord.id == rec_id).first()
        if not rec:
            _logger.error("[auto-consent] OnboardingRecord id=%d not found", rec_id)
            return

        if rec.consent_status not in ("pending", None):
            _logger.info("[auto-consent] Skipping — consent_status already=%r for id=%d", rec.consent_status, rec_id)
            return

        person = db.query(Person).filter(Person.person_id == rec.person_id).first()
        if not person or not person.email:
            _logger.warning(
                "[auto-consent] Driver has no email — cannot auto-send consent for onboarding_id=%d",
                rec_id,
            )
            return

        from backend.services import adobe_sign
        result = adobe_sign.send_envelope(
            signer_email=person.email,
            signer_name=person.full_name,
            doc_type="consent_form",
        )

        envelope_id = result.get("id")
        now = datetime.now(timezone.utc)

        rec.consent_envelope_id = envelope_id
        rec.consent_status = "sent"

        doc = OnboardingDocument(
            onboarding_id=rec.id,
            doc_type="consent_form",
            envelope_id=envelope_id,
            status="sent",
            sent_at=now,
            signer_email=person.email,
        )
        db.add(doc)
        db.commit()

        _logger.info(
            "[auto-consent] Consent form sent — onboarding_id=%d envelope_id=%s signer=%s",
            rec_id,
            envelope_id,
            person.email,
        )

    except Exception as exc:
        _logger.error("[auto-consent] Failed for onboarding_id=%d: %s", rec_id, exc)
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


def _auto_send_sms_portal_link(rec_id: int) -> None:
    """
    Background task: SMS the driver their onboarding portal link after start.
    Only runs if TWILIO_FROM_NUMBER is set. Never raises — all errors are logged.
    """
    from_number = os.environ.get("TWILIO_FROM_NUMBER", "").strip()
    if not from_number:
        _logger.warning(
            "[auto-sms] TWILIO_FROM_NUMBER not set — skipping portal SMS for onboarding_id=%d",
            rec_id,
        )
        return

    from backend.db import SessionLocal
    db = SessionLocal()
    try:
        rec = db.query(OnboardingRecord).filter(OnboardingRecord.id == rec_id).first()
        if not rec:
            _logger.error("[auto-sms] OnboardingRecord id=%d not found", rec_id)
            return

        person = db.query(Person).filter(Person.person_id == rec.person_id).first()
        if not person or not person.phone:
            _logger.warning(
                "[auto-sms] Driver has no phone — cannot auto-send portal SMS for onboarding_id=%d",
                rec_id,
            )
            return

        invite_token = rec.invite_token
        if not invite_token:
            _logger.warning("[auto-sms] No invite_token on record id=%d — skipping SMS", rec_id)
            return

        frontend_url = os.environ.get("FRONTEND_URL", "").rstrip("/")
        portal_link = f"{frontend_url}/join/{invite_token}" if frontend_url else f"/join/{invite_token}"

        driver_first = (person.full_name or "").split()[0] if person.full_name else "there"
        message = (
            f"Hi {driver_first}, welcome to MAZ Services! "
            f"Complete your driver onboarding here: {portal_link}"
        )

        from backend.services import notification_service
        sid = notification_service.send_sms(person.phone, message)

        if sid:
            _logger.info(
                "[auto-sms] Portal link SMS sent — onboarding_id=%d phone=%s sid=%s",
                rec_id,
                person.phone,
                sid,
            )
        else:
            _logger.warning(
                "[auto-sms] SMS send returned None — onboarding_id=%d phone=%s",
                rec_id,
                person.phone,
            )

    except Exception as exc:
        _logger.error("[auto-sms] Failed for onboarding_id=%d: %s", rec_id, exc)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# POST /onboarding/start — create a new onboarding record
# ---------------------------------------------------------------------------

@router.post("/start")
async def start_onboarding(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Create an OnboardingRecord for a driver.

    Body: { "person_id": <int> }
    """
    body = await request.json()
    person_id = body.get("person_id")
    if not person_id:
        return JSONResponse({"error": "person_id is required"}, status_code=400)

    person = db.query(Person).filter(Person.person_id == person_id).first()
    if not person:
        return JSONResponse({"error": f"Person {person_id} not found"}, status_code=404)

    # Idempotent — return existing record if already started
    existing = db.query(OnboardingRecord).filter(OnboardingRecord.person_id == person_id).first()
    if existing:
        return JSONResponse(
            {"ok": True, "already_exists": True, **_record_to_dict(existing, person)},
            status_code=200,
        )

    from sqlalchemy.exc import IntegrityError

    rec = OnboardingRecord(person_id=person_id)
    rec.invite_token = secrets.token_urlsafe(32)
    try:
        db.add(rec)
        db.commit()
        db.refresh(rec)
    except IntegrityError:
        db.rollback()
        return JSONResponse({"error": "Onboarding already started for this person"}, status_code=409)

    _logger.info("Onboarding started for person_id=%d (record id=%d)", person_id, rec.id)

    # Auto-trigger: fire consent form + portal link SMS in background (non-blocking)
    background_tasks.add_task(_auto_send_consent, rec.id)
    background_tasks.add_task(_auto_send_sms_portal_link, rec.id)

    return JSONResponse(_record_to_dict(rec, person), status_code=201)


# ---------------------------------------------------------------------------
# POST /onboarding/{id}/send-consent
# ---------------------------------------------------------------------------

@router.post("/{onboarding_id}/send-consent")
def send_consent(onboarding_id: int, db: Session = Depends(get_db)):
    """Send the consent form envelope via Adobe Sign."""
    rec = db.query(OnboardingRecord).filter(OnboardingRecord.id == onboarding_id).first()
    if not rec:
        return JSONResponse({"error": "Onboarding record not found"}, status_code=404)

    person = db.query(Person).filter(Person.person_id == rec.person_id).first()
    if not person:
        return JSONResponse({"error": "Driver person record not found"}, status_code=404)

    if not person.email:
        return JSONResponse({"error": "Driver has no email address on file"}, status_code=400)

    try:
        from backend.services import adobe_sign
        result = adobe_sign.send_envelope(
            signer_email=person.email,
            signer_name=person.full_name,
            doc_type="consent_form",
        )
    except Exception as exc:
        _logger.error("Adobe Sign send_consent failed for onboarding_id=%d: %s", onboarding_id, exc)
        return JSONResponse({"error": str(exc)}, status_code=502)

    envelope_id = result.get("id")
    now = datetime.now(timezone.utc)

    # Update the parent record
    rec.consent_envelope_id = envelope_id
    rec.consent_status = "sent"

    # Create an OnboardingDocument tracking row
    doc = OnboardingDocument(
        onboarding_id=rec.id,
        doc_type="consent_form",
        envelope_id=envelope_id,
        status="sent",
        sent_at=now,
        signer_email=person.email,
    )
    db.add(doc)
    db.commit()
    db.refresh(rec)

    return JSONResponse({
        "ok": True,
        "envelope_id": envelope_id,
        "consent_status": rec.consent_status,
        "adobe_response": result,
    })


# ---------------------------------------------------------------------------
# POST /onboarding/{id}/send-contract
# ---------------------------------------------------------------------------

@router.post("/{onboarding_id}/send-contract")
def send_contract(onboarding_id: int, db: Session = Depends(get_db)):
    """Send the Acumen driver contract envelope via Adobe Sign."""
    rec = db.query(OnboardingRecord).filter(OnboardingRecord.id == onboarding_id).first()
    if not rec:
        return JSONResponse({"error": "Onboarding record not found"}, status_code=404)

    person = db.query(Person).filter(Person.person_id == rec.person_id).first()
    if not person:
        return JSONResponse({"error": "Driver person record not found"}, status_code=404)

    if not person.email:
        return JSONResponse({"error": "Driver has no email address on file"}, status_code=400)

    try:
        from backend.services import adobe_sign
        result = adobe_sign.send_envelope(
            signer_email=person.email,
            signer_name=person.full_name,
            doc_type="acumen_contract",
        )
    except Exception as exc:
        _logger.error("Adobe Sign send_contract failed for onboarding_id=%d: %s", onboarding_id, exc)
        return JSONResponse({"error": str(exc)}, status_code=502)

    envelope_id = result.get("id")
    now = datetime.now(timezone.utc)

    rec.contract_envelope_id = envelope_id
    rec.contract_status = "sent"

    doc = OnboardingDocument(
        onboarding_id=rec.id,
        doc_type="acumen_contract",
        envelope_id=envelope_id,
        status="sent",
        sent_at=now,
        signer_email=person.email,
    )
    db.add(doc)
    db.commit()
    db.refresh(rec)

    return JSONResponse({
        "ok": True,
        "envelope_id": envelope_id,
        "contract_status": rec.contract_status,
        "adobe_response": result,
    })


# ---------------------------------------------------------------------------
# POST /onboarding/{id}/mark-brandon-sent
# ---------------------------------------------------------------------------

@router.post("/{onboarding_id}/mark-brandon-sent")
def mark_brandon_sent(onboarding_id: int, db: Session = Depends(get_db)):
    """Mark the Brandon (FirstAlt) email as sent."""
    rec = db.query(OnboardingRecord).filter(OnboardingRecord.id == onboarding_id).first()
    if not rec:
        return JSONResponse({"error": "Onboarding record not found"}, status_code=404)

    rec.brandon_email_status = "complete"
    if _check_all_complete(rec):
        rec.completed_at = datetime.now(timezone.utc)
    db.commit()

    return JSONResponse({"ok": True, "brandon_email_status": rec.brandon_email_status})


# ---------------------------------------------------------------------------
# POST /onboarding/{id}/mark-bgc-sent
# ---------------------------------------------------------------------------

@router.post("/{onboarding_id}/mark-bgc-sent")
def mark_bgc_sent(onboarding_id: int, db: Session = Depends(get_db)):
    """Mark the background check as sent/ordered."""
    rec = db.query(OnboardingRecord).filter(OnboardingRecord.id == onboarding_id).first()
    if not rec:
        return JSONResponse({"error": "Onboarding record not found"}, status_code=404)

    rec.bgc_status = "complete"
    if _check_all_complete(rec):
        rec.completed_at = datetime.now(timezone.utc)
    db.commit()

    return JSONResponse({"ok": True, "bgc_status": rec.bgc_status})


# ---------------------------------------------------------------------------
# POST /onboarding/{id}/mark-drug-test-done
# ---------------------------------------------------------------------------

@router.post("/{onboarding_id}/mark-drug-test-done")
def mark_drug_test_done(onboarding_id: int, db: Session = Depends(get_db)):
    """Mark the drug test as completed."""
    rec = db.query(OnboardingRecord).filter(OnboardingRecord.id == onboarding_id).first()
    if not rec:
        return JSONResponse({"error": "Onboarding record not found"}, status_code=404)

    rec.drug_test_status = "complete"
    if _check_all_complete(rec):
        rec.completed_at = datetime.now(timezone.utc)
    db.commit()

    return JSONResponse({"ok": True, "drug_test_status": rec.drug_test_status})


# ---------------------------------------------------------------------------
# POST /onboarding/{id}/mark-paychex-done
# ---------------------------------------------------------------------------

@router.post("/{onboarding_id}/mark-paychex-done")
def mark_paychex_done(onboarding_id: int, db: Session = Depends(get_db)):
    """Mark the Paychex enrollment as complete."""
    rec = db.query(OnboardingRecord).filter(OnboardingRecord.id == onboarding_id).first()
    if not rec:
        return JSONResponse({"error": "Onboarding record not found"}, status_code=404)

    rec.paychex_status = "complete"
    if _check_all_complete(rec):
        rec.completed_at = datetime.now(timezone.utc)
    db.commit()

    return JSONResponse({"ok": True, "paychex_status": rec.paychex_status})


# ---------------------------------------------------------------------------
# POST /onboarding/{id}/mark-training-complete
# ---------------------------------------------------------------------------

@router.post("/{onboarding_id}/mark-training-complete")
def mark_training_complete(onboarding_id: int, db: Session = Depends(get_db)):
    """Mark the training step as complete (admin manual confirmation)."""
    rec = db.query(OnboardingRecord).filter(OnboardingRecord.id == onboarding_id).first()
    if not rec:
        return JSONResponse({"error": "Onboarding record not found"}, status_code=404)

    rec.training_status = "complete"
    if _check_all_complete(rec):
        rec.completed_at = datetime.now(timezone.utc)
    db.commit()

    return JSONResponse({"ok": True, "training_status": rec.training_status})


# ---------------------------------------------------------------------------
# GET /onboarding/{id}/brandon-email — pre-filled email data
# ---------------------------------------------------------------------------

@router.get("/{onboarding_id}/brandon-email")
def brandon_email_data(onboarding_id: int, db: Session = Depends(get_db)):
    """
    Return pre-filled email data for the 1-click Brandon (FirstAlt) email.

    Response: { to, subject, body }
    """
    rec = db.query(OnboardingRecord).filter(OnboardingRecord.id == onboarding_id).first()
    if not rec:
        return JSONResponse({"error": "Onboarding record not found"}, status_code=404)

    person = db.query(Person).filter(Person.person_id == rec.person_id).first()
    if not person:
        return JSONResponse({"error": "Driver person record not found"}, status_code=404)

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

    subject = f"New Driver Onboarding — {name}"

    body = f"""Hi Brandon,

Please find the details below for a new driver we are onboarding. Kindly add them to your system at your earliest convenience.

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
Maz Services
"""

    return JSONResponse({
        "to": "brandon@firstalt.com",
        "subject": subject,
        "body": body,
    })


# ---------------------------------------------------------------------------
# POST /onboarding/webhook/adobe-sign — Adobe Sign event webhook
# ---------------------------------------------------------------------------

@router.post("/webhook/adobe-sign")
async def adobe_sign_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Handle Adobe Sign webhook events.

    Adobe Sign sends a JSON payload. We look for:
      - event == "AGREEMENT_WORKFLOW_COMPLETE"
      - or participantSet[*].memberInfos[*].status == "SIGNED"

    On consent form signed:
        1. Update OnboardingDocument status → "signed"
        2. Update OnboardingRecord consent_status → "signed"
        3. Download PDF → send to admin@prioritysolutions.org via Gmail
        4. Check if all steps complete

    On contract signed:
        1. Update OnboardingDocument status → "signed"
        2. Update OnboardingRecord contract_status → "signed"
        3. Check if all steps complete
    """
    # Verify Adobe Sign HMAC signature if key is configured
    webhook_key = os.environ.get("ADOBE_SIGN_WEBHOOK_KEY", "")
    if webhook_key:
        client_id = request.headers.get("X-ADOBESIGN-CLIENTID", "")
        if not hmac.compare_digest(client_id, webhook_key):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON payload"}, status_code=400)

    event = payload.get("event", "")
    agreement = payload.get("agreement", payload.get("agreementAssetInfo", {}))
    agreement_id = (
        agreement.get("id")
        or agreement.get("agreementId")
        or payload.get("agreementId")
        or ""
    )

    # Determine if this is a signing-complete event
    is_signed_event = event in (
        "AGREEMENT_WORKFLOW_COMPLETE",
        "AGREEMENT_ACTION_COMPLETED",
        "ESIGNED",
    )

    # Also check participant status
    if not is_signed_event:
        for pset in payload.get("participantSetsInfo", []):
            for member in pset.get("memberInfos", []):
                if member.get("status") in ("SIGNED", "SIGNED_BY_SIGNER"):
                    is_signed_event = True
                    break

    if not agreement_id:
        _logger.warning("Adobe Sign webhook received with no agreement_id. Payload keys: %s", list(payload.keys()))
        return JSONResponse({"ok": True, "skipped": "no_agreement_id"})

    if not is_signed_event:
        _logger.info("Adobe Sign webhook event=%r for agreement=%s — not a signing event, ignoring", event, agreement_id)
        return JSONResponse({"ok": True, "skipped": "not_a_signing_event", "event": event})

    # Find the OnboardingDocument for this envelope
    doc = db.query(OnboardingDocument).filter(OnboardingDocument.envelope_id == agreement_id).first()
    if not doc:
        _logger.warning("Adobe Sign webhook: no OnboardingDocument found for envelope_id=%s", agreement_id)
        return JSONResponse({"ok": True, "skipped": "document_not_found", "agreement_id": agreement_id})

    now = datetime.now(timezone.utc)
    doc.status = "signed"
    doc.signed_at = now

    # Update parent OnboardingRecord
    rec = db.query(OnboardingRecord).filter(OnboardingRecord.id == doc.onboarding_id).first()
    if not rec:
        db.commit()
        return JSONResponse({"ok": True, "warning": "onboarding_record_not_found"})

    if doc.doc_type == "consent_form":
        rec.consent_status = "signed"
        _handle_consent_signed(rec, agreement_id, db)
    elif doc.doc_type == "acumen_contract":
        rec.contract_status = "signed"

    # Check overall completion
    if _check_all_complete(rec):
        rec.completed_at = now
        _logger.info("Onboarding record id=%d marked COMPLETE", rec.id)

    db.commit()

    return JSONResponse({
        "ok": True,
        "agreement_id": agreement_id,
        "doc_type": doc.doc_type,
        "status": "signed",
    })


def _handle_consent_signed(rec: OnboardingRecord, agreement_id: str, db: Session) -> None:
    """
    After consent form is signed:
    1. Download the signed PDF from Adobe Sign.
    2. Email it to admin@prioritysolutions.org via Gmail (Acumen account).
    3. Update priority_email_status on the record.
    """
    person = db.query(Person).filter(Person.person_id == rec.person_id).first()
    driver_name = person.full_name if person else f"Driver #{rec.person_id}"

    # --- Download signed PDF ---
    try:
        from backend.services import adobe_sign
        pdf_bytes = adobe_sign.download_signed_document(agreement_id)
    except Exception as exc:
        _logger.error(
            "Failed to download signed consent PDF for agreement_id=%s: %s",
            agreement_id,
            exc,
        )
        rec.priority_email_status = "manual"
        return

    # --- Send to Priority Solutions admin ---
    admin_email = "admin@prioritysolutions.org"
    try:
        _send_consent_pdf_email(
            to_email=admin_email,
            driver_name=driver_name,
            pdf_bytes=pdf_bytes,
            agreement_id=agreement_id,
        )
        rec.priority_email_status = "complete"
        _logger.info(
            "Consent PDF emailed to %s for driver %s (agreement_id=%s)",
            admin_email,
            driver_name,
            agreement_id,
        )
    except Exception as exc:
        _logger.error(
            "Failed to email consent PDF to %s for agreement_id=%s: %s",
            admin_email,
            agreement_id,
            exc,
        )
        rec.priority_email_status = "manual"


def _send_consent_pdf_email(
    to_email: str,
    driver_name: str,
    pdf_bytes: bytes,
    agreement_id: str,
) -> None:
    """
    Send the signed consent PDF to the Priority Solutions admin inbox.
    Uses the Gmail service (Acumen account — firstalt / acumen company key).
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
            "Gmail credentials not fully configured. "
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

    subject = f"Signed Consent Form — {driver_name}"
    plain_body = (
        f"Hi,\n\n"
        f"The consent form for {driver_name} has been signed.\n"
        f"Please find the signed PDF attached.\n\n"
        f"Adobe Sign Agreement ID: {agreement_id}\n\n"
        f"— Z-Pay Onboarding System"
    )
    filename = f"consent_form_{driver_name.replace(' ', '_')}.pdf"

    msg = MIMEMultipart("mixed")
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(alt)

    part = MIMEBase("application", "pdf")
    part.set_payload(pdf_bytes)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
    msg.attach(part)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    service.users().messages().send(userId="me", body={"raw": raw}).execute()


# ---------------------------------------------------------------------------
# PUBLIC routes — no auth required (driver self-onboarding portal)
# These are registered on a separate router so auth middleware skips them.
# ---------------------------------------------------------------------------

public_router = APIRouter(prefix="/onboarding/join", tags=["onboarding-public"])


@public_router.get("/{token}")
def join_get(token: str, db: Session = Depends(get_db)):
    """
    Public — returns onboarding record + person details for the given invite token.
    Used by the driver-facing portal page.
    """
    from datetime import timezone, timedelta
    TOKEN_EXPIRY_DAYS = 30

    rec = db.query(OnboardingRecord).filter(OnboardingRecord.invite_token == token).first()
    if not rec:
        return JSONResponse({"error": "Link expired or invalid"}, status_code=404)

    if rec.started_at:
        # Handle both timezone-aware and naive datetimes safely
        started = rec.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        else:
            started = started.astimezone(timezone.utc)
        age = datetime.now(timezone.utc) - started
        if age.days > TOKEN_EXPIRY_DAYS:
            return JSONResponse({"error": "Link expired or invalid"}, status_code=404)

    person = db.query(Person).filter(Person.person_id == rec.person_id).first()
    return JSONResponse({
        "id": rec.id,
        "person_name": person.full_name if person else None,
        "person_email": person.email if person else None,
        "person_phone": person.phone if person else None,
        "consent_status": rec.consent_status,
        "priority_email_status": rec.priority_email_status,
        "brandon_email_status": rec.brandon_email_status,
        "bgc_status": rec.bgc_status,
        "drug_test_status": rec.drug_test_status,
        "contract_status": rec.contract_status,
        "files_status": rec.files_status,
        "paychex_status": rec.paychex_status,
        "notes": rec.notes,
        "started_at": rec.started_at.isoformat() if rec.started_at else None,
        "completed_at": rec.completed_at.isoformat() if rec.completed_at else None,
        "invite_token": rec.invite_token,
        "personal_info": rec.personal_info,
        "person": {
            "language": person.language if person else None,
        },
    })


def _notify_admin_personal_info(driver_name: str) -> None:
    """Background task: SMS admin when a driver submits their personal info."""
    admin_phone = os.environ.get("ADMIN_PHONE", "").strip()
    if not admin_phone:
        _logger.warning("[admin-notify] ADMIN_PHONE not set — skipping intake notification")
        return
    try:
        from backend.services import notification_service
        notification_service.send_sms(
            admin_phone,
            f"Z Pay: {driver_name} just completed their onboarding intake. Check the portal to proceed.",
        )
    except Exception as e:
        _logger.warning("Failed to notify admin of personal info submission: %s", e)


@public_router.post("/{token}/step")
async def join_submit_step(token: str, request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Public — driver submits data for a step.
    Body: { "step": "personal_info" | "consent" | etc, "data": {...} }
    """
    rec = db.query(OnboardingRecord).filter(OnboardingRecord.invite_token == token).first()
    if not rec:
        return JSONResponse({"error": "Link expired or invalid"}, status_code=404)

    body = await request.json()
    step = body.get("step")
    data = body.get("data", {})

    ALLOWED_PERSONAL_INFO_FIELDS = {
        "full_name", "address", "dob", "emergency_name", "emergency_phone"
    }
    MAX_FIELD_LENGTH = 500

    if step == "personal_info":
        # Validate and sanitize — only allow known fields, cap field length
        filtered = {k: str(v)[:MAX_FIELD_LENGTH] for k, v in data.items() if k in ALLOWED_PERSONAL_INFO_FIELDS}
        if len(str(filtered)) > 5000:  # total payload cap
            return JSONResponse({"error": "Data too large"}, status_code=400)
        rec.personal_info = filtered
        db.commit()
        db.refresh(rec)
        person = db.query(Person).filter(Person.person_id == rec.person_id).first()

        driver_name = person.full_name if person else f"Driver #{rec.person_id}"
        _logger.info("Driver %s submitted personal info for onboarding record %d", driver_name, rec.id)

        # Notify admin via SMS in background — never crash the main request
        background_tasks.add_task(_notify_admin_personal_info, driver_name)

        return JSONResponse({"ok": True, **_record_to_dict(rec, person)})

    return JSONResponse({"error": f"Unknown step: {step}"}, status_code=400)


@public_router.get("/{token}/link")
def join_get_link(token: str, request: Request, db: Session = Depends(get_db)):
    """
    Public — returns the shareable URL for this token.
    Used by the admin copy button.
    """
    rec = db.query(OnboardingRecord).filter(OnboardingRecord.invite_token == token).first()
    if not rec:
        return JSONResponse({"error": "Link expired or invalid"}, status_code=404)

    base_url = str(request.base_url).rstrip("/")
    return JSONResponse({"url": f"{base_url}/join/{token}"})
