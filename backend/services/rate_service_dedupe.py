"""Soft-merge duplicate z_rate_service rows down to one ACTIVE row per (source, canonical service_name).

Background
----------
`z_rate_service` carries a unique index on (source, company_name, service_name),
but `company_name` is not a reliable key — the same route gets imported under
several spellings over time ("FirstAlt" / "Acumen International" / "Acumen",
"EverDriven" / "everDriven"). That produced duplicate rows per (source,
service_name), some with different `default_rate` values. Payroll pricing and
the "Permanent" rate-edit button both need a single ACTIVE row per (source,
service_name) to read/write reliably — this module is the merge logic that
collapses those duplicates, used by both the s14 migration and its tests.

Rule A — canonical grouping. Two rows also count as duplicates when their
service_name differs only by whitespace runs (e.g. a double space) — live
data has at least two such pairs. Grouping key is
(source, canonicalize(service_name)) where canonicalize() lowercases and
collapses whitespace runs to one space; this is done in Python
(dialect-independent) rather than in SQL. The survivor keeps its own raw
service_name, except that internal whitespace runs on the survivor's own
name are collapsed to single spaces (logged + audited if it changes
anything). The DB-level enforcement of this is a Postgres expression index
(regexp_replace) created directly by the s14 migration via raw SQL — it
cannot be represented as a portable SQLAlchemy Index() (SQLite has no
regexp_replace), so the model only carries a comment pointing at it.

Survivor ROW rule (FK continuity only — deterministic): the row in the group
referenced by the most `ride.z_rate_service_id` rows wins; ties go to the
lowest `z_rate_service_id`. FK rows (ride, z_rate_override) are repointed to
the survivor.

Nothing is ever hard-deleted (Malik: no permanent deletion). Losers are
soft-merged: `active = false`, `merged_into_id = <survivor id>`, and every
other column (default_rate, company_name, ...) is left exactly as it was —
the merge is fully reversible. `find_duplicate_groups` only considers
ACTIVE rows, so a second run is a no-op (idempotent).

Rule B — label normalisation. admin_rates.py, excell_reader.py and
pdf_reader.py still filter by `company_name == batch.company_name` in
places, so after the survivor is chosen its `company_name` is normalised to
whatever label current batches actually use for that `source` (the most
recent PayrollBatch.company_name for that source; falls back to the literals
'FirstAlt' (acumen) / 'EverDriven' (maz) when no batch exists). Logged +
audited when it changes.

Rule C — late_cancellation_rate carries over: if the survivor's own value is
NULL and any loser in the group has one set, the loser's value (highest loser
id wins on a tie) is copied onto the survivor. Logged + audited.

Survivor RATE rule (2026-09-23 real-data finding, refined same day): FK
reference count is NOT a reliable signal for which rate drivers were
actually paid — on 13 of 53 conflicting groups the import-time resolver
(backend/services/rates.py) picked a row by company_name label, not by FK,
so the row with zero FK references sometimes held the rate that was
actually paid out most recently. So after the survivor ROW is chosen for FK
continuity, its `default_rate` is separately considered for an update to
the "last paid" rate — see `last_paid_signal_for()` for exactly which rides
qualify and how confidence is decided. The update only happens when the
signal is CONFIRMED; an UNCLEAR signal (e.g. a single special-priced ride)
leaves the stored rate untouched and only gets logged.

Rule D — zero-rate survivor rescue: a stub must never win over a real rate.
If, after the last-paid rule runs, the survivor's default_rate is still NULL
or 0 (i.e. the last-paid signal was UNCLEAR or NONE), and some loser in the
group has a non-zero default_rate, the survivor adopts the highest such
loser rate (tie -> highest loser id). Logged + audited.

Every meaningful change (merge, rate change, label normalisation, LC-rate
carry, zero-rate rescue, own-name whitespace cleanup) writes an `AuditLog`
row so it's traceable and undoable by hand if ever needed.

Callers are responsible for committing the session — nothing here commits or
closes it, so the same logic can run inside an Alembic migration or a plain
test session.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional, Sequence

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db.models import AuditLog, PayrollBatch, Ride, ZRateOverride, ZRateService

# Route-level pricing sources only — a ride only counts toward the "last
# paid" signal if it was priced through the normal route/service lookup.
# Everything else (single-ride overrides, manual corrections, reconciliation
# adjustments, zero-rate placeholders, canceled trips, ...) is excluded so a
# one-off special-priced ride never gets mistaken for the route's going rate.
QUALIFYING_Z_RATE_SOURCES = frozenset({
    "service_default",
    "service",
    "permanent_override",
    "csv_match",
})

# Late-cancellation shaped: net_pay is 40-55% of z_rate. Even if such a ride
# somehow carries a qualifying z_rate_source, it must not count — a
# late-cancel half rate must never become the route's rate.
_LATE_CANCEL_LOW = Decimal("0.40")
_LATE_CANCEL_HIGH = Decimal("0.55")

_MIGRATION_ACTOR_EMAIL = "migration s14"

# Known current partner labels, used as a last-resort fallback for Rule B
# when no PayrollBatch exists yet for a source.
_FALLBACK_COMPANY_NAME_BY_SOURCE = {
    "acumen": "FirstAlt",
    "maz": "EverDriven",
}

# Postgres expression index name (created via raw SQL in the s14 migration —
# see module docstring, Rule A). Referenced here only so tests/tools can
# assert against the same literal name in one place.
CANONICAL_NAME_INDEX_NAME = "uq_z_rate_service_source_canon_name_active"


def canonical_service_name(name: Optional[str]) -> str:
    """Lowercased, whitespace-run-collapsed form of a service name — the
    grouping key for Rule A. Dialect-independent (pure Python), mirrored by
    a Postgres expression index (regexp_replace) at the DB level."""
    return re.sub(r"\s+", " ", (name or "")).strip().lower()


@dataclass(frozen=True)
class LastPaidSignal:
    """What drivers were actually paid, name-matched, for one (source, service_name)."""

    rate: Optional[Decimal]
    batch_id: Optional[int]
    rides_at_rate: int
    confidence: str  # "confirmed" | "unclear" | "none"


@dataclass(frozen=True)
class DedupeGroupResult:
    """Outcome of soft-merging one duplicate (source, canonical service_name) group."""

    source: Optional[str]
    service_name: str
    survivor_id: int
    survivor_default_rate: Optional[Decimal]  # final rate, AFTER the last-paid adjustment (if confirmed)
    merged_ids: tuple[int, ...]  # loser ids — soft-merged (active=false), never deleted
    ride_counts: dict = field(default_factory=dict)  # z_rate_service_id -> ride count, for the report
    rides_repointed: int = 0
    overrides_repointed: int = 0
    # Last-paid-rate signal (name-matched, qualifying rides only — see module docstring)
    last_paid_rate: Optional[Decimal] = None
    last_paid_batch_id: Optional[int] = None
    rides_at_that_rate: int = 0
    confidence: str = "none"  # "confirmed" | "unclear" | "none"
    rate_changed: bool = False
    old_default_rate: Optional[Decimal] = None  # survivor's stored rate BEFORE the last-paid adjustment
    # Rule A: survivor's own service_name whitespace cleanup
    service_name_normalized: bool = False
    old_service_name: Optional[str] = None
    # Rule B: company_name label normalization
    company_name_changed: bool = False
    old_company_name: Optional[str] = None
    new_company_name: Optional[str] = None
    # Rule C: late_cancellation_rate carried from a loser
    late_cancellation_carried: bool = False
    late_cancellation_rate: Optional[Decimal] = None
    late_cancellation_source_id: Optional[int] = None
    # Rule D: zero-rate survivor rescued from a loser's non-zero rate
    zero_rate_rescued: bool = False
    zero_rate_rescued_from_id: Optional[int] = None


def find_duplicate_groups(db: Session) -> list[list[ZRateService]]:
    """Group ACTIVE ZRateService rows by (source, canonical service_name); keep
    only groups with >1 row.

    Rule A: grouping uses the canonicalized name (whitespace-collapsed,
    lowercased) so rows differing only by e.g. a double space still merge.
    Only active rows are grouped — a row already soft-merged (active=false)
    is not a re-merge candidate, and its continued presence must not make an
    otherwise-already-merged (source, service_name) look like a fresh
    duplicate on a second run (idempotency).
    """
    rows = db.query(ZRateService).filter(ZRateService.active.is_(True)).all()
    groups: dict[tuple[Optional[str], str], list[ZRateService]] = defaultdict(list)
    for row in rows:
        key = (row.source, canonical_service_name(row.service_name))
        groups[key].append(row)
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
    """Most ride references wins; ties broken by lowest z_rate_service_id.

    This is FK-continuity only — see last_paid_signal_for() for the rate
    value itself, which is decided by a separate, name-matched rule.
    """

    def _key(row: ZRateService) -> tuple[int, int]:
        return (-ride_counts.get(row.z_rate_service_id, 0), row.z_rate_service_id)

    return sorted(group, key=_key)[0]


def _canonical_company_name_for_source(db: Session, source: Optional[str]) -> Optional[str]:
    """Rule B: the company_name label current batches use for `source`.

    The most recent PayrollBatch.company_name for that source (by highest
    payroll_batch_id, consistent with how "most recent" is decided
    elsewhere in this module); falls back to the known current literal
    labels when no batch exists for that source at all.
    """
    row = (
        db.query(PayrollBatch.company_name)
        .filter(PayrollBatch.source == source)
        .order_by(PayrollBatch.payroll_batch_id.desc())
        .limit(1)
        .one_or_none()
    )
    if row and row[0]:
        return row[0]
    return _FALLBACK_COMPANY_NAME_BY_SOURCE.get(source)


def _qualifying_rides(db: Session, *, source: Optional[str], service_name: str, names: Optional[Sequence[str]] = None) -> list[Ride]:
    """Rides that count toward the 'last paid' signal for (source, service_name).

    A ride qualifies only when ALL of:
      - removed_at IS NULL
      - z_rate > 0
      - z_rate_source is a route-level pricing source (QUALIFYING_Z_RATE_SOURCES)
      - not late-cancel shaped (net_pay > 0 and within 40-55% of z_rate)
      - matched by ride.source + ride.service_name BY NAME (not FK, exact —
        not canonicalized; see module docstring for why Rule A's
        canonicalization is scoped to z_rate_service grouping only)
    """
    # Match every raw spelling the group carried (survivor's original name,
    # its cleaned name, each loser's name) — rides were imported under all
    # of them.
    name_set = {n for n in [service_name, *(names or [])] if n}
    candidates = (
        db.query(Ride)
        .filter(
            Ride.source == source,
            Ride.service_name.in_(sorted(name_set)),
            Ride.removed_at.is_(None),
            Ride.z_rate > 0,
        )
        .all()
    )
    qualifying: list[Ride] = []
    for ride in candidates:
        if ride.z_rate_source not in QUALIFYING_Z_RATE_SOURCES:
            continue
        z_rate = Decimal(str(ride.z_rate))
        net_pay = Decimal(str(ride.net_pay)) if ride.net_pay is not None else Decimal("0")
        if net_pay > 0 and (z_rate * _LATE_CANCEL_LOW) <= net_pay <= (z_rate * _LATE_CANCEL_HIGH):
            continue  # late-cancel shaped — never a signal for the route rate
        qualifying.append(ride)
    return qualifying


def _mode_rate(rides: Sequence[Ride]) -> tuple[Decimal, int]:
    """Most common z_rate among `rides`; ties broken by the higher rate."""
    counts: dict[Decimal, int] = defaultdict(int)
    for ride in rides:
        counts[Decimal(str(ride.z_rate))] += 1
    best_rate, best_count = sorted(counts.items(), key=lambda kv: (-kv[1], -kv[0]))[0]
    return best_rate, best_count


def last_paid_signal_for(db: Session, *, source: Optional[str], service_name: str, names: Optional[Sequence[str]] = None) -> LastPaidSignal:
    """The rate drivers were actually most recently paid, with a confidence level.

    - CONFIRMED: the most recent qualifying batch's mode rate is backed by
      either (a) >=2 qualifying rides in that batch at that rate, or (b) the
      immediately-preceding qualifying batch's mode being the same rate.
      Callers should adopt this rate.
    - UNCLEAR: neither condition holds (typically a single qualifying ride
      in the latest batch with no corroborating prior batch) — could be a
      special price. Callers should keep the row's stored rate.
    - NONE: no qualifying rides at all for this (source, service_name).
    """
    qualifying = _qualifying_rides(db, source=source, service_name=service_name, names=names)
    if not qualifying:
        return LastPaidSignal(rate=None, batch_id=None, rides_at_rate=0, confidence="none")

    by_batch: dict[int, list[Ride]] = defaultdict(list)
    for ride in qualifying:
        by_batch[ride.payroll_batch_id].append(ride)

    latest_batch_id = max(by_batch.keys())
    latest_rate, latest_count = _mode_rate(by_batch[latest_batch_id])

    confirmed = latest_count >= 2
    if not confirmed:
        earlier_batch_ids = [bid for bid in by_batch if bid < latest_batch_id]
        if earlier_batch_ids:
            prev_batch_id = max(earlier_batch_ids)
            prev_rate, _prev_count = _mode_rate(by_batch[prev_batch_id])
            confirmed = prev_rate == latest_rate

    return LastPaidSignal(
        rate=latest_rate,
        batch_id=latest_batch_id,
        rides_at_rate=latest_count,
        confidence="confirmed" if confirmed else "unclear",
    )


def _audit(
    db: Session,
    *,
    action: str,
    target_id: int,
    before_value: Optional[dict],
    after_value: Optional[dict],
) -> None:
    db.add(AuditLog(
        actor_user_id=None,
        actor_email=_MIGRATION_ACTOR_EMAIL,
        action=action,
        target_type="z_rate_service",
        target_id=target_id,
        before_value=before_value,
        after_value=after_value,
    ))


def dedupe_group(db: Session, group: Sequence[ZRateService]) -> DedupeGroupResult:
    """Soft-merge one duplicate group: repoint FKs to the survivor, deactivate
    the rest (never delete), normalize the survivor's own name whitespace
    (Rule A) and company_name label (Rule B), carry over late_cancellation_rate
    if missing (Rule C), adopt the last-paid rate when confirmed, and rescue a
    zero/NULL survivor rate from a loser's non-zero rate when nothing else
    resolved it (Rule D). Writes an AuditLog row for every change made.

    Order matters: FK rows (ride, z_rate_override) are repointed to the
    survivor BEFORE the losers are deactivated, so ride.z_rate_service_id
    always ends up pointing at the row that's actually active.
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
        # Soft-merge: deactivate + point at the survivor. Nothing is deleted
        # — default_rate, company_name, everything else on the loser is left
        # exactly as it was, so the merge is fully reversible.
        for loser in losers:
            loser.active = False
            loser.merged_into_id = survivor.z_rate_service_id
            _audit(
                db,
                action="rate_dedupe_merge",
                target_id=loser.z_rate_service_id,
                before_value={"company_name": loser.company_name},
                after_value={"merged_into_id": survivor.z_rate_service_id},
            )

    # Rule A (own-name cleanup): the survivor keeps its own raw name, but
    # internal whitespace runs are collapsed to a single space.
    old_service_name = survivor.service_name
    cleaned_service_name = re.sub(r"\s+", " ", old_service_name or "").strip()
    service_name_normalized = cleaned_service_name != old_service_name
    if service_name_normalized:
        survivor.service_name = cleaned_service_name
        _audit(
            db,
            action="rate_dedupe_name_normalized",
            target_id=survivor.z_rate_service_id,
            before_value={"service_name": old_service_name},
            after_value={"service_name": cleaned_service_name},
        )

    # Rule B: normalize the survivor's company_name to whatever label
    # current batches actually use for this source.
    old_company_name = survivor.company_name
    new_company_name = _canonical_company_name_for_source(db, survivor.source)
    company_name_changed = new_company_name is not None and new_company_name != old_company_name
    if company_name_changed:
        survivor.company_name = new_company_name
        _audit(
            db,
            action="rate_dedupe_label_normalized",
            target_id=survivor.z_rate_service_id,
            before_value={"company_name": old_company_name},
            after_value={"company_name": new_company_name},
        )

    # Rule C: carry over late_cancellation_rate from a loser if the
    # survivor doesn't have one of its own.
    late_cancellation_carried = False
    late_cancellation_source_id = None
    if survivor.late_cancellation_rate is None:
        lc_candidates = [row for row in losers if row.late_cancellation_rate is not None]
        if lc_candidates:
            chosen = max(lc_candidates, key=lambda r: r.z_rate_service_id)
            survivor.late_cancellation_rate = chosen.late_cancellation_rate
            late_cancellation_carried = True
            late_cancellation_source_id = chosen.z_rate_service_id
            _audit(
                db,
                action="rate_dedupe_late_cancellation_carried",
                target_id=survivor.z_rate_service_id,
                before_value={"late_cancellation_rate": None},
                after_value={
                    "late_cancellation_rate": str(chosen.late_cancellation_rate),
                    "carried_from": chosen.z_rate_service_id,
                },
            )

    # Survivor RATE rule: adopt the last-paid rate only when confirmed —
    # see last_paid_signal_for() for exactly what that means.
    old_default_rate = survivor.default_rate
    group_names = [old_service_name, cleaned_service_name, *[row.service_name for row in losers]]
    signal = last_paid_signal_for(
        db, source=survivor.source, service_name=survivor.service_name, names=group_names,
    )
    # The last-paid rate is only used to settle WHICH COPY the operator meant.
    # So it applies only when the copies disagree, and only when the paid
    # rate is one of the copies' own rates. A paid rate matching neither
    # copy came from a "this batch only" / hand fix and must not become the
    # permanent rate (Malik, 2026-09-23). Same-rate groups keep their rate.
    group_rates = {
        Decimal(str(row.default_rate)) for row in group if row.default_rate is not None
    }
    copies_disagree = len(group_rates) > 1
    rate_changed = (
        copies_disagree
        and signal.confidence == "confirmed"
        and signal.rate is not None
        and signal.rate in group_rates
        and signal.rate != old_default_rate
    )
    if rate_changed:
        survivor.default_rate = signal.rate
        _audit(
            db,
            action="rate_dedupe_rate_change",
            target_id=survivor.z_rate_service_id,
            before_value={"default_rate": str(old_default_rate)},
            after_value={
                "default_rate": str(signal.rate),
                "last_paid_batch": signal.batch_id,
                "rides_at_rate": signal.rides_at_rate,
            },
        )

    # Rule D: a stub must never win over a real rate. If the survivor is
    # still zero/NULL after the last-paid rule (i.e. that signal wasn't
    # confirmed), adopt a loser's non-zero rate if one exists.
    zero_rate_rescued = False
    zero_rate_rescued_from_id = None
    current_rate = survivor.default_rate
    if (current_rate is None or current_rate == 0) and not rate_changed:
        nonzero_losers = [row for row in losers if row.default_rate is not None and row.default_rate != 0]
        if nonzero_losers:
            chosen = max(nonzero_losers, key=lambda r: (r.default_rate, r.z_rate_service_id))
            _audit(
                db,
                action="rate_dedupe_zero_rate_rescued",
                target_id=survivor.z_rate_service_id,
                before_value={"default_rate": str(current_rate) if current_rate is not None else None},
                after_value={
                    "default_rate": str(chosen.default_rate),
                    "adopted_from": chosen.z_rate_service_id,
                },
            )
            survivor.default_rate = chosen.default_rate
            zero_rate_rescued = True
            zero_rate_rescued_from_id = chosen.z_rate_service_id

    return DedupeGroupResult(
        source=survivor.source,
        service_name=survivor.service_name,
        survivor_id=survivor.z_rate_service_id,
        survivor_default_rate=survivor.default_rate,
        merged_ids=tuple(loser_ids),
        ride_counts=ride_counts,
        rides_repointed=rides_repointed,
        overrides_repointed=overrides_repointed,
        last_paid_rate=signal.rate,
        last_paid_batch_id=signal.batch_id,
        rides_at_that_rate=signal.rides_at_rate,
        confidence=signal.confidence,
        rate_changed=rate_changed,
        old_default_rate=old_default_rate,
        service_name_normalized=service_name_normalized,
        old_service_name=old_service_name if service_name_normalized else None,
        company_name_changed=company_name_changed,
        old_company_name=old_company_name if company_name_changed else None,
        new_company_name=new_company_name if company_name_changed else None,
        late_cancellation_carried=late_cancellation_carried,
        late_cancellation_rate=survivor.late_cancellation_rate if late_cancellation_carried else None,
        late_cancellation_source_id=late_cancellation_source_id,
        zero_rate_rescued=zero_rate_rescued,
        zero_rate_rescued_from_id=zero_rate_rescued_from_id,
    )


def normalize_all_active_labels(db: Session) -> list[tuple[int, str, str]]:
    """Rule B for rows that were never duplicated: every ACTIVE row's
    company_name becomes the label current batches use for its source, so
    the few remaining label-filtered code paths see one consistent label.
    Returns [(z_rate_service_id, old_label, new_label)] and audits each.
    Idempotent (nothing to change on a second run)."""
    changed: list[tuple[int, str, str]] = []
    label_by_source: dict[Optional[str], Optional[str]] = {}
    for row in db.query(ZRateService).filter(ZRateService.active.is_(True)).all():
        if row.source not in label_by_source:
            label_by_source[row.source] = _canonical_company_name_for_source(db, row.source)
        target = label_by_source[row.source]
        if target is None or row.company_name == target:
            continue
        old_label = row.company_name
        row.company_name = target
        _audit(
            db,
            action="rate_dedupe_label_normalized",
            target_id=row.z_rate_service_id,
            before_value={"company_name": old_label},
            after_value={"company_name": target},
        )
        changed.append((row.z_rate_service_id, old_label, target))
    db.flush()
    return changed


def dedupe_all(db: Session) -> list[DedupeGroupResult]:
    """Soft-merge every duplicate ACTIVE (source, canonical service_name) group.

    Idempotent: a second call finds no duplicate ACTIVE groups (the first
    call's losers are inactive and excluded from find_duplicate_groups) and
    returns []. Does not commit — caller decides transaction boundaries.
    """
    groups = find_duplicate_groups(db)
    results = [dedupe_group(db, group) for group in groups]
    # Flush so a caller building the partial unique index right after this
    # call sees the active-flag flips even without an explicit commit.
    db.flush()
    return results
