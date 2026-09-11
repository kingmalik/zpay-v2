"""
Training link — one-tap driver training link for operators.

Today the only way to get a driver a training link is the full admin flow:
POST /onboarding/start (needs person_id) then a Regenerate button on the
onboarding detail page. Operators (e.g. Malik's mom, role "operator") don't
have a path to that page. This gives operators (and admins) a single
endpoint that creates-or-reuses an onboarding record for a driver and hands
back the shareable /training/{token} URL — no email/SMS/background task,
nothing sent to the driver.

Kept as its own small router (rather than added to routes/onboarding.py)
because onboarding.py's join-step handler is being edited concurrently.
"""

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import DriverCertification, OnboardingRecord, Person
from backend.routes.onboarding import JOIN_TOKEN_EXPIRY_DAYS
from backend.services.certification import COURSE_VERSION
from backend.services.onboarding_autosend import build_training_link
from backend.utils.roles import require_role

router = APIRouter(prefix="/onboarding", tags=["onboarding-training-link"])


def _latest_cert(db: Session, person_id: int):
    return (
        db.query(DriverCertification)
        .filter(DriverCertification.person_id == person_id)
        .order_by(DriverCertification.certified_at.desc(), DriverCertification.cert_id.desc())
        .first()
    )


@router.post("/training-link/{person_id}")
async def get_or_create_training_link(
    person_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(require_role("admin", "operator")),
):
    """
    Get-or-create the shareable training link for a driver.

    Body (optional): { "partner": "firstalt" | "everdriven" }
    Only consulted when a new onboarding record is created; ignored for an
    existing record. Never emails/texts the driver — the operator copies the
    returned URL and sends it themselves.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    person = db.query(Person).filter(Person.person_id == person_id).first()
    if not person:
        return JSONResponse({"error": f"Person {person_id} not found"}, status_code=404)

    now = datetime.now(timezone.utc)
    rec = db.query(OnboardingRecord).filter(OnboardingRecord.person_id == person_id).first()

    if rec is None:
        partner = body.get("partner", "firstalt")
        if partner not in ("firstalt", "everdriven"):
            partner = "firstalt"
        rec = OnboardingRecord(person_id=person_id)
        rec.invite_token = secrets.token_urlsafe(32)
        rec.partner = partner
        rec.started_at = now
        db.add(rec)
        db.commit()
        db.refresh(rec)
    else:
        started_at = rec.started_at
        is_expired = (
            started_at is None
            or (now - (started_at if started_at.tzinfo else started_at.replace(tzinfo=timezone.utc))).days
            > JOIN_TOKEN_EXPIRY_DAYS
        )
        if is_expired:
            rec.invite_token = secrets.token_urlsafe(32)
            rec.started_at = now
            db.commit()
            db.refresh(rec)

    latest_cert = _latest_cert(db, person_id)
    certified = bool(latest_cert and latest_cert.course_version == COURSE_VERSION)
    expires_at = (rec.started_at or now) + timedelta(days=JOIN_TOKEN_EXPIRY_DAYS)

    return JSONResponse({
        "url": build_training_link(rec.invite_token),
        "expires_at": expires_at.isoformat(),
        "certified": certified,
        "course_version": latest_cert.course_version if latest_cert else None,
    })
