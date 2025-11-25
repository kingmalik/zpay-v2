
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
    """
    Insert rides and auto-create Person rows if they don't exist.
    rides_data should contain:
      [
        {
          "external_id": "EMP123",
          "full_name": "John Doe",
          "ride_start_ts": datetime(...),
          "ride_end_ts": datetime(...),
          "origin": "A",
          "destination": "B",
          "distance_km": 12.5,
          ...
        },
        ...
      ]
    """
    inserted = 0
    skipped = 0

    for data in rides_data:
        # find or create person
        person = (
            db.query(Person)
            .filter(Person.external_id == data["external_id"])
            .first()
        )
        if not person:
            person = Person(
                external_id=data["external_id"],
                full_name=data.get("full_name"),
                active=True,
            )
            db.add(person)
            db.flush()  # assigns person_id immediately

        # build ride record
        ride = Ride(
            person_id=person.person_id,
            ride_start_ts=data["ride_start_ts"],
            ride_end_ts=data.get("ride_end_ts"),
            origin=data.get("origin"),
            destination=data.get("destination"),
            distance_km=data.get("distance_km"),
            duration_min=data.get("duration_min"),
            base_fare=data.get("base_fare", 0),
            tips=data.get("tips", 0),
            adjustments=data.get("adjustments", 0),
            currency=data.get("currency", "USD"),
            source_ref=data.get("source_ref"),
        )

        # optional dedupe check
        exists = (
            db.query(Ride)
            .filter(
                Ride.person_id == ride.person_id,
                Ride.ride_start_ts == ride.ride_start_ts,
                Ride.origin == ride.origin,
                Ride.destination == ride.destination,
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

    return {"inserted": inserted, "skipped_duplicates": skipped}