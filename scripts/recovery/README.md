# Z-Pay Recovery Scripts — May 3 2026 DB Wipe Pipeline

Five-phase pipeline that recovered $148k of damage scope after a full database wipe.
Run these in order. Each phase reads from the prior phase's output files.

---

## What Each Script Does

### Phase A — `build_replay_ledger.py`
Reads the **live prod database** (read-only) and builds a per-driver per-week ledger
of what the DB currently shows was paid. Output is the "DB truth" before any corrections.

- Connects directly to Railway Postgres via public proxy
- Excludes the current in-flight batch (hardcoded `EXCLUDE_BATCH_ID = 73` for W15)
- Classifies each driver-week as PAID / HELD / MIXED / MISSING
- Outputs: `replay_ledger_W1_W14.csv`, `replay_summary.md`

### Phase B — `build_truth_ledger.py`
Reads **mom's weekly Excel files** from Google Drive (Wheels of Unity) as the ground truth.
Parses all format variants across W1–W14 (3 FA formats, 4 Maz formats).

- No DB calls during parsing (pure file read)
- Optionally enriches paycheck codes via a `railway run` DB lookup
- Outputs: `truth_ledger_W1_W14.csv`, `truth_summary.md`

### Phase C — `diff_ledgers.py`
Outer-joins the replay ledger vs the truth ledger on `(paycheck_code, week, llc)`.
No DB calls. Classifies every row into one of four buckets:

| Bucket | Meaning |
|--------|---------|
| MATCH | DB matches mom's file within $0.50 |
| DRIFT | Both exist but amounts differ by >$0.50 |
| TRUTH_ONLY | In mom's files but missing from DB (data loss) |
| REPLAY_ONLY | In DB but not in mom's files (potential overpay) |

- Outputs: `wipe_damage.csv`, `docs/incidents/2026-05-03-wipe-damage-report.md`

### Phase D — `reconcile_to_truth.py`
Applies corrections to prod DB in **one transaction** using `wipe_damage.csv` as input.

Three lanes run sequentially, then commit together:
1. **Lane 1 (TRUTH_ONLY):** Creates W14 batches and inserts missing ride rows
2. **Lane 2 (DRIFT):** Inserts signed adjustment rides to close the gap
3. **Lane 3 (REPLAY_ONLY):** Zeros out rides with no counterpart in mom's files, leaves audit trail

All writes are idempotent — re-running skips already-applied rows via `source_ref` guards.
Rolls back entirely on any exception.

- Outputs: `reconcile_applied.csv`, `reconcile_summary.md`, `QUESTIONS_FOR_MOM.md`

---

## Run Order

```bash
# Prereqs: psycopg2, openpyxl, Google Drive mounted at expected path
pip install psycopg2-binary openpyxl

# Phase A — build DB snapshot
python3 scripts/recovery/build_replay_ledger.py

# Phase B — build mom's Excel truth
python3 scripts/recovery/build_truth_ledger.py

# Phase C — diff them
python3 scripts/recovery/diff_ledgers.py

# Review wipe_damage.csv and the damage report before proceeding
# open ~/Library/Application\ Support/zpay-backups/audit/wipe_damage.csv

# Phase D — apply to prod (destructive — review Phase C output first)
python3 scripts/recovery/reconcile_to_truth.py
```

---

## Environment Variables / Prerequisites

| Requirement | Detail |
|-------------|--------|
| `DATABASE_URL` | Phase A and D use the public Railway proxy URL hardcoded in the script. Update if proxy changes. Current: `junction.proxy.rlwy.net:38477` |
| Google Drive | Must be mounted at `/Users/malikmilion/Library/CloudStorage/GoogleDrive-milionmalik@gmail.com/` with Wheels of Unity shortcut intact |
| `railway` CLI | Required only for Phase B's optional DB-enrichment step. `railway run --service zpay-backend` |
| Python packages | `psycopg2-binary`, `openpyxl` |

No additional env vars needed — the scripts use the hardcoded Railway proxy URL directly.
If you need to use `railway run` instead (e.g., proxy rotated), replace the `DB_URL` constant
at the top of `build_replay_ledger.py` and `reconcile_to_truth.py`.

---

## Audit Output Paths

All output lands in:
```
~/Library/Application Support/zpay-backups/audit/
├── replay_ledger_W1_W14.csv       — Phase A output
├── replay_summary.md              — Phase A summary
├── truth_ledger_W1_W14.csv        — Phase B output
├── truth_summary.md               — Phase B summary
├── wipe_damage.csv                — Phase C output (MATCH/DRIFT/TRUTH_ONLY/REPLAY_ONLY)
├── reconcile_applied.csv          — Phase D: every write logged
├── reconcile_summary.md           — Phase D: dollar-level summary
└── QUESTIONS_FOR_MOM.md           — Phase D: rows that couldn't be auto-resolved
```

The damage report also writes to:
```
docs/incidents/2026-05-03-wipe-damage-report.md
```

---

## Spot-Check Anchors

Phase D verifies these 5 anchors in the truth ledger before touching the DB.
If any fail, the script aborts without writing.

| Driver | Week | LLC | Expected Amount |
|--------|------|-----|----------------|
| Nuraynie Mohammed | W14 | FA | $164.00 |
| Kalkidan Kassa Tesfahun | W13 | Maz | $82.84 |
| Seude Mohammed Adem | W13 | Maz | $61.13 |
| Ahmed J Indris | W13 | FA | (exists check only) |
| Zubeda Adem | W13 | FA | (exists check only) |

---

## What Was Recovered (May 3–4 2026)

The pipeline recovered from a full wipe that zeroed all ride + batch data:

- **79 TRUTH_ONLY rows inserted** — primarily W14 FA + Maz batches (84/85 lost in wipe)
- **744 DRIFT adjustments applied** — DB amounts corrected to match mom's weekly Excel files
- **72 REPLAY_ONLY rows zeroed** — rides in DB with no mom's-file counterpart (ghost overpays)
- **81 drivers reconciled** across both LLCs (FA/Acumen + Maz/EverDriven)

See `docs/incidents/2026-05-03-db-wipe.md` for the full incident report.

---

## Safety Notes

- Phase D will NOT touch `payroll_batch_id = 73` (W15 in-flight at time of wipe)
- All Phase D writes tag service_name as `[W14_RECONSTRUCTED]`, `[RECONCILE_ADJ]`, or `[RECONCILE_REMOVE]`
- Re-running Phase D is safe — idempotent via `source_ref` uniqueness checks
- Phase A, B, C are read-only — safe to run at any time
