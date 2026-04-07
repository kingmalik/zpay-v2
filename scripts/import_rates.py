#!/usr/bin/env python3
"""
Import z_rates from CSV files into z_rate_service table.
Updates default_rate for entries that currently have rate=0.
Also updates rides referencing those services where z_rate=0.
"""

import csv
import re
import psycopg
from decimal import Decimal

DB_URL = "postgresql://app:zpay_secret_2026@junction.proxy.rlwy.net:38477/appdb"

ACUMEN_CSV = "/Users/malikmilion/Documents/z-pay/data/in/acumen.rates.csv"
MAZ_CSV = "/Users/malikmilion/Documents/z-pay/data/in/maz.rates.csv"


def clean_name(name: str) -> str:
    name = name.strip().strip('"').strip()
    name = name.replace('\t', ' ')
    name = re.sub(r'\s+', ' ', name)
    return name


def parse_rate(val: str):
    val = val.strip()
    if not val:
        return None
    try:
        return Decimal(val)
    except Exception:
        return None


def normalize_for_fuzzy(name: str) -> str:
    n = name
    n = re.sub(r'\s+[LE][SR]\d{6}\s+\d+', '', n)
    n = re.sub(r'\s*\[Wt\]', '', n)
    n = re.sub(r'_[A-F]$', '', n)
    n = re.sub(r'\s*\([A-Z/]+\)$', '', n)
    n = re.sub(r'_[A-F]$', '', n)
    n = re.sub(r'\s+ODT\s+\d+', '', n)
    n = re.sub(r'\s+Return Monitor for:.*$', '', n)
    return n.strip()


def read_csv_rates(filepath: str):
    results = []
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            if not row or not row[0].strip():
                continue
            name = clean_name(row[0])
            if not name:
                continue
            if len(row) > 3:
                rate = parse_rate(row[3])
            else:
                rate = None
            if rate and rate > 0:
                results.append((name, rate))
    return results


def build_rate_lookup(csv_rates):
    lookup = {}
    for name, rate in csv_rates:
        lookup[name] = rate
    return lookup


def build_fuzzy_lookup(csv_rates):
    lookup = {}
    for name, rate in csv_rates:
        norm = normalize_for_fuzzy(name)
        if norm not in lookup:
            lookup[norm] = rate
    return lookup


def match_rates(db_rows, csv_rates):
    exact_lookup = build_rate_lookup(csv_rates)
    fuzzy_lookup = build_fuzzy_lookup(csv_rates)
    updates = []
    unmatched = []

    for row_id, service_name in db_rows:
        name = service_name.strip()
        if name in exact_lookup:
            updates.append((row_id, exact_lookup[name], name, "exact"))
            continue
        norm_db = normalize_for_fuzzy(name)
        if norm_db in fuzzy_lookup:
            updates.append((row_id, fuzzy_lookup[norm_db], name, "fuzzy"))
            continue
        unmatched.append((row_id, name))

    return updates, unmatched


def main():
    print("=" * 70)
    print("Z-Pay Rate Import Script")
    print("=" * 70)

    print("\nReading Acumen CSV...")
    acumen_rates = read_csv_rates(ACUMEN_CSV)
    print(f"  Parsed {len(acumen_rates)} rate entries from acumen.rates.csv")

    print("Reading Maz CSV...")
    maz_rates = read_csv_rates(MAZ_CSV)
    print(f"  Parsed {len(maz_rates)} rate entries from maz.rates.csv")

    conn = psycopg.connect(DB_URL)
    conn.autocommit = False

    try:
        cur = conn.cursor()

        # --- ACUMEN ---
        cur.execute("""
            SELECT z_rate_service_id, service_name
            FROM z_rate_service
            WHERE source = 'acumen'
              AND company_name IN ('FirstAlt', 'Acumen International', 'Acumen')
              AND default_rate = 0
            ORDER BY service_name
        """)
        acumen_db_rows = cur.fetchall()
        print(f"\nAcumen zero-rate DB entries: {len(acumen_db_rows)}")
        acumen_updates, acumen_unmatched = match_rates(acumen_db_rows, acumen_rates)

        # --- MAZ ---
        cur.execute("""
            SELECT z_rate_service_id, service_name
            FROM z_rate_service
            WHERE source = 'maz'
              AND LOWER(company_name) = 'everdriven'
              AND default_rate = 0
            ORDER BY service_name
        """)
        maz_db_rows = cur.fetchall()
        print(f"Maz zero-rate DB entries: {len(maz_db_rows)}")
        maz_updates, maz_unmatched = match_rates(maz_db_rows, maz_rates)

        # --- REPORT ---
        print("\n" + "=" * 70)
        print("MATCHING REPORT")
        print("=" * 70)

        print(f"\n--- Acumen/FirstAlt ---")
        print(f"  Matched:   {len(acumen_updates)}")
        print(f"  Unmatched: {len(acumen_unmatched)}")
        if acumen_unmatched:
            print(f"\n  Unmatched Acumen service names:")
            for rid, name in acumen_unmatched:
                print(f"    [{rid}] {name}")

        print(f"\n--- Maz/EverDriven ---")
        print(f"  Matched:   {len(maz_updates)}")
        print(f"  Unmatched: {len(maz_unmatched)}")
        if maz_unmatched:
            print(f"\n  Unmatched Maz service names:")
            for rid, name in maz_unmatched:
                print(f"    [{rid}] {name}")

        all_updates = acumen_updates + maz_updates
        print(f"\n--- TOTAL ---")
        print(f"  Will update: {len(all_updates)} z_rate_service entries")
        print(f"  Unmatched:   {len(acumen_unmatched) + len(maz_unmatched)} entries remain at rate=0")

        print(f"\n  Sample updates (first 10):")
        for svc_id, rate, name, method in all_updates[:10]:
            print(f"    [{svc_id}] {name} -> ${rate} ({method})")

        # --- APPLY z_rate_service updates ---
        if all_updates:
            print(f"\nApplying {len(all_updates)} z_rate_service updates...")
            for svc_id, rate, name, method in all_updates:
                cur.execute(
                    "UPDATE z_rate_service SET default_rate = %s WHERE z_rate_service_id = %s",
                    (rate, svc_id)
                )
            conn.commit()
            print("  z_rate_service updates committed.")

            # Update rides one service at a time to avoid deadlocks
            print("Updating rides with z_rate=0 that reference updated services...")
            rides_updated = 0
            for svc_id, rate, name, method in all_updates:
                cur.execute("""
                    UPDATE ride
                    SET z_rate = %s
                    WHERE z_rate_service_id = %s
                      AND z_rate = 0
                """, (rate, svc_id))
                rides_updated += cur.rowcount
                conn.commit()
            print(f"  Updated {rides_updated} rides")

            print("\nAll changes committed successfully.")
        else:
            print("\nNo updates to apply.")

        # --- VERIFY ---
        cur.execute("SELECT COUNT(*) FROM z_rate_service WHERE default_rate = 0")
        remaining_zero = cur.fetchone()[0]
        print(f"\nRemaining z_rate_service entries with default_rate=0: {remaining_zero}")

        cur.execute("""
            SELECT COUNT(*) FROM ride
            WHERE z_rate = 0
              AND z_rate_service_id IS NOT NULL
        """)
        remaining_rides = cur.fetchone()[0]
        print(f"Remaining rides with z_rate=0 (linked to a service): {remaining_rides}")

    finally:
        conn.close()

    print("\nDone.")


if __name__ == "__main__":
    main()
