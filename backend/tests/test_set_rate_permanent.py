"""
Tests for the "Permanent" rate-edit bug fix (2026-09-23).

Endpoint under test:
  POST /api/data/rides/{ride_id}/set-rate   with update_default=true

Also covers the corresponding lookup in backend/services/recalculate.py —
next week's payroll must read the same row this endpoint just wrote.

Bug being fixed: z_rate_service carries duplicate rows per (source,
service_name) under different company_name spellings ("FirstAlt" vs "Acumen
International" vs "Acumen"; "EverDriven" vs "everDriven"). The old set-rate
code did `ZRateService.query.filter(service_name == X).first()` — company_name
was not part of the key at all, so on a DB with duplicates it could update a
row payroll never reads. This test creates two duplicate rows on purpose and
proves the permanent edit updates the row `recalc`'s lookup actually returns.

DB strategy: same in-memory SQLite pattern as test_remove_ride.py /
test_manual_adjustments.py.

Run in isolation:
    PYTHONPATH=. python3 -m pytest backend/tests/test_set_rate_permanent.py -q --no-header -p no:cacheprovider
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

os.environ.setdefault("ZPAY_SECRET_KEY", "test-secret-key-set-rate-permanent-tests-long-enough")
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

# Drop the post-migration unique index — these tests simulate the
# PRE-migration state (duplicate rows still present) on purpose.
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

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402
from backend.db import get_db  # noqa: E402
from backend.middleware.auth import COOKIE_NAME, create_session  # noqa: E402
from backend.services.recalculate import _resolve_rate_for_ride_local  # noqa: E402


def _override_get_db():
    db = _SessionFactory()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db

_SESSION_COOKIE = create_session(
    username="admin_test",
    display_name="Admin Test",
    color="#333",
    initials="AT",
    role="admin",
)
_AUTH = {COOKIE_NAME: _SESSION_COOKIE}

client = TestClient(app, raise_server_exceptions=True)

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


def _seed_batch(s, batch_id: int = 1, source: str = "acumen", company_name: str = "FirstAlt") -> PayrollBatch:
    b = PayrollBatch(
        payroll_batch_id=batch_id,
        source=source,
        company_name=company_name,
        batch_ref="W-test",
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
    s, service_id: int, source: str, company_name: str, service_name: str, default_rate: str,
    active: bool = True, merged_into_id: int | None = None,
) -> ZRateService:
    svc = ZRateService(
        z_rate_service_id=service_id,
        source=source,
        company_name=company_name,
        service_key=f"svc_key_{service_id}",
        service_name=service_name,
        currency="USD",
        default_rate=Decimal(default_rate),
        active=active,
        merged_into_id=merged_into_id,
        created_at=_NOW,
    )
    s.add(svc)
    s.flush()
    return svc


def _seed_ride(
    s,
    ride_id: int,
    batch_id: int,
    person_id: int,
    source: str,
    service_name: str,
    z_rate_service_id: int | None,
    z_rate: str = "40.00",
) -> Ride:
    r = Ride(
        ride_id=ride_id,
        payroll_batch_id=batch_id,
        person_id=person_id,
        source=source,
        source_ref=f"test-src-{ride_id}",
        service_name=service_name,
        z_rate=Decimal(z_rate),
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


class TestSetRatePermanentAgainstDuplicateRows:
    """The core regression: 'Permanent' must update the row payroll reads,
    even when duplicate rows exist for the same (source, service_name)."""

    def setup_method(self):
        _wipe()
        s = _db()
        _seed_person(s)
        _seed_batch(s)
        # Duplicate z_rate_service rows for the same (source, service_name)
        # under different company_name spellings — the exact bug scenario.
        self.svc_firstalt = _seed_service(s, 1, "acumen", "FirstAlt", "Route A", "40.00")
        self.svc_acumen_intl = _seed_service(s, 2, "acumen", "Acumen International", "Route A", "40.00")
        # The ride is linked to the "Acumen International" row (id=2) —
        # that's the row payroll actually reads for this ride.
        self.ride = _seed_ride(s, 1001, 1, 1, "acumen", "Route A", z_rate_service_id=2, z_rate="40.00")
        s.commit()
        s.close()

    def teardown_method(self):
        _wipe()

    def test_permanent_edit_updates_the_row_payroll_reads(self):
        resp = client.post(
            "/api/data/rides/1001/set-rate",
            json={"rate": 55.00, "update_default": True},
            cookies=_AUTH,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ok"] is True
        assert body["service_updated"] is True
        assert body["z_rate"] == 55.00

        s = _db()
        try:
            # The ride's own z_rate was updated.
            ride = s.query(Ride).filter(Ride.ride_id == 1001).one()
            assert float(ride.z_rate) == 55.00
            assert ride.z_rate_source == "manual"
            assert ride.z_rate_service_id == 2  # still points at its original row

            # The row the ride was actually linked to (id=2, "Acumen
            # International") got the new default_rate — not the other
            # duplicate (id=1, "FirstAlt") that payroll never reads for
            # this ride.
            svc_2 = s.query(ZRateService).filter(ZRateService.z_rate_service_id == 2).one()
            svc_1 = s.query(ZRateService).filter(ZRateService.z_rate_service_id == 1).one()
            assert float(svc_2.default_rate) == 55.00
            assert float(svc_1.default_rate) == 40.00  # untouched duplicate

            # Next week's payroll pricing (recalculate.py) resolves the same
            # row and returns the NEW rate — this is the actual bug: before
            # the fix, recalc's lookup could pick either duplicate.
            # ride_date=None here on purpose — the DATERANGE `@>` override
            # lookup this function does when a date is given is Postgres-only
            # and unrelated to what this test is proving (the SERVICE_DEFAULT
            # branch resolving the correct, just-updated row).
            rate, rate_source, svc_id, _ov_id = _resolve_rate_for_ride_local(
                s,
                source="acumen",
                company_name="Acumen International",
                service_name="Route A",
                ride_date=None,
            )
        finally:
            s.close()

        assert svc_id == 2
        assert rate == Decimal("55.00")
        assert rate_source == "SERVICE_DEFAULT"

    def test_permanent_edit_falls_back_to_source_and_service_name_when_ride_has_no_service_id(self):
        """A ride with z_rate_service_id unset (e.g. an old/unmatched ride)
        must still resolve via (source, service_name), not `.first()` by
        name alone, and must not blow up on the duplicate rows."""
        s = _db()
        _seed_ride(s, 1002, 1, 1, "acumen", "Route A", z_rate_service_id=None, z_rate="0.00")
        s.commit()
        s.close()

        resp = client.post(
            "/api/data/rides/1002/set-rate",
            json={"rate": 60.00, "update_default": True},
            cookies=_AUTH,
        )
        assert resp.status_code == 200, resp.text

        s = _db()
        try:
            ride = s.query(Ride).filter(Ride.ride_id == 1002).one()
            # Ride is now repointed at whichever duplicate row was resolved —
            # never left dangling, never crashed on multiple matches.
            assert ride.z_rate_service_id in (1, 2)
            svc = s.query(ZRateService).filter(ZRateService.z_rate_service_id == ride.z_rate_service_id).one()
            assert float(svc.default_rate) == 60.00
        finally:
            s.close()

    def test_locked_ride_rejects_rate_change(self):
        s = _db()
        ride = s.query(Ride).filter(Ride.ride_id == 1001).one()
        ride.z_rate_locked_at = _NOW
        s.commit()
        s.close()

        resp = client.post(
            "/api/data/rides/1001/set-rate",
            json={"rate": 99.00, "update_default": True},
            cookies=_AUTH,
        )
        assert resp.status_code == 409, resp.text

    def test_nonexistent_ride_returns_404(self):
        resp = client.post(
            "/api/data/rides/9999/set-rate",
            json={"rate": 10.00, "update_default": True},
            cookies=_AUTH,
        )
        assert resp.status_code == 404, resp.text

    def test_missing_rate_returns_400(self):
        resp = client.post(
            "/api/data/rides/1001/set-rate",
            json={"update_default": True},
            cookies=_AUTH,
        )
        assert resp.status_code == 400, resp.text


class TestSetRateCreatesNewServiceRow:
    """update_default=true with no matching ZRateService row at all creates
    one with a valid, unique service_key (the old code omitted service_key,
    which is NOT NULL + unique — a latent insert bug fixed alongside this)."""

    def setup_method(self):
        _wipe()
        s = _db()
        _seed_person(s)
        _seed_batch(s)
        _seed_ride(s, 2001, 1, 1, "acumen", "Brand New Route", z_rate_service_id=None, z_rate="0.00")
        s.commit()
        s.close()

    def teardown_method(self):
        _wipe()

    def test_creates_service_row_with_service_key(self):
        resp = client.post(
            "/api/data/rides/2001/set-rate",
            json={"rate": 33.00, "update_default": True},
            cookies=_AUTH,
        )
        assert resp.status_code == 200, resp.text

        s = _db()
        try:
            ride = s.query(Ride).filter(Ride.ride_id == 2001).one()
            assert ride.z_rate_service_id is not None
            svc = s.query(ZRateService).filter(ZRateService.z_rate_service_id == ride.z_rate_service_id).one()
            assert svc.source == "acumen"
            assert svc.service_name == "Brand New Route"
            assert float(svc.default_rate) == 33.00
            assert svc.service_key  # non-empty, satisfies NOT NULL + unique
        finally:
            s.close()


class TestSetRateAndRecalculateIgnoreInactiveRows:
    """Migration s14 soft-merges duplicates (active=false + merged_into_id,
    never deleted) — every lookup this repo owns must skip inactive rows."""

    def setup_method(self):
        _wipe()
        s = _db()
        _seed_person(s)
        _seed_batch(s)
        # id=1 is the ACTIVE survivor; id=2 is a soft-merged-away loser that
        # still exists (never deleted) and still shares (source, service_name).
        _seed_service(s, 1, "acumen", "FirstAlt", "Route A", "55.00", active=True)
        _seed_service(s, 2, "acumen", "Acumen International", "Route A", "40.00", active=False, merged_into_id=1)
        s.commit()
        s.close()

    def teardown_method(self):
        _wipe()

    def test_set_rate_falls_through_when_ride_points_at_an_inactive_row(self):
        """A ride still pointing at the now-inactive loser (stale FK, e.g.
        pre-migration data) must resolve via (source, service_name) to the
        ACTIVE survivor instead of writing to the dead row."""
        s = _db()
        _seed_ride(s, 3001, 1, 1, "acumen", "Route A", z_rate_service_id=2, z_rate="40.00")
        s.commit()
        s.close()

        resp = client.post(
            "/api/data/rides/3001/set-rate",
            json={"rate": 60.00, "update_default": True},
            cookies=_AUTH,
        )
        assert resp.status_code == 200, resp.text

        s = _db()
        try:
            ride = s.query(Ride).filter(Ride.ride_id == 3001).one()
            # Repointed at the ACTIVE survivor, not left on the inactive row.
            assert ride.z_rate_service_id == 1

            active_svc = s.query(ZRateService).filter(ZRateService.z_rate_service_id == 1).one()
            inactive_svc = s.query(ZRateService).filter(ZRateService.z_rate_service_id == 2).one()
            assert float(active_svc.default_rate) == 60.00  # updated
            assert float(inactive_svc.default_rate) == 40.00  # untouched, still inactive
            assert inactive_svc.active is False
        finally:
            s.close()

    def test_recalculate_lookup_ignores_inactive_duplicate(self):
        s = _db()
        try:
            rate, rate_source, svc_id, _ov_id = _resolve_rate_for_ride_local(
                s,
                source="acumen",
                company_name="Acumen International",  # the INACTIVE row's own label
                service_name="Route A",
                ride_date=None,
            )
        finally:
            s.close()

        # Must resolve to the ACTIVE survivor (id=1, rate 55.00), never the
        # inactive row (id=2, rate 40.00) even though its company_name
        # label is what was passed in.
        assert svc_id == 1
        assert rate == Decimal("55.00")
        assert rate_source == "SERVICE_DEFAULT"
