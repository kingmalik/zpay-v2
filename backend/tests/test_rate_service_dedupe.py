"""
Unit tests for backend/services/rate_service_dedupe.py — the soft-merge +
last-paid-rate logic migration s14 uses to collapse duplicate z_rate_service
rows down to one ACTIVE row per (source, service_name).

DB strategy: in-memory SQLite, same pattern as test_paychex_api_rail.py /
test_remove_ride.py (BigInteger PKs -> Integer, DATERANGE -> Text, NOW()
server_defaults relaxed). The post-migration partial unique index is
stripped from metadata before create_all so these tests can seed the
PRE-migration duplicate rows the dedupe logic is meant to clean up.

Run in isolation:
    PYTHONPATH=. python3 -m pytest backend/tests/test_rate_service_dedupe.py -q --no-header -p no:cacheprovider
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import BigInteger, Integer, Text, create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault("ZPAY_SECRET_KEY", "test-secret-key-for-rate-dedupe-tests-long-enough")
os.environ.setdefault("DATABASE_URL", "sqlite://")

from backend.db.models import AuditLog, Base, PayrollBatch, Person, Ride, ZRateOverride, ZRateService  # noqa: E402

# ── SQLite compat patches (same as other test files in this suite) ──────────
Base.metadata.tables["z_rate_override"].c["effective_during"].type = Text()
for _tbl in Base.metadata.tables.values():
    for _col in _tbl.columns:
        if _col.primary_key and isinstance(_col.type, BigInteger):
            _col.type = Integer()
        if _col.server_default is not None:
            _sd = _col.server_default
            _arg = getattr(getattr(_sd, "arg", None), "text", "") or ""
            if "NOW()" in _arg:
                _col.nullable = True
                _col.server_default = None

# No-op today (Rule A's canonical-name unique index is raw-SQL-only, not a
# SQLAlchemy Index() on the model at all — see models.py). Left as a guard
# in case a future model change reintroduces a portable version of it, so
# these tests can keep seeding PRE-migration duplicate rows either way.
_z_rate_service_tbl = Base.metadata.tables["z_rate_service"]
for _idx in list(_z_rate_service_tbl.indexes):
    if _idx.name == "uq_z_rate_service_source_service_name":
        _z_rate_service_tbl.indexes.discard(_idx)

_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)


@event.listens_for(_engine, "connect")
def _register_now(dbapi_conn, _rec):
    dbapi_conn.create_function("NOW", 0, lambda: datetime.now(timezone.utc).isoformat())


Base.metadata.create_all(_engine)
_SessionFactory = sessionmaker(bind=_engine, autoflush=False, autocommit=False)

from backend.services.rate_service_dedupe import (  # noqa: E402
    CANONICAL_NAME_INDEX_NAME,
    canonical_service_name,
    choose_survivor,
    dedupe_all,
    dedupe_group,
    find_duplicate_groups,
    last_paid_signal_for,
    ride_counts_for,
)

_NOW = datetime.now(timezone.utc)


def _db():
    return _SessionFactory()


def _wipe():
    s = _db()
    try:
        s.query(AuditLog).delete(synchronize_session=False)
        s.query(ZRateOverride).delete(synchronize_session=False)
        s.query(Ride).delete(synchronize_session=False)
        s.query(PayrollBatch).delete(synchronize_session=False)
        s.query(Person).delete(synchronize_session=False)
        s.query(ZRateService).delete(synchronize_session=False)
        s.commit()
    finally:
        s.close()


def _seed_person(s, person_id: int = 1) -> Person:
    p = Person(person_id=person_id, full_name="Test Driver", active=True, status="active", created_at=_NOW)
    s.add(p)
    s.flush()
    return p


def _seed_batch(s, batch_id: int, source: str = "acumen", company_name: str = "FirstAlt") -> PayrollBatch:
    b = PayrollBatch(
        payroll_batch_id=batch_id,
        source=source,
        company_name=company_name,
        batch_ref=f"W-test-{batch_id}",
        status="uploaded",
        currency="USD",
        uploaded_at=_NOW,
        period_start=date(2026, 5, 2),
        period_end=date(2026, 5, 8),
        week_start=date(2026, 5, 2),
        week_end=date(2026, 5, 8),
    )
    s.add(b)
    s.flush()
    return b


def _seed_service(
    s,
    service_id: int,
    source: str,
    company_name: str,
    service_name: str,
    default_rate: str,
    active: bool = True,
    late_cancellation_rate: str | None = None,
) -> ZRateService:
    svc = ZRateService(
        z_rate_service_id=service_id,
        source=source,
        company_name=company_name,
        service_key=f"svc_key_{service_id}",
        service_name=service_name,
        currency="USD",
        default_rate=Decimal(default_rate),
        late_cancellation_rate=Decimal(late_cancellation_rate) if late_cancellation_rate is not None else None,
        active=active,
        created_at=_NOW,
    )
    s.add(svc)
    s.flush()
    return svc


_RIDE_COUNTER = {"n": 0}


def _seed_ride(
    s,
    batch_id: int,
    person_id: int,
    source: str,
    service_name: str,
    z_rate: str,
    z_rate_service_id: int | None = None,
    z_rate_source: str = "service_default",
    net_pay: str | None = None,
    removed_at=None,
    ride_id: int | None = None,
) -> Ride:
    _RIDE_COUNTER["n"] += 1
    if ride_id is None:
        ride_id = 900000 + _RIDE_COUNTER["n"]
    if net_pay is None:
        net_pay = z_rate  # default: full pay, not late-cancel-shaped
    r = Ride(
        ride_id=ride_id,
        payroll_batch_id=batch_id,
        person_id=person_id,
        source=source,
        source_ref=f"test-src-{ride_id}",
        service_name=service_name,
        z_rate=Decimal(z_rate),
        z_rate_source=z_rate_source,
        z_rate_service_id=z_rate_service_id,
        gross_pay=Decimal(net_pay),
        net_pay=Decimal(net_pay),
        miles=Decimal("0.000"),
        deduction=Decimal("0"),
        spiff=Decimal("0"),
        ride_start_ts=datetime(2026, 5, 1, tzinfo=timezone.utc),
        removed_at=removed_at,
    )
    s.add(r)
    s.flush()
    return r


# ── Grouping / survivor-row (FK continuity) ──────────────────────────────────

class TestFindDuplicateGroups:
    def setup_method(self):
        _wipe()

    def teardown_method(self):
        _wipe()

    def test_no_duplicates_returns_empty(self):
        s = _db()
        _seed_service(s, 1, "acumen", "FirstAlt", "Route A", "40.00")
        _seed_service(s, 2, "acumen", "FirstAlt", "Route B", "50.00")
        s.commit()

        assert find_duplicate_groups(s) == []
        s.close()

    def test_duplicate_group_found(self):
        s = _db()
        _seed_service(s, 1, "acumen", "FirstAlt", "Route A", "40.00")
        _seed_service(s, 2, "acumen", "Acumen International", "Route A", "45.00")
        s.commit()

        groups = find_duplicate_groups(s)
        assert len(groups) == 1
        assert sorted(row.z_rate_service_id for row in groups[0]) == [1, 2]
        s.close()

    def test_inactive_rows_excluded_from_grouping(self):
        """A row already soft-merged (active=false) must not create a false
        duplicate group on a later run."""
        s = _db()
        _seed_service(s, 1, "acumen", "FirstAlt", "Route A", "45.00")
        _seed_service(s, 2, "acumen", "Acumen International", "Route A", "40.00", active=False)
        s.commit()

        assert find_duplicate_groups(s) == []
        s.close()

    def test_different_source_not_grouped_together(self):
        s = _db()
        _seed_service(s, 1, "acumen", "FirstAlt", "Route A", "40.00")
        _seed_service(s, 2, "maz", "EverDriven", "Route A", "60.00")
        s.commit()

        assert find_duplicate_groups(s) == []
        s.close()


class TestChooseSurvivor:
    def setup_method(self):
        _wipe()

    def teardown_method(self):
        _wipe()

    def test_most_ride_references_wins(self):
        s = _db()
        _seed_person(s)
        _seed_batch(s, 1)
        svc_a = _seed_service(s, 1, "acumen", "FirstAlt", "Route A", "40.00")
        svc_b = _seed_service(s, 2, "acumen", "Acumen International", "Route A", "45.00")
        _seed_ride(s, 1, 1, "acumen", "Route A", "40.00", z_rate_service_id=1)
        _seed_ride(s, 1, 1, "acumen", "Route A", "45.00", z_rate_service_id=2)
        _seed_ride(s, 1, 1, "acumen", "Route A", "45.00", z_rate_service_id=2)
        s.commit()

        counts = ride_counts_for(s, [1, 2])
        survivor = choose_survivor([svc_a, svc_b], counts)
        assert survivor.z_rate_service_id == 2
        s.close()

    def test_tie_breaks_to_lowest_id(self):
        s = _db()
        svc_a = _seed_service(s, 5, "acumen", "FirstAlt", "Route A", "40.00")
        svc_b = _seed_service(s, 3, "acumen", "Acumen International", "Route A", "45.00")
        s.commit()

        counts = ride_counts_for(s, [5, 3])  # both zero references -> tie
        survivor = choose_survivor([svc_a, svc_b], counts)
        assert survivor.z_rate_service_id == 3
        s.close()


# ── Last-paid-rate signal (qualifying rides + confidence) ───────────────────

class TestLastPaidSignal:
    def setup_method(self):
        _wipe()
        s = _db()
        _seed_person(s)
        s.commit()
        s.close()

    def teardown_method(self):
        _wipe()

    def test_no_qualifying_rides_returns_none_confidence(self):
        s = _db()
        signal = last_paid_signal_for(s, source="acumen", service_name="Route A")
        assert signal.confidence == "none"
        assert signal.rate is None
        s.close()

    def test_two_rides_same_rate_in_latest_batch_is_confirmed(self):
        s = _db()
        _seed_batch(s, 10)
        _seed_ride(s, 10, 1, "acumen", "Route A", "61.00", z_rate_source="service_default")
        _seed_ride(s, 10, 1, "acumen", "Route A", "61.00", z_rate_source="service_default")
        s.commit()

        signal = last_paid_signal_for(s, source="acumen", service_name="Route A")
        assert signal.confidence == "confirmed"
        assert signal.rate == Decimal("61.00")
        assert signal.rides_at_rate == 2
        assert signal.batch_id == 10
        s.close()

    def test_single_ride_matching_previous_batch_mode_is_confirmed(self):
        s = _db()
        _seed_batch(s, 10)
        _seed_batch(s, 11)
        # Prior batch: mode is 61.00 (2 rides)
        _seed_ride(s, 10, 1, "acumen", "Route A", "61.00", z_rate_source="service_default")
        _seed_ride(s, 10, 1, "acumen", "Route A", "61.00", z_rate_source="service_default")
        # Latest batch: only 1 ride, same rate as prior batch's mode
        _seed_ride(s, 11, 1, "acumen", "Route A", "61.00", z_rate_source="service_default")
        s.commit()

        signal = last_paid_signal_for(s, source="acumen", service_name="Route A")
        assert signal.confidence == "confirmed"
        assert signal.rate == Decimal("61.00")
        assert signal.batch_id == 11
        assert signal.rides_at_rate == 1
        s.close()

    def test_single_special_price_ride_with_different_prior_mode_is_unclear(self):
        """Malik's concern: a single ride paid a special price must not
        become the route's rate."""
        s = _db()
        _seed_batch(s, 10)
        _seed_batch(s, 11)
        # Prior batch mode: 62.00
        _seed_ride(s, 10, 1, "acumen", "Route A", "62.00", z_rate_source="service_default")
        _seed_ride(s, 10, 1, "acumen", "Route A", "62.00", z_rate_source="service_default")
        # Latest batch: single ride at a DIFFERENT, special price
        _seed_ride(s, 11, 1, "acumen", "Route A", "99.00", z_rate_source="service_default")
        s.commit()

        signal = last_paid_signal_for(s, source="acumen", service_name="Route A")
        assert signal.confidence == "unclear"
        assert signal.rate == Decimal("99.00")  # reported, but not to be adopted
        assert signal.rides_at_rate == 1
        s.close()

    def test_single_ride_override_rides_ignored_entirely(self):
        s = _db()
        _seed_batch(s, 10)
        # Only ride available is a single_ride_override — must not qualify.
        _seed_ride(s, 10, 1, "acumen", "Route A", "999.00", z_rate_source="single_ride_override")
        s.commit()

        signal = last_paid_signal_for(s, source="acumen", service_name="Route A")
        assert signal.confidence == "none"
        assert signal.rate is None
        s.close()

    def test_manual_rides_ignored_entirely(self):
        s = _db()
        _seed_batch(s, 10)
        _seed_ride(s, 10, 1, "acumen", "Route A", "77.00", z_rate_source="manual")
        s.commit()

        signal = last_paid_signal_for(s, source="acumen", service_name="Route A")
        assert signal.confidence == "none"
        s.close()

    def test_late_cancel_shaped_rides_ignored(self):
        """net_pay between 40-55% of z_rate is late-cancel shaped — excluded
        even if z_rate_source is otherwise qualifying."""
        s = _db()
        _seed_batch(s, 10)
        # z_rate=100, net_pay=50 -> exactly 50% -> late-cancel shaped, excluded
        _seed_ride(s, 10, 1, "acumen", "Route A", "100.00", z_rate_source="service_default", net_pay="50.00")
        s.commit()

        signal = last_paid_signal_for(s, source="acumen", service_name="Route A")
        assert signal.confidence == "none"
        assert signal.rate is None
        s.close()

    def test_removed_rides_ignored(self):
        s = _db()
        _seed_batch(s, 10)
        _seed_ride(
            s, 10, 1, "acumen", "Route A", "61.00", z_rate_source="service_default",
            removed_at=_NOW,
        )
        s.commit()

        signal = last_paid_signal_for(s, source="acumen", service_name="Route A")
        assert signal.confidence == "none"
        s.close()

    def test_mode_tie_picks_higher_rate(self):
        s = _db()
        _seed_batch(s, 10)
        _seed_ride(s, 10, 1, "acumen", "Route A", "60.00", z_rate_source="service_default")
        _seed_ride(s, 10, 1, "acumen", "Route A", "65.00", z_rate_source="service_default")
        s.commit()

        signal = last_paid_signal_for(s, source="acumen", service_name="Route A")
        # 1 ride each -> tie -> higher rate wins as the reported mode.
        assert signal.rate == Decimal("65.00")
        assert signal.rides_at_rate == 1
        # A 1-1 tie with no corroborating prior batch is UNCLEAR, not confirmed.
        assert signal.confidence == "unclear"
        s.close()


# ── dedupe_group / dedupe_all: soft-merge + rate adjustment + audit log ─────

class TestDedupeGroupSoftMerge:
    def setup_method(self):
        _wipe()
        s = _db()
        _seed_person(s)
        s.commit()
        s.close()

    def teardown_method(self):
        _wipe()

    def test_loser_is_deactivated_not_deleted(self):
        s = _db()
        _seed_batch(s, 1)
        _seed_service(s, 1, "acumen", "FirstAlt", "Route A", "40.00")
        _seed_service(s, 2, "acumen", "Acumen International", "Route A", "40.00")
        _seed_ride(s, 1, 1, "acumen", "Route A", "40.00", z_rate_service_id=2)
        _seed_ride(s, 1, 1, "acumen", "Route A", "40.00", z_rate_service_id=2)
        ov = ZRateOverride(
            z_rate_service_id=1,
            effective_during="[2026-05-01,2026-05-08)",
            override_rate=Decimal("55.00"),
            active=True,
            created_at=_NOW,
        )
        s.add(ov)
        s.commit()

        groups = find_duplicate_groups(s)
        assert len(groups) == 1
        result = dedupe_group(s, groups[0])
        s.commit()

        assert result.survivor_id == 2
        assert result.merged_ids == (1,)
        assert result.rides_repointed == 0  # both rides already pointed at survivor
        assert result.overrides_repointed == 1

        # Loser row still exists — soft-merged, not deleted.
        loser = s.query(ZRateService).filter(ZRateService.z_rate_service_id == 1).one()
        assert loser.active is False
        assert loser.merged_into_id == 2
        assert loser.default_rate == Decimal("40.00")  # untouched
        assert loser.company_name == "FirstAlt"  # untouched

        survivor = s.query(ZRateService).filter(ZRateService.z_rate_service_id == 2).one()
        assert survivor.active is True
        assert survivor.merged_into_id is None

        # Override repointed, not cascade-deleted.
        ov_after = s.query(ZRateOverride).one()
        assert ov_after.z_rate_service_id == 2

        # Both rows still present — total count unchanged (nothing deleted).
        assert s.query(ZRateService).count() == 2
        s.close()

    def test_merge_writes_audit_log_row(self):
        s = _db()
        _seed_service(s, 1, "acumen", "FirstAlt", "Route A", "40.00")
        _seed_service(s, 2, "acumen", "Acumen International", "Route A", "40.00")
        s.commit()

        groups = find_duplicate_groups(s)
        dedupe_group(s, groups[0])
        s.commit()

        rows = s.query(AuditLog).filter(AuditLog.action == "rate_dedupe_merge").all()
        assert len(rows) == 1
        assert rows[0].target_type == "z_rate_service"
        # Tie (no ride references on either row) -> survivor = lowest id (1),
        # so the loser being merged away (and audited) is id=2.
        assert rows[0].target_id == 2
        assert rows[0].after_value == {"merged_into_id": 1}
        assert rows[0].actor_email == "migration s14"
        s.close()

    def test_survivor_adopts_confirmed_last_paid_rate_from_different_row(self):
        """Real-data scenario: FK-survivor row (id=1, most refs) stores $62,
        but drivers were actually paid $61 most recently — id=1 must end up
        with $61, and it must be logged as an audit row."""
        s = _db()
        _seed_batch(s, 133)
        svc_a = _seed_service(s, 1, "acumen", "FirstAlt", "LKW REDMOND HS 02 AM", "62.00")
        _seed_service(s, 2, "acumen", "Acumen International", "LKW REDMOND HS 02 AM", "61.00")
        # FK references make id=1 the survivor by row rule...
        _seed_ride(s, 133, 1, "acumen", "LKW REDMOND HS 02 AM", "61.00", z_rate_service_id=1, z_rate_source="service_default")
        _seed_ride(s, 133, 1, "acumen", "LKW REDMOND HS 02 AM", "61.00", z_rate_service_id=1, z_rate_source="service_default")
        s.commit()

        groups = find_duplicate_groups(s)
        result = dedupe_group(s, groups[0])
        s.commit()

        assert result.survivor_id == 1  # FK continuity: id=1 wins the row
        assert result.confidence == "confirmed"
        assert result.rate_changed is True
        assert result.old_default_rate == Decimal("62.00")
        assert result.survivor_default_rate == Decimal("61.00")  # adopted last-paid rate

        survivor = s.query(ZRateService).filter(ZRateService.z_rate_service_id == 1).one()
        assert survivor.default_rate == Decimal("61.00")

        rate_change_rows = s.query(AuditLog).filter(AuditLog.action == "rate_dedupe_rate_change").all()
        assert len(rate_change_rows) == 1
        assert rate_change_rows[0].target_id == 1
        assert rate_change_rows[0].before_value == {"default_rate": "62.00"}
        assert rate_change_rows[0].after_value["default_rate"] == "61.00"
        assert rate_change_rows[0].after_value["last_paid_batch"] == 133
        s.close()

    def test_unclear_signal_leaves_survivor_rate_unchanged(self):
        s = _db()
        _seed_batch(s, 10)
        _seed_batch(s, 11)
        _seed_service(s, 1, "acumen", "FirstAlt", "Route A", "62.00")
        _seed_service(s, 2, "acumen", "Acumen International", "Route A", "60.00")
        # Prior batch mode 62.00, latest batch single special-priced ride 99.00
        _seed_ride(s, 10, 1, "acumen", "Route A", "62.00", z_rate_service_id=1, z_rate_source="service_default")
        _seed_ride(s, 10, 1, "acumen", "Route A", "62.00", z_rate_service_id=1, z_rate_source="service_default")
        _seed_ride(s, 11, 1, "acumen", "Route A", "99.00", z_rate_service_id=1, z_rate_source="service_default")
        s.commit()

        groups = find_duplicate_groups(s)
        result = dedupe_group(s, groups[0])
        s.commit()

        assert result.confidence == "unclear"
        assert result.rate_changed is False
        assert result.survivor_default_rate == Decimal("62.00")  # stored rate kept

        # No rate_dedupe_rate_change audit row written when unchanged.
        rate_change_rows = s.query(AuditLog).filter(AuditLog.action == "rate_dedupe_rate_change").all()
        assert rate_change_rows == []
        s.close()

    def test_no_paid_history_leaves_survivor_rate_unchanged(self):
        s = _db()
        _seed_service(s, 1, "acumen", "FirstAlt", "Route A", "40.00")
        _seed_service(s, 2, "acumen", "Acumen International", "Route A", "45.00")
        s.commit()  # no rides at all

        groups = find_duplicate_groups(s)
        result = dedupe_group(s, groups[0])
        s.commit()

        assert result.confidence == "none"
        assert result.rate_changed is False
        s.close()


class TestDedupeAll:
    def setup_method(self):
        _wipe()
        s = _db()
        _seed_person(s)
        s.commit()
        s.close()

    def teardown_method(self):
        _wipe()

    def test_merges_multiple_groups(self):
        s = _db()
        _seed_service(s, 1, "acumen", "FirstAlt", "Route A", "40.00")
        _seed_service(s, 2, "acumen", "Acumen International", "Route A", "45.00")
        _seed_service(s, 3, "maz", "EverDriven", "Route B", "60.00")
        _seed_service(s, 4, "maz", "everDriven", "Route B", "60.00")
        _seed_service(s, 5, "maz", "Maz Services", "Route B", "60.00")
        _seed_service(s, 6, "acumen", "FirstAlt", "Route C", "70.00")  # not a duplicate
        s.commit()

        results = dedupe_all(s)
        s.commit()

        assert len(results) == 2
        active_rows = s.query(ZRateService).filter(ZRateService.active.is_(True)).all()
        assert len(active_rows) == 3  # one survivor per merged group + untouched Route C
        # Nothing deleted — all 6 rows still present.
        assert s.query(ZRateService).count() == 6
        s.close()

    def test_idempotent_second_run_is_noop(self):
        s = _db()
        _seed_service(s, 1, "acumen", "FirstAlt", "Route A", "40.00")
        _seed_service(s, 2, "acumen", "Acumen International", "Route A", "45.00")
        s.commit()

        first = dedupe_all(s)
        s.commit()
        assert len(first) == 1

        second = dedupe_all(s)
        s.commit()
        assert second == []

        assert s.query(ZRateService).count() == 2  # still both rows, nothing deleted
        active_rows = s.query(ZRateService).filter(ZRateService.active.is_(True)).all()
        assert len(active_rows) == 1
        s.close()

    def test_no_duplicates_at_all_returns_empty(self):
        s = _db()
        _seed_service(s, 1, "acumen", "FirstAlt", "Route A", "40.00")
        s.commit()

        assert dedupe_all(s) == []
        s.close()


# ── Rule A: canonical-name grouping (whitespace-only duplicates) ───────────

class TestRuleACanonicalGrouping:
    def setup_method(self):
        _wipe()
        s = _db()
        _seed_person(s)
        s.commit()
        s.close()

    def teardown_method(self):
        _wipe()

    def test_canonical_service_name_collapses_whitespace_and_lowercases(self):
        assert canonical_service_name("Embrace Learning INST  IB 02") == "embrace learning inst ib 02"
        assert canonical_service_name("Embrace Learning INST IB 02") == "embrace learning inst ib 02"
        assert canonical_service_name("  LKW EMERSON HS  01 AM (F) ") == "lkw emerson hs 01 am (f)"

    def test_double_space_variant_is_grouped_as_duplicate(self):
        """Real live-data pair: 'Embrace Learning INST  IB 02' (double space)
        vs 'Embrace Learning INST IB 02' (single space) must merge."""
        s = _db()
        _seed_service(s, 1, "acumen", "FirstAlt", "Embrace Learning INST  IB 02", "50.00")
        _seed_service(s, 2, "acumen", "Acumen International", "Embrace Learning INST IB 02", "50.00")
        s.commit()

        groups = find_duplicate_groups(s)
        assert len(groups) == 1
        assert sorted(row.z_rate_service_id for row in groups[0]) == [1, 2]
        s.close()

    def test_raw_name_kept_but_survivors_own_whitespace_collapsed(self):
        s = _db()
        _seed_batch(s, 1)
        # Survivor (has the FK reference) carries the double-space name.
        _seed_service(s, 1, "acumen", "FirstAlt", "LKW EMERSON HS  01 AM (F)", "70.00")
        _seed_service(s, 2, "acumen", "Acumen International", "LKW EMERSON HS 01 AM (F)", "70.00")
        _seed_ride(s, 1, 1, "acumen", "LKW EMERSON HS  01 AM (F)", "70.00", z_rate_service_id=1)
        s.commit()

        groups = find_duplicate_groups(s)
        result = dedupe_group(s, groups[0])
        s.commit()

        assert result.survivor_id == 1
        assert result.service_name_normalized is True
        assert result.old_service_name == "LKW EMERSON HS  01 AM (F)"
        assert result.service_name == "LKW EMERSON HS 01 AM (F)"

        survivor = s.query(ZRateService).filter(ZRateService.z_rate_service_id == 1).one()
        assert survivor.service_name == "LKW EMERSON HS 01 AM (F)"

        rows = s.query(AuditLog).filter(AuditLog.action == "rate_dedupe_name_normalized").all()
        assert len(rows) == 1
        assert rows[0].before_value == {"service_name": "LKW EMERSON HS  01 AM (F)"}
        assert rows[0].after_value == {"service_name": "LKW EMERSON HS 01 AM (F)"}
        s.close()

    def test_survivor_with_already_clean_name_is_not_flagged(self):
        s = _db()
        _seed_service(s, 1, "acumen", "FirstAlt", "Route A", "40.00")
        _seed_service(s, 2, "acumen", "Acumen International", "Route A", "45.00")
        s.commit()

        groups = find_duplicate_groups(s)
        result = dedupe_group(s, groups[0])
        s.commit()

        assert result.service_name_normalized is False
        assert result.old_service_name is None
        s.close()


# ── Rule B: company_name label normalization ────────────────────────────────

class TestRuleBLabelNormalization:
    def setup_method(self):
        _wipe()
        s = _db()
        _seed_person(s)
        s.commit()
        s.close()

    def teardown_method(self):
        _wipe()

    def test_survivor_company_name_normalized_to_current_batch_label(self):
        s = _db()
        _seed_batch(s, 1, source="acumen", company_name="FirstAlt")
        # Survivor (lowest id, tie on FK refs) carries a stale label.
        _seed_service(s, 1, "acumen", "Acumen International", "Route A", "40.00")
        _seed_service(s, 2, "acumen", "Some Other Label", "Route A", "40.00")
        s.commit()

        groups = find_duplicate_groups(s)
        result = dedupe_group(s, groups[0])
        s.commit()

        assert result.survivor_id == 1
        assert result.company_name_changed is True
        assert result.old_company_name == "Acumen International"
        assert result.new_company_name == "FirstAlt"

        survivor = s.query(ZRateService).filter(ZRateService.z_rate_service_id == 1).one()
        assert survivor.company_name == "FirstAlt"

        rows = s.query(AuditLog).filter(AuditLog.action == "rate_dedupe_label_normalized").all()
        assert len(rows) == 1
        assert rows[0].target_id == 1
        assert rows[0].before_value == {"company_name": "Acumen International"}
        assert rows[0].after_value == {"company_name": "FirstAlt"}
        s.close()

    def test_falls_back_to_known_literal_when_no_batch_exists(self):
        s = _db()
        _seed_service(s, 1, "maz", "everDriven", "Route B", "60.00")
        _seed_service(s, 2, "maz", "Maz Services", "Route B", "60.00")
        s.commit()  # no PayrollBatch rows at all for source='maz'

        groups = find_duplicate_groups(s)
        result = dedupe_group(s, groups[0])
        s.commit()

        assert result.company_name_changed is True
        assert result.new_company_name == "EverDriven"  # known fallback for maz
        s.close()

    def test_no_change_when_survivor_label_already_matches(self):
        s = _db()
        _seed_batch(s, 1, source="acumen", company_name="FirstAlt")
        _seed_service(s, 1, "acumen", "FirstAlt", "Route A", "40.00")
        _seed_service(s, 2, "acumen", "Acumen International", "Route A", "40.00")
        s.commit()

        groups = find_duplicate_groups(s)
        result = dedupe_group(s, groups[0])
        s.commit()

        assert result.company_name_changed is False
        rows = s.query(AuditLog).filter(AuditLog.action == "rate_dedupe_label_normalized").all()
        assert rows == []
        s.close()


# ── Rule C: late_cancellation_rate carry-over ───────────────────────────────

class TestRuleCLateCancellationCarry:
    def setup_method(self):
        _wipe()

    def teardown_method(self):
        _wipe()

    def test_carried_from_highest_id_loser_on_tie(self):
        s = _db()
        _seed_service(s, 1, "acumen", "FirstAlt", "Route A", "40.00")  # survivor, no LC rate
        _seed_service(s, 2, "acumen", "Acumen International", "Route A", "40.00", late_cancellation_rate="20.00")
        _seed_service(s, 3, "acumen", "Acumen", "Route A", "40.00", late_cancellation_rate="25.00")
        s.commit()

        groups = find_duplicate_groups(s)
        result = dedupe_group(s, groups[0])
        s.commit()

        assert result.survivor_id == 1
        assert result.late_cancellation_carried is True
        # Highest LOSER ID wins the tie (id=3), not the highest rate value.
        assert result.late_cancellation_source_id == 3
        assert result.late_cancellation_rate == Decimal("25.00")

        survivor = s.query(ZRateService).filter(ZRateService.z_rate_service_id == 1).one()
        assert survivor.late_cancellation_rate == Decimal("25.00")

        rows = s.query(AuditLog).filter(AuditLog.action == "rate_dedupe_late_cancellation_carried").all()
        assert len(rows) == 1
        assert rows[0].after_value["carried_from"] == 3
        s.close()

    def test_not_overwritten_when_survivor_already_has_one(self):
        s = _db()
        _seed_service(s, 1, "acumen", "FirstAlt", "Route A", "40.00", late_cancellation_rate="22.00")
        _seed_service(s, 2, "acumen", "Acumen International", "Route A", "40.00", late_cancellation_rate="99.00")
        s.commit()

        groups = find_duplicate_groups(s)
        result = dedupe_group(s, groups[0])
        s.commit()

        assert result.late_cancellation_carried is False
        survivor = s.query(ZRateService).filter(ZRateService.z_rate_service_id == 1).one()
        assert survivor.late_cancellation_rate == Decimal("22.00")  # untouched
        s.close()


# ── Rule D: zero-rate survivor rescue ───────────────────────────────────────

class TestRuleDZeroRateRescue:
    def setup_method(self):
        _wipe()
        s = _db()
        _seed_person(s)
        s.commit()
        s.close()

    def teardown_method(self):
        _wipe()

    def test_zero_rate_survivor_adopts_highest_nonzero_loser_rate(self):
        s = _db()
        _seed_service(s, 1, "acumen", "FirstAlt", "Route A", "0.00")  # stub, survivor by tie
        _seed_service(s, 2, "acumen", "Acumen International", "Route A", "38.00")
        _seed_service(s, 3, "acumen", "Acumen", "Route A", "42.00")
        s.commit()  # no rides at all -> last-paid signal is "none"

        groups = find_duplicate_groups(s)
        result = dedupe_group(s, groups[0])
        s.commit()

        assert result.survivor_id == 1
        assert result.confidence == "none"
        assert result.zero_rate_rescued is True
        assert result.zero_rate_rescued_from_id == 3  # highest non-zero rate wins
        assert result.survivor_default_rate == Decimal("42.00")

        survivor = s.query(ZRateService).filter(ZRateService.z_rate_service_id == 1).one()
        assert survivor.default_rate == Decimal("42.00")

        rows = s.query(AuditLog).filter(AuditLog.action == "rate_dedupe_zero_rate_rescued").all()
        assert len(rows) == 1
        assert rows[0].after_value["adopted_from"] == 3
        assert rows[0].after_value["default_rate"] == "42.00"
        s.close()

    def test_stub_never_wins_once_last_paid_rate_is_confirmed(self):
        """If the last-paid signal IS confirmed, the survivor is no longer
        zero by the time Rule D would run, so Rule D never fires."""
        s = _db()
        _seed_batch(s, 1)
        _seed_service(s, 1, "acumen", "FirstAlt", "Route A", "0.00")
        _seed_service(s, 2, "acumen", "Acumen International", "Route A", "38.00")
        _seed_ride(s, 1, 1, "acumen", "Route A", "55.00", z_rate_source="service_default")
        _seed_ride(s, 1, 1, "acumen", "Route A", "55.00", z_rate_source="service_default")
        s.commit()

        groups = find_duplicate_groups(s)
        result = dedupe_group(s, groups[0])
        s.commit()

        # Paid $55 matches NEITHER copy (0 / 38) → treated as a one-batch or hand
        # fix, not adopted. Rule D then rescues the stub with the loser's $38.
        assert result.confidence == "confirmed"
        assert result.rate_changed is False
        assert result.survivor_default_rate == Decimal("38.00")
        assert result.zero_rate_rescued is True
        s.close()

    def test_confirmed_paid_rate_that_matches_a_copy_is_adopted_over_a_stub(self):
        """Copies disagree (0 vs 38), drivers were paid 38 twice → adopt 38 via
        the last-paid rule itself; Rule D has nothing left to do."""
        s = _db()
        _seed_batch(s, 1)
        _seed_service(s, 1, "acumen", "FirstAlt", "Route A", "0.00")
        _seed_service(s, 2, "acumen", "Acumen International", "Route A", "38.00")
        _seed_ride(s, 1, 1, "acumen", "Route A", "38.00", z_rate_source="service_default")
        _seed_ride(s, 1, 1, "acumen", "Route A", "38.00", z_rate_source="service_default")
        s.commit()

        groups = find_duplicate_groups(s)
        result = dedupe_group(s, groups[0])
        s.commit()

        assert result.rate_changed is True
        assert result.survivor_default_rate == Decimal("38.00")
        assert result.zero_rate_rescued is False
        s.close()

    def test_same_rate_copies_never_change_rate_even_if_paid_differently(self):
        """Both copies say 38 but the latest batch paid 40 on two rides (a
        'this batch only' fix) → the permanent rate stays 38."""
        s = _db()
        _seed_batch(s, 1)
        _seed_service(s, 1, "acumen", "FirstAlt", "Route A", "38.00")
        _seed_service(s, 2, "acumen", "Acumen International", "Route A", "38.00")
        _seed_ride(s, 1, 1, "acumen", "Route A", "40.00", z_rate_source="service_default")
        _seed_ride(s, 1, 1, "acumen", "Route A", "40.00", z_rate_source="service_default")
        s.commit()

        groups = find_duplicate_groups(s)
        result = dedupe_group(s, groups[0])
        s.commit()

        assert result.rate_changed is False
        assert result.survivor_default_rate == Decimal("38.00")
        s.close()

    def test_normalize_all_active_labels_relabels_singletons(self):
        from backend.services.rate_service_dedupe import normalize_all_active_labels
        s = _db()
        _seed_batch(s, 1)  # batch label is what the helper seeds for source acumen
        _seed_service(s, 1, "acumen", "Acumen International", "Only Route", "38.00")
        s.commit()
        changed = normalize_all_active_labels(s)
        s.commit()
        assert len(changed) == 1
        row = s.get(ZRateService, 1)
        assert row.company_name == s.query(PayrollBatch).filter_by(source="acumen").first().company_name
        assert normalize_all_active_labels(s) == []
        s.close()

    def test_no_rescue_when_no_loser_has_a_nonzero_rate(self):
        s = _db()
        _seed_service(s, 1, "acumen", "FirstAlt", "Route A", "0.00")
        _seed_service(s, 2, "acumen", "Acumen International", "Route A", "0.00")
        s.commit()

        groups = find_duplicate_groups(s)
        result = dedupe_group(s, groups[0])
        s.commit()

        assert result.zero_rate_rescued is False
        survivor = s.query(ZRateService).filter(ZRateService.z_rate_service_id == 1).one()
        assert survivor.default_rate == Decimal("0.00")
        s.close()


# ── Migration s14: the Postgres-only expression index SQL (Rule A) ─────────
# regexp_replace has no SQLite equivalent, so this doesn't execute the SQL —
# it asserts the exact text the migration hands to op.execute(), which is
# built once as a module-level constant and passed through verbatim.

class TestMigrationS14CanonicalIndexSQL:
    def _load_migration_module(self):
        import importlib.util

        migration_path = (
            Path(__file__).resolve().parents[2]
            / "backend" / "alembic" / "versions" / "s14_dedupe_z_rate_service.py"
        )
        spec = importlib.util.spec_from_file_location("s14_dedupe_z_rate_service_test_load", migration_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_create_sql_is_partial_expression_unique_index(self):
        mod = self._load_migration_module()
        sql = mod._CANON_INDEX_CREATE_SQL
        assert mod._CANON_INDEX_NAME == CANONICAL_NAME_INDEX_NAME
        assert "CREATE UNIQUE INDEX IF NOT EXISTS" in sql
        assert CANONICAL_NAME_INDEX_NAME in sql
        assert "z_rate_service" in sql
        assert "regexp_replace(service_name" in sql
        assert "lower(" in sql
        assert "WHERE active = true" in sql

    def test_drop_sql_targets_the_same_index_name(self):
        mod = self._load_migration_module()
        assert mod._CANON_INDEX_DROP_SQL == f"DROP INDEX IF EXISTS {CANONICAL_NAME_INDEX_NAME}"

    def test_upgrade_emits_create_sql_via_op_execute(self):
        """Runs the real upgrade() against a throwaway SQLite engine, with
        op.execute intercepted ONLY for the Postgres-only regexp_replace
        statement (SQLite has no such function) — everything else
        (add_column, the dedupe itself, the uq_z_rate_service_scope
        partial-index conversion) executes for real."""
        from unittest.mock import patch

        mod = self._load_migration_module()

        temp_engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )

        @event.listens_for(temp_engine, "connect")
        def _register_now_temp(dbapi_conn, _rec):
            dbapi_conn.create_function("NOW", 0, lambda: datetime.now(timezone.utc).isoformat())

        Base.metadata.create_all(temp_engine)

        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        conn = temp_engine.connect()
        ctx = MigrationContext.configure(conn)

        captured_sql: list[str] = []
        real_execute = mod.op.execute

        def _spy_execute(clause, *a, **kw):
            text_value = str(getattr(clause, "text", clause))
            if "regexp_replace" in text_value:
                captured_sql.append(text_value)
                return None  # never actually run on SQLite
            return real_execute(clause, *a, **kw)

        with Operations.context(ctx):
            with patch.object(mod.op, "execute", side_effect=_spy_execute):
                mod.upgrade()
        conn.commit()
        conn.close()

        assert len(captured_sql) == 1
        assert "regexp_replace(service_name" in captured_sql[0]
        assert CANONICAL_NAME_INDEX_NAME in captured_sql[0]

        # The rest of upgrade() (add_column, dedupe_all, scope-index
        # conversion) really did run against SQLite.
        from sqlalchemy import inspect as sa_inspect
        cols = {c["name"] for c in sa_inspect(temp_engine).get_columns("z_rate_service")}
        assert "merged_into_id" in cols

    def test_downgrade_reactivates_soft_merged_losers(self):
        """Downgrade's SQL (UPDATE ... SET active=true, DROP INDEX IF EXISTS)
        has no Postgres-only pieces, so this runs for real against SQLite —
        no mocking needed, unlike the upgrade() test above."""
        from unittest.mock import patch
        from sqlalchemy import inspect as sa_inspect

        mod = self._load_migration_module()

        temp_engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )

        @event.listens_for(temp_engine, "connect")
        def _register_now_temp2(dbapi_conn, _rec):
            dbapi_conn.create_function("NOW", 0, lambda: datetime.now(timezone.utc).isoformat())

        Base.metadata.create_all(temp_engine)
        TempSession = sessionmaker(bind=temp_engine)

        s = TempSession()
        _seed_service(s, 1, "acumen", "FirstAlt", "Route A", "40.00")
        _seed_service(s, 2, "acumen", "Acumen International", "Route A", "45.00")
        s.commit()
        s.close()

        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        real_execute = mod.op.execute

        def _skip_regexp(clause, *a, **kw):
            text_value = str(getattr(clause, "text", clause))
            if "regexp_replace" in text_value:
                return None
            return real_execute(clause, *a, **kw)

        conn = temp_engine.connect()
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            with patch.object(mod.op, "execute", side_effect=_skip_regexp):
                mod.upgrade()
        conn.commit()  # Core-level commit — the ORM session inside upgrade()
        conn.close()   # only participates in this connection's transaction

        s = TempSession()
        merged = s.query(ZRateService).filter(ZRateService.z_rate_service_id == 2).one()
        assert merged.active is False
        assert merged.merged_into_id == 1
        s.close()

        # Downgrade — fully real, no mocking (no regexp_replace involved).
        conn = temp_engine.connect()
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            mod.downgrade()
        conn.commit()

        # downgrade() drops merged_into_id, so the ORM model (which still
        # declares that column) can no longer SELECT this table — check via
        # a raw query on the same connection instead.
        from sqlalchemy import text as _text
        row = conn.execute(
            _text("SELECT active FROM z_rate_service WHERE z_rate_service_id = 2")
        ).one()
        assert bool(row[0]) is True

        cols_after = {c["name"] for c in sa_inspect(temp_engine).get_columns("z_rate_service")}
        assert "merged_into_id" not in cols_after
        conn.close()
        s.close()
