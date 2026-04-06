
from dataclasses import dataclass
import re
import pdfplumber
import pandas as pd
from typing import List, Tuple, Dict, Optional

SUMMARY_HEADERS = ["Person","Code","Active Between","Days","Runs","Miles","Gross","RAD","WUD","Net Pay"]
DETAILS_HEADERS = ["Person","Code","Date","Key","Name","Miles","Gross","Net Pay"]

CURRENCY_RE = re.compile(r"^\s*\$?\s*([+-]?\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*$")
NUMBER_RE = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*$")

@dataclass
class TableSpec:
    section_title: str               # "Summary" or "Details"f
    headers: List[str]

SUMMARY_SPEC = TableSpec("Summary", SUMMARY_HEADERS)
DETAILS_SPEC = TableSpec("Details", DETAILS_HEADERS)


def _clean_cell(v: str) -> str:
    return (v or "").strip()


def _to_float_maybe(v: str) -> Optional[float]:
    if v is None:
        return None
    s = str(v).strip()
    m = CURRENCY_RE.match(s) or NUMBER_RE.match(s)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except Exception:
        return None


def _find_title_y(page: "pdfplumber.page.Page", title: str) -> Optional[float]:
    for obj in page.extract_words(keep_blank_chars=False, use_text_flow=True, x_tolerance=2, y_tolerance=2):
        if obj.get("text", "").strip().lower() == title.lower():
            return (obj["top"] + obj["bottom"]) / 2
    txt = (page.extract_text() or "")
    if title.lower() in txt.lower():
        return 72.0
    return None


def _normalize_header_text(s: str) -> str:
    return " ".join((s or "").split()).strip().lower()


def _locate_header_row_strict(page: "pdfplumber.page.Page", expected_headers: List[str]) -> Optional[Tuple[float, List[Tuple[str, float, float]]]]:
    expected_norm = { _normalize_header_text(h): h for h in expected_headers }
    words = page.extract_words(extra_attrs=["size"])
    line_groups: Dict[int, List[dict]] = {}
    for w in words:
        y_hash = int(round((w["top"] + w["bottom"]) / 2.0))
        line_groups.setdefault(y_hash, []).append(w)

    for yk, line in line_groups.items():
        line_sorted = sorted(line, key=lambda z: z["x0"])
        tokens = [w["text"] for w in line_sorted]
        n = len(tokens)
        matches: List[Tuple[str, float, float]] = []
        used = [False]*n
        for win in (3, 2, 1):
            i = 0
            while i <= n - win:
                if any(used[i:i+win]):
                    i += 1
                    continue
                phrase = " ".join(tokens[i:i+win])
                key = _normalize_header_text(phrase)
                if key in expected_norm:
                    header = expected_norm[key]
                    x0 = line_sorted[i]["x0"]
                    x1 = line_sorted[i+win-1]["x1"]
                    matches.append((header, x0, x1))
                    for j in range(i, i+win):
                        used[j] = True
                    i += win
                else:
                    i += 1
        if len(matches) >= max(5, len(expected_headers)//2):
            seen = {}
            for h, x0, x1 in sorted(matches, key=lambda t: t[1]):
                if h not in seen:
                    seen[h] = (h, x0, x1)
            cols = list(seen.values())
            return (float(yk), cols)
    return None


def _locate_header_row(page: "pdfplumber.page.Page", expected_headers: List[str]) -> Optional[Tuple[float, List[Tuple[str, float, float]]]]:
    words = page.extract_words(extra_attrs=["size"])
    line_groups: Dict[int, List[dict]] = {}
    for w in words:
        y_hash = int(round((w["top"] + w["bottom"]) / 2.0))
        line_groups.setdefault(y_hash, []).append(w)

    for yk, line in line_groups.items():
        texts = [w["text"].strip() for w in sorted(line, key=lambda z: z["x0"])]
        joined = " ".join(texts).lower()
        hits = sum(1 for h in expected_headers if h.lower() in joined)
        if hits >= max(3, len(expected_headers) // 2):
            cols = []
            for w in sorted(line, key=lambda z: z["x0"]):
                t = w["text"].strip()
                if any(t.lower() in hh.lower() for hh in expected_headers):
                    cols.append((t, w["x0"], w["x1"]))
            merged = []
            i = 0
            while i < len(cols):
                text, x0, x1 = cols[i]
                j = i + 1
                candidate = text
                while j < len(cols):
                    candidate2 = candidate + " " + cols[j][0]
                    if any(candidate2.lower() == h.lower() for h in expected_headers):
                        x1 = cols[j][2]
                        candidate = candidate2
                        i = j
                        j += 1
                    else:
                        break
                merged.append((candidate, x0, x1))
                i += 1
            filtered = [(h, x0, x1) for (h, x0, x1) in merged if any(h.lower() == eh.lower() for eh in expected_headers)]
            if filtered:
                return (float(yk), filtered)
    return None


def _expand_columns_to_full_width(cols: List[Tuple[str, float, float]], page_width: float, gutter: float = 6.0) -> List[Tuple[str, float, float]]:
    cols_sorted = sorted(cols, key=lambda c: c[1])
    xs = [c[1] for c in cols_sorted] + [cols_sorted[-1][2]]
    expanded = []
    for idx, (name, x0, x1) in enumerate(cols_sorted):
        left = 0.0 if idx == 0 else (xs[idx-1] + x0)/2 - gutter
        right = page_width if idx == len(cols_sorted)-1 else (x1 + cols_sorted[idx+1][1])/2 + gutter
        expanded.append((name, max(0.0, left), min(page_width, right)))
    return expanded


def _find_next_section_y(page: "pdfplumber.page.Page", after_y: float) -> Optional[float]:
    candidates: List[float] = []
    for w in page.extract_words(keep_blank_chars=False, use_text_flow=True, x_tolerance=2, y_tolerance=2):
        txt = (w.get("text", "").strip()).lower()
        if txt in {"summary", "details"}:
            y = (w["top"] + w["bottom"]) / 2
            if y > after_y + 6:
                candidates.append(y)
    return min(candidates) if candidates else None


def _extract_table_rows(page: "pdfplumber.page.Page", header_y: float, cols: List[Tuple[str, float, float]], bottom_y: Optional[float]) -> List[List[str]]:
    page_width = page.width
    y_top = header_y + 8
    if bottom_y is None:
        bottom_y = page.height - 24
    if bottom_y <= y_top + 2:
        return []

    expanded_cols = _expand_columns_to_full_width(cols, page_width)

    col_texts: List[List[Tuple[float, str]]] = []
    for _, x0, x1 in expanded_cols:
        x0c, x1c = max(0.0, min(x0, x1)), min(page_width, max(x0, x1))
        if x1c - x0c <= 1:
            col_texts.append([])
            continue
        col_region = page.crop((x0c, y_top, x1c, bottom_y))
        words = col_region.extract_words(x_tolerance=2, y_tolerance=2)
        col_texts.append([(((w["top"] + w["bottom"]) / 2.0), w["text"]) for w in words])

    y_bins: List[float] = []
    for lst in col_texts:
        for y, _ in lst:
            found = False
            for i, yb in enumerate(y_bins):
                if abs(y - yb) <= 4:
                    y_bins[i] = (y_bins[i] + y) / 2.0
                    found = True
                    break
            if not found:
                y_bins.append(y)
    y_bins = sorted(y_bins)

    rows: List[List[str]] = []
    for yb in y_bins:
        row_cells = []
        for lst in col_texts:
            parts = [t for (y, t) in lst if abs(y - yb) <= 4]
            row_cells.append(" ".join(parts).strip())
        if any(c for c in row_cells):
            rows.append(row_cells)

    return rows


def parse_section_table(page: "pdfplumber.page.Page", spec: TableSpec) -> pd.DataFrame:
    title_y = _find_title_y(page, spec.section_title)
    if title_y is None:
        return pd.DataFrame(columns=spec.headers)

    header_loc = _locate_header_row_strict(page, spec.headers) or _locate_header_row(page, spec.headers)
    if not header_loc:
        return pd.DataFrame(columns=spec.headers)

    header_y, cols = header_loc
    bottom_y = _find_next_section_y(page, header_y)

    rows = _extract_table_rows(page, header_y, cols, bottom_y)
    if not rows:
        return pd.DataFrame(columns=spec.headers)

    df = pd.DataFrame(rows, columns=spec.headers[:len(rows[0])] if rows else spec.headers)

    num_like = {"Miles","Gross","RAD","WUD","Net Pay","Runs","Days","Code"}
    for col in df.columns:
        if col in num_like:
            df[col] = df[col].apply(lambda v: _to_float_maybe(str(v)) if pd.notna(v) else None)
        else:
            df[col] = df[col].astype(str).map(_clean_cell)

    def _looks_like_header(row: pd.Series) -> bool:
        return sum(1 for h in spec.headers if str(row.get(h, "")).strip().lower() == h.lower()) >= 2
    if not df.empty and _looks_like_header(df.iloc[0]):
        df = df.iloc[1:].reset_index(drop=True)

    return df


def _concat_clean(frames: List[pd.DataFrame], headers: List[str]) -> pd.DataFrame:
    cleaned: List[pd.DataFrame] = []
    for f in frames:
        if not isinstance(f, pd.DataFrame):
            continue
        if f.empty:
            continue
        f2 = f.dropna(how="all")
        if f2.empty:
            continue
        cleaned.append(f2)
    return pd.concat(cleaned, ignore_index=True) if cleaned else pd.DataFrame(columns=headers)


def parse_payroll_tables(pdf_path: str) -> Dict[str, pd.DataFrame]:
    summary_frames: List[pd.DataFrame] = []
    details_frames: List[pd.DataFrame] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            txt = (page.extract_text() or "").lower()
            if "summary" in txt:
                df_s = parse_section_table(page, SUMMARY_SPEC)
                if not df_s.empty:
                    summary_frames.append(df_s)
            if "details" in txt:
                df_d = parse_section_table(page, DETAILS_SPEC)
                if not df_d.empty:
                    details_frames.append(df_d)

    summary_df = _concat_clean(summary_frames, SUMMARY_SPEC.headers)
    details_df = _concat_clean(details_frames, DETAILS_SPEC.headers)
    return {"summary": summary_df, "details": details_df}
