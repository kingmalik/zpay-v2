"""
Onboarding routes — driver onboarding automation for Z-Pay.

Prefix: /onboarding
All responses are JSON (pure API — consumed by Next.js frontend).

Steps tracked per driver:
    1. firstalt_invite     — send driver FirstAlt app link (repurposed from priority_email_status)
    2. bgc                 — background check (Brandon at FirstAlt triggers)
    3. drug_test_consent   — drug test consent form signed digitally, emailed to Donna at Concentra
    4. drug_test           — Donna handles, emails results back
    5. firstalt_training   — class on FirstAlt app
    6. files               — documents uploaded to FirstAlt + backup copies in Z Pay
    7. partner_contract    — Acumen (FirstAlt) or Maz (EverDriven) contract
    8. maz_training        — interactive training slides in Z Pay
    9. maz_contract        — internal Maz contract, driver signs digitally
   10. paychex_w9          — Paychex enrollment + W-9 form
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
from backend.db.models import Person, OnboardingRecord, OnboardingDocument, OnboardingFile
from backend.utils.test_mode import redirect_email, test_subject

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
        "firstalt_invite_status": rec.priority_email_status,  # repurposed
        "priority_email_status": rec.priority_email_status,
        "brandon_email_status": rec.brandon_email_status,
        "bgc_status": rec.bgc_status,
        "drug_test_status": rec.drug_test_status,
        "contract_status": rec.contract_status,
        "contract_envelope_id": rec.contract_envelope_id,
        "files_status": rec.files_status,
        "paychex_status": rec.paychex_status,
        "training_status": rec.training_status,
        "maz_training_status": rec.maz_training_status if hasattr(rec, "maz_training_status") else "pending",
        "maz_contract_status": rec.maz_contract_status if hasattr(rec, "maz_contract_status") else "pending",
        "notes": rec.notes,
        "started_at": rec.started_at.isoformat() if rec.started_at else None,
        "completed_at": rec.completed_at.isoformat() if rec.completed_at else None,
        "invite_token": rec.invite_token if hasattr(rec, "invite_token") else None,
        "personal_info": rec.personal_info if hasattr(rec, "personal_info") else None,
        "intake_submitted_at": rec.intake_submitted_at.isoformat() if hasattr(rec, "intake_submitted_at") and rec.intake_submitted_at else None,
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


# ---------------------------------------------------------------------------
# GET /onboarding/ — list all records
# ---------------------------------------------------------------------------

@router.get("/contracts/list")
def list_signed_contracts(db: Session = Depends(get_db)):
    """
    List all signed contract/consent PDFs stored in R2.
    Returns presigned download URLs valid for 1 hour.
    Used by the mom's Mac sync agent to auto-download new contracts locally.
    """
    from backend.services import r2_storage

    files = (
        db.query(OnboardingFile)
        .filter(OnboardingFile.file_type.in_(["signed_consent_form", "signed_contract"]))
        .filter(OnboardingFile.r2_key.isnot(None))
        .order_by(OnboardingFile.uploaded_at.desc())
        .all()
    )

    result = []
    for f in files:
        rec = db.query(OnboardingRecord).filter(OnboardingRecord.id == f.onboarding_id).first()
        person = db.query(Person).filter(Person.person_id == rec.person_id).first() if rec else None
        try:
            url = r2_storage.get_presigned_url(f.r2_key, expires_in=3600)
        except Exception:
            url = None
        result.append({
            "id": f.id,
            "onboarding_id": f.onboarding_id,
            "file_type": f.file_type,
            "filename": f.filename,
            "r2_key": f.r2_key,
            "download_url": url,
            "uploaded_at": f.uploaded_at.isoformat() if f.uploaded_at else None,
            "driver_name": person.full_name if person else None,
        })

    return JSONResponse(result)


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
            "[auto-consent] ADOBE_SIGN_INTEGRATION_KEY not set — entering MANUAL MODE for onboarding_id=%d. "
            "Admin must send consent form via email manually.",
            rec_id,
        )
        # Mark as manual so admin knows to handle it and the flow is not blocked
        from backend.db import SessionLocal as _SL
        _db = _SL()
        try:
            _rec = _db.query(OnboardingRecord).filter(OnboardingRecord.id == rec_id).first()
            if _rec and _rec.consent_status in ("pending", None):
                _rec.consent_status = "manual"
                _rec.notes = (_rec.notes or "") + " [MANUAL] Consent form: Adobe Sign unavailable — send via email. "
                _db.commit()
                _logger.info("[auto-consent] consent_status set to 'manual' for onboarding_id=%d", rec_id)
        except Exception as _exc:
            _logger.error("[auto-consent] Failed to set manual status for onboarding_id=%d: %s", rec_id, _exc)
            _db.rollback()
        finally:
            _db.close()
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

    return JSONResponse(_record_to_dict(rec, person), status_code=201)


# ---------------------------------------------------------------------------
# POST /onboarding/{id}/regenerate-token
# ---------------------------------------------------------------------------

@router.post("/{onboarding_id}/regenerate-token")
def regenerate_invite_token(onboarding_id: int, db: Session = Depends(get_db)):
    """Generate (or regenerate) an invite_token for an onboarding record.
    Needed for records created before invite_token was introduced (NULL token).
    """
    rec = db.query(OnboardingRecord).filter(OnboardingRecord.id == onboarding_id).first()
    if not rec:
        return JSONResponse({"error": "Not found"}, status_code=404)
    rec.invite_token = secrets.token_urlsafe(32)
    db.commit()
    db.refresh(rec)
    return JSONResponse({"ok": True, "invite_token": rec.invite_token, "onboarding_id": rec.id})


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

    # Check if Adobe Sign is available
    adobe_key = os.environ.get("ADOBE_SIGN_INTEGRATION_KEY", "").strip()
    if not adobe_key:
        _logger.warning(
            "Adobe Sign unavailable (no integration key) — marking consent as MANUAL for onboarding_id=%d. "
            "Admin must send consent form to %s via email.",
            onboarding_id,
            person.email,
        )
        rec.consent_status = "manual"
        rec.notes = (rec.notes or "") + " [MANUAL] Consent form: Adobe Sign unavailable — send via email. "
        db.commit()
        db.refresh(rec)
        return JSONResponse({
            "ok": True,
            "manual_mode": True,
            "message": f"Adobe Sign is not configured. Please send the consent form to {person.email} manually via email.",
            "consent_status": "manual",
            "driver_email": person.email,
            "driver_name": person.full_name,
        })

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

    # Check if Adobe Sign is available
    adobe_key = os.environ.get("ADOBE_SIGN_INTEGRATION_KEY", "").strip()
    if not adobe_key:
        _logger.warning(
            "Adobe Sign unavailable (no integration key) — marking contract as MANUAL for onboarding_id=%d. "
            "Admin must send Acumen contract to %s via email.",
            onboarding_id,
            person.email,
        )
        rec.contract_status = "manual"
        rec.notes = (rec.notes or "") + " [MANUAL] Contract: Adobe Sign unavailable — send via email. "
        db.commit()
        db.refresh(rec)
        return JSONResponse({
            "ok": True,
            "manual_mode": True,
            "message": f"Adobe Sign is not configured. Please send the Acumen contract to {person.email} manually via email.",
            "contract_status": "manual",
            "driver_email": person.email,
            "driver_name": person.full_name,
        })

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
# POST /onboarding/{id}/mark-firstalt-invited
# ---------------------------------------------------------------------------

@router.post("/{onboarding_id}/mark-firstalt-invited")
def mark_firstalt_invited(onboarding_id: int, db: Session = Depends(get_db)):
    """Mark the FirstAlt invite as sent."""
    rec = db.query(OnboardingRecord).filter(OnboardingRecord.id == onboarding_id).first()
    if not rec:
        return JSONResponse({"error": "Onboarding record not found"}, status_code=404)

    rec.priority_email_status = "complete"
    if _check_all_complete(rec):
        rec.completed_at = datetime.now(timezone.utc)
    db.commit()

    return JSONResponse({"ok": True, "firstalt_invite_status": rec.priority_email_status})


# ---------------------------------------------------------------------------
# POST /onboarding/{id}/mark-consent-signed
# ---------------------------------------------------------------------------

@router.post("/{onboarding_id}/mark-consent-signed")
def mark_consent_signed(onboarding_id: int, db: Session = Depends(get_db)):
    """Mark the drug test consent form as signed."""
    rec = db.query(OnboardingRecord).filter(OnboardingRecord.id == onboarding_id).first()
    if not rec:
        return JSONResponse({"error": "Onboarding record not found"}, status_code=404)

    rec.consent_status = "complete"
    if _check_all_complete(rec):
        rec.completed_at = datetime.now(timezone.utc)
    db.commit()

    return JSONResponse({"ok": True, "consent_status": rec.consent_status})


# ---------------------------------------------------------------------------
# POST /onboarding/{id}/mark-maz-training-complete
# ---------------------------------------------------------------------------

@router.post("/{onboarding_id}/mark-maz-training-complete")
def mark_maz_training_complete(onboarding_id: int, db: Session = Depends(get_db)):
    """Mark the MAZ training as complete."""
    rec = db.query(OnboardingRecord).filter(OnboardingRecord.id == onboarding_id).first()
    if not rec:
        return JSONResponse({"error": "Onboarding record not found"}, status_code=404)

    rec.maz_training_status = "complete"
    if _check_all_complete(rec):
        rec.completed_at = datetime.now(timezone.utc)
    db.commit()

    return JSONResponse({"ok": True, "maz_training_status": rec.maz_training_status})


# ---------------------------------------------------------------------------
# POST /onboarding/{id}/mark-maz-contract-signed
# ---------------------------------------------------------------------------

@router.post("/{onboarding_id}/mark-maz-contract-signed")
def mark_maz_contract_signed(onboarding_id: int, db: Session = Depends(get_db)):
    """Mark the MAZ contract as signed."""
    rec = db.query(OnboardingRecord).filter(OnboardingRecord.id == onboarding_id).first()
    if not rec:
        return JSONResponse({"error": "Onboarding record not found"}, status_code=404)

    rec.maz_contract_status = "signed"
    if _check_all_complete(rec):
        rec.completed_at = datetime.now(timezone.utc)
    db.commit()

    return JSONResponse({"ok": True, "maz_contract_status": rec.maz_contract_status})


# ---------------------------------------------------------------------------
# POST /onboarding/{id}/dev-skip-step — DEV ONLY: advance current pending step
# ---------------------------------------------------------------------------

@router.post("/{onboarding_id}/dev-skip-step")
def dev_skip_step(onboarding_id: int, db: Session = Depends(get_db)):
    """DEV ONLY — marks the first pending step as complete so you can test each stage."""
    rec = db.query(OnboardingRecord).filter(OnboardingRecord.id == onboarding_id).first()
    if not rec:
        return JSONResponse({"error": "Not found"}, status_code=404)

    terminal = {"complete", "signed", "manual", "skipped"}
    skipped = None

    fa_status = rec.priority_email_status or "pending"
    if fa_status not in terminal:
        rec.priority_email_status = "complete"
        skipped = "firstalt_invite"
    elif (rec.bgc_status or "pending") not in terminal:
        rec.bgc_status = "complete"
        skipped = "bgc"
    elif (rec.consent_status or "pending") not in terminal:
        rec.consent_status = "signed"
        skipped = "consent"
    elif (rec.drug_test_status or "pending") not in terminal:
        rec.drug_test_status = "complete"
        skipped = "drug_test"
    elif (rec.training_status or "pending") not in terminal:
        rec.training_status = "complete"
        skipped = "training"
    elif (rec.files_status or "pending") not in terminal:
        rec.files_status = "complete"
        skipped = "files"
    elif (rec.contract_status or "pending") not in terminal:
        rec.contract_status = "signed"
        skipped = "contract"
    elif (rec.maz_training_status or "pending") not in terminal:
        rec.maz_training_status = "complete"
        skipped = "maz_training"
    elif (rec.maz_contract_status or "pending") not in terminal:
        rec.maz_contract_status = "signed"
        skipped = "maz_contract"
    elif (rec.paychex_status or "pending") not in terminal:
        rec.paychex_status = "complete"
        skipped = "paychex"

    if _check_all_complete(rec):
        rec.completed_at = datetime.now(timezone.utc)

    db.commit()
    return JSONResponse({"ok": True, "skipped_step": skipped})


# ---------------------------------------------------------------------------
# POST /onboarding/{id}/set-notes — update admin notes
# ---------------------------------------------------------------------------

@router.post("/{onboarding_id}/set-notes")
async def set_notes(onboarding_id: int, request: Request, db: Session = Depends(get_db)):
    """Update admin notes on an onboarding record."""
    body = await request.json()
    notes = body.get("notes", "")

    rec = db.query(OnboardingRecord).filter(OnboardingRecord.id == onboarding_id).first()
    if not rec:
        return JSONResponse({"error": "Onboarding record not found"}, status_code=404)

    rec.notes = notes
    db.commit()

    return JSONResponse({"ok": True, "notes": rec.notes})


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
        "to": "Branden.Seeberger@firststudentinc.com",
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
    2. Save to R2 (primary storage) + create OnboardingFile record.
    3. Email it to admin@prioritysolutions.org via Gmail (Acumen account).
    4. Update priority_email_status on the record.
    """
    from backend.services import adobe_sign
    from backend.services import r2_storage

    person = db.query(Person).filter(Person.person_id == rec.person_id).first()
    driver_name = person.full_name if person else f"Driver #{rec.person_id}"

    # --- Download signed PDF ---
    try:
        pdf_bytes = adobe_sign.download_signed_document(agreement_id)
    except Exception as exc:
        _logger.error(
            "Failed to download signed consent PDF for agreement_id=%s: %s",
            agreement_id,
            exc,
        )
        rec.priority_email_status = "manual"
        return

    # --- Save to R2 ---
    r2_key = None
    safe_name = (driver_name or f"driver_{rec.person_id}").replace(" ", "_")
    try:
        if r2_storage.r2_configured():
            r2_key = f"contracts/{rec.id}/consent_form_{safe_name}.pdf"
            r2_storage.upload_file(pdf_bytes, r2_key, content_type="application/pdf")
            file_record = OnboardingFile(
                onboarding_id=rec.id,
                file_type="signed_consent_form",
                r2_key=r2_key,
                filename=f"consent_form_{safe_name}.pdf",
                uploaded_at=datetime.now(timezone.utc),
            )
            db.add(file_record)
            db.flush()
            _logger.info("Consent PDF saved to R2: key=%s", r2_key)
        else:
            _logger.warning("R2 not configured — consent PDF not saved to cloud storage")
    except Exception as exc:
        _logger.error("Failed to save consent PDF to R2 for agreement_id=%s: %s", agreement_id, exc)

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
    # TEST MODE: redirect recipient and prefix subject
    to_email = redirect_email(to_email)

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

    subject = test_subject(f"Signed Consent Form — {driver_name}")
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

    # DEV preview token — returns mock data so all driver pages can be tested without a real record
    # All steps start as "pending" so you can walk the full flow from step 1
    if token == "dev":
        return JSONResponse({
            "id": 0,
            "person_name": "Test Driver",
            "person_language": "en",
            "person_email": "testdriver@example.com",
            "person_phone": "206-555-0100",
            "consent_status": "pending",
            "firstalt_invite_status": "pending",
            "priority_email_status": "pending",
            "brandon_email_status": "pending",
            "bgc_status": "pending",
            "drug_test_status": "pending",
            "contract_status": "pending",
            "files_status": "pending",
            "paychex_status": "pending",
            "training_status": "pending",
            "maz_training_status": "pending",
            "maz_contract_status": "pending",
            "notes": None,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
            "invite_token": "dev",
            "personal_info": None,
            "intake_submitted_at": None,
            "person": {"language": "en"},
        })

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
        "person_language": person.language if person else None,
        "person_email": person.email if person else None,
        "person_phone": person.phone if person else None,
        "consent_status": rec.consent_status,
        "firstalt_invite_status": rec.priority_email_status,
        "priority_email_status": rec.priority_email_status,
        "brandon_email_status": rec.brandon_email_status,
        "bgc_status": rec.bgc_status,
        "drug_test_status": rec.drug_test_status,
        "contract_status": rec.contract_status,
        "files_status": rec.files_status,
        "paychex_status": rec.paychex_status,
        "training_status": rec.training_status,
        "maz_training_status": rec.maz_training_status if hasattr(rec, "maz_training_status") else "pending",
        "maz_contract_status": rec.maz_contract_status if hasattr(rec, "maz_contract_status") else "pending",
        "notes": rec.notes,
        "started_at": rec.started_at.isoformat() if rec.started_at else None,
        "completed_at": rec.completed_at.isoformat() if rec.completed_at else None,
        "invite_token": rec.invite_token,
        "personal_info": rec.personal_info,
        "intake_submitted_at": rec.intake_submitted_at.isoformat() if hasattr(rec, "intake_submitted_at") and rec.intake_submitted_at else None,
        "person": {
            "language": person.language if person else None,
        },
    })


def _notify_admin_personal_info(driver_name: str, intake_data: dict | None = None) -> None:
    """Background task: SMS admin when a driver submits their personal info."""
    admin_phone = os.environ.get("ADMIN_PHONE", "").strip()
    if not admin_phone:
        _logger.warning("[admin-notify] ADMIN_PHONE not set — skipping intake notification")
        return
    try:
        from backend.services import notification_service
        email = intake_data.get("email", "N/A") if intake_data else "N/A"
        phone = intake_data.get("phone", "N/A") if intake_data else "N/A"
        notification_service.send_sms(
            admin_phone,
            f"Z Pay: New driver intake!\n{driver_name}\nEmail: {email}\nPhone: {phone}\nCheck the portal to proceed.",
        )
    except Exception as e:
        _logger.warning("Failed to notify admin of personal info submission: %s", e)


@public_router.post("/{token}/step")
async def join_submit_step(token: str, request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Public — driver submits data for a step.
    Body: { "step": "personal_info" | "consent" | etc, "data": {...} }
    """
    # DEV token — accept all submissions silently without touching the DB
    if token == "dev":
        return JSONResponse({"ok": True, "dev": True})

    rec = db.query(OnboardingRecord).filter(OnboardingRecord.invite_token == token).first()
    if not rec:
        return JSONResponse({"error": "Link expired or invalid"}, status_code=404)

    body = await request.json()
    step = body.get("step")
    data = body.get("data", {})

    ALLOWED_PERSONAL_INFO_FIELDS = {
        "full_name", "email", "phone", "address", "dob",
        "drivers_license_number",
        "vehicle_make", "vehicle_model", "vehicle_year", "vehicle_plate", "vehicle_color",
        "emergency_name", "emergency_phone",
        "language",
    }
    MAX_FIELD_LENGTH = 500

    if step == "personal_info":
        # Validate and sanitize — only allow known fields, cap field length
        filtered = {k: str(v)[:MAX_FIELD_LENGTH] for k, v in data.items() if k in ALLOWED_PERSONAL_INFO_FIELDS}
        if len(str(filtered)) > 10000:  # total payload cap
            return JSONResponse({"error": "Data too large"}, status_code=400)
        rec.personal_info = filtered
        rec.intake_submitted_at = datetime.now(timezone.utc)

        # Also update Person record (only fill empty fields, except language which always updates)
        person = db.query(Person).filter(Person.person_id == rec.person_id).first()
        if person:
            if not person.full_name and filtered.get("full_name"):
                person.full_name = filtered["full_name"]
            if not person.email and filtered.get("email"):
                person.email = filtered["email"]
            if not person.phone and filtered.get("phone"):
                person.phone = filtered["phone"]
            if not person.home_address and filtered.get("address"):
                person.home_address = filtered["address"]
            if filtered.get("language"):
                person.language = filtered["language"]
            if not person.vehicle_make and filtered.get("vehicle_make"):
                person.vehicle_make = filtered["vehicle_make"]
            if not person.vehicle_model and filtered.get("vehicle_model"):
                person.vehicle_model = filtered["vehicle_model"]
            if not person.vehicle_year and filtered.get("vehicle_year"):
                try:
                    person.vehicle_year = int(filtered["vehicle_year"])
                except (ValueError, TypeError):
                    pass
            if not person.vehicle_plate and filtered.get("vehicle_plate"):
                person.vehicle_plate = filtered["vehicle_plate"]
            if not person.vehicle_color and filtered.get("vehicle_color"):
                person.vehicle_color = filtered["vehicle_color"]

        db.commit()
        db.refresh(rec)
        if not person:
            person = db.query(Person).filter(Person.person_id == rec.person_id).first()

        driver_name = person.full_name if person else f"Driver #{rec.person_id}"
        _logger.info("Driver %s submitted personal info for onboarding record %d", driver_name, rec.id)

        # Notify admin via SMS in background — never crash the main request
        background_tasks.add_task(_notify_admin_personal_info, driver_name, filtered)

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
