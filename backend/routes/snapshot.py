"""
snapshot.py — DB backup/restore helpers for Z-Pay.

Endpoints:
  POST /snapshot/save   — dump current DB to /data/out/zpay_backup.sql
  GET  /snapshot/status — report file size, mtime, and live ride count
"""

import os
import subprocess
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

router = APIRouter(prefix="/snapshot", tags=["snapshot"])

SEED_FILE = Path("/data/out/zpay_backup.sql")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_db_url(url: str) -> dict:
    """
    Parse a DATABASE_URL (SQLAlchemy or plain postgres scheme) into
    components suitable for psql / pg_dump CLI args.

    Supports:
      postgresql+psycopg://user:pass@host:port/dbname
      postgresql://user:pass@host:port/dbname
      postgres://user:pass@host:port/dbname
    """
    # Normalise driver suffixes so urlparse can handle it
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


def _run_pg_dump() -> tuple[bool, str]:
    """
    Run pg_dump and write output to SEED_FILE.
    Returns (success: bool, message: str).
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        return False, "DATABASE_URL environment variable is not set"
    conn = _parse_db_url(url)

    SEED_FILE.parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["PGPASSWORD"] = conn["password"]

    cmd = [
        "pg_dump",
        "-h", conn["host"],
        "-p", conn["port"],
        "-U", conn["user"],
        conn["dbname"],
    ]

    try:
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            timeout=120,
        )
        if result.returncode != 0:
            err = result.stderr.decode(errors="replace").strip()
            return False, f"pg_dump failed (exit {result.returncode}): {err}"

        SEED_FILE.write_bytes(result.stdout)
        size_kb = len(result.stdout) / 1024
        return True, f"Snapshot saved ({size_kb:.1f} KB)"

    except FileNotFoundError:
        return False, "pg_dump not found — is postgresql-client installed in the image?"
    except subprocess.TimeoutExpired:
        return False, "pg_dump timed out after 120 s"
    except Exception as exc:
        return False, f"Unexpected error: {exc}"


def _snapshot_info() -> dict:
    """Return metadata about the snapshot file (may not exist yet)."""
    if not SEED_FILE.exists():
        return {"exists": False, "size_kb": None, "last_saved": None}

    stat = SEED_FILE.stat()
    return {
        "exists": True,
        "size_kb": round(stat.st_size / 1024, 1),
        "last_saved": datetime.fromtimestamp(stat.st_mtime).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
    }


def _live_ride_count() -> int:
    """Query the live ride count without importing SQLAlchemy models."""
    import psycopg  # type: ignore

    url = os.environ.get("DATABASE_URL")
    if not url:
        return -1
    conn_info = _parse_db_url(url)

    try:
        with psycopg.connect(
            host=conn_info["host"],
            port=int(conn_info["port"]),
            user=conn_info["user"],
            password=conn_info["password"],
            dbname=conn_info["dbname"],
            connect_timeout=5,
        ) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM ride;")
                row = cur.fetchone()
                return row[0] if row else 0
    except Exception:
        return -1


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/save")
async def save_snapshot(request: Request):
    """
    Dump the current DB to /data/out/zpay_backup.sql.

    Supports two response modes:
    - JSON  (Accept: application/json) → {"status": "ok", "message": "..."}
    - HTML form POST → redirect back to referrer with ?snapshot=ok or ?snapshot=error
    """
    success, message = _run_pg_dump()

    wants_json = "application/json" in request.headers.get("accept", "")

    if wants_json:
        status_code = 200 if success else 500
        return JSONResponse(
            content={"status": "ok" if success else "error", "message": message},
            status_code=status_code,
        )

    # HTML form POST — redirect back to referrer
    referrer = request.headers.get("referer", "/summary")
    flag = "snapshot=ok" if success else "snapshot=error"
    sep = "&" if "?" in referrer else "?"
    return RedirectResponse(url=f"{referrer}{sep}{flag}", status_code=303)


@router.get("/status")
async def snapshot_status():
    """Return snapshot file metadata and live ride count."""
    info = _snapshot_info()
    ride_count = _live_ride_count()

    return JSONResponse(
        content={
            "snapshot": info,
            "live_ride_count": ride_count,
        }
    )
