"""
Loop Builder — S10 Season Assignment Board.

Pure chaining engine: takes season rides (legs), proposes standing driver
loops per (day-part, day-signature). No I/O, no ORM — callers pass plain
`Leg` records and get `ProposedLoop` records back, so the whole algorithm
is unit-testable and the API layer owns persistence.

Business rules (docs/SEASON-BOARD-PLAN.md):
  * IB legs are morning (AM), OB legs are afternoon (PM), ODT legs mid-day (MID).
  * Same (source, school, number, is_odt) = same student; the AM loop that
    carries a student's IB leg should pair with the PM loop carrying their OB
    leg — surfaced via companion matching, same driver both by default.
  * Leg B chains after leg A iff A.dropoff_time + drive(A.dropoff_city,
    B.pickup_city) + BUFFER fits before B.pickup_time, idle slack stays under
    MAX_SLACK, the chain stays under MAX_LEGS, and requirement flags union
    into a profile one driver can satisfy.
  * v1 chains only within identical day signatures (a M/F-only ride never
    chains into a Mon–Fri loop) — standing loops must run the same way every
    day they exist.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

# Tunables — callers may override per invocation.
DEFAULT_BUFFER_MIN = 10.0     # load/unload + breathing room between legs
DEFAULT_MAX_SLACK_MIN = 75.0  # never chain across a longer idle gap
DEFAULT_MAX_LEGS = 4          # loop length cap per day-part

REQUIREMENT_FLAGS = ("wheelchair", "car_seat", "booster", "harness", "monitor")

ALL_WEEKDAYS = ("M", "T", "W", "R", "F")


@dataclass(frozen=True)
class Leg:
    """One season ride, flattened to what chaining needs."""
    ride_id: int
    source: str
    school: str            # route_school (normalized-ish; compared lowercased)
    direction: str         # "IB" | "OB"
    number: str
    is_odt: bool = False
    days: Optional[str] = None          # "M,W,F" subset; None = Mon–Fri
    pickup_city: Optional[str] = None
    dropoff_city: Optional[str] = None
    pickup_time: Optional[str] = None   # "HH:MM" 24h or "7:45 AM"
    dropoff_time: Optional[str] = None
    requires: dict = field(default_factory=dict)


@dataclass
class ProposedLoop:
    day_part: str                 # "AM" | "PM" | "MID"
    days: tuple[str, ...]         # e.g. ("M","T","W","R","F")
    ride_ids: list[int]           # ordered legs
    slack_minutes: list[float]    # idle gap before legs[1..]
    requires_profile: dict        # union of true flags across legs
    label: str
    student_keys: frozenset = frozenset()
    companion_index: Optional[int] = None  # index of paired PM loop (set on AM loops)


@dataclass
class BuildResult:
    loops: list[ProposedLoop]
    ungroupable: list[tuple[int, str]]   # (ride_id, reason)


_TIME_12H = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*([AaPp])\.?[Mm]?\.?\s*$")
_TIME_24H = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")


def parse_time_minutes(value: Optional[str]) -> Optional[float]:
    """'HH:MM' (24h) or 'H:MM AM/PM' -> minutes since midnight, else None."""
    if not value:
        return None
    m = _TIME_12H.match(value)
    if m:
        hh, mm, ap = int(m.group(1)), int(m.group(2)), m.group(3).lower()
        if not (1 <= hh <= 12 and 0 <= mm <= 59):
            return None
        if ap == "p" and hh != 12:
            hh += 12
        if ap == "a" and hh == 12:
            hh = 0
        return float(hh * 60 + mm)
    m = _TIME_24H.match(value)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            return None
        return float(hh * 60 + mm)
    return None


def default_drive_minutes(city_a: Optional[str], city_b: Optional[str]) -> float:
    """Heuristic city-to-city estimate; the API layer may inject a real one."""
    if not city_a or not city_b:
        return 20.0
    if city_a.strip().lower() == city_b.strip().lower():
        return 10.0
    return 25.0


def student_key(leg: Leg) -> tuple:
    return (leg.source, leg.school.strip().lower(), leg.number, leg.is_odt)


def day_part(leg: Leg) -> str:
    if leg.is_odt:
        return "MID"
    return "AM" if leg.direction == "IB" else "PM"


# Thursday drifts across sources: the intake parser emits "Th", sheets may
# say "Thu"/"Thurs" — the engine's alphabet uses "R". Normalize here so no
# source silently loses Thursdays from a day signature.
_DAY_ALIASES = {"TH": "R", "THU": "R", "THURS": "R", "R": "R",
                "M": "M", "MON": "M", "T": "T", "TU": "T", "TUE": "T", "TUES": "T",
                "W": "W", "WED": "W", "F": "F", "FRI": "F"}


def day_signature(leg: Leg) -> tuple[str, ...]:
    if not leg.days or not leg.days.strip():
        return ALL_WEEKDAYS
    seen = []
    for tok in leg.days.replace(" ", "").upper().split(","):
        canonical = _DAY_ALIASES.get(tok)
        if canonical and canonical not in seen:
            seen.append(canonical)
    return tuple(d for d in ALL_WEEKDAYS if d in seen) or ALL_WEEKDAYS


def requires_profile(legs: list[Leg]) -> dict:
    profile: dict = {}
    for leg in legs:
        for flag in REQUIREMENT_FLAGS:
            if leg.requires.get(flag):
                profile[flag] = True
    return profile


def _corridor_label(legs: list[Leg], part: str, ordinal: int) -> str:
    cities: list[str] = []
    for leg in legs:
        for c in (leg.pickup_city, leg.dropoff_city):
            if c and c not in cities:
                cities.append(c)
    where = "↔".join(cities[:2]) if cities else "unmapped"
    return f"{part} {ordinal} — {where} ({len(legs)} ride{'s' if len(legs) != 1 else ''})"


def build_loops(
    legs: list[Leg],
    drive_minutes: Callable[[Optional[str], Optional[str]], float] = default_drive_minutes,
    buffer_min: float = DEFAULT_BUFFER_MIN,
    max_slack_min: float = DEFAULT_MAX_SLACK_MIN,
    max_legs: int = DEFAULT_MAX_LEGS,
) -> BuildResult:
    """Chain legs into proposed standing loops.

    Greedy, deterministic: legs sorted by pickup time (ride_id tiebreak);
    each leg extends the open chain with the tightest feasible slack, else
    opens a new chain. Companion matching links AM loops to the PM loop with
    the largest shared-student overlap.
    """
    usable: list[Leg] = []
    ungroupable: list[tuple[int, str]] = []
    for leg in legs:
        reasons = []
        if parse_time_minutes(leg.pickup_time) is None:
            reasons.append("missing/unparseable pickup time")
        if parse_time_minutes(leg.dropoff_time) is None:
            reasons.append("missing/unparseable dropoff time")
        if not leg.pickup_city and not leg.dropoff_city:
            reasons.append("no pickup or dropoff city")
        if leg.direction not in ("IB", "OB"):
            reasons.append(f"unknown direction {leg.direction!r}")
        if reasons:
            ungroupable.append((leg.ride_id, "; ".join(reasons)))
        else:
            usable.append(leg)

    # Partition: (day_part, day_signature) -> legs
    buckets: dict[tuple[str, tuple[str, ...]], list[Leg]] = {}
    for leg in usable:
        buckets.setdefault((day_part(leg), day_signature(leg)), []).append(leg)

    loops: list[ProposedLoop] = []
    ordinals: dict[str, int] = {}

    for (part, days), bucket in sorted(buckets.items()):
        bucket.sort(key=lambda l: (parse_time_minutes(l.pickup_time), l.ride_id))
        chains: list[list[Leg]] = []
        for leg in bucket:
            pickup = parse_time_minutes(leg.pickup_time)
            best: Optional[tuple[float, list[Leg]]] = None  # (slack, chain)
            for chain in chains:
                if len(chain) >= max_legs:
                    continue
                last = chain[-1]
                drop = parse_time_minutes(last.dropoff_time)
                travel = drive_minutes(last.dropoff_city, leg.pickup_city)
                earliest = drop + travel + buffer_min
                slack = pickup - earliest
                if slack < 0 or slack > max_slack_min:
                    continue
                if best is None or slack < best[0]:
                    best = (slack, chain)
            if best is not None:
                best[1].append(leg)
            else:
                chains.append([leg])

        for chain in chains:
            ordinals[part] = ordinals.get(part, 0) + 1
            slacks = []
            for prev, cur in zip(chain, chain[1:]):
                drop = parse_time_minutes(prev.dropoff_time)
                pickup = parse_time_minutes(cur.pickup_time)
                travel = drive_minutes(prev.dropoff_city, cur.pickup_city)
                slacks.append(round(pickup - (drop + travel + buffer_min), 1))
            loops.append(ProposedLoop(
                day_part=part,
                days=days,
                ride_ids=[l.ride_id for l in chain],
                slack_minutes=slacks,
                requires_profile=requires_profile(chain),
                label=_corridor_label(chain, part, ordinals[part]),
                student_keys=frozenset(student_key(l) for l in chain),
            ))

    _match_companions(loops)
    return BuildResult(loops=loops, ungroupable=ungroupable)


def _match_companions(loops: list[ProposedLoop]) -> None:
    """Pair each AM loop with the PM loop sharing the most students.

    Greedy on overlap size (desc), deterministic tiebreak on loop order.
    Same driver should run both halves of a student's day — the UI uses this
    to suggest the PM loop when an AM loop gets assigned.
    """
    am = [(i, lp) for i, lp in enumerate(loops) if lp.day_part == "AM"]
    pm = [(i, lp) for i, lp in enumerate(loops) if lp.day_part == "PM"]
    candidates = []
    for ai, a in am:
        for pi, p in pm:
            overlap = len(a.student_keys & p.student_keys)
            if overlap > 0:
                candidates.append((-overlap, ai, pi))
    candidates.sort()
    used_am: set[int] = set()
    used_pm: set[int] = set()
    for neg_overlap, ai, pi in candidates:
        if ai in used_am or pi in used_pm:
            continue
        loops[ai].companion_index = pi
        loops[pi].companion_index = ai
        used_am.add(ai)
        used_pm.add(pi)
