#!/usr/bin/env python3
"""
apply_w14_partner_gross.py — Set partner_gross_total on W14 reconstructed batches.

W14 FA (batch 79) and W14 Maz (batch 80) were rebuilt from mom's xlsx after the
2026-05-03 DB wipe. The reconstruction script wrote driver net-pay into both
gross_pay and z_rate — it had no partner billing figures. This makes profit
display as $0 on the history page.

This script sets partner_gross_total on both batches so payroll_history can
compute real margin:
  FA  batch 79:  $17,194.00  (from W14_FA_Master_Payroll.xlsx SP PAY SUMMARY gross)
  Maz batch 80:  $14,653.06  (from W14_Master_Payroll.xlsx Table 1 gross)

Expected margin after apply:
  FA:  $17,194.00 - $14,404.00 = $2,790.00
  Maz: $14,653.06 -  $8,304.68 = $6,348.38

Usage:
  python scripts/apply_w14_partner_gross.py --dry-run   # verify only, no writes
  python scripts/apply_w14_partner_gross.py --apply     # commit to prod

Always take a DB backup before --apply.
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal

import psycopg2

DB_URL = "postgresql://app:zpay_secret_2026@junction.proxy.rlwy.net:38477/appdb"

# Source values (from mom's xlsx — do NOT change without re-verifying xlsx)
W14_FA_BATCH_ID = 79
W14_FA_PARTNER_GROSS = Decimal("17194.00")   # FA SP PAY SUMMARY, sum of GROSS PAY col

W14_MAZ_BATCH_ID = 80
W14_MAZ_PARTNER_GROSS = Decimal("14653.06")  # ED Table 1, sum of Gross col

PATCHES = [
    (W14_FA_BATCH_ID, W14_FA_PARTNER_GROSS, "W14 FA", "Acumen International"),
    (W14_MAZ_BATCH_ID, W14_MAZ_PARTNER_GROSS, "W14 Maz", "Maz Services"),
]


def run(dry_run: bool) -> None:
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    print(f"{'[DRY RUN] ' if dry_run else ''}apply_w14_partner_gross")
    print("=" * 60)

    for batch_id, partner_gross, label, expected_company in PATCHES:
        # Pre-flight: confirm batch exists and is the right one
        cur.execute(
            "SELECT payroll_batch_id, source, company_name, notes, partner_gross_total "
            "FROM payroll_batch WHERE payroll_batch_id = %s",
            (batch_id,)
        )
        row = cur.fetchone()
        if row is None:
            print(f"  ERROR: batch {batch_id} ({label}) not found — aborting")
            conn.rollback()
            conn.close()
            sys.exit(1)

        current_pgt = row[4]
        print(f"\n  {label} (batch_id={batch_id})")
        print(f"    company:           {row[2]}")
        print(f"    notes:             {row[3]}")
        print(f"    partner_gross now: {current_pgt}")
        print(f"    partner_gross set: {partner_gross}")

        # Get current ride aggregates for verification
        cur.execute(
            "SELECT SUM(gross_pay)::float, SUM(z_rate)::float FROM ride WHERE payroll_batch_id=%s",
            (batch_id,)
        )
        agg = cur.fetchone()
        ride_gross = round(float(agg[0] or 0), 2)
        ride_z_rate = round(float(agg[1] or 0), 2)
        expected_profit = round(float(partner_gross) - ride_z_rate, 2)
        print(f"    ride sum(gross_pay): {ride_gross}")
        print(f"    ride sum(z_rate):    {ride_z_rate}")
        print(f"    expected profit:     {expected_profit}")

        if not dry_run:
            cur.execute(
                "UPDATE payroll_batch SET partner_gross_total=%s WHERE payroll_batch_id=%s",
                (partner_gross, batch_id)
            )
            print(f"    APPLIED.")

    if dry_run:
        print("\n[DRY RUN] No writes made. Re-run with --apply to commit.")
        conn.rollback()
    else:
        conn.commit()
        print("\nCommitted. Verifying...")

        # Post-apply verification
        for batch_id, partner_gross, label, _ in PATCHES:
            cur.execute(
                "SELECT partner_gross_total FROM payroll_batch WHERE payroll_batch_id=%s",
                (batch_id,)
            )
            actual = cur.fetchone()[0]
            cur.execute(
                "SELECT SUM(z_rate)::float FROM ride WHERE payroll_batch_id=%s",
                (batch_id,)
            )
            z_rate = round(float(cur.fetchone()[0] or 0), 2)
            margin = round(float(actual) - z_rate, 2)
            status = "OK" if abs(float(actual) - float(partner_gross)) < 0.01 else "MISMATCH"
            print(f"  {label}: partner_gross_total={actual}  z_rate={z_rate}  margin=${margin}  [{status}]")

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Set partner_gross_total on W14 batches 79+80")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Print what would change, no writes")
    group.add_argument("--apply", action="store_true", help="Commit changes to prod DB")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
