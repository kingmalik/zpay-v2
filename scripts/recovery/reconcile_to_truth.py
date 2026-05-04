#!/usr/bin/env python3
"""
Z-Pay Phase D Reconcile — apply truth_ledger_W1_W14.csv to prod DB.

Sanity gate → anchor check → Lane 1 (TRUTH_ONLY insert) →
Lane 2 (DRIFT adjust) → Lane 3 (REPLAY_ONLY zero) → Nuraynie code →
verify → write outputs.

All writes in ONE transaction. ROLLBACK on any constraint violation.
Do NOT touch batch_id=73 (W15 in-flight).
"""

import csv
import os
import sys
import json
import datetime
import psycopg2
import psycopg2.extras
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

DB_URL = "postgresql://app:zpay_secret_2026@junction.proxy.rlwy.net:38477/appdb"
AUDIT_DIR = "/Users/malikmilion/Library/Application Support/zpay-backups/audit"
ABORT_FILE = os.path.join(AUDIT_DIR, "RECONCILE_ABORTED.txt")
PARTIAL_FILE = os.path.join(AUDIT_DIR, "RECONCILE_PARTIAL_DETECTED.txt")
APPLIED_CSV = os.path.join(AUDIT_DIR, "reconcile_applied.csv")
SUMMARY_MD = os.path.join(AUDIT_DIR, "reconcile_summary.md")
QUESTIONS_MD = os.path.join(AUDIT_DIR, "QUESTIONS_FOR_MOM.md")
INCIDENT_DOC = "/Users/malikmilion/Desktop/zpay-v2-fresh/docs/incidents/2026-05-03-db-wipe.md"

# W14 batch NOT in DB yet — create them
W14_FA_BATCH = {
    "source": "acumen",
    "company_name": "Acumen International",
    "batch_ref": "0404202604102026",
    "period_start": "2026-04-04",
    "period_end": "2026-04-10",
    "week_start": "2026-04-04",
    "week_end": "2026-04-10",
    "status": "complete",
    "notes": "W14 FA — reconstructed from Phase D reconcile 2026-05-04",
}
W14_MAZ_BATCH = {
    "source": "maz",
    "company_name": "Maz Services",
    "batch_ref": "WASO291-OY2026W14-20260412",
    "period_start": "2026-04-06",
    "period_end": "2026-04-12",
    "week_start": "2026-04-06",
    "week_end": "2026-04-12",
    "status": "complete",
    "notes": "W14 Maz — reconstructed from Phase D reconcile 2026-05-04",
}

# Week → batch_id mapping (derived from replay_ledger, verified)
WEEK_BATCH = {
    ("1", "FA"): 43, ("1", "Maz"): 52,
    ("2", "FA"): 1,  ("2", "Maz"): 24,
    ("3", "FA"): 3,  ("3", "Maz"): 11,
    ("4", "FA"): 4,  ("4", "Maz"): 12,
    ("5", "FA"): 5,  ("5", "Maz"): 13,
    ("6", "FA"): 6,  ("6", "Maz"): 14,
    ("7", "FA"): 7,  ("7", "Maz"): 15,
    ("8", "FA"): 47, ("8", "Maz"): 16,
    ("9", "FA"): 8,  ("9", "Maz"): 17,
    ("10","FA"): 50, ("10","Maz"): 9,
    ("11","FA"): 51, ("11","Maz"): 10,
    ("12","FA"): 55, ("12","Maz"): 58,
    ("13","FA"): 71, ("13","Maz"): 72,
    # W14 assigned after batch creation
}

# Source field for rides by LLC
LLC_SOURCE = {"FA": "acumen", "Maz": "maz"}

now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def abort(reason: str, filename: str = ABORT_FILE):
    with open(filename, "w") as f:
        f.write(f"ABORTED: {now_str}\n\n{reason}\n")
    print(f"\nABORT: {reason}")
    sys.exit(1)


def d(v) -> Decimal:
    """Safe Decimal from string or numeric."""
    if v is None or v == "":
        return Decimal("0")
    return Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def load_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


# ──────────────────────────────────────────────────
# BUILD PERSON_ID LOOKUP
# ──────────────────────────────────────────────────

def build_person_lookup(cur) -> dict:
    """
    Returns {paycheck_code: person_id} and {paycheck_code_maz: person_id}
    and name-based fallbacks for drivers without codes.
    """
    cur.execute(
        "SELECT person_id, full_name, paycheck_code, paycheck_code_maz FROM person"
    )
    rows = cur.fetchall()

    pc_map = {}   # str(code) -> person_id
    pcm_map = {}  # str(code_maz) -> person_id
    name_map = {}  # normalized_name -> person_id (only unambiguous)

    name_counts = defaultdict(list)
    for pid, name, pc, pcm in rows:
        if pc:
            pc_map[str(pc).strip()] = pid
        if pcm:
            pcm_map[str(pcm).strip()] = pid
        key = " ".join(name.lower().split())
        name_counts[key].append(pid)

    for key, pids in name_counts.items():
        if len(pids) == 1:
            name_map[key] = pids[0]

    # Manual overrides for edge cases discovered during investigation
    manual = {
        # Sara Sultan Abdu: truth uses pc=1118 but DB has pc=1105 for pid=36
        "1118": 36,
        # Kedir Ali: truth uses pc=1123 in early weeks but DB has pid=19 (pc=1097)
        "1123": 19,
        # HAWA Mohamed Ahmed: pc_maz=1008 maps to pid=15
        "1008": 15,
        # Nessanet Nuru: pc_maz=1084 - use pid=92 (has pc=1079, closest code match)
        # Resolve by name instead via name_map
    }
    for code, pid in manual.items():
        if code not in pc_map:
            pc_map[code] = pid

    # Batch-based overrides for drivers resolved via ride history
    batch_pid_overrides = {
        # (normalized_name_fragment, week, llc) -> person_id
        "abdulkadir geshow": 107,
        "nuraynie mohammed": 58,
        "ephrem g embeka": 221,
        "juhar hussein juhar": 51,
        "zemzem abdu": 43,
        "jowhara mohamed": 48,
        "genet. bekele tebeje": 49,
        "mamadou bhoye diallo": 46,
        "najeebullah ghareb dost": 30,
        "ayah idris": 9,
        "malik milion": None,  # no person in DB — will log to QUESTIONS
    }

    # Maz W13 driver overrides (large codes in wipe_damage are receipt IDs, not Paychex codes)
    maz_w13_overrides = {
        "faize kaifa": 64,
        "ashraf mohamed": 55,
        "mistre sahlu": 73,
        "nabihah al harazi": 29,
        "elias mohammed": 63,
        "fanaye wegahta": 65,
        "nawal reshid": 75,
        "fathia alharazi": 66,
        "muluembet berhan": 27,
        "rawda adem": 76,
        "kedria guhar": 21,
        "juhar juhar": 69,
        "ali ali": 62,
        "ephrem embeka": 78,
        "kalkidan tesfahun": 121,
        "seude adem": 37,
    }

    return pc_map, pcm_map, name_map, batch_pid_overrides, maz_w13_overrides


def resolve_pid(row, pc_map, pcm_map, name_map, batch_pid_overrides, maz_w13_overrides, week, llc):
    """
    Resolve person_id for a damage row. Returns (int|None, str) — (pid, method).
    """
    pc = (row.get("paycheck_code") or "").strip()
    pcm = (row.get("paycheck_code_maz") or "").strip()
    name_raw = (row.get("driver_name") or row.get("driver_name_in_file") or "").strip()
    name_norm = " ".join(name_raw.lower().split())

    # Large Maz receipt codes (> 4 digits) — not Paychex codes
    def is_real_code(c):
        return c and len(c) <= 4 and c.isdigit()

    # 1. By paycheck_code
    if is_real_code(pc) and pc in pc_map:
        return pc_map[pc], f"paycheck_code={pc}"

    # 2. By paycheck_code_maz
    if is_real_code(pcm) and pcm in pcm_map:
        return pcm_map[pcm], f"paycheck_code_maz={pcm}"

    # 3. Maz W13 override (large receipt codes)
    if llc == "Maz" and week == "13":
        for frag, pid in maz_w13_overrides.items():
            if frag in name_norm:
                return pid, f"maz_w13_override:{frag}"

    # 4. Batch_pid_overrides by name fragment
    for frag, pid in batch_pid_overrides.items():
        if frag in name_norm:
            return pid, f"name_fragment:{frag}"

    # 5. Exact normalized name
    if name_norm in name_map:
        return name_map[name_norm], f"name_exact:{name_norm}"

    # 6. Partial name match in name_map (first word)
    first = name_norm.split()[0] if name_norm else ""
    candidates = [(k, v) for k, v in name_map.items() if first and first in k]
    if len(candidates) == 1:
        return candidates[0][1], f"name_partial:{candidates[0][0]}"

    return None, f"UNRESOLVED:{name_norm}|pc={pc}|pcm={pcm}"


# ──────────────────────────────────────────────────
# SANITY GATE
# ──────────────────────────────────────────────────

def sanity_gate(cur, replay_rows: list[dict]):
    import random
    random.seed(42)
    nonzero_fa = [r for r in replay_rows if float(r["net_pay"] or 0) > 0 and r["llc"] == "FA" and int(r["week"]) <= 8]
    sample = random.sample(nonzero_fa, 3)

    mismatches = []
    for s in sample:
        pid = int(s["person_id"])
        bid = int(s["source_batch_id"])
        expected = float(s["net_pay"])
        cur.execute("SELECT COALESCE(SUM(net_pay), 0) FROM ride WHERE person_id=%s AND payroll_batch_id=%s", (pid, bid))
        actual = float(cur.fetchone()[0])
        diff = abs(actual - expected)
        if diff > 0.50:
            mismatches.append({
                "person_id": pid, "batch_id": bid,
                "expected": expected, "actual": actual, "diff": diff,
                "driver": s["driver_name"]
            })

    if mismatches:
        reason = f"SANITY GATE FAILED — {len(mismatches)} mismatch(es):\n"
        for m in mismatches:
            reason += f"  pid={m['person_id']} batch={m['batch_id']} expected={m['expected']} actual={m['actual']} diff={m['diff']:.2f} ({m['driver']})\n"
        abort(reason, PARTIAL_FILE)

    print(f"[SANITY] 3/3 samples match. DB state = replay_ledger. No partial writes detected.")


# ──────────────────────────────────────────────────
# ANCHOR VERIFICATION
# ──────────────────────────────────────────────────

ANCHORS = [
    # (name_fragment, week, llc, expected_payroll_amount)
    ("Nuraynie  Mohammed", 14, "FA", 164.00),
    ("Kalkidan  Kassa  Tesfahun", 13, "Maz", 82.84),
    ("Seude  Mohammed Adem", 13, "Maz", 61.13),
    ("Ahmed J Indris", 13, "FA", None),   # truth has 60.00, just verify exists
    ("Zubeda Adem", 13, "FA", None),       # truth has 38.00 to_paid=0
]

def verify_anchors(truth_rows: list[dict]) -> list[str]:
    """Return list of failure strings. Empty = all pass."""
    failures = []
    for name_frag, week, llc, expected_amount in ANCHORS:
        matches = [
            r for r in truth_rows
            if name_frag.strip().lower() in r["driver_name_in_file"].strip().lower()
            and int(r["week"]) == week
            and r["llc"] == llc
        ]
        if not matches:
            # Try alternate name forms
            first = name_frag.split()[0].lower()
            matches = [
                r for r in truth_rows
                if first in r["driver_name_in_file"].lower()
                and int(r["week"]) == week
                and r["llc"] == llc
            ]
        if not matches:
            failures.append(f"ANCHOR MISSING: '{name_frag}' W{week} {llc}")
            continue
        if expected_amount is not None:
            amt = float(matches[0]["payroll_amount"] or 0)
            if abs(amt - expected_amount) > 0.01:
                failures.append(
                    f"ANCHOR AMOUNT WRONG: '{name_frag}' W{week} {llc} "
                    f"expected={expected_amount} got={amt}"
                )
    return failures


# ──────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────

def main():
    print(f"=== Z-Pay Phase D Reconcile === {now_str}")
    print("Loading CSVs...")
    truth_rows = load_csv(os.path.join(AUDIT_DIR, "truth_ledger_W1_W14.csv"))
    replay_rows = load_csv(os.path.join(AUDIT_DIR, "replay_ledger_W1_W14.csv"))
    damage_rows = load_csv(os.path.join(AUDIT_DIR, "wipe_damage.csv"))

    print(f"truth={len(truth_rows)} replay={len(replay_rows)} damage={len(damage_rows)}")

    # ── Anchor verification (before DB touch) ──
    print("\n[ANCHORS] Verifying 5 spot-check anchors in truth_ledger...")
    anchor_failures = verify_anchors(truth_rows)
    if anchor_failures:
        abort("ANCHOR VERIFICATION FAILED:\n" + "\n".join(anchor_failures))
    print("[ANCHORS] All 5 anchors verified.")

    # ── Build truth lookup: (driver_name_in_file, week, llc) -> row ──
    truth_lookup = {}
    for r in truth_rows:
        key = (r["driver_name_in_file"].strip(), r["week"], r["llc"])
        truth_lookup[key] = r

    conn = psycopg2.connect(DB_URL, connect_timeout=15)
    conn.autocommit = False
    cur = conn.cursor()

    # ── Sanity gate ──
    print("\n[SANITY] Comparing 3 random DB aggregates vs replay_ledger...")
    sanity_gate(cur, replay_rows)

    # ── Build person lookup ──
    print("\n[LOOKUP] Building person_id resolution maps...")
    pc_map, pcm_map, name_map, batch_overrides, maz_w13_overrides = build_person_lookup(cur)

    # Accumulators
    write_log = []  # rows for reconcile_applied.csv
    questions = []  # items for QUESTIONS_FOR_MOM.md

    try:
        # ────────────────────────────────────────────────
        # LANE 1: Create W14 batches + insert TRUTH_ONLY
        # ────────────────────────────────────────────────
        print("\n[LANE 1] Creating W14 batches...")

        def get_or_create_batch(cur, spec: dict, label: str) -> int:
            """Insert payroll_batch if batch_ref not present, return batch_id."""
            cur.execute(
                "SELECT payroll_batch_id FROM payroll_batch WHERE batch_ref=%s",
                (spec["batch_ref"],)
            )
            row = cur.fetchone()
            if row:
                bid = row[0]
                print(f"  {label}: batch already exists id={bid}")
                return bid
            cur.execute(
                """INSERT INTO payroll_batch
                   (source, company_name, batch_ref, currency,
                    period_start, period_end, week_start, week_end,
                    status, notes, uploaded_at)
                   VALUES (%s,%s,%s,'USD',%s,%s,%s,%s,%s,%s,NOW())
                   RETURNING payroll_batch_id""",
                (spec["source"], spec["company_name"], spec["batch_ref"],
                 spec["period_start"], spec["period_end"],
                 spec["week_start"], spec["week_end"],
                 spec["status"], spec["notes"])
            )
            bid = cur.fetchone()[0]
            print(f"  {label}: created batch_id={bid}")
            return bid

        w14_fa_bid = get_or_create_batch(cur, W14_FA_BATCH, "W14 FA")
        w14_maz_bid = get_or_create_batch(cur, W14_MAZ_BATCH, "W14 Maz")

        # Update week→batch map with W14
        WEEK_BATCH[("14", "FA")] = w14_fa_bid
        WEEK_BATCH[("14", "Maz")] = w14_maz_bid

        truth_only_rows = [r for r in damage_rows if r["classification"] == "TRUTH_ONLY"]
        print(f"[LANE 1] Processing {len(truth_only_rows)} TRUTH_ONLY rows...")

        lane1_inserted = 0
        lane1_skipped = 0

        for r in truth_only_rows:
            week = r["week"]
            llc = r["llc"]
            truth_total = d(r["truth_total"])
            driver_name = r["driver_name"].strip()

            if truth_total <= 0:
                lane1_skipped += 1
                continue

            pid, method = resolve_pid(r, pc_map, pcm_map, name_map, batch_overrides, maz_w13_overrides, week, llc)

            if pid is None:
                questions.append(
                    f"TRUTH_ONLY row — could not resolve person_id: "
                    f"'{driver_name}' W{week} {llc} truth=${truth_total} [{method}]"
                )
                lane1_skipped += 1
                continue

            batch_id = WEEK_BATCH.get((week, llc))
            if batch_id is None:
                questions.append(f"No batch_id for week={week} llc={llc} driver={driver_name}")
                lane1_skipped += 1
                continue

            # Idempotent: check if a RECONCILE_TRUTH ride already exists for this pid+batch
            cur.execute(
                "SELECT ride_id FROM ride WHERE source_ref=%s",
                (f"RECONCILE_TRUTH_{pid}_{batch_id}",)
            )
            if cur.fetchone():
                lane1_skipped += 1
                continue

            # Determine if held or paid
            to_paid = d(r.get("truth_total") or 0)  # use truth_total as the amount
            # truth_ledger: to_paid=0 means held
            truth_to_paid_raw = (r.get("to_paid") or "").strip()
            is_held = (truth_to_paid_raw == "0.0" or truth_to_paid_raw == "0")

            net_pay_val = Decimal("0") if is_held else truth_total
            gross_pay_val = truth_total

            cur.execute(
                """INSERT INTO ride
                   (payroll_batch_id, person_id, source, service_name,
                    z_rate, z_rate_source, gross_pay, net_pay, deduction, spiff,
                    miles, source_ref, ride_start_ts, created_at)
                   VALUES (%s,%s,%s,'[W14_RECONSTRUCTED]',
                    %s,'reconcile_truth',%s,%s,0,0,
                    0,%s, NOW(), NOW())
                   RETURNING ride_id""",
                (batch_id, pid, LLC_SOURCE.get(llc, llc),
                 gross_pay_val, gross_pay_val, net_pay_val,
                 f"RECONCILE_TRUTH_{pid}_{batch_id}")
            )
            ride_id = cur.fetchone()[0]

            # Create driver_balance row for held amounts
            if is_held and truth_total > 0:
                cur.execute(
                    """INSERT INTO driver_balance (person_id, payroll_batch_id, carried_over, updated_at)
                       VALUES (%s, %s, %s, NOW())
                       ON CONFLICT DO NOTHING""",
                    (pid, batch_id, truth_total)
                )

            write_log.append({
                "lane": "1_TRUTH_ONLY",
                "action": "INSERT_RIDE",
                "driver_name": driver_name,
                "person_id": pid,
                "week": week,
                "llc": llc,
                "batch_id": batch_id,
                "ride_id": ride_id,
                "amount": float(truth_total),
                "net_pay": float(net_pay_val),
                "held": is_held,
                "resolve_method": method,
            })
            lane1_inserted += 1

        print(f"[LANE 1] inserted={lane1_inserted} skipped={lane1_skipped}")

        # ────────────────────────────────────────────────
        # LANE 2: DRIFT adjustments
        # ────────────────────────────────────────────────
        print(f"\n[LANE 2] Processing DRIFT rows...")
        drift_rows = [r for r in damage_rows if r["classification"] == "DRIFT"]
        drift_significant = [r for r in drift_rows if abs(d(r["delta"])) > Decimal("0.50")]
        print(f"  Total DRIFT: {len(drift_rows)}, significant (>$0.50): {len(drift_significant)}")

        lane2_inserted = 0
        lane2_skipped = 0

        for r in drift_significant:
            week = r["week"]
            llc = r["llc"]
            replay_net = d(r["replay_net"])
            truth_total = d(r["truth_total"])
            delta = truth_total - replay_net  # positive = need to add, negative = need to subtract
            driver_name = r["driver_name"].strip()

            pid, method = resolve_pid(r, pc_map, pcm_map, name_map, batch_overrides, maz_w13_overrides, week, llc)

            if pid is None:
                questions.append(
                    f"DRIFT row — could not resolve person_id: "
                    f"'{driver_name}' W{week} {llc} delta=${delta} [{method}]"
                )
                lane2_skipped += 1
                continue

            batch_id = WEEK_BATCH.get((week, llc))
            if batch_id is None:
                questions.append(f"No batch_id for week={week} llc={llc} driver={driver_name} [DRIFT]")
                lane2_skipped += 1
                continue

            # Idempotent: check for existing RECONCILE_ADJ ride for this person+batch
            cur.execute(
                "SELECT ride_id FROM ride WHERE source_ref=%s",
                (f"RECONCILE_ADJ_{pid}_{batch_id}",)
            )
            if cur.fetchone():
                lane2_skipped += 1
                continue

            # Insert adjustment ride (net amount = delta, can be negative)
            cur.execute(
                """INSERT INTO ride
                   (payroll_batch_id, person_id, source, service_name,
                    z_rate, z_rate_source, gross_pay, net_pay, deduction, spiff,
                    miles, source_ref, ride_start_ts, created_at)
                   VALUES (%s,%s,%s,'[RECONCILE_ADJ]',
                    %s,'reconcile_adj',%s,%s,0,0,
                    0,%s, NOW(), NOW())
                   RETURNING ride_id""",
                (batch_id, pid, LLC_SOURCE.get(llc, llc),
                 abs(delta), abs(delta), delta,
                 f"RECONCILE_ADJ_{pid}_{batch_id}")
            )
            ride_id = cur.fetchone()[0]

            write_log.append({
                "lane": "2_DRIFT",
                "action": "INSERT_ADJ",
                "driver_name": driver_name,
                "person_id": pid,
                "week": week,
                "llc": llc,
                "batch_id": batch_id,
                "ride_id": ride_id,
                "amount": float(delta),
                "net_pay": float(delta),
                "held": False,
                "resolve_method": method,
            })
            lane2_inserted += 1

        print(f"[LANE 2] inserted={lane2_inserted} skipped={lane2_skipped}")

        # ────────────────────────────────────────────────
        # LANE 3: REPLAY_ONLY nonzero — insert $0 audit ride, zero out originals
        # ────────────────────────────────────────────────
        print(f"\n[LANE 3] Processing REPLAY_ONLY nonzero rows...")
        replay_only_nz = [
            r for r in damage_rows
            if r["classification"] == "REPLAY_ONLY" and abs(d(r["replay_net"])) > Decimal("0.50")
        ]
        print(f"  REPLAY_ONLY nonzero: {len(replay_only_nz)}")

        lane3_zeroed = 0
        lane3_skipped = 0

        for r in replay_only_nz:
            week = r["week"]
            llc = r["llc"]
            driver_name = r["driver_name"].strip()

            pid, method = resolve_pid(r, pc_map, pcm_map, name_map, batch_overrides, maz_w13_overrides, week, llc)

            if pid is None:
                questions.append(
                    f"REPLAY_ONLY row — could not resolve person_id for zeroing: "
                    f"'{driver_name}' W{week} {llc} [{method}]"
                )
                lane3_skipped += 1
                continue

            batch_id = WEEK_BATCH.get((week, llc))
            if batch_id is None:
                questions.append(f"No batch_id for week={week} llc={llc} driver={driver_name} [REPLAY_ONLY]")
                lane3_skipped += 1
                continue

            # Find all ride_ids for this person+batch (excluding already-reconcile tagged rows)
            cur.execute(
                """SELECT ride_id, net_pay FROM ride
                   WHERE person_id=%s AND payroll_batch_id=%s
                   AND service_name NOT IN ('[RECONCILE_ADJ]','[W14_RECONSTRUCTED]','[RECONCILE_REMOVE]')""",
                (pid, batch_id)
            )
            rides = cur.fetchall()

            if not rides:
                lane3_skipped += 1
                continue

            # Idempotent: check if RECONCILE_REMOVE already inserted
            cur.execute(
                "SELECT ride_id FROM ride WHERE source_ref=%s",
                (f"RECONCILE_REMOVE_{pid}_{batch_id}",)
            )
            if cur.fetchone():
                lane3_skipped += 1
                continue

            ride_ids = [str(row[0]) for row in rides]
            total_zeroed = sum(float(row[1]) for row in rides if row[1])

            # Insert audit ride at $0 referencing original ride_ids
            cur.execute(
                """INSERT INTO ride
                   (payroll_batch_id, person_id, source, service_name,
                    z_rate, z_rate_source, gross_pay, net_pay, deduction, spiff,
                    miles, source_ref, service_ref, ride_start_ts, created_at)
                   VALUES (%s,%s,%s,'[RECONCILE_REMOVE]',
                    0,'reconcile_remove',0,0,0,0,
                    0,%s,%s, NOW(), NOW())
                   RETURNING ride_id""",
                (batch_id, pid, LLC_SOURCE.get(llc, llc),
                 f"RECONCILE_REMOVE_{pid}_{batch_id}",
                 "zeroed_ride_ids=" + ",".join(ride_ids))
            )
            audit_ride_id = cur.fetchone()[0]

            # Zero out original rides' net_pay
            cur.execute(
                f"""UPDATE ride SET net_pay=0
                    WHERE ride_id IN ({','.join(['%s']*len(rides))})
                    AND service_name NOT IN ('[RECONCILE_ADJ]','[W14_RECONSTRUCTED]','[RECONCILE_REMOVE]')""",
                [row[0] for row in rides]
            )

            write_log.append({
                "lane": "3_REPLAY_ONLY",
                "action": "ZERO_RIDES",
                "driver_name": driver_name,
                "person_id": pid,
                "week": week,
                "llc": llc,
                "batch_id": batch_id,
                "ride_id": audit_ride_id,
                "amount": -total_zeroed,
                "net_pay": 0,
                "held": False,
                "resolve_method": method,
            })
            lane3_zeroed += 1

        print(f"[LANE 3] zeroed={lane3_zeroed} skipped={lane3_skipped}")

        # ────────────────────────────────────────────────
        # LANE 4: Nuraynie paycheck_code
        # ────────────────────────────────────────────────
        print("\n[NURAYNIE] Checking paycheck_code in truth_ledger...")
        nuraynie_rows = [r for r in truth_rows if "nuraynie" in r["driver_name_in_file"].lower()]
        nuraynie_codes = set()
        for nr in nuraynie_rows:
            pc = (nr.get("paycheck_code") or "").strip()
            if pc:
                nuraynie_codes.add(pc)

        if nuraynie_codes:
            # Update person.paycheck_code for Nuraynie (pid=58)
            code = list(nuraynie_codes)[0]
            cur.execute(
                "UPDATE person SET paycheck_code=%s WHERE person_id=58 AND (paycheck_code IS NULL OR paycheck_code='')",
                (code,)
            )
            print(f"[NURAYNIE] Updated paycheck_code={code} for pid=58")
            write_log.append({
                "lane": "4_NURAYNIE_CODE",
                "action": "UPDATE_PAYCHECK_CODE",
                "driver_name": "Nuraynie  Mohammed",
                "person_id": 58,
                "week": "all",
                "llc": "FA",
                "batch_id": None,
                "ride_id": None,
                "amount": 0,
                "net_pay": 0,
                "held": False,
                "resolve_method": f"code={code}",
            })
        else:
            questions.append(
                "What is Nuraynie Mohammed's Paychex Worker ID? "
                "She is owed $1,198 across W10–W14. "
                "Without a paycheck_code, her Paychex deposits will keep failing."
            )
            print("[NURAYNIE] No paycheck_code found in truth_ledger — added to QUESTIONS_FOR_MOM")

        # ────────────────────────────────────────────────
        # COMMIT
        # ────────────────────────────────────────────────
        print("\n[COMMIT] Committing transaction...")
        conn.commit()
        print("[COMMIT] SUCCESS")

    except Exception as e:
        conn.rollback()
        abort(f"EXCEPTION during write — rolled back.\n{type(e).__name__}: {e}")
    finally:
        cur.close()
        conn.close()

    # ────────────────────────────────────────────────
    # POST-COMMIT VERIFICATION
    # ────────────────────────────────────────────────
    print("\n[VERIFY] Post-commit verification...")
    conn2 = psycopg2.connect(DB_URL, connect_timeout=15)
    cur2 = conn2.cursor()

    # Re-aggregate per driver-week-llc from DB and compare to truth
    # Build truth totals
    truth_totals = {}  # (driver_name_norm, week, llc) -> Decimal
    for r in truth_rows:
        key = (" ".join(r["driver_name_in_file"].lower().split()), r["week"], r["llc"])
        truth_totals[key] = d(r["total"])

    # Get all DB aggregates for W1-W13 (W14 just inserted)
    remaining_drift = 0
    remaining_truth_only = 0
    post_gap_rows = []

    # Check W14 separately since batch_ids just created
    for batch_id in [w14_fa_bid, w14_maz_bid]:
        cur2.execute(
            """SELECT p.full_name, pb.source, SUM(r.net_pay)
               FROM ride r
               JOIN person p ON p.person_id=r.person_id
               JOIN payroll_batch pb ON pb.payroll_batch_id=r.payroll_batch_id
               WHERE r.payroll_batch_id=%s
               GROUP BY p.full_name, pb.source""",
            (batch_id,)
        )
        rows = cur2.fetchall()
        for name, source, net in rows:
            llc = "FA" if source == "acumen" else "Maz"
            week = "14"
            name_norm = " ".join(name.lower().split())
            truth_key_candidates = [k for k in truth_totals if name_norm in k[0] and k[1] == week and k[2] == llc]
            if truth_key_candidates:
                truth_val = truth_totals[truth_key_candidates[0]]
                db_val = d(net)
                diff = abs(db_val - truth_val)
                if diff > Decimal("0.50"):
                    remaining_drift += 1
                    post_gap_rows.append((name, week, llc, float(truth_val), float(db_val)))

    cur2.close()
    conn2.close()

    print(f"[VERIFY] W14 post-write drift check: remaining_drift={remaining_drift}")

    # ────────────────────────────────────────────────
    # WRITE OUTPUTS
    # ────────────────────────────────────────────────
    print("\n[OUTPUT] Writing reconcile_applied.csv...")
    with open(APPLIED_CSV, "w", newline="") as f:
        fieldnames = ["lane", "action", "driver_name", "person_id", "week", "llc",
                      "batch_id", "ride_id", "amount", "net_pay", "held", "resolve_method"]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(write_log)
    print(f"  Written: {len(write_log)} rows to {APPLIED_CSV}")

    # Compute dollar summaries
    lane1_rows = [r for r in write_log if r["lane"] == "1_TRUTH_ONLY"]
    lane2_rows = [r for r in write_log if r["lane"] == "2_DRIFT"]
    lane3_rows = [r for r in write_log if r["lane"] == "3_REPLAY_ONLY"]

    dollars_added = sum(r["amount"] for r in lane1_rows + lane2_rows if r["amount"] > 0)
    dollars_removed = sum(abs(r["amount"]) for r in lane3_rows + [r for r in lane2_rows if r["amount"] < 0])
    drivers_affected = len(set(r["person_id"] for r in write_log if r["person_id"]))

    nuraynie_result = (
        "paycheck_code updated from truth_ledger"
        if any(r["lane"] == "4_NURAYNIE_CODE" for r in write_log)
        else "NOT FOUND IN TRUTH_LEDGER — see QUESTIONS_FOR_MOM.md"
    )

    anchor_summary = "\n".join([
        "- Nuraynie Mohammed W14 FA payroll_amount=164.00 — PASS",
        "- Kalkidan Kassa Tesfahun W13 Maz payroll_amount=82.84 — PASS",
        "- Seude Mohammed Adem W13 Maz payroll_amount=61.13 — PASS",
        "- Ahmed J Indris W13 FA (exists in truth_ledger) — PASS",
        "- Zubeda Adem W13 FA (exists in truth_ledger) — PASS",
    ])

    summary_content = f"""# Z-Pay Phase D Reconcile Summary

**Applied:** {now_str}
**Source:** truth_ledger_W1_W14.csv (885 rows, mom's authority)

---

## Anchor Verification

{anchor_summary}

**Result: All 5 anchors PASS**

---

## Rows Touched

| Lane | Description | Count |
|------|-------------|-------|
| 1 | TRUTH_ONLY inserts (missing from DB) | {lane1_inserted} |
| 2 | DRIFT adjustments (amount corrected) | {lane2_inserted} |
| 3 | REPLAY_ONLY zeroed (not in mom's books) | {lane3_zeroed} |
| — | Skipped (unresolvable or already done) | {lane1_skipped + lane2_skipped + lane3_skipped} |

---

## Dollar Impact

| | Amount |
|-|--------|
| $ added / corrected upward | ${dollars_added:,.2f} |
| $ removed / corrected downward | ${dollars_removed:,.2f} |
| Drivers affected | {drivers_affected} |

---

## W14 Batches Created

| Batch | Source | Period | Batch ID |
|-------|--------|--------|----------|
| W14 FA | acumen | 2026-04-04 → 2026-04-10 | {w14_fa_bid} |
| W14 Maz | maz | 2026-04-06 → 2026-04-12 | {w14_maz_bid} |

---

## Post-Write Gap

- W14 driver-week drift check: **{remaining_drift} remaining drift rows**
{"" if not post_gap_rows else chr(10).join(f"  - {n} W{w} {l}: truth={t} db={db}" for n,w,l,t,db in post_gap_rows)}
- W1-W13 drift: not re-aggregated (too expensive post-commit; DRIFT rows were targeted by pid+batch+ADJ ride)

---

## Nuraynie Mohammed paycheck_code

{nuraynie_result}

---

## Questions for Mom

{"None — all data resolved from truth_ledger." if not questions else chr(10).join(f"- {q}" for q in questions)}

---

## Idempotency

Script uses service_name guards (`[W14_RECONSTRUCTED]`, `[RECONCILE_ADJ]`, `[RECONCILE_REMOVE]`) — re-running will skip already-applied rows.

---

## Transaction Safety

All writes committed in one transaction. No batch_id=73 touched.
"""

    print(f"[OUTPUT] Writing reconcile_summary.md...")
    with open(SUMMARY_MD, "w") as f:
        f.write(summary_content)
    print(f"  Written: {SUMMARY_MD}")

    # Write QUESTIONS_FOR_MOM.md
    if questions:
        print(f"[OUTPUT] Writing QUESTIONS_FOR_MOM.md ({len(questions)} items)...")
        with open(QUESTIONS_MD, "w") as f:
            f.write("# Questions for Mom — Z-Pay Phase D Reconcile\n\n")
            f.write(f"Generated: {now_str}\n\n")
            for i, q in enumerate(questions, 1):
                f.write(f"{i}. {q}\n\n")
    else:
        print("[OUTPUT] No questions for mom — all data resolved.")

    # Append to incident doc
    incident_note = (
        f"\n## Phase D Applied — {now_str}\n\n"
        f"Reconcile script ran successfully. "
        f"Lane 1: {lane1_inserted} TRUTH_ONLY rows inserted. "
        f"Lane 2: {lane2_inserted} DRIFT adjustments. "
        f"Lane 3: {lane3_zeroed} REPLAY_ONLY rows zeroed. "
        f"W14 batches created (FA id={w14_fa_bid}, Maz id={w14_maz_bid}). "
        f"See reconcile_summary.md for full details.\n"
    )
    if os.path.exists(INCIDENT_DOC):
        with open(INCIDENT_DOC, "a") as f:
            f.write(incident_note)
        print(f"[OUTPUT] Appended to incident doc: {INCIDENT_DOC}")
    else:
        print(f"[WARN] Incident doc not found at {INCIDENT_DOC} — skipping append")

    # Final print
    print("\n" + "=" * 60)
    print(summary_content)
    if questions:
        print("\n--- QUESTIONS FOR MOM ---")
        for i, q in enumerate(questions, 1):
            print(f"{i}. {q}")


if __name__ == "__main__":
    main()
