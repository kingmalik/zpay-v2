"""
Tests for the date-range guard added to bulk_insert_rides() in pdf_reader.py.

The guard skips any ride whose service_date falls outside [period_start, period_end]
(inclusive), logs a WARNING, and annotates batch.notes.  These are pure unit tests
that mock the DB and all collaborators — no real database connection required.

Test matrix:
  Test 1 — all rides in-period  -> all inserted, no warning, notes unchanged
  Test 2 — all rides out-of-period -> 0 inserted, warning fired, notes annotated
  Test 3 — mixed in/out-of-period -> only in-period inserted, notes reflect count
  Test 4 — boundary dates (period_start and period_end inclusive) -> inserted, not skipped
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Row / DB helpers
# ---------------------------------------------------------------------------

def _make_row(
    service_date,
    person: str = "Test Driver",
    code: str = "9999",
    key: str = "TRIPKEY",
    name: str = "Route A",
    miles: float = 10.0,
    gross: float = 50.0,
    net_pay: float = 48.0,
    rad: float = 0.0,
    wud: float = 0.0,
) -> dict:
    """Build a minimal rides_data row for bulk_insert_rides."""
    return {
        "Person": person,
        "Code": code,
        "Date": service_date,
        "Key": key,
        "Name": name,
        "Miles": miles,
        "Gross": gross,
        "Net Pay": net_pay,
        "RAD": rad,
        "WUD": wud,
        "source_file": "test.pdf",
        "source_page": 1,
    }


def _make_db_mock() -> MagicMock:
    db = MagicMock()
    db.begin_nested.return_value.__enter__ = MagicMock(return_value=None)
    db.begin_nested.return_value.__exit__ = MagicMock(return_value=False)
    db.query.return_value.filter.return_value.all.return_value = []
    return db


PATCH_PREFIX = "backend.services.pdf_reader"


def _run_bulk_insert(
    rides_data: list[dict],
    period_start: str = "2026-04-13",
    period_end: str = "2026-04-19",
) -> tuple[dict, MagicMock, SimpleNamespace]:
    """
    Call bulk_insert_rides with fully mocked collaborators.
    Returns (result_dict, db_mock, fake_batch).
    The fake_batch has a mutable .notes attribute so tests can inspect annotations.
    """
    from backend.services.pdf_reader import bulk_insert_rides

    db = _make_db_mock()
    fake_person = SimpleNamespace(person_id=1)
    fake_batch = SimpleNamespace(
        payroll_batch_id=99,
        source="maz",
        company_name="EverDriven",
        currency="USD",
        notes=f"imported from test.pdf",
    )

    with (
        patch(f"{PATCH_PREFIX}.PayrollBatch", return_value=fake_batch),
        patch(f"{PATCH_PREFIX}.upsert_person", return_value=fake_person),
        patch(f"{PATCH_PREFIX}.ensure_rate_services", return_value=None),
        patch(
            f"{PATCH_PREFIX}.resolve_rate_for_ride",
            return_value=(Decimal("50.00"), "override", 1, None),
        ),
        patch(f"{PATCH_PREFIX}.ZRateService"),
        patch(f"{PATCH_PREFIX}.Ride", side_effect=lambda **kw: SimpleNamespace(**kw)),
    ):
        result = bulk_insert_rides(
            db,
            period_start=period_start,
            period_end=period_end,
            batch_id="TEST-BATCH",
            source_file="test.pdf",
            rides_data=rides_data,
        )

    return result, db, fake_batch


# ---------------------------------------------------------------------------
# Test 1 — all rides in-period -> all inserted, no warning
# ---------------------------------------------------------------------------

class TestAllRidesInPeriod:
    """All rides within [period_start, period_end] must be imported normally."""

    def test_all_in_period_inserted(self, caplog):
        rows = [
            _make_row(date(2026, 4, 13), key="T1"),  # exactly period_start
            _make_row(date(2026, 4, 15), key="T2"),  # mid-period
            _make_row(date(2026, 4, 19), key="T3"),  # exactly period_end
        ]
        with caplog.at_level(logging.WARNING, logger="backend.services.pdf_reader"):
            result, db, batch = _run_bulk_insert(rows)

        assert result["inserted"] == 3, (
            f"All 3 in-period rides must be inserted, got {result['inserted']}"
        )
        assert result["out_of_period"] == 0, (
            f"No out-of-period rides expected, got {result['out_of_period']}"
        )

        guard_warnings = [
            r.message for r in caplog.records
            if r.levelno >= logging.WARNING and "date-range-guard" in (r.getMessage() + r.message)
        ]
        assert not guard_warnings, f"Unexpected date-range-guard warning: {guard_warnings}"

    def test_all_in_period_no_batch_notes_annotation(self):
        rows = [_make_row(date(2026, 4, 16), key="ONLY")]
        result, db, batch = _run_bulk_insert(rows)
        assert "[date-range-guard]" not in (batch.notes or "")


# ---------------------------------------------------------------------------
# Test 2 — all rides out-of-period -> 0 inserted, warning fired, notes annotated
# ---------------------------------------------------------------------------

class TestAllRidesOutOfPeriod:
    """When every ride is outside the batch period, nothing is inserted, a WARNING
    is logged, and batch.notes receives the guard annotation."""

    def test_zero_inserted_when_all_out_of_period(self):
        rows = [
            _make_row(date(2026, 4, 20), key="W16-1"),
            _make_row(date(2026, 4, 21), key="W16-2"),
            _make_row(date(2026, 4, 24), key="W16-3"),
        ]
        result, db, batch = _run_bulk_insert(rows)

        assert result["inserted"] == 0, (
            f"No rides should be inserted for all-out-of-period rows, got {result['inserted']}"
        )
        assert result["out_of_period"] == 3, (
            f"All 3 rides should be counted as out-of-period, got {result['out_of_period']}"
        )

    def test_warning_logged_when_out_of_period(self, caplog):
        rows = [
            _make_row(date(2026, 4, 20), key="W16-A"),
            _make_row(date(2026, 4, 22), key="W16-B"),
        ]
        with caplog.at_level(logging.WARNING, logger="backend.services.pdf_reader"):
            result, db, batch = _run_bulk_insert(rows)

        guard_warnings = [
            r for r in caplog.records
            if r.levelno >= logging.WARNING
            and "bulk_insert_rides" in r.getMessage()
            and "Skipped" in r.getMessage()
        ]
        assert guard_warnings, (
            "A WARNING must be logged when out-of-period rides are skipped. "
            f"Captured records: {[r.getMessage() for r in caplog.records]}"
        )
        msg = guard_warnings[0].getMessage()
        assert "2" in msg, f"Warning must mention the count (2). Got: {msg}"

    def test_batch_notes_annotated_when_out_of_period(self):
        rows = [
            _make_row(date(2026, 4, 20), key="OOP-1"),
            _make_row(date(2026, 4, 24), key="OOP-2"),
        ]
        result, db, batch = _run_bulk_insert(rows)

        assert "[date-range-guard]" in (batch.notes or ""), (
            f"batch.notes must contain '[date-range-guard]'. Got: {batch.notes!r}"
        )
        assert "2" in (batch.notes or ""), (
            "batch.notes annotation must include the skipped count (2)"
        )

    def test_already_imported_false_when_all_out_of_period(self):
        """A batch where every ride is out-of-period is NOT a duplicate import.
        already_imported must be False so the batch is not deleted."""
        rows = [_make_row(date(2026, 4, 20), key="OOP")]
        result, db, batch = _run_bulk_insert(rows)
        assert result["already_imported"] is False, (
            "A bad-PDF upload (all out-of-period) must not be treated as a duplicate. "
            f"already_imported={result['already_imported']}"
        )


# ---------------------------------------------------------------------------
# Test 3 — mixed in-period and out-of-period
# ---------------------------------------------------------------------------

class TestMixedRides:
    """Only in-period rides are inserted; out-of-period count is reflected in notes."""

    def test_only_in_period_rides_inserted(self):
        rows = [
            _make_row(date(2026, 4, 13), key="IN-1"),   # in period
            _make_row(date(2026, 4, 20), key="OUT-1"),  # out of period (W16)
            _make_row(date(2026, 4, 17), key="IN-2"),   # in period
            _make_row(date(2026, 4, 21), key="OUT-2"),  # out of period (W16)
            _make_row(date(2026, 4, 19), key="IN-3"),   # in period (boundary)
        ]
        result, db, batch = _run_bulk_insert(rows)

        assert result["inserted"] == 3, (
            f"3 in-period rides expected; got {result['inserted']}"
        )
        assert result["out_of_period"] == 2, (
            f"2 out-of-period rides expected; got {result['out_of_period']}"
        )

    def test_mixed_notes_reflect_out_of_period_count(self):
        rows = [
            _make_row(date(2026, 4, 14), key="IN"),
            _make_row(date(2026, 4, 22), key="OUT"),
        ]
        result, db, batch = _run_bulk_insert(rows)

        assert "[date-range-guard]" in (batch.notes or ""), (
            "batch.notes must carry guard annotation for partial out-of-period batch"
        )
        assert "1" in (batch.notes or ""), (
            "batch.notes must record the count of skipped rides (1)"
        )

    def test_mixed_warning_shows_correct_count(self, caplog):
        rows = [
            _make_row(date(2026, 4, 15), key="IN"),
            _make_row(date(2026, 4, 25), key="OUT"),
        ]
        with caplog.at_level(logging.WARNING, logger="backend.services.pdf_reader"):
            result, db, batch = _run_bulk_insert(rows)

        guard_warnings = [
            r for r in caplog.records
            if r.levelno >= logging.WARNING
            and "bulk_insert_rides" in r.getMessage()
            and "Skipped" in r.getMessage()
        ]
        assert guard_warnings, "WARNING must fire for the one out-of-period ride"
        msg = guard_warnings[0].getMessage()
        assert "1" in msg, f"Warning must say 1 skipped. Got: {msg}"


# ---------------------------------------------------------------------------
# Test 4 — boundary dates (period_start and period_end inclusive)
# ---------------------------------------------------------------------------

class TestBoundaryDates:
    """Rides on exactly period_start and period_end must be inserted, not skipped."""

    def test_period_start_date_is_included(self):
        rows = [_make_row(date(2026, 4, 13), key="START")]
        result, db, batch = _run_bulk_insert(rows)

        assert result["inserted"] == 1, (
            f"Ride on period_start must be inserted. Got inserted={result['inserted']}"
        )
        assert result["out_of_period"] == 0

    def test_period_end_date_is_included(self):
        rows = [_make_row(date(2026, 4, 19), key="END")]
        result, db, batch = _run_bulk_insert(rows)

        assert result["inserted"] == 1, (
            f"Ride on period_end must be inserted. Got inserted={result['inserted']}"
        )
        assert result["out_of_period"] == 0

    def test_one_day_before_start_is_excluded(self):
        rows = [_make_row(date(2026, 4, 12), key="BEFORE")]
        result, db, batch = _run_bulk_insert(rows)

        assert result["out_of_period"] == 1, (
            f"Ride one day before period_start must be skipped. Got out_of_period={result['out_of_period']}"
        )
        assert result["inserted"] == 0

    def test_one_day_after_end_is_excluded(self):
        rows = [_make_row(date(2026, 4, 20), key="AFTER")]
        result, db, batch = _run_bulk_insert(rows)

        assert result["out_of_period"] == 1, (
            f"Ride one day after period_end must be skipped. Got out_of_period={result['out_of_period']}"
        )
        assert result["inserted"] == 0

    def test_both_boundary_dates_included_together(self):
        rows = [
            _make_row(date(2026, 4, 13), key="START"),
            _make_row(date(2026, 4, 19), key="END"),
        ]
        result, db, batch = _run_bulk_insert(rows)

        assert result["inserted"] == 2, "Both boundary-date rides must be inserted"
        assert result["out_of_period"] == 0

    def test_date_as_pandas_timestamp_coerced(self):
        """Guard must handle pd.Timestamp ride dates (the real ingest format)."""
        import pandas as pd

        ts = pd.Timestamp("2026-04-15")
        rows = [_make_row(ts, key="TS-IN")]
        result, db, batch = _run_bulk_insert(rows)

        assert result["inserted"] == 1, (
            f"pd.Timestamp ride date in-period must be inserted. Got {result['inserted']}"
        )
        assert result["out_of_period"] == 0

    def test_out_of_period_datetime_coerced(self):
        """Guard must handle datetime ride dates (not just date)."""
        dt = datetime(2026, 4, 20, 8, 30)
        rows = [_make_row(dt, key="DT-OUT")]
        result, db, batch = _run_bulk_insert(rows)

        assert result["out_of_period"] == 1, (
            f"datetime ride date out-of-period must be skipped. Got {result['out_of_period']}"
        )
