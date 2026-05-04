# Z-Pay Disaster Recovery Runbook

**Last updated:** 2026-05-03
**Author:** Automated overnight recovery session (post-wipe)

## When to use this doc

The Railway Postgres was wiped once (2026-05-03, ~09:25 AM PDT, ~6-hour silent outage).
Use this runbook any time the backend has lost data.

**First: confirm the incident.** Check these:
1. Go to https://zpay-v2-production.up.railway.app/snapshot/status — if `live_ride_count` is 0, you have a wipe.
2. Check Railway dashboard → Postgres service → was it reprovisioned?
3. Check Discord — the boot guard (added 2026-05-03) will fire an alert when it detects empty DB.

---

## Restore Tiers (in order — try 1 first, escalate down only if needed)

### Tier 1: Backblaze B2 Hourly SQL Dump

**RPO:** 1 hour | **RTO:** ~5 minutes | **Confidence:** High

**When:** `BACKUP_CRON_ENABLED=1` was set and at least 1 hourly backup completed.

```bash
# List available backups
# Install b2 CLI: pip install b2sdk
python3 -c "
from b2sdk.v2 import InMemoryAccountInfo, B2Api
import os
info = InMemoryAccountInfo()
api = B2Api(info)
api.authorize_account('production', os.environ['BACKBLAZE_KEY_ID'], os.environ['BACKBLAZE_APP_KEY'])
bucket = api.get_bucket_by_name(os.environ['BACKBLAZE_BUCKET'])
for f in bucket.ls('zpay-backups/sql/', latest_only=False):
    print(f[0].file_name, f[0].upload_timestamp)
"

# Restore the most recent backup (replace the filename):
python3 scripts/restore_from_vault.py \
    --source "b2://zpay-backups/zpay-backups/sql/20260503T012345Z.sql.gz.gpg" \
    --target "$DATABASE_URL_PUBLIC" \
    --dry-run    # remove --dry-run when ready

# After restore: set ALLOW_EMPTY_DB=1 temporarily so boot guard doesn't block,
# then set it back to 0 after verifying row counts.
```

**Verification:**
```bash
python3 scripts/restore_from_vault.py \
    --source "b2://zpay-backups/..." \
    --target "postgresql://app:pass@junction.proxy.rlwy.net:38477/appdb"
# Script exits 0 if person >= 200, payroll_batch >= 20, ride >= 1000
```

---

### Tier 2: Mac-Mirrored Daily CSV Exports

**RPO:** 24 hours | **RTO:** ~30 minutes | **Confidence:** Medium-High

**When:** B2 is unavailable or hourly backup didn't run. CSV exports ran at 03:05 UTC daily.

Files at: `/data/out/backups/csv/YYYY-MM-DD/` (on Railway) or via B2 at `zpay-backups/csv/`.

**Restore process:**
```bash
# Download CSV from Railway (if local disk wasn't wiped):
# SSH or Railway exec into service, grab the files

# Then use the existing CSV import endpoints:
# 1. People:  POST /people/audit/import-csv
# 2. Rates:   POST /admin_rates/import-csv
# 3. Rides:   POST /upload/ (FA xlsx or ED PDF — not CSV direct, needs re-ingest from source files)

# For payroll batches and balances: manual SQL insert from CSVs
# (Scripts: scripts/emergency_seed_path_a.py as reference for approach)
```

---

### Tier 3: Mom's Vaulted Weekly Files

**RPO:** 7 days (last payroll cycle) | **RTO:** ~2 hours | **Confidence:** Medium

**When:** Only the current week's state needs to be rebuilt. Good for "mom needs to run W15 now."

Files auto-vaulted to: `~/Library/Application Support/zpay-backups/moms-weekly/`

```bash
# List vaulted files:
ls -lah "~/Library/Application Support/zpay-backups/moms-weekly/"

# The vault contains:
# - W14_FA_Master_Payroll.xlsx (mom's output — driver pay for W14)
# - W14_Acumen_SPI.csv
# - W14_Maz_SPI.csv
# - W15 files once mom runs them (auto-vaulted within 60 seconds)

# These are OUTPUT files — they tell you what was paid, not the raw ride data.
# Use them to verify payroll amounts, not to re-import rides.
```

**What you CAN rebuild from these files:**
- Driver payment history for the vaulted week
- Which drivers were on which batch
- Total partner pay

**What you CANNOT rebuild from these files:**
- Individual ride trip codes
- Driver dispatch history (times, status, etc.)
- Exact ride-level margin data

---

### Tier 4: Drive Partner-Source Files + Manual Re-ingest

**RPO:** Full history (W1–W17+) | **RTO:** ~4–6 hours | **Confidence:** High (but slow)

**When:** Complete rebuild needed. This was the path used on 2026-05-03.

Google Drive files at:
`~/Library/CloudStorage/GoogleDrive-milionmalik@gmail.com/.shortcut-targets-by-id/<id>/Wheels of Unity/Payroll/`
- `Acumen/2026/Week N/` — FA Excel files (`Prod_SP_Acumen International_*.xlsx`)
- `Maz/2026/Week N/` — ED PDF files (`CashieringReceipt-*.pdf`)

**Rebuild process:**

Step 1: Check which weeks have files:
```bash
python3 scripts/scan_drive_archive.py
```

Step 2: Set `ALLOW_EMPTY_DB=1` in Railway so backend will start on empty DB.

Step 3: Run migrations first:
```bash
# Via Railway exec or railway run:
alembic upgrade head
```

Step 4: Re-ingest FA files (W1 → W17):
```
For each week:
  1. Go to /upload in the Z-Pay app
  2. Upload the FA Excel file under "Acumen" tab
  3. Go to /payroll → select the created batch → review → finalize
```

Step 5: Re-ingest ED files similarly.

Step 6: Apply manual adjustments (from ~/Downloads/_recon/zpay_driver_weekly.csv if available).

Step 7: Set `ALLOW_EMPTY_DB=0` (or unset) after row counts are healthy.

Step 8: Run post-restore sanity:
```bash
PGPASSWORD=zpay_secret_2026 psql \
  -h junction.proxy.rlwy.net -p 38477 -U app appdb \
  -c "SELECT COUNT(*) FROM ride; SELECT COUNT(*) FROM person; SELECT COUNT(*) FROM payroll_batch;"
# Expect: ride ~7000+, person ~226+, payroll_batch ~26+
```

---

## Post-Restore Checklist

```
[ ] Boot guard passed (no CRITICAL in Railway logs)
[ ] ride COUNT >= what was there before
[ ] person COUNT >= 226
[ ] payroll_batch COUNT >= 26
[ ] driver_balance rows match known balances (check Nuraynie = $332.50 post-wipe baseline)
[ ] /workflow page loads without errors
[ ] /dispatch/reliability page loads
[ ] Set ALLOW_EMPTY_DB back to 0 (or unset)
[ ] Disable BACKUP_CRON_ENABLED during restore, re-enable after
[ ] Post Discord confirmation: "Z-Pay restored. Row counts: rides=X, drivers=Y, batches=Z"
```

---

## Important Context

**Nuraynie balance post-wipe:** $332.50. Pre-wipe was ~$1,595. $1,263 permanently lost.
If you see Nuraynie's balance > $332.50 in a fresh restore without a manual adjustment — something is wrong.

**Railway TCP proxy for direct Postgres access:**
```
Host: junction.proxy.rlwy.net
Port: 38477
User: app
Password: zpay_secret_2026
DB: appdb
```

**Manual encrypted backup location (2026-05-03 post-recovery):**
`~/Library/Application Support/zpay-backups/manual/2026-05-03_post-recovery.sql.gpg`
Passphrase in macOS Keychain: service name `zpay-backup-gpg-2026-05-03`, account `malik`.
Retrieve with: `security find-generic-password -s zpay-backup-gpg-2026-05-03 -w`

---

## Scripts Reference

| Script | Purpose |
|---|---|
| `scripts/restore_from_vault.py` | One-command restore from local or B2 backup |
| `scripts/scan_drive_archive.py` | Check which weeks have FA/Maz source files on Drive |
| `scripts/emergency_seed_path_a.py` | Reference: how the 2026-05-03 restore was done (FA path) |
| `scripts/emergency_seed_path_b*.py` | Reference: ED + contacts + balances restore |

---

## Tabletop Test Procedure (Malik runs when he has time)

To validate this runbook works end-to-end:
1. Create a scratch Postgres: `createdb zpay_scratch`
2. Run: `python3 scripts/restore_from_vault.py --source <latest B2 path> --target postgresql://localhost/zpay_scratch`
3. Verify: script exits 0, row counts pass
4. Time it: should be < 5 minutes for Tier 1
5. Document time in this file

Last tabletop test: NOT YET RUN
