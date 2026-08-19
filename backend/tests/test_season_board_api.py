"""
API contract tests for backend/routes/season_board.py (S10).

Full in-memory SQLite via TestClient + dependency_overrides, mirroring the
established pattern in test_assignment_routes.py (global metadata patches
for SQLite compatibility — BigInteger PKs, DATERANGE, NOW() defaults).

Run in isolation:
    PYTHONPATH=. pytest backend/tests/test_season_board_api.py -x -v
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import BigInteger, Integer, Text, create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault(
    "ZPAY_SECRET_KEY",
    "test-secret-key-for-season-board-routes-tests-long-enough",
)
os.environ.setdefault("DATABASE_URL", "sqlite://")  # silenced by get_db override

from backend.db.models import Base, ZRateOverride  # noqa: E402

# ── Metadata patches (same three as test_assignment_routes.py) ──────────────
Base.metadata.tables["z_rate_override"].c["effective_during"].type = Text()

for _tbl in Base.metadata.tables.values():
    for _col in _tbl.columns:
        if _col.primary_key and isinstance(_col.type, BigInteger):
            _col.type = Integer()

for _tbl in Base.metadata.tables.values():
    for _col in _tbl.columns:
        if _col.server_default is not None:
            _sd = _col.server_default
            try:
                _arg = _sd.arg.text if hasattr(_sd, "arg") and hasattr(_sd.arg, "text") else ""
            except Exception:
                _arg = ""
            if "NOW()" in _arg:
                _col.nullable = True
                _col.server_default = None

_engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
)


@event.listens_for(_engine, "connect")
def _register_now(dbapi_conn, _rec):
    dbapi_conn.create_function("NOW", 0, lambda: datetime.now(timezone.utc).isoformat())


Base.metadata.create_all(_engine)

_SessionFactory = sessionmaker(bind=_engine, autoflush=False, autocommit=False)

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402
from backend.db import get_db  # noqa: E402
from backend.db.models import (  # noqa: E402
    DriverLoop,
    Person,
    RideIntake,
    School,
    SeasonRide,
)
from backend.middleware.auth import COOKIE_NAME, create_session  # noqa: E402
from backend.services.inbox_intake import pool_taken_intake  # noqa: E402


def _override_get_db():
    db = _SessionFactory()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db

_SESSION_COOKIE = create_session(
    username="testadmin", display_name="Test Admin", color="#333", initials="TA", role="admin",
)
_AUTH = {COOKIE_NAME: _SESSION_COOKIE}

client = TestClient(app, raise_server_exceptions=True)

SEASON = "2026-27"


def _db():
    return _SessionFactory()


def _wipe():
    sess = _db()
    try:
        sess.query(SeasonRide).delete(synchronize_session=False)
        sess.query(DriverLoop).delete(synchronize_session=False)
        sess.query(School).delete(synchronize_session=False)
        sess.query(RideIntake).delete(synchronize_session=False)
        sess.query(Person).delete(synchronize_session=False)
        sess.commit()
    finally:
        sess.close()


@pytest.fixture(autouse=True)
def _clean_db():
    _wipe()
    yield
    _wipe()


def _seed_person(sess, **overrides) -> Person:
    fields = {"full_name": "Test Driver", "active": True, "status": "active", **overrides}
    p = Person(**fields)
    sess.add(p)
    sess.flush()
    sess.commit()
    return p


def _seed_school(sess, **overrides) -> School:
    fields = {"name": overrides.pop("name", "test school"), "display_name": "Test School", **overrides}
    s = School(**fields)
    sess.add(s)
    sess.flush()
    sess.commit()
    return s


def _seed_ride(sess, **overrides) -> SeasonRide:
    fields = {
        "season": SEASON,
        "source": "firstalt",
        "route_school": "Test School",
        "route_direction": "IB",
        "route_number": "01",
        "route_is_odt": False,
        "status": "unassigned",
        "requires": {},
        **overrides,
    }
    r = SeasonRide(**fields)
    sess.add(r)
    sess.flush()
    sess.commit()
    return r


# ── GET /season/board ────────────────────────────────────────────────────────

def test_board_grouping_adjacency_filters_and_unplaced():
    sess = _db()
    school_lw = _seed_school(sess, name="lake wa es", display_name="Lake WA ES", district="Lake Washington")
    school_kent = _seed_school(sess, name="kent es", display_name="Kent ES", district="Kent")
    driver = _seed_person(sess, full_name="Assigned Driver")

    r1 = _seed_ride(
        sess, school_id=school_lw.school_id, route_school="Lake WA ES", route_number="01", route_direction="IB",
        pickup_city="Kirkland", dropoff_city="Redmond", pickup_time="07:45", dropoff_time="08:15",
    )
    r2 = _seed_ride(
        sess, school_id=school_lw.school_id, route_school="Lake WA ES", route_number="01", route_direction="OB",
        pickup_city="Redmond", dropoff_city="Kirkland", pickup_time="15:00", dropoff_time="15:30",
    )
    r3 = _seed_ride(
        sess, school_id=school_lw.school_id, route_school="Lake WA ES", route_number="02", route_direction="IB",
        pickup_city="Kirkland", dropoff_city=None, pickup_time="07:00", dropoff_time=None,
    )
    r4 = _seed_ride(
        sess, school_id=school_kent.school_id, route_school="Kent ES", route_number="01", route_direction="IB",
        pickup_city="Kent", dropoff_city="Auburn", pickup_time="07:30", dropoff_time="08:00",
        days="M,W,F", status="assigned", assigned_person_id=driver.person_id,
    )
    r1_id, r2_id, r3_id, r4_id = (
        r1.season_ride_id, r2.season_ride_id, r3.season_ride_id, r4.season_ride_id,
    )
    driver_id = driver.person_id
    sess.close()

    # No filters.
    resp = client.get("/api/data/season/board", params={"season": SEASON}, cookies=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["stats"] == {"total": 4, "assigned": 1, "unassigned": 3, "needs_info": 1}
    assert body["districts"] == ["Kent", "Lake Washington"]

    ids_in_unplaced = {r["season_ride_id"] for r in body["unplaced"]}
    assert ids_in_unplaced == {r3_id}
    assert body["unplaced"][0]["needs"]["address"] is True

    corridor_keys = [(c["pickup_city"], c["dropoff_city"]) for c in body["corridors"]]
    assert ("Kent", "Auburn") in corridor_keys
    kw_idx = corridor_keys.index(("Kirkland", "Redmond"))
    wk_idx = corridor_keys.index(("Redmond", "Kirkland"))
    assert wk_idx == kw_idx + 1  # opposite corridor immediately follows

    kirkland_corridor = body["corridors"][kw_idx]
    assert {r["season_ride_id"] for r in kirkland_corridor["rides"]} == {r1_id}
    assigned_ride = next(
        r for c in body["corridors"] for r in c["rides"] if r["season_ride_id"] == r4_id
    )
    assert assigned_ride["assigned_person"] == {"person_id": driver_id, "name": "Assigned Driver"}

    # District filter.
    resp = client.get(
        "/api/data/season/board", params={"season": SEASON, "district": "Kent"}, cookies=_AUTH,
    )
    body = resp.json()
    assert body["stats"]["total"] == 1
    assert [c["pickup_city"] for c in body["corridors"]] == ["Kent"]

    # day_part filter (PM = OB only -> r2).
    resp = client.get(
        "/api/data/season/board", params={"season": SEASON, "day_part": "PM"}, cookies=_AUTH,
    )
    body = resp.json()
    assert body["stats"]["total"] == 1
    all_ride_ids = {r["season_ride_id"] for c in body["corridors"] for r in c["rides"]}
    assert all_ride_ids == {r2_id}

    # weekday filter (r4 is M/W/F only -> excluded on Tuesday).
    resp = client.get(
        "/api/data/season/board", params={"season": SEASON, "weekday": "T"}, cookies=_AUTH,
    )
    body = resp.json()
    assert body["stats"]["total"] == 3
    assert body["stats"]["needs_info"] == 1


def test_board_rejects_bad_day_part():
    resp = client.get(
        "/api/data/season/board", params={"season": SEASON, "day_part": "NOON"}, cookies=_AUTH,
    )
    assert resp.status_code == 400


# ── POST /season/import ──────────────────────────────────────────────────────

def test_import_from_intake_pools_and_creates_school():
    sess = _db()
    intake = RideIntake(
        raw_text="raw",
        parsed={
            "school": "Brand New MS",
            "direction": "IB",
            "number": "07",
            "is_odt": False,
            "wheelchair": False,
            "miles": 6.0,
            "net_pay": 40.0,
            "days": ["M", "T", "W", "Th", "F"],
            "start_time": "7:15 AM",
            "district": "Kent",
            "origin": "123 Home St, Kent, WA",
            "destination": "Brand New MS, Kent, WA",
        },
        status="taken",
    )
    sess.add(intake)
    sess.commit()
    sess.close()

    resp = client.post(
        "/api/data/season/import", json={"from_intake": True}, cookies=_AUTH,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_rows"] == 1
    assert body["created"] >= 1
    assert body["schools_created"] == 1

    sess = _db()
    # route_school is stored canonicalized (lower/single-spaced) — casing never forks identity
    rows = sess.query(SeasonRide).filter(SeasonRide.route_school == "brand new ms").all()
    assert len(rows) == 1
    sess.close()


def test_import_requires_file_or_from_intake():
    resp = client.post("/api/data/season/import", json={}, cookies=_AUTH)
    assert resp.status_code == 400


# ── POST /season/loops/propose + GET /season/loops ───────────────────────────

def _seed_chainable_am_rides(sess):
    school = _seed_school(sess, name="chain school", display_name="Chain School")
    r1 = _seed_ride(
        sess, school_id=school.school_id, route_number="01", route_direction="IB",
        pickup_city="Bellevue", dropoff_city="Seattle", pickup_time="7:00", dropoff_time="7:30",
    )
    r2 = _seed_ride(
        sess, school_id=school.school_id, route_number="02", route_direction="IB",
        pickup_city="Seattle", dropoff_city="Seattle", pickup_time="7:50", dropoff_time="8:10",
    )
    return r1, r2


def test_propose_persists_loops_with_meta_and_links_rides():
    sess = _db()
    r1, r2 = _seed_chainable_am_rides(sess)
    r1_id, r2_id = r1.season_ride_id, r2.season_ride_id
    sess.close()

    resp = client.post(
        "/api/data/season/loops/propose", json={"season": SEASON}, cookies=_AUTH,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["loops_created"] >= 1
    assert body["ungroupable"] == []

    sess = _db()
    loops = sess.query(DriverLoop).filter(DriverLoop.season == SEASON).all()
    assert len(loops) == body["loops_created"]
    loop = next(l for l in loops if l.day_part == "AM")
    assert loop.status == "proposed"
    assert loop.origin == "system"
    assert "slack_minutes" in loop.meta
    assert "requires_profile" in loop.meta
    assert loop.meta["builder"] == "s10-v1"

    r1_refreshed = sess.query(SeasonRide).filter(SeasonRide.season_ride_id == r1_id).first()
    r2_refreshed = sess.query(SeasonRide).filter(SeasonRide.season_ride_id == r2_id).first()
    assert r1_refreshed.loop_id == loop.loop_id
    assert r2_refreshed.loop_id == loop.loop_id
    assert {r1_refreshed.loop_position, r2_refreshed.loop_position} == {0, 1}
    old_loop_id = loop.loop_id
    loops_after_first_propose = len(loops)
    sess.close()

    listing = client.get("/api/data/season/loops", params={"season": SEASON}, cookies=_AUTH)
    assert listing.status_code == 200
    listed = listing.json()["loops"]
    assert any(l["loop_id"] == old_loop_id and len(l["rides"]) == 2 for l in listed)

    # Re-propose with the identical input: the previous system-proposed loop
    # must be cleared before the new one is inserted — if it weren't, the
    # scope would end up with 2 AM loops instead of 1 (sqlite may reuse the
    # freed PK on the replacement row, so PK identity alone can't prove this).
    resp2 = client.post(
        "/api/data/season/loops/propose", json={"season": SEASON}, cookies=_AUTH,
    )
    assert resp2.status_code == 200
    assert resp2.json()["loops_created"] == loops_after_first_propose
    sess = _db()
    new_loops = sess.query(DriverLoop).filter(DriverLoop.season == SEASON).all()
    assert len(new_loops) == loops_after_first_propose
    sess.close()


def test_repropose_never_touches_confirmed_loop():
    sess = _db()
    r1, r2 = _seed_chainable_am_rides(sess)
    driver = _seed_person(sess, full_name="Confirmed Driver")
    driver_id = driver.person_id
    sess.close()

    client.post("/api/data/season/loops/propose", json={"season": SEASON}, cookies=_AUTH)

    sess = _db()
    loop = sess.query(DriverLoop).filter(DriverLoop.season == SEASON).first()
    loop_id = loop.loop_id
    sess.close()

    assign_resp = client.post(
        f"/api/data/season/loops/{loop_id}/assign", json={"person_id": driver_id}, cookies=_AUTH,
    )
    assert assign_resp.status_code == 200
    assert assign_resp.json()["status"] == "confirmed"

    # Re-propose with no other rides in the pool — confirmed loop must survive untouched.
    resp = client.post("/api/data/season/loops/propose", json={"season": SEASON}, cookies=_AUTH)
    assert resp.status_code == 200
    assert resp.json()["loops_created"] == 0

    sess = _db()
    still_there = sess.query(DriverLoop).filter(DriverLoop.loop_id == loop_id).first()
    assert still_there is not None
    assert still_there.status == "confirmed"
    sess.close()


# ── assign / dismiss ─────────────────────────────────────────────────────────

def _seed_proposed_loop(sess, ride, requires_profile=None) -> DriverLoop:
    loop = DriverLoop(
        season=SEASON, label="AM 1 — Test", day_part="AM", days="M,T,W,R,F",
        status="proposed", origin="system",
        meta={"slack_minutes": [], "requires_profile": requires_profile or {}, "builder": "s10-v1"},
    )
    sess.add(loop)
    sess.flush()
    ride.loop_id = loop.loop_id
    ride.loop_position = 0
    sess.commit()
    return loop


def test_assign_happy_path():
    sess = _db()
    ride = _seed_ride(sess)
    driver = _seed_person(sess, full_name="Happy Driver")
    loop = _seed_proposed_loop(sess, ride)
    loop_id, driver_id, ride_id = loop.loop_id, driver.person_id, ride.season_ride_id
    sess.close()

    resp = client.post(
        f"/api/data/season/loops/{loop_id}/assign", json={"person_id": driver_id}, cookies=_AUTH,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "confirmed"
    assert body["person_id"] == driver_id

    sess = _db()
    ride_refreshed = sess.query(SeasonRide).filter(SeasonRide.season_ride_id == ride_id).first()
    assert ride_refreshed.assigned_person_id == driver_id
    assert ride_refreshed.status == "assigned"
    sess.close()


def test_assign_409_missing_capabilities_then_override():
    sess = _db()
    ride = _seed_ride(sess, requires={"wheelchair": True})
    driver = _seed_person(sess, full_name="No Wheelchair Van", capabilities={"wheelchair_vehicle": False})
    loop = _seed_proposed_loop(sess, ride, requires_profile={"wheelchair": True})
    loop_id, driver_id = loop.loop_id, driver.person_id
    sess.close()

    resp = client.post(
        f"/api/data/season/loops/{loop_id}/assign", json={"person_id": driver_id}, cookies=_AUTH,
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["reason"]
    assert "wheelchair" in detail["missing"]

    resp2 = client.post(
        f"/api/data/season/loops/{loop_id}/assign",
        json={"person_id": driver_id, "override": True},
        cookies=_AUTH,
    )
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "confirmed"


def test_dismiss_clears_ride_loop_fields_and_blocks_confirmed():
    sess = _db()
    ride = _seed_ride(sess)
    loop = _seed_proposed_loop(sess, ride)
    loop_id, ride_id = loop.loop_id, ride.season_ride_id
    sess.close()

    resp = client.post(
        f"/api/data/season/loops/{loop_id}/dismiss", cookies=_AUTH, headers={"Accept": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "dismissed"

    sess = _db()
    ride_refreshed = sess.query(SeasonRide).filter(SeasonRide.season_ride_id == ride_id).first()
    assert ride_refreshed.loop_id is None
    assert ride_refreshed.loop_position is None
    confirmed_loop = DriverLoop(season=SEASON, label="X", day_part="AM", status="confirmed", origin="system")
    sess.add(confirmed_loop)
    sess.commit()
    confirmed_id = confirmed_loop.loop_id
    sess.close()

    resp2 = client.post(
        f"/api/data/season/loops/{confirmed_id}/dismiss", cookies=_AUTH, headers={"Accept": "application/json"},
    )
    assert resp2.status_code == 409


# ── PATCH /season/rides/{id} + unassign ──────────────────────────────────────

def test_patch_ride_reextracts_city_from_new_address():
    sess = _db()
    ride = _seed_ride(sess, pickup_address=None, pickup_city=None)
    ride_id = ride.season_ride_id
    sess.close()

    resp = client.patch(
        f"/api/data/season/rides/{ride_id}",
        json={"pickup_address": "123 Main St, Bellevue, WA 98004"},
        cookies=_AUTH,
    )
    assert resp.status_code == 200
    assert resp.json()["pickup_city"] == "Bellevue"

    # Explicit city in the same payload wins over re-extraction.
    resp2 = client.patch(
        f"/api/data/season/rides/{ride_id}",
        json={"pickup_address": "456 Oak Ave, Renton, WA", "pickup_city": "Kirkland"},
        cookies=_AUTH,
    )
    assert resp2.status_code == 200
    assert resp2.json()["pickup_city"] == "Kirkland"


def test_unassign_ride():
    sess = _db()
    driver = _seed_person(sess, full_name="To Unassign")
    ride = _seed_ride(sess, status="assigned", assigned_person_id=driver.person_id)
    ride_id = ride.season_ride_id
    sess.close()

    resp = client.post(
        f"/api/data/season/rides/{ride_id}/unassign", cookies=_AUTH, headers={"Accept": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "unassigned"

    sess = _db()
    refreshed = sess.query(SeasonRide).filter(SeasonRide.season_ride_id == ride_id).first()
    assert refreshed.assigned_person_id is None
    assert refreshed.status == "unassigned"
    sess.close()


# ── schools ───────────────────────────────────────────────────────────────────

def test_school_patch_triggers_ride_backfill():
    sess = _db()
    school = _seed_school(sess, name="needs address es", display_name="Needs Address ES")
    ride = _seed_ride(
        sess, school_id=school.school_id, route_direction="IB",
        dropoff_address=None, dropoff_city=None,
    )
    school_id, ride_id = school.school_id, ride.season_ride_id
    sess.close()

    resp = client.patch(
        f"/api/data/schools/{school_id}",
        json={"address": "500 School Rd, Renton, WA", "city": "Renton", "district": "Kent"},
        cookies=_AUTH,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["city"] == "Renton"
    assert body["district"] == "Kent"

    sess = _db()
    ride_refreshed = sess.query(SeasonRide).filter(SeasonRide.season_ride_id == ride_id).first()
    assert ride_refreshed.dropoff_city == "Renton"
    assert ride_refreshed.dropoff_address == "500 School Rd, Renton, WA"
    sess.close()


def test_school_patch_404_for_unknown_school():
    resp = client.patch("/api/data/schools/999999", json={"city": "X"}, cookies=_AUTH)
    assert resp.status_code == 404


# ── people / capabilities ─────────────────────────────────────────────────────

def test_capabilities_patch_rejects_unknown_key():
    sess = _db()
    person = _seed_person(sess, full_name="Cap Test")
    person_id = person.person_id
    sess.close()

    resp = client.patch(
        f"/api/data/people/{person_id}/capabilities",
        json={"not_a_real_flag": True},
        cookies=_AUTH,
    )
    assert resp.status_code == 422


def test_capabilities_patch_accepts_known_keys():
    sess = _db()
    person = _seed_person(sess, full_name="Cap Test 2")
    person_id = person.person_id
    sess.close()

    resp = client.patch(
        f"/api/data/people/{person_id}/capabilities",
        json={"wheelchair_vehicle": True, "monitor_ok": False},
        cookies=_AUTH,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["capabilities"] == {"wheelchair_vehicle": True, "monitor_ok": False}


# ── SEASON_POOL_AUTOFILL wiring ──────────────────────────────────────────────

def test_pool_taken_intake_never_raises_on_bad_intake():
    sess = _db()
    busted = RideIntake(raw_text="garbage, no route identity at all", parsed={}, status="taken")
    # Deliberately not persisted — upsert_from_intake only reads .parsed/.intake_id.
    result = pool_taken_intake(sess, busted)
    assert result is None
    sess.close()


# ── review-round guards (S10 ship gate) ──────────────────────────────────────

def test_patch_ride_rejects_unknown_status():
    sess = _db()
    ride = _seed_ride(sess)
    ride_id = ride.season_ride_id
    sess.close()

    resp = client.patch(
        f"/api/data/season/rides/{ride_id}", json={"status": "banana"}, cookies=_AUTH,
    )
    assert resp.status_code == 422
    assert "status must be one of" in str(resp.json()["detail"])


def test_malformed_and_non_object_json_bodies_return_400():
    sess = _db()
    ride = _seed_ride(sess)
    ride_id = ride.season_ride_id
    sess.close()

    not_json = client.patch(
        f"/api/data/season/rides/{ride_id}",
        content=b"this is not json",
        headers={"Content-Type": "application/json"},
        cookies=_AUTH,
    )
    assert not_json.status_code == 400

    json_array = client.patch(
        f"/api/data/season/rides/{ride_id}",
        json=["a", "list"],
        cookies=_AUTH,
    )
    assert json_array.status_code == 400


def test_equipment_flags_never_gate_assignment():
    # Car seat/booster/harness are equipment Maz hands the driver, monitors
    # come from FirstAlt — none of them block assignment (Malik 2026-08-06).
    # Only wheelchair gates.
    sess = _db()
    ride = _seed_ride(sess, requires={"car_seat": True, "booster": True, "harness": True, "monitor": True})
    driver = _seed_person(sess, full_name="No Equipment On File", capabilities=None)
    loop = _seed_proposed_loop(
        sess, ride,
        requires_profile={"car_seat": True, "booster": True, "harness": True, "monitor": True},
    )
    loop_id, driver_id = loop.loop_id, driver.person_id
    sess.close()

    resp = client.post(
        f"/api/data/season/loops/{loop_id}/assign", json={"person_id": driver_id}, cookies=_AUTH,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "confirmed"


# ── PDF queue (upload fallback drained by the local ride-pdf-worker) ─────────

from unittest.mock import patch as _mock_patch  # noqa: E402

from backend.services.season_pool import (  # noqa: E402
    PDF_QUEUE_FAILED,
    PDF_QUEUE_IMPORTED,
    PDF_QUEUE_PENDING,
)


def _upload_pdf(filename: str = "Bell ES OB 01.pdf") -> dict:
    """POST a fake Trip Plan PDF through /season/import with server-side
    extraction unavailable (parse_intake_from_pdf -> [])."""
    with _mock_patch(
        "backend.services.ride_pdf_intake.parse_intake_from_pdf", return_value=[],
    ):
        resp = client.post(
            "/api/data/season/import",
            files={"file": (filename, b"%PDF-fake-bytes", "application/pdf")},
            cookies=_AUTH,
            # Same header the Next.js frontend sends — CSRFMiddleware exempts
            # JSON-accepting API calls (protected by CORS + session instead).
            headers={"accept": "application/json"},
        )
    assert resp.status_code == 200
    return resp.json()


def test_pdf_upload_queues_and_reports_queued():
    payload = _upload_pdf()
    assert payload["queued"] == 1
    assert payload["created"] == 0
    assert payload["errors"] == []

    sess = _db()
    try:
        intake = sess.query(RideIntake).one()
        assert intake.status == PDF_QUEUE_PENDING
    finally:
        sess.close()


def test_pdf_queue_list_and_complete_ok_strips_payload():
    _upload_pdf("Juanita HS IB 02.pdf")

    resp = client.get("/api/data/season/pdf-queue", cookies=_AUTH)
    assert resp.status_code == 200
    pending = resp.json()["pending"]
    assert len(pending) == 1
    item = pending[0]
    assert item["filename"] == "Juanita HS IB 02.pdf"
    import base64 as _b64
    assert _b64.b64decode(item["pdf_b64"]) == b"%PDF-fake-bytes"

    resp = client.post(
        f"/api/data/season/pdf-queue/{item['intake_id']}/complete",
        json={"ok": True, "note": "imported as Juanita HS IB 02"},
        cookies=_AUTH,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == PDF_QUEUE_IMPORTED

    sess = _db()
    try:
        intake = sess.query(RideIntake).one()
        assert intake.status == PDF_QUEUE_IMPORTED
        assert "pdf_b64" not in intake.parsed  # payload dropped on completion
        assert intake.parsed["pdf_filename"] == "Juanita HS IB 02.pdf"
        assert intake.decided_at is not None
    finally:
        sess.close()

    # Queue is drained — and a completed row can't be completed twice.
    resp = client.get("/api/data/season/pdf-queue", cookies=_AUTH)
    assert resp.json()["pending"] == []
    resp = client.post(
        f"/api/data/season/pdf-queue/{item['intake_id']}/complete",
        json={"ok": True}, cookies=_AUTH,
    )
    assert resp.status_code == 404


def test_pdf_queue_complete_failure_records_reason():
    _upload_pdf("garbled.pdf")
    item = client.get("/api/data/season/pdf-queue", cookies=_AUTH).json()["pending"][0]

    resp = client.post(
        f"/api/data/season/pdf-queue/{item['intake_id']}/complete",
        json={"ok": False, "note": "no renderable pages"},
        cookies=_AUTH,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == PDF_QUEUE_FAILED

    sess = _db()
    try:
        intake = sess.query(RideIntake).one()
        assert intake.status == PDF_QUEUE_FAILED
        assert intake.decision_reason == "no renderable pages"
    finally:
        sess.close()


def test_pdf_queue_rows_hidden_from_unfiltered_intake_listing():
    _upload_pdf("hidden.pdf")

    resp = client.get("/api/data/assignment/intakes", cookies=_AUTH)
    assert resp.status_code == 200
    assert resp.json()["intakes"] == []  # queue plumbing never shows as an offer
