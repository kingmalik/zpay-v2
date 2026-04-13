# backend/routes/onboarding_files.py — registered in app.py

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import OnboardingFile, OnboardingRecord
from backend.services.r2_storage import get_presigned_url, r2_configured, upload_file

router = APIRouter(prefix="/onboarding", tags=["onboarding-files"])

ALLOWED_FILE_TYPES = {
    "drivers_license", "vehicle_registration", "inspection",
    "drug_test_results", "consent_form", "insurance", "w9", "maz_contract", "other",
}
# Only these 3 are required for auto-complete of files_status
REQUIRED_FILE_TYPES = {"drivers_license", "vehicle_registration", "inspection"}


@router.post("/{onboarding_id}/upload")
async def upload_onboarding_file(
    onboarding_id: int,
    file: UploadFile = File(...),
    file_type: str = Form(...),
    db: Session = Depends(get_db),
):
    """
    Upload a driver document for an onboarding record.

    Accepted file_type values: drivers_license | vehicle_registration | inspection |
        drug_test_results | consent_form | insurance | w9 | maz_contract | other

    Required for auto-complete: drivers_license, vehicle_registration, inspection
    """
    if file_type not in ALLOWED_FILE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file_type '{file_type}'. Must be one of: {', '.join(sorted(ALLOWED_FILE_TYPES))}",
        )

    # Verify the onboarding record exists
    record = db.query(OnboardingRecord).filter(OnboardingRecord.id == onboarding_id).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"OnboardingRecord {onboarding_id} not found")

    file_bytes = await file.read()

    # Size limit: 10 MB
    MAX_SIZE = 10 * 1024 * 1024
    if len(file_bytes) > MAX_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds 10 MB limit")

    # Type validation: only PDF or image
    _PDF_MAGIC = b"%PDF-"
    _JPEG_MAGIC = b"\xFF\xD8\xFF"
    _PNG_MAGIC = b"\x89PNG\r\n"
    if not (file_bytes.startswith(_PDF_MAGIC) or
            file_bytes.startswith(_JPEG_MAGIC) or
            file_bytes.startswith(_PNG_MAGIC)):
        raise HTTPException(status_code=400, detail="File must be a PDF or image (PNG/JPG)")

    filename = file.filename or f"{file_type}_upload"
    content_type = file.content_type or "application/octet-stream"

    # --- R2 upload path ---
    if r2_configured():
        r2_key = f"onboarding/{onboarding_id}/{file_type}/{filename}"
        upload_file(file_bytes, r2_key, content_type)
        presigned_url = get_presigned_url(r2_key, expires_in=3600)

        # Upsert OnboardingFile record (one row per file_type per onboarding)
        existing = (
            db.query(OnboardingFile)
            .filter(
                OnboardingFile.onboarding_id == onboarding_id,
                OnboardingFile.file_type == file_type,
            )
            .first()
        )
        if existing:
            existing.r2_key = r2_key
            existing.r2_url = presigned_url
            existing.filename = filename
            existing.uploaded_at = datetime.now(timezone.utc)
        else:
            db.add(
                OnboardingFile(
                    onboarding_id=onboarding_id,
                    file_type=file_type,
                    r2_key=r2_key,
                    r2_url=presigned_url,
                    filename=filename,
                    uploaded_at=datetime.now(timezone.utc),
                )
            )

        db.flush()

        # Check if all 3 required file types are now uploaded
        uploaded_types = {
            row.file_type
            for row in db.query(OnboardingFile.file_type)
            .filter(OnboardingFile.onboarding_id == onboarding_id)
            .all()
        }
        if REQUIRED_FILE_TYPES.issubset(uploaded_types):
            record.files_status = "complete"

        db.commit()

        return JSONResponse(
            {
                "ok": True,
                "r2_configured": True,
                "onboarding_id": onboarding_id,
                "file_type": file_type,
                "filename": filename,
                "r2_key": r2_key,
                "presigned_url": presigned_url,
                "files_status": record.files_status,
            }
        )

    # --- R2 not configured: store filename only ---
    existing = (
        db.query(OnboardingFile)
        .filter(
            OnboardingFile.onboarding_id == onboarding_id,
            OnboardingFile.file_type == file_type,
        )
        .first()
    )
    if existing:
        existing.filename = filename
        existing.uploaded_at = datetime.now(timezone.utc)
    else:
        db.add(
            OnboardingFile(
                onboarding_id=onboarding_id,
                file_type=file_type,
                r2_key=None,
                r2_url=None,
                filename=filename,
                uploaded_at=datetime.now(timezone.utc),
            )
        )

    db.flush()

    uploaded_types = {
        row.file_type
        for row in db.query(OnboardingFile.file_type)
        .filter(OnboardingFile.onboarding_id == onboarding_id)
        .all()
    }
    if REQUIRED_FILE_TYPES.issubset(uploaded_types):
        record.files_status = "complete"

    db.commit()

    return JSONResponse(
        {
            "ok": True,
            "r2_configured": False,
            "onboarding_id": onboarding_id,
            "file_type": file_type,
            "filename": filename,
            "files_status": record.files_status,
        }
    )
