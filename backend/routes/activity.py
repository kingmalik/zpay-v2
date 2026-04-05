"""Activity log — shows who did what and when."""

from pathlib import Path

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import ActivityLog

router = APIRouter(tags=["activity"])
_templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))


@router.get("/activity", response_class=HTMLResponse)
async def activity_page(
    request: Request,
    username: str = "",
    db: Session = Depends(get_db),
):
    q = db.query(ActivityLog).order_by(ActivityLog.created_at.desc())
    if username:
        q = q.filter(ActivityLog.username == username)
    logs = q.limit(200).all()

    entries = []
    for log in logs:
        entries.append({
            "id": log.id,
            "username": log.username,
            "display_name": log.display_name,
            "color": log.user_color or "#667eea",
            "action": log.action,
            "description": log.description,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id,
            "created_at": log.created_at,
            "time_ago": _time_ago(log.created_at),
        })

    return _templates.TemplateResponse(request, "activity.html", {
        "entries": entries,
        "filter_username": username,
    })


def _time_ago(dt) -> str:
    if not dt:
        return "—"
    from datetime import timezone
    now = __import__("datetime").datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = now - dt
    s = int(diff.total_seconds())
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"
