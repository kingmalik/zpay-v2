"""
Paychex Bot API — triggers headless Playwright automation to fill payroll in Paychex Flex.
The bot fills all driver amounts but never submits. Malik reviews and submits manually.
"""

import logging
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, BackgroundTasks, Body, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import PayrollBatch, PaychexSession
from backend.routes.summary import _build_summary
from backend.services.r2_storage import get_r2_client, r2_configured
from backend.utils.roles import require_role

logger = logging.getLogger(__name__)

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

# ── In-memory session store ────────────────────────────────────────────────────
# Keyed by company bucket ("acumen" or "maz").
# Value is a list of cookie dicts captured from a real browser session.
# These are passed directly to Playwright so the bot skips the login flow.
_sessions: dict[str, list[dict]] = {}  # "acumen" or "maz" → list of cookie dicts

# Paychex client IDs by company bucket
_COMPANY_IDS = {
    "maz": "17182126",
    "acumen": "70189220",
}


# ── POST /sync-session ────────────────────────────────────────────────────────

@router.post("/sync-session")
async def sync_session(
    payload: dict = Body(...),
) -> JSONResponse:
    """
    Accepts pre-captured browser cookies for a given company and stores them
    in-memory so the bot can skip the login flow entirely on the next run.

    Body: {"company": "acumen" | "maz", "cookies": [...]}
    """
    company = (payload.get("company") or "").strip().lower()
    cookies = payload.get("cookies")

    if company not in ("acumen", "maz"):
        return JSONResponse(
            {"error": "Invalid company. Must be 'acumen' or 'maz'."},
            status_code=400,
        )
    if not isinstance(cookies, list) or len(cookies) == 0:
        return JSONResponse(
            {"error": "cookies must be a non-empty list of cookie dicts."},
            status_code=400,
        )

    _sessions[company] = cookies
    return JSONResponse({"ok": True, "count": len(cookies), "company": company})


# ── GET /session-status ───────────────────────────────────────────────────────

@router.get("/session-status")
def session_status(db: Session = Depends(get_db)) -> JSONResponse:
    """
    Returns whether each company has stored session cookies and when they were captured.
    Checks the DB first (persistent across restarts), then falls back to in-memory.
    """
    db_sessions = db.query(PaychexSession).all()
    result: dict = {}
    for s in db_sessions:
        result[s.company] = {
            "has_session": True,
            "captured_at": s.captured_at.isoformat(),
            "source": "db",
        }
    # Fill in any companies not in DB but present in memory
    for co in ("acumen", "maz"):
        if co not in result:
            in_mem = co in _sessions and len(_sessions[co]) > 0
            result[co] = {
                "has_session": in_mem,
                "captured_at": None,
                "source": "memory" if in_mem else None,
            }
    return JSONResponse(result)


# ── POST /store-session/{company} ─────────────────────────────────────────────

@router.post("/store-session/{company}")
async def store_session(
    company: str,
    request: Request,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Accepts browser-captured cookies for the given company and persists them
    to the database so they survive Railway restarts.

    Body: {"cookies": [...list of cookie dicts...]}
    """
    secret = request.headers.get("X-Internal-Secret", "")
    expected = os.environ.get("ZPAY_INTERNAL_SECRET", "")
    if not expected:
        return JSONResponse({"error": "Internal secret not configured"}, status_code=503)
    if secret != expected:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    company = company.strip().lower()
    if company not in ("acumen", "maz"):
        return JSONResponse(
            {"error": "Invalid company. Must be 'acumen' or 'maz'."},
            status_code=400,
        )

    body = await request.json()
    cookies = body.get("cookies", [])
    if not isinstance(cookies, list) or len(cookies) == 0:
        return JSONResponse({"error": "No cookies provided"}, status_code=400)

    # Upsert into paychex_sessions
    session_row = db.query(PaychexSession).filter_by(company=company).first()
    if session_row:
        session_row.cookies = cookies
        session_row.captured_at = datetime.now(timezone.utc)
    else:
        session_row = PaychexSession(
            company=company,
            cookies=cookies,
            captured_at=datetime.now(timezone.utc),
        )
        db.add(session_row)
    db.commit()

    # Also update the in-memory cache so an immediately-triggered bot run benefits
    _sessions[company] = cookies

    return JSONResponse({"ok": True, "company": company, "cookie_count": len(cookies)})


# ── POST /capture/{company} — admin-only in-app session capture ───────────────

# Well-known Paychex cookie names that must be present for the bot to work.
# HttpOnly cookies (e.g. session tokens) will NOT appear here — JS can't read them.
_KNOWN_CRITICAL_COOKIES = {
    "JSESSIONID",
    "paychex_session",
    "SSO_SESSION",
    "AWSALB",
    "AWSALBCORS",
}

@router.post(
    "/capture/{company}",
    dependencies=[Depends(require_role("admin"))],
)
async def capture_session_from_browser(
    company: str,
    request: Request,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Admin-only endpoint called by the in-app Paychex reauth UI after Malik
    signs in through the popup window and clicks "Capture my session."

    The browser popup (on paychex.com domain) reads document.cookie and posts
    them here via window.opener.postMessage → parent window fetch → this endpoint.

    NOTE: HttpOnly cookies are NOT readable by JS — only non-HttpOnly cookies
    will arrive here. The bot may still fail if Paychex requires HttpOnly session
    tokens (we will learn this on the first live capture attempt).

    Body: {"cookies": [...cookie dicts or raw string...]}
    Accepts two formats:
      - List of dicts: [{"name": "x", "value": "y", ...}, ...]
      - Raw cookie string: "name1=value1; name2=value2"
    """
    company = company.strip().lower()
    if company not in ("acumen", "maz"):
        return JSONResponse(
            {"error": "Invalid company. Must be 'acumen' or 'maz'."},
            status_code=400,
        )

    body = await request.json()
    raw = body.get("cookies")

    if raw is None:
        return JSONResponse({"error": "cookies field is required"}, status_code=400)

    # Normalise to list of dicts
    cookies: list[dict] = []
    if isinstance(raw, str):
        # Parse "name1=val1; name2=val2" format
        for pair in raw.split(";"):
            pair = pair.strip()
            if "=" in pair:
                name, _, value = pair.partition("=")
                cookies.append({"name": name.strip(), "value": value.strip()})
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and item.get("name"):
                cookies.append(item)
    else:
        return JSONResponse(
            {"error": "cookies must be a list of cookie dicts or a raw cookie string"},
            status_code=400,
        )

    if not cookies:
        return JSONResponse({"error": "No valid cookies parsed"}, status_code=400)

    # Identify which well-known critical cookies arrived (and which are missing)
    arrived_names = {c["name"] for c in cookies}
    missing_critical = _KNOWN_CRITICAL_COOKIES - arrived_names
    # Log only names+counts — never values
    logger.info(
        "Paychex capture for '%s': %d cookies received. Names: %s",
        company,
        len(cookies),
        sorted(arrived_names),
    )
    if missing_critical:
        logger.warning(
            "Paychex capture for '%s': well-known critical cookies not present "
            "(likely HttpOnly): %s",
            company,
            sorted(missing_critical),
        )

    # Upsert into paychex_sessions (same shape as /store-session)
    session_row = db.query(PaychexSession).filter_by(company=company).first()
    if session_row:
        session_row.cookies = cookies
        session_row.captured_at = datetime.now(timezone.utc)
    else:
        session_row = PaychexSession(
            company=company,
            cookies=cookies,
            captured_at=datetime.now(timezone.utc),
        )
        db.add(session_row)
    db.commit()

    # Keep in-memory cache fresh
    _sessions[company] = cookies

    return JSONResponse({
        "ok": True,
        "company": company,
        "cookie_count": len(cookies),
        "cookie_names": sorted(arrived_names),
        "missing_critical": sorted(missing_critical),
        "warning": (
            f"These well-known cookies were not captured (likely HttpOnly — JS cannot read them): "
            f"{sorted(missing_critical)}"
        ) if missing_critical else None,
    })


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


# ── R2 debug upload helper ─────────────────────────────────────────────────────

def _upload_snaps_to_r2(job_id: str, snap_dir: str) -> list[str]:
    """
    Uploads every file in snap_dir to R2 under paychex-debug/{job_id}/.
    Returns a list of presigned URLs (7-day TTL) for each uploaded file.
    Wrapped in try/except by the caller — this function may raise.
    """
    bucket = os.environ.get("R2_BUCKET", "zpay-driver-docs")
    client = get_r2_client()
    urls: list[str] = []

    for file_path in sorted(Path(snap_dir).iterdir()):
        if not file_path.is_file():
            continue
        key = f"paychex-debug/{job_id}/{file_path.name}"
        content_type = "image/png" if file_path.suffix == ".png" else "text/html"
        with open(file_path, "rb") as fh:
            client.put_object(
                Bucket=bucket,
                Key=key,
                Body=fh.read(),
                ContentType=content_type,
            )
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=7 * 24 * 3600,  # 7 days
        )
        urls.append(url)

    return urls


# ── Background task ────────────────────────────────────────────────────────────

async def _run_bot(
    job_id: str,
    company: str,
    username: str,
    password: str,
    drivers: list[dict],
    session_cookies: list[dict] | None = None,
) -> None:
    """
    Runs the Paychex Playwright bot in the background.
    Updates _jobs[job_id] via the on_status callback.
    Accepts pre-loaded session_cookies (from DB) to skip the login flow.
    Screenshots are saved to /tmp/paychex-snaps/{job_id}/ during the run,
    then uploaded to R2 under paychex-debug/{job_id}/ and cleaned up.
    """
    from backend.paychex_bot.paychex_entry import run_paychex_entry

    snap_dir = f"/tmp/paychex-snaps/{job_id}"
    os.makedirs(snap_dir, exist_ok=True)

    def on_status(data: dict) -> None:
        update: dict = {}
        if "status" in data:
            update["status"] = data["status"]
        if "progress" in data:
            update["progress"] = data["progress"]
        if "total" in data:
            update["total"] = data["total"]
        if "current_driver" in data:
            update["current_driver"] = data["current_driver"]
        if "message" in data:
            update["message"] = data["message"]
        if "error" in data:
            update["error"] = data["error"]
        _jobs[job_id].update(update)

    try:
        await run_paychex_entry(
            company,
            username,
            password,
            drivers,
            on_status,
            session_cookies=session_cookies,
            screenshot_dir=snap_dir,
        )
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
    finally:
        # Upload snaps to R2 regardless of success/failure, then clean up /tmp.
        # Upload failure must never crash the bot result — log and continue.
        debug_urls: list[str] = []
        if r2_configured():
            try:
                debug_urls = _upload_snaps_to_r2(job_id, snap_dir)
                logger.info("Uploaded %d debug snaps to R2 for job %s", len(debug_urls), job_id)
            except Exception:
                logger.exception("Failed to upload Paychex debug snaps to R2 for job %s", job_id)
        else:
            logger.warning("R2 not configured — skipping debug snap upload for job %s", job_id)

        try:
            shutil.rmtree(snap_dir, ignore_errors=True)
        except Exception:
            logger.exception("Failed to clean up snap_dir %s for job %s", snap_dir, job_id)

        _jobs[job_id]["debug_urls"] = debug_urls


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

    # Load session cookies from DB (persistent) — fall back to in-memory if not in DB
    session_row = db.query(PaychexSession).filter_by(company=company_bucket).first()
    if session_row:
        session_cookies = session_row.cookies  # native JSON list, no deserialization needed
    else:
        # Fall back to in-memory cookies (captured via /sync-session)
        session_cookies = _sessions.get(company_bucket) or None

    # Create job entry
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "status": "pending",
        "progress": 0,
        "total": len(drivers),
        "current_driver": "",
        "message": "Starting...",
        "error": None,
        "debug_urls": [],
    }

    # Launch bot as background task (FastAPI natively supports async background tasks)
    background_tasks.add_task(_run_bot, job_id, company_bucket, username, password, drivers, session_cookies)

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
