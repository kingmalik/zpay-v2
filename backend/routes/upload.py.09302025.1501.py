from __future__ import annotations

import logging
import math
import re as _re
from typing import Any, Dict, List



import pandas as pd
from fastapi import APIRouter, File, UploadFile, HTTPException
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
    "ride_start_ts": ["ride_start", "start_time", "ride_start_time", "pickup_time", "start ts", "ride start ts", "date", "start", "start_date", "pickup_date"],
    "ride_end_ts":   ["ride_end", "end_time", "ride_end_time", "dropoff_time", "end ts", "ride end ts"],
    # add other required fields here…
}

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

def _parse_dt_column(df: pd.DataFrame, col: str, min_success_ratio: float = 0.6) -> pd.Series:
    """
    Robust datetime parser for one column:
      - extracts the FIRST date-like token from each cell (handles ranges like '9/02/2025 - 9/05/2025')
      - tries general ISO parsing, then day-first, then explicit formats
      - supports Unix seconds (10 digits), Unix ms (13 digits), and Excel serial day numbers
      - success ratio is computed over NON-BLANK cells only
    Raises HTTPException 400 if too few non-blank values parse.
    """
    s_raw = df[col]
    s_str = s_raw.astype(str).str.strip()

    # Extract first date-like substring if present; else keep the original (may be ISO/epoch)
    m = s_str.str.extract(
        r'(?P<date>(\d{1,2}/\d{1,2}/\d{2,4})(\s+\d{1,2}:\d{2}(:\d{2})?\s*(AM|PM)?)?)',
        expand=False
    )
    s_tok = m["date"].fillna(s_str)

    # Non-blank mask
    nb_mask = s_tok.str.strip().replace({"": None, "NaT": None, "nat": None, "NaN": None, "nan": None, "NONE": None, "None": None, "null": None, "NULL": None}).notna()
    if not nb_mask.any():
        return pd.to_datetime(pd.Series([pd.NaT] * len(s_tok)), errors="coerce", utc=True)

    # 1) general parser (ISO, many formats)
    dt = pd.to_datetime(s_tok, errors="coerce", utc=True)
    success_nb = dt[nb_mask].notna().mean()
    target = min_success_ratio

    # 2) day-first fallback
    if success_nb < target:
        dt2 = pd.to_datetime(s_tok, errors="coerce", utc=True, dayfirst=True)
        if dt2[nb_mask].notna().mean() > success_nb:
            dt = dt2
            success_nb = dt[nb_mask].notna().mean()

    # 3) explicit common formats
    if success_nb < target:
        for fmt in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M", "%d/%m/%Y %H:%M",
                    "%m/%d/%y %H:%M", "%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S"):
            try_dt = pd.to_datetime(s_tok, format=fmt, errors="coerce", utc=True)
            if try_dt[nb_mask].notna().mean() > success_nb:
                dt = try_dt
                success_nb = dt[nb_mask].notna().mean()
                if success_nb >= target:
                    break

    # 4) numeric epochs & Excel serials for remaining NaT among non-blank tokens
    need = dt.isna() & nb_mask
    if need.any():
        s_need = s_tok.where(need)
        s_num = pd.to_numeric(s_need, errors="coerce")

        # Unix seconds (10 digits)
        mask_s = s_need.str.fullmatch(r"\d{10}")
        if mask_s.fillna(False).any():
            dt.loc[mask_s.fillna(False)] = pd.to_datetime(
                s_num.loc[mask_s.fillna(False)], unit="s", origin="unix", utc=True
            )

        # Unix milliseconds (13 digits)
        mask_ms = s_need.str.fullmatch(r"\d{13}")
        if mask_ms.fillna(False).any():
            dt.loc[mask_ms.fillna(False)] = pd.to_datetime(
                s_num.loc[mask_ms.fillna(False)], unit="ms", origin="unix", utc=True
            )

        # Excel serials ~20000..60000
        mask_xl = s_num.between(20000, 60000, inclusive="both")
        if mask_xl.fillna(False).any():
            dt.loc[mask_xl.fillna(False)] = pd.to_datetime(
                s_num.loc[mask_xl.fillna(False)], unit="D", origin="1899-12-30", utc=True
            )

        success_nb = dt[nb_mask].notna().mean()

    # 5) validate success over non-blank cells
    if success_nb < target:
        bad_examples = s_tok[need].astype(str).head(5).tolist()
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_datetime",
                "column": col,
                "hint": ("Unrecognized datetime in non-blank cells. Supported: "
                         "ISO (e.g. 2025-09-29T08:30Z), MM/DD/YYYY [HH:MM][AM/PM], "
                         "DD/MM/YYYY, Unix seconds (10 digits), Unix ms (13 digits), "
                         "Excel serial days; also handles 'MM/DD/YYYY - MM/DD/YYYY' by "
                         "taking the first date."),
                "examples_failed": bad_examples,
                "non_blank_parse_ratio": round(float(success_nb), 3),
            },
        )

    return dt

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

def _clean_rows(rows: pd.DataFrame) -> pd.DataFrame:
    # 0) Debug logs to see what arrived
    # logger.info("Incoming columns (raw): %s", list(rows.columns))
    rows.columns = _normalize_cols(list(rows.columns))
    rows = _apply_aliases(rows, CANONICAL)

    # Fallback build ride_start_ts when column is present but blank/NaT
    if "ride_start_ts" in rows.columns:
        rs = rows["ride_start_ts"]
        rs_blank = rs.isna() | rs.astype(str).str.strip().isin(["", "NaT", "nan", "None", "null"])
        if rs_blank.all():
            # Prefer 'date' if present
            if "date" in rows.columns:
                tok = rows["date"].astype(str).str.extract(r'(\d{1,2}/\d{1,2}/\d{2,4}(\s+\d{1,2}:\d{2}(:\d{2})?\s*(AM|PM)?)?)', expand=False)[0]
                rows["ride_start_ts"] = pd.to_datetime(tok, errors="coerce", utc=True)
            # Try common text columns
            if rows["ride_start_ts"].isna().all():
                for cand in ["code", "Code", "ride", "details", "name"]:
                    if cand in rows.columns:
                        tok = rows[cand].astype(str).str.extract(r'(\d{1,2}/\d{1,2}/\d{2,4})', expand=False)[0]
                        dt2 = pd.to_datetime(tok, errors="coerce", utc=True)
                        has_dt = (dt2.notna().any() if isinstance(dt2, pd.Series) else pd.notna(dt2))
                        if has_dt:
                            rows["ride_start_ts"] = dt2
                            break

    _require_columns(rows, ["ride_start_ts"])  # add other must-haves if needed

    # 1) Parse timestamps safely (coerce bad values to NaT, set UTC)
    # rows["ride_start_ts"] = pd.to_datetime(rows["ride_start_ts"], errors="coerce", utc=True)

    rows["ride_start_ts"] = _parse_dt_column(rows, "ride_start_ts", min_success_ratio=0.6)

    # 2) If you need a format hint (optional):
    # rows["ride_start_ts"] = pd.to_datetime(rows["ride_start_ts"], format="%Y-%m-%d %H:%M:%S", errors="coerce", utc=True)

    # 3) Optionally reject entirely if all values failed to parse
    if rows["ride_start_ts"].isna().all():
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_datetime", "column": "ride_start_ts", "hint": "Check header name and datetime format."},
        )

    # continue with your existing cleaning…
    return rows

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
def upload(file: UploadFile = File(...)) -> HTMLResponse:
    logger.info("=== /upload start ===")
    logger.info("Incoming file: name=%s, type=%s", file.filename, file.content_type)

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
    rows = details_to_rows(details_df)
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

    rows = _clean_rows(rows)
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