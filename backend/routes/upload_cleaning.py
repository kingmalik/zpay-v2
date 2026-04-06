# backend/routes/upload_cleaning.py
from __future__ import annotations

import re as _re
from typing import Dict, List, Optional

import pandas as pd
from fastapi import HTTPException


# Canonical header aliases (extend as needed)
CANONICAL: Dict[str, List[str]] = {
    "ride_start_ts": [
        "ride_start_ts", "ride_start", "start_time", "ride_start_time",
        "pickup_time", "start_ts", "ride_start_ts_utc", "date", "start",
        "start_date", "pickup_date",
    ],
    "external_id": ["external_id", "id", "external-id"],
    "person": ["person", "driver", "rider"],
    "code": ["code", "trip_code"],
    "name": ["name", "title"],
    "distance_miles": ["distance_miles", "miles", "distance"],
    "base_fare": ["base_fare", "gross", "fare"],
    "net_pay": ["net_pay", "net"],
}

# Filename / default-date inference (Option B)
_FN_DATE_PATTERNS = [
    r"(\d{4})[-_](\d{2})[-_](\d{2})",       # 2025-09-02 or 2025_09_02
    r"(\d{1,2})[-_](\d{1,2})[-_](\d{2,4})", # 09-02-2025 or 9_2_25
    r"(\d{1,2})/(\d{1,2})/(\d{2,4})",       # 9/2/2025
]

def infer_date_from_text(text: str) -> Optional[pd.Timestamp]:
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
                if y < 100:
                    y += 2000
            return pd.Timestamp(year=y, month=mo, day=d, tz="UTC")
        except Exception:
            continue
    return None


def normalize_cols(cols: List[str]) -> List[str]:
    out = []
    for c in cols:
        c = str(c).strip().lower()
        c = _re.sub(r"\s+", " ", c)
        c = c.replace("-", "_").replace(" ", "_")
        c = _re.sub(r"[^0-9a-zA-Z_]", "", c)
        c = c.strip("_")
        out.append(c)
    return out


def apply_aliases(df: pd.DataFrame, mapping: Dict[str, List[str]]) -> pd.DataFrame:
    rename: Dict[str, str] = {}
    cols = set(df.columns)
    for canon, aliases in mapping.items():
        if canon in cols:
            continue
        for a in aliases:
            if a in cols:
                rename[a] = canon
                break
    if rename:
        df = df.rename(columns=rename)
    return df


def require_columns(df: pd.DataFrame, required: List[str]) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "missing_columns",
                "missing": missing,
                "available": list(df.columns),
            },
        )


def parse_dt_column(df: pd.DataFrame, col: str, min_success_ratio: float = 0.6) -> pd.Series:
    s_raw = df[col]
    s_str = s_raw.astype(str).str.strip()

    # Extract first date-like substring; if none, keep original (ISO/epoch)
    m = s_str.str.extract(
        r'(?P<date>(\d{1,2}/\d{1,2}/\d{2,4})(\s+\d{1,2}:\d{2}(:\d{2})?\s*(AM|PM)?)?)',
        expand=False
    )
    s_tok = m["date"].fillna(s_str)

    nb_mask = s_tok.str.strip().replace({
        "": None, "NaT": None, "nat": None, "NaN": None, "nan": None,
        "NONE": None, "None": None, "null": None, "NULL": None
    }).notna()

    if not nb_mask.any():
        return pd.to_datetime(pd.Series([pd.NaT] * len(s_tok)), errors="coerce", utc=True)

    # 1) general parser
    dt = pd.to_datetime(s_tok, errors="coerce", utc=True)
    success_nb = dt[nb_mask].notna().mean()

    # 2) day-first fallback
    if success_nb < min_success_ratio:
        dt2 = pd.to_datetime(s_tok, errors="coerce", utc=True, dayfirst=True)
        if dt2[nb_mask].notna().mean() > success_nb:
            dt = dt2
            success_nb = dt[nb_mask].notna().mean()

    # 3) explicit formats
    if success_nb < min_success_ratio:
        for fmt in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M", "%d/%m/%Y %H:%M",
                    "%m/%d/%y %H:%M", "%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S"):
            try_dt = pd.to_datetime(s_tok, format=fmt, errors="coerce", utc=True)
            if try_dt[nb_mask].notna().mean() > success_nb:
                dt = try_dt
                success_nb = dt[nb_mask].notna().mean()
                if success_nb >= min_success_ratio:
                    break

    # 4) numeric epochs & Excel serials
    need = dt.isna() & nb_mask
    if need.any():
        s_need = s_tok.where(need)
        s_num = pd.to_numeric(s_need, errors="coerce")

        mask_s = s_need.str.fullmatch(r"\d{10}")        # unix seconds
        if mask_s.fillna(False).any():
            dt.loc[mask_s.fillna(False)] = pd.to_datetime(
                s_num.loc[mask_s.fillna(False)], unit="s", origin="unix", utc=True
            )

        mask_ms = s_need.str.fullmatch(r"\d{13}")       # unix ms
        if mask_ms.fillna(False).any():
            dt.loc[mask_ms.fillna(False)] = pd.to_datetime(
                s_num.loc[mask_ms.fillna(False)], unit="ms", origin="unix", utc=True
            )

        mask_xl = s_num.between(20000, 60000, inclusive="both")  # Excel serials
        if mask_xl.fillna(False).any():
            dt.loc[mask_xl.fillna(False)] = pd.to_datetime(
                s_num.loc[mask_xl.fillna(False)], unit="D", origin="1899-12-30", utc=True
            )

    success_nb = dt[nb_mask].notna().mean()
    if success_nb < min_success_ratio:
        bad_examples = s_tok[dt.isna() & nb_mask].astype(str).head(5).tolist()
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_datetime",
                "column": col,
                "hint": ("Unrecognized datetime in non-blank cells. "
                         "Provide default_date or include a date column."),
                "examples_failed": bad_examples,
                "non_blank_parse_ratio": round(float(success_nb), 3),
            },
        )

    return dt


def clean_rows(
    rows: pd.DataFrame,
    fallback_text: Optional[str] = None,
) -> pd.DataFrame:
    # Normalize/alias
    rows.columns = [str(c) for c in rows.columns]
    rows.columns = normalize_cols(list(rows.columns))
    rows = apply_aliases(rows, CANONICAL)

    # Option B: force-apply default date (query/form or filename)
    if fallback_text:
        inferred = pd.to_datetime(str(fallback_text), errors="coerce", utc=True)
        if pd.isna(inferred):
            maybe = infer_date_from_text(str(fallback_text))
            if maybe is not None:
                inferred = maybe
        if pd.notna(inferred):
            if "ride_start_ts" not in rows.columns:
                rows["ride_start_ts"] = pd.NaT
            rows["ride_start_ts"] = inferred

    # Require and parse
    require_columns(rows, ["ride_start_ts"])

    if not (pd.api.types.is_datetime64_any_dtype(rows["ride_start_ts"]) and rows["ride_start_ts"].notna().any()):
        rows["ride_start_ts"] = parse_dt_column(rows, "ride_start_ts", min_success_ratio=0.6)

    return rows

