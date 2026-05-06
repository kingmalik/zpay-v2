from __future__ import annotations
import io
import hashlib
import math
from datetime import date, datetime, timezone, time
from typing import List, Tuple
import re

import pdfplumber
import pandas as pd
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from backend.db.models import Ride, Person, PayrollBatch, ZRateService
from backend.services.rates import resolve_rate_for_ride
from backend.db.crud import upsert_person, ensure_rate_services


EXPECTED_COLS = ["Person", "Code", "Date", "Key", "Name", "Miles", "Gross", "RAD", "WUD", "Net Pay"]
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

def _nan_to_zero(v) -> float:
    """Convert a value to float, treating None and NaN as 0.0.

    pandas stores missing numeric cells as float('nan') in to_dict() output.
    The expression ``float(nan or 0)`` does NOT work because ``nan or 0``
    evaluates to ``nan`` (NaN is truthy), producing a NaN result instead of 0.
    This helper guards against that by explicitly checking math.isnan.
    """
    if v is None:
        return 0.0
    try:
        f = float(v)
        return 0.0 if math.isnan(f) else f
    except (TypeError, ValueError):
        return 0.0


def _looks_like_header(row: list) -> bool:
    if not row:
        return False
    tokens = [str(x or "").strip().lower() for x in row]
    labels = {"person", "code", "date", "key", "name", "miles", "gross", "rad", "wud", "net pay", "netpay", "net_pay"}
    return sum(1 for t in tokens if t in labels) >= 4

def _canonicalize_columns(cols: list) -> list:
    out = []
    for c in cols:
        key = str(c or "").strip().lower().replace("_", " ").replace("  ", " ")
        if key == "person":
            out.append("Person")
        elif key == "code":
            out.append("Code")
        elif key == "date":
            out.append("Date")
        elif key == "key":
            out.append("Key")
        elif key.startswith("name"):
            out.append("Name")
        elif "mile" in key:
            out.append("Miles")
        elif "gross" in key:
            out.append("Gross")
        elif key == "rad":
            out.append("RAD")
        elif key == "wud":
            out.append("WUD")
        elif "net" in key and "pay" in key:
            out.append("Net Pay")
        else:
            out.append(str(c or ""))
    return out


def extract_tables(file_bytes: bytes) -> List[Tuple[int, pd.DataFrame]]:
    out: List[Tuple[int, pd.DataFrame]] = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            try:
                raw_tables = page.extract_tables() or []
            except Exception:
                raw_tables = []

            for tbl in raw_tables:
                if not tbl or not any(row for row in tbl):
                    continue

                df = pd.DataFrame(tbl)

                header_row = None
                for r_i, row in enumerate(df.values.tolist()[:8]):
                    if _looks_like_header(row):
                        header_row = r_i
                        break
                if header_row is None:
                    header_row = 0

                header = [str(x or "").strip() for x in df.iloc[header_row].tolist()]
                header = _canonicalize_columns(header)

                df = df.iloc[header_row + 1 :].reset_index(drop=True)

                if len(header) != df.shape[1]:
                    if len(header) < df.shape[1]:
                        header = header + [f"col{n}" for n in range(len(header), df.shape[1])]
                    else:
                        header = header[: df.shape[1]]

                df.columns = header

                matches = sum(1 for c in df.columns if c in EXPECTED_COLS)
                if matches >= 5:
                    out.append((idx, df))

    return out

def extract_pdf_text(file_bytes: bytes) -> str:
    """
    Extract concatenated text from all pages in a PDF (best-effort).
    Returns a single string.
    """
    parts: List[str] = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            try:
                # layout=True often preserves spacing/line breaks better for headers
                txt = page.extract_text(layout=True) or ""
            except Exception:
                txt = ""
            if txt.strip():
                parts.append(txt)

    return "\n\n".join(parts)


def extract_pdf_text_by_page(file_bytes: bytes) -> List[Tuple[int, str]]:
    """
    Extract text per page. Returns [(page_number, text), ...]
    """
    out: List[Tuple[int, str]] = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            try:
                txt = page.extract_text(layout=True) or ""
            except Exception:
                txt = ""
            out.append((idx, txt))
    return out

def normalize_details_tables(tables: List[Tuple[int, pd.DataFrame]], source_file: str) -> pd.DataFrame:
    frames = []

    def _strip_cell(x):
        return x.strip() if isinstance(x, str) else x

    def _to_float(v):
        if v is None:
            return None
        s = str(v).strip().replace(",", "").replace("$", "")
        if s == "":
            return None
        neg = s.startswith("(") and s.endswith(")")
        s = s.strip("()")
        try:
            val = float(s)
            return -val if neg else val
        except Exception:
            return None

    for page, df in tables:
        for col in EXPECTED_COLS:
            if col not in df.columns:
                df[col] = None
        df = df[EXPECTED_COLS].copy()

        # strip
        try:
            df = df.map(_strip_cell)  # pandas >=2.1
        except AttributeError:
            df = df.apply(lambda s: s.map(_strip_cell))

        # drop leaked headers
        for col in ["Person", "Code", "Date", "Miles", "Gross", "Net Pay"]:
            df = df[~(df[col].astype(str).str.lower().fillna("") == col.lower())]

        # forward-fill merged cells
        df["Person"] = df["Person"].replace({"": None}).ffill()
        df["Code"] = df["Code"].replace({"": None}).ffill()

        # parse numbers
        df["Miles"] = df["Miles"].apply(_to_float)
        df["Gross"] = df["Gross"].apply(_to_float)
        df["RAD"] = df["RAD"].apply(_to_float)
        df["WUD"] = df["WUD"].apply(_to_float)
        df["Net Pay"] = df["Net Pay"].apply(_to_float)

        # parse date
        df["Date"] = df["Date"].replace({"": None})
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df["Date"] = df["Date"].ffill()

        # clean strings
        df["Key"] = df["Key"].astype(str).str.strip().replace({"nan": None, "": None})
        df["Name"] = df["Name"].astype(str).str.strip().replace({"nan": None, "": None})

        df["source_page"] = page
        df["source_file"] = source_file

        # keep valid rows
        mask_valid = df["Date"].notna() & (df["Key"].notna() | df["Name"].notna())
        pruned = df[mask_valid].copy()

        def _valid_person(p):
            if p is None:
                return False
            s = str(p).strip()
            return bool(s) and not s.isdigit()

        pruned = pruned[pruned["Person"].apply(_valid_person)]
        frames.append(pruned)

    if not frames:
        return pd.DataFrame(columns=EXPECTED_COLS + ["source_page", "source_file"])

    all_df = pd.concat(frames, ignore_index=True)
    return all_df.reset_index(drop=True)


def _make_ride_key(
    code: str | None,
    ride_date: datetime,
    key_col: str | None,
    miles: float | None,
    gross_pay: float | None,
    net_pay: float | None,
    source_file: str,
    source_page: int,
    row_index: int,
) -> str:
    """
    We want a stable key per ride-row. Prefer the PDF "Key" column when present.
    Otherwise hash a signature that includes page+row so multiple rides per day don't collide.
    """
    parts = [
        str(code or ""),
        ride_date.date().isoformat(),
        str(key_col or ""),
        str(miles or 0),
        str(gross_pay or 0),
        str(net_pay or 0),
        str(source_file or ""),
        f"p{source_page}",
        f"r{row_index}",
    ]
    base = "|".join(parts)
    return hashlib.sha1(base.encode("utf-8")).hexdigest()

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

def _to_date(v) -> "date | None":
    """Coerce v to a date object. Handles date, datetime, pd.Timestamp, and ISO strings."""
    if v is None:
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    # pd.Timestamp or any object with .date()
    if hasattr(v, "date") and callable(v.date):
        return v.date()
    # ISO string "YYYY-MM-DD"
    try:
        return date.fromisoformat(str(v)[:10])
    except (ValueError, TypeError):
        return None


import logging as _logging
_bir_logger = _logging.getLogger(__name__)


def bulk_insert_rides(db: Session, period_start: str, period_end: str, batch_id: str, source_file: str, rides_data: list[dict]):
    """
    Inserts rides from normalized PDF rows.
    DEDUPE MUST USE (person_id, ride_key) — NOT (start_ts, miles, base_fare).
    Your DB already has:
      UNIQUE (person_id, ride_key) WHERE ride_key IS NOT NULL

    Date-range guard: any ride whose service date falls outside [period_start, period_end]
    is skipped (not inserted), a WARNING is logged, and a note is appended to batch.notes.
    This prevents mislabeled PDFs (e.g. EverDriven serving W16 trips inside a W15 header)
    from silently contaminating the wrong batch.
    """
    inserted = 0
    skipped = 0
    last_person_name = None
    last_code = None
    last_ride_dt = None
    company_name="EverDriven"
    source="maz"
    # 0 batch
    batch = PayrollBatch(
            source=source,
            company_name=company_name,
            batch_ref=batch_id,
            currency="USD",
            period_start=period_start,
            week_start=period_start,
            period_end=period_end,
            week_end=period_end,
            notes=f"imported from {source_file}",
        )
    db.add(batch)
    db.flush()

    # Coerce period bounds to date objects once for the whole call.
    # _to_date handles str "YYYY-MM-DD", date, datetime, and pd.Timestamp.
    _period_start_date: "date | None" = _to_date(period_start)
    _period_end_date: "date | None" = _to_date(period_end)
    # Accumulate out-of-period rides so we can log + annotate batch.notes in one shot.
    _out_of_period: list[tuple[object, "date"]] = []

    # ------------------------------------------------------------
    # ------------------------------------------------------------
    # 1) Upsert z_rate_service FIRST (unique per service_name)
    # ------------------------------------------------------------
    # service_key must be UNIQUE per (source, company, service_name) so that
    # every distinct service gets its own row — never reuse a static key.
    def make_service_key(src: str, company: str, svc_name: str) -> str:
        parts = f"{src}_{company}_{svc_name}"
        return re.sub(r"[^a-z0-9_]", "_", parts.lower())[:120]

    source="maz"
    # Dedupe by service_name (because service_name is the unique identity)
    service_names: set[str] = set()
    for i, row in enumerate(rides_data):
        sname = (str(row.get("Name") or "").strip() or None)
        nm = norm_str(sname)
        if nm:
            service_names.add(nm)

    services = [
        {
            "service_key": make_service_key(source, company_name, nm),
            "service_name": nm,
            "currency": "USD",
        }
        for nm in sorted(service_names)
    ]

    #print("RATES --> Services", len(services), "SERVICES:", services[:3], "...")  # preview only
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

    inserted, skipped, unmatched = 0, 0, 0
    unmatched_drivers: list[dict] = []

    # ------------------------------------------------------------
    # 2) Insert rides; use SAVEPOINT per row (no global rollback)
    # ------------------------------------------------------------
    for i, row in enumerate(rides_data):
        #driver
        
        # Fill-down Person/Code/Date because the PDF only shows them once per block
        raw_person = (str(row.get("Person") or "").strip() or None)
        raw_code = (str(row.get("Code") or "").strip() or None)
        raw_dt = row.get("Date")

        if raw_person:
            last_person_name = raw_person
        if raw_code:
            last_code = raw_code
        if raw_dt is not None and str(raw_dt).strip() != "":
            last_ride_dt = raw_dt
        person_name = last_person_name
        code = last_code
        ride_dt = last_ride_dt

        # ------------------------------------------------------------------
        # Date-range guard: skip rides whose service date falls outside the
        # declared batch period [period_start, period_end] (inclusive).
        # This catches mislabeled EverDriven PDFs (header says W15 but body
        # contains W16 trips).  Skipped rides are logged + noted on batch.notes;
        # the import still succeeds with whatever in-period rides exist.
        # out-of-period skips are tracked separately from dedup/integrity skips
        # so the already_imported heuristic stays accurate.
        # ------------------------------------------------------------------
        if _period_start_date and _period_end_date and ride_dt is not None:
            _rdate = _to_date(ride_dt)
            if _rdate is not None and not (_period_start_date <= _rdate <= _period_end_date):
                _out_of_period.append((row.get("Key") or row.get("Code") or f"row{i}", _rdate))
                continue

        driver_name = norm_str(person_name)
        driver_ext = norm_str((str(code or "").strip() or None))
        # normalized input fields
        miles = row.get("Miles")
        gross = row.get("Gross")
        net_pay = row.get("Net Pay")
        service_key = (str(row.get("Key") or "").strip() or None)
        service_name = (str(row.get("Name") or "").strip() or None)
        service_code = code
        service_ref = norm_service_ref(code)
        
        # person for driver
        person = upsert_person(db, external_id=driver_ext, full_name=driver_name)
        if not person:
            # Explicit unmatched tracking — do NOT silently bucket under Unassigned (person_id=227)
            unmatched += 1
            unmatched_drivers.append({
                "driver_name": driver_name,
                "driver_ext": driver_ext,
                "service_name": service_name,
                "reason": "no name provided — row skipped",
            })
            skipped += 1
            continue
        
        #rate lookup/insert
        service_key = make_service_key(source, company_name, service_name or "")  # unique per service
        svc_id = service_id_by_name.get(service_name)
        
        # if for any reason it’s missing, still resolve by key (or return default)
        z_rate, z_rate_source, z_rate_service_id, z_rate_override_id = resolve_rate_for_ride(
            db=db,
            source=batch.source,
            company_name=batch.company_name,
            service_name=service_name,
            currency=batch.currency,
            ride_date=ride_dt,
        )

        # Late-cancel auto-apply: if this ride's net_pay is 40–55% of the
        # resolved default rate and the service has a stored
        # late_cancellation_rate, use that rate instead.
        try:
            from decimal import Decimal as _Dec
            np_val = float(net_pay or 0)
            base_rate = float(z_rate or 0)
            if base_rate > 0 and np_val > 0:
                ratio = np_val / base_rate
                if 0.40 <= ratio <= 0.55:
                    lookup_svc_id = z_rate_service_id or svc_id
                    if lookup_svc_id is not None:
                        svc_row = (
                            db.query(ZRateService)
                            .filter(ZRateService.z_rate_service_id == lookup_svc_id)
                            .first()
                        )
                        lc_rate = getattr(svc_row, "late_cancellation_rate", None) if svc_row else None
                        if lc_rate is not None:
                            z_rate = _Dec(str(lc_rate))
                            z_rate_source = "late_cancellation"
        except Exception:
            pass

        # Flag zero-rate rides that have no configured rate.
        # NEVER default to any partner rate — 0 with this source tag is the correct signal.
        # ED has no cancellation_reason column; a $0 ride here is always a flag.
        if z_rate == 0 and z_rate_source not in ("late_cancellation",):
            z_rate_source = "zero_rate_no_config"

        source_file_v = str(row.get("source_file") or source_file or "upload")
        source_page_v = int(row.get("source_page") or 0)

        # Make a stable unique ref per PDF row (prevents uq_ride_source_ref collisions)
        # This will also be identical if you re-import the same PDF, so duplicates will be skipped cleanly.
        # Use the EverDriven trip Key as stable unique identifier when available.
        # Fall back to filename+page+row so we still deduplicate on re-uploads.
        trip_key = norm_service_ref(row.get("Key"))
        if trip_key:
            source_ref = f"maz:{trip_key}"
        else:
            source_ref = f"{company_name}:{source_file_v}:p{source_page_v}:r{i}"

        service_ref = trip_key or norm_service_ref(row.get("Code"))

        ride = Ride(
            payroll_batch_id=batch.payroll_batch_id,
            person_id=person.person_id,
            ride_start_ts=ride_dt,

            source=source,
            source_ref=source_ref,

            service_ref_type="CODE",
            service_name=service_name,
            service_ref=service_ref,

            z_rate=z_rate,
            z_rate_source=z_rate_source,
            z_rate_service_id=z_rate_service_id or svc_id,
            z_rate_override_id=z_rate_override_id,

            miles=float(miles or 0),
            gross_pay=float(gross or 0),
            net_pay=float(net_pay or 0),
            deduction=_nan_to_zero(row.get("RAD")) + _nan_to_zero(row.get("WUD")),
        )
        try:
            with db.begin_nested():
                    db.add(ride)
                    db.flush()
            inserted += 1
        except IntegrityError:
            skipped += 1
            # no db.rollback() here; begin_nested() handled it
            continue

    # ------------------------------------------------------------------
    # Date-range guard: emit warning + annotate batch.notes for any rides
    # that were skipped because their service date was outside the declared
    # batch period.
    # ------------------------------------------------------------------
    if _out_of_period:
        _oop_dates = [d for _, d in _out_of_period]
        _oop_refs = [ref for ref, _ in _out_of_period]
        _bir_logger.warning(
            "[bulk_insert_rides] Skipped %d ride(s) outside batch period [%s, %s]. "
            "date range in skipped rows: %s – %s. refs (first 10): %s",
            len(_out_of_period),
            _period_start_date,
            _period_end_date,
            min(_oop_dates),
            max(_oop_dates),
            _oop_refs[:10],
        )
        _guard_note = (
            f"\n[date-range-guard] skipped {len(_out_of_period)} out-of-period ride(s) "
            f"(min {min(_oop_dates)}, max {max(_oop_dates)})"
        )
        batch.notes = (batch.notes or "") + _guard_note

    db.commit()

    # ── Handle duplicate upload: 0 inserted means all rides already in DB ────
    if inserted == 0 and skipped > 0:
        db.delete(batch)
        db.commit()

    return {
        "inserted": inserted,
        "skipped": skipped,
        "out_of_period": len(_out_of_period),
        "unmatched": unmatched,
        "unmatched_drivers": unmatched_drivers,
        # already_imported: all skips were dedup skips (IntegrityError), not date-guard skips.
        # If out-of-period rides account for all non-inserts, this is a bad-PDF upload, not a duplicate.
        "already_imported": inserted == 0 and skipped > 0 and len(_out_of_period) == 0,
    }
