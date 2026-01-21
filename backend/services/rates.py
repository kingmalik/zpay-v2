# backend/services/rates.py
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional, Tuple, Union

import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from backend.db.models import ZRateService, ZRateOverride
import re

DateLike = Union[date, datetime, str]


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
    Pick newest row deterministically.
    Uses canonical matching to survive case/spacing differences in stored data.
    """
    # canonical inputs (python side)
    source_n = _norm_text(source)
    company_n = _norm_text(company_name)
    name_n = _norm_text(service_name)

    # canonicalize DB column values (sql side)
    def canon(col):
        # lower + collapse whitespace
        return sa.func.lower(sa.func.regexp_replace(col, r"\s+", " ", "g"))

    q = (
        db.query(ZRateService)
        .filter(
            canon(ZRateService.source) == source_n,
            canon(ZRateService.company_name) == company_n,
            canon(ZRateService.service_name) == name_n,
        )
    )

    if hasattr(ZRateService, "z_rate_service_id"):
        q = q.order_by(ZRateService.z_rate_service_id.desc())

    # optional debug
    # print("LOOKUP", source_n, company_n, name_n, "count", q.count())

    return q.first()


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
        # MUST match an existing unique constraint/index:
        .on_conflict_do_nothing(index_elements=["source", "company_name", "service_name"])
    )
    db.execute(stmt)