"""
Partner-payment backfill — July 2026 remittance audit (T2)
==========================================================
One-time CLI writing PartnerPayment rows for the 26 First Student EFT
deposits matched in the 2026-07-23 remittance audit (Jan 22 → Jul 23,
$575,716.27 across 26 deposits; the 27th — 07/23 $4,871.00 — has no
uploaded batch yet and is NOT in the mapping).

Input: a mapping JSON produced from remit_rows.json + expected revenue —
list of objects {deposit_date, amount, payroll_batch_id, week_end, invoice}.

Safety rules
------------
- DRY-RUN by default; nothing is written without --execute.
- A batch that already has ANY partner_payment row is skipped (a human,
  e.g. mom, may have entered recent deposits — never double-count).
- Every batch id is verified to exist, be source='acumen', and carry the
  expected week_end before any write. Mismatch = hard abort.
- Every written row is tagged memo "backfill-2026-07 | ..." —
  rollback = DELETE FROM partner_payment WHERE memo LIKE 'backfill-2026-07%'.
- Set EFT_AUTOINGEST=0 (Railway) for the duration of an --execute run: the
  live remit-ingest watcher polls every 10 minutes and could insert an auto
  row for the same deposit between this script's existence check and its
  final commit.

Usage
-----
  cd /path/to/zpay-v2-fresh
  DATABASE_URL="postgresql://..." python -m backend.scripts.backfill_partner_payments_2026_07 \
      --mapping /path/to/backfill_mapping.json [--execute]

DO NOT run from CI or automatically. Manual one-shot.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

MEMO_TAG = "backfill-2026-07"
CREATED_BY = "fable-backfill"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", required=True, help="path to backfill mapping JSON")
    parser.add_argument("--execute", action="store_true", help="write rows (default: dry-run)")
    args = parser.parse_args()

    rows = json.loads(Path(args.mapping).read_text())
    if not isinstance(rows, list) or not rows:
        print("ABORT: mapping file is empty or not a list")
        return 1

    batch_ids = [int(r["payroll_batch_id"]) for r in rows]
    if len(batch_ids) != len(set(batch_ids)):
        dupes = sorted({b for b in batch_ids if batch_ids.count(b) > 1})
        print(f"ABORT: mapping contains duplicate batch ids {dupes} — resolve before writing")
        return 1

    from backend.db.db import SessionLocal
    from backend.db.models import PartnerPayment, PayrollBatch

    planned: list[dict] = []
    skipped: list[str] = []

    with SessionLocal() as db:
        for row in rows:
            batch_id = int(row["payroll_batch_id"])
            week_end = date.fromisoformat(row["week_end"])
            amount = round(float(row["amount"]), 2)
            deposit_date = date.fromisoformat(row["deposit_date"])

            batch = (
                db.query(PayrollBatch)
                .filter(PayrollBatch.payroll_batch_id == batch_id)
                .first()
            )
            if batch is None:
                print(f"ABORT: batch {batch_id} not found in DB")
                return 1
            if batch.source != "acumen":
                print(f"ABORT: batch {batch_id} source={batch.source!r}, expected 'acumen'")
                return 1
            if batch.week_end != week_end:
                print(
                    f"ABORT: batch {batch_id} week_end={batch.week_end} "
                    f"but mapping says {week_end}"
                )
                return 1

            existing = (
                db.query(PartnerPayment)
                .filter(PartnerPayment.payroll_batch_id == batch_id)
                .count()
            )
            if existing:
                skipped.append(
                    f"batch {batch_id} (wk-end {week_end}) — {existing} existing row(s), untouched"
                )
                continue

            planned.append(
                {
                    "batch_id": batch_id,
                    "deposit_date": deposit_date,
                    "amount": amount,
                    "memo": (
                        f"{MEMO_TAG} | eft {row['invoice']} | wk-end {week_end.isoformat()}"
                    ),
                }
            )

        mode = "EXECUTE" if args.execute else "DRY-RUN"
        total = sum(p["amount"] for p in planned)
        print(f"[{mode}] {len(planned)} rows to write, ${total:,.2f} total; {len(skipped)} skipped")
        for s in skipped:
            print(f"  SKIP {s}")
        for p in planned:
            print(
                f"  WRITE batch {p['batch_id']:>4}  {p['deposit_date']}  "
                f"${p['amount']:>10,.2f}  {p['memo']}"
            )

        if not args.execute:
            print("Dry-run complete — re-run with --execute to write.")
            return 0

        for p in planned:
            db.add(
                PartnerPayment(
                    source="acumen",
                    amount=p["amount"],
                    deposit_date=p["deposit_date"],
                    payroll_batch_id=p["batch_id"],
                    memo=p["memo"],
                    created_by=CREATED_BY,
                )
            )
        db.commit()
        print(f"COMMITTED {len(planned)} partner_payment rows (memo tag '{MEMO_TAG}')")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
