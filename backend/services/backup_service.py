"""
backup_service.py — Z-Pay automated backup pipeline.

Provides:
  - run_backup_cycle()   : pg_dump → gzip → encrypt → ship (Backblaze B2 or local)
  - run_csv_export()     : export critical tables as gzip CSV
  - start_backup_cron()  : register both jobs on an existing APScheduler instance
  - stop_backup_cron()   : shut down the backup scheduler (if owned here)

Environment variables (Railway):
  BACKUP_CRON_ENABLED    "1" to enable (default "0" — safety gate)
  BACKUP_PASSPHRASE      Symmetric GPG passphrase for encrypting dumps
  BACKUP_GPG_RECIPIENT   (Optional) Asymmetric GPG key fingerprint — preferred over passphrase
  BACKBLAZE_KEY_ID       B2 application key ID (optional; local fallback if missing)
  BACKBLAZE_APP_KEY      B2 application key secret
  BACKBLAZE_BUCKET       B2 bucket name (e.g. "zpay-backups")

If B2 credentials are not set: writes to /data/out/backups/ and keeps last 48 hourly files.
If BACKUP_PASSPHRASE is not set: dumps are gzipped but NOT encrypted — a WARNING is logged.

Cron schedule (both gated by BACKUP_CRON_ENABLED):
  Hourly  : :05 every hour (avoids collision with scorecard cron at Sun 20:00 :00)
  Daily   : 03:05 UTC — CSV exports

Discord alert on failure (uses ~/.claude/scripts/notify_discord.sh logic via subprocess).
"""
from __future__ import annotations

import gzip
import io
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger("zpay.backup")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOCAL_HOURLY_DIR = Path(os.environ.get("DATA_OUT_DIR", "/data/out")) / "backups" / "hourly"
_LOCAL_CSV_DIR = Path(os.environ.get("DATA_OUT_DIR", "/data/out")) / "backups" / "csv"
_LOCAL_HOURLY_KEEP = 48  # keep last 48 hourly snapshots on Railway disk

_CSV_TABLES = [
    "person",
    "payroll_batch",
    "ride",
    "driver_balance",
    "z_rate_service",
    "payroll_note",
]

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_db_url(url: str) -> dict:
    """Parse DATABASE_URL into psql/pg_dump CLI args."""
    clean = re.sub(r"^postgresql\+\w+://", "postgresql://", url)
    clean = re.sub(r"^postgres://", "postgresql://", clean)
    parsed = urlparse(clean)
    return {
        "host": parsed.hostname or "db",
        "port": str(parsed.port or 5432),
        "user": parsed.username or "app",
        "password": parsed.password or "",
        "dbname": parsed.path.lstrip("/") or "appdb",
    }


def _pg_dump_bytes() -> tuple[bool, bytes, str]:
    """
    Run pg_dump and return the SQL bytes.
    Returns (success, data_bytes, error_message).
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        return False, b"", "DATABASE_URL not set"
    conn = _parse_db_url(url)

    env = os.environ.copy()
    env["PGPASSWORD"] = conn["password"]

    cmd = [
        "pg_dump",
        "-h", conn["host"],
        "-p", conn["port"],
        "-U", conn["user"],
        conn["dbname"],
        "--no-owner",
        "--no-acl",
    ]

    try:
        result = subprocess.run(
            cmd, env=env, capture_output=True, timeout=180
        )
        if result.returncode != 0:
            err = result.stderr.decode(errors="replace").strip()
            return False, b"", f"pg_dump failed (exit {result.returncode}): {err[:300]}"
        return True, result.stdout, ""
    except FileNotFoundError:
        return False, b"", "pg_dump not found in PATH"
    except subprocess.TimeoutExpired:
        return False, b"", "pg_dump timed out (180s)"
    except Exception as exc:
        return False, b"", f"Unexpected pg_dump error: {exc}"


def _gzip_bytes(data: bytes) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        gz.write(data)
    return buf.getvalue()


def _encrypt_bytes(data: bytes) -> tuple[bytes, bool]:
    """
    Encrypt bytes with GPG.
    Prefers BACKUP_GPG_RECIPIENT (asymmetric), falls back to BACKUP_PASSPHRASE (symmetric).
    Returns (encrypted_bytes, was_encrypted).
    If neither env var is set, returns (data, False) — caller must log a WARNING.
    """
    recipient = os.environ.get("BACKUP_GPG_RECIPIENT", "").strip()
    passphrase = os.environ.get("BACKUP_PASSPHRASE", "").strip()

    if not recipient and not passphrase:
        return data, False

    with tempfile.NamedTemporaryFile(delete=False, suffix=".gz") as tmp_in:
        tmp_in.write(data)
        tmp_in_path = tmp_in.name

    tmp_out_path = tmp_in_path + ".gpg"
    try:
        if recipient:
            cmd = [
                "gpg", "--batch", "--yes",
                "--recipient", recipient,
                "--output", tmp_out_path,
                "--encrypt",
                tmp_in_path,
            ]
        else:
            cmd = [
                "gpg", "--batch", "--yes",
                "--passphrase", passphrase,
                "--symmetric",
                "--cipher-algo", "AES256",
                "--output", tmp_out_path,
                tmp_in_path,
            ]
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        if result.returncode != 0:
            err = result.stderr.decode(errors="replace").strip()
            logger.error("[backup] GPG encryption failed: %s", err[:200])
            return data, False

        encrypted = Path(tmp_out_path).read_bytes()
        return encrypted, True
    except Exception as exc:
        logger.error("[backup] GPG error: %s", exc)
        return data, False
    finally:
        for p in [tmp_in_path, tmp_out_path]:
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass


def _ship_to_b2(data: bytes, remote_path: str) -> tuple[bool, str]:
    """
    Upload bytes to Backblaze B2 via b2sdk.
    Returns (success, error_message).
    """
    key_id = os.environ.get("BACKBLAZE_KEY_ID", "")
    app_key = os.environ.get("BACKBLAZE_APP_KEY", "")
    bucket_name = os.environ.get("BACKBLAZE_BUCKET", "")

    if not (key_id and app_key and bucket_name):
        return False, "B2 env vars not set (BACKBLAZE_KEY_ID / BACKBLAZE_APP_KEY / BACKBLAZE_BUCKET)"

    try:
        from b2sdk.v2 import InMemoryAccountInfo, B2Api  # type: ignore
        info = InMemoryAccountInfo()
        api = B2Api(info)
        api.authorize_account("production", key_id, app_key)
        bucket = api.get_bucket_by_name(bucket_name)

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        try:
            bucket.upload_local_file(
                local_file=tmp_path,
                file_name=remote_path,
                content_type="application/octet-stream",
            )
            return True, ""
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    except ImportError:
        return False, "b2sdk not installed (add b2sdk to requirements.txt)"
    except Exception as exc:
        return False, f"B2 upload error: {exc}"


def _list_b2_sql_files() -> list[dict]:
    """
    List all SQL backup files under zpay-backups/sql/ in the configured B2 bucket.
    Returns list of dicts with keys: name (str), last_modified (datetime), size (int).
    Returns empty list if B2 credentials are missing or b2sdk is not installed.
    """
    key_id = os.environ.get("BACKBLAZE_KEY_ID", "")
    app_key = os.environ.get("BACKBLAZE_APP_KEY", "")
    bucket_name = os.environ.get("BACKBLAZE_BUCKET", "")
    if not (key_id and app_key and bucket_name):
        return []
    try:
        from b2sdk.v2 import InMemoryAccountInfo, B2Api  # type: ignore
        info = InMemoryAccountInfo()
        api = B2Api(info)
        api.authorize_account("production", key_id, app_key)
        bucket = api.get_bucket_by_name(bucket_name)
        files = []
        for file_version, _ in bucket.ls(folder_to_list="zpay-backups/sql/", latest_only=True):
            last_mod = datetime.fromtimestamp(
                file_version.upload_timestamp / 1000, tz=timezone.utc
            )
            files.append({
                "name": file_version.file_name,
                "id": file_version.id_,
                "last_modified": last_mod,
                "size": file_version.size,
            })
        return files
    except ImportError:
        logger.warning("[backup-retain] b2sdk not installed — cannot list B2 files")
        return []
    except Exception as exc:
        logger.warning("[backup-retain] B2 list error: %s", exc)
        return []


def _delete_b2_file(file_name: str, file_id: str) -> bool:
    """Delete a single file version from B2. Returns True on success."""
    key_id = os.environ.get("BACKBLAZE_KEY_ID", "")
    app_key = os.environ.get("BACKBLAZE_APP_KEY", "")
    if not (key_id and app_key):
        return False
    try:
        from b2sdk.v2 import InMemoryAccountInfo, B2Api  # type: ignore
        info = InMemoryAccountInfo()
        api = B2Api(info)
        api.authorize_account("production", key_id, app_key)
        api.delete_file_version(file_id, file_name)
        return True
    except Exception as exc:
        logger.warning("[backup-retain] B2 delete error for %s: %s", file_name, exc)
        return False


def _parse_backup_timestamp(file_entry: dict) -> Optional[datetime]:
    """
    Extract the UTC datetime from a backup filename.
    Filenames are: zpay-backups/sql/20260507T030500Z.sql.gz.gpg
    Falls back to last_modified if the name cannot be parsed.
    """
    name = file_entry["name"]
    basename = name.rsplit("/", 1)[-1]  # strip folder prefix
    # Try to parse YYYYMMDDTHHMMSSz from filename
    ts_match = re.match(r"^(\d{8}T\d{6}Z)", basename)
    if ts_match:
        try:
            return datetime.strptime(ts_match.group(1), "%Y%m%dT%H%M%SZ").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            pass
    return file_entry.get("last_modified")


def run_b2_retention() -> dict:
    """
    Enforce retention policy on zpay-backups/sql/ in B2:

      - Keep 30 most recent daily backups (one representative per calendar day,
        the latest upload for that day)
      - Keep 12 weekly backups (one per ISO week, the latest for that week)
      - Keep 12 monthly backups (one per calendar month, the latest for that month)
      - Delete everything not covered by any of the above windows

    "Keep" means keep the LATEST upload for each day/week/month bucket.
    Daily window = last 30 calendar days.
    Weekly window = last 12 ISO weeks.
    Monthly window = last 12 calendar months.

    Returns dict: {deleted: int, kept: int, skipped: int, errors: list[str]}
    """
    files = _list_b2_sql_files()
    if not files:
        logger.info("[backup-retain] No B2 files found or B2 not reachable — skipping retention")
        return {"deleted": 0, "kept": 0, "skipped": 0, "errors": []}

    now = datetime.now(timezone.utc)

    # Attach parsed timestamps
    for f in files:
        f["ts"] = _parse_backup_timestamp(f) or now

    # Sort newest first
    files.sort(key=lambda f: f["ts"], reverse=True)

    # Build keep sets: best (latest) file per bucket
    keep_ids: set[str] = set()

    # Daily: last 30 calendar days
    daily_seen: set[str] = set()
    for f in files:
        day_key = f["ts"].strftime("%Y-%m-%d")
        age_days = (now - f["ts"]).days
        if age_days <= 30 and day_key not in daily_seen:
            daily_seen.add(day_key)
            keep_ids.add(f["id"])

    # Weekly: last 12 ISO weeks
    weekly_seen: set[str] = set()
    for f in files:
        week_key = f["ts"].strftime("%G-W%V")  # ISO year + week number
        age_weeks = math.floor((now - f["ts"]).days / 7)
        if age_weeks <= 12 and week_key not in weekly_seen:
            weekly_seen.add(week_key)
            keep_ids.add(f["id"])

    # Monthly: last 12 calendar months
    monthly_seen: set[str] = set()
    for f in files:
        month_key = f["ts"].strftime("%Y-%m")
        # Approximate month age
        age_months = (now.year - f["ts"].year) * 12 + (now.month - f["ts"].month)
        if age_months <= 12 and month_key not in monthly_seen:
            monthly_seen.add(month_key)
            keep_ids.add(f["id"])

    deleted = 0
    kept = 0
    skipped = 0
    errors: list[str] = []

    for f in files:
        if f["id"] in keep_ids:
            kept += 1
            logger.debug("[backup-retain] KEEP  %s", f["name"])
        else:
            ok = _delete_b2_file(f["name"], f["id"])
            if ok:
                deleted += 1
                logger.info("[backup-retain] DELETED %s (ts=%s)", f["name"], f["ts"].isoformat())
            else:
                skipped += 1
                errors.append(f"delete failed: {f['name']}")
                logger.warning("[backup-retain] SKIP delete (error) %s", f["name"])

    logger.info(
        "[backup-retain] Retention complete — kept=%d deleted=%d skipped=%d",
        kept, deleted, skipped,
    )
    return {"deleted": deleted, "kept": kept, "skipped": skipped, "errors": errors}


def get_b2_freshness() -> dict:
    """
    Look up the most recent file in zpay-backups/sql/ and return its age.
    Returns dict with keys: found (bool), last_modified (ISO str or None),
    age_hours (float or None), file_name (str or None).
    """
    files = _list_b2_sql_files()
    if not files:
        return {"found": False, "last_modified": None, "age_hours": None, "file_name": None}
    # Sort by last_modified descending
    files.sort(key=lambda f: f["last_modified"], reverse=True)
    newest = files[0]
    age_hours = (datetime.now(timezone.utc) - newest["last_modified"]).total_seconds() / 3600
    return {
        "found": True,
        "last_modified": newest["last_modified"].isoformat(),
        "age_hours": round(age_hours, 2),
        "file_name": newest["name"],
    }


def _write_local_hourly(data: bytes, filename: str) -> None:
    """Write to local Railway disk, keep only last _LOCAL_HOURLY_KEEP files."""
    _LOCAL_HOURLY_DIR.mkdir(parents=True, exist_ok=True)
    dest = _LOCAL_HOURLY_DIR / filename
    dest.write_bytes(data)

    # Rotate: delete oldest beyond retention limit
    files = sorted(_LOCAL_HOURLY_DIR.iterdir(), key=lambda f: f.stat().st_mtime)
    while len(files) > _LOCAL_HOURLY_KEEP:
        try:
            files.pop(0).unlink()
        except Exception:
            break


def _write_local_csv(data: bytes, table: str, date_str: str) -> None:
    dest_dir = _LOCAL_CSV_DIR / date_str
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / f"{table}.csv.gz").write_bytes(data)


def _discord_alert(message: str) -> None:
    """Best-effort Discord notification on backup failure."""
    try:
        script = Path.home() / ".claude" / "scripts" / "notify_discord.sh"
        if script.exists():
            subprocess.run(
                [str(script), message],
                timeout=10,
                capture_output=True,
            )
        else:
            # Fallback: direct HTTP via requests if script not available (Railway environment)
            env_file = Path.home() / "Documents" / "Projects" / "jarvis-discord" / ".env"
            if env_file.exists():
                import shlex
                token_line = next(
                    (ln for ln in env_file.read_text().splitlines()
                     if ln.startswith("DISCORD_BOT_TOKEN=")),
                    ""
                )
                token = token_line.split("=", 1)[1].strip() if token_line else ""
                if token:
                    import urllib.request, json as _json
                    payload = _json.dumps({"content": message[:1990]}).encode()
                    req = urllib.request.Request(
                        "https://discord.com/api/v10/channels/951604531567935511/messages",
                        data=payload,
                        headers={
                            "Authorization": f"Bot {token}",
                            "Content-Type": "application/json",
                        },
                    )
                    urllib.request.urlopen(req, timeout=10)
    except Exception as exc:
        logger.warning("[backup] Discord alert failed: %s", exc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_backup_cycle() -> dict:
    """
    Execute one full hourly backup cycle:
      1. pg_dump
      2. gzip
      3. encrypt (if BACKUP_PASSPHRASE or BACKUP_GPG_RECIPIENT is set)
      4. ship to B2 (if credentials set) or write to local disk

    Returns a dict with keys: success, message, size_bytes, destination.
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ext = ".sql.gz.gpg" if (
        os.environ.get("BACKUP_PASSPHRASE") or os.environ.get("BACKUP_GPG_RECIPIENT")
    ) else ".sql.gz"
    filename = f"{ts}{ext}"
    b2_path = f"zpay-backups/sql/{filename}"

    logger.info("[backup] Starting hourly backup cycle — %s", ts)

    # Step 1: dump
    ok, sql_bytes, err = _pg_dump_bytes()
    if not ok:
        msg = f"[backup] FAILED — pg_dump error: {err}"
        logger.error(msg)
        _discord_alert(f"ZPay hourly backup FAILED (pg_dump): {err[:200]}")
        return {"success": False, "message": err, "size_bytes": 0, "destination": None}

    # Step 2: gzip
    gz_bytes = _gzip_bytes(sql_bytes)
    logger.info("[backup] pg_dump: %d bytes → gzipped: %d bytes", len(sql_bytes), len(gz_bytes))

    # Step 3: encrypt
    final_bytes, encrypted = _encrypt_bytes(gz_bytes)
    if not encrypted:
        logger.warning(
            "[backup] BACKUP_PASSPHRASE and BACKUP_GPG_RECIPIENT are both unset — "
            "backup is NOT encrypted. Set BACKUP_PASSPHRASE in Railway to enable encryption."
        )

    # Step 4: ship or write local
    b2_ok, b2_err = _ship_to_b2(final_bytes, b2_path)
    if b2_ok:
        dest = f"b2://{os.environ.get('BACKBLAZE_BUCKET', 'bucket')}/{b2_path}"
        logger.info("[backup] Shipped to B2: %s (%d bytes)", b2_path, len(final_bytes))
        # Step 5: retention rotation — prune B2 after each successful upload
        try:
            retain_result = run_b2_retention()
            logger.info(
                "[backup] Retention — kept=%d deleted=%d",
                retain_result["kept"], retain_result["deleted"],
            )
        except Exception as exc:
            # Non-fatal: never let retention kill a successful backup record
            logger.warning("[backup] Retention rotation error (non-fatal): %s", exc)
    else:
        if "not set" not in b2_err:
            # B2 was configured but failed — alert
            logger.error("[backup] B2 upload failed: %s", b2_err)
            _discord_alert(f"ZPay hourly backup B2 upload FAILED: {b2_err[:200]}")
        else:
            logger.warning("[backup] B2 not configured — writing to local disk. Configure BACKBLAZE_KEY_ID/APP_KEY/BUCKET.")

        _write_local_hourly(final_bytes, filename)
        dest = str(_LOCAL_HOURLY_DIR / filename)
        logger.info("[backup] Written local: %s (%d bytes)", dest, len(final_bytes))

    return {
        "success": True,
        "message": f"Backup complete — {len(final_bytes)} bytes → {dest}",
        "size_bytes": len(final_bytes),
        "destination": dest,
    }


def run_csv_export() -> dict:
    """
    Export critical tables as gzip CSV.
    Ships to B2 at zpay-backups/csv/<UTC date>/<table>.csv.gz
    or writes to /data/out/backups/csv/<UTC date>/<table>.csv.gz

    Returns a dict with keys: success, tables_exported, errors.
    """
    import pandas as pd  # type: ignore
    from sqlalchemy import create_engine

    url = os.environ.get("DATABASE_URL", "")
    if not url:
        logger.error("[backup-csv] DATABASE_URL not set")
        return {"success": False, "tables_exported": [], "errors": ["DATABASE_URL not set"]}

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    b2_configured = all([
        os.environ.get("BACKBLAZE_KEY_ID"),
        os.environ.get("BACKBLAZE_APP_KEY"),
        os.environ.get("BACKBLAZE_BUCKET"),
    ])

    exported: list[str] = []
    errors: list[str] = []

    try:
        engine = create_engine(url)
    except Exception as exc:
        return {"success": False, "tables_exported": [], "errors": [f"DB connect failed: {exc}"]}

    for table in _CSV_TABLES:
        try:
            df = pd.read_sql_table(table, engine)
            buf = io.BytesIO()
            with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
                df.to_csv(gz, index=False)
            data = buf.getvalue()

            remote_path = f"zpay-backups/csv/{date_str}/{table}.csv.gz"
            if b2_configured:
                ok, err = _ship_to_b2(data, remote_path)
                if ok:
                    exported.append(f"b2://{table}")
                    logger.info("[backup-csv] %s → B2 (%d bytes)", table, len(data))
                else:
                    errors.append(f"{table}: B2 error: {err}")
                    logger.error("[backup-csv] %s B2 failed: %s", table, err)
            else:
                _write_local_csv(data, table, date_str)
                exported.append(f"local://{table}")
                logger.info("[backup-csv] %s → local (%d bytes)", table, len(data))

        except Exception as exc:
            errors.append(f"{table}: {exc}")
            logger.error("[backup-csv] Failed to export %s: %s", table, exc)

    engine.dispose()

    if errors:
        _discord_alert(f"ZPay CSV export partial failure ({len(errors)} tables): {'; '.join(errors[:3])}")

    logger.info("[backup-csv] Done — exported: %d, errors: %d", len(exported), len(errors))
    return {
        "success": len(errors) == 0,
        "tables_exported": exported,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Scheduler registration
# ---------------------------------------------------------------------------

_BACKUP_SCHEDULER = None  # owned by this module only if start_backup_cron() is called standalone


def register_backup_jobs(scheduler) -> None:
    """
    Register hourly backup + daily CSV export jobs on an existing APScheduler instance.
    Call this from start_monitor() in trip_monitor.py after the scheduler is created.

    Jobs are registered regardless of BACKUP_CRON_ENABLED — the job wrappers
    check the flag at runtime so Railway env var changes take effect on next tick
    without a redeploy.
    """
    from apscheduler.triggers.cron import CronTrigger  # type: ignore

    _common = dict(replace_existing=True, max_instances=1, coalesce=True, misfire_grace_time=300)

    def _safe_backup():
        if os.environ.get("BACKUP_CRON_ENABLED", "0") != "1":
            logger.debug("[backup] BACKUP_CRON_ENABLED != 1 — skipping")
            return
        try:
            result = run_backup_cycle()
            if not result["success"]:
                logger.error("[backup] Cycle failed: %s", result["message"])
        except Exception as exc:
            logger.exception("[backup] Uncaught error in backup cycle: %s", exc)
            _discord_alert(f"ZPay backup cycle crashed: {str(exc)[:200]}")

    def _safe_csv_export():
        if os.environ.get("BACKUP_CRON_ENABLED", "0") != "1":
            logger.debug("[backup-csv] BACKUP_CRON_ENABLED != 1 — skipping")
            return
        try:
            result = run_csv_export()
            if not result["success"]:
                logger.error("[backup-csv] Export had errors: %s", result["errors"])
        except Exception as exc:
            logger.exception("[backup-csv] Uncaught error in CSV export: %s", exc)
            _discord_alert(f"ZPay CSV export crashed: {str(exc)[:200]}")

    scheduler.add_job(
        _safe_backup,
        trigger=CronTrigger(minute=5, timezone="UTC"),  # :05 every hour
        id="zpay_backup_hourly",
        name="ZPay Hourly DB Backup",
        **_common,
    )
    logger.info("[backup] Hourly backup job registered (every hour at :05 UTC)")

    scheduler.add_job(
        _safe_csv_export,
        trigger=CronTrigger(hour=3, minute=5, timezone="UTC"),  # 03:05 UTC daily
        id="zpay_backup_csv_daily",
        name="ZPay Daily CSV Export",
        **_common,
    )
    logger.info("[backup-csv] Daily CSV export job registered (03:05 UTC)")


def start_backup_cron() -> None:
    """
    Standalone entry point: create own scheduler and start backup jobs.
    Use this if you want backup cron independent of the trip monitor.
    Normally you'd call register_backup_jobs(existing_scheduler) instead.
    """
    global _BACKUP_SCHEDULER
    if _BACKUP_SCHEDULER is not None:
        logger.warning("[backup] Scheduler already started")
        return

    from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore
    _BACKUP_SCHEDULER = BackgroundScheduler(timezone="UTC")
    register_backup_jobs(_BACKUP_SCHEDULER)
    _BACKUP_SCHEDULER.start()
    logger.info("[backup] Standalone backup scheduler started")


def stop_backup_cron() -> None:
    global _BACKUP_SCHEDULER
    if _BACKUP_SCHEDULER:
        _BACKUP_SCHEDULER.shutdown(wait=False)
        _BACKUP_SCHEDULER = None
        logger.info("[backup] Standalone backup scheduler stopped")
