# backend/services/service_keys.py
import re
from typing import Any, Mapping

_ALLOWED = re.compile(r"[^a-z0-9._-]+")

def _norm(val: Any) -> str:
    if val is None:
        return ""
    s = str(val).strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = s.replace("&", " and ")
    s = _ALLOWED.sub("-", s)
    s = re.sub(r"-{2,}", "-", s)
    return s.strip("-")

def build_service_key_for_acumen(row: Mapping[str, Any]) -> str:
    # Prefer trip_code (stable)
    trip_code = row.get("trip_code") or row.get("Trip Code") or row.get("tripcode")
    if trip_code is not None:
        code = str(trip_code).strip()
        # handle "7660064.0" style
        if code.endswith(".0") and code[:-2].isdigit():
            code = code[:-2]
        code = _norm(code)
        if code:
            return f"acumen|trip|{code}"

    # Fallback to trip_name
    trip_name = row.get("trip_name") or row.get("Trip Name")
    name = _norm(trip_name)
    if name:
        return f"acumen|tripname|{name}"

    return "acumen|fallback|unknown"

def build_service_key_for_maz(row: Mapping[str, Any]) -> str:
    # Prefer trip_code (stable)
    trip_code = row.get("trip_code") or row.get("Trip Code") or row.get("tripcode")
    if trip_code is not None:
        code = str(trip_code).strip()
        # handle "7660064.0" style
        if code.endswith(".0") and code[:-2].isdigit():
            code = code[:-2]
        code = _norm(code)
        if code:
            return f"acumen|trip|{code}"

    # Fallback to trip_name
    trip_name = row.get("trip_name") or row.get("Trip Name")
    name = _norm(trip_name)
    if name:
        return f"maz|tripname|{name}"

    return "maz|fallback|unknown"
