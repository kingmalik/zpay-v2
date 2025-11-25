from __future__ import annotations

import logging
import math
import re as _re
from typing import Any, Dict, List, Optional, Annotated


import pandas as pd
from fastapi import APIRouter, File, UploadFile, HTTPException, Form, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select, and_

from backend.db import SessionLocal
from backend.models import Person, Ride
from backend.config import DATA_OUT
from backend.services.storage import save_upload
from backend.services.build_rows import details_to_rows
from backend.services.parse_details import parse_details  # adjust path if different

logger = logging.getLogger("zpay.upload")
router = APIRouter()
PREVIEW_ROWS = 7

# ---------- small helpers ---------------------------------------------------

def norm_text(v: object) -> str | None:
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    s = str(v).strip()
    return s or None

_JUNK_UPPER = {"SUBTOTAL", "UNKNOWN", "TOTAL"}
_DATE_LIKE = _re.compile(r"^\s*\d{1,2}/\d{1,2}/\d{2,4}(\s+\d{1,2}:\d{2}(:\d{2})?\s*(AM|PM))?$", _re.I)
CANONICAL = {
    "ride_start_ts": ["ride_start", "start_time", "ride_start_time", "pickup_time", "start ts", "ride start ts"],
    "ride_end_ts":   ["ride_end", "end_time", "ride_end_time", "dropoff_time", "end ts", "ride end ts"],
    # add other required fields here…
}

# --- filename/default date inference helper ---
_FN_DATE_PATTERNS = [
    r"(\d{4})[-_](\d{2})[-_](\d{2})",       # 2025-09-02 or 2025_09_02
    r"(\d{1,2})[-_](\d{1,2})[-_](\d{2,4})", # 09-02-2025 or 9_2_25
    r"(\d{1,2})/(\d{1,2})/(\d{2,4})",       # 9/2/2025
]

def _infer_date_from_text(text: str) -> pd.Timestamp | None:
    if not text:
        return None
    for pat in _FN_DATE_PATTERNS:
        m = _re.search(pat, text)
        if not m:
            continue
        g = m.groups()
        try:
            if len(g[0]) == 4:  # yyyy-mm-dd
                y, mo, d = int(g[0]), int(g[1]), int(g[2])
            else:               # mm-dd-yyyy or m-d-yy
                mo, d, y = int(g[0]), int(g[1]), int(g[2])
                if y < 100:  # handle two-digit years, assume 20yy
                    y += 2000
            return pd.Timestamp(year=y, month=mo, day=d, tz="UTC")
        except Exception:
            continue
    return None


def _normalize_cols(cols: List[str]) -> List[str]:
    # lower, strip, collapse whitespace, replace non-alphanum with underscores
    out = []
    for c in cols:
        c = c.strip().lower()
        c = _re.sub(r"\s+", " ", c)                 # collapse spaces
        c = _re.sub(r"[^0-9a-zA-Z]+", "_", c)       # -> underscores
        c = c.strip("_")
        out.append(c)
    return out

def _apply_aliases(df: pd.DataFrame, canonical: Dict[str, List[str]]) -> pd.DataFrame:
    colset = set(df.columns)
    # build lookup from alias -> canonical
    alias_to_canon = {}
    for canon, aliases in canonical.items():
        for a in aliases:
            alias_to_canon[_re.sub(r"[^0-9a-zA-Z]+", "_", a.strip().lower()).strip("_")] = canon

    # rename if an alias exists
    renames = {}
    for col in df.columns:
        if col in alias_to_canon and alias_to_canon[col] not in colset:
            renames[col] = alias_to_canon[col]
    if renames:
        df = df.rename(columns=renames)
    return df

def _require_columns(df: pd.DataFrame, required: List[str]):
    missing = [c for c in required if c not in df.columns]
    if missing:
        # Help the client fix their file: echo our expected and the actual header
        raise HTTPException(
            status_code=400,
            detail={
                "error": "missing_required_columns",
                "missing": missing,
                "expected_any_of": CANONICAL,              # shows acceptable aliases
                "actual_columns": list(df.columns),
            },
        )
def is_junk_person_name(name) -> bool:
    if name is None:
        return False
    n = str(name).strip()
    if n == "":
        return True
    if n.upper() in _JUNK_UPPER:
        return True
    if _DATE_LIKE.match(n):
        return True
    return False

def _preview_df(details_df: pd.DataFrame) -> pd.DataFrame:
    prev = details_df.copy()
    for c in prev.columns:
        if str(c).lower() in {"date", "start", "end"}:
            prev[c] = pd.to_datetime(prev[c], errors="coerce", format="%m/%d/%Y")
    return prev.head(PREVIEW_ROWS)

# ---------- inline “people” helpers (no external module) --------------------

def _person_key(code: str | None, full_name: str | None) -> str:
    c = (code or "").strip()
    n = (full_name or "").strip().lower()
    return f"{c}|{n}"

def build_existing_people_map(db, PersonModel) -> dict[str, Any]:
    cache: dict[str, Any] = {}
    for p in db.execute(select(PersonModel)).scalars().all():
        key = _person_key(getattr(p, "external_id", None), getattr(p, "full_name", None))
        if key and key not in cache:
            cache[key] = p
    return cache

def get_or_create_person(db, PersonModel, code: str, full_name: str, existing_by_key: dict[str, Any]):
    key = _person_key(code, full_name)
    if key in existing_by_key:
        return existing_by_key[key]
    p = PersonModel(external_id=(code or None), full_name=full_name)
    db.add(p)
    db.flush()
    existing_by_key[key] = p
    return p

# ---------- inline ride insert (no external module) -------------------------

def insert_ride_from_row(db, RideModel, person: Person, rec: dict[str, Any]) -> Ride:
    """Create (or reuse) a Ride for this person/row; de-dupe by (person_id, external_id)."""
    def _n(v):
        if v is None:
            return None
        if isinstance(v, float) and math.isnan(v):
            return None
        s = str(v).strip()
        return s or None

    ext_id = _n(rec.get("external_id"))
    if ext_id:
        existing = db.execute(
            select(RideModel).where(
                and_(RideModel.person_id == person.person_id, RideModel.external_id == ext_id)
            )
        ).scalars().first()
        if existing:
            return existing

    ride = RideModel(
        person_id=person.person_id,
        external_id=ext_id,
        ride_start_ts=rec.get("ride_start_ts"),
        name=_n(rec.get("name")),
        distance_miles=rec.get("distance_miles"),
        base_fare=rec.get("base_fare"),
        net_pay=rec.get("net_pay"),
    )
    db.add(ride)
    db.flush()
    return ride

# ---------- build/clean rows ------------------------------------------------

def _precreate_people_from_details(details_df: pd.DataFrame) -> int:
    if details_df is None or details_df.empty:
        return 0
    df = details_df.copy()
    codes = (
        df.get("Code", pd.Series([None] * len(df)))
          .astype(str).str.extract(r"^\s*([0-9A-Za-z\-_]+)")[0]
          .replace("", pd.NA).ffill()
    )
    persons = df.get("Person", pd.Series([None] * len(df))).replace(r"^\s*$", pd.NA, regex=True).ffill()
    pre_df = pd.DataFrame({"code": codes, "person": persons}).dropna(how="all")
    pre_df["code"] = pre_df["code"].apply(norm_text)
    pre_df["person"] = pre_df["person"].apply(norm_text)
    pre_df = pre_df.dropna(subset=["person"])
    pre_df = pre_df[~pre_df["person"].apply(is_junk_person_name)]
    pre_df["key"] = pre_df["code"].fillna("") + "|" + pre_df["person"]
    pre_df = pre_df.drop_duplicates("key")

    with SessionLocal() as db:
        people_cache = build_existing_people_map(db, Person)
        before = len(people_cache)
        for _, row in pre_df.iterrows():
            _ = get_or_create_person(db, Person, (row["code"] or ""), row["person"], existing_by_key=people_cache)
        db.commit()
        created = len(people_cache) - before
    logger.info("Pre-created people from Details (unique code|person pairs): %d", created)
    return created

def _ensure_cols(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Ensure required columns exist; create with sensible defaults."""
    for c in cols:
        if c not in df.columns:
            if c == "ride_start_ts":
                df[c] = pd.NaT
            elif c in ("distance_miles", "base_fare", "net_pay"):
                df[c] = pd.NA
            else:
                df[c] = pd.NA
    return df

def _clean_rows(rows: pd.DataFrame, fallback_text: str | None = None) -> pd.DataFrame:
    
    # --- Force-apply default date if provided (query/form or filename) ---
    if fallback_text:
        # 1) try direct parse (works for ISO like 2025-09-02)
        inferred = pd.to_datetime(str(fallback_text), errors="coerce", utc=True)
        # 2) else, try filename-like patterns
        if pd.isna(inferred):
            maybe = _infer_date_from_text(str(fallback_text))
            if maybe is not None:
                inferred = maybe
        # 3) if we have anything valid, ensure the column exists and broadcast
        if pd.notna(inferred):
            if "ride_start_ts" not in rows.columns:
                rows["ride_start_ts"] = pd.NaT
            # broadcast the scalar to the whole column
            rows["ride_start_ts"] = inferred
    # 0) Debug logs to see what arrived
    # logger.info("Incoming columns (raw): %s", list(rows.columns))
    rows.columns = _normalize_cols(list(rows.columns))
    rows = _apply_aliases(rows, CANONICAL)
    _require_columns(rows, ["ride_start_ts"])  # add other must-haves if needed
    
    # If we already set a valid datetime column above, leave it; else parse.
    if not (pd.api.types.is_datetime64_any_dtype(rows["ride_start_ts"]) and rows["ride_start_ts"].notna().any()):
        rows["ride_start_ts"] = _parse_dt_column(rows, "ride_start_ts", min_success_ratio=0.6)

    # 1) Parse timestamps safely (coerce bad values to NaT, set UTC)
    rows["ride_start_ts"] = pd.to_datetime(rows["ride_start_ts"], errors="coerce", utc=True)

    # 2) If you need a format hint (optional):
    # rows["ride_start_ts"] = pd.to_datetime(rows["ride_start_ts"], format="%Y-%m-%d %H:%M:%S", errors="coerce", utc=True)

    # 3) Optionally reject entirely if all values failed to parse
    # Use a filename or provided default_date as a last resort
    if rows["ride_start_ts"].isna().all() and fallback_text:
        inferred_dt = _infer_date_from_text(str(fallback_text))
        if inferred_dt is not None:
            rows["ride_start_ts"] = pd.Series([inferred_dt] * len(rows), index=rows.index)

    if rows["ride_start_ts"].isna().all():
        # Provide debug context to help fix inputs
        date_pat_simple = r'(\d{1,2}/\d{1,2}/\d{2,4})'
        any_date_anywhere = False
        samples = []
        for _i in range(min(len(rows), 8)):
            row = rows.iloc[_i]
            row_str = " | ".join([f"{c}={row[c]}" for c in rows.columns])
            samples.append(row_str[:220])
            import re as _tmpre
            if _tmpre.search(date_pat_simple, row_str or ""):
                any_date_anywhere = True
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_datetime",
                "column": "ride_start_ts",
                "hint": "Check header name and datetime format.",
                "date_token_found_elsewhere": any_date_anywhere,
                "row_samples": samples,
            }
        )

def _fallback_build_rows(details_df: pd.DataFrame) -> pd.DataFrame:
    df = details_df.copy()
    def _col(_df, name: str) -> pd.Series:
        for c in _df.columns:
            if str(c).lower().strip() == name.lower():
                return _df[c]
        return pd.Series([None] * len(_df))

    person = _col(df, "Person")
    code   = _col(df, "Code")
    date   = _col(df, "Date")
    key    = _col(df, "Key")
    name   = _col(df, "Name")
    miles  = _col(df, "Miles")
    gross  = _col(df, "Gross")
    netpay = _col(df, "Net Pay")

    df["person"] = person.replace(r"^\s*$", pd.NA, regex=True).ffill()
    df["code"] = code.astype(str).str.extract(r"^\s*([0-9A-Za-z\-_]+)")[0].replace("", pd.NA).ffill()
    dstr = date.astype(str).str.extract(r"(\d{1,2}/\d{1,2}/\d{2,4})")[0].ffill()
    df["ride_start_ts"] = pd.to_datetime(dstr, errors="coerce", utc=True)

    ride_mask = key.astype(str).str.match(r"^\s*\d+\s*$").fillna(False)
    rides = df.loc[ride_mask].copy()

    nums = rides["Miles"].astype(str).str.findall(r"([-+]?\d*\.?\d+)")
    rides["distance_miles"] = pd.to_numeric(nums.str[-1], errors="coerce")

    def _money(series: pd.Series) -> pd.Series:
        v = series.astype(str).str.replace(",", "", regex=False)
        m = v.str.findall(r"[-+]?\$?\d*\.?\d+")
        last = m.str[-1].str.replace("$", "", regex=False)
        return pd.to_numeric(last, errors="coerce")

    rides["base_fare"] = _money(gross)
    rides["net_pay"]   = _money(netpay)
    rides["external_id"] = key.astype(str).str.strip()
    rides["name"] = name.astype(str).str.strip()

    return rides[["external_id","person","code","ride_start_ts","name","distance_miles","base_fare","net_pay"]].reset_index(drop=True)

# ---------- route -----------------------------------------------------------

@router.post("/upload", response_class=HTMLResponse)
def upload(
    file: UploadFile = File(...),
    # NOTE: default goes after the annotation; Form()/Query() go inside Annotated
    default_date_form: Annotated[Optional[str], Form()] = None,
    default_date_q: Annotated[Optional[str], Query()] = None,
) -> HTMLResponse:
    effective_default = default_date_q or default_date_form
    logger.info(
        "Incoming file: name=%s, type=%s, default_date=%s",
        getattr(file, "filename", None),
        getattr(file, "content_type", None),
        effective_default,
    )   
    # Save file
    try:
        dest_path = save_upload(file)
        logger.info("Saved upload to: %s", dest_path)
    except Exception as e:
        logger.exception("Failed to save upload: %s", e)
        raise HTTPException(400, f"Could not save upload: {e}")

    # Parse Details
    try:
        details_df = parse_details(dest_path)
    except Exception as e:
        logger.exception("Failed to parse Details: %s", e)
        raise HTTPException(400, f"Could not parse Details: {e}")

    logger.info("Parsed Details: rows=%d", 0 if details_df is None else len(details_df.index))
    if details_df is None:
        details_df = pd.DataFrame(columns=["Person","Code","Date","Key","Name","Miles","Gross","Net Pay"])

    prev = _preview_df(details_df)
    logger.info("Details DF: shape=%s, columns=%s", details_df.shape, list(details_df.columns))
    try:
        logger.info("Details DF (head): %s", prev.fillna("").astype(str).head(5).to_dict(orient="records"))
    except Exception:
        pass

    diag = {
        "total": int(len(details_df.index)),
        "missing Key": int(details_df.get("Key", pd.Series(dtype=object)).isna().sum()) if "Key" in details_df else 0,
        "missing Date(parse)": int(prev.get("Date", pd.Series(dtype=object)).isna().sum()) if "Date" in prev.columns else 0,
        "missing Gross": int(details_df.get("Gross", pd.Series(dtype=object)).isna().sum()) if "Gross" in details_df else 0,
        "missing Net Pay": int(details_df.get("Net Pay", pd.Series(dtype=object)).isna().sum()) if "Net Pay" in details_df else 0,
    }
    logger.info("Details diagnostics: %s", ", ".join(f"{k}={v}" for k, v in diag.items()))
    d_person = details_df.get("Person")
    d_code = details_df.get("Code")
    logger.info("Distinct Person=%d, Code=%d",
                int(d_person.nunique(dropna=True)) if d_person is not None else 0,
                int(d_code.nunique(dropna=True)) if d_code is not None else 0)

    # Pre-create people from headers
    pre_created = _precreate_people_from_details(details_df)

    # Build rows
    rows = _clean_rows(rows, fallback_text=(effective_default or file.filename))
    if rows is None or rows.empty or not (("person" in rows.columns) and ("code" in rows.columns)):
        try:
            rows_fb = _fallback_build_rows(details_df)
            if rows is None or rows.empty:
                rows = rows_fb
            elif len(rows_fb.index) > 0 and len(rows_fb.index) > len(rows.index):
                rows = rows_fb
            logger.info("Fallback builder used: rows=%d", len(rows.index))
        except Exception as e:
            logger.warning("Fallback builder failed: %s", e)

    rows = _clean_rows(rows, fallback_text=(default_date or file.filename))
    logger.info("Normalized rows: %d", len(rows.index))
    logger.info("Rows DF: shape=%s, columns=%s", rows.shape, list(rows.columns))
    try:
        logger.info("Rows DF (head): %s", rows.fillna("").astype(str).head(5).to_dict(orient="records"))
    except Exception:
        pass

    # Write CSVs
    try:
        details_df.to_csv(DATA_OUT / "details.csv", index=False)
        rows.to_csv(DATA_OUT / "rows.csv", index=False)
        logger.info("Wrote CSVs: %s , %s", DATA_OUT / "details.csv", DATA_OUT / "rows.csv")
    except Exception as e:
        logger.warning("Failed writing CSVs: %s", e)

    # Insert
    created_rides = 0
    created_people_during_rides = 0
    skipped_people = 0

    with SessionLocal() as db:
        people_cache = build_existing_people_map(db, Person)
        logger.info("People cache (before rides): %d", len(people_cache))

        for i, rec in enumerate(rows.to_dict(orient="records")):
            try:
                _code = norm_text(rec.get("code"))
                _pname = norm_text(rec.get("person"))
                if is_junk_person_name(_pname):
                    skipped_people += 1
                    continue

                before = len(people_cache)
                person = get_or_create_person(db, Person, (_code or ""), (_pname or ""), existing_by_key=people_cache)
                if len(people_cache) > before:
                    created_people_during_rides += 1

                insert_ride_from_row(db, Ride, person, rec)
                created_rides += 1

                if (i + 1) <= 5 or (i + 1) % 20 == 0:
                    logger.info(
                        "Inserted ride %d/%d: key=%s date=%s gross=%s miles=%s net=%s",
                        i + 1, len(rows.index),
                        f" person(code={_code or 'NA'},name={_pname or 'NA'})",
                        str(rec.get("ride_start_ts")),
                        str(rec.get("base_fare")),
                        str(rec.get("distance_miles")),
                        str(rec.get("net_pay")),
                    )
            except Exception:
                logger.exception("Failed to insert row %d: key=%s", i + 1, f" person(code={rec.get('code')},name={rec.get('person')})")
        db.commit()
        logger.info('DB commit complete. pre_created_people=%d, new_people_during_rides=%d, skipped_people=%d, new_rides=%d',
                    pre_created, created_people_during_rides, skipped_people, created_rides)

    # People summary
    try:
        if not rows.empty:
            rows_clean = rows[~rows["person"].apply(is_junk_person_name)].copy()
            people_agg = (
                rows_clean.groupby(["code", "person"], dropna=False, as_index=False)
                    .agg(
                        rides=("external_id", "count"),
                        miles_total=("distance_miles", "sum"),
                        gross_total=("base_fare", "sum"),
                        net_total=("net_pay", "sum"),
                        first_ride=("ride_start_ts", "min"),
                        last_ride=("ride_start_ts", "max"),
                    )
            )
            out_csv = DATA_OUT / "people_summary.csv"
            people_agg.to_csv(out_csv, index=False)
            logger.info("Wrote summary CSV: %s", out_csv)
            logger.info("People Summary (from rows): shape=%s, columns=%s", people_agg.shape, list(people_agg.columns))
            try:
                logger.info("People Summary (head): %s", people_agg.fillna("").astype(str).head(5).to_dict(orient="records"))
            except Exception:
                pass
    except Exception as e:
        logger.warning("Failed to build people summary: %s", e)

    logger.info("=== /upload done: pre_created_people=%d, created_people_during_rides=%d, created_rides=%d ===",
                pre_created, created_people_during_rides, created_rides)

    return HTMLResponse(
        f"<h2>Processed {created_rides} rides from Details.</h2>"
        f"<p>Raw Details → <code>{DATA_OUT / 'details.csv'}</code> | "
        f"Rows → <code>{DATA_OUT / 'rows.csv'}</code> | "
        f"People Summary → <code>{DATA_OUT / 'people_summary.csv'}</code></p>"
        f'<p><a href="/">Home</a> · <a href="/people">People</a> · '
        f'<a href="/rides">Rides</a> · <a href="/summary">Summary</a></p>'
    )