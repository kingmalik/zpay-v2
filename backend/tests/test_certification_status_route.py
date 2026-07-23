"""
API contract test for GET /api/data/certification/status (S7 admin fleet
certification status endpoint).

Full in-memory SQLite via TestClient + dependency_overrides, mirroring the
established pattern in test_assignment_routes.py.

Run in isolation:
    PYTHONPATH=. pytest backend/tests/test_certification_status_route.py -v
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
    "test-secret-key-for-certification-status-route-long-enough",
)
os.environ.setdefault("DATABASE_URL", "sqlite://")

from backend.db.models import Base, ZRateOverride  # noqa: E402

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
from backend.db.models import DriverCertification, Person  # noqa: E402
from backend.middleware.auth import COOKIE_NAME, create_session  # noqa: E402
from backend.services import certification  # noqa: E402


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
        sess.query(DriverCertification).delete(synchronize_session=False)
        sess.query(Person).delete(synchronize_session=False)
        sess.commit()
    finally:
        sess.close()


class TestCertificationStatusRoute:
    def setup_method(self):
        _wipe()

    def test_never_certified_driver_shows_not_certified(self):
        sess = _db()
        sess.add(Person(person_id=1, full_name="Never Certified", active=True, status="active"))
        sess.commit()
        sess.close()

        resp = client.get("/api/data/certification/status", cookies=_AUTH)
        assert resp.status_code == 200
        drivers = resp.json()["drivers"]
        entry = next(d for d in drivers if d["person_id"] == 1)
        assert entry["certified"] is False
        assert entry["needs_recert"] is False
        assert entry["course_version"] is None

    def test_certified_driver_shows_certified(self):
        sess = _db()
        sess.add(Person(person_id=2, full_name="Certified Driver", active=True, status="active"))
        sess.commit()
        certification.record_certification(sess, 2, quiz_score=9, quiz_total=10, signed_name="Certified Driver")
        sess.close()

        resp = client.get("/api/data/certification/status", cookies=_AUTH)
        assert resp.status_code == 200
        drivers = resp.json()["drivers"]
        entry = next(d for d in drivers if d["person_id"] == 2)
        assert entry["certified"] is True
        assert entry["needs_recert"] is False
        assert entry["course_version"] == certification.COURSE_VERSION

    def test_stale_course_version_shows_needs_recert(self):
        sess = _db()
        sess.add(Person(person_id=3, full_name="Stale Cert Driver", active=True, status="active"))
        sess.commit()
        certification.record_certification(
            sess, 3, quiz_score=8, quiz_total=10, signed_name="Stale Cert Driver",
            course_version="2025-01",
        )
        sess.close()

        resp = client.get("/api/data/certification/status", cookies=_AUTH)
        assert resp.status_code == 200
        drivers = resp.json()["drivers"]
        entry = next(d for d in drivers if d["person_id"] == 3)
        assert entry["certified"] is False
        assert entry["needs_recert"] is True

    def test_inactive_drivers_excluded(self):
        sess = _db()
        sess.add(Person(person_id=4, full_name="Inactive Driver", active=False, status="active"))
        sess.commit()
        sess.close()

        resp = client.get("/api/data/certification/status", cookies=_AUTH)
        assert resp.status_code == 200
        ids = {d["person_id"] for d in resp.json()["drivers"]}
        assert 4 not in ids
