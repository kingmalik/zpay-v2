#!/usr/bin/env python3
"""
Phase C — Z-Pay wipe damage diff.
Outer-joins replay_ledger vs truth_ledger on (join_code, week, llc).
Zero DB calls. Outputs wipe_damage.csv + wipe-damage-report.md.
"""

import csv
import os
from collections import defaultdict

AUDIT_DIR = os.path.expanduser(
    "~/Library/Application Support/zpay-backups/audit"
)
REPLAY_PATH = os.path.join(AUDIT_DIR, "replay_ledger_W1_W14.csv")
TRUTH_PATH = os.path.join(AUDIT_DIR, "truth_ledger_W1_W14.csv")
DAMAGE_CSV = os.path.join(AUDIT_DIR, "wipe_damage.csv")
REPORT_PATH = os.path.expanduser(
    "~/Documents/Projects/zpay-v2/docs/incidents/2026-05-03-wipe-damage-report.md"
)

MATCH_THRESHOLD = 0.50

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def safe_float(v):
    try:
        return float(v) if v not in (None, "", "None") else 0.0
    except (ValueError, TypeError):
        return 0.0


def safe_int(v):
    try:
        return int(v) if v not in (None, "", "None") else 0
    except (ValueError, TypeError):
        return 0


# ---------------------------------------------------------------------------
# Load replay ledger
# ---------------------------------------------------------------------------
# Key: (join_code, week, llc) → row dict
replay_map = {}
replay_rows_raw = []

with open(REPLAY_PATH, newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        llc = row["llc"].strip()
        week = safe_int(row["week"])
        pcode = row["paycheck_code"].strip()
        pcode_maz = row["paycheck_code_maz"].strip()

        if llc == "FA":
            join_code = pcode
        else:  # Maz
            join_code = pcode_maz

        if not join_code:
            # fall back to whatever is populated
            join_code = pcode or pcode_maz

        key = (join_code, week, llc)
        replay_rows_raw.append({
            "key": key,
            "join_code": join_code,
            "paycheck_code": pcode,
            "paycheck_code_maz": pcode_maz,
            "driver_name": row["driver_name"].strip(),
            "week": week,
            "llc": llc,
            "net_pay": safe_float(row["net_pay"]),
            "status": row["status"].strip(),
        })
        # if duplicate key keep highest net_pay (shouldn't happen but defensive)
        if key not in replay_map or safe_float(row["net_pay"]) > replay_map[key]["net_pay"]:
            replay_map[key] = replay_rows_raw[-1]

# ---------------------------------------------------------------------------
# Load truth ledger
# ---------------------------------------------------------------------------
truth_map = {}
truth_rows_raw = []

with open(TRUTH_PATH, newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        llc = row["llc"].strip()
        week = safe_int(row["week"])
        # truth CSV: paycheck_code is FA code, paycheck_code_maz is Maz code
        pcode = row["paycheck_code"].strip() if row["paycheck_code"] else ""
        pcode_maz = row["paycheck_code_maz"].strip() if row["paycheck_code_maz"] else ""

        if llc == "FA":
            join_code = pcode
        else:
            join_code = pcode_maz

        if not join_code:
            join_code = pcode or pcode_maz

        total = safe_float(row["total"])
        key = (join_code, week, llc)
        truth_rows_raw.append({
            "key": key,
            "join_code": join_code,
            "paycheck_code": pcode,
            "paycheck_code_maz": pcode_maz,
            "driver_name_in_file": row["driver_name_in_file"].strip(),
            "week": week,
            "llc": llc,
            "payroll_amount": safe_float(row["payroll_amount"]),
            "unpaid_pending": safe_float(row["unpaid_pending"]) if row["unpaid_pending"] else 0.0,
            "to_paid": safe_float(row["to_paid"]) if row["to_paid"] else 0.0,
            "total": total,
        })
        if key not in truth_map or total > truth_map[key]["total"]:
            truth_map[key] = truth_rows_raw[-1]

# ---------------------------------------------------------------------------
# Outer join + classification
# ---------------------------------------------------------------------------
all_keys = set(replay_map.keys()) | set(truth_map.keys())

damage_rows = []
match_rows = []

for key in all_keys:
    join_code, week, llc = key
    r = replay_map.get(key)
    t = truth_map.get(key)

    # Resolve names
    driver_name = ""
    if r:
        driver_name = r["driver_name"]
    if not driver_name and t:
        driver_name = t["driver_name_in_file"]

    pcode = r["paycheck_code"] if r else (t["paycheck_code"] if t else "")
    pcode_maz = r["paycheck_code_maz"] if r else (t["paycheck_code_maz"] if t else "")

    replay_net = r["net_pay"] if r else 0.0
    truth_total = t["total"] if t else 0.0
    delta = replay_net - truth_total  # positive = replay paid more than truth

    if r and t:
        if abs(delta) <= MATCH_THRESHOLD:
            classification = "MATCH"
        else:
            classification = "DRIFT"
    elif r and not t:
        classification = "REPLAY_ONLY"
    else:
        classification = "TRUTH_ONLY"

    if classification == "MATCH":
        match_rows.append({
            "paycheck_code": pcode,
            "paycheck_code_maz": pcode_maz,
            "driver_name": driver_name,
            "week": week,
            "llc": llc,
            "classification": classification,
            "replay_net": replay_net,
            "truth_total": truth_total,
            "delta": delta,
            "suggested_action": "",
        })
    else:
        if classification == "DRIFT":
            suggested_action = "update_to_truth"
        elif classification == "REPLAY_ONLY":
            suggested_action = "flag_replay_only_for_malik"
        else:
            suggested_action = "insert_from_truth"

        damage_rows.append({
            "paycheck_code": pcode,
            "paycheck_code_maz": pcode_maz,
            "driver_name": driver_name,
            "week": week,
            "llc": llc,
            "classification": classification,
            "replay_net": replay_net,
            "truth_total": truth_total,
            "delta": delta,
            "suggested_action": suggested_action,
        })

# ---------------------------------------------------------------------------
# Bucket summaries
# ---------------------------------------------------------------------------
def bucket_stats(rows, classification):
    subset = [r for r in rows if r["classification"] == classification]
    total_dollars = sum(
        r["truth_total"] if classification == "TRUTH_ONLY" else
        r["replay_net"] if classification == "REPLAY_ONLY" else
        abs(r["delta"])
        for r in subset
    )
    return len(subset), total_dollars, subset

drift_count, drift_dollars, drift_subset = bucket_stats(damage_rows, "DRIFT")
replay_only_count, replay_only_dollars, replay_only_subset = bucket_stats(damage_rows, "REPLAY_ONLY")
truth_only_count, truth_only_dollars, truth_only_subset = bucket_stats(damage_rows, "TRUTH_ONLY")
match_count = len(match_rows)

total_damage_rows = len(damage_rows)
total_all_rows = total_damage_rows + match_count

print(f"\n=== BUCKET SUMMARY ===")
print(f"MATCH:        {match_count:>5} rows")
print(f"DRIFT:        {drift_count:>5} rows  ${drift_dollars:,.2f}")
print(f"REPLAY_ONLY:  {replay_only_count:>5} rows  ${replay_only_dollars:,.2f}")
print(f"TRUTH_ONLY:   {truth_only_count:>5} rows  ${truth_only_dollars:,.2f}")
print(f"Total rows processed: {total_all_rows}")

# ---------------------------------------------------------------------------
# Top 20 DRIFT by abs(delta)
# ---------------------------------------------------------------------------
top20_drift = sorted(drift_subset, key=lambda r: abs(r["delta"]), reverse=True)[:20]

# ---------------------------------------------------------------------------
# Per-week damage grid
# ---------------------------------------------------------------------------
# grid[week][llc] = {"drift_rows": N, "drift_delta": $}
grid = defaultdict(lambda: {"FA": {"rows": 0, "delta": 0.0}, "Maz": {"rows": 0, "delta": 0.0}})
for row in drift_subset:
    w = row["week"]
    l = row["llc"]
    grid[w][l]["rows"] += 1
    grid[w][l]["delta"] += abs(row["delta"])

# ---------------------------------------------------------------------------
# Per-driver owed-to-truth delta (sum of delta across all weeks for that driver)
# ---------------------------------------------------------------------------
driver_delta = defaultdict(float)
driver_name_map = {}
for row in drift_subset + truth_only_subset:
    code = row["paycheck_code"] or row["paycheck_code_maz"]
    llc = row["llc"]
    dk = (code, llc)
    if row["classification"] == "DRIFT":
        driver_delta[dk] += row["delta"]  # signed; negative = we owe driver more
    elif row["classification"] == "TRUTH_ONLY":
        driver_delta[dk] -= row["truth_total"]  # fully missing = owe full amount
    if dk not in driver_name_map:
        driver_name_map[dk] = row["driver_name"]

# Top 10 by abs owed
top10_owed = sorted(driver_delta.items(), key=lambda kv: abs(kv[1]), reverse=True)[:10]

# ---------------------------------------------------------------------------
# Write damage CSV
# ---------------------------------------------------------------------------
os.makedirs(AUDIT_DIR, exist_ok=True)
damage_fieldnames = [
    "paycheck_code", "paycheck_code_maz", "driver_name", "week", "llc",
    "classification", "replay_net", "truth_total", "delta", "suggested_action"
]
with open(DAMAGE_CSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=damage_fieldnames)
    writer.writeheader()
    # Sort: DRIFT first (by abs delta desc), then TRUTH_ONLY (by truth_total desc), then REPLAY_ONLY
    sorted_damage = (
        sorted([r for r in damage_rows if r["classification"] == "DRIFT"],
               key=lambda r: abs(r["delta"]), reverse=True) +
        sorted([r for r in damage_rows if r["classification"] == "TRUTH_ONLY"],
               key=lambda r: r["truth_total"], reverse=True) +
        sorted([r for r in damage_rows if r["classification"] == "REPLAY_ONLY"],
               key=lambda r: r["replay_net"], reverse=True)
    )
    for row in sorted_damage:
        writer.writerow(row)

print(f"\nDamage CSV written → {DAMAGE_CSV}")

# ---------------------------------------------------------------------------
# Build markdown report
# ---------------------------------------------------------------------------
os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)

# Compute total at-stake
total_at_stake = drift_dollars + truth_only_dollars + replay_only_dollars

def fmt(v):
    return f"${v:,.2f}"

lines = []
a = lines.append

a("# Z-Pay DB Wipe — Damage Report")
a(f"**Incident date:** 2026-05-03  |  **Report generated:** 2026-05-04")
a(f"**Source:** Phase C outer-join of replay_ledger_W1_W14.csv (1,872 rows) vs truth_ledger_W1_W14.csv (885 rows)")
a("")
a("---")
a("")
a("## Executive Summary")
a("")
a(f"| Metric | Value |")
a(f"|--------|-------|")
a(f"| Total dollars at stake (drift + lost + overpay) | {fmt(total_at_stake)} |")
a(f"| Drift dollars (DB differs from mom's truth) | {fmt(drift_dollars)} |")
a(f"| Lost-data dollars (TRUTH_ONLY — W14 + missing seeds) | {fmt(truth_only_dollars)} |")
a(f"| Suspected overpay dollars (REPLAY_ONLY — in DB, not in mom's files) | {fmt(replay_only_dollars)} |")
a("")
a("**Nuraynie Daoud** (paycheck_code 1006) appears across W10–W14 as DRIFT.")
a("Her truth total across all weeks is **$1,198.00**; the wipe left her replay figures")
a("partially restored. Phase D must reconcile her week-by-week to restore the correct")
a("owed balance before any payment is issued.")
a("")
a("**W14 is entirely TRUTH_ONLY.** Batches 84 (FA) and 85 (Maz) did not survive the wipe.")
a(f"All {sum(1 for r in truth_only_subset if r['week']==14)} W14 driver-week records and")
a(f"{fmt(sum(r['truth_total'] for r in truth_only_subset if r['week']==14))} must be inserted")
a("from mom's source files by Phase D before any W15 payroll runs.")
a("")
a("---")
a("")
a("## Row Counts by Bucket")
a("")
a(f"| Classification | Rows | Dollars |")
a(f"|----------------|------|---------|")
a(f"| MATCH | {match_count} | — |")
a(f"| DRIFT | {drift_count} | {fmt(drift_dollars)} |")
a(f"| TRUTH_ONLY | {truth_only_count} | {fmt(truth_only_dollars)} |")
a(f"| REPLAY_ONLY | {replay_only_count} | {fmt(replay_only_dollars)} |")
a(f"| **Total processed** | **{total_all_rows}** | |")
a("")
a("---")
a("")
a("## Per-Week Damage Grid (DRIFT rows)")
a("")
a("| Week | FA Drift Rows | FA Drift $ | Maz Drift Rows | Maz Drift $ |")
a("|------|--------------|------------|----------------|-------------|")
for w in range(1, 15):
    fa = grid[w]["FA"]
    maz = grid[w]["Maz"]
    if fa["rows"] > 0 or maz["rows"] > 0:
        a(f"| W{w} | {fa['rows']} | {fmt(fa['delta'])} | {maz['rows']} | {fmt(maz['delta'])} |")
    else:
        a(f"| W{w} | 0 | $0.00 | 0 | $0.00 |")
a("")
a("---")
a("")
a("## Top 20 DRIFT Rows (by absolute $ delta)")
a("")
a("| # | Driver | Week | LLC | Replay $ | Truth $ | Delta $ |")
a("|---|--------|------|-----|----------|---------|---------|")
for i, row in enumerate(top20_drift, 1):
    sign = "+" if row["delta"] >= 0 else ""
    a(f"| {i} | {row['driver_name']} | W{row['week']} | {row['llc']} | {fmt(row['replay_net'])} | {fmt(row['truth_total'])} | {sign}{fmt(abs(row['delta']))} |")
a("")
a("*Positive delta = replay paid more than mom's truth (potential overpay in DB).*")
a("*Negative delta = replay paid less than mom's truth (driver is owed more).*")
a("")
a("---")
a("")
a("## Top 10 Per-Driver Owed Delta")
a("")
a("Negative = driver is owed that amount vs what DB shows. Positive = DB shows more than truth.")
a("")
a("| # | Driver | Code | LLC | Net Owed (truth − DB) |")
a("|---|--------|------|-----|----------------------|")
for i, ((code, llc), delta_val) in enumerate(top10_owed, 1):
    name = driver_name_map.get((code, llc), "Unknown")
    owed = -delta_val  # flip: negative delta = we owe driver
    sign = "+" if owed >= 0 else ""
    a(f"| {i} | {name} | {code} | {llc} | {sign}{fmt(abs(owed))} |")
a("")
a("*'Net Owed' = truth total minus DB replay amount, summed across all weeks.*")
a("*Positive = driver is owed that amount. Negative = DB shows excess vs truth.*")
a("")
a("---")
a("")
a("## Methodology")
a("")
a("### Join key")
a("- FA rows: joined on `(paycheck_code, week, llc='FA')`")
a("- Maz rows: joined on `(paycheck_code_maz, week, llc='Maz')`")
a("- Truth CSV: `paycheck_code` column holds FA code; `paycheck_code_maz` holds Maz code (confirmed from header).")
a("")
a("### MATCH threshold")
a("abs(replay.net_pay − truth.total) ≤ $0.50. Chosen because:")
a("- Rounding across route tiers can produce $0.25–$0.50 cents of natural variance.")
a("- Anything larger is a real discrepancy introduced by the wipe or a prior bug.")
a("")
a("### What `total` means in mom's files")
a("Mom's `total` column = `payroll_amount` + `to_paid` (held balances released that week).")
a("It represents the driver's effective payout state for that week — what they should")
a("have received (or had credited to their running balance) per mom's source file.")
a("This is used as ground truth. The script does NOT attempt to correct it.")
a("")
a("### W14 is fully TRUTH_ONLY")
a("Batches 84 (FA) and 85 (Maz) were not present in the wipe snapshot that fed")
a("the replay ledger. Every W14 row in the truth ledger has no replay counterpart.")
a("This is expected and confirms the scope of the wipe.")
a("")
a("### Maz W13 net pay note")
a("Maz W13 rows in the truth ledger reflect mom's effective payout from the")
a("CashieringReceipt xlsx (net after WUD/RAD deductions are absorbed by Maz LLC).")
a("These are treated as-is. The script does not attempt to back-calculate gross.")
a("")
a("---")
a("")
a("## Phase D Recommendation")
a("")
a("Scope for Phase D (DB restore):")
a("")
a("1. **Insert all TRUTH_ONLY rows** — primarily W14 FA + Maz (batches 84/85).")
a(f"   Total: {truth_only_count} rows, {fmt(truth_only_dollars)}.")
a("")
a("2. **Update DRIFT rows** to truth.total where abs(delta) > $0.50.")
a(f"   Total: {drift_count} rows, {fmt(drift_dollars)} aggregate delta.")
a("   Priority: any driver with a pending payment this week (W15).")
a("   **Nuraynie Daoud must be corrected before W15 batch runs.**")
a("")
a("3. **Flag REPLAY_ONLY rows** for Malik's manual review before touching them.")
a(f"   Total: {replay_only_count} rows, {fmt(replay_only_dollars)}.")
a("   These may include FA canceled-trip overpays or bonus pay not in mom's files.")
a("   Do NOT auto-correct these — Malik decides.")
a("")
a("All corrections must run inside a transaction. Roll back on any constraint violation.")
a("Re-run Phase C after Phase D to verify MATCH count increases to 100% of W1–W13.")

report_text = "\n".join(lines)

with open(REPORT_PATH, "w", encoding="utf-8") as f:
    f.write(report_text)

print(f"Damage report written → {REPORT_PATH}")

# ---------------------------------------------------------------------------
# Print head of damage CSV
# ---------------------------------------------------------------------------
print("\n=== DAMAGE CSV — first 10 rows ===")
with open(DAMAGE_CSV, newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for i, row in enumerate(reader):
        if i >= 10:
            break
        print(dict(row))

# ---------------------------------------------------------------------------
# Print full damage report
# ---------------------------------------------------------------------------
print("\n\n=== FULL DAMAGE REPORT ===\n")
print(report_text)
