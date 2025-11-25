from __future__ import annotations
import pandas as pd

# Prefer details-only parser; fallback to dual return
try:
    from backend.parser import parse_details as _parse_details_only
except Exception:
    _parse_details_only = None
try:
    from backend.parser import parse_summary_and_details as _parse_both
except Exception:
    _parse_both = None

def parse_details(pdf_path: str) -> pd.DataFrame:
    """Return the Details DataFrame for the given PDF path."""
    if _parse_details_only is not None:
        return _parse_details_only(pdf_path)
    if _parse_both is not None:
        details, _summary = _parse_both(pdf_path)
        return details
    raise RuntimeError("No parser available (need backend.parser.parse_details or parse_summary_and_details)")
