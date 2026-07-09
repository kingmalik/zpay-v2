"""Partner deposit CRUD (S1.5 reconciliation).

Records deposits received from partner companies (FA/Acumen, EverDriven)
so reconciliation can diff them against expected batch revenue and run
the FA TPA §6b 14-day dispute clock.

All routes return JSON under /api/data/partner-payments.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import PartnerPayment, PayrollBatch

router = APIRouter(prefix="/api/data/partner-payments", tags=["partner-payments"])

_VALID_SOURCES = ("acumen", "maz")


def _payment_to_dict(p: PartnerPayment) -> dict:
    return {
        "partner_payment_id": p.partner_payment_id,
        "source": p.source,
        "amount": float(p.amount),
        "deposit_date": p.deposit_date.isoformat() if p.deposit_date else None,
        "payroll_batch_id": p.payroll_batch_id,
        "memo": p.memo,
        "disputed_at": p.disputed_at.isoformat() if p.disputed_at else None,
        "dispute_note": p.dispute_note,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "created_by": p.created_by,
    }


@router.get("")
def list_partner_payments(
    batch_id: int | None = None,
    source: str | None = None,
    db: Session = Depends(get_db),
):
    try:
        q = db.query(PartnerPayment)
        if batch_id is not None:
            q = q.filter(PartnerPayment.payroll_batch_id == batch_id)
        if source:
            q = q.filter(PartnerPayment.source == source)
        payments = q.order_by(PartnerPayment.deposit_date.desc()).limit(500).all()
        return JSONResponse({"payments": [_payment_to_dict(p) for p in payments]})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.post("/create")
async def create_partner_payment(request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.json()

        source = (body.get("source") or "").strip().lower()
        if source not in _VALID_SOURCES:
            return JSONResponse(
                {"error": f"source must be one of {_VALID_SOURCES}"}, status_code=400
            )

        try:
            amount = round(float(body.get("amount")), 2)
        except (TypeError, ValueError):
            return JSONResponse({"error": "amount must be a number"}, status_code=400)
        if amount <= 0:
            return JSONResponse({"error": "amount must be positive"}, status_code=400)

        try:
            deposit_date = date.fromisoformat((body.get("deposit_date") or "").strip())
        except ValueError:
            return JSONResponse(
                {"error": "deposit_date must be YYYY-MM-DD"}, status_code=400
            )

        batch_id = body.get("payroll_batch_id")
        if batch_id is not None:
            batch = (
                db.query(PayrollBatch)
                .filter(PayrollBatch.payroll_batch_id == int(batch_id))
                .first()
            )
            if not batch:
                return JSONResponse(
                    {"error": f"batch {batch_id} not found"}, status_code=404
                )

        payment = PartnerPayment(
            source=source,
            amount=amount,
            deposit_date=deposit_date,
            payroll_batch_id=int(batch_id) if batch_id is not None else None,
            memo=(body.get("memo") or "").strip() or None,
            created_by=(body.get("created_by") or "").strip() or None,
        )
        db.add(payment)
        db.commit()
        db.refresh(payment)
        return JSONResponse(
            {"ok": True, "payment": _payment_to_dict(payment)}, status_code=201
        )
    except Exception as exc:
        db.rollback()
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.post("/{payment_id}/dispute")
async def dispute_partner_payment(
    payment_id: int, request: Request, db: Session = Depends(get_db)
):
    """Record that a written dispute was filed for this deposit's shortfall.

    This is the FA TPA §6b action — it stops the dispute-deadline alerts
    for the linked batch. The note should say where the written dispute
    lives (email subject/date).
    """
    try:
        body = await request.json()
        payment = (
            db.query(PartnerPayment)
            .filter(PartnerPayment.partner_payment_id == payment_id)
            .first()
        )
        if not payment:
            return JSONResponse({"error": "payment not found"}, status_code=404)

        note = (body.get("note") or "").strip()
        if not note:
            return JSONResponse(
                {"error": "note is required — cite the written dispute (email subject + date)"},
                status_code=400,
            )

        payment.disputed_at = datetime.now(timezone.utc)
        payment.dispute_note = note
        db.commit()
        db.refresh(payment)
        return JSONResponse({"ok": True, "payment": _payment_to_dict(payment)})
    except Exception as exc:
        db.rollback()
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.delete("/{payment_id}")
def delete_partner_payment(payment_id: int, db: Session = Depends(get_db)):
    """Remove a mis-entered deposit row."""
    try:
        payment = (
            db.query(PartnerPayment)
            .filter(PartnerPayment.partner_payment_id == payment_id)
            .first()
        )
        if not payment:
            return JSONResponse({"error": "payment not found"}, status_code=404)
        db.delete(payment)
        db.commit()
        return JSONResponse({"ok": True, "deleted": payment_id})
    except Exception as exc:
        db.rollback()
        return JSONResponse({"error": str(exc)}, status_code=500)
