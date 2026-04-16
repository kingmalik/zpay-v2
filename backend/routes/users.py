"""
Team user management routes.

Endpoints:
  GET    /api/users/me            — current user info (any authenticated role)
  PATCH  /api/users/me            — update own profile (name, email, phone, avatar)
  POST   /api/users/me/password   — change own password
  GET    /api/users               — list team (admin / operator)
  POST   /api/users               — create team member (admin only)
  PATCH  /api/users/{user_id}     — edit team member (admin only)
  POST   /api/users/{user_id}/deactivate — deactivate (admin only)
  POST   /api/users/{user_id}/reset-password — set new password (admin only)
"""

from __future__ import annotations

import bcrypt
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import UserAccount
from backend.utils.permissions import (
    get_current_user,
    require_admin,
    require_manager_or_admin,
    is_admin,
)


router = APIRouter(prefix="/users", tags=["users"])

_VALID_ROLES = {"admin", "operator", "associate"}


# ── Schemas ────────────────────────────────────────────────────

class UpdateMe(BaseModel):
    full_name: Optional[str] = None
    display_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    language: Optional[str] = None
    avatar_url: Optional[str] = None


class ChangePassword(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=128)


class CreateUser(BaseModel):
    username: str = Field(..., min_length=2, max_length=32)
    full_name: str = Field(..., min_length=1, max_length=128)
    display_name: Optional[str] = None
    role: str = Field(..., pattern="^(admin|operator|associate)$")
    password: str = Field(..., min_length=8, max_length=128)
    email: Optional[str] = None
    phone: Optional[str] = None
    language: str = "en"
    color: str = "#4facfe"
    initials: Optional[str] = None


class UpdateUser(BaseModel):
    full_name: Optional[str] = None
    display_name: Optional[str] = None
    role: Optional[str] = Field(None, pattern="^(admin|operator|associate)$")
    email: Optional[str] = None
    phone: Optional[str] = None
    language: Optional[str] = None
    color: Optional[str] = None
    initials: Optional[str] = None
    active: Optional[bool] = None


class ResetPassword(BaseModel):
    new_password: str = Field(..., min_length=8, max_length=128)


# ── Helpers ────────────────────────────────────────────────────

def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _row_to_dict(row: UserAccount) -> dict:
    return row.to_safe_dict() | {
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "last_login_at": row.last_login_at.isoformat() if row.last_login_at else None,
    }


def _get_user_or_404(db: Session, user_id: int) -> UserAccount:
    row = db.query(UserAccount).filter(UserAccount.user_id == user_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="User not found.")
    return row


# ── /me endpoints (any authenticated user) ─────────────────────

@router.get("/me")
async def get_me(request: Request, db: Session = Depends(get_db)):
    session_user = get_current_user(request)
    username = session_user.get("username")

    # Prefer the live DB row; fall back to the session cookie content for
    # env-fallback users (which have no DB row).
    row = db.query(UserAccount).filter(UserAccount.username == username).first()
    if row:
        return _row_to_dict(row)
    return {
        "user_id": session_user.get("user_id"),
        "username": username,
        "display_name": session_user.get("display_name"),
        "role": session_user.get("role"),
        "color": session_user.get("color"),
        "initials": session_user.get("initials"),
        "full_name": session_user.get("display_name"),
        "source": "env_fallback",
    }


@router.patch("/me")
async def update_me(
    payload: UpdateMe,
    request: Request,
    db: Session = Depends(get_db),
):
    session_user = get_current_user(request)
    row = (
        db.query(UserAccount)
        .filter(UserAccount.username == session_user.get("username"))
        .first()
    )
    if not row:
        raise HTTPException(
            status_code=400,
            detail="Your account is still env-managed. Ask an admin to migrate it.",
        )

    for field in ("full_name", "display_name", "email", "phone", "language", "avatar_url"):
        val = getattr(payload, field)
        if val is not None:
            setattr(row, field, val)

    db.commit()
    db.refresh(row)
    return _row_to_dict(row)


@router.post("/me/password")
async def change_own_password(
    payload: ChangePassword,
    request: Request,
    db: Session = Depends(get_db),
):
    session_user = get_current_user(request)
    row = (
        db.query(UserAccount)
        .filter(UserAccount.username == session_user.get("username"))
        .first()
    )
    if not row:
        raise HTTPException(
            status_code=400,
            detail="Your account is still env-managed. Ask an admin to migrate it.",
        )

    if not row.password_hash or not bcrypt.checkpw(
        payload.current_password.encode("utf-8"),
        row.password_hash.encode("utf-8"),
    ):
        raise HTTPException(status_code=403, detail="Current password is incorrect.")

    row.password_hash = _hash(payload.new_password)
    db.commit()
    return {"ok": True}


# ── Team list / admin ops ──────────────────────────────────────

@router.get("")
async def list_team(
    db: Session = Depends(get_db),
    _user: dict = Depends(require_manager_or_admin),
):
    rows = (
        db.query(UserAccount)
        .order_by(UserAccount.role.asc(), UserAccount.full_name.asc())
        .all()
    )
    return [_row_to_dict(r) for r in rows]


@router.post("", status_code=201)
async def create_user(
    payload: CreateUser,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_admin),
):
    if payload.role not in _VALID_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role.")

    uname = payload.username.lower().strip()
    existing = db.query(UserAccount).filter(UserAccount.username == uname).first()
    if existing:
        raise HTTPException(status_code=409, detail="Username already exists.")

    display = (payload.display_name or payload.full_name.split()[0] or uname).strip()
    initials = (
        payload.initials
        or "".join(part[0] for part in payload.full_name.split()[:2]).upper()
        or "?"
    )

    row = UserAccount(
        username=uname,
        full_name=payload.full_name.strip(),
        display_name=display,
        role=payload.role,
        password_hash=_hash(payload.password),
        email=payload.email,
        phone=payload.phone,
        language=payload.language or "en",
        color=payload.color or "#4facfe",
        initials=initials,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _row_to_dict(row)


@router.patch("/{user_id}")
async def update_user(
    user_id: int,
    payload: UpdateUser,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_admin),
):
    row = _get_user_or_404(db, user_id)

    for field in (
        "full_name",
        "display_name",
        "role",
        "email",
        "phone",
        "language",
        "color",
        "initials",
        "active",
    ):
        val = getattr(payload, field)
        if val is not None:
            setattr(row, field, val)

    db.commit()
    db.refresh(row)
    return _row_to_dict(row)


@router.post("/{user_id}/deactivate")
async def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    row = _get_user_or_404(db, user_id)
    if row.username == admin.get("username"):
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself.")
    row.active = False
    db.commit()
    return {"ok": True}


@router.post("/{user_id}/reset-password")
async def reset_password(
    user_id: int,
    payload: ResetPassword,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_admin),
):
    row = _get_user_or_404(db, user_id)
    row.password_hash = _hash(payload.new_password)
    db.commit()
    return {"ok": True}
