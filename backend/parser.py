from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import pdfplumber

# We only emit these columns, as plain text (no normalization)
DETAILS_HEADERS = ["Person", "Code", "Date", "Key", "Name", "Miles", "Gross", "Net Pay"]
EMPTY_SUMMARY_HEADERS = [
    "Person", "Code", "Active Between", "Days", "Runs",
    "Miles", "Gross", "RAD", "WUD", "Net Pay"
]

# ---------- helpers ----------

def _norm(s: str) -> str:
    """lowercase + collapse whitespace (helps match 'Net    Pay')."""
    return " ".join((s or "").split()).strip().lower()

def _locate_header_row_strict(
    page: "pdfplumber.page.Page",
    expected_headers: List[str],
) -> Optional[Tuple[float, List[Tuple[str, float, float]]]]:
    """
    Find the header row by scanning each text line and matching 1–3 word windows
    to expected header names (case/space-insensitive). Returns:
      (y_center, [(header_text, x0, x1), ...])  or  None
    """
    expect = {_norm(h): h for h in expected_headers}
    words = page.extract_words(extra_attrs=["size"])

    # group words by approximate baseline Y
    lines: Dict[int, List[dict]] = {}
    for w in words:
        yk = int(round((w["top"] + w["bottom"]) / 2.0))
        lines.setdefault(yk, []).append(w)

    for yk, line in lines.items():
        line_sorted = sorted(line, key=lambda z: z["x0"])
        toks = [w["text"] for w in line_sorted]
        n = len(toks)
        matches: List[Tuple[str, float, float]] = []
        used = [False] * n

        # Greedy sliding windows: 3 → 2 → 1 tokens
        for win in (3, 2, 1):
            i = 0
            while i <= n - win:
                if any(used[i : i + win]):
                    i += 1
                    continue
                phrase = " ".join(toks[i : i + win])
                key = _norm(phrase)
                if key in expect:
                    h = expect[key]
                    x0 = line_sorted[i]["x0"]
                    x1 = line_sorted[i + win - 1]["x1"]
                    matches.append((h, x0, x1))
                    for j in range(i, i + win):
                        used[j] = True
                    i += win
                else:
                    i += 1

        # treat as header if we captured at least half the headers (or ≥5)
        if len(matches) >= max(5, len(expected_headers) // 2):
            # de-dup by header name (keep left-most)
            seen = {}
            for h, x0, x1 in sorted(matches, key=lambda t: t[1]):
                if h not in seen:
                    seen[h] = (h, x0, x1)
            cols = list(seen.values())
            return (float(yk), cols)

    return None

def _expand_spans(
    cols: List[Tuple[str, float, float]],
    page_width: float,
    gutter: float = 6.0,
) -> List[Tuple[str, float, float]]:
    """Expand each header’s x-span to capture its column’s text."""
    cols = sorted(cols, key=lambda c: c[1])
    xs = [c[1] for c in cols] + [cols[-1][2]]
    out = []
    for i, (name, x0, x1) in enumerate(cols):
        left = 0.0 if i == 0 else (xs[i - 1] + x0) / 2 - gutter
        right = page_width if i == len(cols) - 1 else (x1 + cols[i + 1][1]) / 2 + gutter
        out.append((name, max(0.0, left), min(page_width, right)))
    return out

def _find_next_title_below(page: "pdfplumber.page.Page", after_y: float) -> Optional[float]:
    """Find Y of next 'Summary' or 'Details' *below* after_y; else None."""
    candidates = []
    for w in page.extract_words(keep_blank_chars=False, use_text_flow=True, x_tolerance=2, y_tolerance=2):
        txt = _norm(w.get("text", ""))
        if txt in {"summary", "details"}:
            y = (w["top"] + w["bottom"]) / 2
            if y > after_y + 6:
                candidates.append(y)
    return min(candidates) if candidates else None

def _extract_details_from_page(page: "pdfplumber.page.Page") -> pd.DataFrame:
    """Return a Details frame (raw strings). Empty if not found on this page."""
    loc = _locate_header_row_strict(page, DETAILS_HEADERS)
    if not loc:
        return pd.DataFrame(columns=DETAILS_HEADERS)
    header_y, cols = loc

    y_top = header_y + 8
    y_bottom = _find_next_title_below(page, header_y) or (page.height - 24)
    if y_bottom <= y_top + 2:
        return pd.DataFrame(columns=DETAILS_HEADERS)

    spans = _expand_spans(cols, page.width)

    # read columns separately, keep (y, text) for alignment
    col_texts: List[List[Tuple[float, str]]] = []
    present_headers = [h for (h, _, _) in spans]
    for _, x0, x1 in spans:
        x0c, x1c = max(0.0, min(x0, x1)), min(page.width, max(x0, x1))
        if x1c - x0c <= 1:
            col_texts.append([])
            continue
        region = page.crop((x0c, y_top, x1c, y_bottom))
        words = region.extract_words(x_tolerance=2, y_tolerance=2)
        col_texts.append([(((w["top"] + w["bottom"]) / 2.0), w["text"]) for w in words])

    # bin by Y
    ybins: List[float] = []
    for lst in col_texts:
        for y, _ in lst:
            placed = False
            for i, yb in enumerate(ybins):
                if abs(y - yb) <= 4:
                    ybins[i] = (y + yb) / 2.0
                    placed = True
                    break
            if not placed:
                ybins.append(y)
    ybins.sort()

    # build rows
    rows: List[List[str]] = []
    for yb in ybins:
        cells = []
        for lst in col_texts:
            parts = [t for (y, t) in lst if abs(y - yb) <= 4]
            cells.append(" ".join(parts).strip())
        if any(cells):
            rows.append(cells)

    if not rows:
        return pd.DataFrame(columns=DETAILS_HEADERS)

    # frame with detected headers; add any missing columns empty; reorder
    df = pd.DataFrame(rows, columns=present_headers)
    for h in DETAILS_HEADERS:
        if h not in df.columns:
            df[h] = ""
    return df[DETAILS_HEADERS]

# ---------- public API ----------

def parse_details(pdf_path: str) -> pd.DataFrame:
    """Extract the Details table (across all pages). Returns raw strings."""
    frames: List[pd.DataFrame] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            if "details" in (page.extract_text() or "").lower():
                dfp = _extract_details_from_page(page)
                if not dfp.empty:
                    frames.append(dfp)

    if not frames:
        return pd.DataFrame(columns=DETAILS_HEADERS)

    out = pd.concat(frames, ignore_index=True)
    return out.dropna(how="all").reset_index(drop=True)

# Backward-compat wrapper for your FastAPI app import.
# Still "details only": we return an EMPTY summary.
def parse_summary_and_details(pdf_path: str):
    details_df = parse_details(pdf_path)
    summary_df = pd.DataFrame(columns=EMPTY_SUMMARY_HEADERS)
    return details_df, summary_df

