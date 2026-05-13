"""
Paystub Archive Backfill Script
================================
Regenerates paystub PDFs for every (person_id, batch_id) pair where:
  - The batch status is complete / stubs_sending / export_ready, AND
  - The driver had rides with z_rate > 0 in that batch

Marks regenerated_from_data=True since we are rebuilding from current
ride data (the originals were never persisted pre-Phase-1).

sent_at is best-guess from email_send_log:
  - If email_send_log has a matching (person_id, batch_id) row with
    status='sent', uses the most recent sent_at.
  - Otherwise sent_at is left NULL.

Idempotent: skips rows already in paystub_archive.

Usage
-----
  cd /path/to/zpay-v2-fresh
  DATABASE_URL="postgresql://..." python -m backend.scripts.backfill_paystub_archive

Options (env vars)
------------------
  BACKFILL_DRY_RUN=1   Print what would happen; write nothing.
  BACKFILL_BATCH_ID=42  Only backfill a single batch (useful for testing).

DO NOT run this script from CI or automatically.
Malik reviews output first, then triggers it manually.
"""

from __future__ import annotations

import os
import sys
import logging
from collections import defaultdict
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
_logger = logging.getLogger("zpay.backfill_paystubs")

ELIGIBLE_STATUSES = {"complete", "stubs_sending", "export_ready"}
DRY_RUN = os.getenv("BACKFILL_DRY_RUN", "0") == "1"
ONLY_BATCH_ID: Optional[int] = int(os.getenv("BACKFILL_BATCH_ID")) if os.getenv("BACKFILL_BATCH_ID") else None


def main() -> None:
    from backend.db import SessionLocal
    from backend.db.models import (
        PayrollBatch,
        Ride,
        Person,
        PaystubArchive,
        EmailSendLog,
    )
    from backend.services.paystub_archive import (
        save_pdf_to_archive,
        _build_paystub_pdf,
        _build_payweek,
    )

    db = SessionLocal()
    try:
        # ── 1. Find all eligible batches ──────────────────────────────────────
        batch_q = db.query(PayrollBatch).filter(
            PayrollBatch.status.in_(ELIGIBLE_STATUSES)
        )
        if ONLY_BATCH_ID:
            batch_q = batch_q.filter(PayrollBatch.payroll_batch_id == ONLY_BATCH_ID)
        batches = batch_q.order_by(PayrollBatch.period_start.asc()).all()

        _logger.info(
            "Found %d eligible batch(es) to process%s",
            len(batches),
            " (DRY RUN)" if DRY_RUN else "",
        )

        # ── 2. Pre-load existing archive rows to skip efficiently ─────────────
        existing_keys: set[tuple[int, int]] = set()
        for row in db.query(
            PaystubArchive.person_id, PaystubArchive.payroll_batch_id
        ).all():
            existing_keys.add((row.person_id, row.payroll_batch_id))

        _logger.info("Existing archive entries: %d", len(existing_keys))

        # ── 3. Pre-load email_send_log for best-guess sent_at ─────────────────
        # Shape: {(person_id, batch_id): latest_sent_at}
        send_log: dict[tuple[int, int], object] = {}
        for row in db.query(EmailSendLog).filter(
            EmailSendLog.status == "sent"
        ).all():
            key = (row.person_id, row.payroll_batch_id)
            if key not in send_log or row.sent_at > send_log[key]:
                send_log[key] = row.sent_at

        # ── 4. Iterate batches ─────────────────────────────────────────────────
        total_written = 0
        total_skipped = 0
        total_errors  = 0

        for batch in batches:
            bid = batch.payroll_batch_id
            _logger.info(
                "Batch %d (%s %s → %s)",
                bid,
                batch.source,
                batch.period_start or "?",
                batch.period_end or "?",
            )

            # Get distinct person_ids with payable rides in this batch
            person_ids = [
                row.person_id
                for row in db.query(Ride.person_id)
                .filter(
                    Ride.payroll_batch_id == bid,
                    Ride.z_rate > 0,
                )
                .distinct()
                .all()
            ]

            if not person_ids:
                _logger.info("  No payable rides — skip")
                continue

            company  = batch.company_name or "Z-Pay"
            payweek  = _build_payweek(batch)

            batch_written = 0
            batch_skipped = 0

            for pid in person_ids:
                key = (pid, bid)

                if key in existing_keys:
                    batch_skipped += 1
                    total_skipped += 1
                    continue

                person = db.get(Person, pid)
                if not person:
                    _logger.warning("  person_id=%d not found, skip", pid)
                    total_errors += 1
                    continue

                rides = (
                    db.query(Ride)
                    .filter(
                        Ride.payroll_batch_id == bid,
                        Ride.person_id == pid,
                        Ride.z_rate > 0,
                    )
                    .order_by(Ride.ride_start_ts.asc())
                    .all()
                )

                total_pay_val = sum(float(r.z_rate or 0) for r in rides)

                if DRY_RUN:
                    _logger.info(
                        "  [DRY RUN] Would write: person=%d (%s), rides=%d, total=$%.2f",
                        pid, person.full_name, len(rides), total_pay_val,
                    )
                    batch_written += 1
                    total_written += 1
                    continue

                try:
                    pdf_bytes = _build_paystub_pdf(person, rides, company, payweek)
                    best_sent_at = send_log.get(key)

                    archive_id = save_pdf_to_archive(
                        db,
                        person_id=pid,
                        batch_id=bid,
                        pdf_bytes=pdf_bytes,
                        recipient_email=person.email,
                        sent=bool(best_sent_at),
                        regenerated=True,
                        total_pay=total_pay_val,
                        ride_count=len(rides),
                    )

                    # Manually set sent_at from the send log if we have it
                    if best_sent_at:
                        row = db.get(PaystubArchive, archive_id)
                        if row and row.sent_at is None:
                            row.sent_at = best_sent_at
                            db.commit()

                    existing_keys.add(key)
                    batch_written += 1
                    total_written += 1

                except Exception as exc:
                    _logger.error(
                        "  ERROR person=%d batch=%d: %s", pid, bid, exc
                    )
                    total_errors += 1

            _logger.info(
                "  Batch %d done — written: %d, skipped: %d",
                bid, batch_written, batch_skipped,
            )

        # ── 5. Summary ─────────────────────────────────────────────────────────
        _logger.info(
            "Backfill complete%s — written: %d, skipped (already existed): %d, errors: %d",
            " (DRY RUN)" if DRY_RUN else "",
            total_written,
            total_skipped,
            total_errors,
        )

    finally:
        db.close()


if __name__ == "__main__":
    main()
