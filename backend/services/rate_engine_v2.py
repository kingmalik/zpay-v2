"""
Pricing Engine v2 — two-tier route-identity resolution.

Semantics (Malik's ground truth, MASTER-PLAN-2026-07 §S2):

  TIER 1 — in-season identity. FA route numbers are per-student pairings;
  in-season name churn (variants, day/wheelchair markers, ER/LS blocks, ODT)
  never changes the ride. Same (school, direction, number) = same student =
  same rate. This REPLACES v1's ±neighbor guessing, which matched different
  students.

  TIER 2 — season-boundary price inheritance. New season renumbers routes,
  but PRICE FOLLOWS DISTANCE. No Tier-1 match → look at the same school +
  direction, find an established route whose typical miles are within ±1 of
  this ride's miles, and inherit the PRICE only (never the pairing). Always
  with evidence.

  Anything else → unresolved. v2 refuses rather than guesses: a route left
  for rate review costs minutes; a wrong rate costs money and trust.

Mode flag (RATE_ENGINE_V2): "0" = off (default) · "shadow" = compute + record
next to v1, never affects pay · "1" = v2 prices for real.
"""
from __future__ import annotations

import os
import re
import statistics
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Mapping, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.services.route_identity import RouteIdentity, parse_route_identity

MODE_OFF = "0"
MODE_SHADOW = "shadow"
MODE_LIVE = "1"

TIER_IDENTITY = "tier1_identity"
TIER_DISTANCE = "tier2_distance"
TIER_NONE = "none"

_MILES_TOLERANCE = float(os.environ.get("RATE_V2_MILES_TOLERANCE", "1.0"))
# Tier-1 sanity guards (added after the 2026-07-09 replay):
#   drift — a churn variant whose miles moved is a physically changed route
#           (Cedar Heights OB 16 (W)_A went 31mi→11mi and $62→$40).
#   evidence — non-exact matches built on a couple of rides are how the one
#           irreducible replay wrong survived (Cedarhome _A @ 2 rides).
_TIER1_MILES_DRIFT = float(os.environ.get("RATE_V2_TIER1_MILES_DRIFT", "2.0"))
_MIN_EVIDENCE_RIDES = int(os.environ.get("RATE_V2_MIN_EVIDENCE_RIDES", "3"))


def v2_mode() -> str:
    raw = os.environ.get("RATE_ENGINE_V2", MODE_OFF).lower().strip()
    return raw if raw in (MODE_OFF, MODE_SHADOW, MODE_LIVE) else MODE_OFF


@dataclass(frozen=True)
class ServiceProfile:
    """One rate-bearing service row + its ride history stats."""
    service_name: str
    identity: RouteIdentity
    rate: Decimal
    z_rate_service_id: Optional[int]
    ride_count: int
    median_miles: Optional[float]


@dataclass(frozen=True)
class V2Resolution:
    rate: Decimal
    tier: str
    evidence: str
    z_rate_service_id: Optional[int] = None
    matched_service_name: Optional[str] = None

    @property
    def resolved(self) -> bool:
        return self.tier != TIER_NONE and self.rate > 0


def load_pricing_context(
    db: Session,
    *,
    source: str = "acumen",
    ref_date=None,
    exclude_service_names: frozenset[str] = frozenset(),
) -> list[ServiceProfile]:
    """Build the candidate pool once (per batch / per replay run).

    A candidate is an active rate service with a real (>0) effective rate and
    a parseable route identity. Ride stats come from non-removed rides.

    Exactly three queries regardless of pool size — effective rates
    (date-ranged overrides included) are resolved in bulk, not per service.
    """
    from datetime import date as _date

    from backend.db.models import Ride, ZRateOverride, ZRateService

    ref = ref_date or _date.today()

    stats_rows = (
        db.query(
            Ride.service_name,
            func.count().label("n"),
            func.percentile_cont(0.5).within_group(Ride.miles).label("median_miles"),
        )
        .filter(
            Ride.source == source,
            Ride.removed_at.is_(None),
            Ride.miles > 0,
        )
        .group_by(Ride.service_name)
        .all()
    )
    ride_stats = {
        r.service_name: (int(r.n), float(r.median_miles) if r.median_miles is not None else None)
        for r in stats_rows
    }

    services = (
        db.query(ZRateService)
        .filter(
            func.lower(func.coalesce(ZRateService.source, "")) == source.lower(),
            ZRateService.active.is_(True),
        )
        .all()
    )

    # Bulk override resolution: newest active override containing ref wins,
    # mirroring resolve_rate_for_ride's precedence.
    svc_ids = [s.z_rate_service_id for s in services if s.z_rate_service_id is not None]
    override_rate_by_svc: dict[int, Decimal] = {}
    if svc_ids:
        ov_rows = (
            db.query(ZRateOverride)
            .filter(
                ZRateOverride.z_rate_service_id.in_(svc_ids),
                ZRateOverride.active.is_(True),
                ZRateOverride.effective_during.op("@>")(ref),
            )
            .order_by(
                ZRateOverride.z_rate_service_id,
                func.lower(ZRateOverride.effective_during).desc(),
            )
            .all()
        )
        for ov in ov_rows:
            if ov.z_rate_service_id not in override_rate_by_svc and ov.override_rate is not None:
                override_rate_by_svc[ov.z_rate_service_id] = Decimal(str(ov.override_rate))

    profiles: list[ServiceProfile] = []
    excluded = {n.lower() for n in exclude_service_names}
    for svc in services:
        name = (svc.service_name or "").strip()
        if not name or name.lower() in excluded:
            continue
        identity = parse_route_identity(name)
        if identity is None:
            continue
        rate = override_rate_by_svc.get(svc.z_rate_service_id)
        if rate is None and svc.default_rate is not None:
            rate = Decimal(str(svc.default_rate))
        if rate is None or rate <= 0:
            continue
        n, median_miles = ride_stats.get(name, (0, None))
        profiles.append(ServiceProfile(
            service_name=name,
            identity=identity,
            rate=rate,
            z_rate_service_id=svc.z_rate_service_id,
            ride_count=n,
            median_miles=median_miles,
        ))
    return profiles


def resolve_rate_v2(
    service_name: str,
    miles: Optional[float],
    candidates: Iterable[ServiceProfile],
) -> V2Resolution:
    """Resolve one ride against a prebuilt candidate pool. Pure — no DB."""
    identity = parse_route_identity(service_name)
    if identity is None:
        return V2Resolution(
            rate=Decimal("0"), tier=TIER_NONE,
            evidence=f"'{service_name}' is not a parseable route name",
        )

    # Self-name rows stay in the pool — an exact-name match IS the strongest
    # Tier-1 case; replay excludes the target via load_pricing_context.
    pool = list(candidates)

    # ── TIER 1: same student pairing ─────────────────────────────────────────
    # Replay against prod ground truth (2026-07-09) taught two hard lessons:
    #   1. ODT runs are their own pricing class — "Alderwood MS OB ODT 03"
    #      is NOT priced like "Alderwood MS OB 03". ODT only matches ODT.
    #   2. Day-marker variants ((W)/(F)) are SOMETIMES repriced (Wednesday
    #      early-release economics). A family whose variants disagree on
    #      price is a human call, not a guess.
    # Rule: family = same (school, direction, number, odt-class). Exact name
    # match always wins. Otherwise auto-price ONLY if the family's rates all
    # agree; a split family refuses to rate review.
    #   3. Day-marker mismatches ((W) vs unmarked) are exactly where the
    #      remaining replay wrongs lived — the repriced variant is invisible
    #      precisely when it's the new arrival. Day-marker sets must match;
    #      equipment markers (HCV/[Wt]) proved price-neutral and may cross.
    tier1 = [
        c for c in pool
        if c.identity.key == identity.key
        and c.identity.is_odt == identity.is_odt
        and c.identity.day_markers == identity.day_markers
    ]
    if tier1:
        exact = [c for c in tier1 if c.service_name.lower() == service_name.lower()]
        rates = {c.rate for c in tier1}
        if exact:
            best = exact[0]
        elif len(rates) == 1:
            best = max(tier1, key=lambda c: c.ride_count)
            if best.ride_count < _MIN_EVIDENCE_RIDES:
                return V2Resolution(
                    rate=Decimal("0"), tier=TIER_NONE,
                    evidence=(
                        f"same pairing as '{best.service_name}' but only "
                        f"{best.ride_count} ride(s) of evidence — human call"
                    ),
                )
            if (
                miles and miles > 0
                and best.median_miles is not None
                and abs(best.median_miles - miles) > _TIER1_MILES_DRIFT
            ):
                return V2Resolution(
                    rate=Decimal("0"), tier=TIER_NONE,
                    evidence=(
                        f"same pairing as '{best.service_name}' but distance moved "
                        f"{best.median_miles:.0f}mi → {miles:g}mi — price follows "
                        f"distance, human call"
                    ),
                )
        else:
            opts = ", ".join(
                f"'{c.service_name}' @ ${c.rate}"
                for c in sorted(tier1, key=lambda c: -c.ride_count)[:4]
            )
            return V2Resolution(
                rate=Decimal("0"), tier=TIER_NONE,
                evidence=(
                    f"pairing family {identity.school} {identity.direction} "
                    f"{identity.number} is split-priced — human call: {opts}"
                ),
            )
        return V2Resolution(
            rate=best.rate,
            tier=TIER_IDENTITY,
            evidence=(
                f"same pairing: '{best.service_name}' @ ${best.rate}"
                f" × {best.ride_count} rides"
            ),
            z_rate_service_id=best.z_rate_service_id,
            matched_service_name=best.service_name,
        )

    # ── TIER 2: price follows distance within school+direction ──────────────
    if not miles or miles <= 0:
        return V2Resolution(
            rate=Decimal("0"), tier=TIER_NONE,
            evidence="no Tier-1 identity match and no miles on ride — cannot distance-match",
        )

    scope = [
        c for c in pool
        if c.identity.school_direction_key == identity.school_direction_key
        and c.identity.is_odt == identity.is_odt   # ODT inherits only from ODT
        and c.identity.day_markers == identity.day_markers  # (W) inherits only from (W)
        and c.median_miles is not None
        and c.ride_count >= _MIN_EVIDENCE_RIDES
        and abs(c.median_miles - miles) <= _MILES_TOLERANCE
    ]
    if not scope:
        return V2Resolution(
            rate=Decimal("0"), tier=TIER_NONE,
            evidence=(
                f"no established {identity.school} {identity.direction} route "
                f"within ±{_MILES_TOLERANCE:g}mi of {miles:g}mi"
            ),
        )

    scope.sort(key=lambda c: (abs(c.median_miles - miles), -c.ride_count))
    best = scope[0]
    nearest_delta = abs(best.median_miles - miles)
    ties = [c for c in scope if abs(abs(c.median_miles - miles) - nearest_delta) < 0.25]
    if len({c.rate for c in ties}) > 1:
        opts = ", ".join(
            f"'{c.service_name}' {c.median_miles:.0f}mi @ ${c.rate}" for c in ties[:4]
        )
        return V2Resolution(
            rate=Decimal("0"), tier=TIER_NONE,
            evidence=f"ambiguous distance match at {miles:g}mi — refusing to guess between: {opts}",
        )

    return V2Resolution(
        rate=best.rate,
        tier=TIER_DISTANCE,
        evidence=(
            f"new pairing #{identity.number}, {miles:g}mi — inherits price of "
            f"'{best.service_name}', {best.median_miles:.0f}mi @ ${best.rate}"
            f" × {best.ride_count} rides (price follows distance)"
        ),
        z_rate_service_id=best.z_rate_service_id,
        matched_service_name=best.service_name,
    )
