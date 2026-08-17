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


@dataclass(frozen=True)
class RideShape:
    day_part: str
    days: Optional[str]           # "M,T,W,R" — None/empty = Mon-Fri
    requires_wheelchair: bool
    pickup_city: Optional[str]
    dropoff_city: Optional[str]


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


# Real-world days strings carry more than single-letter tokens (intake maps
# Thursday -> "Th", not "R"), plus various Mon/Tue/Wed/Fri spellings. Without
# normalizing these to the canonical M/T/W/R/F letters, schedule-conflict
# checks silently miss real overlaps.
_DAY_ALIASES = {
    "MON": "M",
    "TUE": "T",
    "TUES": "T",
    "WED": "W",
    "TH": "R",
    "THU": "R",
    "THUR": "R",
    "THURS": "R",
    "FRI": "F",
}


def _day_set(days: Optional[str]) -> set[str]:
    if not days or not days.strip():
        return {"M", "T", "W", "R", "F"}
    tokens = {tok.strip().upper() for tok in days.split(",") if tok.strip()}
    return {_DAY_ALIASES.get(tok, tok) for tok in tokens}


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


def suggest_for_ride(ride: RideShape, drivers: list[CandidateDriver],
                     assigned_ride_counts: dict[int, int],
                     top_n: int = TOP_N,
                     prior_route_rides: Optional[dict[int, int]] = None) -> list[Suggestion]:
    """Ordered best-fit drivers for ONE ride — single-ride assignment mode.

    At low season volume loops are unfair: one driver gets four rides while
    others get none (locked with Malik 2026-08-17). So here fairness is a
    hard tier, not a score weight: a driver's assigned ride count sorts
    first, and proximity/route familiarity only break ties WITHIN a tier.
    Nobody is suggested for a second ride while a qualified driver has zero.

    assigned_ride_counts: person_id -> season rides already assigned (loop
    or single), season-wide so board filters never hide existing load.
    """
    ranked: list[tuple[int, Suggestion]] = []
    for d in drivers:
        if ride.requires_wheelchair and not d.wheelchair_vehicle:
            continue
        # confirmed_loops carries ALL commitments (loops + single rides) in
        # this mode; the conflict rule only reads day_part + days.
        busy_check = LoopShape(
            day_part=ride.day_part, days=ride.days,
            requires_wheelchair=ride.requires_wheelchair,
            first_pickup_city=ride.pickup_city, leg_cities=(),
        )
        if has_schedule_conflict(d, busy_check):
            continue

        count = assigned_ride_counts.get(d.person_id, 0)
        score = 0.0
        reasons = ["no rides yet" if count == 0
                   else f"{count} ride{'s' if count != 1 else ''} already"]

        if _address_mentions_city(d.home_address, ride.pickup_city):
            score += _PROXIMITY_FIRST_PICKUP
            reasons.append(f"lives near pickup ({ride.pickup_city})")
        elif _address_mentions_city(d.home_address, ride.dropoff_city):
            score += _PROXIMITY_ANY_LEG
            reasons.append(f"lives near dropoff ({ride.dropoff_city})")

        prior = (prior_route_rides or {}).get(d.person_id, 0)
        if prior > 0:
            score += _PRIOR_ROUTE
            reasons.append(f"drove this route before ({prior} ride{'s' if prior != 1 else ''})")

        if ride.requires_wheelchair:
            reasons.insert(0, "wheelchair vehicle")

        ranked.append((count, Suggestion(person_id=d.person_id, name=d.name,
                                         score=score, reasons=reasons)))

    ranked.sort(key=lambda t: (t[0], -t[1].score, t[1].name))
    return [s for _, s in ranked[:top_n]]
