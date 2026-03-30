#!/usr/bin/env python3
"""
fix_unmatched_rates.py

Bulk-fixes all rides with z_rate=0 by matching them to rates in the CSV files.

Matching priority (per ride):
  1. Exact match (stripped)
  2. Strip ER/LS one-time suffix (regex: \s+[A-Z]{2}\d{6}\s+\d{2}$)
  3. Strip trailing (W), (F), (M), (M/F), (T/H), (H) day suffixes
  4. For names containing 'ODT': look for matching base route without ODT num suffix
  5. Return Monitor rides: use net_pay as z_rate (pass-through)
  6. Fallback: use net_pay as z_rate if truly no match

Also upserts ZRateService rows for any new service -> rate mappings found.
"""

from __future__ import annotations

import csv
import os
import re
import sys
from decimal import Decimal

import psycopg

# ── Config ────────────────────────────────────────────────────────────────────

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://app:secret@db:5432/appdb")
if DATABASE_URL.startswith("postgresql+psycopg://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://", 1)

ACUMEN_CSV = os.getenv("ACUMEN_CSV", "/data/in/acumen.rates.csv")
MAZ_CSV    = os.getenv("MAZ_CSV", "/data/in/maz.rates.csv")


# ── Helpers ───────────────────────────────────────────────────────────────────

def slugify(name: str) -> str:
    s = name.strip().lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "service"


def load_csv_rates(path: str) -> dict[str, Decimal]:
    """
    Load CSV into {normalized_service_name: rate} dict.
    CSV format: service_name,,,z_rate, (col 0 = name, col 3 = rate)
    Keys are stripped + lowercased for robust matching.
    """
    rates: dict[str, Decimal] = {}
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)  # skip header row
        for row in reader:
            if not row or all(not c.strip() for c in row):
                continue
            name_raw = row[0].strip() if len(row) > 0 else ""
            rate_raw = row[3].strip() if len(row) > 3 else ""
            if not name_raw or not rate_raw:
                continue
            try:
                rate = Decimal(rate_raw.replace(",", ""))
                if rate > 0:
                    # Store with original casing stripped and lowercase
                    key = name_raw.strip().lower()
                    # First writer wins (keeps first occurrence for duplicates)
                    if key not in rates:
                        rates[key] = rate
            except Exception:
                continue
    return rates


# Suffix patterns to strip for fuzzy matching
# Pattern: trailing " ER012726 01" or " LS030626 01" etc.
ONE_TIME_SUFFIX = re.compile(r'\s+[A-Z]{2}\d{6}\s+\d{2}$')

# Day-of-week suffixes like (W), (F), (M), (M/F), (T/H), (H), (M/T), (W/H)
DAY_SUFFIX = re.compile(r'\s+\([A-Z/]+\)$')

# Multiple trailing _X letter variants like _A, _B, _D
VARIANT_SUFFIX = re.compile(r'_[A-Z]$')


def strip_suffixes(name: str) -> list[str]:
    """
    Generate candidate base names by progressively stripping suffixes.
    Returns list of candidates in priority order (most specific first).
    """
    candidates = [name]

    # 1. Strip one-time suffix (ER/LS code)
    s = ONE_TIME_SUFFIX.sub("", name)
    if s != name:
        candidates.append(s)
        name = s

    # 2. Strip day suffix
    s = DAY_SUFFIX.sub("", name)
    if s != name:
        candidates.append(s)
        name = s

    # 3. Strip trailing _ variant letter (e.g. _D, _F)
    s = VARIANT_SUFFIX.sub("", name)
    if s != name:
        candidates.append(s)

    return candidates


def find_rate(service_name: str, rates: dict[str, Decimal]) -> Decimal | None:
    """
    Try to match service_name to a rate using progressive fallback logic.
    rates dict keys are lowercased+stripped.
    """
    # Build candidates
    candidates = strip_suffixes(service_name.strip())

    for candidate in candidates:
        key = candidate.strip().lower()
        if key in rates:
            return rates[key]

    # ODT rides: strip the ODT number from end and try the base route
    # e.g. "Albert Einstein ES IB ODT 06" → "Albert Einstein ES IB ODT 01" etc.
    # Also try without ODT at all: "Albert Einstein ES IB 04"
    if "ODT" in service_name.upper():
        # Try replacing ODT NN with ODT 01 (most common base)
        for candidate in candidates:
            odt_base = re.sub(r'\bODT\s+\d+', 'ODT 01', candidate, flags=re.IGNORECASE)
            if odt_base.lower() in rates:
                return rates[odt_base.lower()]
            odt_base2 = re.sub(r'\bODT\s+\d+', 'ODT 02', candidate, flags=re.IGNORECASE)
            if odt_base2.lower() in rates:
                return rates[odt_base2.lower()]

        # Try stripping ODT + number entirely
        for candidate in candidates:
            no_odt = re.sub(r'\s+ODT\s+\d+', '', candidate, flags=re.IGNORECASE).strip()
            if no_odt.lower() in rates:
                return rates[no_odt.lower()]
            # Also try replacing the ODT number with a regular route number
            # e.g. "Albert Einstein ES OB ODT 03" → "Albert Einstein ES OB 03"
            no_odt2 = re.sub(r'\s+ODT\s+(\d+)', r' \1', candidate, flags=re.IGNORECASE).strip()
            if no_odt2.lower() in rates:
                return rates[no_odt2.lower()]

    return None


def is_return_monitor(service_name: str) -> bool:
    return "return monitor" in service_name.lower()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    print("=" * 70)
    print("fix_unmatched_rates.py")
    print("=" * 70)

    # Load CSV rate tables
    print(f"\nLoading acumen rates from {ACUMEN_CSV}...")
    acumen_rates = load_csv_rates(ACUMEN_CSV)
    print(f"  Loaded {len(acumen_rates)} acumen rate entries.")

    print(f"Loading maz rates from {MAZ_CSV}...")
    maz_rates = load_csv_rates(MAZ_CSV)
    print(f"  Loaded {len(maz_rates)} maz rate entries.")

    with psycopg.connect(DATABASE_URL) as conn:

        # ── Query unmatched rides ─────────────────────────────────────────────
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ride_id, source, service_name, net_pay
                FROM ride
                WHERE z_rate = 0
                ORDER BY source, service_name
            """)
            rides = cur.fetchall()

        print(f"\nFound {len(rides)} rides with z_rate=0.")

        # ── Process each ride ─────────────────────────────────────────────────
        updates: list[tuple[Decimal, str, int]] = []   # (z_rate, z_rate_source, ride_id)
        new_service_rows: dict[str, dict] = {}          # service_key → row dict for upsert
        still_unmatched: list[tuple] = []

        for ride_id, source, service_name, net_pay in rides:
            rates_table = acumen_rates if source == "acumen" else maz_rates

            matched_rate: Decimal | None = None
            match_method: str = "csv_match"

            # Return Monitor: use net_pay as pass-through
            if is_return_monitor(service_name or ""):
                matched_rate = Decimal(str(net_pay)) if net_pay else Decimal("0")
                match_method = "return_monitor_passthrough"

            # Try CSV matching
            if matched_rate is None and service_name:
                matched_rate = find_rate(service_name, rates_table)
                if matched_rate is not None:
                    match_method = "csv_match"

            # Fallback: use net_pay for ODT/specialty with no match
            if matched_rate is None and service_name and (
                "ODT" in service_name.upper() or
                "iGrad" in service_name or
                "Stadium" in service_name or
                "Decatur" in service_name or
                "Alderwood" in service_name or
                "Scriber Lake HS IB 04" in service_name or
                "Scriber Lake HS OB 04" in service_name or
                "Overlake SPE IB 06" in service_name or
                "Transition @" in service_name or
                "Cedarcrest MS IB 01_A" in service_name
            ):
                matched_rate = Decimal(str(net_pay)) if net_pay else Decimal("0")
                match_method = "net_pay_fallback"

            # Maz fallback: net_pay for anything still unmatched in maz
            if matched_rate is None and source == "maz":
                matched_rate = Decimal(str(net_pay)) if net_pay else Decimal("0")
                match_method = "net_pay_fallback"

            if matched_rate is not None and matched_rate > 0:
                updates.append((matched_rate, match_method, ride_id))

                # Track new service mapping for upsert (only csv_match gets persisted)
                if match_method == "csv_match" and service_name:
                    skey = slugify(service_name)
                    if skey not in new_service_rows:
                        company = "Acumen" if source == "acumen" else "Maz"
                        new_service_rows[skey] = {
                            "source": source,
                            "company_name": company,
                            "service_key": skey,
                            "service_name": service_name.strip(),
                            "currency": "USD",
                            "default_rate": matched_rate,
                        }
            else:
                still_unmatched.append((ride_id, source, service_name, net_pay))

        # ── Apply updates ─────────────────────────────────────────────────────
        print(f"\nApplying {len(updates)} z_rate updates...")

        updated_count = 0
        with conn.cursor() as cur:
            for z_rate, z_rate_source, ride_id in updates:
                cur.execute(
                    """
                    UPDATE ride
                    SET z_rate = %s, z_rate_source = %s
                    WHERE ride_id = %s AND z_rate = 0
                    """,
                    (z_rate, z_rate_source, ride_id),
                )
                updated_count += cur.rowcount

        # ── Upsert ZRateService rows ──────────────────────────────────────────
        upserted = 0
        if new_service_rows:
            print(f"Upserting {len(new_service_rows)} ZRateService rows...")
            with conn.cursor() as cur:
                for row in new_service_rows.values():
                    cur.execute(
                        """
                        INSERT INTO z_rate_service
                          (source, company_name, service_key, service_name, currency, default_rate)
                        VALUES
                          (%(source)s, %(company_name)s, %(service_key)s,
                           %(service_name)s, %(currency)s, %(default_rate)s)
                        ON CONFLICT (source, company_name, service_key) DO UPDATE SET
                          default_rate = EXCLUDED.default_rate,
                          service_name = EXCLUDED.service_name,
                          active = true
                        """,
                        row,
                    )
                    upserted += 1

        conn.commit()
        print(f"  Committed. Updated {updated_count} rides, upserted {upserted} service rows.")

        # ── Verify ────────────────────────────────────────────────────────────
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM ride WHERE z_rate = 0")
            remaining = cur.fetchone()[0]

    # ── Report ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)
    print(f"  Total rides processed:      {len(rides)}")
    print(f"  Rides updated:              {updated_count}")
    print(f"  ZRateService rows upserted: {upserted}")
    print(f"  Rides STILL z_rate=0:       {remaining}")

    # Breakdown by match method
    method_counts: dict[str, int] = {}
    for _, method, _ in updates:
        method_counts[method] = method_counts.get(method, 0) + 1
    print("\n  Match method breakdown:")
    for method, count in sorted(method_counts.items(), key=lambda x: -x[1]):
        print(f"    {method:<35} {count}")

    if still_unmatched:
        print(f"\n  STILL UNMATCHED ({len(still_unmatched)} rides):")
        seen: set[str] = set()
        for ride_id, source, sname, npay in still_unmatched:
            key = f"{source}|{sname}"
            if key not in seen:
                print(f"    [{source}] {sname!r}  (net_pay={npay})")
                seen.add(key)
    else:
        print("\n  All rides matched successfully!")

    return 0 if remaining == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
