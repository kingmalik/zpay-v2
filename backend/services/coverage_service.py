"""
Coverage — standing route rosters + call-out solving.

S5. Every recurring route gets a route_roster row (derived from ride
history, kept current by sync_rosters) with a primary driver and a ranked
backup list. When a driver calls out, find_coverage() proposes who can step
in — first a direct match (someone free at that time), then a ≤2-move chain
swap when nobody's simply free. Pure-Python, no live partner-API calls in the
request path; every option carries a human-readable move description for the
dispatcher to read at a glance.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from backend.services.assignment_service import (
    DriverSuggestion,
    active_driver_pool,
    familiar_rides_count,
    suggest_drivers,
)
from backend.services.driver_reliability_tier import TIER_CHRONIC, get_tier

# Rosters unseen this long are considered dead (route no longer runs).
ROSTER_STALE_DAYS = 400
# Modal-driver window for deciding who "owns" a roster identity.
PRIMARY_DRIVER_SAMPLE_SIZE = 30
# Trailing history window for a driver's typical per-weekday ride times.
TYPICAL_TIME_LOOKBACK_DAYS = 30
# Two ride times this close together count as a scheduling conflict.
TIME_CONFLICT_BUFFER_MINUTES = 45
# Time-of-day rounding bucket for "typical time" mode detection.
TIME_BUCKET_MINUTES = 15

DEFAULT_BACKUP_COUNT = 2
MAX_DIRECT_RESULTS = 5
MAX_CHAIN_RESULTS = 3

_TIER_SORT_ORDER = {"trusted": 0, "watch": 1, TIER_CHRONIC: 2}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def sync_rosters(db: Session) -> dict:
    """Derive/refresh route_roster from ride history.

    A roster identity is "live" when it has a ride with a parsed route
    identity in the trailing ROSTER_STALE_DAYS. Its primary driver is the
    modal person_id among the most recent PRIMARY_DRIVER_SAMPLE_SIZE rides on
    that identity. Rosters not seen in the window get deactivated (never
    deleted — history stays queryable).
    """
    from backend.db.models import Ride, RouteRoster

    since = _now() - timedelta(days=ROSTER_STALE_DAYS)
    rows = (
        db.query(
            Ride.source, Ride.route_school, Ride.route_direction,
            Ride.route_number, Ride.route_is_odt, Ride.service_name,
            Ride.person_id, Ride.ride_start_ts,
        )
        .filter(
            Ride.route_school.isnot(None),
            Ride.removed_at.is_(None),
            Ride.ride_start_ts >= since,
        )
        .order_by(Ride.ride_start_ts.desc())
        .all()
    )

    grouped: dict[tuple, list] = {}
    for r in rows:
        key = (r.source, r.route_school, r.route_direction, r.route_number, bool(r.route_is_odt))
        grouped.setdefault(key, []).append(r)

    created = 0
    updated = 0
    seen_keys: set[tuple] = set()
    now = _now()

    for key, ride_rows in grouped.items():
        seen_keys.add(key)
        top_n = ride_rows[:PRIMARY_DRIVER_SAMPLE_SIZE]
        counts = Counter(r.person_id for r in top_n)
        primary_person_id = counts.most_common(1)[0][0] if counts else None
        last_seen = ride_rows[0].ride_start_ts
        sample_name = ride_rows[0].service_name

        existing = (
            db.query(RouteRoster)
            .filter(
                RouteRoster.source == key[0],
                RouteRoster.route_school == key[1],
                RouteRoster.route_direction == key[2],
                RouteRoster.route_number == key[3],
                RouteRoster.route_is_odt == key[4],
            )
            .first()
        )
        if existing:
            existing.primary_person_id = primary_person_id
            existing.service_name_sample = sample_name
            existing.last_seen_ride_ts = last_seen
            existing.active = True
            existing.updated_at = now
            updated += 1
        else:
            db.add(RouteRoster(
                source=key[0], route_school=key[1], route_direction=key[2],
                route_number=key[3], route_is_odt=key[4],
                primary_person_id=primary_person_id, service_name_sample=sample_name,
                last_seen_ride_ts=last_seen, active=True,
            ))
            created += 1

    deactivated = 0
    for roster in db.query(RouteRoster).filter(RouteRoster.active.is_(True)).all():
        key = (roster.source, roster.route_school, roster.route_direction, roster.route_number, bool(roster.route_is_odt))
        if key not in seen_keys:
            roster.active = False
            roster.updated_at = now
            deactivated += 1

    db.commit()
    return {"created": created, "updated": updated, "deactivated": deactivated}


def backup_candidates(db: Session, roster_id: int, limit: int = DEFAULT_BACKUP_COUNT) -> list[DriverSuggestion]:
    """Suggest 1-2 backup drivers for a roster row — same scoring, excludes primary + existing backups."""
    from backend.db.models import RouteRoster

    roster = db.query(RouteRoster).filter(RouteRoster.roster_id == roster_id).first()
    if roster is None:
        return []

    exclude = {b.person_id for b in roster.backups}
    if roster.primary_person_id:
        exclude.add(roster.primary_person_id)

    suggestions, _pricing = suggest_drivers(
        db,
        school=roster.route_school,
        direction=roster.route_direction,
        miles=None,
        net_pay=None,
        is_odt=roster.route_is_odt,
        source=roster.source,
        limit=limit,
        exclude_person_ids=frozenset(exclude),
    )
    return suggestions


def _typical_ride_times(db: Session, person_id: int, weekday: int, before_date: datetime) -> list[tuple[int, int]]:
    """(hour, minute) of this driver's rides falling on `weekday`, trailing lookback before `before_date`."""
    from backend.db.models import Ride

    since = before_date - timedelta(days=TYPICAL_TIME_LOOKBACK_DAYS)
    rows = (
        db.query(Ride.ride_start_ts)
        .filter(
            Ride.person_id == person_id,
            Ride.removed_at.is_(None),
            Ride.ride_start_ts >= since,
            Ride.ride_start_ts < before_date,
        )
        .all()
    )
    return [(ts.hour, ts.minute) for (ts,) in rows if ts is not None and ts.weekday() == weekday]


def _roster_typical_time(db: Session, roster) -> Optional[tuple[int, int]]:
    """Modal (hour, 15-min-bucket) ride start time for a roster's recent history."""
    from backend.db.models import Ride

    rows = (
        db.query(Ride.ride_start_ts)
        .filter(
            Ride.source == roster.source,
            Ride.route_school == roster.route_school,
            Ride.route_direction == roster.route_direction,
            Ride.route_number == roster.route_number,
            Ride.route_is_odt == roster.route_is_odt,
            Ride.removed_at.is_(None),
            Ride.ride_start_ts.isnot(None),
        )
        .order_by(Ride.ride_start_ts.desc())
        .limit(PRIMARY_DRIVER_SAMPLE_SIZE)
        .all()
    )
    times = [(ts.hour, ts.minute) for (ts,) in rows if ts is not None]
    if not times:
        return None
    buckets = Counter((h, (m // TIME_BUCKET_MINUTES) * TIME_BUCKET_MINUTES) for h, m in times)
    return buckets.most_common(1)[0][0]


def _times_conflict(t1: tuple[int, int], t2: tuple[int, int]) -> bool:
    minutes1 = t1[0] * 60 + t1[1]
    minutes2 = t2[0] * 60 + t2[1]
    return abs(minutes1 - minutes2) <= TIME_CONFLICT_BUFFER_MINUTES


def _as_datetime(for_date) -> datetime:
    if isinstance(for_date, datetime):
        return for_date
    if isinstance(for_date, date):
        return datetime(for_date.year, for_date.month, for_date.day, tzinfo=timezone.utc)
    raise TypeError(f"for_date must be date or datetime, got {type(for_date)!r}")


def find_coverage(db: Session, roster_id: int, for_date) -> dict:
    """Direct + chain coverage options for a call-out on this roster's route."""
    from backend.db.models import RouteRoster

    roster = db.query(RouteRoster).filter(RouteRoster.roster_id == roster_id).first()
    if roster is None:
        return {"direct": [], "chains": [], "notes": ["roster not found"]}

    anchor = _as_datetime(for_date)
    weekday = anchor.weekday()
    target_time = _roster_typical_time(db, roster)
    notes: list[str] = []
    if target_time is None:
        notes.append("no ride-time history for this route yet — treating any ride that day as a conflict")

    people = [p for p in active_driver_pool(db) if p.person_id != roster.primary_person_id]

    direct: list[dict] = []
    busy: dict[int, tuple] = {}
    for person in people:
        times = _typical_ride_times(db, person.person_id, weekday, anchor)
        conflict = any(_times_conflict(t, target_time) for t in times) if target_time else bool(times)
        tier_result = get_tier(db, person.person_id)
        if conflict:
            busy[person.person_id] = (person, tier_result)
            continue
        reasons = ["no scheduled obligation at this time" if target_time else "no rides recorded this weekday recently"]
        familiar = familiar_rides_count(db, person.person_id, roster.route_school, roster.source)
        if familiar:
            reasons.append(f"{familiar} ride(s) at {roster.route_school} in the last year")
        direct.append({
            "person_id": person.person_id,
            "name": person.full_name,
            "tier": tier_result.tier,
            "reasons": reasons,
        })

    direct.sort(key=lambda d: _TIER_SORT_ORDER.get(d["tier"], 1))
    direct = direct[:MAX_DIRECT_RESULTS]

    chains: list[dict] = []
    if not direct:
        chains = _build_chain_options(db, roster, busy, people, weekday, anchor)
        if not chains:
            notes.append("no direct or chain coverage found — manual dispatch call needed")

    return {"direct": direct, "chains": chains, "notes": notes}


def _build_chain_options(db, roster, busy: dict, people: list, weekday: int, anchor: datetime) -> list[dict]:
    """≤2-move swaps: A (busy, not chronic) covers the target; B (free) backfills A's usual run."""
    from backend.db.models import RouteRoster

    chains: list[dict] = []
    already_displaced: set[int] = set()

    for person_id, (person, tier_result) in busy.items():
        if len(chains) >= MAX_CHAIN_RESULTS:
            break
        if tier_result.tier == TIER_CHRONIC:
            continue  # never put a chronic driver in the time-critical seat

        own_rosters = (
            db.query(RouteRoster)
            .filter(RouteRoster.primary_person_id == person_id, RouteRoster.active.is_(True))
            .all()
        )
        for other_roster in own_rosters:
            if other_roster.roster_id == roster.roster_id:
                continue
            other_time = _roster_typical_time(db, other_roster)
            if other_time is None:
                continue

            backfill = _find_free_backfill(db, other_roster, other_time, people, weekday, anchor, exclude={person_id, roster.primary_person_id} | already_displaced)
            if backfill is None:
                continue

            already_displaced.add(backfill.person_id)
            chains.append({
                "moves": [
                    {
                        "person_id": person.person_id,
                        "name": person.full_name,
                        "action": f"covers {roster.route_school} {roster.route_direction} {roster.route_number}",
                    },
                    {
                        "person_id": backfill.person_id,
                        "name": backfill.full_name,
                        "action": (
                            f"covers {other_roster.route_school} {other_roster.route_direction} "
                            f"{other_roster.route_number} (usually {person.full_name}'s)"
                        ),
                    },
                ],
                "description": (
                    f"{person.full_name} moves to cover the open route; {backfill.full_name} backfills "
                    f"{person.full_name}'s usual {other_roster.route_school} {other_roster.route_direction} "
                    f"{other_roster.route_number} run"
                ),
            })
            break  # one backfill per A is enough

    return chains


def _find_free_backfill(db, other_roster, other_time, people, weekday, anchor, exclude: set[int]):
    """First candidate with no conflicting obligation at `other_time`. Never re-displaces someone already moved."""
    for candidate in people:
        if candidate.person_id in exclude:
            continue
        cand_times = _typical_ride_times(db, candidate.person_id, weekday, anchor)
        if any(_times_conflict(t, other_time) for t in cand_times):
            continue
        return candidate
    return None
