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
# Trailing 2-digit route number, e.g. "Alderwood OB 03" → prefix="Alderwood OB ", num=3
_TRAILING_NUM_RE = re.compile(r"^(.*\D)(\d{2})$")
# ODT (On Demand Trip) suffix: " ODT 06" / " ODT 01" etc.
# FA appends this tag when a canceled trip is reinstated mid-day.
# ODT pays the same rate as the base route — strip to find the base.
_ODT_RE = re.compile(r"\s+ODT\s+\d+", re.IGNORECASE)

# Company name aliases used during rate lookup.
#
# FA batches are stored under whichever company_name the import used at that
# point in time.  Historical progression:
#   "Acumen International"  (earliest xlsx imports, still common in rate rows)
#   "Acumen"                (mid-period imports)
#   "FirstAlt"              (current — batch.company_name="FirstAlt" since W16)
#   "everDriven"            (PDF batches stored under this name before rename)
#
# All four names refer to the same FA contract.  Any lookup under one name
# must also try the others so that rate rows created under an old name are
# still found when a new-name batch imports.
_ACUMEN_COMPANY_ALIASES: dict[str, list[str]] = {
    "acumen international": ["acumen", "firstalt", "everdriven"],
    "acumen":               ["acumen international", "firstalt", "everdriven"],
    "firstalt":             ["acumen", "acumen international", "everdriven"],
    "everdriven":           ["acumen", "acumen international", "firstalt"],
}


def _service_name_candidates(name: str) -> list[str]:
    """
    Generate candidate base names by progressively stripping known suffixes.
    Returns list in priority order (most specific → most generic).

    Suffix-stripping cascade:
      1. One-time dispatch code ("ER012726 01")
      2. Bracket suffix ("[Wt]")
      3. Variant letter ("_A", "_B")
      4. Day-of-week suffix ("(W)", "(M/F)")

    Numbered-neighbor expansion (added 2026-05-06):
      After all suffix stripping, if the resulting base name ends in a 2-digit
      route number (e.g. "Foo OB 03"), add ±1 and ±2 neighbors so that lookups
      for "Foo OB 04" can find "Foo OB 03" when no exact match exists.
      Neighbors are appended AFTER all suffix-stripped forms — they are lowest
      priority (last resort within the candidate list).
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

    # Deduplicate while preserving order (before ODT expansion and numbered neighbors)
    seen: set[str] = set()
    out: list[str] = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            out.append(c)

    # Capture the neighbor-expansion base BEFORE ODT block runs.
    # ODT expansion will append route-number forms (e.g. "Albert Einstein ES IB 06")
    # which end in a 2-digit number and would trigger neighbor expansion if we read
    # out[-1] after the block. Neighbors of an ODT-derived candidate are NOT valid
    # fallbacks — adjacent routes don't necessarily share the same pay rate and
    # using them would silently underpay or overpay the driver with no audit trail.
    # The guard relies on `name` still containing the ODT token at this point —
    # no upstream suffix stripper must remove "ODT NN" before this function is called.
    _neighbor_base = out[-1] if out else name.strip()

    # ODT (On Demand Trip) expansion — added 2026-05-21.
    # FA tags reinstated mid-day trips as e.g. "Albert Einstein ES IB ODT 06".
    # These pay the SAME rate as the base route. Generate candidates by:
    #   1. Swapping the ODT number for ODT 01 (most common base variant in rate table)
    #   2. Swapping for ODT 02 (second most common)
    #   3. Stripping " ODT NN" entirely (bare route name without ODT tag)
    #   4. Replacing " ODT NN" with " NN" (route-number-only form, no ODT keyword)
    # Only triggered when the name contains the ODT token — no effect on other rides.
    if _ODT_RE.search(name):
        # Work from the most-stripped form produced so far (already in `out`)
        for base in list(out):
            if not _ODT_RE.search(base):
                continue
            # Swap ODT number → ODT 01
            odt01 = _ODT_RE.sub(" ODT 01", base).strip()
            if odt01 not in seen:
                seen.add(odt01)
                out.append(odt01)
            # Swap ODT number → ODT 02
            odt02 = _ODT_RE.sub(" ODT 02", base).strip()
            if odt02 not in seen:
                seen.add(odt02)
                out.append(odt02)
            # Strip ODT token entirely → bare base route name
            no_odt = _ODT_RE.sub("", base).strip()
            if no_odt and no_odt not in seen:
                seen.add(no_odt)
                out.append(no_odt)
            # Replace " ODT NN" with " NN" → route-number form
            no_odt_kw = re.sub(r"\s+ODT\s+(\d+)", r" \1", base, flags=re.IGNORECASE).strip()
            if no_odt_kw and no_odt_kw not in seen:
                seen.add(no_odt_kw)
                out.append(no_odt_kw)

    # Numbered-neighbor expansion: for the most-stripped base form (captured
    # BEFORE ODT expansion so ODT-derived route-number forms are excluded),
    # generate ±1/±2 neighbors as last-resort candidates.
    m = _TRAILING_NUM_RE.match(_neighbor_base)
    if m:
        prefix = m.group(1)   # e.g. "Alderwood OB "
        num = int(m.group(2)) # e.g. 3
        for delta in (1, 2):
            for n in (num - delta, num + delta):
                if n >= 0:
                    neighbor = f"{prefix}{n:02d}"
                    if neighbor not in seen:
                        seen.add(neighbor)
                        out.append(neighbor)

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
            index_elements=["service_key"]
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

def _find_sibling_rate_in_rates(
    db: Session,
    *,
    source: str,
    company_name: str,
    service_name: str,
) -> Optional[tuple]:
    """
    Look for an active sibling z_rate_service row with a non-zero default_rate.
    Returns (default_rate, sibling_service_name) or None.

    Uses _service_name_candidates (which now includes numbered-neighbor expansion)
    but skips the first candidate (that is the route itself) so we only look at
    siblings, not the route's own row.

    Company aliases from _ACUMEN_COMPANY_ALIASES are tried for every candidate
    so that a rate row stored under "Acumen International" is found when the
    current import uses "FirstAlt".
    """
    canon = lambda col: sa.func.lower(sa.func.regexp_replace(col, r"\s+", " ", "g"))

    src_n = _norm_text(source)
    comp_n = _norm_text(company_name)
    company_names_to_try = [comp_n] + _ACUMEN_COMPANY_ALIASES.get(comp_n, [])

    # All candidates except the first (exact self match)
    siblings = _service_name_candidates(service_name)[1:]

    for candidate in siblings:
        cand_n = _norm_text(candidate)
        for co_n in company_names_to_try:
            row = (
                db.query(ZRateService)
                .filter(
                    canon(sa.func.coalesce(ZRateService.source, "")) == src_n,
                    canon(sa.func.coalesce(ZRateService.company_name, "")) == co_n,
                    canon(ZRateService.service_name) == cand_n,
                    ZRateService.active.is_(True),
                    ZRateService.default_rate > 0,
                )
                .order_by(ZRateService.z_rate_service_id.desc())
                .first()
            )
            if row is not None:
                return (row.default_rate, row.service_name)

    return None


def ensure_rate_services(
    db: Session,
    services: Iterable[Mapping[str, Any]],
    *,
    source: str,
    company_name: str,
) -> None:
    """
    Upsert z_rate_service rows.  When a new route has no rate (default_rate=0),
    attempt sibling-rate inheritance before committing the $0 row.  Tags every
    new row with default_rate_source so dispatch can audit which rates were inferred.

    Sibling logic (2026-05-06):
      1. Strip letter suffix (_B) → check base name
      2. Numbered neighbors (±1, ±2) on trailing 2-digit route number
      3. Inherit rate + tag 'inherited_from_sibling'  OR  tag 'unknown_route' if nothing found
    """
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

        supplied_rate = s.get("default_rate", 0)
        try:
            supplied_rate_val = float(supplied_rate)
        except (TypeError, ValueError):
            supplied_rate_val = 0.0

        if supplied_rate_val > 0:
            resolved_rate = supplied_rate
            rate_source: Optional[str] = "imported"
        else:
            sibling = _find_sibling_rate_in_rates(
                db,
                source=source_n,
                company_name=company_n,
                service_name=service_name,
            )
            if sibling is not None:
                resolved_rate, _sib_name = sibling
                rate_source = "inherited_from_sibling"
            else:
                resolved_rate = 0
                rate_source = "unknown_route"

        payload.append(
            {
                "source": source_n,
                "company_name": company_n,
                "service_key": service_key,            # keep it (not unique)
                "service_name": service_name,          # UNIQUE SCOPE
                "currency": (_norm_text(s.get("currency")) or "USD"),
                "active": bool(s.get("active", True)),
                "default_rate": resolved_rate,
                "default_rate_source": rate_source,
            }
        )

    if not payload:
        return

    # Use the business-identity constraint (source, company_name, service_name) so that
    # services previously imported via admin scripts (different service_key, same name)
    # don't cause IntegrityErrors and silently preserve the existing rate.
    stmt = (
        insert(ZRateService)
        .values(payload)
        .on_conflict_do_nothing(index_elements=["source", "company_name", "service_name"])
    )
    db.execute(stmt)