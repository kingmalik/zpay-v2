#!/usr/bin/env python3
"""
fix_najeebullah_balance_apply.py
---------------------------------
APPLY script — run ONCE against prod to zero the phantom W16 ED balance
for Najeebullah Ghareb Dost (person_id=30).

ALREADY APPLIED: 2026-05-07 ~21:30 UTC. This file is the git-resident
audit record of what was executed and what the result was.

Companion plan-only script:
  scripts/fix_najeebullah_balance_planonly.py  (read-only, prints evidence)

WHAT THIS DOES
==============
  - driver_balance_id=76  batch_id=85  W15 ED  $442  → UNCHANGED (authoritative)
  - driver_balance_id=78  batch_id=88  W16 ED  $442  → zeroed (phantom, artifact
    of W16 ED import re-stamping a carry-forward that already existed under batch 85)

SAFETY GUARDS
=============
  - UPDATE WHERE clause includes carried_over = 442.00 (exact match).
  - GET DIAGNOSTICS row_count check inside transaction — aborts if <> 1 row affected.
  - payroll_manual_withhold for pid=30 is NOT touched (separate concern; Malik added
    the withhold entry directly at 2026-05-06 23:40 UTC — driver owes company money).

EXECUTION RECORD
================
  Applied by:  zpay-agent (Jarvis / Claude Sonnet 4.6)
  Applied at:  2026-05-07 21:30 UTC (Malik at gym, full autonomy delegated)
  Backup:      20260507T180500Z.sql.gz.gpg (B2 verify passed before apply)
  Rows:        UPDATE 1  +  INSERT 1 (batch_correction_log)
  Result:      COMMIT confirmed

POST-FIX VERIFICATION (run anytime)
====================================
  SELECT
      driver_balance_id, payroll_batch_id, carried_over,
      settled_externally, external_method, updated_at
  FROM driver_balance
  WHERE person_id = 30 AND payroll_batch_id IN (85, 88)
  ORDER BY payroll_batch_id;

  Expected:
    batch_id=85  carried_over=442.00  settled_externally=false  (authoritative)
    batch_id=88  carried_over=0.00    settled_externally=true   (zeroed phantom)

TO RE-RUN (if ever needed on a fresh DB restore)
================================================
  python3 scripts/fix_najeebullah_balance_apply.py --apply
"""

from __future__ import annotations

import os
import sys

PROD_DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://app:zpay_secret_2026@junction.proxy.rlwy.net:38477/appdb",
)

APPLY_SQL = """
BEGIN;

DO $$
DECLARE
    row_count INTEGER;
BEGIN
    -- Step 1: Zero the phantom row (driver_balance_id=78, batch_id=88)
    UPDATE driver_balance
    SET
        carried_over       = 0.00,
        settled_externally = TRUE,
        external_method    = 'zero_phantom',
        external_amount    = 0.00,
        external_note      = 'PHANTOM DUPLICATE — zeroed 2026-05-07. Authoritative '
                             '$442 W15 ED carryforward is driver_balance_id=76 '
                             '(batch_id=85). This row (batch_id=88) was a W16 merge '
                             'artifact with no rides and no correction_log anchor. '
                             'Approved by Malik.',
        updated_at         = NOW()
    WHERE driver_balance_id = 78
      AND person_id         = 30
      AND payroll_batch_id  = 88
      AND carried_over      = 442.00;

    GET DIAGNOSTICS row_count = ROW_COUNT;

    IF row_count <> 1 THEN
        RAISE EXCEPTION 'UPDATE matched % rows (expected exactly 1). Aborting.', row_count;
    END IF;

    RAISE NOTICE 'UPDATE OK: % row affected.', row_count;

    -- Step 2: Audit log entry
    INSERT INTO batch_correction_log
        (batch_id, person_id, field, old_value, new_value, reason, corrected_by, corrected_at)
    VALUES
        (88, 30,
         'driver_balance.carried_over',
         '442.00',
         '0.00',
         'Phantom duplicate zeroed. W15 ED $442 carryforward is authoritative at '
         'driver_balance_id=76 (batch_85). Row created by W16 ED merge agent at '
         '2026-05-06 23:41 UTC — no ride data, no correction_log anchor, same '
         'batch_ref=1350821 as batch_85. Approved by Malik 2026-05-07.',
         'malik-direct',
         NOW());

    RAISE NOTICE 'Audit INSERT OK.';
END;
$$;

COMMIT;
"""

VERIFY_SQL = """
SELECT
    db.driver_balance_id,
    db.payroll_batch_id,
    db.carried_over,
    db.settled_externally,
    db.external_method,
    db.updated_at
FROM driver_balance db
WHERE db.person_id = 30
  AND db.payroll_batch_id IN (85, 88)
ORDER BY db.payroll_batch_id;
"""


def main() -> None:
    if "--apply" not in sys.argv:
        print(__doc__)
        print("\nTo apply: python3 scripts/fix_najeebullah_balance_apply.py --apply")
        print("NOTE: This was already applied to prod on 2026-05-07.")
        return

    try:
        import psycopg2  # type: ignore[import-untyped]
    except ImportError:
        print("psycopg2 not installed. Run: pip install psycopg2-binary")
        sys.exit(1)

    conn = psycopg2.connect(PROD_DB_URL)
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            # Pre-fix state
            cur.execute(VERIFY_SQL)
            rows_before = cur.fetchall()
            print("PRE-FIX STATE:")
            for row in rows_before:
                print(f"  balance_id={row[0]}  batch={row[1]}  carried_over={row[2]}"
                      f"  settled={row[3]}  method={row[4]}  updated={row[5]}")

            # Apply
            cur.execute(APPLY_SQL)

            # Post-fix state
            cur.execute(VERIFY_SQL)
            rows_after = cur.fetchall()
            print("\nPOST-FIX STATE:")
            for row in rows_after:
                print(f"  balance_id={row[0]}  batch={row[1]}  carried_over={row[2]}"
                      f"  settled={row[3]}  method={row[4]}  updated={row[5]}")

            # Verify expectations
            batch85 = next((r for r in rows_after if r[1] == 85), None)
            batch88 = next((r for r in rows_after if r[1] == 88), None)

            assert batch85 is not None, "Row A (batch 85) missing — abort"
            assert float(batch85[2]) == 442.00, f"Row A carried_over wrong: {batch85[2]}"
            assert batch85[3] is False, "Row A should not be settled"

            assert batch88 is not None, "Row B (batch 88) missing — abort"
            assert float(batch88[2]) == 0.00, f"Row B carried_over wrong: {batch88[2]}"
            assert batch88[3] is True, "Row B should be settled"
            assert batch88[4] == "zero_phantom", f"Row B external_method wrong: {batch88[4]}"

        conn.commit()
        print("\nCOMMIT OK. Fix verified.")

    except Exception as exc:
        conn.rollback()
        print(f"\nROLLBACK — error: {exc}")
        sys.exit(1)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
