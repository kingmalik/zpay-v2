"""
Paychex Bot API — triggers headless Playwright automation to fill payroll in Paychex Flex.
The bot fills all driver amounts but never submits. Malik reviews and submits manually.
"""

import asyncio
import os
import uuid

from fastapi import APIRouter, Depends, BackgroundTasks
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import PayrollBatch
from backend.routes.summary import _build_summary

router = APIRouter(prefix="/api/data/paychex-bot", tags=["paychex-bot"])

# ── In-memory job store ────────────────────────────────────────────────────────
# Keyed by job_id (str UUID).
# Structure:
#   {
#     "status": str,           # "pending" | "running" | "done" | "failed"
#     "progress": int,         # number of drivers completed so far
#     "total": int,            # total drivers to process
#     "current_driver": str,   # name of driver currently being processed
#     "message": str,          # human-readable status line
#     "error": str | None,     # populated only on failure
#   }
_jobs: dict[str, dict] = {}

# Paychex client IDs by company bucket
_COMPANY_IDS = {
    "maz": "17182126",
    "acumen": "70189220",
}


def _resolve_company(company_name: str) -> str:
    """Map a raw DB company_name to 'maz' or 'acumen'."""
    cn = (company_name or "").lower()
    if "maz" in cn or "ever" in cn:
        return "maz"
    return "acumen"


def _load_credentials(company_bucket: str) -> tuple[str, str]:
    """Return (username, password) from env vars for the given company bucket."""
    if company_bucket == "maz":
        user = os.environ.get("PAYCHEX_MAZ_USER", "")
        pwd = os.environ.get("PAYCHEX_MAZ_PASS", "")
    else:
        user = os.environ.get("PAYCHEX_ACUMEN_USER", "")
        pwd = os.environ.get("PAYCHEX_ACUMEN_PASS", "")
    return user, pwd


# ── Background task ────────────────────────────────────────────────────────────

async def _run_bot(
    job_id: str,
    company: str,
    username: str,
    password: str,
    drivers: list[dict],
) -> None:
    """
    Runs the Paychex Playwright bot in the background.
    Updates _jobs[job_id] via the on_status callback.
    """
    from backend.paychex_bot.paychex_entry import run_paychex_entry

    def on_status(progress: int, total: int, current_driver: str, message: str) -> None:
        _jobs[job_id].update({
            "status": "running",
            "progress": progress,
            "total": total,
            "current_driver": current_driver,
            "message": message,
        })

    try:
        await run_paychex_entry(company, username, password, drivers, on_status)
        _jobs[job_id].update({
            "status": "done",
            "message": "Paychex fill complete — review and submit manually.",
        })
    except Exception as e:
        _jobs[job_id].update({
            "status": "failed",
            "message": "Bot encountered an error.",
            "error": str(e),
        })


# ── POST /push/{batch_id} ──────────────────────────────────────────────────────

@router.post("/push/{batch_id}")
async def push_to_paychex(
    batch_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Triggers the Paychex bot for the given batch.
    Queues a background job and returns a job_id to poll for status.
    The bot fills all driver amounts in Paychex Flex but never submits.
    """
    # Look up the batch
    batch = db.query(PayrollBatch).filter(
        PayrollBatch.payroll_batch_id == batch_id
    ).first()
    if not batch:
        return JSONResponse({"error": f"Batch {batch_id} not found."}, status_code=404)

    # Resolve company bucket and credentials
    company_bucket = _resolve_company(batch.company_name)
    username, password = _load_credentials(company_bucket)

    if not username or not password:
        return JSONResponse(
            {"error": f"Paychex credentials not configured for company '{company_bucket}'. "
                      f"Set PAYCHEX_{company_bucket.upper()}_USER and PAYCHEX_{company_bucket.upper()}_PASS."},
            status_code=500,
        )

    # Build summary rows for this batch (same logic the UI uses)
    summary = _build_summary(db, batch_id=batch_id)
    rows = summary.get("rows", [])

    # Filter: only drivers getting paid this period (not withheld, amount > 0)
    drivers = [
        {
            "worker_id": row["code"],
            "name": row["person"],
            "amount": row["pay_this_period"],
        }
        for row in rows
        if row.get("pay_this_period", 0) > 0 and not row.get("withheld", False)
    ]

    if not drivers:
        return JSONResponse(
            {"error": "No drivers eligible for payment in this batch (all withheld or zero pay)."},
            status_code=400,
        )

    # Create job entry
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "status": "pending",
        "progress": 0,
        "total": len(drivers),
        "current_driver": "",
        "message": "Starting...",
        "error": None,
    }

    # Launch bot as background task
    background_tasks.add_task(
        asyncio.ensure_future,
        _run_bot(job_id, company_bucket, username, password, drivers),
    )

    return JSONResponse({"job_id": job_id, "total": len(drivers)})


# ── GET /status/{job_id} ───────────────────────────────────────────────────────

@router.get("/status/{job_id}")
def get_job_status(job_id: str) -> JSONResponse:
    """
    Returns the current status of a Paychex bot job.
    Poll this after calling /push/{batch_id}.
    """
    job = _jobs.get(job_id)
    if job is None:
        return JSONResponse({"error": f"Job '{job_id}' not found."}, status_code=404)
    return JSONResponse(job)
