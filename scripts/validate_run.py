#!/usr/bin/env python3
"""
validate_run.py — Run accuracy test comparing Z-Pay calculated z_rate
against DB stored values for all Acumen and Maz files.
"""
import sys
sys.path.insert(0, "/app")

from pathlib import Path
import pandas as pd
from backend.db.db import SessionLocal
from backend.services.rates import resolve_rate_for_ride
from backend.services.excell_reader import read_sp_pay_summary
from backend.services.excel_config import load_excel_config
from backend.services.pdf_reader import extract_tables, extract_pdf_text, normalize_details_tables
from backend.services.data_extractor import parse_maz_period
from backend.db.models import Ride, Person, PayrollBatch
from sqlalchemy import func

BAD = {"", "-", "—", "n/a", "na", "none", "null", "<na>", "<nat>", "nan"}
ACU_CFG   = Path("/app/backend/config/source/acumen.yml")
ACUMEN_DIR = Path("/data/validate/Acumen")
MAZ_DIR    = Path("/data/validate/Maz")


def ns(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    s = str(v).strip()
    return None if (not s or s.lower() in BAD) else s


def dry_acumen(db, xlsx_path):
    cfg = load_excel_config(ACU_CFG)
    summary = read_sp_pay_summary(str(xlsx_path))
    mapper = {raw: internal for internal, raw in cfg["columns"]["details"].items()}
    df = pd.read_excel(xlsx_path, sheet_name=cfg["sheet_names"]["details"]).rename(columns=mapper)
    df.columns = df.columns.astype(str).str.strip().str.lower().str.replace(" ", "_", regex=False)
    for c in ("gross_pay", "deduction", "net_pay", "miles", "spiff"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    company = str(df["company_name"].iloc[0]).strip() if len(df) else "Acumen International"
    drivers = {}
    for row in df.itertuples(index=False, name="R"):
        name = ns(row.driver_name)
        if not name:
            continue
        service = ns(row.trip_name)
        ride_dt = row.date if not pd.isna(row.date) else None
        z_rate, _, _, _ = resolve_rate_for_ride(db=db, source="acumen", company_name=company, service_name=service, ride_date=ride_dt, currency="USD")
        if name not in drivers:
            drivers[name] = {"rides": 0, "z_rate": 0.0, "net_pay": 0.0, "gross_pay": 0.0}
        drivers[name]["rides"] += 1
        drivers[name]["z_rate"]    += float(z_rate or 0)
        drivers[name]["net_pay"]   += float(row.net_pay or 0)
        drivers[name]["gross_pay"] += float(row.gross_pay or 0)
    for d in drivers.values():
        d["z_rate"]    = round(d["z_rate"], 2)
        d["net_pay"]   = round(d["net_pay"], 2)
        d["gross_pay"] = round(d["gross_pay"], 2)
    return {
        "period_start": summary["period_start"],
        "period_end":   summary["period_end"],
        "company":      company,
        "total_rides":  sum(d["rides"]   for d in drivers.values()),
        "total_z_rate": round(sum(d["z_rate"]  for d in drivers.values()), 2),
        "total_net_pay":round(sum(d["net_pay"] for d in drivers.values()), 2),
        "drivers":      drivers,
    }


def dry_maz(db, pdf_path):
    raw = pdf_path.read_bytes()
    tables   = extract_tables(raw)
    pdf_text = extract_pdf_text(raw)
    period_start, period_end = parse_maz_period(pdf_text)
    rides_df = normalize_details_tables(tables, source_file=pdf_path.name)
    if rides_df.empty:
        return None
    records = rides_df.to_dict(orient="records")
    drivers = {}
    for row in records:
        name = ns(str(row.get("Person") or ""))
        if not name:
            continue
        service = ns(str(row.get("Name") or ""))
        ride_dt = None
        try:
            ride_dt = pd.to_datetime(row.get("Date"))
        except Exception:
            pass
        z_rate, _, _, _ = resolve_rate_for_ride(db=db, source="maz", company_name="everDriven", service_name=service, ride_date=ride_dt, currency="USD")
        net_pay = float(row.get("Net Pay") or 0)
        gross   = float(row.get("Gross") or 0)
        if name not in drivers:
            drivers[name] = {"rides": 0, "z_rate": 0.0, "net_pay": 0.0, "gross_pay": 0.0}
        drivers[name]["rides"]     += 1
        drivers[name]["z_rate"]    += float(z_rate or 0)
        drivers[name]["net_pay"]   += net_pay
        drivers[name]["gross_pay"] += gross
    for d in drivers.values():
        d["z_rate"]    = round(d["z_rate"], 2)
        d["net_pay"]   = round(d["net_pay"], 2)
        d["gross_pay"] = round(d["gross_pay"], 2)
    return {
        "period_start": period_start,
        "period_end":   period_end,
        "total_rides":  sum(d["rides"]   for d in drivers.values()),
        "total_z_rate": round(sum(d["z_rate"]  for d in drivers.values()), 2),
        "total_net_pay":round(sum(d["net_pay"] for d in drivers.values()), 2),
        "drivers":      drivers,
    }


def db_totals(db, source, period_start):
    batch = db.query(PayrollBatch).filter(
        PayrollBatch.source == source,
        PayrollBatch.period_start == period_start
    ).first()
    if not batch:
        return None
    rows = (
        db.query(
            Person.full_name,
            func.sum(Ride.z_rate).label("z"),
            func.sum(Ride.net_pay).label("np"),
            func.count(Ride.ride_id).label("r"),
        )
        .join(Ride, Ride.person_id == Person.person_id)
        .filter(Ride.payroll_batch_id == batch.payroll_batch_id)
        .group_by(Person.full_name)
        .all()
    )
    drivers = {
        r.full_name: {
            "z_rate":  round(float(r.z  or 0), 2),
            "net_pay": round(float(r.np or 0), 2),
            "rides":   int(r.r or 0),
        }
        for r in rows
    }
    return {
        "total_z_rate":  round(sum(d["z_rate"]  for d in drivers.values()), 2),
        "total_net_pay": round(sum(d["net_pay"] for d in drivers.values()), 2),
        "total_rides":   sum(d["rides"]   for d in drivers.values()),
        "drivers":       drivers,
    }


def run():
    db = SessionLocal()

    # ── ACUMEN ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("ACUMEN VALIDATION  (Z-Pay calculated vs DB stored z_rate)")
    print("=" * 80)
    print(f"{'Week':<10} {'Period':<25} {'Rides':>6} {'Partner Pay':>13} {'Z-Pay Calc':>12} {'DB Stored':>12} {'Variance':>10}")
    print("-" * 80)
    acu = {"calc": 0.0, "db": 0.0, "rides": 0, "partner": 0.0}

    for wdir in sorted(ACUMEN_DIR.iterdir()):
        xlsx = list(wdir.glob("*.xlsx"))
        if not xlsx:
            continue
        print(f"  processing {wdir.name}...", end="", flush=True)
        try:
            fd = dry_acumen(db, xlsx[0])
            dd = db_totals(db, "acumen", fd["period_start"])
            db_z = dd["total_z_rate"] if dd else 0.0
            var  = round(fd["total_z_rate"] - db_z, 2)
            period = f"{fd['period_start'].strftime('%m/%d')} - {fd['period_end'].strftime('%m/%d/%Y')}"
            print(f"\r{wdir.name:<10} {period:<25} {fd['total_rides']:>6} ${fd['total_net_pay']:>12,.2f} ${fd['total_z_rate']:>11,.2f} ${db_z:>11,.2f} ${var:>+9,.2f}")
            acu["calc"]    += fd["total_z_rate"]
            acu["db"]      += db_z
            acu["rides"]   += fd["total_rides"]
            acu["partner"] += fd["total_net_pay"]
        except Exception as e:
            print(f"\r{wdir.name:<10} ERROR: {e}")

    print("-" * 80)
    print(f"{'TOTAL':<10} {'6 weeks':<25} {acu['rides']:>6} ${acu['partner']:>12,.2f} ${acu['calc']:>11,.2f} ${acu['db']:>11,.2f} ${acu['calc']-acu['db']:>+9,.2f}")

    # ── MAZ ───────────────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("MAZ VALIDATION  (Z-Pay calculated vs DB stored z_rate)")
    print("=" * 80)
    print(f"{'Week':<10} {'Period':<25} {'Rides':>6} {'Partner Pay':>13} {'Z-Pay Calc':>12} {'DB Stored':>12} {'Variance':>10}")
    print("-" * 80)
    maz = {"calc": 0.0, "db": 0.0, "rides": 0, "partner": 0.0}

    for wdir in sorted(MAZ_DIR.iterdir()):
        pdfs = list(wdir.glob("*.pdf"))
        if not pdfs:
            continue
        print(f"  processing {wdir.name}...", end="", flush=True)
        try:
            fd = dry_maz(db, pdfs[0])
            if not fd:
                print(f"\r{wdir.name:<10} SKIP: no rides parsed")
                continue
            dd = db_totals(db, "maz", fd["period_start"])
            db_z = dd["total_z_rate"] if dd else 0.0
            var  = round(fd["total_z_rate"] - db_z, 2)
            period = f"{fd['period_start'].strftime('%m/%d')} - {fd['period_end'].strftime('%m/%d/%Y')}"
            print(f"\r{wdir.name:<10} {period:<25} {fd['total_rides']:>6} ${fd['total_net_pay']:>12,.2f} ${fd['total_z_rate']:>11,.2f} ${db_z:>11,.2f} ${var:>+9,.2f}")
            maz["calc"]    += fd["total_z_rate"]
            maz["db"]      += db_z
            maz["rides"]   += fd["total_rides"]
            maz["partner"] += fd["total_net_pay"]
        except Exception as e:
            print(f"\r{wdir.name:<10} ERROR: {e}")

    print("-" * 80)
    print(f"{'TOTAL':<10} {'9 weeks':<25} {maz['rides']:>6} ${maz['partner']:>12,.2f} ${maz['calc']:>11,.2f} ${maz['db']:>11,.2f} ${maz['calc']-maz['db']:>+9,.2f}")

    # ── GRAND TOTAL ───────────────────────────────────────────────────────────
    total_calc = acu["calc"] + maz["calc"]
    total_db   = acu["db"]   + maz["db"]
    total_part = acu["partner"] + maz["partner"]
    total_rides = acu["rides"] + maz["rides"]
    print("\n" + "=" * 80)
    print("GRAND TOTAL — Acumen + Maz")
    print("=" * 80)
    print(f"  Rides processed : {total_rides:,}")
    print(f"  Partner paid in : ${total_part:,.2f}")
    print(f"  Z-Pay calculated: ${total_calc:,.2f}")
    print(f"  DB stored       : ${total_db:,.2f}")
    print(f"  Variance        : ${total_calc - total_db:+,.2f}")
    print(f"  Profit (Partner - Z-Pay calc): ${total_part - total_calc:,.2f}")
    print("=" * 80)

    db.close()


if __name__ == "__main__":
    run()
