#!/usr/bin/env python3
"""
fix_batch72_phantoms_planonly.py
---------------------------------
READ-ONLY investigation + plan output for 6 phantom driver_balance rows
created by the 2026-05-04 wipe-recovery script in batch 72 (W14 ED,
Mar 30–Apr 5, batch_ref=1348853).

All 6 rows were inserted at 2026-05-04 05:40 UTC in a single sweep.
Each has 0 rides in batch 72 and is an exact-amount duplicate of a
prior-week real balance with audit trail.

Total double-counted: $394.06

NO DB WRITES. NO --apply. Prints the SQL that would fix it.

Pattern match to PR #65 (Najeebullah bal_id=78 — already fixed 2026-05-07).

Run:  python3 scripts/fix_batch72_phantoms_planonly.py
"""

from __future__ import annotations

PROD_DB_URL = "postgresql://app:zpay_secret_2026@junction.proxy.rlwy.net:38477/appdb"

# ── Evidence record ──────────────────────────────────────────────────────────

EVIDENCE = """
INVESTIGATION SUMMARY
=====================
Root cause:
  2026-05-04 wipe-recovery script ran at 05:40 UTC. It re-inserted
  carried-over balances for multiple drivers into batch 72 (W14 ED,
  batch_ref=1348853, period 2026-03-30 to 2026-04-05) without checking
  whether authoritative rows for those same amounts already existed in
  prior-week batches.

  The result: 6 drivers each have TWO driver_balance rows for the same
  dollar amount — the real row anchored to the correct prior batch, and
  a phantom row stamped into batch 72 with zero supporting rides.

  This is the same pattern as Najeebullah bal_id=78 (zeroed in PR #65,
  2026-05-07), except at scale across 6 rows.

The 6 phantom rows to zero (batch 72 / 2026-05-04 05:40 UTC sweep):

  bal_id | person_id | name                              | amount  | dup_of
  -------+-----------+-----------------------------------+---------+--------
     54  |    22     | Meskerem Hussen Juhar              |  $86.72 | bal_id 18 (batch 9)
     56  |    30     | Najeebullah Ghareb dost            |  $41.42 | bal_id 26 (batch 16)
     51  |    45     | Elham Mohammedtahir Mohammedseid   |  $89.60 | bal_id 43 (batch 58)
     53  |    56     | Helen Shumie Marie                 |  $41.42 | bal_id 44 (batch 58)
     57  |    92     | Nessanet Nuru                     |  $86.72 | bal_id 32 (batch 24)
     52  |   118     | Finan Abreham                     |  $48.18 | bal_id 45 (batch 58)

  Total: $86.72 + $41.42 + $89.60 + $41.42 + $86.72 + $48.18 = $394.06

Why the phantom rows are NOT authoritative:
  1. All 6 inserted in a single script run at 2026-05-04 05:40 UTC (wipe
     recovery artifact — confirmed by updated_at clustering).
  2. Each has 0 rides in batch 72 (no real trip data for the week).
  3. Each is an exact-amount duplicate of a prior-week balance that has
     its own audit trail (batch_correction_log or mom-sourced anchor).
  4. Note: Najeebullah bal_id=56 ($41.42) here is DIFFERENT from the
     $442 phantom zeroed in PR #65 (bal_id=78) — this is his batch 72
     phantom, which is separate.

Idempotency guard:
  If any row already has settled_externally=TRUE, it was zeroed by a
  prior run and will be skipped (apply script enforces this).
"""

# ── Phantom row specs ────────────────────────────────────────────────────────

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

BATCH_72_ID = 72  # The phantom batch (W14 ED, Mar 30–Apr 5, batch_ref=1348853)

# ── Plan-only SQL ────────────────────────────────────────────────────────────

def build_plan_sql() -> str:
    lines = [
        "-- PLAN ONLY — DO NOT EXECUTE WITHOUT MALIK APPROVAL",
        "-- Fix: zero out 6 phantom batch-72 driver_balance rows.",
        "-- Each phantom is a wipe-recovery artifact (2026-05-04 05:40 UTC sweep).",
        "-- Authoritative prior-week rows are NOT touched.",
        "",
        "BEGIN;",
        "",
        "DO $$",
        "DECLARE",
        "    row_count INTEGER;",
        "BEGIN",
        "",
        "    -- ── Pre-flight: verify exactly 6 rows exist and are not yet settled ──",
        "    SELECT COUNT(*) INTO row_count",
        "    FROM driver_balance",
        "    WHERE driver_balance_id IN (54, 56, 51, 53, 57, 52)",
        "      AND settled_externally IS DISTINCT FROM TRUE;",
        "",
        "    IF row_count <> 6 THEN",
        "        RAISE EXCEPTION",
        "            'Pre-flight: expected 6 un-settled phantom rows, found %. '",
        "            'Some may already be zeroed or missing. Aborting.', row_count;",
        "    END IF;",
        "",
        "    RAISE NOTICE 'Pre-flight OK: % rows to zero.', row_count;",
        "",
        "    -- ── UPDATE all 6 in one statement ──",
        "    UPDATE driver_balance",
        "    SET",
        "        carried_over       = 0.00,",
        "        settled_externally = TRUE,",
        "        external_method    = 'phantom_zero',",
        "        external_note      = 'Batch 72 wipe-recovery phantom: zero rides in batch, "
        "duplicate of prior-week real balance. Zeroed 2026-05-07.',",
        "        settled_at         = NOW(),",
        "        settled_by         = 'zpay-agent-phantom-sweep',",
        "        updated_at         = NOW()",
        "    WHERE driver_balance_id IN (54, 56, 51, 53, 57, 52)",
        "      AND settled_externally IS DISTINCT FROM TRUE;",
        "",
        "    GET DIAGNOSTICS row_count = ROW_COUNT;",
        "",
        "    IF row_count <> 6 THEN",
        "        RAISE EXCEPTION 'UPDATE matched % rows (expected 6). Aborting.', row_count;",
        "    END IF;",
        "",
        "    RAISE NOTICE 'UPDATE OK: % rows zeroed.', row_count;",
        "",
        "    -- ── Audit log: one INSERT per phantom row ──",
    ]

    for r in PHANTOM_ROWS:
        lines.append(
            f"    INSERT INTO batch_correction_log"
            f" (batch_id, person_id, field, old_value, new_value, reason, corrected_by, corrected_at)"
            f" VALUES ({BATCH_72_ID}, {r['person_id']},"
            f" 'driver_balance.carried_over',"
            f" '{r['amount']:.2f}', '0.00',"
            f" 'Batch 72 wipe-recovery phantom zeroed. {r['name']} (pid={r['person_id']}):"
            f" phantom bal_id={r['bal_id']} duplicates authoritative bal_id={r['dup_of_bal_id']}"
            f" (batch {r['dup_of_batch']}). Root cause: 2026-05-04 05:40 UTC recovery sweep."
            f" Same pattern as PR #65 Najeebullah fix.',"
            f" 'zpay-agent-phantom-sweep', NOW());"
        )

    lines += [
        "",
        "    RAISE NOTICE 'Audit INSERTs OK.';",
        "END;",
        "$$;",
        "",
        "-- ROLLBACK;  -- uncomment to dry-run in psql",
        "COMMIT;",
    ]

    return "\n".join(lines)


VERIFICATION_QUERY = """
-- Run AFTER applying to confirm all 6 are zeroed:
SELECT
    db.driver_balance_id,
    db.person_id,
    db.carried_over,
    db.settled_externally,
    db.external_method,
    db.settled_by,
    db.updated_at
FROM driver_balance db
WHERE db.driver_balance_id IN (54, 56, 51, 53, 57, 52)
ORDER BY db.driver_balance_id;

-- Expected for each row:
--   carried_over=0.00  settled_externally=true
--   external_method='phantom_zero'  settled_by='zpay-agent-phantom-sweep'

-- Confirm authoritative prior-week rows are UNTOUCHED:
SELECT
    db.driver_balance_id,
    db.person_id,
    db.carried_over,
    db.settled_externally
FROM driver_balance db
WHERE db.driver_balance_id IN (18, 26, 43, 44, 32, 45)
ORDER BY db.driver_balance_id;

-- Expected for each: settled_externally IS NULL or FALSE, carried_over > 0
"""

if __name__ == "__main__":
    total = sum(r["amount"] for r in PHANTOM_ROWS)
    bal_ids = ", ".join(str(r["bal_id"]) for r in PHANTOM_ROWS)

    print("=" * 70)
    print("PLAN-ONLY: fix_batch72_phantoms_planonly.py")
    print("NO DB WRITES IN THIS SCRIPT.")
    print("=" * 70)
    print(EVIDENCE)
    print("=" * 70)
    print(f"Phantom bal_ids to zero: {bal_ids}")
    print(f"Total dollars reclaimed: ${total:.2f}")
    print("=" * 70)
    print()
    print("PROPOSED FIX SQL (plan only):")
    print("-" * 70)
    print(build_plan_sql())
    print()
    print("=" * 70)
    print("POST-FIX VERIFICATION QUERY:")
    print("=" * 70)
    print(VERIFICATION_QUERY)
    print()
    print("To apply after approval:")
    print(
        "  python3 scripts/fix_batch72_phantoms_apply.py --apply"
    )
