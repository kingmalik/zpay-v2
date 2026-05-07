#!/usr/bin/env python3
"""
scripts/sync_master_ledger.py
==============================
Manual trigger for the Master Ledger Drive shadow sync.

Usage:
    python3 scripts/sync_master_ledger.py [--db-url <url>] [--drive-path <path>]

Options:
    --db-url     Override DATABASE_URL (default: read from .env or env)
    --drive-path Override DRIVE_MOUNT_PATH (default: ~/Library/CloudStorage/...)
    --dry-run    Pull from DB and report row counts, but skip writing to Drive

Writes three CSVs to Wheels of Unity / Z-Pay Reference/:
  driver_paycheck_codes.csv  — pid / paycheck codes / status
  llc_mapping.csv            — LLC enrollment per driver
  route_rates.csv            — z_rate_service rows (all partners)

Safe to run anytime. Read-only on DB. Idempotent (overwrites previous CSVs).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup — allow running from repo root or scripts/ directory
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Load .env from repo root (local dev convenience — Railway ignores this)
try:
    from dotenv import load_dotenv
    _env_file = _REPO_ROOT / ".env"
    if _env_file.exists():
        load_dotenv(str(_env_file))
except ImportError:
    pass  # python-dotenv optional for Railway-run context


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync prod DB → Drive master ledger CSVs")
    parser.add_argument("--db-url", help="Override DATABASE_URL")
    parser.add_argument("--drive-path", help="Override DRIVE_MOUNT_PATH")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Pull from DB and show row counts, do NOT write to Drive",
    )
    args = parser.parse_args()

    # Apply overrides before importing service (service reads env at call time)
    if args.db_url:
        os.environ["DATABASE_URL"] = args.db_url
    if args.drive_path:
        os.environ["DRIVE_MOUNT_PATH"] = args.drive_path

    from backend.services.master_ledger_sync import run_sync, _query_rows, _get_db_url, _HEADERS

    if args.dry_run:
        print("DRY RUN — pulling from DB, not writing to Drive")
        try:
            url = args.db_url or _get_db_url()
        except RuntimeError as e:
            print(f"ERROR: {e}")
            return 1

        queries = {
            "driver_paycheck_codes": (
                "SELECT COUNT(*) FROM person;",
                ["count"],
            ),
            "llc_mapping": (
                "SELECT COUNT(*) FROM person;",
                ["count"],
            ),
            "route_rates": (
                "SELECT COUNT(*) FROM z_rate_service;",
                ["count"],
            ),
        }
        for name, (sql, headers) in queries.items():
            rows = _query_rows(url, sql, headers)
            print(f"  {name}: {rows[0]['count']} rows would be written")
        return 0

    print("Syncing prod DB → Google Drive master ledger...")
    result = run_sync()

    if result["success"]:
        print(f"\nSync complete at {result['timestamp']}")
        print(f"Drive path: {result['path']}")
        print()
        for sheet, count in result["rows"].items():
            print(f"  {sheet}: {count} rows")
        print()
        print("CSVs are now in Google Drive. They sync automatically within ~30s.")
        print("Open at: Wheels of Unity / Z-Pay Reference /")
        return 0
    else:
        print(f"\nSync FAILED at {result['timestamp']}")
        if result["rows"]:
            print("Partial success:")
            for sheet, count in result["rows"].items():
                print(f"  {sheet}: {count} rows written")
        print("\nErrors:")
        for err in result["errors"]:
            print(f"  - {err}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
