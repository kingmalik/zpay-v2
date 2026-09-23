"""Merge duplicate z_rate_service rows down to one row per (source, service_name).

Background
----------
`z_rate_service` carries a unique index on (source, company_name, service_name),
but `company_name` is not a reliable key — the same route gets imported under
several spellings over time ("FirstAlt" / "Acumen International" / "Acumen",
"EverDriven" / "everDriven"). That produced duplicate rows per (source,
service_name), some with different `default_rate` values. Payroll pricing and
the "Permanent" rate-edit button both need a single row per (source,
service_name) to read/write reliably — this module is the merge logic that
collapses those duplicates, used by both the s14 migration and its tests.

Survivor rule (deterministic, no data loss beyond the duplicate rows
themselves): the row in the group referenced by the most `ride.z_rate_service_id`
rows wins; ties go to the lowest `z_rate_service_id`. The survivor's own
`default_rate` is kept as-is (never overwritten by a loser's rate).

Callers are responsible for committing the session — nothing here commits or
closes it, so the same logic can run inside an Alembic migration or a plain
test session.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional, Sequence

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db.models import Ride, ZRateOverride, ZRateService


@dataclass(frozen=True)
class DedupeGroupResult:
    """Outcome of merging one duplicate (source, service_name) group."""

    source: Optional[str]
    service_name: str
    survivor_id: int
    survivor_default_rate: Optional[Decimal]
    merged_ids: tuple[int, ...]
    ride_counts: dict = field(default_factory=dict)  # z_rate_service_id -> ride count, for the report
    rides_repointed: int = 0
    overrides_repointed: int = 0


def find_duplicate_groups(db: Session) -> list[list[ZRateService]]:
    """Group all ZRateService rows by (source, service_name); keep only groups with >1 row.

    NULL `source` values are grouped together like any other value (Python
    equality treats None == None as a valid grouping key here) — that mirrors
    how duplicates actually occur in this table.
    """
    rows = db.query(ZRateService).all()
    groups: dict[tuple[Optional[str], str], list[ZRateService]] = defaultdict(list)
    for row in rows:
        groups[(row.source, row.service_name)].append(row)
    return [group for group in groups.values() if len(group) > 1]


def ride_counts_for(db: Session, service_ids: Sequence[int]) -> dict[int, int]:
    """Count rides referencing each z_rate_service_id in `service_ids`."""
    if not service_ids:
        return {}
    rows = (
        db.query(Ride.z_rate_service_id, func.count(Ride.ride_id))
        .filter(Ride.z_rate_service_id.in_(service_ids))
        .group_by(Ride.z_rate_service_id)
        .all()
    )
    return {sid: int(cnt) for sid, cnt in rows}


def choose_survivor(group: Sequence[ZRateService], ride_counts: dict) -> ZRateService:
    """Most ride references wins; ties broken by lowest z_rate_service_id."""

    def _key(row: ZRateService) -> tuple[int, int]:
        return (-ride_counts.get(row.z_rate_service_id, 0), row.z_rate_service_id)

    return sorted(group, key=_key)[0]


def dedupe_group(db: Session, group: Sequence[ZRateService]) -> DedupeGroupResult:
    """Merge one duplicate group in-place: repoint FKs to the survivor, delete the rest.

    Order matters: FK rows (ride, z_rate_override) are repointed to the survivor
    BEFORE the loser rows are deleted, so ride.z_rate_service_id (ondelete=SET NULL)
    never gets silently nulled and z_rate_override (ondelete=CASCADE) never gets
    silently deleted.
    """
    ids = [row.z_rate_service_id for row in group]
    ride_counts = ride_counts_for(db, ids)
    survivor = choose_survivor(group, ride_counts)
    losers = [row for row in group if row.z_rate_service_id != survivor.z_rate_service_id]
    loser_ids = [row.z_rate_service_id for row in losers]

    rides_repointed = 0
    overrides_repointed = 0
    if loser_ids:
        rides_repointed = (
            db.query(Ride)
            .filter(Ride.z_rate_service_id.in_(loser_ids))
            .update({Ride.z_rate_service_id: survivor.z_rate_service_id}, synchronize_session=False)
        )
        overrides_repointed = (
            db.query(ZRateOverride)
            .filter(ZRateOverride.z_rate_service_id.in_(loser_ids))
            .update({ZRateOverride.z_rate_service_id: survivor.z_rate_service_id}, synchronize_session=False)
        )
        db.query(ZRateService).filter(ZRateService.z_rate_service_id.in_(loser_ids)).delete(
            synchronize_session=False
        )

    return DedupeGroupResult(
        source=survivor.source,
        service_name=survivor.service_name,
        survivor_id=survivor.z_rate_service_id,
        survivor_default_rate=survivor.default_rate,
        merged_ids=tuple(loser_ids),
        ride_counts=ride_counts,
        rides_repointed=rides_repointed,
        overrides_repointed=overrides_repointed,
    )


def dedupe_all(db: Session) -> list[DedupeGroupResult]:
    """Merge every duplicate (source, service_name) group.

    Idempotent: a second call after the first (or against a DB that already
    has the unique index) finds no duplicate groups and returns [].
    Does not commit — caller decides transaction boundaries.
    """
    groups = find_duplicate_groups(db)
    results = [dedupe_group(db, group) for group in groups]
    # Flush so a caller building the unique index right after this call sees
    # the deletes/repoints even without an explicit commit in between.
    db.flush()
    return results
