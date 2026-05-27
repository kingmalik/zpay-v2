"""
R2 Payroll Backfill Script
===========================
One-time CLI to push historical payroll xlsx files and paystub PDFs to Cloudflare R2.

What it does
------------
1. Scans every approved Maz PayrollBatch with ``r2_key IS NULL``.
   Rebuilds the xlsx in-memory (same logic as the approval hook) and uploads to R2.

2. Scans every PaystubArchive row with ``r2_key IS NULL`` that has a readable file
   on disk. Reads the bytes from disk and uploads to R2.

Both passes are idempotent — rows with ``r2_key IS NOT NULL`` are skipped.

Usage
-----
  cd /path/to/zpay-v2-fresh
  DATABASE_URL="postgresql://..." python -m backend.scripts.backfill_r2_payroll

Options (CLI flags)
-------------------
  --dry-run       Print what would happen; write nothing to R2 or the DB.
  --company=maz   Limit to a single company slug (maz | acumen | all).
                  Default: maz (only Maz produces approval-time xlsx).

Safety rules
------------
- R2_ACCOUNT_ID / R2_ACCESS_KEY / R2_SECRET_KEY must be set — aborts early if not.
- Never touches payroll math columns (rates, gross_pay, net_pay, etc.).
- Uses the same ``r2_payroll_archive`` module as the live hook — identical key layout.
- Malik reviews the dry-run output BEFORE running for real.

DO NOT run from CI or automatically. This is a manual one-shot operation.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Optional

# Ensure the repo root is on sys.path when run as a module
_repo_root = Path(__file__).resolve().parents[2]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
_logger = logging.getLogger("zpay.backfill_r2_payroll")

_APPROVED_STATUSES = {"approved", "export_ready", "stubs_sending", "complete"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill R2 payroll archive")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print what would happen; write nothing.",
    )
    parser.add_argument(
        "--company",
        default="maz",
        choices=["maz", "acumen", "all"],
        help="Limit to a company (default: maz).",
    )
    return parser.parse_args()


def _check_r2_configured() -> None:
    """Abort early if R2 env vars are missing."""
    from backend.services.r2_storage import r2_configured
    if not r2_configured():
        _logger.error(
            "R2 env vars not set (R2_ACCOUNT_ID, R2_ACCESS_KEY, R2_SECRET_KEY). "
            "Cannot run backfill. Exiting."
        )
        sys.exit(1)


def _backfill_batches(db, *, dry_run: bool, company_filter: str) -> tuple[int, int, int]:
    """
    Upload xlsx for every approved Maz batch missing an r2_key.

    Returns (scanned, uploaded, skipped).
    """
    from backend.db.models import PayrollBatch
    from backend.routes.workflow import _build_maz_xlsx_bytes
    from backend.services import r2_payroll_archive

    q = db.query(PayrollBatch).filter(
        PayrollBatch.status.in_(_APPROVED_STATUSES),
        PayrollBatch.r2_key.is_(None),
    )

    if company_filter != "all":
        q = q.filter(PayrollBatch.source.ilike(f"%{company_filter}%"))
    else:
        # Only sources that produce xlsx on approval — currently only Maz
        q = q.filter(PayrollBatch.source.ilike("%maz%"))

    batches = q.order_by(PayrollBatch.period_start.asc()).all()

    scanned = len(batches)
    uploaded = 0
    skipped = 0

    _logger.info("Batch pass: %d batches to check", scanned)

    for batch in batches:
        try:
            # Rebuild xlsx — same call as the live approval hook
            # Suppress summary DB writes (auto_save=False inside _build_maz_xlsx_bytes)
            xlsx_bytes = _build_maz_xlsx_bytes(db, batch)
        except Exception:
            _logger.exception(
                "Batch %s: could not build xlsx — skipping",
                batch.payroll_batch_id,
            )
            skipped += 1
            continue

        week = r2_payroll_archive._week_num(batch)
        company = r2_payroll_archive._company_slug(batch)
        _logger.info(
            "Batch %s: W%02d/%s %d bytes %s",
            batch.payroll_batch_id, week, company, len(xlsx_bytes),
            "(DRY RUN — not uploading)" if dry_run else "→ uploading",
        )

        if dry_run:
            uploaded += 1
            continue

        key = r2_payroll_archive.upload_batch_xlsx(
            batch.payroll_batch_id, xlsx_bytes, db
        )
        if key:
            uploaded += 1
            _logger.info("Batch %s: uploaded -> %s", batch.payroll_batch_id, key)
        else:
            skipped += 1
            _logger.warning("Batch %s: upload returned None (check logs above)", batch.payroll_batch_id)

    return scanned, uploaded, skipped


def _backfill_paystubs(db, *, dry_run: bool, company_filter: str) -> tuple[int, int, int]:
    """
    Upload PDFs for every paystub_archive row missing an r2_key.

    Returns (scanned, uploaded, skipped).
    """
    from backend.db.models import PaystubArchive, PayrollBatch
    from backend.config import DATA_DIR
    from backend.services import r2_payroll_archive

    q = (
        db.query(PaystubArchive)
        .join(PayrollBatch, PaystubArchive.payroll_batch_id == PayrollBatch.payroll_batch_id)
        .filter(
            PaystubArchive.r2_key.is_(None),
            PayrollBatch.status.in_(_APPROVED_STATUSES),
        )
    )

    if company_filter != "all":
        q = q.filter(PayrollBatch.source.ilike(f"%{company_filter}%"))

    rows = q.order_by(PaystubArchive.generated_at.asc()).all()

    scanned = len(rows)
    uploaded = 0
    skipped = 0

    _logger.info("Paystub pass: %d stubs to check", scanned)

    for row in rows:
        abs_path = DATA_DIR / row.file_path
        if not abs_path.exists():
            _logger.warning(
                "Stub %s: file missing on disk (%s) — skipping",
                row.paystub_id, abs_path,
            )
            skipped += 1
            continue

        try:
            pdf_bytes = abs_path.read_bytes()
        except OSError:
            _logger.exception("Stub %s: could not read file — skipping", row.paystub_id)
            skipped += 1
            continue

        batch = db.get(PayrollBatch, row.payroll_batch_id)
        week = r2_payroll_archive._week_num(batch) if batch else 0
        company = r2_payroll_archive._company_slug(batch) if batch else "unknown"

        _logger.info(
            "Stub %s: person=%s W%02d/%s %d bytes %s",
            row.paystub_id, row.person_id, week, company, len(pdf_bytes),
            "(DRY RUN — not uploading)" if dry_run else "→ uploading",
        )

        if dry_run:
            uploaded += 1
            continue

        key = r2_payroll_archive.upload_paystub_pdf(row.paystub_id, pdf_bytes, db)
        if key:
            uploaded += 1
            _logger.info("Stub %s: uploaded -> %s", row.paystub_id, key)
        else:
            skipped += 1
            _logger.warning(
                "Stub %s: upload returned None (check logs above)", row.paystub_id
            )

    return scanned, uploaded, skipped


def main() -> None:
    args = _parse_args()
    _check_r2_configured()

    if args.dry_run:
        _logger.info("=== DRY RUN MODE — no writes ===")

    _logger.info(
        "Starting R2 payroll backfill | company=%s | dry_run=%s",
        args.company, args.dry_run,
    )

    from backend.db import SessionLocal

    db = SessionLocal()
    try:
        b_scanned, b_uploaded, b_skipped = _backfill_batches(
            db, dry_run=args.dry_run, company_filter=args.company
        )
        s_scanned, s_uploaded, s_skipped = _backfill_paystubs(
            db, dry_run=args.dry_run, company_filter=args.company
        )
    finally:
        db.close()

    tag = "DRY RUN SUMMARY" if args.dry_run else "SUMMARY"
    _logger.info(
        "=== %s ===\n"
        "  Batches : scanned=%d  would_upload=%d  skipped=%d\n"
        "  Paystubs: scanned=%d  would_upload=%d  skipped=%d",
        tag,
        b_scanned, b_uploaded, b_skipped,
        s_scanned, s_uploaded, s_skipped,
    )


if __name__ == "__main__":
    main()
