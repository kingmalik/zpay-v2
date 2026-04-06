# backend/services/rates.py
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, Mapping, Optional, Tuple, Union

import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from backend.db.models import ZRateService, ZRateOverride
import re

DateLike = Union[date, datetime, str]

# One-time dispatch suffix: "ER012726 01" / "LS030626 01"
_ONETIME_RE = re.compile(r"\s+[A-Z]{2}\d{6}\s+\d{2}$")
# Day-of-week suffix: "(W)", "(F)", "(M/F)", "(T/H)", "(H)", "(HCV)", etc.
_DAY_RE = re.compile(r"\s+\([A-Z/]+\)$")
# Variant letter: "_A", "_B", "_D", "_ F" (with optional space)
_VARIANT_RE = re.compile(r"\s*_\s*[A-Z]$")
# [Wt] style bracket suffix
_BRACKET_RE = re.compile(r"\s*\[[^\]]+\]$")

# Company name aliases used during rate lookup.
# "Acumen International" ↔ "Acumen" (Excel files vary).
# "FirstAlt" ↔ "everDriven" — PDF batches were stored as "everDriven" before the
# rename; this ensures existing rate rows are still found under the new name.
_ACUMEN_COMPANY_ALIASES: dict[str, list[str]] = {
    "acumen international": ["acumen"],
    "acumen": ["acumen international"],
    # PDF batches were stored as "everdriven" before renaming to "FirstAlt"
    "firstalt": ["everdriven"],
    "everdriven": ["firstalt"],
}


def _service_name_candidates(name: str) -> list[str]:
    """
    Generate candidate base names by progressively stripping known suffixes.
    Returns list in priority order (most specific → most generic).
    """
    candidates: list[str] = []
    s = name.strip()
    candidates.append(s)

    # Strip one-time dispatch code first
    s2 = _ONETIME_RE.sub("", s)
    if s2 != s:
        candidates.append(s2.strip())
        s = s2.strip()

    # Strip bracket suffix [Wt]
    s2 = _BRACKET_RE.sub("", s)
    if s2 != s:
        candidates.append(s2.strip())
        s = s2.strip()

    # Strip variant letter (_A, _B, _ F)
    s2 = _VARIANT_RE.sub("", s)
    if s2 != s:
        candidates.append(s2.strip())
        # Also try stripping day suffix from this result
        s3 = _DAY_RE.sub("", s2.strip())
        if s3 != s2.strip():
            candidates.append(s3.strip())
        s = s2.strip()

    # Strip day suffix
    s2 = _DAY_RE.sub("", s)
    if s2 != s:
        candidates.append(s2.strip())
        # Also try stripping variant from this result
        s3 = _VARIANT_RE.sub("", s2.strip())
        if s3 != s2.strip():
            candidates.append(s3.strip())

    # Deduplicate while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _norm_text(v: Optional[str]) -> str:
    s = (v or "").strip()
    # collapse any whitespace (incl tabs / NBSP)
    s = re.sub(r"\s+", " ", s)
    # make lookups case-insensitive consistently
    s = s.lower()
    return s

def _norm_service_name(v) -> str:
    # IMPORTANT: normalize the same way for insert + lookup
    # (collapses whitespace + keeps case stable)
    s = _norm_text(v)
    s = " ".join(s.split())
    return s.upper()

def _as_date(v: Optional[DateLike]) -> Optional[date]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            # accepts 'YYYY-MM-DD' and full iso datetime strings
            return datetime.fromisoformat(s).date()
        except ValueError:
            return None
    return None


def _to_decimal(v) -> Optional[Decimal]:
    if v is None:
        return None
    # Numeric values from SQLAlchemy may already be Decimal; stringify is safe
    return Decimal(str(v))


def _pick_latest_service_row(
    db: Session,
    *,
    source: str,
    company_name: str,
    service_name: str,
) -> Optional[ZRateService]:
    """
    Pick newest matching ZRateService row, trying suffix-stripped fallbacks.
    Uses canonical matching to survive case/spacing differences in stored data.

    Company name aliases: Acumen files report "Acumen International" but many DB
    rows were inserted as "Acumen". When exact company lookup fails, the aliases
    dict causes a retry under the alternate name so all rows are found regardless
    of which company name variant was used at insert time.
    """
    source_n = _norm_text(source)
    company_n = _norm_text(company_name)

    def canon(col):
        return sa.func.lower(sa.func.regexp_replace(col, r"\s+", " ", "g"))

    # Build the ordered list of company names to try (primary first, then aliases)
    company_names_to_try = [company_n] + _ACUMEN_COMPANY_ALIASES.get(company_n, [])

    # Try each candidate name (exact → suffix-stripped → day-stripped)
    for candidate in _service_name_candidates(service_name or ""):
        name_n = _norm_text(candidate)
        for co_n in company_names_to_try:
            q = (
                db.query(ZRateService)
                .filter(
                    canon(ZRateService.source) == source_n,
                    canon(ZRateService.company_name) == co_n,
                    canon(ZRateService.service_name) == name_n,
                    # Skip rows with default_rate=0 when better matches may exist
                    ZRateService.default_rate != 0,
                )
            )
            if hasattr(ZRateService, "z_rate_service_id"):
                q = q.order_by(ZRateService.z_rate_service_id.desc())
            row = q.first()
            if row is not None:
                return row

    # Final fallback: allow zero-rate rows (better than no match at all)
    for candidate in _service_name_candidates(service_name or ""):
        name_n = _norm_text(candidate)
        for co_n in company_names_to_try:
            q = (
                db.query(ZRateService)
                .filter(
                    canon(ZRateService.source) == source_n,
                    canon(ZRateService.company_name) == co_n,
                    canon(ZRateService.service_name) == name_n,
                )
            )
            if hasattr(ZRateService, "z_rate_service_id"):
                q = q.order_by(ZRateService.z_rate_service_id.desc())
            row = q.first()
            if row is not None:
                return row

    return None


def resolve_rate_for_ride(
    db: Session,
    *,
    source: str,
    company_name: str,
    service_name: str,
    ride_date: Optional[DateLike] = None,
    currency: str = "USD",
) -> Tuple[Decimal, str, Optional[int], Optional[int]]:
    """
    Schema-aligned resolver:

    z_rate_service:
      - source (NOT NULL, default '')
      - company_name (NOT NULL, default '')
      - service_name
      - default_rate (Numeric)

    z_rate_override:
      - z_rate_service_id (FK)
      - effective_during (DATERANGE)
      - override_rate (Numeric)
      - active (bool, default true)

    Returns:
      (rate_decimal, source_str, z_rate_service_id, z_rate_override_id)

    Precedence:
      1) active override where effective_during contains ride_day
      2) service.default_rate
      3) else 0
    """
    source_n = _norm_text(source)
    company_n = _norm_text(company_name)
    service_n = _norm_text(service_name)

    svc = _pick_latest_service_row(
        db, source=source_n, company_name=company_n, service_name=service_n
    )
    if not svc:
        return Decimal("0"), "none", None, None

    svc_id = getattr(svc, "z_rate_service_id", None) or getattr(svc, "id", None)

    ride_day = _as_date(ride_date)
    if ride_day is not None and svc_id is not None:
        # Use daterange containment: effective_during @> ride_day
        # and only active overrides.
        q = (
            db.query(ZRateOverride)
            .filter(
                ZRateOverride.z_rate_service_id == svc_id,
                ZRateOverride.active.is_(True),
                ZRateOverride.effective_during.op("@>")(ride_day),
            )
        )

        # newest override wins: order by lower(effective_during) desc
        q = q.order_by(sa.func.lower(ZRateOverride.effective_during).desc())

        ov = q.first()
        if ov is not None and getattr(ov, "override_rate", None) is not None:
            ov_id = getattr(ov, "z_rate_override_id", None) or getattr(ov, "id", None)
            return _to_decimal(ov.override_rate) or Decimal("0"), "override", svc_id, ov_id

    # Default rate
    if getattr(svc, "default_rate", None) is None:
        return Decimal("0"), "service_default_none", svc_id, None

    return _to_decimal(svc.default_rate) or Decimal("0"), "service_default", svc_id, None


def ensure_z_rate_service(
    db: Session,
    *,
    source: str,
    company_name: str,
    service_key: str,
    service_name: str,
    currency: str = "USD",
) -> ZRateService:
    source_n = _norm_text(source)
    company_n = _norm_text(company_name)
    key_n = _norm_text(service_key)
    name_n = _norm_text(service_name)

    stmt = (
        insert(ZRateService)
        .values(
            source=source_n,
            company_name=company_n,
            service_key=key_n,
            service_name=name_n,
            currency=(currency or "USD").strip() or "USD",
            active=True,
        )
        .on_conflict_do_nothing(
            index_elements=["source", "company_name", "service_key"]
        )
        .returning(ZRateService.z_rate_service_id)
    )

    res = db.execute(stmt).scalar()
    if res is not None:
        return db.get(ZRateService, res)

    # already exists — fetch deterministically
    svc = (
        db.query(ZRateService)
        .filter(
            ZRateService.source == source_n,
            ZRateService.company_name == company_n,
            ZRateService.service_key == key_n,
        )
        .one_or_none()
    )

    if svc:
        return svc

    # should never happen, but safety net
    svc = ZRateService(
        source=source_n,
        company_name=company_n,
        service_key=key_n,
        service_name=name_n,
        currency=(currency or "USD").strip() or "USD",
        active=True,
    )
    db.add(svc)
    db.flush()
    return svc

def ensure_rate_services(
    db: Session,
    services: Iterable[Mapping[str, Any]],
    *,
    source: str,
    company_name: str,
) -> None:
    source_n = _norm_text(source)
    company_n = _norm_text(company_name)

    seen: set[tuple[str, str, str]] = set()
    payload: list[dict[str, Any]] = []

    for s in services:
        service_key = _norm_text(s.get("service_key"))
        service_name = _norm_service_name(s.get("service_name"))

        if not service_name:
            continue

        scope_key = (source_n, company_n, service_name)
        if scope_key in seen:
            continue
        seen.add(scope_key)

        payload.append(
            {
                "source": source_n,
                "company_name": company_n,
                "service_key": service_key,     # keep it (not unique)
                "service_name": service_name,   # UNIQUE SCOPE
                "currency": (_norm_text(s.get("currency")) or "USD"),
                "active": bool(s.get("active", True)),
                "default_rate": s.get("default_rate", 0),
            }
        )

    if not payload:
        return

    stmt = (
        insert(ZRateService)
        .values(payload)
        .on_conflict_do_nothing(index_elements=["source", "company_name", "service_key"])
    )
    db.execute(stmt)