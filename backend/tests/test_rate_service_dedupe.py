"""
Unit tests for backend/services/rate_service_dedupe.py — the merge logic
migration s14 uses to collapse duplicate z_rate_service rows down to one
row per (source, service_name).

DB strategy: in-memory SQLite, same pattern as test_paychex_api_rail.py /
test_remove_ride.py (BigInteger PKs -> Integer, DATERANGE -> Text, NOW()
server_defaults relaxed).

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

from backend.db.models import Base, PayrollBatch, Person, Ride, ZRateOverride, ZRateService  # noqa: E402

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

# Drop the post-migration unique index from metadata so these tests can seed
# the PRE-migration duplicate rows the dedupe logic is meant to clean up —
# that's exactly the state migration s14 runs against in production.
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
    choose_survivor,
    dedupe_all,
    dedupe_group,
    find_duplicate_groups,
    ride_counts_for,
)

_NOW = datetime.now(timezone.utc)


def _db():
    return _SessionFactory()


def _wipe():
    s = _db()
    try:
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


def _seed_service(s, service_id: int, source: str, company_name: str, service_name: str, default_rate: str) -> ZRateService:
    svc = ZRateService(
        z_rate_service_id=service_id,
        source=source,
        company_name=company_name,
        service_key=f"svc_key_{service_id}",
        service_name=service_name,
        currency="USD",
        default_rate=Decimal(default_rate),
        active=True,
        created_at=_NOW,
    )
    s.add(svc)
    s.flush()
    return svc


def _seed_ride(s, ride_id: int, batch_id: int, person_id: int, source: str, service_name: str, z_rate_service_id: int | None) -> Ride:
    r = Ride(
        ride_id=ride_id,
        payroll_batch_id=batch_id,
        person_id=person_id,
        source=source,
        source_ref=f"test-src-{ride_id}",
        service_name=service_name,
        z_rate=Decimal("100.00"),
        z_rate_source="service_default",
        z_rate_service_id=z_rate_service_id,
        gross_pay=Decimal("150.00"),
        net_pay=Decimal("150.00"),
        miles=Decimal("0.000"),
        deduction=Decimal("0"),
        spiff=Decimal("0"),
        ride_start_ts=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    s.add(r)
    s.flush()
    return r


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

        groups = find_duplicate_groups(s)
        assert groups == []
        s.close()

    def test_duplicate_group_found(self):
        s = _db()
        _seed_service(s, 1, "acumen", "FirstAlt", "Route A", "40.00")
        _seed_service(s, 2, "acumen", "Acumen International", "Route A", "45.00")
        s.commit()

        groups = find_duplicate_groups(s)
        assert len(groups) == 1
        ids = sorted(row.z_rate_service_id for row in groups[0])
        assert ids == [1, 2]
        s.close()

    def test_different_source_not_grouped_together(self):
        s = _db()
        _seed_service(s, 1, "acumen", "FirstAlt", "Route A", "40.00")
        _seed_service(s, 2, "maz", "EverDriven", "Route A", "60.00")
        s.commit()

        groups = find_duplicate_groups(s)
        assert groups == []
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
        # 2 rides on svc_b, 1 ride on svc_a
        _seed_ride(s, 101, 1, 1, "acumen", "Route A", 1)
        _seed_ride(s, 102, 1, 1, "acumen", "Route A", 2)
        _seed_ride(s, 103, 1, 1, "acumen", "Route A", 2)
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


class TestDedupeGroup:
    def setup_method(self):
        _wipe()

    def teardown_method(self):
        _wipe()

    def test_repoints_rides_and_overrides_and_deletes_losers(self):
        s = _db()
        _seed_person(s)
        _seed_batch(s, 1)
        _seed_service(s, 1, "acumen", "FirstAlt", "Route A", "40.00")
        _seed_service(s, 2, "acumen", "Acumen International", "Route A", "45.00")
        # svc 2 has more rides -> survivor
        _seed_ride(s, 101, 1, 1, "acumen", "Route A", 1)
        _seed_ride(s, 102, 1, 1, "acumen", "Route A", 2)
        _seed_ride(s, 103, 1, 1, "acumen", "Route A", 2)
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
        assert result.survivor_default_rate == Decimal("45.00")
        assert result.rides_repointed == 1  # only ride 101 was pointed at the loser (id 1)
        assert result.overrides_repointed == 1

        # Loser row is gone
        assert s.query(ZRateService).filter(ZRateService.z_rate_service_id == 1).one_or_none() is None
        # Survivor untouched (own rate kept)
        survivor = s.query(ZRateService).filter(ZRateService.z_rate_service_id == 2).one()
        assert survivor.default_rate == Decimal("45.00")
        # All rides now point at the survivor
        ride_ids = {r.z_rate_service_id for r in s.query(Ride).all()}
        assert ride_ids == {2}
        # Override repointed, not cascade-deleted
        ov_after = s.query(ZRateOverride).one()
        assert ov_after.z_rate_service_id == 2
        s.close()


class TestDedupeAll:
    def setup_method(self):
        _wipe()

    def teardown_method(self):
        _wipe()

    def test_merges_multiple_groups(self):
        s = _db()
        _seed_person(s)
        _seed_batch(s, 1)
        # Group 1: Route A (acumen) — 2 dupes
        _seed_service(s, 1, "acumen", "FirstAlt", "Route A", "40.00")
        _seed_service(s, 2, "acumen", "Acumen International", "Route A", "45.00")
        # Group 2: Route B (maz) — 3 dupes, same rate on all (still a duplicate group)
        _seed_service(s, 3, "maz", "EverDriven", "Route B", "60.00")
        _seed_service(s, 4, "maz", "everDriven", "Route B", "60.00")
        _seed_service(s, 5, "maz", "Maz Services", "Route B", "60.00")
        # Not a duplicate — untouched
        _seed_service(s, 6, "acumen", "FirstAlt", "Route C", "70.00")
        s.commit()

        results = dedupe_all(s)
        s.commit()

        assert len(results) == 2
        remaining = s.query(ZRateService).all()
        assert len(remaining) == 3  # one survivor per group + untouched Route C
        remaining_names = sorted((r.source, r.service_name) for r in remaining)
        assert remaining_names == [("acumen", "Route A"), ("acumen", "Route C"), ("maz", "Route B")]
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

        remaining = s.query(ZRateService).all()
        assert len(remaining) == 1
        s.close()

    def test_no_duplicates_at_all_returns_empty(self):
        s = _db()
        _seed_service(s, 1, "acumen", "FirstAlt", "Route A", "40.00")
        s.commit()

        results = dedupe_all(s)
        assert results == []
        s.close()
