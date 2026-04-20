import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger("zpay.disputes")

_DISPUTE_PATTERNS = [
    (re.compile(r"wrong.?pay|incorrect.?pay|underpay|overpay|bad.?rate", re.I), "wrong_pay"),
    (re.compile(r"missing.?ride|didn.?t.?get.?paid|not.?paid|unpaid|no.?ride", re.I), "missing_ride"),
    (re.compile(r"rate.?issue|rate.?wrong|rate.?change|wrong.?rate|low.?rate", re.I), "rate_issue"),
]


def detect_dispute_type(body: str) -> str | None:
    for pattern, label in _DISPUTE_PATTERNS:
        if pattern.search(body):
            return label
    return None


def create_dispute(from_phone: str, body: str, dispute_type: str) -> dict:
    from backend.db import SessionLocal
    from backend.db.models import OpsNote

    note_body = f"[DISPUTE:{dispute_type.upper()}] From {from_phone}: {body}"
    db = SessionLocal()
    try:
        note = OpsNote(
            body=note_body,
            created_by="whatsapp_bot",
            done=False,
            created_at=datetime.now(timezone.utc),
        )
        db.add(note)
        db.commit()
        db.refresh(note)
        logger.info("Dispute created — id=%s type=%s from=%s", note.id, dispute_type, from_phone)
        return {"id": note.id, "type": dispute_type, "body": note_body}
    except Exception as e:
        db.rollback()
        logger.error("Failed to create dispute record: %s", e)
        raise
    finally:
        db.close()


def list_disputes(limit: int = 50) -> list[dict]:
    from backend.db import SessionLocal
    from backend.db.models import OpsNote

    db = SessionLocal()
    try:
        rows = (
            db.query(OpsNote)
            .filter(OpsNote.body.like("[DISPUTE:%"))
            .order_by(OpsNote.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": r.id,
                "body": r.body,
                "done": r.done,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    finally:
        db.close()
