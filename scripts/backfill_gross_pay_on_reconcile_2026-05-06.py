#!/usr/bin/env python3
"""
backfill_gross_pay_on_reconcile_2026-05-06.py
=============================================
Set gross_pay = z_rate on synthetic reconcile rows where gross_pay is 0 or NULL
and z_rate > 0.

These rows were inserted by closeout/reconcile scripts that correctly populated
net_pay and z_rate but left gross_pay at 0. Once the payroll_history query is
flipped to use SUM(gross_pay) as partner revenue, those rows would show $0 partner
revenue — wrong. Setting gross_pay = z_rate makes them contribute $0 margin
(gross_pay == z_rate == net_pay), which is the correct semantic for a synthetic
anchoring row.

Target: rows WHERE (source ILIKE '%reconcile%' OR z_rate_source ILIKE '%reconcile%')
                 AND (gross_pay = 0 OR gross_pay IS NULL)
                 AND z_rate > 0

Usage:
  python3 scripts/backfill_gross_pay_on_reconcile_2026-05-06.py           # dry-run
  python3 scripts/backfill_gross_pay_on_reconcile_2026-05-06.py --apply   # apply
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

PROD_DB_URL = "postgresql://app:zpay_secret_2026@junction.proxy.rlwy.net:38477/appdb"

AUDIT_QUERY = """
SELECT
    ride_id,
    payroll_batch_id,
    person_id,
    source,
    source_ref,
    z_rate,
    z_rate_source,
    gross_pay,
    net_pay
FROM ride
WHERE
    (source ILIKE '%reconcile%' OR z_rate_source ILIKE '%reconcile%')
    AND (gross_pay = 0 OR gross_pay IS NULL)
    AND z_rate > 0
ORDER BY payroll_batch_id, ride_id
"""

UPDATE_QUERY = """
UPDATE ride
SET gross_pay = z_rate
WHERE
    (source ILIKE '%reconcile%' OR z_rate_source ILIKE '%reconcile%')
    AND (gross_pay = 0 OR gross_pay IS NULL)
    AND z_rate > 0
"""


def get_conn():
    import psycopg2
    conn = psycopg2.connect(PROD_DB_URL, connect_timeout=15)
    conn.autocommit = False
    return conn


def run(dry_run: bool) -> int:
    mode = "DRY-RUN" if dry_run else "APPLY"
    print(f"\n{'=' * 68}")
    print(f"  backfill_gross_pay_on_reconcile  [{mode}]  {datetime.now().isoformat(timespec='seconds')}")
    print(f"{'=' * 68}")

    conn = get_conn()
    cur = conn.cursor()

    try:
        # Always audit first
        cur.execute(AUDIT_QUERY)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]

        print(f"\n[Audit] {len(rows)} row(s) match backfill criteria:\n")
        if rows:
            header = f"  {'ride_id':>8}  {'batch':>6}  {'pid':>5}  {'source':>20}  {'z_rate':>8}  {'gross_pay':>10}  {'net_pay':>8}"
            print(header)
            print("  " + "-" * 72)
            for r in rows:
                rd = dict(zip(cols, r))
                print(
                    f"  {rd['ride_id']:>8}  {rd['payroll_batch_id']:>6}  "
                    f"{rd['person_id']:>5}  {str(rd['source']):>20}  "
                    f"{float(rd['z_rate'] or 0):>8.2f}  "
                    f"{float(rd['gross_pay'] or 0):>10.2f}  "
                    f"{float(rd['net_pay'] or 0):>8.2f}"
                )

        if len(rows) == 0:
            print("\n  Nothing to backfill — all reconcile rows already have gross_pay set.")
            conn.rollback()
            return 0

        # Safety gate: if somehow there are > 500 rows, stop
        if len(rows) > 500:
            print(f"\n  ABORT: {len(rows)} rows found — exceeds safe threshold of 500.")
            print("  This is unexpected. Investigate before proceeding.")
            conn.rollback()
            return 1

        if dry_run:
            print(f"\n  [DRY-RUN] Would update {len(rows)} row(s). No writes.")
            conn.rollback()
            return 0

        # Apply
        print(f"\n[Applying UPDATE to {len(rows)} row(s)]")
        cur.execute(UPDATE_QUERY)
        updated = cur.rowcount
        print(f"  rowcount = {updated}")

        # Verify: re-run audit — should return 0 rows now
        cur.execute(AUDIT_QUERY)
        remaining = cur.fetchall()
        if remaining:
            print(f"  WARN: {len(remaining)} row(s) still match after UPDATE — rolling back")
            conn.rollback()
            return 1

        conn.commit()
        print(f"  COMMITTED. {updated} row(s) updated. gross_pay = z_rate on all reconcile rows.")
        return 0

    except Exception as exc:
        import traceback
        print(f"\n  EXCEPTION — ROLLING BACK: {exc}")
        traceback.print_exc()
        conn.rollback()
        return 1
    finally:
        cur.close()
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill gross_pay = z_rate on synthetic reconcile rows"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Apply the UPDATE (default: dry-run only)",
    )
    args = parser.parse_args()
    sys.exit(run(dry_run=not args.apply))


if __name__ == "__main__":
    main()
