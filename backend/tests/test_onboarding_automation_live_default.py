"""
Tests for the S6 punch-list fix: onboarding_record.automation_live now
defaults to true for NEW rows (migration s6a_automation_live_default_true),
while existing rows are untouched (schema-only DEFAULT change, no data UPDATE).

DB strategy: same in-memory SQLite + StaticPool pattern used across the
test suite (see test_settle_external.py).

Run in isolation:
    PYTHONPATH=/path/to/zpay-v2-fresh pytest backend/tests/test_onboarding_automation_live_default.py -v
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import BigInteger, Integer, Text, create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault(
    "ZPAY_SECRET_KEY",
    "test-secret-automation-live-default-long-enough",
)
os.environ.setdefault("DATABASE_URL", "sqlite://")

from backend.db.models import Base, OnboardingRecord, Person  # noqa: E402

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
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

Base.metadata.create_all(_engine)
_SessionFactory = sessionmaker(bind=_engine, autoflush=False, autocommit=False)


def _db():
    return _SessionFactory()


class TestAutomationLiveDefault:
    def test_new_onboarding_record_defaults_automation_live_true(self):
        """A freshly INSERTed row that doesn't specify automation_live should
        pick up the new server_default (true) — matching the model's
        server_default=text("true") set in migration s6a_automation_live_default_true."""
        sess = _db()
        try:
            p = Person(person_id=8001, full_name="Autolive Test", active=True, status="active")
            sess.add(p)
            rec = OnboardingRecord(person_id=8001, invite_token="tok-autolive-1")
            sess.add(rec)
            sess.commit()
            sess.refresh(rec)
            assert rec.automation_live is True
        finally:
            sess.query(OnboardingRecord).delete(synchronize_session=False)
            sess.query(Person).delete(synchronize_session=False)
            sess.commit()
            sess.close()

    def test_explicit_false_is_still_respected(self):
        """The default only applies when no value is given — existing code
        paths (and any future admin action) can still explicitly set False."""
        sess = _db()
        try:
            p = Person(person_id=8002, full_name="Explicit False Test", active=True, status="active")
            sess.add(p)
            rec = OnboardingRecord(person_id=8002, invite_token="tok-autolive-2", automation_live=False)
            sess.add(rec)
            sess.commit()
            sess.refresh(rec)
            assert rec.automation_live is False
        finally:
            sess.query(OnboardingRecord).delete(synchronize_session=False)
            sess.query(Person).delete(synchronize_session=False)
            sess.commit()
            sess.close()

    def test_model_column_server_default_is_true(self):
        """Guard against silent regression back to the old false default."""
        col = OnboardingRecord.__table__.c["automation_live"]
        assert col.server_default is not None
        assert "true" in col.server_default.arg.text.lower()
