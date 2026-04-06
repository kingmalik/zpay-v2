from __future__ import annotations

import warnings
from typing import Iterable
import pandas as pd

def money_to_float(series: pd.Series | Iterable | None) -> pd.Series:
    """Turn '$1,234.56' strings into floats; returns Series (may be empty)."""
    if series is None:
        return pd.Series([], dtype="float64")
    s = pd.Series(series)
    s = s.astype(str).str.replace(r"[$,]", "", regex=True)
    return pd.to_numeric(s, errors="coerce")

def get_col_ci(df: pd.DataFrame, name: str, default=None, dtype=str) -> pd.Series:
    """Case-insensitive getter that always returns a Series aligned to df."""
    if df is None or df.empty:
        return pd.Series([], dtype=dtype)
    if name in df.columns:
        return df[name].astype(dtype)
    lower_map = {c.lower(): c for c in df.columns}
    if name.lower() in lower_map:
        return df[lower_map[name.lower()]].astype(dtype)
    v = default() if callable(default) else default
    return pd.Series([v] * len(df), index=df.index, dtype=dtype)

def parse_date_utc(series: pd.Series) -> pd.Series:
    """Parse 'Date' to UTC; tries explicit formats first to avoid warnings."""
    s = series.astype(str)
    fmts = [
        "%m/%d/%Y %I:%M %p", "%m/%d/%y %I:%M %p",
        "%m/%d/%Y", "%m/%d/%y",
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
    ]
    for fmt in fmts:
        cand = pd.to_datetime(s, format=fmt, errors="coerce", utc=True)
        if cand.notna().mean() >= 0.80:
            return cand
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.to_datetime(s, errors="coerce", utc=True)
