"""
SOP (Standard Operating Procedure) routes — Team OS Phase 2.

Endpoints:
  GET    /api/sops                         — list (any authenticated)
  POST   /api/sops                         — create (admin or operator)
  GET    /api/sops/{id}                    — detail + field notes (any authenticated)
  PATCH  /api/sops/{id}                    — edit (admin or operator) — bumps version
  POST   /api/sops/{id}/archive            — archive/unarchive (admin or operator)
  POST   /api/sops/{id}/notes              — add a field note (any authenticated)
  POST   /api/sops/notes/{note_id}/promote — mark a field note as promoted (admin/operator)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import SOP, SOPFieldNote, UserAccount
from backend.utils.permissions import (
    get_current_user,
    require_manager_or_admin,
    require_any_role,
)


router = APIRouter(prefix="/api/sops", tags=["sops"])


# ── Schemas ────────────────────────────────────────────────────

class CreateSOP(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    category: Optional[str] = None
    owner_role: str = Field("operator", pattern="^(admin|operator|associate)$")
    trigger_when: Optional[str] = None
    content: str = Field(..., min_length=1)


class UpdateSOP(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    owner_role: Optional[str] = Field(None, pattern="^(admin|operator|associate)$")
    trigger_when: Optional[str] = None
    content: Optional[str] = None


class CreateNote(BaseModel):
    note: str = Field(..., min_length=1, max_length=4000)


# ── Helpers ────────────────────────────────────────────────────

def _author_map(db: Session, user_ids: set[int]) -> dict[int, dict]:
    if not user_ids:
        return {}
    rows = db.query(UserAccount).filter(UserAccount.user_id.in_(user_ids)).all()
    return {
        r.user_id: {"user_id": r.user_id, "display_name": r.display_name, "initials": r.initials, "color": r.color}
        for r in rows
    }


def _sop_or_404(db: Session, sop_id: int) -> SOP:
    row = db.query(SOP).filter(SOP.sop_id == sop_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="SOP not found.")
    return row


def _current_db_user_id(request: Request, db: Session) -> Optional[int]:
    """Look up the logged-in user's DB id (None if env-fallback account)."""
    user = get_current_user(request)
    row = db.query(UserAccount).filter(UserAccount.username == user.get("username")).first()
    return row.user_id if row else None


# ── Routes ─────────────────────────────────────────────────────

@router.get("")
async def list_sops(
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_role),
    category: Optional[str] = None,
    include_archived: bool = False,
):
    q = db.query(SOP)
    if not include_archived:
        q = q.filter(SOP.archived == False)  # noqa: E712
    if category:
        q = q.filter(SOP.category == category)
    rows = q.order_by(SOP.category.asc().nullslast(), SOP.title.asc()).all()
    return [r.to_dict() for r in rows]


@router.post("", status_code=201)
async def create_sop(
    payload: CreateSOP,
    request: Request,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_manager_or_admin),
):
    author_id = _current_db_user_id(request, db)
    row = SOP(
        title=payload.title,
        category=payload.category,
        owner_role=payload.owner_role,
        trigger_when=payload.trigger_when,
        content=payload.content,
        created_by=author_id,
        updated_by=author_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.to_dict()


@router.get("/{sop_id}")
async def get_sop(
    sop_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_role),
):
    row = _sop_or_404(db, sop_id)

    notes = (
        db.query(SOPFieldNote)
        .filter(SOPFieldNote.sop_id == sop_id)
        .order_by(SOPFieldNote.created_at.desc())
        .all()
    )
    author_ids = {n.author_user_id for n in notes}
    authors = _author_map(db, author_ids)

    return row.to_dict() | {
        "field_notes": [
            {
                "id": n.id,
                "note": n.note,
                "promoted": n.promoted,
                "created_at": n.created_at.isoformat() if n.created_at else None,
                "author": authors.get(n.author_user_id),
            }
            for n in notes
        ]
    }


@router.patch("/{sop_id}")
async def update_sop(
    sop_id: int,
    payload: UpdateSOP,
    request: Request,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_manager_or_admin),
):
    row = _sop_or_404(db, sop_id)
    changed = False
    for field in ("title", "category", "owner_role", "trigger_when", "content"):
        val = getattr(payload, field)
        if val is not None:
            setattr(row, field, val)
            changed = True
    if changed:
        row.version = (row.version or 1) + 1
        row.updated_at = datetime.now(timezone.utc)
        row.updated_by = _current_db_user_id(request, db)
    db.commit()
    db.refresh(row)
    return row.to_dict()


@router.post("/{sop_id}/archive")
async def toggle_archive(
    sop_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_manager_or_admin),
):
    row = _sop_or_404(db, sop_id)
    row.archived = not row.archived
    db.commit()
    return {"ok": True, "archived": row.archived}


@router.post("/{sop_id}/notes", status_code=201)
async def add_field_note(
    sop_id: int,
    payload: CreateNote,
    request: Request,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_role),
):
    _sop_or_404(db, sop_id)
    author_id = _current_db_user_id(request, db)
    if not author_id:
        raise HTTPException(
            status_code=400,
            detail="Your account is env-managed. Ask an admin to migrate it.",
        )
    note = SOPFieldNote(sop_id=sop_id, author_user_id=author_id, note=payload.note)
    db.add(note)
    db.commit()
    db.refresh(note)
    return {
        "id": note.id,
        "note": note.note,
        "promoted": note.promoted,
        "created_at": note.created_at.isoformat() if note.created_at else None,
        "author": _author_map(db, {author_id}).get(author_id),
    }


@router.post("/notes/{note_id}/promote")
async def promote_note(
    note_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_manager_or_admin),
):
    note = db.query(SOPFieldNote).filter(SOPFieldNote.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found.")
    note.promoted = True
    db.commit()
    return {"ok": True}
