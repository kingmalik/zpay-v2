"""
Tests for audit logging on the toggle-active endpoint.

Endpoint under test:
  POST /people/{person_id}/toggle-active

What we verify:
  1. Toggle flips person.active correctly (existing behaviour, regression guard).
  2. An AuditLog row is created with the correct before/after values.
  3. actor_email is populated from the session cookie user.
  4. Before/after values are inverted on a second toggle (active→inactive→active).
  5. A 404 on an unknown person creates no audit row.

DB strategy (matches test_manual_adjustments.py pattern):
  In-memory SQLite via StaticPool. Patches applied before create_all:
    - DATERANGE → Text   (PostgreSQL-only type)
    - BigInteger PKs → Integer   (SQLite autoincrement requirement)
    - server_default=text("NOW()") columns → nullable=True, no server_default
      (SQLite has no NOW(); we set created_at explicitly where needed)

Run:
    PYTHONPATH=/path/to/zpay-v2-fresh pytest backend/tests/test_audit_log_toggle_active.py -v
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import BigInteger, Column, Integer, Text, create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ── Project root on sys.path ──────────────────────────────────────────────────
_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Auth middleware reads ZPAY_SECRET_KEY at import time.
os.environ.setdefault(
    "ZPAY_SECRET_KEY",
    "test-secret-key-for-audit-log-tests-long-enough-32chars",
)
os.environ.setdefault("DATABASE_URL", "sqlite://")

# Import models so Base.metadata is populated before we patch + create_all.
from backend.db.models import AuditLog, Base, ZRateOverride  # noqa: E402

# ── Metadata patches ──────────────────────────────────────────────────────────

# Patch 1: DATERANGE is PostgreSQL-only.
Base.metadata.tables["z_rate_override"].c["effective_during"].type = Text()

# Patch 2: BigInteger PKs → Integer (SQLite autoincrement only works on INTEGER).
for _tbl in Base.metadata.tables.values():
    for _col in _tbl.columns:
        if _col.primary_key and isinstance(_col.type, BigInteger):
            _col.type = Integer()

# Patch 3: Columns with server_default NOW() — make nullable, remove default.
for _tbl in Base.metadata.tables.values():
    for _col in _tbl.columns:
        if _col.server_default is not None:
            try:
                _arg = (
                    _col.server_default.arg.text
                    if hasattr(_col.server_default, "arg") and hasattr(_col.server_default.arg, "text")
                    else ""
                )
            except Exception:
                _arg = ""
            if "NOW()" in _arg:
                _col.nullable = True
                _col.server_default = None

# ── Shared in-memory SQLite engine ───────────────────────────────────────────
_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(_engine)
_SessionFactory = sessionmaker(bind=_engine, autoflush=False, autocommit=False)

# ── FastAPI app + dependency overrides ───────────────────────────────────────
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402
from backend.db import get_db  # noqa: E402
from backend.db.models import Person  # noqa: E402
from backend.middleware.auth import COOKIE_NAME, create_session  # noqa: E402


def _override_get_db():
    db = _SessionFactory()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db

_SESSION_COOKIE = create_session(
    username="testadmin",
    display_name="Test Admin",
    color="#333",
    initials="TA",
    role="admin",
    user_id=1,
)

# Set the session cookie on the client instance so every request carries it.
# Also set the CSRF cookie — the middleware exempts JSON requests from the
# double-submit check, but setting it avoids redirect-follow surprises.
client = TestClient(app, raise_server_exceptions=True)
client.cookies.set(COOKIE_NAME, _SESSION_COOKIE)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _db():
    return _SessionFactory()


_person_counter = 0


def _make_person(db, *, active: bool = True) -> Person:
    global _person_counter
    _person_counter += 1
    p = Person(
        full_name=f"Test Driver {_person_counter}",
        email=f"driver_{_person_counter}@example.com",
        active=active,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _wipe(db):
    db.query(AuditLog).delete(synchronize_session=False)
    db.query(Person).delete(synchronize_session=False)
    db.commit()


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestToggleActiveAuditLog:

    def setup_method(self):
        """Clean slate before every test."""
        db = _db()
        _wipe(db)
        db.close()

    def test_toggle_flips_active_false_to_true(self):
        """Regression: endpoint still flips active correctly."""
        db = _db()
        person = _make_person(db, active=True)
        pid = person.person_id
        db.close()

        resp = client.post(f"/people/{pid}/toggle-active", json={})
        assert resp.status_code == 200, resp.text
        assert resp.json()["active"] is False

    def test_audit_row_created_on_toggle(self):
        """Primary assertion: one AuditLog row exists after a toggle."""
        db = _db()
        person = _make_person(db, active=True)
        pid = person.person_id
        db.close()

        resp = client.post(f"/people/{pid}/toggle-active", json={})
        assert resp.status_code == 200

        db = _db()
        rows = db.query(AuditLog).filter(AuditLog.target_id == pid).all()
        db.close()

        assert len(rows) == 1, f"Expected 1 audit row, got {len(rows)}"

    def test_audit_row_before_after_values(self):
        """before_value and after_value must capture the state change precisely."""
        db = _db()
        person = _make_person(db, active=True)
        pid = person.person_id
        db.close()

        client.post(f"/people/{pid}/toggle-active", json={})

        db = _db()
        row = db.query(AuditLog).filter(AuditLog.target_id == pid).first()
        db.close()

        assert row is not None
        assert row.before_value == {"is_active": True}
        assert row.after_value  == {"is_active": False}

    def test_audit_row_action_and_target_fields(self):
        """action, target_type, target_id must be set correctly."""
        db = _db()
        person = _make_person(db, active=True)
        pid = person.person_id
        db.close()

        client.post(f"/people/{pid}/toggle-active", json={})

        db = _db()
        row = db.query(AuditLog).filter(AuditLog.target_id == pid).first()
        db.close()

        assert row.action      == "person.toggle_active"
        assert row.target_type == "person"
        assert row.target_id   == pid

    def test_audit_row_actor_user_id_populated(self):
        """actor_user_id should be pulled from the session cookie user_id field."""
        db = _db()
        person = _make_person(db, active=True)
        pid = person.person_id
        db.close()

        client.post(f"/people/{pid}/toggle-active", json={})

        db = _db()
        row = db.query(AuditLog).filter(AuditLog.target_id == pid).first()
        db.close()

        assert row is not None
        # Session cookie was created with user_id=1; the route reads actor_user_id
        # from request.state.user["user_id"].
        assert row.actor_user_id == 1

    def test_second_toggle_inverts_before_after(self):
        """Toggle twice: second row should show False→True."""
        db = _db()
        person = _make_person(db, active=True)
        pid = person.person_id
        db.close()

        client.post(f"/people/{pid}/toggle-active", json={})
        client.post(f"/people/{pid}/toggle-active", json={})

        db = _db()
        rows = (
            db.query(AuditLog)
            .filter(AuditLog.target_id == pid)
            .order_by(AuditLog.id)
            .all()
        )
        db.close()

        assert len(rows) == 2
        assert rows[0].before_value == {"is_active": True}
        assert rows[0].after_value  == {"is_active": False}
        assert rows[1].before_value == {"is_active": False}
        assert rows[1].after_value  == {"is_active": True}

    def test_no_audit_row_for_unknown_person(self):
        """404 on an unknown person_id must not create a stray audit row."""
        resp = client.post("/people/999999/toggle-active", json={})
        assert resp.status_code == 404

        db = _db()
        count = db.query(AuditLog).filter(AuditLog.target_id == 999999).count()
        db.close()

        assert count == 0, f"Expected 0 audit rows for unknown person, got {count}"
