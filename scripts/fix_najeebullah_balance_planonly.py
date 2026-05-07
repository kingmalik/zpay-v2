#!/usr/bin/env python3
"""
fix_najeebullah_balance_planonly.py
------------------------------------
READ-ONLY investigation + plan output for Najeebullah Ghareb Dost (pid=30)
double-counted $442 balance.

VERDICT: DUPLICATE
  - driver_balance_id=76  batch_id=85  ED W15  carried_over=$442.00  <- AUTHORITATIVE
  - driver_balance_id=78  batch_id=88  ED W16  carried_over=$442.00  <- PHANTOM (zero this)

NO DB WRITES. NO --apply. Prints the SQL that would fix it if Malik approves.

Run:  python3 scripts/fix_najeebullah_balance_planonly.py
"""

from __future__ import annotations

PROD_DB_URL = "postgresql://app:zpay_secret_2026@junction.proxy.rlwy.net:38477/appdb"

# ── Evidence record (from investigation 2026-05-07) ────────────────────────

EVIDENCE = """
INVESTIGATION SUMMARY
=====================
Driver:   Najeebullah Ghareb Dost  (person_id=30)
  paycheck_code      = 1108  (FA/Acumen)
  paycheck_code_maz  = 1080  (ED/Maz)
  Both codes non-NULL → dual-LLC driver. But read on.

Row A — driver_balance_id=76
  batch_id=85  source=maz  company=EverDriven  batch_ref=1350821
  period=2026-04-13→2026-04-19  (W15 ED)
  carried_over=$442.00
  updated_at=2026-05-06 22:25:31 UTC
  batch_correction_log id=22:
    field='driver_balance.carried_over'
    reason='W15 ED unpaid carry-forward: Najeebullah Ghareb Dost $442
            anchored to batch 85 per mom's W15 ED master Unpaid on Week
            section. Sum of 4 entries: 38+76+214+114.'
    corrected_by='zpay-agent'  corrected_at=2026-05-06 22:26:17 UTC

Row B — driver_balance_id=78
  batch_id=88  source=maz  company=EverDriven  batch_ref=1350821
  period=2026-04-20→2026-04-26  (W16 ED)
  carried_over=$442.00
  updated_at=2026-05-06 23:41:47 UTC
  NO batch_correction_log entry explaining this row.
  Rides for pid=30 in batch_88: 0
  Rides for pid=30 in batch_85: 0

Key finding:
  batch_ref=1350821 is IDENTICAL for both batch 85 and batch 88.
  Both are EverDriven / source=maz.
  There is NO ride data backing either row — the $442 is a pure
  carryforward balance inserted by the W15 ED settle agent at 22:25 UTC.

  Row B (batch 88) was created at 23:41 UTC — 75 minutes later —
  during the W16 ED import/merge workflow (batch_correction_log id=17
  shows batch_86 stub merged into batch_88 at 22:08 UTC).
  The W16 ED merge agent appears to have re-inserted the carried-over
  balance row for pid=30 into batch_88 without checking that it already
  existed under batch_85.

  Najeebullah is also in payroll_manual_withhold (note: 'owes company
  money'), added malik-direct at 23:40 UTC — 1 minute before Row B was
  created. The withhold note does NOT change which balance row is
  canonical; it just means both balances will be held regardless.

WHY ROW A IS AUTHORITATIVE:
  1. batch_correction_log id=22 explicitly documents the $442 amount and
     its source (mom's W15 ED 'Unpaid on Week' section, sum of 4 sub-entries:
     $38+$76+$214+$114). This is the mom-sourced anchor.
  2. Row A is anchored to batch_85 (W15 ED) — the correct week this
     balance accrued.
  3. Row B has zero supporting correction log, zero rides, and sits in
     batch_88 (W16 ED) which is the WRONG week for this balance.
  4. Same batch_ref=1350821 on both batches confirms the W16 batch was
     imported from the same PDF as W15 (multi-week file), and the agent
     mistakenly re-stamped the carryforward.

EFFECTIVE DOUBLE-COUNT: $442 shown twice = $884 displayed to mom.
The authoritative amount is $442 (Row A, batch 85).
"""

# ── Plan-only SQL ────────────────────────────────────────────────────────────

PLAN_SQL = """
-- PLAN ONLY — DO NOT EXECUTE WITHOUT MALIK APPROVAL
-- Fix: zero out the phantom Row B (driver_balance_id=78, batch_id=88)
-- Preserve Row A (driver_balance_id=76, batch_id=85) untouched.

BEGIN;

-- Step 1: Zero the carried_over on the phantom row.
-- We set to 0.00 (not DELETE) to preserve the audit trail.
UPDATE driver_balance
SET
    carried_over      = 0.00,
    settled_externally = TRUE,
    external_method   = 'zero_phantom',
    external_amount   = 0.00,
    external_note     = 'PHANTOM DUPLICATE — zeroed 2026-05-07. Authoritative '
                        '$442 W15 ED carryforward is driver_balance_id=76 '
                        '(batch_id=85). This row (batch_id=88) was a W16 merge '
                        'artifact with no rides and no correction_log anchor. '
                        'Approved by Malik.',
    updated_at        = NOW()
WHERE driver_balance_id = 78
  AND person_id          = 30
  AND payroll_batch_id   = 88
  AND carried_over       = 442.00;   -- safety guard: only touches exact row

-- Step 2: Log to batch_correction_log for audit trail.
INSERT INTO batch_correction_log
    (batch_id, person_id, field, old_value, new_value, reason, corrected_by, corrected_at)
VALUES
    (88, 30,
     'driver_balance.carried_over',
     '442.00',
     '0.00',
     'Phantom duplicate zeroed. W15 ED $442 carryforward is authoritative at '
     'driver_balance_id=76 (batch_85). This row was created by W16 ED merge '
     'agent at 2026-05-06 23:41 UTC with no ride data or correction_log anchor. '
     'Same batch_ref=1350821 on both batches confirmed same-source double-insert.',
     'malik-direct',
     NOW());

-- ROLLBACK;   -- uncomment to dry-run in psql
COMMIT;
"""

VERIFICATION_QUERY = """
-- Run this AFTER applying to verify:
SELECT
    db.driver_balance_id,
    db.payroll_batch_id,
    db.carried_over,
    db.settled_externally,
    db.external_note,
    db.updated_at
FROM driver_balance db
WHERE db.person_id = 30
  AND db.payroll_batch_id IN (85, 88)
ORDER BY db.payroll_batch_id;

-- Expected after fix:
--  batch_id=85  carried_over=442.00  settled_externally=false   (AUTHORITATIVE, unchanged)
--  batch_id=88  carried_over=0.00    settled_externally=true    (ZEROED phantom)
"""

if __name__ == "__main__":
    print("=" * 70)
    print("PLAN-ONLY: fix_najeebullah_balance_planonly.py")
    print("NO DB WRITES IN THIS SCRIPT.")
    print("=" * 70)
    print(EVIDENCE)
    print("=" * 70)
    print("PROPOSED FIX SQL (plan only — requires Malik approval before apply):")
    print("=" * 70)
    print(PLAN_SQL)
    print("=" * 70)
    print("POST-FIX VERIFICATION QUERY:")
    print("=" * 70)
    print(VERIFICATION_QUERY)
    print()
    print("To apply after Malik approves:")
    print(
        "  PGPASSWORD=zpay_secret_2026 psql "
        "'postgresql://app:zpay_secret_2026@junction.proxy.rlwy.net:38477/appdb' "
        "-f <(python3 scripts/fix_najeebullah_balance_planonly.py | "
        "sed -n '/PLAN ONLY/,/COMMIT/p')"
    )
    print()
    print("Or paste the SQL block above directly into psql after removing")
    print("the '-- PLAN ONLY' comment line.")
