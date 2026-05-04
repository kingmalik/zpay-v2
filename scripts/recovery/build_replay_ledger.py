#!/usr/bin/env python3
"""
W1–W14 Replay Ledger — pure read from prod DB.
Writes:
  ~/Library/Application Support/zpay-backups/audit/replay_ledger_W1_W14.csv
  ~/Library/Application Support/zpay-backups/audit/replay_summary.md
"""

import os
import csv
import sys
from pathlib import Path
from collections import defaultdict

import psycopg2
import psycopg2.extras

PARTIAL = False

# Public proxy — confirmed working 2026-05-01
DATABASE_URL = "postgresql://app:zpay_secret_2026@junction.proxy.rlwy.net:38477/appdb"
print(f"Connecting to: {DATABASE_URL[:60]}...")

AUDIT_DIR = Path.home() / "Library/Application Support/zpay-backups/audit"
AUDIT_DIR.mkdir(parents=True, exist_ok=True)
CSV_PATH = AUDIT_DIR / "replay_ledger_W1_W14.csv"
SUMMARY_PATH = AUDIT_DIR / "replay_summary.md"

# W15 batch to exclude
EXCLUDE_BATCH_ID = 73


def new_cursor(conn):
    """Fresh dict cursor — each query in its own try block, no transaction bleed."""
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


conn = psycopg2.connect(DATABASE_URL)
conn.set_session(readonly=True, autocommit=False)
print("Connected to prod DB (read-only).")

# ── 1. Discover week boundaries ──────────────────────────────────────────────
batches = []
try:
    cur = new_cursor(conn)
    cur.execute("""
        SELECT payroll_batch_id, source, period_start, period_end, status
        FROM payroll_batch
        WHERE payroll_batch_id != %s
        ORDER BY period_start, source
    """, (EXCLUDE_BATCH_ID,))
    batches = cur.fetchall()
    cur.close()
    print(f"Found {len(batches)} batches (excluding batch {EXCLUDE_BATCH_ID})")
    for b in batches:
        print(f"  batch {b['payroll_batch_id']:>3} | {b['source']:>10} | {b['period_start']} → {b['period_end']} | {b['status']}")
except Exception as e:
    print(f"FATAL: batch query failed: {e}", file=sys.stderr)
    PARTIAL = True

# Classify batches by LLC
fa_sources = {"firstalt", "fa", "acumen"}
maz_sources = {"maz", "everdrive", "everdriven", "ed"}

fa_batches = [b for b in batches if b["source"] in fa_sources]
maz_batches = [b for b in batches if b["source"] in maz_sources]
other_batches = [b for b in batches if b["source"] not in fa_sources and b["source"] not in maz_sources]

if other_batches:
    print(f"Unknown sources: {set(b['source'] for b in other_batches)}")

print(f"FA batches: {len(fa_batches)}, Maz batches: {len(maz_batches)}")


def assign_week_numbers(batch_list):
    if not batch_list:
        return {}
    sorted_b = sorted(batch_list, key=lambda b: b["period_start"])
    anchor = sorted_b[0]["period_start"]
    mapping = {}
    seen_starts = sorted(set(x["period_start"] for x in sorted_b))
    for b in sorted_b:
        delta = (b["period_start"] - anchor).days
        if delta % 7 == 0:
            week_num = delta // 7 + 1
        else:
            # Ordinal fallback
            week_num = seen_starts.index(b["period_start"]) + 1
        mapping[b["payroll_batch_id"]] = week_num
    return mapping


fa_week_map = assign_week_numbers(fa_batches)
maz_week_map = assign_week_numbers(maz_batches)

if fa_batches:
    fa_anchor = sorted(fa_batches, key=lambda b: b["period_start"])[0]["period_start"]
    print(f"FA W1 anchor: {fa_anchor}")
if maz_batches:
    maz_anchor = sorted(maz_batches, key=lambda b: b["period_start"])[0]["period_start"]
    print(f"Maz W1 anchor: {maz_anchor}")

# Build batch_meta index
batch_meta = {}
for b in fa_batches:
    batch_meta[b["payroll_batch_id"]] = {
        "week": fa_week_map.get(b["payroll_batch_id"], 0),
        "llc": "FA",
        "source": b["source"],
        "period_start": b["period_start"],
    }
for b in maz_batches:
    batch_meta[b["payroll_batch_id"]] = {
        "week": maz_week_map.get(b["payroll_batch_id"], 0),
        "llc": "Maz",
        "source": b["source"],
        "period_start": b["period_start"],
    }

print(f"FA weeks assigned: {sorted(set(v['week'] for v in batch_meta.values() if v['llc']=='FA'))}")
print(f"Maz weeks assigned: {sorted(set(v['week'] for v in batch_meta.values() if v['llc']=='Maz'))}")

# ── 2. Person lookup ─────────────────────────────────────────────────────────
persons = []
try:
    cur = new_cursor(conn)
    cur.execute("""
        SELECT person_id, full_name, paycheck_code, paycheck_code_maz, active
        FROM person
        ORDER BY full_name
    """)
    persons = cur.fetchall()
    cur.close()
    print(f"Found {len(persons)} persons total")
except Exception as e:
    print(f"WARN: person query failed: {e}", file=sys.stderr)
    PARTIAL = True

person_map = {p["person_id"]: p for p in persons}

# Active persons with at least one code
coded_fa = set(p["person_id"] for p in persons if p["paycheck_code"] is not None)
coded_maz = set(p["person_id"] for p in persons if p["paycheck_code_maz"] is not None)
print(f"Persons with FA code: {len(coded_fa)}, Maz code: {len(coded_maz)}")

# ── 3. Rides aggregated per (person_id, batch_id) ───────────────────────────
ride_aggs = []
try:
    cur = new_cursor(conn)
    cur.execute("""
        SELECT
            r.person_id,
            r.payroll_batch_id,
            SUM(r.z_rate)    AS gross_pay,
            SUM(r.net_pay)   AS net_pay,
            COUNT(*)         AS ride_count
        FROM ride r
        WHERE r.payroll_batch_id IS NOT NULL
          AND r.payroll_batch_id != %s
        GROUP BY r.person_id, r.payroll_batch_id
    """, (EXCLUDE_BATCH_ID,))
    ride_aggs = cur.fetchall()
    cur.close()
    print(f"Got {len(ride_aggs)} (person, batch) ride aggregates")
except Exception as e:
    print(f"WARN: ride agg query failed: {e}", file=sys.stderr)
    PARTIAL = True

# Index: (person_id, batch_id) -> agg row
ride_index = {}
for r in ride_aggs:
    ride_index[(r["person_id"], r["payroll_batch_id"])] = r

# ── 4. Driver balances (carryover) ──────────────────────────────────────────
balances = []
try:
    cur = new_cursor(conn)
    cur.execute("""
        SELECT person_id, payroll_batch_id, carried_over
        FROM driver_balance
        WHERE payroll_batch_id != %s
    """, (EXCLUDE_BATCH_ID,))
    balances = cur.fetchall()
    cur.close()
    print(f"Got {len(balances)} driver_balance rows")
except Exception as e:
    print(f"WARN: driver_balance query failed: {e}", file=sys.stderr)
    PARTIAL = True

# Index: (person_id, batch_id) -> carried_over float
balance_map = {}
for b in balances:
    balance_map[(b["person_id"], b["payroll_batch_id"])] = float(b["carried_over"] or 0)

# ── 5. Build per-person per-week-per-LLC records ─────────────────────────────
fa_batch_order = sorted(
    [bid for bid, m in batch_meta.items() if m["llc"] == "FA"],
    key=lambda bid: batch_meta[bid]["period_start"]
)
maz_batch_order = sorted(
    [bid for bid, m in batch_meta.items() if m["llc"] == "Maz"],
    key=lambda bid: batch_meta[bid]["period_start"]
)

rows = []


def process_batches(batch_order, llc, coded_set):
    for i, batch_id in enumerate(batch_order):
        meta = batch_meta[batch_id]
        week = meta["week"]

        # All persons with rides this batch
        persons_in_batch = {pid for (pid, bid) in ride_index if bid == batch_id}
        # Union coded persons (to catch MISSING)
        all_persons = persons_in_batch | coded_set

        for pid in sorted(all_persons):
            person = person_map.get(pid)

            agg = ride_index.get((pid, batch_id))
            gross = float(agg["gross_pay"] or 0) if agg else 0.0
            net = float(agg["net_pay"] or 0) if agg else 0.0
            ride_count = int(agg["ride_count"] or 0) if agg else 0
            withheld = max(0.0, gross - net)

            # carryover_out = balance carried from THIS batch
            carryover_out = balance_map.get((pid, batch_id), 0.0)

            # carryover_in = balance carried out of PRIOR batch (same LLC)
            carryover_in = 0.0
            if i > 0:
                prior_batch_id = batch_order[i - 1]
                carryover_in = balance_map.get((pid, prior_batch_id), 0.0)

            # Status logic
            if ride_count == 0:
                if pid in coded_set:
                    status = "MISSING"
                else:
                    continue  # no rides, no code — skip
            elif net > 0 and withheld > 0:
                status = "MIXED"
            elif net > 0:
                status = "PAID"
            elif withheld > 0 or (gross > 0 and net == 0):
                status = "HELD"
            else:
                # Rides exist but both gross and net are 0 (e.g. canceled with $0)
                status = "HELD"

            name = person["full_name"] if person else "UNKNOWN"
            code_fa = person["paycheck_code"] if person else None
            code_maz = person["paycheck_code_maz"] if person else None

            rows.append({
                "person_id": pid,
                "driver_name": name,
                "paycheck_code": code_fa or "",
                "paycheck_code_maz": code_maz or "",
                "week": week,
                "llc": llc,
                "gross_pay": round(gross, 2),
                "net_pay": round(net, 2),
                "withheld_amount": round(withheld, 2),
                "carryover_in": round(carryover_in, 2),
                "carryover_out": round(carryover_out, 2),
                "ride_count": ride_count,
                "status": status,
                "source_batch_id": batch_id,
            })


process_batches(fa_batch_order, "FA", coded_fa)
process_batches(maz_batch_order, "Maz", coded_maz)

print(f"Built {len(rows)} ledger rows")

# ── 6. Write CSV ─────────────────────────────────────────────────────────────
FIELDNAMES = [
    "person_id", "driver_name", "paycheck_code", "paycheck_code_maz",
    "week", "llc", "gross_pay", "net_pay", "withheld_amount",
    "carryover_in", "carryover_out", "ride_count", "status", "source_batch_id"
]

with open(CSV_PATH, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
    writer.writeheader()
    writer.writerows(rows)

print(f"CSV written: {CSV_PATH} ({len(rows)} rows)")

# ── 7. Summary stats ──────────────────────────────────────────────────────────
total_net = sum(r["net_pay"] for r in rows)
total_gross = sum(r["gross_pay"] for r in rows)

# Per-week ride count grid
grid_rides = defaultdict(lambda: defaultdict(int))
grid_net = defaultdict(lambda: defaultdict(float))
for r in rows:
    grid_rides[r["week"]][r["llc"]] += r["ride_count"]
    grid_net[r["week"]][r["llc"]] += r["net_pay"]

all_weeks = sorted(set(r["week"] for r in rows))
all_llcs = ["FA", "Maz"]

# Per-driver: set of weeks with rides per LLC
fa_weeks_per_driver = defaultdict(set)
maz_weeks_per_driver = defaultdict(set)
for r in rows:
    if r["status"] not in ("MISSING",):
        if r["llc"] == "FA":
            fa_weeks_per_driver[r["person_id"]].add(r["week"])
        else:
            maz_weeks_per_driver[r["person_id"]].add(r["week"])

max_fa_week = max((v["week"] for v in batch_meta.values() if v["llc"] == "FA"), default=0)
max_maz_week = max((v["week"] for v in batch_meta.values() if v["llc"] == "Maz"), default=0)

full_fa_drivers = [pid for pid, wks in fa_weeks_per_driver.items() if len(wks) >= max_fa_week]
full_maz_drivers = [pid for pid, wks in maz_weeks_per_driver.items() if len(wks) >= max_maz_week]

partial_fa = sorted(
    [(pid, sorted(wks)) for pid, wks in fa_weeks_per_driver.items() if 0 < len(wks) < max_fa_week],
    key=lambda x: x[0]
)
partial_maz = sorted(
    [(pid, sorted(wks)) for pid, wks in maz_weeks_per_driver.items() if 0 < len(wks) < max_maz_week],
    key=lambda x: x[0]
)

# Drivers with code but zero rides ever
zero_rides_fa = [p for p in persons if p["paycheck_code"] and p["person_id"] not in fa_weeks_per_driver]
zero_rides_maz = [p for p in persons if p["paycheck_code_maz"] and p["person_id"] not in maz_weeks_per_driver]

# Top 10 by net pay
driver_totals = defaultdict(float)
driver_status_grid = defaultdict(dict)  # [pid][llc_Wn] = status initial
for r in rows:
    driver_totals[r["person_id"]] += r["net_pay"]
    key = f"{r['llc']}_W{r['week']:02d}"
    existing = driver_status_grid[r["person_id"]].get(key, "-")
    # Merge: PAID > MIXED > HELD > MISSING > -
    rank = {"PAID": 5, "MIXED": 4, "HELD": 3, "MISSING": 2, "-": 1}
    new_s = r["status"]
    if rank.get(new_s, 0) > rank.get(existing, 0):
        driver_status_grid[r["person_id"]][key] = new_s

top10 = sorted(driver_totals.items(), key=lambda x: -x[1])[:10]

# Build week column headers
fa_wcols = [f"FA_W{w:02d}" for w in sorted(set(r["week"] for r in rows if r["llc"] == "FA"))]
maz_wcols = [f"Maz_W{w:02d}" for w in sorted(set(r["week"] for r in rows if r["llc"] == "Maz"))]
all_wcols = fa_wcols + maz_wcols

status_abbrev = {"PAID": "P", "HELD": "H", "MIXED": "M", "MISSING": "X", "-": "-"}

# ── 8. Write summary.md ───────────────────────────────────────────────────────
partial_header = "# PARTIAL\n\n" if PARTIAL else ""

with open(SUMMARY_PATH, "w") as f:
    f.write(f"{partial_header}# Z-Pay W1–W14 Replay Ledger Summary\n")
    f.write(f"Generated: 2026-05-04 | Excludes batch {EXCLUDE_BATCH_ID} (W15 in-flight)\n\n")

    f.write(f"## Totals\n")
    f.write(f"- Ledger rows: {len(rows):,}\n")
    f.write(f"- Total gross (z_rate): ${total_gross:,.2f}\n")
    f.write(f"- Total net paid: ${total_net:,.2f}\n")
    f.write(f"- Total withheld: ${total_gross - total_net:,.2f}\n")
    f.write(f"- FA batches: {len(fa_batches)} (W1–W{max_fa_week})\n")
    f.write(f"- Maz batches: {len(maz_batches)} (W1–W{max_maz_week})\n\n")

    f.write(f"## Week x LLC Ride Count Grid\n\n")
    f.write(f"| Week | FA rides | Maz rides | Total rides | FA net $ | Maz net $ |\n")
    f.write(f"|------|----------|-----------|-------------|----------|----------|\n")
    for w in all_weeks:
        fa_r = grid_rides[w]["FA"]
        maz_r = grid_rides[w]["Maz"]
        fa_n = grid_net[w]["FA"]
        maz_n = grid_net[w]["Maz"]
        f.write(f"| W{w:02d} | {fa_r:>8} | {maz_r:>9} | {fa_r+maz_r:>11} | ${fa_n:>8,.0f} | ${maz_n:>8,.0f} |\n")
    # Totals
    fa_tr = sum(grid_rides[w]["FA"] for w in all_weeks)
    maz_tr = sum(grid_rides[w]["Maz"] for w in all_weeks)
    fa_tn = sum(grid_net[w]["FA"] for w in all_weeks)
    maz_tn = sum(grid_net[w]["Maz"] for w in all_weeks)
    f.write(f"| **Total** | **{fa_tr}** | **{maz_tr}** | **{fa_tr+maz_tr}** | **${fa_tn:,.0f}** | **${maz_tn:,.0f}** |\n\n")

    f.write(f"## Driver History Coverage\n")
    f.write(f"- FA: {len(full_fa_drivers)} drivers with all {max_fa_week} weeks, {len(partial_fa)} with partial history\n")
    f.write(f"- Maz: {len(full_maz_drivers)} drivers with all {max_maz_week} weeks, {len(partial_maz)} with partial history\n\n")

    if partial_fa:
        f.write(f"### Partial FA History (drove some but not all {max_fa_week} weeks)\n")
        for pid, wks in partial_fa:
            p = person_map.get(pid, {})
            name = p.get("full_name", "UNKNOWN") if p else "UNKNOWN"
            missing = sorted(set(range(1, max_fa_week + 1)) - set(wks))
            f.write(f"- {name} (pid={pid}, code={p.get('paycheck_code','?')}): drove W{wks}, missing W{missing}\n")
        f.write("\n")

    if partial_maz:
        f.write(f"### Partial Maz History (drove some but not all {max_maz_week} weeks)\n")
        for pid, wks in partial_maz:
            p = person_map.get(pid, {})
            name = p.get("full_name", "UNKNOWN") if p else "UNKNOWN"
            missing = sorted(set(range(1, max_maz_week + 1)) - set(wks))
            f.write(f"- {name} (pid={pid}, code_maz={p.get('paycheck_code_maz','?')}): drove W{wks}, missing W{missing}\n")
        f.write("\n")

    f.write(f"## Drivers With Paychex Code But Zero Rides\n")
    f.write(f"(Registered in system, never appear in any batch W1–W{max(max_fa_week, max_maz_week)})\n\n")
    f.write(f"### FA (paycheck_code set, 0 rides in any FA batch)\n")
    if zero_rides_fa:
        for p in zero_rides_fa:
            f.write(f"- {p['full_name']} (pid={p['person_id']}, code={p['paycheck_code']}, active={p['active']})\n")
    else:
        f.write("- None\n")
    f.write(f"\n### Maz (paycheck_code_maz set, 0 rides in any Maz batch)\n")
    if zero_rides_maz:
        for p in zero_rides_maz:
            f.write(f"- {p['full_name']} (pid={p['person_id']}, code_maz={p['paycheck_code_maz']}, active={p['active']})\n")
    else:
        f.write("- None\n")
    f.write("\n")

    f.write(f"## Top 10 Drivers by Total Net Pay (W1–W{max(max_fa_week, max_maz_week)})\n\n")
    f.write(f"Key: P=PAID H=HELD M=MIXED X=MISSING -=no rides that week\n\n")
    col_header = " | ".join(all_wcols)
    f.write(f"| Driver | Total Net | {col_header} |\n")
    sep = "|--------|-----------|" + "---|" * len(all_wcols) + "\n"
    f.write(sep)
    for pid, total in top10:
        p = person_map.get(pid, {})
        name = p.get("full_name", "UNKNOWN") if p else "UNKNOWN"
        sgrid = driver_status_grid[pid]
        cols = [status_abbrev.get(sgrid.get(wc, "-"), "-") for wc in all_wcols]
        f.write(f"| {name} | ${total:>9,.2f} | " + " | ".join(cols) + " |\n")
    f.write("\n")

print(f"Summary written: {SUMMARY_PATH}")

# ── 9. Close ──────────────────────────────────────────────────────────────────
conn.close()
print("DB connection closed (read-only, no writes made).")
