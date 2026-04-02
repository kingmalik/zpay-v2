"""
validate.py — dry-run accuracy test for Z-Pay payroll calculation.

Reads raw partner files from disk, runs the rate resolver without saving to DB,
then compares calculated z_rate to what is already stored in the database.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, Request, Query
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import Ride, Person, PayrollBatch
from backend.services.rates import resolve_rate_for_ride
from backend.services.excell_reader import read_sp_pay_summary
from backend.services.excel_config import load_excel_config
from backend.services.pdf_reader import extract_tables, extract_pdf_text, normalize_details_tables
from backend.services.data_extractor import parse_maz_period, parse_maz_receipt_number

import os as _os

# ── Paths ─────────────────────────────────────────────────────────────────────
# VALIDATE_PATH can be set per-environment. Default is /data/in/validate/ (Docker).
# On a dev machine, set VALIDATE_PATH=$HOME/Downloads/validate or similar.
_VALIDATE_BASE = Path(_os.environ.get("VALIDATE_PATH", "/data/in/validate"))
ACUMEN_DIR = _VALIDATE_BASE / "Acumen"
MAZ_DIR    = _VALIDATE_BASE / "Maz"
ACU_CFG    = Path(__file__).resolve().parents[1] / "config" / "source" / "acumen.yml"

router = APIRouter(prefix="/validate", tags=["validate"])

_templates = None


def templates():
    global _templates
    if _templates is None:
        templates_dir = Path(__file__).resolve().parents[1] / "templates"
        _templates = Jinja2Templates(directory=str(templates_dir))
    return _templates


BAD = {"", "-", "—", "n/a", "na", "none", "null", "<na>", "<nat>", "nan"}


def _ns(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    s = str(v).strip()
    return None if (not s or s.lower() in BAD) else s


# ── Dry-run parsers ───────────────────────────────────────────────────────────

def _dry_acumen(db: Session, xlsx_path: Path) -> dict:
    """Parse Acumen Excel, resolve z_rates, return per-driver aggregates."""
    cfg = load_excel_config(ACU_CFG)
    summary = read_sp_pay_summary(str(xlsx_path))

    internal_to_raw = cfg["columns"]["details"]
    mapper = {raw: internal for internal, raw in internal_to_raw.items()}
    df = pd.read_excel(xlsx_path, sheet_name=cfg["sheet_names"]["details"]).rename(columns=mapper)
    df.columns = df.columns.astype(str).str.strip().str.lower().str.replace(" ", "_", regex=False)

    for c in ("miles", "spiff", "gross_pay", "deduction", "net_pay"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    company_name = str(df["company_name"].iloc[0]).strip() if len(df) else "Acumen International"

    drivers: dict[str, dict] = {}
    for row in df.itertuples(index=False, name="R"):
        name = _ns(row.driver_name)
        if not name:
            continue
        service = _ns(row.trip_name)
        ride_dt = row.date if not pd.isna(row.date) else None

        z_rate, _, _, _ = resolve_rate_for_ride(
            db=db,
            source="acumen",
            company_name=company_name,
            service_name=service,
            ride_date=ride_dt,
            currency="USD",
        )

        if name not in drivers:
            drivers[name] = {"rides": 0, "z_rate": 0.0, "gross_pay": 0.0, "net_pay": 0.0}
        drivers[name]["rides"] += 1
        drivers[name]["z_rate"]     += float(z_rate or 0)
        drivers[name]["gross_pay"]  += float(row.gross_pay or 0)
        drivers[name]["net_pay"]    += float(row.net_pay or 0)

    for d in drivers.values():
        d["z_rate"]    = round(d["z_rate"], 2)
        d["gross_pay"] = round(d["gross_pay"], 2)
        d["net_pay"]   = round(d["net_pay"], 2)

    return {
        "period_start": summary["period_start"],
        "period_end":   summary["period_end"],
        "company_name": company_name,
        "total_rides":  sum(d["rides"] for d in drivers.values()),
        "total_z_rate": round(sum(d["z_rate"] for d in drivers.values()), 2),
        "total_net_pay": round(sum(d["net_pay"] for d in drivers.values()), 2),
        "drivers": drivers,
    }


def _dry_maz(db: Session, pdf_path: Path) -> dict:
    """Parse Maz PDF, resolve z_rates, return per-driver aggregates."""
    raw = pdf_path.read_bytes()
    tables   = extract_tables(raw)
    pdf_text = extract_pdf_text(raw)

    period_start, period_end = parse_maz_period(pdf_text)
    batch_ref = parse_maz_receipt_number(pdf_text)
    rides_df  = normalize_details_tables(tables, source_file=pdf_path.name)

    if rides_df.empty:
        return None

    records = rides_df.to_dict(orient="records")
    company_name = "everDriven"
    source = "maz"

    drivers: dict[str, dict] = {}
    for row in records:
        name = _ns(str(row.get("Person") or ""))
        if not name:
            continue
        service = _ns(str(row.get("Name") or ""))
        ride_dt = None
        raw_dt = row.get("Date")
        if raw_dt:
            try:
                ride_dt = pd.to_datetime(raw_dt)
            except Exception:
                pass

        z_rate, _, _, _ = resolve_rate_for_ride(
            db=db,
            source=source,
            company_name=company_name,
            service_name=service,
            ride_date=ride_dt,
            currency="USD",
        )

        gross_pay = float(row.get("Gross") or 0)
        net_pay   = float(row.get("Net Pay") or 0)

        if name not in drivers:
            drivers[name] = {"rides": 0, "z_rate": 0.0, "gross_pay": 0.0, "net_pay": 0.0}
        drivers[name]["rides"]     += 1
        drivers[name]["z_rate"]    += float(z_rate or 0)
        drivers[name]["gross_pay"] += gross_pay
        drivers[name]["net_pay"]   += net_pay

    for d in drivers.values():
        d["z_rate"]    = round(d["z_rate"], 2)
        d["gross_pay"] = round(d["gross_pay"], 2)
        d["net_pay"]   = round(d["net_pay"], 2)

    return {
        "period_start": period_start,
        "period_end":   period_end,
        "batch_ref":    batch_ref,
        "company_name": company_name,
        "total_rides":  sum(d["rides"] for d in drivers.values()),
        "total_z_rate": round(sum(d["z_rate"] for d in drivers.values()), 2),
        "total_net_pay": round(sum(d["net_pay"] for d in drivers.values()), 2),
        "drivers": drivers,
    }


def _db_data(db: Session, source: str, period_start) -> dict | None:
    """Pull per-driver totals from DB for a given batch (matched by source + period_start)."""
    batch = (
        db.query(PayrollBatch)
        .filter(PayrollBatch.source == source, PayrollBatch.period_start == period_start)
        .first()
    )
    if not batch:
        return None

    rows = (
        db.query(
            Person.full_name,
            func.count(Ride.ride_id).label("rides"),
            func.sum(Ride.z_rate).label("z_rate"),
            func.sum(Ride.net_pay).label("net_pay"),
        )
        .join(Ride, Ride.person_id == Person.person_id)
        .filter(Ride.payroll_batch_id == batch.payroll_batch_id)
        .group_by(Person.full_name)
        .all()
    )

    drivers = {
        r.full_name: {
            "rides":   int(r.rides or 0),
            "z_rate":  round(float(r.z_rate or 0), 2),
            "net_pay": round(float(r.net_pay or 0), 2),
        }
        for r in rows
    }
    return {
        "payroll_batch_id": batch.payroll_batch_id,
        "total_rides":   sum(d["rides"] for d in drivers.values()),
        "total_z_rate":  round(sum(d["z_rate"] for d in drivers.values()), 2),
        "total_net_pay": round(sum(d["net_pay"] for d in drivers.values()), 2),
        "drivers": drivers,
    }


def _merge_drivers(file_drivers: dict, db_drivers: dict) -> list[dict]:
    all_names = sorted(set(file_drivers) | set(db_drivers))
    out = []
    for name in all_names:
        fd = file_drivers.get(name, {"rides": 0, "z_rate": 0.0, "gross_pay": 0.0, "net_pay": 0.0})
        dd = db_drivers.get(name,  {"rides": 0, "z_rate": 0.0, "net_pay": 0.0})
        variance = round(fd["z_rate"] - dd["z_rate"], 2)
        out.append({
            "name":          name,
            "file_rides":    fd["rides"],
            "db_rides":      dd["rides"],
            "file_z_rate":   fd["z_rate"],
            "db_z_rate":     dd["z_rate"],
            "file_gross_pay": fd.get("gross_pay", 0.0),
            "file_net_pay":  fd.get("net_pay", 0.0),
            "db_net_pay":    dd.get("net_pay", 0.0),
            "variance":      variance,
            "match":         abs(variance) < 0.02,
        })
    return sorted(out, key=lambda x: -x["file_z_rate"])


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/", name="validate_page")
def validate_page(
    request: Request,
    source: str = Query("acumen"),
    week: str | None = Query(None),
    db: Session = Depends(get_db),
):
    weeks_out = []

    if source == "acumen" and ACUMEN_DIR.exists():
        week_dirs = sorted(ACUMEN_DIR.iterdir())
        for wdir in week_dirs:
            if week and wdir.name != week:
                continue
            xlsx_files = list(wdir.glob("*.xlsx"))
            if not xlsx_files:
                continue
            try:
                fd = _dry_acumen(db, xlsx_files[0])
                dd = _db_data(db, "acumen", fd["period_start"])
                variance = round(fd["total_z_rate"] - (dd["total_z_rate"] if dd else 0), 2)
                weeks_out.append({
                    "week":           wdir.name,
                    "file":           xlsx_files[0].name,
                    "period_start":   fd["period_start"].strftime("%-m/%-d/%Y") if fd["period_start"] else "—",
                    "period_end":     fd["period_end"].strftime("%-m/%-d/%Y") if fd["period_end"] else "—",
                    "file_rides":     fd["total_rides"],
                    "db_rides":       dd["total_rides"] if dd else 0,
                    "file_z_rate":    fd["total_z_rate"],
                    "db_z_rate":      dd["total_z_rate"] if dd else 0.0,
                    "file_net_pay":   fd["total_net_pay"],
                    "db_net_pay":     dd["total_net_pay"] if dd else 0.0,
                    "variance":       variance,
                    "db_found":       dd is not None,
                    "drivers":        _merge_drivers(fd["drivers"], dd["drivers"] if dd else {}),
                })
            except Exception as exc:
                weeks_out.append({"week": wdir.name, "error": str(exc)})

    elif source == "maz" and MAZ_DIR.exists():
        week_dirs = sorted(MAZ_DIR.iterdir())
        for wdir in week_dirs:
            if week and wdir.name != week:
                continue
            pdf_files = list(wdir.glob("*.pdf"))
            if not pdf_files:
                continue
            try:
                fd = _dry_maz(db, pdf_files[0])
                if not fd:
                    continue
                dd = _db_data(db, "maz", fd["period_start"])
                variance = round(fd["total_z_rate"] - (dd["total_z_rate"] if dd else 0), 2)
                weeks_out.append({
                    "week":           wdir.name,
                    "file":           pdf_files[0].name,
                    "period_start":   fd["period_start"].strftime("%-m/%-d/%Y") if fd["period_start"] else "—",
                    "period_end":     fd["period_end"].strftime("%-m/%-d/%Y") if fd["period_end"] else "—",
                    "file_rides":     fd["total_rides"],
                    "db_rides":       dd["total_rides"] if dd else 0,
                    "file_z_rate":    fd["total_z_rate"],
                    "db_z_rate":      dd["total_z_rate"] if dd else 0.0,
                    "file_net_pay":   fd["total_net_pay"],
                    "db_net_pay":     dd["total_net_pay"] if dd else 0.0,
                    "variance":       variance,
                    "db_found":       dd is not None,
                    "drivers":        _merge_drivers(fd["drivers"], dd["drivers"] if dd else {}),
                })
            except Exception as exc:
                weeks_out.append({"week": wdir.name, "error": str(exc)})

    # Grand totals (only clean weeks)
    clean = [w for w in weeks_out if "error" not in w]
    grand = {
        "file_z_rate":  round(sum(w["file_z_rate"] for w in clean), 2),
        "db_z_rate":    round(sum(w["db_z_rate"] for w in clean), 2),
        "file_net_pay": round(sum(w["file_net_pay"] for w in clean), 2),
        "file_rides":   sum(w["file_rides"] for w in clean),
        "db_rides":     sum(w["db_rides"] for w in clean),
    }
    grand["variance"] = round(grand["file_z_rate"] - grand["db_z_rate"], 2)

    return templates().TemplateResponse(
        request,
        "validate.html",
        {
            "source":       source,
            "weeks":        weeks_out,
            "selected_week": week,
            "grand":        grand,
            "acumen_count": len(list(ACUMEN_DIR.iterdir())) if ACUMEN_DIR.exists() else 0,
            "maz_count":    len(list(MAZ_DIR.iterdir()))    if MAZ_DIR.exists()    else 0,
        },
    )
