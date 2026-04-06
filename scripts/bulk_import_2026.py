"""
Bulk import all 2026 payroll files + update driver info from TIN file.

Run inside Docker:
  docker exec z-pay-app-1 python3 /app/scripts/bulk_import_2026.py
"""
import sys
import re
import os
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy.exc import IntegrityError

sys.path.insert(0, "/app")

from backend.db.db import SessionLocal
from backend.db.models import PayrollBatch, Ride, Person
from backend.db.crud import upsert_person
from backend.services.excell_reader import import_payroll_excel
from backend.services.rates import resolve_rate_for_ride

FILES_DIR = Path("/tmp/re_files")
ACU_CFG = Path("/app/backend/config/source/acumen.yml")

ACUMEN_FILES = sorted(FILES_DIR.glob("Prod_SP_Acumen International_*.xlsx"))
EVERDRIVEN_FILES = sorted(FILES_DIR.glob("CashieringReceipt-*.xlsx"))
DRIVER_FILE = FILES_DIR / "Driver's TIN.xlsx"


# ── helpers ──────────────────────────────────────────────────────────────────

def norm(v):
    if v is None:
        return None
    try:
        import pandas as _pd
        if _pd.isna(v):
            return None
    except Exception:
        pass
    s = str(v).strip()
    return s if s and s.lower() not in {"nan", "none", "nat", "-", "n/a"} else None


def parse_ed_period_from_filename(filename: str):
    """CashieringReceipt-WASO291-OY2026W01-20260111.xlsx -> (2026-01-05, 2026-01-11)"""
    m = re.search(r"(\d{8})", filename)
    if not m:
        return None, None
    end_date = datetime.strptime(m.group(1), "%Y%m%d").date()
    start_date = end_date - timedelta(days=6)
    return start_date, end_date


def parse_ed_table1(xlsx_path: Path):
    """
    Read Table 1 sheet from an EverDriven Excel file using positional access.
    Row 0 is the header row; data starts at row 1.
    Positions: 0=Person, 1=Code, 7=Runs, 8=Miles, 9=Gross, 10=RAD, 11=WUD, 13=Net Pay
    """
    df = pd.read_excel(str(xlsx_path), sheet_name="Table 1", header=None)
    # Skip header row; use integer positional columns to avoid duplicate-name issues
    df = df.iloc[1:].reset_index(drop=True)

    def safe_float(series_val):
        try:
            f = float(series_val)
            return 0.0 if pd.isna(f) else f
        except Exception:
            return 0.0

    records = []
    for _, row in df.iterrows():
        person = norm(row.iloc[0])
        if not person or person.upper() in ("TOTAL", "PERSON", "SUMMARY"):
            continue

        code = norm(row.iloc[1])
        runs = int(safe_float(row.iloc[7]))
        miles = safe_float(row.iloc[8])
        gross = safe_float(row.iloc[9])
        rad = safe_float(row.iloc[10])
        wud = safe_float(row.iloc[11])
        net_pay = safe_float(row.iloc[13])

        records.append({
            "person": person,
            "code": code,
            "runs": runs,
            "miles": miles,
            "gross": gross,
            "rad": rad,
            "wud": wud,
            "net_pay": net_pay,
        })

    return records


# ── ACUMEN IMPORT ─────────────────────────────────────────────────────────────

def import_acumen_files():
    print("\n" + "="*60)
    print("IMPORTING ACUMEN FILES")
    print("="*60)
    total_inserted = total_skipped = 0

    for f in ACUMEN_FILES:
        db = SessionLocal()
        try:
            print(f"\n  → {f.name}")
            result = import_payroll_excel(db, str(f), ACU_CFG)
            print(f"     inserted={result['inserted']}  skipped={result['skipped']}  batch_id={result['payroll_batch_id']}")
            total_inserted += result["inserted"]
            total_skipped += result["skipped"]
        except Exception as e:
            print(f"     ERROR: {e}")
        finally:
            db.close()

    print(f"\nAcumen total: inserted={total_inserted}  skipped={total_skipped}")


# ── EVERDRIVEN IMPORT ─────────────────────────────────────────────────────────

def import_everdriven_files():
    print("\n" + "="*60)
    print("IMPORTING EVERDRIVEN FILES")
    print("="*60)
    total_inserted = total_skipped = 0

    for f in EVERDRIVEN_FILES:
        db = SessionLocal()
        try:
            print(f"\n  → {f.name}")
            period_start, period_end = parse_ed_period_from_filename(f.name)
            if not period_start:
                print("     SKIP: could not parse period from filename")
                continue

            records = parse_ed_table1(f)
            if not records:
                print("     SKIP: no driver records found in Table 1")
                continue

            # Check if batch already exists
            existing = db.query(PayrollBatch).filter(
                PayrollBatch.batch_ref == f.stem,
                PayrollBatch.source == "maz"
            ).first()
            if existing:
                print(f"     SKIP: batch already exists (id={existing.payroll_batch_id})")
                continue

            batch = PayrollBatch(
                source="maz",
                company_name="everDriven",
                batch_ref=f.stem,
                currency="USD",
                period_start=period_start,
                period_end=period_end,
                week_start=period_start,
                week_end=period_end,
                notes=f"bulk import from {f.name}",
            )
            db.add(batch)
            db.flush()

            inserted = skipped = 0
            for rec in records:
                person = upsert_person(db, external_id=rec["code"], full_name=rec["person"])
                if not person:
                    skipped += 1
                    continue

                source_ref = f"maz:{f.stem}:{rec['code'] or rec['person']}"

                # Deduction = RAD + WUD
                deduction = rec["rad"] + rec["wud"]
                gross = rec["gross"]
                net_pay = rec["net_pay"]

                z_rate, z_rate_source, z_rate_service_id, z_rate_override_id = resolve_rate_for_ride(
                    db=db,
                    source="maz",
                    company_name="everDriven",
                    service_name="EverDriven Weekly Summary",
                    ride_date=period_start,
                    currency="USD",
                )

                ride = Ride(
                    payroll_batch_id=batch.payroll_batch_id,
                    person_id=person.person_id,
                    ride_start_ts=datetime.combine(period_start, datetime.min.time()),
                    source="maz",
                    source_ref=source_ref,
                    service_ref_type="WEEKLY",
                    service_name="EverDriven Weekly Summary",
                    service_ref=rec["code"],
                    z_rate=z_rate,
                    z_rate_source=z_rate_source,
                    z_rate_service_id=z_rate_service_id,
                    z_rate_override_id=z_rate_override_id,
                    miles=rec["miles"],
                    gross_pay=gross,
                    net_pay=net_pay,
                    deduction=deduction,
                    spiff=0,
                )

                try:
                    with db.begin_nested():
                        db.add(ride)
                        db.flush()
                    inserted += 1
                except IntegrityError:
                    skipped += 1

            db.commit()
            print(f"     period={period_start} – {period_end}  drivers={len(records)}  inserted={inserted}  skipped={skipped}  batch_id={batch.payroll_batch_id}")
            total_inserted += inserted
            total_skipped += skipped

        except Exception as e:
            db.rollback()
            print(f"     ERROR: {e}")
            import traceback; traceback.print_exc()
        finally:
            db.close()

    print(f"\nEverDriven total: inserted={total_inserted}  skipped={total_skipped}")


# ── DRIVER INFO UPDATE ────────────────────────────────────────────────────────

def update_driver_info():
    print("\n" + "="*60)
    print("UPDATING DRIVER INFO FROM TIN FILE")
    print("="*60)

    # Use the TIN sheet (most complete: 159 drivers)
    tin_df = pd.read_excel(str(DRIVER_FILE), sheet_name="TIN")
    area_df = pd.read_excel(str(DRIVER_FILE), sheet_name="By Area")

    # Build email/phone lookup by normalized name
    info = {}
    for _, row in tin_df.iterrows():
        name = norm(row.get("Driver Name"))
        if not name:
            continue
        email = norm(row.get("Email", ""))
        phone = norm(row.get("Phone", ""))
        lic = norm(row.get("LIC#", ""))
        tin = norm(row.get("TIN", ""))
        # Strip leading tab from emails (some have \t prefix)
        if email:
            email = email.lstrip("\t").strip()
        info[name.lower()] = {"email": email, "phone": phone, "license": lic, "tin": tin}

    # Build area/app lookup
    area_info = {}
    for _, row in area_df.iterrows():
        name = norm(row.get("Driver Name"))
        if not name:
            continue
        area = norm(row.get("Area", ""))
        app = norm(row.get("App", ""))
        area_info[name.lower()] = {"area": area, "app": app}

    db = SessionLocal()
    updated = not_found = already_set = 0
    unmatched_names = []

    try:
        persons = db.query(Person).all()
        for person in persons:
            key = person.full_name.lower().strip() if person.full_name else ""
            match = info.get(key)

            if not match:
                # Try partial match: first + last name
                key_parts = key.split()
                found_key = None
                for ikey in info:
                    iparts = ikey.split()
                    if len(key_parts) >= 2 and len(iparts) >= 2:
                        if key_parts[0] == iparts[0] and key_parts[-1] == iparts[-1]:
                            found_key = ikey
                            break
                if found_key:
                    match = info[found_key]
                else:
                    not_found += 1
                    unmatched_names.append(person.full_name)
                    continue

            changed = False
            if match.get("email") and not person.email:
                person.email = match["email"]
                changed = True
            elif match.get("email") and person.email and person.email != match["email"]:
                # File takes precedence for email updates
                person.email = match["email"]
                changed = True

            if match.get("phone") and not person.phone:
                person.phone = match["phone"]
                changed = True

            if changed:
                updated += 1
            else:
                already_set += 1

        db.commit()
        print(f"  Updated: {updated}")
        print(f"  Already had info: {already_set}")
        print(f"  No match in file: {not_found}")
        if unmatched_names:
            print(f"\n  Drivers in DB not found in TIN file ({len(unmatched_names)}):")
            for n in sorted(unmatched_names)[:30]:
                print(f"    - {n}")
            if len(unmatched_names) > 30:
                print(f"    ... and {len(unmatched_names)-30} more")

    except Exception as e:
        db.rollback()
        print(f"  ERROR: {e}")
        import traceback; traceback.print_exc()
    finally:
        db.close()


# ── MAIN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Z-Pay 2026 Bulk Import")
    print(f"Acumen files:    {len(ACUMEN_FILES)}")
    print(f"EverDriven files:{len(EVERDRIVEN_FILES)}")
    print(f"Driver file:     {'found' if DRIVER_FILE.exists() else 'MISSING'}")

    import_acumen_files()
    import_everdriven_files()
    update_driver_info()

    print("\n✓ Done.")
