"""
Import missing Maz Week 11 (2026-03-16 to 2026-03-22) from PDF.

Weeks 4 and 8 were already in the DB under slightly different period_start dates
(2026-01-25 instead of 2026-01-26, and 2026-02-22 instead of 2026-02-23) — but
with matching ride counts and net_pay totals, confirming they are already imported.

Only Week 11 is truly missing and needs to be imported.
"""
from __future__ import annotations
import sys
sys.path.insert(0, "/app")

from pathlib import Path
from backend.db.db import SessionLocal
from backend.services.pdf_reader import (
    extract_tables,
    extract_pdf_text,
    normalize_details_tables,
    bulk_insert_rides,
)
from backend.services.data_extractor import parse_maz_period, parse_maz_receipt_number

MISSING_PDFS = [
    "/data/validate/Maz/Week 11/CashieringReceipt-WASO291-OY2026W11-20260322 (1).pdf",
]

def import_pdf(pdf_path: str) -> None:
    p = Path(pdf_path)
    if not p.exists():
        print(f"ERROR: File not found: {pdf_path}")
        return

    print(f"\n--- Importing: {p.name} ---")
    raw = p.read_bytes()
    tables = extract_tables(raw)
    pdf_text = extract_pdf_text(raw)
    period_start, period_end = parse_maz_period(pdf_text)
    batch_id = parse_maz_receipt_number(pdf_text)
    df = normalize_details_tables(tables, source_file=p.name)

    print(f"  Period:   {period_start} to {period_end}")
    print(f"  Batch ID: {batch_id}")
    print(f"  Rides:    {len(df)}")
    print(f"  Drivers:  {df['Person'].nunique() if not df.empty else 0}")

    if df.empty:
        print("  ERROR: No rides parsed from PDF — aborting.")
        return

    records = df.to_dict(orient="records")
    db = SessionLocal()
    try:
        result = bulk_insert_rides(
            db,
            period_start=period_start,
            period_end=period_end,
            batch_id=batch_id,
            source_file=p.name,
            rides_data=records,
        )
        print(f"  Inserted: {result['inserted']}")
        print(f"  Skipped:  {result['skipped']}")
    finally:
        db.close()


if __name__ == "__main__":
    print("=== Maz Missing Week Import ===")
    print("Weeks 4 and 8 already exist in DB — importing Week 11 only.\n")
    for pdf_path in MISSING_PDFS:
        import_pdf(pdf_path)
    print("\n=== Done ===")
