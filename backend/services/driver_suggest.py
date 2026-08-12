"""
backend/services/driver_suggest.py
===================================
Pure ranking engine: which drivers fit a proposed season loop best.

Mirrors loop_builder.py's style — no DB, no framework imports. The API
layer (season_board.list_loops) flattens rows into the dataclasses below
and gets back an ordered list of suggestions with human-readable reasons.

Ranking rules (locked with Malik 2026-08-11):
- Wheelchair is the ONLY hard capability gate (feedback: equipment flags
  are info-only; monitors come from FirstAlt).
- A driver already on a confirmed loop in the same day-part with an
  overlapping day is physically unavailable -> excluded.
- Score: home-city proximity to the loop's first pickup (strongest),
  proximity to any leg city, then fewest confirmed loops (load balance).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

TOP_N = 3

_PROXIMITY_FIRST_PICKUP = 3.0
_PROXIMITY_ANY_LEG = 1.5
# Drove this loop's route(s) in a prior season. Deliberately below
# first-pickup proximity: efficiency outranks familiarity, familiarity breaks ties.
_PRIOR_ROUTE = 2.0


@dataclass(frozen=True)
class CandidateDriver:
    person_id: int
    name: str
    home_address: Optional[str]
    wheelchair_vehicle: bool
    # (day_part, days-string) for every loop already confirmed on this driver
    confirmed_loops: tuple[tuple[str, Optional[str]], ...] = ()


@dataclass(frozen=True)
class LoopShape:
    day_part: str
    days: Optional[str]           # "M,T,W,R" — None/empty = Mon-Fri
    requires_wheelchair: bool
    first_pickup_city: Optional[str]
    leg_cities: tuple[str, ...]   # every pickup/dropoff city on the loop


@dataclass
class Suggestion:
    person_id: int
    name: str
    score: float
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "person_id": self.person_id,
            "name": self.name,
            "score": round(self.score, 1),
            "reasons": self.reasons,
        }


def _day_set(days: Optional[str]) -> set[str]:
    if not days or not days.strip():
        return {"M", "T", "W", "R", "F"}
    return {tok.strip().upper() for tok in days.split(",") if tok.strip()}


def _address_mentions_city(address: Optional[str], city: Optional[str]) -> bool:
    if not address or not city:
        return False
    return city.strip().lower() in address.lower()


def has_schedule_conflict(driver: CandidateDriver, loop: LoopShape) -> bool:
    loop_days = _day_set(loop.days)
    for part, days in driver.confirmed_loops:
        if part == loop.day_part and loop_days & _day_set(days):
            return True
    return False


def suggest_drivers(loop: LoopShape, drivers: list[CandidateDriver],
                    top_n: int = TOP_N,
                    prior_route_rides: Optional[dict[int, int]] = None) -> list[Suggestion]:
    """Ordered best-fit drivers for one proposed loop.

    prior_route_rides: person_id -> count of historical payroll rides this
    driver ran on the same route identity (school + number) as this loop.
    """
    ranked: list[Suggestion] = []
    for d in drivers:
        if loop.requires_wheelchair and not d.wheelchair_vehicle:
            continue
        if has_schedule_conflict(d, loop):
            continue

        score = 0.0
        reasons: list[str] = []

        if _address_mentions_city(d.home_address, loop.first_pickup_city):
            score += _PROXIMITY_FIRST_PICKUP
            reasons.append(f"lives near first pickup ({loop.first_pickup_city})")
        elif any(_address_mentions_city(d.home_address, c) for c in loop.leg_cities):
            city = next(c for c in loop.leg_cities if _address_mentions_city(d.home_address, c))
            score += _PROXIMITY_ANY_LEG
            reasons.append(f"lives near route ({city})")

        prior = (prior_route_rides or {}).get(d.person_id, 0)
        if prior > 0:
            score += _PRIOR_ROUTE
            reasons.append(f"drove this route before ({prior} ride{'s' if prior != 1 else ''})")

        load = len(d.confirmed_loops)
        score += max(0.0, 1.0 - 0.25 * load)
        if load == 0:
            reasons.append("no loops assigned yet")
        else:
            reasons.append(f"{load} loop{'s' if load != 1 else ''} already")

        if loop.requires_wheelchair:
            reasons.insert(0, "wheelchair vehicle")

        ranked.append(Suggestion(person_id=d.person_id, name=d.name,
                                 score=score, reasons=reasons))

    ranked.sort(key=lambda s: (-s.score, s.name))
    return ranked[:top_n]
