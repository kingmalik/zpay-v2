"""
Ops Board routes — shared command center for Malik and Mom.

Prefix: /ops (registered under /api/data in app.py)
All responses are JSON, consumed by the Next.js frontend.
"""

import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import OpsNote, OnboardingRecord, Person, PayrollBatch

_logger = logging.getLogger("zpay.ops")

router = APIRouter(prefix="/ops", tags=["ops"])


# ---------------------------------------------------------------------------
# Serialisation helper
# ---------------------------------------------------------------------------

def _note_to_dict(note: OpsNote) -> dict:
    return {
        "id": note.id,
        "body": note.body,
        "created_by": note.created_by,
        "done": note.done,
        "created_at": note.created_at.isoformat() if note.created_at else None,
        "done_at": note.done_at.isoformat() if note.done_at else None,
    }


# ---------------------------------------------------------------------------
# GET /ops/summary — morning brief stats
# ---------------------------------------------------------------------------

@router.get("/summary")
def ops_summary(db: Session = Depends(get_db)):
    """Return high-level ops stats for the morning brief."""
    # Payroll due date: most recent batch period_end + 14 days
    payroll_due_date = None
    try:
        latest_batch = (
            db.query(PayrollBatch)
            .filter(PayrollBatch.period_end.isnot(None))
            .order_by(PayrollBatch.period_end.desc())
            .first()
        )
        if latest_batch and latest_batch.period_end:
            from datetime import date
            period_end = latest_batch.period_end
            if hasattr(period_end, 'isoformat'):
                due = period_end
                if isinstance(due, date):
                    due_dt = datetime(due.year, due.month, due.day) + timedelta(days=14)
                    payroll_due_date = due_dt.date().isoformat()
    except Exception as exc:
        _logger.warning("Could not compute payroll_due_date: %s", exc)
        payroll_due_date = None

    # Onboarding active: records with completed_at IS NULL
    try:
        onboarding_active = (
            db.query(OnboardingRecord)
            .filter(OnboardingRecord.completed_at.is_(None))
            .count()
        )
    except Exception as exc:
        _logger.warning("Could not count onboarding_active: %s", exc)
        onboarding_active = 0

    # Open notes
    try:
        open_notes = db.query(OpsNote).filter(OpsNote.done.is_(False)).count()
    except Exception as exc:
        _logger.warning("Could not count open_notes: %s", exc)
        open_notes = 0

    # Total drivers (active persons)
    try:
        drivers_total = db.query(Person).filter(Person.active.is_(True)).count()
    except Exception as exc:
        _logger.warning("Could not count drivers_total: %s", exc)
        drivers_total = 0

    return JSONResponse({
        "payroll_due_date": payroll_due_date,
        "onboarding_active": onboarding_active,
        "open_notes": open_notes,
        "drivers_total": drivers_total,
    })


# ---------------------------------------------------------------------------
# GET /ops/notes — list all notes
# ---------------------------------------------------------------------------

@router.get("/notes")
def list_notes(db: Session = Depends(get_db)):
    """Return all ops notes ordered by created_at desc."""
    notes = db.query(OpsNote).order_by(OpsNote.created_at.desc()).all()
    return JSONResponse([_note_to_dict(n) for n in notes])


# ---------------------------------------------------------------------------
# POST /ops/notes — create a note
# ---------------------------------------------------------------------------

from fastapi import Request

@router.post("/notes")
async def create_note(request: Request, db: Session = Depends(get_db)):
    """Create a new ops note. Body: { body, created_by }"""
    body_data = await request.json()
    body_text = (body_data.get("body") or "").strip()
    created_by = (body_data.get("created_by") or "Malik").strip()

    if not body_text:
        return JSONResponse({"error": "body is required"}, status_code=400)
    if created_by not in ("Malik", "Mom"):
        created_by = "Malik"

    note = OpsNote(body=body_text, created_by=created_by)
    db.add(note)
    db.commit()
    db.refresh(note)

    _logger.info("Ops note created by %s (id=%d)", created_by, note.id)
    return JSONResponse(_note_to_dict(note), status_code=201)


# ---------------------------------------------------------------------------
# PATCH /ops/notes/{id} — toggle done
# ---------------------------------------------------------------------------

@router.patch("/notes/{note_id}")
def toggle_note_done(note_id: int, db: Session = Depends(get_db)):
    """Mark a note as done (sets done=True, done_at=now). Idempotent."""
    note = db.query(OpsNote).filter(OpsNote.id == note_id).first()
    if not note:
        return JSONResponse({"error": "Note not found"}, status_code=404)

    note.done = not note.done
    note.done_at = datetime.now(timezone.utc) if note.done else None
    db.commit()
    db.refresh(note)

    return JSONResponse(_note_to_dict(note))


# ---------------------------------------------------------------------------
# DELETE /ops/notes/{id} — delete a note
# ---------------------------------------------------------------------------

@router.delete("/notes/{note_id}")
def delete_note(note_id: int, db: Session = Depends(get_db)):
    """Delete an ops note."""
    note = db.query(OpsNote).filter(OpsNote.id == note_id).first()
    if not note:
        return JSONResponse({"error": "Note not found"}, status_code=404)

    db.delete(note)
    db.commit()

    _logger.info("Ops note deleted (id=%d)", note_id)
    return JSONResponse({"ok": True, "deleted_id": note_id})
