# Migration Safety Audit — 2026-05-03

Reviewed all Alembic migrations from 2026-04-25 onward.
This is a read-only audit. Fixes are Malik's call.

## Summary

| Migration | Risk | Rollback | Notes |
|---|---|---|---|
| `za1b2c3d4e5f6` | LOW | YES | Moves drug test cols |
| `zb2c3d4e5f6g7` | MEDIUM | YES | Data-mutating backfill |
| `zc3d4e5f6g7h8` | LOW | YES | IF NOT EXISTS safe |
| `zd4e5f6g7h8i9` | LOW | YES | Nullable add |
| `ze1f2g3h4i5j6` | LOW | YES | New table + nullable cols |
| `ze5f6g7h8i9j` | MEDIUM | YES | Parallel head — was part of orphan-head storm |
| `zf6g7h8i9j0k` | LOW | YES | Nullable add with default |
| `zg7h8i9j0k1l` | LOW | YES | Nullable add |
| `zh8i9j0k1l2m` | LOW | YES | Nullable add |
| `zi1j2k3l4m5n` | LOW | YES | Nullable add with default |
| `zj2k3l4m5n6o` | LOW | YES | Nullable add |
| `zk3l4m5n6o7p` | LOW | YES | IF NOT EXISTS safe |
| `zl4m5n6o7p8q` | LOW | YES | CREATE IF NOT EXISTS — idempotent |

## Detailed Findings

### `zb2c3d4e5f6g7` — Backfill Manual Rides (MEDIUM risk)

- Mutates live `ride` rows: sets `source='manual'` and `net_pay=0` for rows where `z_rate_source='manual'`
- Has a downgrade that drops columns, but does NOT restore the overwritten data values
- **Risk**: If run against a prod DB that already had a different run of this migration,
  it will overwrite again (idempotent at the column level but not at data level)
- **No blocking issue** — just note that this migration modifies data irreversibly

### `ze5f6g7h8i9j` — Alert Overrides (MEDIUM risk — was in orphan-head storm)

- `down_revision = "zd4e5f6g7h8i9"` — same parent as `ze1f2g3h4i5j6`
- This created the 3-way orphan-head conflict that triggered the May 2 crash loop
- The conflict was resolved by `1024a56610b6_merge_scorecard_phase_1_orphan_into_.py`
- **Rollback**: full downgrade path exists — drops notification_event table, removes 6 columns
- **Risk now**: resolved. But demonstrates the gap: two migrations with same parent were
  committed without a merge migration, causing Alembic to refuse to run either

### `zk3l4m5n6o7p` — person.status + maz_contract_status (LOW risk, good pattern)

- Uses `ADD COLUMN IF NOT EXISTS` — idempotent against a DB that already has these columns
- Safe to run on a fresh DB (which it did after the wipe)
- **Recommendation**: all future migrations that add columns should use `IF NOT EXISTS`

### `zl4m5n6o7p8q` — Payroll Override Tables (LOW risk, good pattern)

- Uses `CREATE TABLE IF NOT EXISTS` — idempotent
- Written post-wipe specifically because these tables were missing after restore
- **Recommendation**: any table creation should always use `CREATE TABLE IF NOT EXISTS`

## Structural Issues

### Issue 1: No Standard Pre-Upgrade Snapshot Hook

None of the migrations trigger a DB snapshot before running. If a migration fails mid-way
(especially a data-mutating one like `zb2c3d4e5f6g7`), recovery requires manual rollback.

**Recommendation (Malik decides)**: Add a pre-migration hook in `env.py` that calls
`/snapshot/save` before any upgrade, gated by `BACKUP_BEFORE_MIGRATE=1` env var.

### Issue 2: `zb2c3d4e5f6g7` Has No True Data Rollback

The downgrade drops the columns but doesn't restore the original values.
Comment in the file itself warns "run interactively with Malik present" — but Railway auto-runs
migrations on every deploy. This is a documentation mismatch.

**Recommendation**: Either mark this migration as "no auto-run, manual only" (via Alembic
`--sql` flag + manual apply) or accept that the data mutation is intentional and permanent.

### Issue 3: Orphan Head Pattern (was the May 2 root cause)

Two migrations shared `down_revision = "zd4e5f6g7h8i9"`:
- `ze1f2g3h4i5j6` (trip_status_event)
- `ze5f6g7h8i9j` (alert_overrides)

This is an Alembic multi-head situation. Alembic refused to run either until a merge migration
(`1024a56610b6`) was created. The crash loop this caused is the likely precursor to the May 3
Postgres reprovision.

**Prevention**: Before committing any new migration, verify with:
```bash
alembic heads
alembic check
```
If `alembic heads` returns more than one head — create a merge migration immediately.

## Migrations That Handle Fresh-DB Gracefully

These migrations are safe to run on a fresh database (important for disaster recovery):

- `zc3d4e5f6g7h8` — uses `CREATE TABLE IF NOT EXISTS`
- `zk3l4m5n6o7p` — uses `ADD COLUMN IF NOT EXISTS`
- `zl4m5n6o7p8q` — uses `CREATE TABLE IF NOT EXISTS`
- `ze1f2g3h4i5j6` — creates new table (always safe on fresh DB)

All other migrations use `add_column` / `create_table` without IF NOT EXISTS guards.
On a fresh DB they will succeed (table is empty, column doesn't exist yet). On a partially
restored DB they may fail if the column already exists from a prior partial migration run.

## No Drop Operations Found

None of the reviewed migrations DROP tables or DROP columns in the `upgrade()` path.
Rollback `downgrade()` paths do drop, but those are not auto-run.

This is the expected safe pattern — no blocking issues found.
