"""
API contract tests for backend/routes/assignment.py (S5).

Full in-memory SQLite via TestClient + dependency_overrides, mirroring the
established pattern in test_manual_adjustments.py (global metadata patches
for SQLite compatibility — BigInteger PKs, DATERANGE, NOW() defaults).

Run in isolation:
    PYTHONPATH=. pytest backend/tests/test_assignment_routes.py -x -v
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import BigInteger, Integer, Text, create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault(
    "ZPAY_SECRET_KEY",
    "test-secret-key-for-assignment-routes-tests-long-enough",
)
os.environ.setdefault("DATABASE_URL", "sqlite://")  # silenced by get_db override

from backend.db.models import Base, ZRateOverride  # noqa: E402

# ── Metadata patches (same three as test_manual_adjustments.py) ─────────────
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
from backend.db.models import Person, RideIntake, RouteBackup, RouteRoster  # noqa: E402
from backend.middleware.auth import COOKIE_NAME, create_session  # noqa: E402
from backend.services import assignment_service  # noqa: E402


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


def _db():
    return _SessionFactory()


def _wipe():
    sess = _db()
    try:
        sess.query(RouteBackup).delete(synchronize_session=False)
        sess.query(RouteRoster).delete(synchronize_session=False)
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


# ── /intake ──────────────────────────────────────────────────────────────────

def test_intake_wheelchair_ride_never_auto_prices():
    sess = _db()
    _seed_person(sess)
    sess.close()

    resp = client.post(
        "/api/data/assignment/intake",
        json={"raw_text": "Cedar Heights MS OB 16 (HCV), $62, 9 miles, wheelchair van needed."},
        cookies=_AUTH,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["parsed"]["wheelchair"] is True
    assert body["pricing"]["predicted_rate"] is None
    assert body["pricing"]["manual_review"] is True
    assert body["pricing"]["pass_through_suggestion"] == 62.0
    assert "reply_draft" in body
    assert isinstance(body["suggestions"], list)


def test_intake_requires_raw_text():
    resp = client.post("/api/data/assignment/intake", json={"raw_text": ""}, cookies=_AUTH)
    assert resp.status_code == 400


def test_intake_persists_and_lists():
    with patch.object(assignment_service, "load_pricing_context", return_value=[]):
        resp = client.post(
            "/api/data/assignment/intake",
            json={"raw_text": "Brand New School IB 01, $40, 10 miles."},
            cookies=_AUTH,
        )
    assert resp.status_code == 200
    intake_id = resp.json()["intake_id"]

    listing = client.get("/api/data/assignment/intakes", cookies=_AUTH)
    assert listing.status_code == 200
    ids = [i["intake_id"] for i in listing.json()["intakes"]]
    assert intake_id in ids


def test_intake_decision_take_and_pass():
    with patch.object(assignment_service, "load_pricing_context", return_value=[]):
        resp = client.post(
            "/api/data/assignment/intake",
            json={"raw_text": "Some School OB 02, $30, 5 miles."},
            cookies=_AUTH,
        )
    intake_id = resp.json()["intake_id"]

    decided = client.post(
        f"/api/data/assignment/intake/{intake_id}/decision",
        json={"decision": "pass", "reason": "no available driver"},
        cookies=_AUTH,
    )
    assert decided.status_code == 200
    assert decided.json()["status"] == "passed"
    assert decided.json()["decision_reason"] == "no available driver"


def test_intake_decision_rejects_bad_value():
    resp = client.post(
        "/api/data/assignment/intake/1/decision",
        json={"decision": "maybe"},
        cookies=_AUTH,
    )
    assert resp.status_code == 400


def test_intake_decision_404_for_unknown_id():
    resp = client.post(
        "/api/data/assignment/intake/999999/decision",
        json={"decision": "take"},
        cookies=_AUTH,
    )
    assert resp.status_code == 404


# ── /suggest ─────────────────────────────────────────────────────────────────

def test_suggest_returns_contract_shape():
    sess = _db()
    _seed_person(sess, full_name="Driver One")
    sess.close()

    resp = client.get(
        "/api/data/assignment/suggest",
        params={"school": "Risalah ES", "direction": "IB", "wheelchair": True},
        cookies=_AUTH,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "suggestions" in body and "pricing" in body
    if body["suggestions"]:
        s = body["suggestions"][0]
        for key in ("person_id", "name", "tier", "score", "reasons", "familiar_rides", "load_recent", "home_area"):
            assert key in s


# ── rosters ──────────────────────────────────────────────────────────────────

def test_roster_backups_put_and_get():
    sess = _db()
    primary = _seed_person(sess, full_name="Primary")
    backup = _seed_person(sess, full_name="Backup One")
    roster = RouteRoster(
        source="acumen", route_school="Risalah ES", route_direction="IB", route_number="05",
        route_is_odt=False, primary_person_id=primary.person_id, active=True,
    )
    sess.add(roster)
    sess.commit()
    roster_id = roster.roster_id
    primary_id = primary.person_id
    backup_id = backup.person_id
    sess.close()

    resp = client.put(
        f"/api/data/assignment/rosters/{roster_id}/backups",
        json={"backups": [{"person_id": backup_id, "rank": 1}]},
        cookies=_AUTH,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["primary"]["person_id"] == primary_id
    assert body["backups"] == [{"person_id": backup_id, "name": "Backup One", "rank": 1}]

    listing = client.get("/api/data/assignment/rosters", cookies=_AUTH)
    assert listing.status_code == 200
    rosters = listing.json()["rosters"]
    assert any(r["roster_id"] == roster_id and r["backups"] for r in rosters)


def test_roster_sync_endpoint_returns_counts():
    # No JSON body on this POST — CSRF middleware only exempts JSON
    # content-type/Accept requests, so an explicit Accept header is needed
    # (same precedent as the DELETE calls in test_manual_adjustments.py).
    resp = client.post(
        "/api/data/assignment/rosters/sync", cookies=_AUTH, headers={"Accept": "application/json"},
    )
    assert resp.status_code == 200
    body = resp.json()
    for key in ("created", "updated", "deactivated"):
        assert key in body


def test_backup_candidates_404_for_unknown_roster():
    resp = client.get("/api/data/assignment/rosters/999999/backup-candidates", cookies=_AUTH)
    assert resp.status_code == 404


def test_coverage_404_for_unknown_roster():
    resp = client.get(
        "/api/data/assignment/coverage", params={"roster_id": 999999, "date": "2026-07-28"}, cookies=_AUTH,
    )
    assert resp.status_code == 404


def test_coverage_rejects_bad_date():
    sess = _db()
    primary = _seed_person(sess, full_name="Primary")
    roster = RouteRoster(
        source="acumen", route_school="Risalah ES", route_direction="IB", route_number="05",
        route_is_odt=False, primary_person_id=primary.person_id, active=True,
    )
    sess.add(roster)
    sess.commit()
    roster_id = roster.roster_id
    sess.close()

    resp = client.get(
        "/api/data/assignment/coverage", params={"roster_id": roster_id, "date": "not-a-date"}, cookies=_AUTH,
    )
    assert resp.status_code == 400


# ── home-gaps + people/home PATCH ────────────────────────────────────────────

def test_home_gaps_lists_active_drivers_without_home_area():
    sess = _db()
    _seed_person(sess, full_name="No Home Area")
    _seed_person(sess, full_name="Has Home Area", home_area="Bellevue")
    sess.close()

    resp = client.get("/api/data/assignment/home-gaps", cookies=_AUTH)
    assert resp.status_code == 200
    names = {d["name"] for d in resp.json()["drivers"]}
    assert "No Home Area" in names
    assert "Has Home Area" not in names


def test_patch_person_home_sets_area_and_zip():
    sess = _db()
    person = _seed_person(sess, full_name="Set Home")
    person_id = person.person_id
    sess.close()

    resp = client.patch(
        f"/api/data/people/{person_id}/home",
        json={"home_area": "Renton", "home_zip": "98055"},
        cookies=_AUTH,
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    sess = _db()
    refreshed = sess.query(Person).filter(Person.person_id == person_id).first()
    assert refreshed.home_area == "Renton"
    assert refreshed.home_zip == "98055"
    sess.close()


def test_patch_person_home_404_for_unknown_person():
    resp = client.patch(
        "/api/data/people/999999/home", json={"home_area": "X"}, cookies=_AUTH,
    )
    assert resp.status_code == 404
