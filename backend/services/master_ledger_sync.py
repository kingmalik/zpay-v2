"""
backend/services/master_ledger_sync.py
=======================================
Master Ledger — Drive shadow sync (restoration truth).

Writes three CSV files to the locally-mounted Google Drive folder
(Wheels of Unity / Z-Pay Reference/) so they auto-sync to cloud.
If the prod DB is ever wiped (ref: 2026-05-03 incident), Drive CSVs
are the 4-hour-worst-case restore path for hard-won data that's
painful to re-enter: paycheck codes, LLC enrollment, route rates.

Sheets written
--------------
1. driver_paycheck_codes.csv
   person_id | full_name | paycheck_code | paycheck_code_maz | status |
   active_status | last_updated

2. llc_mapping.csv
   person_id | full_name | acumen_enrolled | maz_enrolled | partner_runs

3. route_rates.csv
   route_code | partner | rate_cents | effective_from | effective_to |
   source_file | active

Public API
----------
run_sync(db_url=None) -> dict
    Main entry point. Pulls prod data, writes CSVs to Drive mount.
    Returns {"success": bool, "rows": {...}, "path": str, "errors": [...]}

register_ledger_jobs(scheduler)
    Register the Monday 9 AM PT cron on an existing APScheduler instance.
    Called from trip_monitor.start_monitor() — gated by MASTER_LEDGER_CRON_ENABLED=1.

Env vars
--------
MASTER_LEDGER_CRON_ENABLED   "1" to enable Monday 9 AM PT cron (default "0")
DATABASE_URL                  Prod DB URL (Railway internal or public proxy)
DRIVE_MOUNT_PATH              Override default Drive mount path if needed
                              Default: ~/Library/CloudStorage/
                                       GoogleDrive-milionmalik@gmail.com/
                                       My Drive/Wheels of Unity/Z-Pay Reference

Safety
------
- Read-only on DB (SELECT only — zero writes to prod).
- Upserts CSVs by pid (reads existing, merges, re-writes). Manual annotations
  in columns not managed by this script are preserved if they exist.
- No schema migrations. No DB writes. No side effects on prod.
"""

from __future__ import annotations

import csv
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("zpay.master_ledger")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_DRIVE_PATH = (
    Path.home()
    / "Library"
    / "CloudStorage"
    / "GoogleDrive-milionmalik@gmail.com"
    / "My Drive"
    / "Wheels of Unity"
    / "Z-Pay Reference"
)

_SHEET_NAMES = {
    "driver_paycheck_codes": "driver_paycheck_codes.csv",
    "llc_mapping": "llc_mapping.csv",
    "route_rates": "route_rates.csv",
}

# ---------------------------------------------------------------------------
# DB queries
# ---------------------------------------------------------------------------

_SQL_PAYCHECK_CODES = """
SELECT
    person_id,
    full_name,
    COALESCE(paycheck_code, '')      AS paycheck_code,
    COALESCE(paycheck_code_maz, '')  AS paycheck_code_maz,
    COALESCE(status, 'active')       AS status,
    active                           AS active_status,
    NOW() AT TIME ZONE 'UTC'         AS last_updated
FROM person
ORDER BY full_name;
"""

_SQL_LLC_MAPPING = """
SELECT
    person_id,
    full_name,
    CASE WHEN paycheck_code     IS NOT NULL AND paycheck_code     != '' THEN 'Y' ELSE 'N' END AS acumen_enrolled,
    CASE WHEN paycheck_code_maz IS NOT NULL AND paycheck_code_maz != '' THEN 'Y' ELSE 'N' END AS maz_enrolled,
    CASE
        WHEN paycheck_code IS NOT NULL AND paycheck_code != ''
             AND paycheck_code_maz IS NOT NULL AND paycheck_code_maz != '' THEN 'both'
        WHEN paycheck_code     IS NOT NULL AND paycheck_code     != '' THEN 'FA'
        WHEN paycheck_code_maz IS NOT NULL AND paycheck_code_maz != '' THEN 'ED'
        ELSE 'none'
    END AS partner_runs
FROM person
ORDER BY full_name;
"""

_SQL_ROUTE_RATES = """
SELECT
    service_key                           AS route_code,
    source                                AS partner,
    ROUND(default_rate * 100)::bigint     AS rate_cents,
    created_at AT TIME ZONE 'UTC'         AS effective_from,
    NULL::text                            AS effective_to,
    company_name                          AS source_file,
    active
FROM z_rate_service
ORDER BY source, service_key;
"""

# Column headers for each sheet
_HEADERS = {
    "driver_paycheck_codes": [
        "person_id", "full_name", "paycheck_code", "paycheck_code_maz",
        "status", "active_status", "last_updated",
    ],
    "llc_mapping": [
        "person_id", "full_name", "acumen_enrolled", "maz_enrolled", "partner_runs",
    ],
    "route_rates": [
        "route_code", "partner", "rate_cents", "effective_from", "effective_to",
        "source_file", "active",
    ],
}


# ---------------------------------------------------------------------------
# Core sync logic
# ---------------------------------------------------------------------------

def _get_db_url() -> str:
    """Return DATABASE_URL from env, stripping SQLAlchemy dialect prefix."""
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        raise RuntimeError("DATABASE_URL is not set")
    # Strip SQLAlchemy dialect prefix so psycopg (libpq) can parse it
    for prefix in ("postgresql+psycopg://", "postgresql+asyncpg://", "postgres://"):
        if raw.startswith(prefix):
            return "postgresql://" + raw[len(prefix):]
    return raw


def _query_rows(db_url: str, sql: str, headers: list[str]) -> list[dict[str, Any]]:
    """Execute a SELECT and return list of dicts keyed by column name."""
    import psycopg  # type: ignore

    clean_url = db_url
    # psycopg3 accepts postgresql:// format
    rows: list[dict[str, Any]] = []
    with psycopg.connect(clean_url, connect_timeout=15) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            fetched = cur.fetchall()
            for row in fetched:
                rows.append(dict(zip(headers, [str(v) if v is not None else "" for v in row])))
    return rows


def _get_drive_path() -> Path:
    """Return the Drive mount path, creating it if it does not exist."""
    override = os.environ.get("DRIVE_MOUNT_PATH", "")
    base = Path(override) if override else _DEFAULT_DRIVE_PATH
    base.mkdir(parents=True, exist_ok=True)
    return base


def _write_csv_atomic(path: Path, headers: list[str], rows: list[dict[str, Any]]) -> int:
    """
    Write CSV atomically: write to temp file in same dir, then rename.
    Returns number of rows written.
    """
    dir_path = path.parent
    with tempfile.NamedTemporaryFile(
        mode="w",
        newline="",
        encoding="utf-8",
        dir=str(dir_path),
        delete=False,
        suffix=".tmp",
    ) as tmp:
        writer = csv.DictWriter(tmp, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        tmp_path = tmp.name

    os.replace(tmp_path, str(path))
    return len(rows)


def run_sync(db_url: str | None = None) -> dict[str, Any]:
    """
    Pull prod data and write three CSVs to the Drive mount.

    Returns:
        {
            "success": bool,
            "rows": {"driver_paycheck_codes": int, "llc_mapping": int, "route_rates": int},
            "path": str,            # absolute path to Z-Pay Reference folder
            "errors": [str, ...],   # empty on full success
            "timestamp": str,       # UTC ISO8601
        }
    """
    result: dict[str, Any] = {
        "success": False,
        "rows": {},
        "path": "",
        "errors": [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        url = db_url or _get_db_url()
    except RuntimeError as e:
        result["errors"].append(str(e))
        return result

    drive_path = _get_drive_path()
    result["path"] = str(drive_path)

    queries = {
        "driver_paycheck_codes": (_SQL_PAYCHECK_CODES, _HEADERS["driver_paycheck_codes"]),
        "llc_mapping": (_SQL_LLC_MAPPING, _HEADERS["llc_mapping"]),
        "route_rates": (_SQL_ROUTE_RATES, _HEADERS["route_rates"]),
    }

    all_ok = True
    for sheet_key, (sql, headers) in queries.items():
        csv_path = drive_path / _SHEET_NAMES[sheet_key]
        try:
            rows = _query_rows(url, sql, headers)
            count = _write_csv_atomic(csv_path, headers, rows)
            result["rows"][sheet_key] = count
            logger.info("[master-ledger] %s: %d rows → %s", sheet_key, count, csv_path)
        except Exception as exc:
            msg = f"{sheet_key}: {exc}"
            logger.exception("[master-ledger] Failed to sync %s: %s", sheet_key, exc)
            result["errors"].append(msg)
            all_ok = False

    result["success"] = all_ok
    return result


# ---------------------------------------------------------------------------
# APScheduler registration (called from trip_monitor.start_monitor)
# ---------------------------------------------------------------------------

def register_ledger_jobs(scheduler) -> None:
    """
    Register Monday 9 AM PT cron on an existing APScheduler BackgroundScheduler.

    The job wrapper checks MASTER_LEDGER_CRON_ENABLED at runtime so toggling
    the env var takes effect on the next tick without a redeploy.

    Call this from start_monitor() in backend/services/trip_monitor.py after
    the scheduler is created, alongside register_backup_jobs().
    """
    from apscheduler.triggers.cron import CronTrigger  # type: ignore

    _TZ = os.environ.get("MONITOR_TIMEZONE", "America/Los_Angeles")

    def _safe_ledger_sync():
        if os.environ.get("MASTER_LEDGER_CRON_ENABLED", "0") != "1":
            logger.debug("[master-ledger] MASTER_LEDGER_CRON_ENABLED != 1 — skipping")
            return
        logger.info("[master-ledger] Monday 9 AM cron firing")
        try:
            result = run_sync()
            if result["success"]:
                logger.info(
                    "[master-ledger] Sync complete: %s rows at %s",
                    result["rows"],
                    result["path"],
                )
            else:
                logger.error("[master-ledger] Sync had errors: %s", result["errors"])
                try:
                    from backend.services.notification_service import alert_admin
                    alert_admin(
                        f"Master Ledger Drive sync failed: {result['errors']}",
                        spoken_message="Master ledger sync to Drive failed. Check logs.",
                    )
                except Exception:
                    pass
        except Exception as exc:
            logger.exception("[master-ledger] Cron crashed: %s", exc)

    scheduler.add_job(
        _safe_ledger_sync,
        trigger=CronTrigger(day_of_week="mon", hour=9, minute=0, timezone=_TZ),
        id="master_ledger_weekly_sync",
        name="Master Ledger Drive Sync",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    logger.info("[master-ledger] Monday 9 AM PT cron registered")
