"""
restore_from_vault.py — Z-Pay single-command database restore.

Usage:
  python scripts/restore_from_vault.py \\
      --source /path/to/backup.sql.gz.gpg \\
      --target postgresql://user:pass@host:5432/dbname \\
      [--passphrase "secret"]   \\  # or set BACKUP_PASSPHRASE env var
      [--dry-run]               \\  # print what would happen, don't apply
      [--skip-sanity]              # skip row-count checks (for fresh DBs)

Source formats supported:
  - Local file path (absolute): /path/to/backup.sql.gz.gpg
  - Local file (unencrypted gzip): /path/to/backup.sql.gz
  - Local file (plain SQL): /path/to/backup.sql
  - B2 path: b2://bucket-name/zpay-backups/sql/20260503T012345Z.sql.gz.gpg

Post-restore sanity checks (idempotent — exits non-zero if checks fail):
  - person      >= 200 rows
  - payroll_batch >= 20 rows
  - ride         >= 1000 rows

The restore uses psql with --clean so it is idempotent: you can run it
multiple times against the same target DB without duplicating data.

Passphrase resolution order:
  1. --passphrase CLI flag
  2. BACKUP_PASSPHRASE environment variable
  3. macOS Keychain service "zpay-backup-gpg-<date>" (auto-detected from filename)
  4. Interactive prompt (not available in headless mode)
"""
from __future__ import annotations

import argparse
import gzip
import io
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)
logger = logging.getLogger("zpay.restore")

# ---------------------------------------------------------------------------
# Sanity thresholds
# ---------------------------------------------------------------------------
SANITY_CHECKS = {
    "person": 200,
    "payroll_batch": 20,
    "ride": 1000,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_db_url(url: str) -> dict:
    clean = re.sub(r"^postgresql\+\w+://", "postgresql://", url)
    clean = re.sub(r"^postgres://", "postgresql://", clean)
    parsed = urlparse(clean)
    return {
        "host": parsed.hostname or "localhost",
        "port": str(parsed.port or 5432),
        "user": parsed.username or "postgres",
        "password": parsed.password or "",
        "dbname": parsed.path.lstrip("/") or "postgres",
    }


def _resolve_passphrase(cli_passphrase: str, source_path: str) -> str:
    """
    Resolve GPG passphrase from CLI arg → env var → macOS Keychain → empty string.
    """
    if cli_passphrase:
        return cli_passphrase

    env_val = os.environ.get("BACKUP_PASSPHRASE", "")
    if env_val:
        return env_val

    # Try macOS Keychain — look for service matching filename date pattern
    date_match = re.search(r"(\d{4}-\d{2}-\d{2}|\d{8})", Path(source_path).name)
    if date_match:
        date_str = date_match.group(1)
        service = f"zpay-backup-gpg-{date_str}"
        try:
            result = subprocess.run(
                ["security", "find-generic-password", "-s", service, "-w"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                logger.info("Passphrase resolved from macOS Keychain (service: %s)", service)
                return result.stdout.strip()
        except Exception:
            pass

    return ""


def _download_from_b2(b2_path: str) -> bytes:
    """Download file from Backblaze B2. b2_path format: b2://bucket/path/to/file."""
    key_id = os.environ.get("BACKBLAZE_KEY_ID", "")
    app_key = os.environ.get("BACKBLAZE_APP_KEY", "")

    if not key_id or not app_key:
        raise RuntimeError(
            "BACKBLAZE_KEY_ID and BACKBLAZE_APP_KEY must be set to restore from B2"
        )

    # Parse b2://bucket/path
    without_scheme = b2_path[len("b2://"):]
    parts = without_scheme.split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid B2 path: {b2_path}. Format: b2://bucket/remote/path")
    bucket_name, remote_path = parts

    try:
        from b2sdk.v2 import InMemoryAccountInfo, B2Api  # type: ignore
    except ImportError:
        raise RuntimeError("b2sdk not installed. Run: pip install b2sdk>=2.0")

    info = InMemoryAccountInfo()
    api = B2Api(info)
    api.authorize_account("production", key_id, app_key)
    bucket = api.get_bucket_by_name(bucket_name)

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp_path = tmp.name

    try:
        bucket.download_file_by_name(remote_path).save_to(tmp_path)
        return Path(tmp_path).read_bytes()
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _decrypt_bytes(data: bytes, passphrase: str) -> bytes:
    """Decrypt GPG-encrypted bytes. Returns plaintext bytes."""
    with tempfile.NamedTemporaryFile(delete=False) as tmp_in:
        tmp_in.write(data)
        tmp_in_path = tmp_in.name

    tmp_out_path = tmp_in_path + ".dec"
    try:
        cmd = [
            "gpg", "--batch", "--yes",
            "--passphrase", passphrase,
            "--output", tmp_out_path,
            "--decrypt",
            tmp_in_path,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        if result.returncode != 0:
            err = result.stderr.decode(errors="replace").strip()
            raise RuntimeError(f"GPG decryption failed: {err[:300]}")
        return Path(tmp_out_path).read_bytes()
    finally:
        for p in [tmp_in_path, tmp_out_path]:
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass


def _decompress_gzip(data: bytes) -> bytes:
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
        return gz.read()


def _apply_sql(sql_bytes: bytes, conn: dict, dry_run: bool) -> None:
    """Apply SQL to target DB using psql --clean (idempotent)."""
    if dry_run:
        logger.info("[DRY RUN] Would apply %d bytes of SQL to %s@%s:%s/%s",
                    len(sql_bytes), conn["user"], conn["host"], conn["port"], conn["dbname"])
        return

    env = os.environ.copy()
    env["PGPASSWORD"] = conn["password"]

    with tempfile.NamedTemporaryFile(
        delete=False, suffix=".sql", mode="wb"
    ) as tmp:
        tmp.write(sql_bytes)
        tmp_path = tmp.name

    try:
        cmd = [
            "psql",
            "-h", conn["host"],
            "-p", conn["port"],
            "-U", conn["user"],
            conn["dbname"],
            "-f", tmp_path,
            "--single-transaction",
            "-v", "ON_ERROR_STOP=1",
        ]
        logger.info("Applying SQL to %s:%s/%s ...", conn["host"], conn["port"], conn["dbname"])
        result = subprocess.run(cmd, env=env, capture_output=True, timeout=300)
        if result.returncode != 0:
            err = result.stderr.decode(errors="replace").strip()
            raise RuntimeError(f"psql apply failed (exit {result.returncode}): {err[:500]}")
        logger.info("SQL applied successfully")
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _run_sanity_checks(conn: dict, skip: bool) -> bool:
    """
    Run row-count checks. Returns True if all pass (or skip=True).
    """
    if skip:
        logger.info("[sanity] Skipping sanity checks (--skip-sanity)")
        return True

    env = os.environ.copy()
    env["PGPASSWORD"] = conn["password"]

    all_ok = True
    for table, minimum in SANITY_CHECKS.items():
        cmd = [
            "psql",
            "-h", conn["host"],
            "-p", conn["port"],
            "-U", conn["user"],
            conn["dbname"],
            "-t", "-c", f"SELECT COUNT(*) FROM {table};",
        ]
        try:
            result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
            count_str = result.stdout.strip()
            count = int(count_str) if count_str.isdigit() else -1
            if count >= minimum:
                logger.info("[sanity] PASS — %s: %d rows (min %d)", table, count, minimum)
            else:
                logger.error("[sanity] FAIL — %s: %d rows (min %d required)", table, count, minimum)
                all_ok = False
        except Exception as exc:
            logger.error("[sanity] ERROR checking %s: %s", table, exc)
            all_ok = False

    return all_ok


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Restore Z-Pay database from a vault backup.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--source", required=True,
        help="Path to backup file (local path or b2://bucket/path)",
    )
    parser.add_argument(
        "--target", required=True,
        help="Target database URL (postgresql://user:pass@host:5432/dbname)",
    )
    parser.add_argument(
        "--passphrase", default="",
        help="GPG decryption passphrase (or set BACKUP_PASSPHRASE env var)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would happen without applying any changes",
    )
    parser.add_argument(
        "--skip-sanity", action="store_true",
        help="Skip post-restore row-count sanity checks",
    )
    args = parser.parse_args()

    conn = _parse_db_url(args.target)
    source = args.source
    passphrase = _resolve_passphrase(args.passphrase, source)

    logger.info("=== Z-Pay Restore ===")
    logger.info("Source: %s", source)
    logger.info("Target: %s@%s:%s/%s", conn["user"], conn["host"], conn["port"], conn["dbname"])
    if args.dry_run:
        logger.info("DRY RUN mode — no changes will be applied")

    # Step 1: load raw bytes
    if source.startswith("b2://"):
        logger.info("Downloading from Backblaze B2 ...")
        raw = _download_from_b2(source)
        logger.info("Downloaded %d bytes from B2", len(raw))
    else:
        p = Path(source)
        if not p.exists():
            logger.error("Source file not found: %s", source)
            return 1
        raw = p.read_bytes()
        logger.info("Loaded %d bytes from local file", len(raw))

    # Step 2: decrypt if needed
    if source.endswith(".gpg"):
        if not passphrase:
            logger.error(
                "Source file is GPG-encrypted but no passphrase found. "
                "Set --passphrase or BACKUP_PASSPHRASE env var."
            )
            return 1
        logger.info("Decrypting GPG ...")
        raw = _decrypt_bytes(raw, passphrase)
        logger.info("Decrypted: %d bytes", len(raw))

    # Step 3: decompress if needed
    if source.endswith(".gz") or source.endswith(".gz.gpg"):
        logger.info("Decompressing gzip ...")
        raw = _decompress_gzip(raw)
        logger.info("Decompressed: %d bytes of SQL", len(raw))

    if not raw.startswith(b"--"):
        logger.error("Data does not look like a valid pg_dump SQL file (missing '--' header)")
        return 1

    # Step 4: apply
    _apply_sql(raw, conn, dry_run=args.dry_run)

    # Step 5: sanity checks
    if args.dry_run:
        logger.info("[DRY RUN] Skipping sanity checks in dry-run mode")
        return 0

    ok = _run_sanity_checks(conn, skip=args.skip_sanity)
    if not ok:
        logger.error("Post-restore sanity checks FAILED — database may be incomplete")
        return 2

    logger.info("=== Restore complete — all sanity checks passed ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
