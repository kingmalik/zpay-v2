import io
import csv
import pandas as pd
from typing import Tuple, Dict, Optional
from .cleaning import clean_bytes
from .pdf_reader import extract_pdf

def _detect_delimiter(sample: str) -> str:
    # Try Sniffer first; fallback to header heuristic
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=[",", "\t", ";", "|"])
        return dialect.delimiter
    except Exception:
        header = sample.splitlines()[0] if sample else ""
        candidates = [",", "\t", ";", "|"]
        counts = {d: header.count(d) for d in candidates}
        best = max(counts, key=counts.get) if counts else ","
        return best if counts.get(best, 0) > 0 else ","

def read_csv_robust(file_bytes: bytes) -> Tuple[pd.DataFrame, Dict]:
    cleaned = clean_bytes(file_bytes)
    sample = cleaned[:4096].decode("utf-8", errors="replace")
    delimiter = _detect_delimiter(sample)

    info = {
        "kind": "csv",
        "detected_delimiter": delimiter,
        "lines_preview": "\n".join(sample.splitlines()[:10])
    }

    # First attempt: let pandas infer separators
    try:
        df = pd.read_csv(
            io.BytesIO(cleaned),
            engine="python",
            sep=None,                 # infer
            dtype=str,
            on_bad_lines="skip",      # drop malformed lines
            quoting=csv.QUOTE_MINIMAL
        )
        # Fallback: force detected delimiter if we only got 1 col
        if df.shape[1] == 1 and delimiter != ",":
            df = pd.read_csv(
                io.BytesIO(cleaned),
                engine="python",
                sep=delimiter,
                dtype=str,
                on_bad_lines="skip",
                quoting=csv.QUOTE_MINIMAL
            )
        df.columns = [c.strip() for c in df.columns]
        df = df.applymap(lambda x: x.strip() if isinstance(x, str) else x)
        return df, info
    except Exception as e:
        # Second attempt: force delimiter and warn on bad lines
        try:
            df = pd.read_csv(
                io.BytesIO(cleaned),
                engine="python",
                sep=delimiter,
                dtype=str,
                on_bad_lines="warn",
                quoting=csv.QUOTE_MINIMAL
            )
            df.columns = [c.strip() for c in df.columns]
            df = df.applymap(lambda x: x.strip() if isinstance(x, str) else x)
            return df, info
        except Exception as e2:
            raise RuntimeError(f"unreadable_csv: {e2}")

def read_excel_robust(file_bytes: bytes) -> Tuple[pd.DataFrame, Dict]:
    cleaned = clean_bytes(file_bytes)  # mostly for newline normalizing if CSV mistakenly named
    info = {"kind": "excel"}
    try:
        df = pd.read_excel(io.BytesIO(cleaned), dtype=str)  # openpyxl behind the scenes
        df.columns = [c.strip() for c in df.columns]
        df = df.applymap(lambda x: x.strip() if isinstance(x, str) else x)
        return df, info
    except Exception as e:
        raise RuntimeError(f"unreadable_excel: {e}")

def ingest_file(filename: str, file_bytes: bytes):
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        meta = extract_pdf(file_bytes)
        return None, meta
    if name.endswith((".xls", ".xlsx")):
        df, info = read_excel_robust(file_bytes)
        return df, info
    # default: CSV/TSV/pipe-delimited
    df, info = read_csv_robust(file_bytes)
    return df, info
