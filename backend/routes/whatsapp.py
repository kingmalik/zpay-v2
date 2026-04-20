import logging
from typing import Optional

from fastapi import APIRouter, Request, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from backend.services.whatsapp_service import parse_incoming, build_bot_reply, send_whatsapp

logger = logging.getLogger("zpay.whatsapp.routes")

router = APIRouter(tags=["whatsapp"])


@router.get("/webhooks/whatsapp")
def whatsapp_verify(request: Request):
    # Twilio doesn't use a challenge/verify handshake for WhatsApp like Meta does,
    # but keep this endpoint live for manual health checks.
    return PlainTextResponse("ok")


@router.post("/webhooks/whatsapp")
async def whatsapp_webhook(request: Request):
    form = await request.form()
    data = dict(form)
    msg = parse_incoming(data)

    logger.info("WhatsApp inbound from %s: %s", msg["from"], msg["body"][:80])

    reply_text = build_bot_reply(msg["body"], from_phone=msg["from"])

    if reply_text:
        from_number = msg["from"]
        if from_number:
            send_whatsapp(from_number, reply_text)
    else:
        logger.debug("No bot reply for message: %r", msg["body"])

    # Twilio expects a 200 with empty TwiML or plain 200
    return Response(
        content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
        media_type="application/xml",
        status_code=200,
    )


# ── Disputes API ──────────────────────────────────────────────

class CreateDisputeRequest(BaseModel):
    from_phone: str
    body: str
    dispute_type: Optional[str] = None


@router.get("/api/data/disputes")
def list_disputes_endpoint(limit: int = 50):
    from backend.services.dispute_service import list_disputes
    return {"disputes": list_disputes(limit=limit)}


@router.post("/api/data/disputes")
def create_dispute_endpoint(payload: CreateDisputeRequest):
    from backend.services.dispute_service import detect_dispute_type, create_dispute
    dispute_type = payload.dispute_type or detect_dispute_type(payload.body) or "general"
    record = create_dispute(payload.from_phone, payload.body, dispute_type)
    return {"ok": True, "dispute": record}
