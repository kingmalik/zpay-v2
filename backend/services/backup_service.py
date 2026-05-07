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
# Startup check — log gpg binary availability at import time so Railway logs
# confirm the binary is present before the first backup cron fires.
# ---------------------------------------------------------------------------
_GPG_PATH = shutil.which("gpg")
if _GPG_PATH:
    logger.info("[backup] gpg binary found at %s — encryption available", _GPG_PATH)
else:
    logger.warning(
        "[backup] gpg binary NOT found in PATH. "
        "Backups will fail if BACKUP_PASSPHRASE is set. "
        "Add gnupg to the Dockerfile."
    )

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

    SECURITY GUARD: If BACKUP_PASSPHRASE or BACKUP_GPG_RECIPIENT is set and GPG
    fails for any reason (binary missing, key error, etc.), this function raises
    RuntimeError. We would rather produce NO backup than ship plaintext PII to
    an offsite store that has a .gpg extension but is not actually encrypted.
    """
    recipient = os.environ.get("BACKUP_GPG_RECIPIENT", "").strip()
    passphrase = os.environ.get("BACKUP_PASSPHRASE", "").strip()
    encryption_required = bool(recipient or passphrase)

    if not encryption_required:
        return data, False

    # Verify gpg binary is present before writing temp files
    if shutil.which("gpg") is None:
        msg = (
            "[backup] ENCRYPT-OR-FAIL: gpg binary not found in PATH. "
            "BACKUP_PASSPHRASE is set — refusing to ship plaintext backup. "
            "Add gnupg to Dockerfile and redeploy."
        )
        logger.error(msg)
        raise RuntimeError(msg)

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
            msg = f"[backup] ENCRYPT-OR-FAIL: GPG exited {result.returncode}: {err[:200]}"
            logger.error(msg)
            raise RuntimeError(msg)

        encrypted = Path(tmp_out_path).read_bytes()
        return encrypted, True
    except RuntimeError:
        raise
    except Exception as exc:
        msg = f"[backup] ENCRYPT-OR-FAIL: unexpected GPG error: {exc}"
        logger.error(msg)
        raise RuntimeError(msg) from exc
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
    # _encrypt_bytes raises RuntimeError if BACKUP_PASSPHRASE/RECIPIENT is set but gpg fails.
    # That exception propagates up to _safe_backup() which logs + alerts Discord.
    # We intentionally let it propagate rather than ship plaintext PII.
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
