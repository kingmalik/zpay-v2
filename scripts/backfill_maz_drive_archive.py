#!/usr/bin/env python3
"""
Backfill script: upload all historical Maz payroll batches to Google Drive.

Uploads the payroll xlsx for each Maz batch to Master/Maz/Z-Pay Outputs/
and writes the Drive URL into payroll_batch.drive_archive_url.

Default mode is --dry-run (prints what WOULD be uploaded, makes no changes).
Pass --apply to actually upload.

Idempotent: already-uploaded batches (drive_archive_url IS NOT NULL) are skipped
unless --force is also passed.

Usage:
    # Preview (safe, no uploads):
    DATABASE_URL=... python3 scripts/backfill_maz_drive_archive.py

    # Apply (uploads all 16 historical batches):
    DATABASE_URL=... python3 scripts/backfill_maz_drive_archive.py --apply

    # Re-upload even already-archived batches:
    DATABASE_URL=... python3 scripts/backfill_maz_drive_archive.py --apply --force

Required env vars:
    DATABASE_URL
    GMAIL_CLIENT_ID
    GMAIL_CLIENT_SECRET
    GOOGLE_DRIVE_REFRESH_TOKEN_MAZ

Optional:
    MAZ_PAYROLL_DRIVE_FOLDER_ID   # skip folder lookup
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

# Allow running from repo root without installing the package
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))

# Load .env if present (local dev convenience)
env_path = repo_root / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill Maz Drive payroll archive")
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Actually upload files and update the DB. Without this flag, dry-run only.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Re-upload batches that already have drive_archive_url set.",
    )
    args = parser.parse_args()

    dry_run = not args.apply
    force = args.force

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        print("ERROR: DATABASE_URL is not set.", file=sys.stderr)
        sys.exit(1)

    # ── Database setup ────────────────────────────────────────────────────────
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    # Normalise URL dialect for psycopg v3
    db_url = db_url.replace("postgresql+psycopg2://", "postgresql+psycopg://")
    db_url = db_url.replace("postgres://", "postgresql+psycopg://")
    if db_url.startswith("postgresql://") and "+psycopg" not in db_url:
        db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)

    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)
    db = Session()

    from backend.db.models import PayrollBatch

    # ── Fetch all Maz batches ─────────────────────────────────────────────────
    batches = (
        db.query(PayrollBatch)
        .filter(PayrollBatch.source == "maz")
        .order_by(PayrollBatch.payroll_batch_id.asc())
        .all()
    )

    if not batches:
        print("No Maz batches found in the database.")
        db.close()
        return

    print()
    print(f"{'DRY RUN' if dry_run else 'APPLY'} — {len(batches)} Maz batch(es) found")
    print("-" * 72)
    print(f"{'ID':>6}  {'Week':>4}  {'Period Start':<14}  {'Status':<15}  {'Action'}")
    print("-" * 72)

    today = date.today()
    to_upload = []

    for batch in batches:
        bid = batch.payroll_batch_id
        period_start = batch.period_start

        # Derive ISO week number from period_start or batch_ref
        from backend.utils.week_label import canonical_week_num
        week_no = canonical_week_num(period_start, getattr(batch, "batch_ref", None))

        # Determine the approved date for filename
        finalized_at = batch.finalized_at
        if finalized_at:
            approved_date = finalized_at.date()
        else:
            # W15/W16 have null finalized_at — use today
            approved_date = today

        already_done = bool(batch.drive_archive_url)
        if already_done and not force:
            action = "SKIP (already archived)"
        else:
            action = "UPLOAD" if args.apply else "would upload"
            to_upload.append((batch, week_no, approved_date))

        week_label = f"W{week_no:02d}"
        period_str = period_start.isoformat() if period_start else "NULL"
        print(
            f"{bid:>6}  {week_label:>4}  {period_str:<14}  {batch.status:<15}  {action}"
        )

    print("-" * 72)
    print(f"Total to upload: {len(to_upload)} | Skipped: {len(batches) - len(to_upload)}")
    print()

    if dry_run:
        print("Dry run complete. Pass --apply to perform the uploads.")
        db.close()
        return

    # ── Apply: upload each batch ──────────────────────────────────────────────
    from backend.routes.workflow import _build_maz_xlsx_bytes
    from backend.services.drive_archive import upload_maz_payroll_xlsx

    succeeded = 0
    failed = 0

    for batch, week_no, approved_date in to_upload:
        bid = batch.payroll_batch_id
        week_label = f"W{week_no:02d}"
        print(f"  Uploading {week_label} (batch {bid}) ...", end=" ", flush=True)
        try:
            xlsx_bytes = _build_maz_xlsx_bytes(db, batch)
            drive_url = upload_maz_payroll_xlsx(
                week_no=week_no,
                period_start=batch.period_start,
                xlsx_bytes=xlsx_bytes,
                approved_date=approved_date,
            )
            batch.drive_archive_url = drive_url
            db.commit()
            print(f"OK -> {drive_url[:70]}...")
            succeeded += 1
        except Exception as exc:
            db.rollback()
            print(f"FAILED — {exc}")
            failed += 1

    print()
    print(f"Backfill complete: {succeeded} succeeded, {failed} failed.")
    if failed:
        print("Check the errors above. Failed batches were not modified in the DB.")
        sys.exit(1)

    db.close()


if __name__ == "__main__":
    main()
