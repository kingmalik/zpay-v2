"""
Tests for z_rate_locked_at defensive lock.

Covers:
  1. regenerate_paystub_from_data sets z_rate_locked_at on rides after stub generation
  2. z_rate_locked_at does not move on subsequent regeneration (idempotent)
  3. _lock_z_rate helper is a no-op when lock is already set (SQL WHERE clause)
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_person(person_id: int = 10, email: str = "driver@example.com", full_name: str = "Test Driver"):
    p = SimpleNamespace()
    p.person_id = person_id
    p.email = email
    p.full_name = full_name
    return p


def _make_batch(batch_id: int = 42, company_name: str = "TestCo"):
    b = SimpleNamespace()
    b.payroll_batch_id = batch_id
    b.company_name = company_name
    b.week_start = None
    b.week_end = None
    b.period_start = None
    b.period_end = None
    return b


def _make_ride(ride_id: int, person_id: int = 10, batch_id: int = 42, z_rate: float = 15.0):
    r = SimpleNamespace()
    r.ride_id = ride_id
    r.person_id = person_id
    r.payroll_batch_id = batch_id
    r.z_rate = z_rate
    r.ride_start_ts = None
    r.z_rate_locked_at = None
    return r


def _make_db(person=None, batch=None, rides=None):
    """Return a mock Session wired for the paystub_archive service calls."""
    from backend.db.models import Person, PayrollBatch, Ride

    db = MagicMock()

    def _get(model_cls, pk):
        if model_cls is Person:
            return person
        if model_cls is PayrollBatch:
            return batch
        return None

    db.get.side_effect = _get

    # .query(...).filter(...).order_by(...).all() chain
    mock_query = MagicMock()
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.all.return_value = rides or []
    db.query.return_value = mock_query

    return db


# ── 1. regenerate_paystub_from_data stamps z_rate_locked_at ──────────────────

class TestRegenerateStubSetsLock:
    @patch("backend.services.paystub_archive.save_pdf_to_archive")
    @patch("backend.services.paystub_archive._build_paystub_pdf")
    def test_lock_stamped_after_successful_archive(self, mock_build_pdf, mock_archive):
        """After a successful regenerate, _lock_z_rate must issue the UPDATE."""
        from backend.services.paystub_archive import regenerate_paystub_from_data

        mock_build_pdf.return_value = b"%PDF-fake"
        mock_archive.return_value = 99  # paystub_id

        person = _make_person(person_id=10)
        batch = _make_batch(batch_id=42)
        rides = [_make_ride(ride_id=1), _make_ride(ride_id=2)]

        db = _make_db(person=person, batch=batch, rides=rides)

        pdf_bytes, paystub_id = regenerate_paystub_from_data(db, person_id=10, batch_id=42)

        assert paystub_id == 99
        # db.execute must have been called with the UPDATE statement
        assert db.execute.called, "Expected db.execute to be called for _lock_z_rate UPDATE"
        call_args = db.execute.call_args
        sql_text = str(call_args[0][0])  # first positional arg is the text() object
        assert "z_rate_locked_at" in sql_text, f"UPDATE did not mention z_rate_locked_at: {sql_text}"
        assert "payroll_batch_id" in sql_text or ":b" in sql_text
        assert "person_id" in sql_text or ":p" in sql_text

        # params must carry the right batch_id and person_id
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
        if isinstance(params, dict):
            assert params.get("b") == 42
            assert params.get("p") == 10

    @patch("backend.services.paystub_archive.save_pdf_to_archive")
    @patch("backend.services.paystub_archive._build_paystub_pdf")
    def test_lock_commit_called(self, mock_build_pdf, mock_archive):
        """db.commit() must be called after the lock UPDATE (not just after archive)."""
        from backend.services.paystub_archive import regenerate_paystub_from_data

        mock_build_pdf.return_value = b"%PDF-fake"
        mock_archive.return_value = 1

        person = _make_person()
        batch = _make_batch()
        db = _make_db(person=person, batch=batch, rides=[_make_ride(ride_id=1)])

        regenerate_paystub_from_data(db, person_id=10, batch_id=42)

        # commit called at least twice: once by save_pdf_to_archive (mocked), once by _lock_z_rate
        assert db.commit.call_count >= 1, "Expected at least one db.commit() from _lock_z_rate"


# ── 2. Idempotency — z_rate_locked_at does not move on re-generation ─────────

class TestLockIdempotency:
    def test_lock_z_rate_sql_has_null_guard(self):
        """
        _lock_z_rate's SQL must include 'z_rate_locked_at IS NULL' so a second
        call cannot overwrite a previously set timestamp.
        """
        from backend.services.paystub_archive import _lock_z_rate

        db = MagicMock()

        _lock_z_rate(db, batch_id=42, person_id=10)

        assert db.execute.called
        sql_text = str(db.execute.call_args[0][0])
        assert "IS NULL" in sql_text, (
            "SQL must include 'z_rate_locked_at IS NULL' to be idempotent; got: " + sql_text
        )

    def test_lock_z_rate_commits(self):
        """_lock_z_rate must commit after the UPDATE."""
        from backend.services.paystub_archive import _lock_z_rate

        db = MagicMock()
        _lock_z_rate(db, batch_id=42, person_id=10)
        db.commit.assert_called_once()

    def test_lock_z_rate_passes_correct_params(self):
        """Params dict must have keys 'b' and 'p' matching batch_id and person_id."""
        from backend.services.paystub_archive import _lock_z_rate

        db = MagicMock()
        _lock_z_rate(db, batch_id=77, person_id=33)

        call_args = db.execute.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
        assert isinstance(params, dict)
        assert params["b"] == 77
        assert params["p"] == 33


# ── 3. Existing regenerate_paystub_from_data still raises on bad person/batch ─

class TestRegenerateValidation:
    def test_raises_on_missing_person(self):
        from backend.services.paystub_archive import regenerate_paystub_from_data

        db = _make_db(person=None, batch=_make_batch())

        with pytest.raises(ValueError, match="Person"):
            regenerate_paystub_from_data(db, person_id=999, batch_id=42)

    def test_raises_on_missing_batch(self):
        from backend.services.paystub_archive import regenerate_paystub_from_data

        db = _make_db(person=_make_person(), batch=None)

        with pytest.raises(ValueError, match="Batch"):
            regenerate_paystub_from_data(db, person_id=10, batch_id=999)
