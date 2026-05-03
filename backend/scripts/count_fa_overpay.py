"""
FA-canceled overpay audit script.

Identifies historical rides where:
  - source = 'acumen'  (FirstAlt / Acumen rides)
  - z_rate_source = 'canceled_trip'  (FA canceled, old code paid driver regardless)
  - net_pay = 0  (FA did NOT pay Maz — the bug: Maz fronted driver pay it never received)
  - z_rate > 0  (driver was paid something)

The fix shipped in commit a71351d (2026-05-02) corrects NEW ingest going forward.
Historical rides were not re-rated.  This script counts and reports the exposure
so Malik can decide: adjust (clawback / write off) vs leave as-is.

READ-ONLY.  No UPDATE or DELETE statements anywhere in this file.

Usage:
    python -m backend.scripts.count_fa_overpay
    python -m backend.scripts.count_fa_overpay --export-csv /tmp/fa_overpay.csv

Flags:
    --export-csv PATH   Dump all matching rides to a CSV file (default: off)
    --help              Show this message

Run inside the Railway container:
    railway run --service zpay-v2 python -m backend.scripts.count_fa_overpay
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from backend.db.db import SessionLocal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_money(val: Any) -> str:
    if val is None:
        return "$0.00"
    return f"${float(val):,.2f}"


def _fmt_date(val: Any) -> str:
    if val is None:
        return "N/A"
    if isinstance(val, (datetime, date)):
        return str(val)[:10]
    return str(val)[:10]


def _log(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

_OVERPAY_SQL = text("""
SELECT
    r.ride_id,
    r.ride_start_ts,
    r.service_name,
    r.z_rate,
    r.net_pay,
    r.z_rate_source,
    r.source_ref,
    r.person_id,
    p.full_name,
    pb.week_start
FROM ride r
JOIN person  p  ON p.person_id  = r.person_id
JOIN payroll_batch pb ON pb.payroll_batch_id = r.payroll_batch_id
WHERE
    r.source            = 'acumen'
    AND r.z_rate_source = 'canceled_trip'
    AND r.net_pay       = 0
    AND r.z_rate        > 0
ORDER BY r.ride_start_ts DESC
""")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_audit(export_csv: str | None = None) -> None:
    db = SessionLocal()
    try:
        rows = db.execute(_OVERPAY_SQL).fetchall()
    finally:
        db.close()

    if not rows:
        _log("\nFA-canceled overpay audit")
        _log("==========================")
        _log("No overpay rides found.  All FA-canceled rides with net_pay=0 have z_rate=0.")
        _log("Historical data is clean (or no FA-canceled rides exist yet).")
        return

    # ---- Aggregate -----------------------------------------------------------
    total_overpaid: Decimal = Decimal("0")
    drivers: dict[int, dict[str, Any]] = {}
    by_week: dict[str, dict[str, Any]] = defaultdict(lambda: {"rides": 0, "amount": Decimal("0")})
    date_min: str | None = None
    date_max: str | None = None

    for row in rows:
        z_rate = Decimal(str(row.z_rate or 0))
        total_overpaid += z_rate

        # per-driver
        pid = row.person_id
        if pid not in drivers:
            drivers[pid] = {
                "person_id": pid,
                "name": row.full_name or f"pid={pid}",
                "rides": 0,
                "amount": Decimal("0"),
            }
        drivers[pid]["rides"] += 1
        drivers[pid]["amount"] += z_rate

        # per-week
        wk = _fmt_date(row.week_start) if row.week_start else _fmt_date(row.ride_start_ts)
        by_week[wk]["rides"] += 1
        by_week[wk]["amount"] += z_rate

        # date range
        rd = _fmt_date(row.ride_start_ts)
        if date_min is None or rd < date_min:
            date_min = rd
        if date_max is None or rd > date_max:
            date_max = rd

    top_drivers = sorted(drivers.values(), key=lambda d: d["amount"], reverse=True)[:10]
    sorted_weeks = sorted(by_week.items())  # chronological

    # ---- Report --------------------------------------------------------------
    _log("")
    _log("FA-canceled overpay audit")
    _log("==========================")
    _log(f"Total overpay rides:   {len(rows)}")
    _log(f"Total $ overpaid:      {_fmt_money(total_overpaid)}")
    _log(f"Drivers affected:      {len(drivers)}")
    _log(f"Date range:            {date_min} -> {date_max}")
    _log("")

    _log("Top 10 drivers by overpay $:")
    _log(f"  {'driver_id':<10}  {'name':<28}  {'rides':>5}   {'$overpaid':>10}")
    _log(f"  {'-'*10}  {'-'*28}  {'-'*5}   {'-'*10}")
    for d in top_drivers:
        _log(
            f"  {d['person_id']:<10}  {d['name']:<28}  {d['rides']:>5}   "
            f"{_fmt_money(d['amount']):>10}"
        )

    _log("")
    _log("By week:")
    _log(f"  {'week_start':<12}  {'rides':>5}  {'$overpaid':>10}")
    _log(f"  {'-'*12}  {'-'*5}  {'-'*10}")
    for wk, data in sorted_weeks:
        _log(f"  {wk:<12}  {data['rides']:>5}  {_fmt_money(data['amount']):>10}")

    _log("")
    _log("Sample 5 rides (most recent):")
    _log(
        f"  {'ride_id':<10}  {'date':<12}  {'service_name':<30}  "
        f"{'z_rate':>8}  {'net_pay':>8}  {'z_rate_source':<22}  source_ref"
    )
    _log(
        f"  {'-'*10}  {'-'*12}  {'-'*30}  "
        f"{'-'*8}  {'-'*8}  {'-'*22}  {'-'*20}"
    )
    for row in rows[:5]:
        _log(
            f"  {row.ride_id:<10}  {_fmt_date(row.ride_start_ts):<12}  "
            f"{(row.service_name or ''):<30}  "
            f"{_fmt_money(row.z_rate):>8}  {_fmt_money(row.net_pay):>8}  "
            f"{(row.z_rate_source or ''):< 22}  {row.source_ref or ''}"
        )

    _log("")
    _log("Next step: share this output with Malik to decide adjust vs write-off.")
    _log("This script made zero changes to the database.")

    # ---- CSV export ----------------------------------------------------------
    if export_csv:
        cols = [
            "ride_id", "ride_start_ts", "week_start", "person_id", "full_name",
            "service_name", "z_rate", "net_pay", "z_rate_source", "source_ref",
        ]
        with open(export_csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=cols)
            writer.writeheader()
            for row in rows:
                writer.writerow({
                    "ride_id": row.ride_id,
                    "ride_start_ts": _fmt_date(row.ride_start_ts),
                    "week_start": _fmt_date(row.week_start),
                    "person_id": row.person_id,
                    "full_name": row.full_name,
                    "service_name": row.service_name,
                    "z_rate": float(row.z_rate or 0),
                    "net_pay": float(row.net_pay or 0),
                    "z_rate_source": row.z_rate_source,
                    "source_ref": row.source_ref,
                })
        _log(f"\nCSV written to: {export_csv}  ({len(rows)} rows)")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only audit: count FA-canceled rides where driver was paid "
            "but FA never paid Maz (net_pay=0, z_rate>0)."
        )
    )
    parser.add_argument(
        "--export-csv",
        metavar="PATH",
        default=None,
        help="Dump all matching rides to a CSV file at PATH.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    run_audit(export_csv=args.export_csv)


if __name__ == "__main__":
    main(sys.argv[1:])
