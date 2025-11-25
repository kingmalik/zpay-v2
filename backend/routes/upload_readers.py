# backend/routes/upload_readers.py
from __future__ import annotations

import csv
from io import StringIO
from typing import Optional, Tuple

import pandas as pd


def _detect_delimiter(sample_text: str, default: str = ",") -> str:
    try:
        dialect = csv.Sniffer().sniff(sample_text, delimiters=[",", "\t", ";", "|"])
        return dialect.delimiter
    except Exception:
        return default


def read_uploaded_file(
    raw: bytes,
    filename: Optional[str],
    content_type: Optional[str],
) -> Tuple[pd.DataFrame, str]:
    """
    CSV/TSV fast path only (self-contained; avoids Excel engines).
    Returns: (DataFrame, info_string)
    Raises: ValueError on unreadable/empty input.
    """
    if not raw:
        raise ValueError("empty_file")

    # Detect delimiter cheaply from the first few KiB
    head = raw[:8192].decode("utf-8-sig", errors="ignore")
    delim = _detect_delimiter(head, default=",")

    try:
        df = pd.read_csv(
            StringIO(raw.decode("utf-8-sig", errors="ignore")),
            sep=delim,
            engine="c",           # fast
            dtype=str,            # avoid dtype guessing
            keep_default_na=False # keep empty strings as ""
        )
    except Exception as e:
        raise ValueError(f"unreadable_csv: {e!s}")

    if df is None or df.empty:
        r

