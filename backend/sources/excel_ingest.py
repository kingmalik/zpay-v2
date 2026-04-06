# zpay/sources/excel_ingest.py
from __future__ import annotations
import pandas as pd
import yaml
from pathlib import Path

def load_source_config(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def read_excel_with_mapping(xlsx_path: str | Path, cfg_path: str | Path):
    cfg = load_source_config(cfg_path)
    sheets = cfg["sheet_names"]

    # Read Excel sheets
    df_summary_raw = pd.read_excel(xlsx_path, sheet_name=sheets["summary"])
    df_details_raw = pd.read_excel(xlsx_path, sheet_name=sheets["details"])

    # Rename columns to canonical names
    df_summary = df_summary_raw.rename(columns=cfg["columns"]["summary"])
    df_details = df_details_raw.rename(columns=cfg["columns"]["details"])

    # Keep only mapped columns
    df_summary = df_summary[list(cfg["columns"]["summary"].keys())]
    df_details = df_details[list(cfg["columns"]["details"].keys())]

    # Parse dates/times
    for col in ("payroll_start", "payroll_end", "date", "start_ts", "end_ts"):
        if col in df_summary.columns:
            if "ts" in col:
                continue
        if col in df_details.columns:
            df_details[col] = pd.to_datetime(df_details[col], errors="coerce")
    if "payroll_start" in df_summary.columns:
        df_summary["payroll_start"] = pd.to_datetime(df_summary["payroll_start"], errors="coerce")
    if "payroll_end" in df_summary.columns:
        df_summary["payroll_end"] = pd.to_datetime(df_summary["payroll_end"], errors="coerce")

    # Numeric coercions
    for c in ("miles", "base_pay", "tips", "adjustments"):
        if c in df_details.columns:
            df_details[c] = pd.to_numeric(df_details[c], errors="coerce").fillna(0)

    return df_summary, df_details, cfg

