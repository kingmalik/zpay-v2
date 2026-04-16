"""
Task routes — Team OS Phase 2.

Endpoints:
  GET    /api/tasks                          — list (scoped by role)
  POST   /api/tasks                          — create (admin / operator)
  GET    /api/tasks/{id}                     — detail w/ checklist + comments
  PATCH  /api/tasks/{id}                     — edit fields / reassign / status
  POST   /api/tasks/{id}/complete            — mark done
  DELETE /api/tasks/{id}                     — delete (admin only)
  POST   /api/tasks/{id}/checklist           — add checklist item (admin/operator/assignee)
  PATCH  /api/tasks/{id}/checklist/{item_id} — toggle / rename item
  DELETE /api/tasks/{id}/checklist/{item_id} — remove item
  POST   /api/tasks/{id}/comments            — add comment
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import (
    Task,
    TaskChecklistItem,
    TaskComment,
    UserAccount,
)
from backend.utils.permissions import (
    get_current_user,
    is_admin,
    require_any_role,
    require_admin,
    require_manager_or_admin,
    role_at_least,
)


router = APIRouter(prefix="/tasks", tags=["tasks"])


_VALID_STATUS = {"todo", "in_progress", "blocked", "done"}
_VALID_PRIORITY = {"low", "normal", "high", "urgent"}


# ── Schemas ────────────────────────────────────────────────────

class CreateTask(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    assignee_id: Optional[int] = None
    priority: str = Field("normal", pattern="^(low|normal|high|urgent)$")
    due_at: Optional[datetime] = None
    linked_sop_id: Optional[int] = None
    checklist: list[str] = Field(default_factory=list)


class UpdateTask(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    assignee_id: Optional[int] = None
    priority: Optional[str] = Field(None, pattern="^(low|normal|high|urgent)$")
    status: Optional[str] = Field(None, pattern="^(todo|in_progress|blocked|done)$")
    due_at: Optional[datetime] = None
    linked_sop_id: Optional[int] = None


class ChecklistItemPayload(BaseModel):
    label: str = Field(..., min_length=1, max_length=200)


class ChecklistUpdate(BaseModel):
    label: Optional[str] = None
    done: Optional[bool] = None


class CommentPayload(BaseModel):
    body: str = Field(..., min_length=1, max_length=4000)


# ── Helpers ────────────────────────────────────────────────────

def _task_or_404(db: Session, task_id: int) -> Task:
    row = db.query(Task).filter(Task.task_id == task_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found.")
    return row


def _current_db_user(request: Request, db: Session) -> Optional[UserAccount]:
    user = get_current_user(request)
    return db.query(UserAccount).filter(UserAccount.username == user.get("username")).first()


def _can_see_task(user: dict, task: Task, db_user_id: Optional[int]) -> bool:
    """Admin/operator see everything. Associate only sees their assigned tasks."""
    if role_at_least(user, "operator"):
        return True
    return db_user_id is not None and task.assignee_id == db_user_id


def _user_map(db: Session, user_ids: set[int]) -> dict[int, dict]:
    ids = {uid for uid in user_ids if uid}
    if not ids:
        return {}
    rows = db.query(UserAccount).filter(UserAccount.user_id.in_(ids)).all()
    return {
        r.user_id: {
            "user_id": r.user_id,
            "username": r.username,
            "display_name": r.display_name,
            "color": r.color,
            "initials": r.initials,
        }
        for r in rows
    }


# ── Routes ─────────────────────────────────────────────────────

@router.get("")
async def list_tasks(
    request: Request,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_role),
    status_filter: Optional[str] = None,
    assignee_id: Optional[int] = None,
):
    user = get_current_user(request)
    db_user = _current_db_user(request, db)
    db_user_id = db_user.user_id if db_user else None

    q = db.query(Task)

    if not role_at_least(user, "operator"):
        if not db_user_id:
            return []
        q = q.filter(Task.assignee_id == db_user_id)
    elif assignee_id is not None:
        q = q.filter(Task.assignee_id == assignee_id)

    if status_filter:
        if status_filter not in _VALID_STATUS:
            raise HTTPException(status_code=400, detail="Invalid status filter.")
        q = q.filter(Task.status == status_filter)

    rows = q.order_by(Task.status.asc(), Task.priority.desc(), Task.created_at.desc()).all()

    people = _user_map(db, {t.assignee_id for t in rows} | {t.created_by for t in rows})

    return [
        r.to_dict()
        | {
            "assignee": people.get(r.assignee_id),
            "creator": people.get(r.created_by),
        }
        for r in rows
    ]


@router.post("", status_code=201)
async def create_task(
    payload: CreateTask,
    request: Request,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_manager_or_admin),
):
    creator = _current_db_user(request, db)

    row = Task(
        title=payload.title,
        description=payload.description,
        assignee_id=payload.assignee_id,
        created_by=creator.user_id if creator else None,
        priority=payload.priority,
        due_at=payload.due_at,
        linked_sop_id=payload.linked_sop_id,
    )
    db.add(row)
    db.flush()  # get task_id

    for i, label in enumerate(payload.checklist or []):
        label = label.strip()
        if not label:
            continue
        db.add(TaskChecklistItem(task_id=row.task_id, label=label, order_index=i))

    db.commit()
    db.refresh(row)
    return row.to_dict()


@router.get("/{task_id}")
async def get_task(
    task_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_role),
):
    user = get_current_user(request)
    db_user = _current_db_user(request, db)
    db_user_id = db_user.user_id if db_user else None

    row = _task_or_404(db, task_id)
    if not _can_see_task(user, row, db_user_id):
        raise HTTPException(status_code=403, detail="Not your task.")

    items = (
        db.query(TaskChecklistItem)
        .filter(TaskChecklistItem.task_id == task_id)
        .order_by(TaskChecklistItem.order_index.asc(), TaskChecklistItem.id.asc())
        .all()
    )
    comments = (
        db.query(TaskComment)
        .filter(TaskComment.task_id == task_id)
        .order_by(TaskComment.created_at.asc())
        .all()
    )

    people = _user_map(
        db,
        {row.assignee_id, row.created_by} | {c.author_user_id for c in comments},
    )

    return row.to_dict() | {
        "assignee": people.get(row.assignee_id),
        "creator": people.get(row.created_by),
        "checklist": [
            {"id": i.id, "label": i.label, "done": i.done, "order_index": i.order_index}
            for i in items
        ],
        "comments": [
            {
                "id": c.id,
                "body": c.body,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "author": people.get(c.author_user_id),
            }
            for c in comments
        ],
    }


@router.patch("/{task_id}")
async def update_task(
    task_id: int,
    payload: UpdateTask,
    request: Request,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_role),
):
    user = get_current_user(request)
    db_user = _current_db_user(request, db)
    db_user_id = db_user.user_id if db_user else None

    row = _task_or_404(db, task_id)

    can_edit_all = role_at_least(user, "operator")
    is_assignee = db_user_id is not None and row.assignee_id == db_user_id

    if not can_edit_all and not is_assignee:
        raise HTTPException(status_code=403, detail="Not your task.")

    # Assignees can only update status (and their own checklist / comments elsewhere)
    if not can_edit_all:
        disallowed = {
            "title", "description", "assignee_id", "priority", "due_at", "linked_sop_id",
        }
        for f in disallowed:
            if getattr(payload, f) is not None:
                raise HTTPException(status_code=403, detail=f"Only admin/operator can change {f}.")

    for field in ("title", "description", "assignee_id", "priority", "status", "due_at", "linked_sop_id"):
        val = getattr(payload, field)
        if val is not None:
            setattr(row, field, val)

    if payload.status == "done":
        row.completed_at = datetime.now(timezone.utc)
    elif payload.status and payload.status != "done":
        row.completed_at = None

    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row.to_dict()


@router.post("/{task_id}/complete")
async def complete_task(
    task_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_role),
):
    user = get_current_user(request)
    db_user = _current_db_user(request, db)
    db_user_id = db_user.user_id if db_user else None

    row = _task_or_404(db, task_id)
    if not _can_see_task(user, row, db_user_id):
        raise HTTPException(status_code=403, detail="Not your task.")

    row.status = "done"
    row.completed_at = datetime.now(timezone.utc)
    row.updated_at = row.completed_at
    db.commit()
    return row.to_dict()


@router.delete("/{task_id}")
async def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_admin),
):
    row = _task_or_404(db, task_id)
    db.delete(row)
    db.commit()
    return {"ok": True}


# ── Checklist ──────────────────────────────────────────────────

@router.post("/{task_id}/checklist", status_code=201)
async def add_checklist_item(
    task_id: int,
    payload: ChecklistItemPayload,
    request: Request,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_role),
):
    user = get_current_user(request)
    db_user = _current_db_user(request, db)
    db_user_id = db_user.user_id if db_user else None

    row = _task_or_404(db, task_id)
    if not _can_see_task(user, row, db_user_id):
        raise HTTPException(status_code=403, detail="Not your task.")

    count = db.query(TaskChecklistItem).filter(TaskChecklistItem.task_id == task_id).count()
    item = TaskChecklistItem(task_id=task_id, label=payload.label, order_index=count)
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": item.id, "label": item.label, "done": item.done, "order_index": item.order_index}


@router.patch("/{task_id}/checklist/{item_id}")
async def update_checklist_item(
    task_id: int,
    item_id: int,
    payload: ChecklistUpdate,
    request: Request,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_role),
):
    user = get_current_user(request)
    db_user = _current_db_user(request, db)
    db_user_id = db_user.user_id if db_user else None

    task = _task_or_404(db, task_id)
    if not _can_see_task(user, task, db_user_id):
        raise HTTPException(status_code=403, detail="Not your task.")

    item = (
        db.query(TaskChecklistItem)
        .filter(TaskChecklistItem.id == item_id, TaskChecklistItem.task_id == task_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Checklist item not found.")

    if payload.label is not None:
        if not role_at_least(user, "operator"):
            raise HTTPException(status_code=403, detail="Only admin/operator can rename items.")
        item.label = payload.label
    if payload.done is not None:
        item.done = payload.done

    db.commit()
    return {"id": item.id, "label": item.label, "done": item.done, "order_index": item.order_index}


@router.delete("/{task_id}/checklist/{item_id}")
async def delete_checklist_item(
    task_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_manager_or_admin),
):
    item = (
        db.query(TaskChecklistItem)
        .filter(TaskChecklistItem.id == item_id, TaskChecklistItem.task_id == task_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Checklist item not found.")
    db.delete(item)
    db.commit()
    return {"ok": True}


# ── Comments ───────────────────────────────────────────────────

@router.post("/{task_id}/comments", status_code=201)
async def add_comment(
    task_id: int,
    payload: CommentPayload,
    request: Request,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_role),
):
    user = get_current_user(request)
    db_user = _current_db_user(request, db)
    db_user_id = db_user.user_id if db_user else None

    task = _task_or_404(db, task_id)
    if not _can_see_task(user, task, db_user_id):
        raise HTTPException(status_code=403, detail="Not your task.")

    if not db_user_id:
        raise HTTPException(
            status_code=400,
            detail="Your account is env-managed. Ask an admin to migrate it.",
        )

    comment = TaskComment(task_id=task_id, author_user_id=db_user_id, body=payload.body)
    db.add(comment)
    db.commit()
    db.refresh(comment)

    author = _user_map(db, {db_user_id}).get(db_user_id)
    return {
        "id": comment.id,
        "body": comment.body,
        "created_at": comment.created_at.isoformat() if comment.created_at else None,
        "author": author,
    }
