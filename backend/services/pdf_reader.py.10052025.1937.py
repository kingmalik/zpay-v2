
import io
import pdfplumber
import pandas as pd
from typing import List, Tuple

EXPECTED_COLS = ["Person","Code","Date","Key","Name","Miles","Gross","Net Pay"]

def _looks_like_header(row: list) -> bool:
    if not row:
        return False
    tokens = [str(x or "").strip().lower() for x in row]
    hits = sum(1 for t in tokens if t in {"person","code","date","key","name","miles","gross","net pay","netpay","net_pay"})
    return hits >= 4

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
    out = []
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
                header_row = None
                for r_i, row in enumerate(df.values.tolist()[:5]):
                    if _looks_like_header(row):
                        header_row = r_i
                        break
                if header_row is None:
                    header_row = 0
                header = [str(x or "").strip() for x in df.iloc[header_row].tolist()]
                header = _canonicalize_columns(header)
                df = df.iloc[header_row+1:].reset_index(drop=True)
                df.columns = header
                matches = sum(1 for c in df.columns if c in EXPECTED_COLS)
                if matches >= 5:
                    out.append((idx, df))
    return out

def normalize_details_tables(tables: List[Tuple[int, pd.DataFrame]], source_file: str) -> pd.DataFrame:
    frames = []
    for page, df in tables:
        for col in EXPECTED_COLS:
            if col not in df.columns:
                df[col] = None
        df = df[EXPECTED_COLS].copy()
        df = df.applymap(lambda x: x.strip() if isinstance(x, str) else x)

        # Drop repeated headers
        for col in ["Person","Code","Date","Miles","Gross","Net Pay"]:
            df = df[~(df[col].str.lower().fillna("") == col.lower())]

        # Forward-fill Person/Code
        df["Person"] = df["Person"].replace("", None).ffill()
        df["Code"] = df["Code"].replace("", None).ffill()

        def _to_float(v):
            if v is None: return None
            s = str(v).replace(",", "").replace("$", "").strip()
            if s == "": return None
            try:
                return float(s)
            except:
                return None

        df["Miles"] = df["Miles"].apply(_to_float)
        df["Gross"] = df["Gross"].apply(_to_float)
        df["Net Pay"] = df["Net Pay"].apply(_to_float)

        df["Date"] = pd.to_datetime(df["Date"], errors="coerce", infer_datetime_format=True)
        df["Key"] = df["Key"].astype(str).str.strip().replace({"nan": None, "": None})
        df["Name"] = df["Name"].astype(str).str.strip().replace({"nan": None, "": None})
        df["source_page"] = page
        df["source_file"] = source_file

        mask_valid = df["Date"].notna() & (df[["Miles","Gross","Net Pay"]].notna().any(axis=1))
        frames.append(df[mask_valid])

    if not frames:
        return pd.DataFrame(columns=EXPECTED_COLS + ["source_page","source_file"])

    all_df = pd.concat(frames, ignore_index=True)

    def _valid_person(p):
        if p is None: return False
        s = str(p).strip()
        if not s: return False
        return not s.isdigit()

    all_df = all_df[all_df["Person"].apply(_valid_person)]
    return all_df.reset_index(drop=True)
