"""
Assignment Helper — rank drivers for a new (or re-priced) ride.

S5. Every new-ride email from Brandon needs a driver suggestion within
minutes. suggest_drivers() ranks the active driver pool by transparent,
named-weight signals (school familiarity, reliability tier, recent load,
home-area tie-break) and returns human-readable reasons for each candidate —
this is a dispatcher aid, never an auto-assign.

Pricing is resolved separately via rate_engine_v2's Tier-2 (distance) path,
since a brand-new ride has no existing service_name to Tier-1 match against.

WHEELCHAIR RULE: wheelchair-equipped rides never get an auto-suggested rate.
predicted_rate is always None; the raw partner net_pay is surfaced as
pass_through_suggestion and manual_review is forced true.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.services.driver_reliability_tier import TIER_CHRONIC, TIER_TRUSTED, get_tier
from backend.services.rate_engine_v2 import V2Resolution, load_pricing_context, resolve_rate_v2

# ── Scoring weights (named + tunable, never magic numbers inline) ───────────
FAMILIARITY_WEIGHT = 4.0
FAMILIARITY_LOOKBACK_DAYS = 365
FAMILIARITY_CAP_RIDES = 10          # rides beyond this add no more score

TIER_BONUS = {
    TIER_TRUSTED: 15.0,
    "watch": 0.0,
    TIER_CHRONIC: -25.0,
}

LOAD_LOOKBACK_DAYS = 14
LOAD_PENALTY_PER_RIDE = 2.0
LOAD_PENALTY_CAP = 20.0
LOW_LOAD_THRESHOLD = 3               # at/under this = "light load" in reasons

HOME_AREA_TIE_BREAK_BONUS = 5.0

DEFAULT_SOURCE = "acumen"            # Brandon/FirstStudent = FA/Acumen

_MARGIN_WARN_FLOOR = float(os.environ.get("ASSIGN_MARGIN_WARN_FLOOR", "8"))


@dataclass(frozen=True)
class DriverSuggestion:
    person_id: int
    name: str
    tier: str
    score: float
    reasons: tuple[str, ...]
    familiar_rides: int
    load_recent: int
    home_area: Optional[str]


@dataclass(frozen=True)
class PricingResult:
    predicted_rate: Optional[float]
    margin: Optional[float]
    margin_pct: Optional[float]
    unprofitable: bool
    evidence: str
    manual_review: bool
    pass_through_suggestion: Optional[float]


def _synthetic_service_name(school: str, direction: str, is_odt: bool) -> str:
    """Build a Tier-2-matchable fake route name for a brand-new ride.

    Tier 1 can never match (no existing pairing yet); Tier 2 only needs
    school_direction_key + odt-class + empty day-markers, so the fake
    number is a placeholder that will never coincide with a real pairing's
    exact name (avoiding an accidental Tier-1 "exact name" hit).
    """
    odt_part = "ODT " if is_odt else ""
    return f"{school} {direction} {odt_part}99"


def predict_pricing(
    db: Session,
    *,
    school: Optional[str],
    direction: Optional[str],
    miles: Optional[float],
    net_pay: Optional[float],
    is_odt: bool = False,
    wheelchair: bool = False,
    source: str = DEFAULT_SOURCE,
) -> PricingResult:
    """Predict driver pay + margin for a new ride. Never auto-rates wheelchair rides."""
    if wheelchair:
        return PricingResult(
            predicted_rate=None,
            margin=None,
            margin_pct=None,
            unprofitable=False,
            evidence="wheelchair-equipped ride — rate needs manual review, never auto-suggested",
            manual_review=True,
            pass_through_suggestion=net_pay,
        )

    if not school or not direction:
        return PricingResult(
            predicted_rate=None, margin=None, margin_pct=None, unprofitable=False,
            evidence="school/direction not confirmed yet — cannot predict a rate",
            manual_review=False, pass_through_suggestion=None,
        )

    candidates = load_pricing_context(db, source=source)
    synthetic_name = _synthetic_service_name(school, direction, is_odt)
    resolution: V2Resolution = resolve_rate_v2(synthetic_name, miles, candidates)

    if not resolution.resolved:
        return PricingResult(
            predicted_rate=None, margin=None, margin_pct=None, unprofitable=False,
            evidence=resolution.evidence, manual_review=False, pass_through_suggestion=None,
        )

    predicted_rate = float(resolution.rate)
    margin: Optional[float] = None
    margin_pct: Optional[float] = None
    unprofitable = False
    if net_pay is not None:
        margin = round(net_pay - predicted_rate, 2)
        margin_pct = round((margin / net_pay) * 100, 1) if net_pay else None
        unprofitable = margin < _MARGIN_WARN_FLOOR

    return PricingResult(
        predicted_rate=predicted_rate,
        margin=margin,
        margin_pct=margin_pct,
        unprofitable=unprofitable,
        evidence=resolution.evidence,
        manual_review=False,
        pass_through_suggestion=None,
    )


def active_driver_pool(db: Session):
    from backend.db.models import Person

    return (
        db.query(Person)
        .filter(Person.active.is_(True))
        .filter(Person.status == "active")
        .all()
    )


def familiar_rides_count(db: Session, person_id: int, school: str, source: str) -> int:
    from backend.db.models import Ride

    since = datetime.now(timezone.utc) - timedelta(days=FAMILIARITY_LOOKBACK_DAYS)
    return (
        db.query(func.count(Ride.ride_id))
        .filter(
            Ride.person_id == person_id,
            Ride.source == source,
            Ride.removed_at.is_(None),
            func.lower(Ride.route_school) == school.lower(),
            Ride.ride_start_ts >= since,
        )
        .scalar()
    ) or 0


def _recent_load_count(db: Session, person_id: int, for_date: Optional[datetime] = None) -> int:
    from backend.db.models import Ride

    anchor = for_date or datetime.now(timezone.utc)
    since = anchor - timedelta(days=LOAD_LOOKBACK_DAYS)
    return (
        db.query(func.count(Ride.ride_id))
        .filter(
            Ride.person_id == person_id,
            Ride.removed_at.is_(None),
            Ride.ride_start_ts >= since,
            Ride.ride_start_ts <= anchor,
        )
        .scalar()
    ) or 0


def _score_candidate(
    familiar_rides: int, tier: str, load_recent: int, home_area: Optional[str]
) -> tuple[float, list[str]]:
    """Pure scoring — every point is explainable via reasons[]."""
    reasons: list[str] = []
    score = 0.0

    familiarity_score = min(familiar_rides, FAMILIARITY_CAP_RIDES) * FAMILIARITY_WEIGHT
    score += familiarity_score
    if familiar_rides > 0:
        reasons.append(f"{familiar_rides} ride(s) at this school in the last year")
    else:
        reasons.append("no recent history at this school")

    tier_bonus = TIER_BONUS.get(tier, 0.0)
    score += tier_bonus
    reasons.append(f"{tier} tier")

    load_penalty = min(load_recent * LOAD_PENALTY_PER_RIDE, LOAD_PENALTY_CAP)
    score -= load_penalty
    if load_recent <= LOW_LOAD_THRESHOLD:
        reasons.append(f"light load ({load_recent} rides in last {LOAD_LOOKBACK_DAYS}d)")
    else:
        reasons.append(f"busy ({load_recent} rides in last {LOAD_LOOKBACK_DAYS}d)")

    if home_area:
        score += HOME_AREA_TIE_BREAK_BONUS
        reasons.append(f"home area on file ({home_area})")

    return score, reasons


def suggest_drivers(
    db: Session,
    *,
    school: Optional[str],
    direction: Optional[str],
    miles: Optional[float] = None,
    net_pay: Optional[float] = None,
    for_date: Optional[datetime] = None,
    limit: int = 10,
    wheelchair: bool = False,
    is_odt: bool = False,
    source: str = DEFAULT_SOURCE,
    exclude_person_ids: frozenset[int] = frozenset(),
) -> tuple[list[DriverSuggestion], PricingResult]:
    """Rank the active driver pool for a new ride. Returns (suggestions, pricing)."""
    pricing = predict_pricing(
        db, school=school, direction=direction, miles=miles, net_pay=net_pay,
        is_odt=is_odt, wheelchair=wheelchair, source=source,
    )

    if not school:
        return [], pricing

    people = [p for p in active_driver_pool(db) if p.person_id not in exclude_person_ids]

    scored: list[DriverSuggestion] = []
    for person in people:
        familiar_rides = familiar_rides_count(db, person.person_id, school, source)
        load_recent = _recent_load_count(db, person.person_id, for_date)
        tier_result = get_tier(db, person.person_id)
        score, reasons = _score_candidate(
            familiar_rides, tier_result.tier, load_recent, person.home_area
        )
        scored.append(DriverSuggestion(
            person_id=person.person_id,
            name=person.full_name,
            tier=tier_result.tier,
            score=round(score, 2),
            reasons=tuple(reasons),
            familiar_rides=familiar_rides,
            load_recent=load_recent,
            home_area=person.home_area,
        ))

    scored.sort(key=lambda s: s.score, reverse=True)
    return scored[:limit], pricing
