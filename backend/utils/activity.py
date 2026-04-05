"""Activity logging helper — call from any route to log user actions."""

from datetime import datetime, timezone
from backend.db.models import ActivityLog


def log_activity(
    db,
    request,
    action: str,
    description: str,
    entity_type: str = None,
    entity_id: int = None,
):
    """Log a user action to the activity_log table."""
    try:
        user = getattr(request.state, "user", None) or {}
        entry = ActivityLog(
            username=user.get("username", "system"),
            display_name=user.get("display_name", "System"),
            user_color=user.get("color"),
            action=action,
            description=description,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        db.add(entry)
        db.commit()
    except Exception:
        pass  # Never let logging crash the main request
