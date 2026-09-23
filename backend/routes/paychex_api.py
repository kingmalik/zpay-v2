"""
Paychex External API rail — replaces the Playwright pay-entry bot
(backend/routes/paychex_bot.py) with the official Paychex Flex API.

There is no submit/release endpoint in the Paychex API (confirmed in
docs/PAYCHEX-API-SPEC-2026-09-16.md) — this rail only stages checks into an
open pay period. A human still opens Flex and submits payroll (law:
automation types, humans move money).

Admin-gated behind PAYCHEX_API_ENABLED=1 until Malik releases it — every
endpoint returns 404 {"error": "Paychex API rail is disabled"} otherwise.

See docs/PAYCHEX-API-RAIL-PLAN-2026-09-16.md for the full flow this
implements.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from decimal import Decimal

import requests
from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text as sql_text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import BatchWorkflowLog, PaychexApiCheck, PayrollBatch
from backend.routes.paychex_bot import _resolve_company
from backend.routes.summary import _build_summary
from backend.services.paychex_api import (
    OPEN_PAY_PERIOD_STATUSES,
    PaychexApiClient,
    PaychexApiConfigError,
    PaychexApiError,
)
from backend.services.paychex_api_matching import (
    build_worker_index,
    component_supports_contractor,
    count_contractor_workers,
    filter_contractor_components,
    match_rows,
    select_pay_period,
)
from backend.utils.roles import require_role

logger = logging.getLogger("zpay.paychex_api")

router = APIRouter(prefix="/api/data/paychex-api", tags=["paychex-api"])

_COMPANIES = ("acumen", "maz")


# ── Feature flag ─────────────────────────────────────────────────────────────

# Money only moves after a human approved the batch in Z-Pay (law: humans
# move money). Earlier stages still have unpriced or unreviewed rows.
STAGEABLE_BATCH_STATUSES = frozenset({"approved", "export_ready", "stubs_sending", "complete"})


def _rail_disabled_response() -> JSONResponse | None:
    if os.environ.get("PAYCHEX_API_ENABLED") != "1":
        return JSONResponse({"error": "Paychex API rail is disabled"}, status_code=404)
    return None


# ── Shared error mapping ─────────────────────────────────────────────────────

def _paychex_error_response(exc: Exception) -> JSONResponse:
    """Every Paychex-facing call error becomes a clean JSONResponse — never a raw 500."""
    if isinstance(exc, PaychexApiConfigError):
        return JSONResponse({"error": str(exc)}, status_code=400)
    if isinstance(exc, PaychexApiError):
        status = exc.status_code if exc.status_code and 400 <= exc.status_code < 600 else 502
        return JSONResponse({"error": str(exc)}, status_code=status)
    return JSONResponse({"error": f"Paychex network error: {exc}"}, status_code=502)


_PAYCHEX_EXCEPTIONS = (PaychexApiConfigError, PaychexApiError, requests.RequestException)


# ── Row shaping ──────────────────────────────────────────────────────────────

def _load_withhold_overrides(db: Session, batch_id: int) -> tuple[set[int] | None, set[int] | None]:
    """Same override tables paychex_bot.push_to_paychex reads, so the eligible-driver
    list here matches the reviewed/approved state shown in the UI."""
    try:
        override_rows = db.execute(
            sql_text("SELECT person_id FROM payroll_withheld_override WHERE batch_id = :b"),
            {"b": batch_id},
        ).fetchall()
        manual_rows = db.execute(
            sql_text("SELECT person_id FROM payroll_manual_withhold"),
        ).fetchall()
        return ({r[0] for r in override_rows} or None), ({r[0] for r in manual_rows} or None)
    except Exception as exc:
        logger.warning("[paychex-api] override tables unavailable, continuing without them: %s", exc)
        db.rollback()
        return None, None


def _eligible_rows(db: Session, batch: PayrollBatch) -> list[dict]:
    override_ids, manual_withhold_ids = _load_withhold_overrides(db, batch.payroll_batch_id)
    summary = _build_summary(
        db,
        batch_id=batch.payroll_batch_id,
        override_ids=override_ids,
        manual_withhold_ids=manual_withhold_ids,
    )
    return [
        row for row in summary.get("rows", [])
        if row.get("pay_this_period", 0) > 0 and not row.get("withheld", False)
    ]


def _row_summary(row: dict) -> dict:
    return {
        "person_id": row.get("person_id"),
        "person": row.get("person"),
        "code": row.get("code"),
        "amount": row.get("pay_this_period"),
        "worker_id": row.get("worker_id"),
        "worker_name": row.get("worker_name"),
        "reason": row.get("reason"),
    }


def _period_summary(period: dict) -> dict:
    return {
        "pay_period_id": period.get("payPeriodId"),
        "start_date": period.get("startDate"),
        "end_date": period.get("endDate"),
        "status": period.get("status"),
        "check_date": period.get("checkDate"),
        "description": period.get("description"),
    }


def _component_summary(component: dict) -> dict:
    return {
        "component_id": component.get("componentId"),
        "name": component.get("name"),
        "applies_to_worker_types": component.get("appliesToWorkerTypes"),
    }


# ── Preview (shared by GET preview and POST push) ───────────────────────────

def _build_preview(db: Session, batch: PayrollBatch) -> dict:
    company_bucket = _resolve_company(batch.company_name)
    client = PaychexApiClient(company_bucket)

    rows = _eligible_rows(db, batch)
    index = build_worker_index(client.get_workers())
    matched, unmatched = match_rows(rows, index)

    periods = client.get_pay_periods(OPEN_PAY_PERIOD_STATUSES)
    period = select_pay_period(periods, batch.period_start, batch.period_end)

    components = client.get_pay_components()
    component_ok = bool(client.component_id) and component_supports_contractor(components, client.component_id)

    total_amount = sum((Decimal(str(r["pay_this_period"])) for r in matched), Decimal("0"))

    return {
        "batch_id": batch.payroll_batch_id,
        "company": company_bucket,
        "pay_period": _period_summary(period) if period else None,
        "pay_period_error": None if period else (
            "No open pay period (INITIAL/ENTRY) matches this batch's period_start/period_end."
        ),
        "open_pay_periods": [] if period else [_period_summary(p) for p in periods],
        "component_id": client.component_id or None,
        "component_ok": component_ok,
        "matched": [_row_summary(r) for r in matched],
        "unmatched": [_row_summary(r) for r in unmatched],
        "total_amount": float(total_amount),
        "count": len(matched),
    }


def _load_batch(db: Session, batch_id: int) -> PayrollBatch | None:
    return db.query(PayrollBatch).filter(PayrollBatch.payroll_batch_id == batch_id).first()


# ── GET /{company}/health ────────────────────────────────────────────────────

@router.get("/{company}/health", dependencies=[Depends(require_role("admin"))])
def get_health(company: str) -> JSONResponse:
    disabled = _rail_disabled_response()
    if disabled:
        return disabled

    company_bucket = company.strip().lower()
    if company_bucket not in _COMPANIES:
        return JSONResponse({"error": "Invalid company. Must be 'acumen' or 'maz'."}, status_code=400)

    client = PaychexApiClient(company_bucket)
    try:
        client.get_access_token()
        workers = client.get_workers()
        periods = client.get_open_pay_periods()
        components = client.get_pay_components()
    except _PAYCHEX_EXCEPTIONS as exc:
        return _paychex_error_response(exc)

    return JSONResponse({
        "company": company_bucket,
        "token_ok": True,
        "company_name": client.get_company_name(),
        "contractor_count": count_contractor_workers(workers),
        "open_pay_periods": [_period_summary(p) for p in periods],
        "candidate_1099_components": [_component_summary(c) for c in filter_contractor_components(components)],
        "configured_component_id": client.component_id or None,
    })


# ── POST /preview/{batch_id} ─────────────────────────────────────────────────

@router.post("/preview/{batch_id}", dependencies=[Depends(require_role("admin", "operator"))])
def preview_batch(batch_id: int, db: Session = Depends(get_db)) -> JSONResponse:
    disabled = _rail_disabled_response()
    if disabled:
        return disabled

    batch = _load_batch(db, batch_id)
    if not batch:
        return JSONResponse({"error": f"Batch {batch_id} not found."}, status_code=404)

    try:
        result = _build_preview(db, batch)
    except _PAYCHEX_EXCEPTIONS as exc:
        return _paychex_error_response(exc)

    return JSONResponse(result)


# ── POST /push/{batch_id} ────────────────────────────────────────────────────

@router.post("/push/{batch_id}", dependencies=[Depends(require_role("admin", "operator"))])
def push_batch(batch_id: int, db: Session = Depends(get_db), body: dict | None = Body(default=None)) -> JSONResponse:
    disabled = _rail_disabled_response()
    if disabled:
        return disabled

    batch = _load_batch(db, batch_id)
    if not batch:
        return JSONResponse({"error": f"Batch {batch_id} not found."}, status_code=404)

    if batch.status not in STAGEABLE_BATCH_STATUSES:
        return JSONResponse(
            {"error": f"Batch must be approved before staging in Paychex (status={batch.status})."},
            status_code=400,
        )
    skip_unmatched = bool((body or {}).get("skip_unmatched", False))

    try:
        preview = _build_preview(db, batch)
    except _PAYCHEX_EXCEPTIONS as exc:
        return _paychex_error_response(exc)

    if preview["unmatched"] and not skip_unmatched:
        return JSONResponse(
            {"error": "Unmatched rows present — resolve or pass skip_unmatched=true.", "unmatched": preview["unmatched"]},
            status_code=400,
        )
    if not preview["pay_period"]:
        return JSONResponse(
            {"error": preview["pay_period_error"], "open_pay_periods": preview["open_pay_periods"]},
            status_code=400,
        )
    if not preview["component_ok"]:
        return JSONResponse(
            {"error": f"Pay component '{preview['component_id']}' is not configured or not eligible for INDEPENDENT_CONTRACTOR."},
            status_code=400,
        )

    matched = preview["matched"]
    if not matched:
        return JSONResponse({"error": "No eligible rows to stage."}, status_code=400)

    # Only rows that exist (or may exist) in Paychex block a re-send: "staged"
    # and in-flight "pending". A "failed" row never reached Paychex, so the
    # operator can press Send again after a fix (9/23: every row failed API-13,
    # the fix deployed, and the button had to work a second time).
    existing = db.query(PaychexApiCheck).filter(PaychexApiCheck.payroll_batch_id == batch_id).all()
    blocking_ids = {row.person_id for row in existing if row.status != FAILED_STATUS}
    failed_rows = [row for row in existing if row.status == FAILED_STATUS]

    retry_matched = [row for row in matched if row["person_id"] not in blocking_ids]
    if not retry_matched:
        return JSONResponse(
            {
                "error": "This batch already has staged Paychex API checks — refusing to stage again.",
                "already_staged_person_ids": sorted(blocking_ids),
            },
            status_code=400,
        )

    for row in failed_rows:
        db.delete(row)
    db.commit()

    return _stage_and_record(db, batch, preview, retry_matched)


def _stage_and_record(db: Session, batch: PayrollBatch, preview: dict, matched: list[dict]) -> JSONResponse:
    company_bucket = preview["company"]
    client = PaychexApiClient(company_bucket)
    period_id = preview["pay_period"]["pay_period_id"]
    component_id = client.component_id

    checks_payload = [
        {
            "person_id": row["person_id"],
            "worker_id": row["worker_id"],
            "pay_period_id": period_id,
            "component_id": component_id,
            "amount": row["amount"],
        }
        for row in matched
    ]
    # Claim every (batch, person) row BEFORE talking to Paychex. The unique
    # index makes a second concurrent push fail here, not after Paychex has
    # already accepted duplicate checks.
    claimed = _claim_rows(db, batch, company_bucket, period_id, matched)
    if claimed is None:
        return JSONResponse(
            {"error": "Another push already claimed this batch — refusing to stage twice."},
            status_code=409,
        )
    try:
        results = client.stage_checks(checks_payload)
    except _PAYCHEX_EXCEPTIONS as exc:
        _release_claims(db, claimed)
        return _paychex_error_response(exc)

    staged_count, total_staged, result_rows = _record_check_results(db, claimed, matched, results)

    if staged_count > 0:
        _mark_batch_exported(db, batch, staged_count, len(matched), total_staged)

    db.commit()

    failed_count = len(matched) - staged_count
    return JSONResponse(
        {
            "batch_id": batch.payroll_batch_id,
            "company": company_bucket,
            "staged": staged_count,
            "failed": failed_count,
            "total": len(matched),
            "results": result_rows,
        },
        status_code=200 if failed_count == 0 else 207,
    )


CLAIM_STATUS = "pending"
FAILED_STATUS = "failed"


def _claim_rows(
    db: Session, batch: PayrollBatch, company_bucket: str, period_id: str, matched: list[dict],
) -> list[PaychexApiCheck] | None:
    """Insert a pending row per matched driver and commit. None = someone else got there first."""
    claims = [
        PaychexApiCheck(
            payroll_batch_id=batch.payroll_batch_id,
            person_id=row["person_id"],
            company=company_bucket,
            worker_id=row["worker_id"],
            pay_period_id=period_id,
            amount=Decimal(str(row["amount"])),
            status=CLAIM_STATUS,
        )
        for row in matched
    ]
    try:
        db.add_all(claims)
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    return claims


def _release_claims(db: Session, claimed: list[PaychexApiCheck]) -> None:
    """Paychex never answered — drop the claims so a retry is possible."""
    for claim in claimed:
        db.delete(claim)
    db.commit()


def _record_check_results(
    db: Session, claimed: list[PaychexApiCheck], matched: list[dict], results: list[dict],
) -> tuple[int, Decimal, list[dict]]:
    staged_count = 0
    total_staged = Decimal("0")
    result_rows: list[dict] = []
    for claim, row, result in zip(claimed, matched, results):
        amount = Decimal(str(row["amount"]))
        claim.status = result["status"]
        claim.paycheck_id = result.get("paycheck_id")
        claim.error = result.get("error")
        if result["status"] == "staged":
            staged_count += 1
            total_staged += amount
        result_rows = result_rows + [{
            "person_id": row["person_id"],
            "person": row["person"],
            "amount": row["amount"],
            "status": result["status"],
            "paycheck_id": result.get("paycheck_id"),
            "error": result.get("error"),
        }]
    return staged_count, total_staged, result_rows


def _mark_batch_exported(db: Session, batch: PayrollBatch, staged_count: int, total: int, total_staged: Decimal) -> None:
    if batch.paychex_exported_at is None:
        batch.paychex_exported_at = datetime.now(timezone.utc)
    db.add(BatchWorkflowLog(
        payroll_batch_id=batch.payroll_batch_id,
        from_status=batch.status,
        to_status=batch.status,
        triggered_by="user",
        notes=f"Paychex API: staged {staged_count}/{total} checks (${total_staged:.2f}).",
    ))
