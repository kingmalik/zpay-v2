#!/usr/bin/env python3
"""
fix_batch72_phantoms_apply.py
------------------------------
APPLY script — run ONCE against prod to zero 6 phantom batch-72
driver_balance rows created by the 2026-05-04 wipe-recovery script.

Companion plan-only script:
  scripts/fix_batch72_phantoms_planonly.py  (read-only, prints evidence)

WHAT THIS DOES
==============
Zeros the following driver_balance rows (all in batch 72, W14 ED,
Mar 30–Apr 5, batch_ref=1348853). These are wipe-recovery artifacts
with zero rides in batch 72, each duplicating a prior-week real balance:

  bal_id | pid | name                              | amount  | real_row
  -------+-----+-----------------------------------+---------+---------
     54  |  22 | Meskerem Hussen Juhar              |  $86.72 | bal_id 18 (batch 9)
     56  |  30 | Najeebullah Ghareb dost            |  $41.42 | bal_id 26 (batch 16)
     51  |  45 | Elham Mohammedtahir Mohammedseid   |  $89.60 | bal_id 43 (batch 58)
     53  |  56 | Helen Shumie Marie                 |  $41.42 | bal_id 44 (batch 58)
     57  |  92 | Nessanet Nuru                     |  $86.72 | bal_id 32 (batch 24)
     52  | 118 | Finan Abreham                     |  $48.18 | bal_id 45 (batch 58)

  Total reclaimed: $394.06

Same root cause as PR #65 Najeebullah fix (bal_id=78), just 6 rows
instead of 1.

SAFETY GUARDS
=============
  - Pre-flight SELECT: must find exactly 6 rows with settled_externally != TRUE.
    If any are already zeroed (idempotent guard), they are excluded and reported.
    If count != 6, transaction aborts.
  - UPDATE rowcount check inside transaction — aborts if != 6.
  - Authoritative prior-week rows (bal_ids 18, 26, 43, 44, 32, 45) are NOT touched.
  - payroll_manual_withhold is NOT touched (separate concern).

EXECUTION RECORD
================
  Applied by:  zpay-agent (Jarvis / Claude Sonnet 4.6)
  Applied at:  2026-05-07 (Malik at gym, full autonomy delegated)
  Backup:      manual-pre-batch72-phantom-fix-20260507-2144.sql (2.1M, verified)

TO RUN
======
  python3 scripts/fix_batch72_phantoms_apply.py --apply
"""

from __future__ import annotations

import os
import sys

PROD_DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://app:zpay_secret_2026@junction.proxy.rlwy.net:38477/appdb",
)

PHANTOM_BAL_IDS = (54, 56, 51, 53, 57, 52)
BATCH_72_ID = 72

PHANTOM_ROWS = [
    {
        "bal_id": 54,
        "person_id": 22,
        "name": "Meskerem Hussen Juhar",
        "amount": 86.72,
        "dup_of_bal_id": 18,
        "dup_of_batch": 9,
    },
    {
        "bal_id": 56,
        "person_id": 30,
        "name": "Najeebullah Ghareb dost",
        "amount": 41.42,
        "dup_of_bal_id": 26,
        "dup_of_batch": 16,
    },
    {
        "bal_id": 51,
        "person_id": 45,
        "name": "Elham Mohammedtahir Mohammedseid",
        "amount": 89.60,
        "dup_of_bal_id": 43,
        "dup_of_batch": 58,
    },
    {
        "bal_id": 53,
        "person_id": 56,
        "name": "Helen Shumie Marie",
        "amount": 41.42,
        "dup_of_bal_id": 44,
        "dup_of_batch": 58,
    },
    {
        "bal_id": 57,
        "person_id": 92,
        "name": "Nessanet Nuru",
        "amount": 86.72,
        "dup_of_bal_id": 32,
        "dup_of_batch": 24,
    },
    {
        "bal_id": 52,
        "person_id": 118,
        "name": "Finan Abreham",
        "amount": 48.18,
        "dup_of_bal_id": 45,
        "dup_of_batch": 58,
    },
]

PRE_FLIGHT_SQL = """
SELECT
    driver_balance_id,
    person_id,
    payroll_batch_id,
    carried_over,
    settled_externally,
    external_method,
    updated_at
FROM driver_balance
WHERE driver_balance_id = ANY(%s)
ORDER BY driver_balance_id;
"""

UPDATE_SQL = """
UPDATE driver_balance
SET
    carried_over       = 0.00,
    settled_externally = TRUE,
    external_method    = 'phantom_zero',
    external_note      = 'Batch 72 wipe-recovery phantom: zero rides in batch, '
                         'duplicate of prior-week real balance. Zeroed 2026-05-07.',
    settled_at         = NOW(),
    settled_by         = 'zpay-agent-phantom-sweep',
    updated_at         = NOW()
WHERE driver_balance_id = ANY(%s)
  AND settled_externally IS DISTINCT FROM TRUE;
"""

AUDIT_INSERT_SQL = """
INSERT INTO batch_correction_log
    (batch_id, person_id, field, old_value, new_value, reason, corrected_by, corrected_at)
VALUES
    (%s, %s,
     'driver_balance.carried_over',
     %s, '0.00',
     %s,
     'zpay-agent-phantom-sweep',
     NOW());
"""

POST_FIX_SQL = """
SELECT
    db.driver_balance_id,
    db.person_id,
    db.payroll_batch_id,
    db.carried_over,
    db.settled_externally,
    db.external_method,
    db.settled_by,
    db.updated_at
FROM driver_balance db
WHERE db.driver_balance_id = ANY(%s)
ORDER BY db.driver_balance_id;
"""

PRIOR_ROWS_CHECK_SQL = """
SELECT
    driver_balance_id,
    person_id,
    carried_over,
    settled_externally
FROM driver_balance
WHERE driver_balance_id = ANY(%s)
ORDER BY driver_balance_id;
"""

AUTHORITATIVE_BAL_IDS = [18, 26, 43, 44, 32, 45]


def main() -> None:
    if "--apply" not in sys.argv:
        print(__doc__)
        print("\nTo apply: python3 scripts/fix_batch72_phantoms_apply.py --apply")
        return

    try:
        import psycopg2  # type: ignore[import-untyped]
    except ImportError:
        print("psycopg2 not installed. Run: pip install psycopg2-binary")
        sys.exit(1)

    print("=" * 70)
    print("fix_batch72_phantoms_apply.py — APPLYING TO PROD")
    print("=" * 70)

    conn = psycopg2.connect(PROD_DB_URL)
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            # ── Pre-flight: inspect current state ───────────────────────────
            cur.execute(PRE_FLIGHT_SQL, (list(PHANTOM_BAL_IDS),))
            rows_before = cur.fetchall()

            print(f"\nPRE-FLIGHT STATE ({len(rows_before)} rows found):")
            already_settled = []
            to_zero = []
            for row in rows_before:
                bal_id, pid, batch, carried, settled, method, updated = row
                status = "ALREADY SETTLED (idempotent guard)" if settled else "to zero"
                print(
                    f"  bal_id={bal_id}  pid={pid}  batch={batch}"
                    f"  carried_over={carried}  settled={settled}"
                    f"  method={method or 'none'}  [{status}]"
                )
                if settled:
                    already_settled.append(bal_id)
                else:
                    to_zero.append(bal_id)

            if already_settled:
                print(f"\nIDEMPOTENT GUARD: {len(already_settled)} row(s) already settled,"
                      f" will be excluded: {already_settled}")

            expected_to_zero = len(PHANTOM_BAL_IDS) - len(already_settled)

            if len(to_zero) != 6:
                # If already_settled > 0, adjust expectation
                if len(to_zero) != expected_to_zero:
                    raise ValueError(
                        f"Pre-flight: expected {expected_to_zero} rows to zero,"
                        f" found {len(to_zero)}. Something changed. Aborting."
                    )

            if len(to_zero) == 0:
                print("\nAll 6 rows already settled. Nothing to do. Exiting clean.")
                return

            if len(to_zero) != 6:
                raise ValueError(
                    f"Pre-flight: expected 6 rows to zero, only {len(to_zero)} eligible."
                    f" Already settled: {already_settled}. Aborting — check with Malik."
                )

            print(f"\nPre-flight OK: {len(to_zero)} rows will be zeroed.")

            # ── Apply UPDATE ─────────────────────────────────────────────────
            cur.execute(UPDATE_SQL, (list(PHANTOM_BAL_IDS),))
            updated_count = cur.rowcount

            if updated_count != 6:
                raise ValueError(
                    f"UPDATE matched {updated_count} rows (expected 6). "
                    f"Rolling back."
                )

            print(f"\nUPDATE OK: {updated_count} rows zeroed.")

            # ── Audit log: one INSERT per phantom row ────────────────────────
            audit_count = 0
            for r in PHANTOM_ROWS:
                reason = (
                    f"Batch 72 wipe-recovery phantom zeroed. "
                    f"{r['name']} (pid={r['person_id']}): "
                    f"phantom bal_id={r['bal_id']} duplicates authoritative "
                    f"bal_id={r['dup_of_bal_id']} (batch {r['dup_of_batch']}). "
                    f"Root cause: 2026-05-04 05:40 UTC recovery sweep, 0 rides "
                    f"in batch 72. Same pattern as PR #65 Najeebullah fix."
                )
                cur.execute(
                    AUDIT_INSERT_SQL,
                    (
                        BATCH_72_ID,
                        r["person_id"],
                        f"{r['amount']:.2f}",
                        reason,
                    ),
                )
                audit_count += 1

            print(f"Audit INSERTs OK: {audit_count} log entries written.")

            # ── Commit ───────────────────────────────────────────────────────
            conn.commit()
            print("\nCOMMIT OK.")

            # ── Post-fix verification ────────────────────────────────────────
            with conn.cursor() as vcur:
                vcur.execute(POST_FIX_SQL, (list(PHANTOM_BAL_IDS),))
                rows_after = vcur.fetchall()

            print(f"\nPOST-FIX STATE ({len(rows_after)} rows):")
            all_good = True
            for row in rows_after:
                bal_id, pid, batch, carried, settled, method, settled_by, updated = row
                ok = (float(carried) == 0.0) and settled and method == "phantom_zero"
                status = "OK" if ok else "MISMATCH"
                if not ok:
                    all_good = False
                print(
                    f"  bal_id={bal_id}  pid={pid}  carried_over={carried}"
                    f"  settled={settled}  method={method}  [{status}]"
                )

            # ── Verify authoritative rows untouched ──────────────────────────
            with conn.cursor() as vcur:
                vcur.execute(PRIOR_ROWS_CHECK_SQL, (AUTHORITATIVE_BAL_IDS,))
                prior_rows = vcur.fetchall()

            print(f"\nAUTHORITATIVE PRIOR ROWS (must be untouched):")
            for row in prior_rows:
                bal_id, pid, carried, settled = row
                ok = not settled and float(carried) > 0
                status = "OK (untouched)" if ok else "WARNING — check this"
                if not ok:
                    all_good = False
                print(
                    f"  bal_id={bal_id}  pid={pid}"
                    f"  carried_over={carried}  settled={settled}  [{status}]"
                )

            total_zeroed = sum(r["amount"] for r in PHANTOM_ROWS)
            print(f"\nTotal dollars zeroed: ${total_zeroed:.2f}")
            print(f"Audit log entries inserted: {audit_count}")

            if already_settled:
                print(f"\nIDEMPOTENT GUARD triggered for: {already_settled}")
                print("  These were already settled before this run — not re-zeroed.")

            if all_good:
                print("\nALL CHECKS PASSED. Fix complete.")
            else:
                print("\nWARNING: Some post-fix checks did not pass. Review output above.")

    except Exception as exc:
        conn.rollback()
        print(f"\nROLLBACK — error: {exc}")
        sys.exit(1)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
