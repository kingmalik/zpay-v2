# backend/services/build_rows.py
from __future__ import annotations
import pandas as pd
import re

# reuse your helpers already imported in upload.py
from backend.utils.pandas_tools import money_to_float, parse_date_utc

NUM = re.compile(r"([-+]?\d*\.?\d+)")   # <-- add () to capture
DATE_EXTRACT = re.compile(r"(\d{1,2}/\d{1,2}/\d{2,4})")


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    # case-insensitive accessor with graceful fallback
    for c in df.columns:
        if c.lower().strip() == name.lower():
            return df[c]
    return pd.Series([None] * len(df))

def _to_miles(s: pd.Series) -> pd.Series:
    """
    Extract a numeric miles value from the cell.
    Using findall and taking the LAST number makes it robust to cells like
    '25 4 12 33.6' (PDF noise) while ride rows usually have a single value.
    """
    nums = s.astype(str).str.findall(NUM)     # list of matches per cell
    last = nums.str[-1]                       # last match (NaN if none)
    return pd.to_numeric(last, errors="coerce")

def _to_date_forward_fill(s: pd.Series) -> pd.Series:
    """
    Extract m/d/Y strings from the 'Date' column, forward-fill them down to ride rows,
    and convert the whole Series to UTC datetimes using parse_date_utc (expects Series).
    """
    # pull out '9/3/2025' text (or NaN), then carry the last seen date downward
    dstr = (
        s.astype(str)
         .str.extract(DATE_EXTRACT)[0]   # Series of date strings or NaN
         .ffill()
    )
    # convert the whole Series in one call (no .map on scalars)
    return parse_date_utc(dstr)

def details_to_rows(details_df: pd.DataFrame) -> pd.DataFrame:
    if details_df is None or details_df.empty:
        return pd.DataFrame(columns=[
            "external_id","person","code","ride_start_ts",
            "name","distance_miles","base_fare","net_pay"
        ])

    df = details_df.copy()

    person = _col(df, "Person")
    code   = _col(df, "Code")
    date   = _col(df, "Date")
    key    = _col(df, "Key")
    name   = _col(df, "Name")
    miles  = _col(df, "Miles")
    gross  = _col(df, "Gross")
    netpay = _col(df, "Net Pay")

    # forward-fill Person / Code (they appear once per block)
    df["person"] = person.replace(r"^\s*$", pd.NA, regex=True).ffill()
    # keep only the leading token of Code (e.g., "124710 9/3/2025 - 9/5/2025" -> "124710")
    df["code"] = (
        code.astype(str)
            .str.extract(r"^\s*([0-9A-Za-z\-_]+)")[0]
            .replace("", pd.NA)
            .ffill()
    )

    # carry down Date header to subsequent ride rows
    df["ride_start_ts"] = _to_date_forward_fill(date)

    # identify ride rows: numeric Key present
    ride_mask = key.astype(str).str.fullmatch(r"\d+")
    rides = df.loc[ride_mask].copy()

    # parse numerics
    rides["distance_miles"] = _to_miles(miles)
    rides["base_fare"] = money_to_float(gross)
    rides["net_pay"]   = money_to_float(netpay)

    # identifiers / payload
    rides["external_id"] = key.astype(str)
    rides["name"] = name.astype(str).str.strip()

    out = rides[[
        "external_id","person","code","ride_start_ts",
        "name","distance_miles","base_fare","net_pay"
    ]].reset_index(drop=True)

    return out
