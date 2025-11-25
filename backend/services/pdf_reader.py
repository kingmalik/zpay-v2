
import io
from typing import List, Tuple
import pdfplumber
import pandas as pd
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from models import Person, Ride

# Columns we aim to produce
EXPECTED_COLS = ["Person","Code","Date","Key","Name","Miles","Gross","Net Pay"]

def _looks_like_header(row: list) -> bool:
    """Heuristic: header if at least 4 known labels present (case-insensitive)."""
    if not row:
        return False
    tokens = [str(x or "").strip().lower() for x in row]
    labels = {"person","code","date","key","name","miles","gross","net pay","netpay","net_pay"}
    return sum(1 for t in tokens if t in labels) >= 4

def _canonicalize_columns(cols: list) -> list:
    out = []
    for c in cols:
        key = str(c or "").strip().lower().replace("_", " ").replace("  ", " ")
        if "person" in key:
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
        elif "net" in key and "pay" in key:
            out.append("Net Pay")
        else:
            out.append(str(c or ""))
    return out

def extract_tables(file_bytes: bytes) -> List[Tuple[int, pd.DataFrame]]:
    """Return (page_number, DataFrame) for tables that look like the Details grid."""
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
                # find header row within first few lines
                header_row = None
                for r_i, row in enumerate(df.values.tolist()[:8]):
                    if _looks_like_header(row):
                        header_row = r_i
                        break
                if header_row is None:
                    header_row = 0
                header = [str(x or "").strip() for x in df.iloc[header_row].tolist()]
                header = _canonicalize_columns(header)
                df = df.iloc[header_row+1:].reset_index(drop=True)
                # ensure unique column names length == df width
                if len(header) != df.shape[1]:
                    # pad or trim to fit
                    if len(header) < df.shape[1]:
                        header = header + [f"col{n}" for n in range(len(header), df.shape[1])]
                    else:
                        header = header[: df.shape[1]]
                df.columns = header
                matches = sum(1 for c in df.columns if c in EXPECTED_COLS)
                if matches >= 5:
                    out.append((idx, df))
    return out

def normalize_details_tables(tables: List[Tuple[int, pd.DataFrame]], source_file: str) -> pd.DataFrame:
    """Merge and clean the extracted 'Details' tables into a normalized rides DataFrame."""
    frames = []
    for page, df in tables:
        # Ensure all expected columns exist, and select only those
        for col in EXPECTED_COLS:
            if col not in df.columns:
                df[col] = None
        df = df[EXPECTED_COLS].copy()

        # Strip whitespace from all string cells (applymap -> map fallback for pandas >=2.1)
        def _strip_cell(x):
            return x.strip() if isinstance(x, str) else x
        try:
            # pandas >= 2.1
            df = df.map(_strip_cell)  # type: ignore[attr-defined]
        except AttributeError:
            # older pandas
            df = df.apply(lambda s: s.map(_strip_cell))

        # Drop repeated header rows that leak into body
        for col in ["Person","Code","Date","Miles","Gross","Net Pay"]:
            df = df[~(df[col].astype(str).str.lower().fillna("") == col.lower())]

        # Forward-fill merged cells for Person/Code
        df["Person"] = df["Person"].replace({"": None}).ffill()
        df["Code"]   = df["Code"].replace({"": None}).ffill()

        # Parse numeric cells (handle $, commas, parentheses for negatives)
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

        df["Miles"]   = df["Miles"].apply(_to_float)
        df["Gross"]   = df["Gross"].apply(_to_float)
        df["Net Pay"] = df["Net Pay"].apply(_to_float)

        # Parse dates (infer_datetime_format deprecated; default is now strict enough)
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

        # Clean key/name
        df["Key"]  = df["Key"].astype(str).str.strip().replace({"nan": None, "": None})
        df["Name"] = df["Name"].astype(str).str.strip().replace({"nan": None, "": None})

        # Attach provenance
        df["source_page"] = page
        df["source_file"] = source_file

        # Keep rows with a date and at least one numeric value
        mask_valid = df["Date"].notna() & (df[["Miles","Gross","Net Pay"]].notna().any(axis=1))
        pruned = df[mask_valid].copy()

        # Filter out obviously bad Person values (mostly digits or empty)
        def _valid_person(p):
            if p is None:
                return False
            s = str(p).strip()
            if not s:
                return False
            return not s.isdigit()

        pruned = pruned[pruned["Person"].apply(_valid_person)]
        frames.append(pruned)

    if not frames:
        return pd.DataFrame(columns=EXPECTED_COLS + ["source_page","source_file"])

    all_df = pd.concat(frames, ignore_index=True)
    return all_df.reset_index(drop=True)

def bulk_insert_rides(db: Session, rides_data: list[dict]):
    """Insert rides; auto-create Person; accept either normalized PDF rows or model-like dicts.

    Accepts rows like:
      { "Person": "...", "Code": "...", "Date": <datetime/str>, "Miles": 12.3, "Gross": 45.67, "Net Pay": 40.00 }
    or:
      { "external_id": "...", "full_name": "...", "ride_start_ts": dt, "distance_km": 12.3, "base_fare": 45.67, ... }
    Returns: (inserted_count, skipped_duplicates)
    """
    from datetime import datetime
    inserted = 0
    skipped = 0

    def _to_dt(v):
        if v is None:
            return None
        if isinstance(v, datetime):
            return v
        try:
            # pandas Timestamp has .to_pydatetime
            to_py = getattr(v, "to_pydatetime", None)
            if callable(to_py):
                return to_py()
        except Exception:
            pass
        try:
            return pd.to_datetime(v, errors="coerce").to_pydatetime()
        except Exception:
            return None

    for row in rides_data:
        # Map inputs
        external_id = row.get("external_id") or (str(row.get("Code") or row.get("Key") or "").strip() or None)
        full_name   = row.get("full_name") or row.get("Person") or row.get("Name")
        ride_start  = row.get("ride_start_ts") or row.get("Date")
        ride_end    = row.get("ride_end_ts")
        distance_km = row.get("distance_km")
        if distance_km is None and row.get("Miles") is not None:
            try:
                distance_km = float(row.get("Miles"))
            except Exception:
                distance_km = None
        base_fare   = row.get("base_fare")
        if base_fare is None and row.get("Gross") is not None:
            try:
                base_fare = float(row.get("Gross"))
            except Exception:
                base_fare = 0

        tips        = row.get("tips", 0)  # Net Pay is not tips; keep as 0 unless provided
        adjustments = row.get("adjustments", 0)
        currency    = row.get("currency") or "USD"
        origin      = row.get("origin")
        destination = row.get("destination")
        source_ref  = row.get("source_ref") or (row.get("Key") or row.get("Name"))

        ride_start_dt = _to_dt(ride_start)
        ride_end_dt   = _to_dt(ride_end)

        # Ensure we have minimal viable data
        if not full_name and not external_id:
            skipped += 1
            continue
        if ride_start_dt is None:
            skipped += 1
            continue

        # find or create person
        person_q = None
        if external_id:
            person_q = db.query(Person).filter(Person.external_id == external_id).first()
        else:
            person_q = db.query(Person).filter(Person.full_name == full_name).first()

        if not person_q:
            person_q = Person(
                external_id=external_id,
                full_name=full_name,
                active=True,
            )
            db.add(person_q)
            db.flush()  # assign person_id

        # Build ride model
        ride = Ride(
            person_id=person_q.person_id,
            ride_start_ts=ride_start_dt,
            ride_end_ts=ride_end_dt,
            origin=origin,
            destination=destination,
            distance_km=distance_km,
            duration_min=row.get("duration_min"),
            base_fare=base_fare or 0,
            tips=tips or 0,
            adjustments=adjustments or 0,
            currency=currency,
            source_ref=source_ref,
        )

        # Dedupe: person + start_ts + distance + base_fare is a decent unique row signature for ride statements
        exists = (
            db.query(Ride)
            .filter(
                Ride.person_id == ride.person_id,
                Ride.ride_start_ts == ride.ride_start_ts,
                Ride.distance_km == ride.distance_km,
                Ride.base_fare == ride.base_fare,
            )
            .first()
        )
        if exists:
            skipped += 1
            continue

        db.add(ride)
        inserted += 1

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise

    return inserted, skipped