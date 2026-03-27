
import pandas as pd
import sqlalchemy as sa
import re
import pytz
from datetime import datetime
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError


from backend.db.models import PayrollBatch, Ride, ZRateService, ZRateOverride
from backend.db.crud import upsert_person, ensure_rate_services  # your existing function
from backend.services.excel_config import load_excel_config  # wherever it is
from backend.services.service_keys import build_service_key_for_acumen
from backend.services.rates import resolve_rate_for_ride

BAD_STRINGS = {"", "-", "—", "n/a", "na", "none", "null", "<na>", "<nat>", "nan"}


def norm_str(v):
    if v is None or pd.isna(v):
        return None
    s = str(v).strip()
    if not s:
        return None
    if s.lower() in BAD_STRINGS:
        return None
    return s


def norm_service_ref(v):
    """
    Convert numeric-like codes (e.g. 7660064.0) into '7660064'
    """
    s = norm_str(v)
    if not s:
        return None
    # strip a trailing ".0" (common when pandas reads as float)
    if s.endswith(".0") and s.replace(".0", "").isdigit():
        return s[:-2]
    return s

def parse_service_period(period_str: str):
    # "10/18/2025 - 10/24/2025"
    m = re.match(r"\s*(\d{1,2}/\d{1,2}/\d{4})\s*-\s*(\d{1,2}/\d{1,2}/\d{4})\s*", period_str or "")
    if not m:
        return None, None
    start = datetime.strptime(m.group(1), "%m/%d/%Y").date()
    end = datetime.strptime(m.group(2), "%m/%d/%Y").date()
    return start, end

def read_sp_pay_summary(excel_path: str):
    df = pd.read_excel(excel_path, sheet_name="SP PAY SUMMARY")  # ✅ load the sheet :contentReference[oaicite:3]{index=3}

    # normalize headers
    cols = {c.strip().upper(): c for c in df.columns}

    batch_id = str(df.loc[0, cols["BATCH ID"]]).strip()
    company = str(df.loc[0, cols["SP COMPANY"]]).strip()
    period = str(df.loc[0, cols["SERVICE PERIOD"]]).strip()
    period_start, period_end = parse_service_period(period)

    return {
        "batch_id": batch_id,
        "company": company,
        "period_start": period_start,
        "period_end": period_end,
        "service_period_raw": period,
    }

def get_service_default_rate(db, service_name: str, company: str):
    svc = (
        db.query(ZRateService)
        .filter(ZRateService.service_name == service_name)
        .filter(ZRateService.company == company)
        .first()
    )
    return svc.rate if svc else None

def import_payroll_excel(db: Session, xlsx_path: str, cfg_path: str):
    cfg = load_excel_config(cfg_path)
    details_sheet = cfg["sheet_names"]["details"]
    source="acumen"

    summary = read_sp_pay_summary(str(xlsx_path))
    
    internal_to_raw = cfg["columns"]["details"]
    mapper = {raw: internal for internal, raw in internal_to_raw.items()}

    df = pd.read_excel(xlsx_path, sheet_name=details_sheet).rename(columns=mapper)

    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.lower()
        .str.replace(" ", "_", regex=False)
    )

    expected = [
        "batch_id", "company_name",
        "driver_name", "drive_code",
        "date",
        "trip_code", "trip_name",
        "cancellation_reason",
        "miles", "spiff",
        "gross_pay", "deduction", "net_pay",
    ]
    missing = [c for c in expected if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}. Got: {df.columns.tolist()}")

    df = df[expected].copy()

    for c in ("miles", "spiff", "gross_pay", "deduction", "net_pay"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["miles"] = df["miles"] 

    company_file = Path(xlsx_path).stem
    df["source_ref"] = company_file + ":" + df["trip_code"].astype("string")
    df["currency"] = cfg["defaults"].get("currency", "USD")

    period_start = summary["period_start"]
    period_end = summary["period_end"]

    batch = PayrollBatch(
        source=source,
        company_name=str(df["company_name"].iloc[0]) if len(df) else company_file,
        batch_ref=summary["batch_id"],
        currency=df["currency"].iloc[0] if len(df) else "USD",
        period_start=period_start,
        period_end=period_end,
        week_start=period_start,
        week_end=period_end,
        notes=f"imported from {Path(xlsx_path).name}",
    )
    db.add(batch)
    db.flush()

    # ------------------------------------------------------------
    # ------------------------------------------------------------
    # 1) Upsert z_rate_service FIRST (unique per service_name)
    # ------------------------------------------------------------
    # service_key MUST be stable and must NOT include trip code.
    # If you want it source-scoped, keep it as "acumen".
    stable_service_key = "acumen"
    source="acumen"
    # Dedupe by service_name (because service_name is the unique identity)
    service_names: set[str] = set()
    for row in df.itertuples(index=False, name="R"):
        nm = norm_str(row.trip_name)
        if nm:
            service_names.add(nm)

    services = [
        {"service_key": stable_service_key, "service_name": nm, "currency": df["currency"].iloc[0]}
        for nm in sorted(service_names)
    ]

    ensure_rate_services(
        db,
        services,
        source=source,
        company_name=batch.company_name,
    )
    db.flush()

    # Build lookup by service_name (NOT by service_key)
    svc_rows = (
        db.query(ZRateService)
        .filter(
            ZRateService.source == source,
            ZRateService.company_name == batch.company_name,
            ZRateService.service_name.in_(list(service_names)),
        )
        .all()
    )

    service_id_by_name: dict[str, int] = {}
    for s in svc_rows:
        sid = getattr(s, "z_rate_service_id", None) or getattr(s, "id", None)
        if s.service_name:
            service_id_by_name[s.service_name] = sid

    inserted, skipped = 0, 0

    # ------------------------------------------------------------
    # 2) Insert rides; use SAVEPOINT per row (no global rollback)
    # ------------------------------------------------------------
    for row in df.itertuples(index=False, name="R"):
        rowd = row._asdict()

        driver_ext = norm_str(row.drive_code)
        driver_name = norm_str(row.driver_name)

        person = upsert_person(db, external_id=driver_ext, full_name=driver_name)
        if not person:
            skipped += 1
            continue

        ride_dt = row.date if not pd.isna(row.date) else None

        service_name = norm_str(row.trip_name)
        service_code = norm_str(row.trip_code)
        service_ref = norm_service_ref(row.trip_code)

        service_key = source  # stable; NOT trip-based
        svc_id = service_id_by_name.get(service_name)
        source_ref=norm_str(row.source_ref) or f"{company_file}:{service_ref}:{person.person_id}",

        """
        # after trying to read rate from SP PAY Summary
        if z_rate is None:
            z_rate = get_service_default_rate(
                db=db,
                service_name=service_name,
                company=company,
            )

        if z_rate is None:
            z_rate = Decimal("0.00")
        """  
        # if for any reason it’s missing, still resolve by key (or return default)
        z_rate, z_rate_source, z_rate_service_id, z_rate_override_id = resolve_rate_for_ride(
            db=db,
            source=batch.source,
            company_name=batch.company_name,
            service_name=service_name,   # ✅ add this
            ride_date=ride_dt,
            currency=batch.currency,
        )
        gross_pay = float(rowd.get("gross_pay") or 0) or float(z_rate or 0)
        net_pay = float(rowd.get("net_pay") or 0) or float(z_rate or 0)
        deduction = float(rowd.get("deduction") or 0)
        ride = Ride(
            payroll_batch_id=batch.payroll_batch_id,
            person_id=person.person_id,
            ride_start_ts=ride_dt,

            source="acumen",
            source_ref=source_ref,


            service_ref_type="CODE",
            service_name=service_name,
            service_ref=service_ref,

            # keep your existing rate fields
            z_rate=z_rate,
            z_rate_source=z_rate_source,

            # ensure it's linked (prefer resolver output; fallback to lookup)
            z_rate_service_id=z_rate_service_id or svc_id,
            z_rate_override_id=z_rate_override_id,

            miles=row.miles,
            gross_pay=gross_pay,
            net_pay=net_pay,
            deduction=deduction,
            spiff=float(row.spiff or 0),
        )

        try:
            with db.begin_nested():  # ✅ SAVEPOINT per row
                db.add(ride)
                db.flush()
            inserted += 1
        except IntegrityError as e:
            skipped += 1
            #print("SKIP IntegrityError", {"source_ref": ride.source_ref, "err": str(e)})

    db.commit()
    return {
        "source": "acumen",
        "company_name": batch.company_name,   # ✅ add this
        "inserted": inserted,
        "skipped": skipped,
        "payroll_batch_id": batch.payroll_batch_id,
    }
