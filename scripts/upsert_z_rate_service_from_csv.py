#!/usr/bin/env python3
"""
upsert_z_rate_service_from_csv.py

Reads a CSV with columns:
  service_name, z_rate
and UPSERTs into z_rate_service:
  (source, company_name, service_key, service_name, currency, default_rate)

Usage:
  python upsert_z_rate_service_from_csv.py \
    --csv rates.csv \
    --source acumen \
    --company-name "Acumen International" \
    --db-url "postgresql://app:app@localhost:5432/appdb"

If --db-url is omitted, uses DATABASE_URL env var.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from decimal import Decimal, InvalidOperation

import psycopg


def slugify_service_key(name: str) -> str:
    """
    Create a stable key from service_name:
    - lower
    - trim
    - replace '&' with 'and'
    - collapse non-alphanum to '-'
    - collapse multiple '-' and strip ends
    """
    s = name.strip().lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "service"


def parse_decimal(val: str) -> Decimal:
    v = (val or "").strip()
    if not v:
        raise ValueError("empty rate")
    # Allow commas in numbers like "1,234.56"
    v = v.replace(",", "")
    try:
        return Decimal(v)
    except InvalidOperation as e:
        raise ValueError(f"invalid decimal: {val!r}") from e


UPSERT_SQL = """
INSERT INTO z_rate_service (
  source,
  company_name,
  service_key,
  service_name,
  currency,
  default_rate
)
VALUES (
  %(source)s,
  %(company_name)s,
  %(service_key)s,
  %(service_name)s,
  %(currency)s,
  %(default_rate)s
)
ON CONFLICT (source, company_name, service_name)
DO UPDATE SET
  default_rate = EXCLUDED.default_rate,
  currency = EXCLUDED.currency,
  active = true;
"""

ENSURE_UNIQUE_INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS ux_z_rate_service_scope
ON z_rate_service (source, company_name, service_name);
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="Path to CSV/TSV file")
    ap.add_argument("--source", required=True, help="e.g. acumen")
    ap.add_argument("--company-name", required=True, help='e.g. "Acumen International"')
    ap.add_argument("--currency", default="USD", help="Default currency (default: USD)")
    ap.add_argument("--db-url", default=os.getenv("DATABASE_URL", ""), help="Postgres URL")
    ap.add_argument("--dry-run", action="store_true", help="Print rows, do not write to DB")
    args = ap.parse_args()

    db_url = (args.db_url or "").strip()

    if db_url.startswith("postgresql+psycopg://"):
        db_url = db_url.replace("postgresql+psycopg://", "postgresql://", 1)
    elif db_url.startswith("postgresql+psycopg2://"):
        db_url = db_url.replace("postgresql+psycopg2://", "postgresql://", 1)


    # --- Read file, auto-detect delimiter (comma vs tab) ---
    rows: list[dict] = []
    with open(args.csv, "r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)

        # Try to detect delimiter; default to comma
        delimiter = ","
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=[",", "\t", ";", "|"])
            delimiter = dialect.delimiter
        except csv.Error:
            # If it looks tab-separated, force tab
            if "\t" in sample and "," not in sample:
                delimiter = "\t"

        reader = csv.reader(f, delimiter=delimiter)

        # Read first row (maybe header, maybe data)
        first = next(reader, None)
        if not first:
            print("ERROR: CSV is empty.", file=sys.stderr)
            return 2

        # Normalize cells
        first_norm = [c.strip() for c in first]

        # Detect header
        lower = [c.lower().strip() for c in first_norm]
        has_header = ("service_name" in lower) and (("z_rate" in lower) or ("rate" in lower) or ("z_tmp_rate" in lower))

        if has_header:
            headers = lower
        else:
            # Assume 2-column file without header: service_name, z_rate
            headers = ["service_name", "z_rate"]
            # Treat first row as data
            data_row = first_norm
            if len(data_row) >= 2:
                service_name = data_row[0].strip()
                rate_str = data_row[1].strip()
                if service_name and rate_str:
                    try:
                        rate = parse_decimal(rate_str)
                        rows.append({
                            "source": args.source.strip(),
                            "company_name": args.company_name.strip(),
                            "service_key": slugify_service_key(service_name),
                            "service_name": service_name,
                            "currency": (args.currency.strip() or "USD"),
                            "default_rate": rate,
                        })
                    except ValueError as e:
                        print(f"Skipping first data row: {e}", file=sys.stderr)

        # Helper to fetch a column by header name (robust to spaces)
        def idx_of(name: str) -> int | None:
            name = name.lower().strip()
            for i, h in enumerate(headers):
                if h == name:
                    return i
            return None

        i_service = idx_of("service_name")
        i_rate = idx_of("z_rate") or idx_of("z_tmp_rate") or idx_of("rate")

        line_no = 1
        for r in reader:
            line_no += 1
            if not r or all(not c.strip() for c in r):
                continue

            cells = [c.strip() for c in r]

            service_name = (cells[i_service] if i_service is not None and i_service < len(cells) else "").strip()
            rate_str = (cells[i_rate] if i_rate is not None and i_rate < len(cells) else "").strip()

            if not service_name:
                print(f"Skipping line {line_no}: missing service_name", file=sys.stderr)
                continue
            if not rate_str:
                print(f"Skipping line {line_no}: empty rate", file=sys.stderr)
                continue

            try:
                rate = parse_decimal(rate_str)
            except ValueError as e:
                print(f"Skipping line {line_no}: {e}", file=sys.stderr)
                continue

            rows.append({
                "source": args.source.strip(),
                "company_name": args.company_name.strip(),
                "service_key": slugify_service_key(service_name),
                "service_name": service_name,
                "currency": (args.currency.strip() or "USD"),
                "default_rate": rate,
            })

    if args.dry_run:
        for p in rows[:10]:
            print(p)
        print(f"\nDRY RUN: would upsert {len(rows)} rows.")
        return 0

    if not rows:
        print("ERROR: No valid rows parsed from file (check delimiter/headers).", file=sys.stderr)
        return 2

    # --- Write to DB ---
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(ENSURE_UNIQUE_INDEX_SQL)
            for p in rows:
                cur.execute(UPSERT_SQL, p)
        conn.commit()

    print(f"Upserted {len(rows)} rows into z_rate_service.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
