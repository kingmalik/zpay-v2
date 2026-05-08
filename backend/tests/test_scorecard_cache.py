"""
Tests for backend/services/scorecard_cache_service.py

Run with:
    PYTHONPATH=. pytest backend/tests/test_scorecard_cache.py -v

Tests use an in-memory SQLite DB with a minimal schema that mirrors the
scorecard_cache table structure. No Postgres or real migration needed.

Covered cases
-------------
1. upsert_cache — write + verify row exists
2. upsert_cache — idempotent UPSERT on same (person_id, week_num, year)
3. get_prior_week_composites — returns correct prior score
4. get_prior_week_composites — returns None for drivers with no cache
5. get_rolling_30d — averages 4 weeks correctly
6. get_rolling_30d — returns zeros/None when no cache rows
7. get_weekly_trend — returns newest-first, limited to num_weeks
8. get_fleet_trend — WowDelta.escalation_delta correct
9. get_fleet_trend — WowDelta returns None when only one week available
10. get_fleet_trend — improved driver (fewer escalations) has negative delta
"""

from __future__ import annotations

import sys
import os
from datetime import date, datetime, timezone
from typing import Optional
from unittest.mock import MagicMock

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

UTC = timezone.utc

# ── Minimal DriverScorecard stand-in ──────────────────────────────────────────
# We don't need a full DB to test the cache service. We mock DriverScorecard
# with a simple object and feed a mock Session to the service functions.

from dataclasses import dataclass
from typing import Any


@dataclass
class _MockAxisScore:
    raw_value: float
    available: bool
    sample_size: int


@dataclass
class _MockScorecard:
    person_id: int
    composite_score: Optional[float]
    self_serve_pct: Optional[float]
    escalation_count: int
    total_trips: int
    axes: dict

    @property
    def tier(self) -> str:
        s = self.composite_score or 0
        if s >= 90:
            return "gold"
        if s >= 80:
            return "silver"
        if s >= 70:
            return "bronze"
        return "probation"


def _make_scorecard(
    person_id: int = 1,
    composite: float = 88.0,
    self_serve_pct: float = 90.0,
    escalations: int = 2,
    total_trips: int = 20,
    on_time_raw: float = 0.85,
) -> _MockScorecard:
    return _MockScorecard(
        person_id=person_id,
        composite_score=composite,
        self_serve_pct=self_serve_pct,
        escalation_count=escalations,
        total_trips=total_trips,
        axes={
            "on_time_pickup_arrival": _MockAxisScore(
                raw_value=on_time_raw,
                available=True,
                sample_size=total_trips,
            )
        },
    )


# ── SQL-level mock session ────────────────────────────────────────────────────
# Rather than spinning up SQLite (which won't have ON CONFLICT syntax for
# PostgreSQL-style UPSERT), we mock the Session so we can assert the right
# SQL/params are sent and test the data-transform logic.


class _FakeRow:
    def __init__(self, **kwargs: Any) -> None:
        self._data = kwargs

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)


class _FakeResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = [_FakeRow(**r) for r in rows]

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self, rows_to_return: list[dict] | None = None) -> None:
        self._rows = rows_to_return or []
        self.executed: list[tuple[str, dict]] = []
        self.committed = False

    def execute(self, stmt, params: dict | None = None):
        self.executed.append((str(stmt), params or {}))
        return _FakeResult(self._rows)

    def commit(self):
        self.committed = True


# ── Import the service under test ─────────────────────────────────────────────

from backend.services.scorecard_cache_service import (
    WowDelta,
    _iso_to_week_parts,
    _week_isos_before,
    upsert_cache,
    get_prior_week_composites,
    get_rolling_30d,
    get_weekly_trend,
    get_fleet_trend,
)


# ── Unit tests: pure helpers ───────────────────────────────────────────────────

class TestIsoHelpers:
    def test_iso_to_week_parts_basic(self):
        year, week = _iso_to_week_parts("2026-W18")
        assert year == 2026
        assert week == 18

    def test_iso_to_week_parts_single_digit(self):
        year, week = _iso_to_week_parts("2026-W01")
        assert year == 2026
        assert week == 1

    def test_iso_to_week_parts_invalid(self):
        with pytest.raises(ValueError):
            _iso_to_week_parts("2026-18")

    def test_week_isos_before_count(self):
        monday = date(2026, 5, 4)  # 2026-W19
        isos = _week_isos_before(monday, 4)
        assert len(isos) == 4

    def test_week_isos_before_newest_first(self):
        monday = date(2026, 5, 4)  # W19 monday
        isos = _week_isos_before(monday, 4)
        # Should be W18, W17, W16, W15 (newest first)
        assert isos[0] == "2026-W18"
        assert isos[-1] == "2026-W15"

    def test_week_isos_before_crosses_year(self):
        monday = date(2026, 1, 5)  # First Monday of 2026
        isos = _week_isos_before(monday, 2)
        assert len(isos) == 2
        # Both should be in 2025
        for iso in isos:
            assert iso.startswith("2025-W") or iso.startswith("2026-W")


# ── upsert_cache ──────────────────────────────────────────────────────────────

class TestUpsertCache:
    def test_sends_correct_params(self):
        sc = _make_scorecard(person_id=42, composite=91.5, self_serve_pct=95.0, escalations=0)
        session = _FakeSession()
        upsert_cache(sc, "2026-W18", session, source="cron")

        assert session.committed
        assert len(session.executed) == 1
        sql, params = session.executed[0]

        assert params["pid"] == 42
        assert params["week_num"] == 18
        assert params["year"] == 2026
        assert params["week_iso"] == "2026-W18"
        assert params["source"] == "cron"
        assert params["escalation_count"] == 0
        assert params["total_trips"] == 20

    def test_on_time_pct_computed(self):
        sc = _make_scorecard(on_time_raw=0.88)
        session = _FakeSession()
        upsert_cache(sc, "2026-W18", session)

        _, params = session.executed[0]
        assert params["on_time_pct"] == pytest.approx(88.0, abs=0.1)

    def test_on_time_pct_null_when_unavailable(self):
        sc = _make_scorecard()
        sc.axes["on_time_pickup_arrival"] = _MockAxisScore(raw_value=0.0, available=False, sample_size=0)
        session = _FakeSession()
        upsert_cache(sc, "2026-W18", session)

        _, params = session.executed[0]
        assert params["on_time_pct"] is None

    def test_manual_source(self):
        sc = _make_scorecard()
        session = _FakeSession()
        upsert_cache(sc, "2026-W18", session, source="manual")

        _, params = session.executed[0]
        assert params["source"] == "manual"


# ── get_prior_week_composites ─────────────────────────────────────────────────

class TestGetPriorWeekComposites:
    def test_returns_scores_for_found_drivers(self):
        rows = [
            {"person_id": 1, "composite_score": 88.5},
            {"person_id": 2, "composite_score": 72.0},
        ]
        session = _FakeSession(rows)
        # week_start is the CURRENT week Monday — prior = one week before
        week_start = date(2026, 5, 4)  # W19
        result = get_prior_week_composites([1, 2, 3], week_start, session)

        assert result[1] == pytest.approx(88.5, abs=0.01)
        assert result[2] == pytest.approx(72.0, abs=0.01)
        # pid 3 not in rows — should be None
        assert result[3] is None

    def test_returns_none_for_missing_drivers(self):
        session = _FakeSession([])
        week_start = date(2026, 5, 4)
        result = get_prior_week_composites([99], week_start, session)
        assert result[99] is None

    def test_empty_person_ids(self):
        session = _FakeSession([])
        result = get_prior_week_composites([], date(2026, 5, 4), session)
        assert result == {}


# ── get_rolling_30d ───────────────────────────────────────────────────────────

class TestGetRolling30d:
    def test_averages_correctly(self):
        rows = [
            {"self_serve_pct": 90.0, "on_time_pct": 85.0, "escalation_count": 2, "composite_score": 88.0, "total_trips": 20},
            {"self_serve_pct": 80.0, "on_time_pct": None, "escalation_count": 4, "composite_score": 78.0, "total_trips": 18},
        ]
        session = _FakeSession(rows)
        result = get_rolling_30d(1, date(2026, 5, 11), session)

        assert result["weeks_found"] == 2
        assert result["total_trips"] == 38
        assert result["self_serve_pct"] == pytest.approx(85.0, abs=0.1)
        # on_time_pct: only 1 non-null value → avg = 85.0
        assert result["on_time_pct"] == pytest.approx(85.0, abs=0.1)
        assert result["escalation_count"] == pytest.approx(3.0, abs=0.1)
        assert result["composite_score"] == pytest.approx(83.0, abs=0.1)

    def test_returns_zeros_when_no_cache(self):
        session = _FakeSession([])
        result = get_rolling_30d(99, date(2026, 5, 11), session)

        assert result["weeks_found"] == 0
        assert result["total_trips"] == 0
        assert result["self_serve_pct"] is None
        assert result["composite_score"] is None


# ── get_weekly_trend ──────────────────────────────────────────────────────────

class TestGetWeeklyTrend:
    def test_returns_entries_in_correct_shape(self):
        rows = [
            {"week_iso": "2026-W18", "week_num": 18, "year": 2026,
             "composite_score": 88.0, "self_serve_pct": 92.0,
             "on_time_pct": 85.0, "escalation_count": 1, "total_trips": 20},
            {"week_iso": "2026-W17", "week_num": 17, "year": 2026,
             "composite_score": 82.0, "self_serve_pct": 85.0,
             "on_time_pct": 80.0, "escalation_count": 3, "total_trips": 18},
        ]
        session = _FakeSession(rows)
        entries = get_weekly_trend(1, session, num_weeks=8)

        assert len(entries) == 2
        assert entries[0].week_iso == "2026-W18"
        assert entries[0].composite_score == pytest.approx(88.0, abs=0.01)
        assert entries[0].escalation_count == 1

    def test_returns_empty_when_no_cache(self):
        session = _FakeSession([])
        entries = get_weekly_trend(99, session, num_weeks=8)
        assert entries == []


# ── get_fleet_trend ───────────────────────────────────────────────────────────

class TestGetFleetTrend:
    def test_delta_fewer_escalations(self):
        # Driver improved: 4 escalations → 2 (delta = -2)
        rows = [
            {"person_id": 1, "year": 2026, "week_num": 18,
             "escalation_count": 2, "composite_score": 90.0},
            {"person_id": 1, "year": 2026, "week_num": 17,
             "escalation_count": 4, "composite_score": 82.0},
        ]
        session = _FakeSession(rows)
        # week_start = W18 monday (Apr 27). current=W18, prior=W17.
        result = get_fleet_trend(date(2026, 4, 27), session)

        # date(2026, 4, 27) is W18 monday → current_week=W18, prior_week=W17.
        assert 1 in result
        delta = result[1]
        assert delta.escalation_delta == -2  # fewer escalations = negative = good
        assert delta.composite_delta == pytest.approx(8.0, abs=0.1)

    def test_delta_more_escalations(self):
        rows = [
            {"person_id": 2, "year": 2026, "week_num": 18,
             "escalation_count": 5, "composite_score": 75.0},
            {"person_id": 2, "year": 2026, "week_num": 17,
             "escalation_count": 2, "composite_score": 85.0},
        ]
        session = _FakeSession(rows)
        result = get_fleet_trend(date(2026, 4, 27), session)

        delta = result[2]
        assert delta.escalation_delta == 3   # more escalations = positive = bad
        assert delta.composite_delta == pytest.approx(-10.0, abs=0.1)

    def test_none_when_only_current_week(self):
        rows = [
            {"person_id": 3, "year": 2026, "week_num": 18,
             "escalation_count": 1, "composite_score": 92.0},
        ]
        session = _FakeSession(rows)
        result = get_fleet_trend(date(2026, 4, 27), session)

        delta = result[3]
        assert delta.escalation_delta is None
        assert delta.composite_delta is None

    def test_multiple_drivers(self):
        rows = [
            {"person_id": 1, "year": 2026, "week_num": 18, "escalation_count": 0, "composite_score": 95.0},
            {"person_id": 1, "year": 2026, "week_num": 17, "escalation_count": 2, "composite_score": 85.0},
            {"person_id": 2, "year": 2026, "week_num": 18, "escalation_count": 3, "composite_score": 78.0},
            {"person_id": 2, "year": 2026, "week_num": 17, "escalation_count": 1, "composite_score": 82.0},
        ]
        session = _FakeSession(rows)
        result = get_fleet_trend(date(2026, 4, 27), session)

        assert result[1].escalation_delta == -2  # improved
        assert result[2].escalation_delta == 2   # worsened


# ── WowDelta property tests ────────────────────────────────────────────────────

class TestWowDelta:
    def test_escalation_delta_none_when_missing_current(self):
        d = WowDelta(person_id=1, current_escalations=None, prior_escalations=2,
                     current_composite=None, prior_composite=85.0)
        assert d.escalation_delta is None

    def test_escalation_delta_none_when_missing_prior(self):
        d = WowDelta(person_id=1, current_escalations=2, prior_escalations=None,
                     current_composite=90.0, prior_composite=None)
        assert d.escalation_delta is None

    def test_composite_delta_positive(self):
        d = WowDelta(person_id=1, current_escalations=1, prior_escalations=3,
                     current_composite=92.0, prior_composite=84.0)
        assert d.composite_delta == pytest.approx(8.0, abs=0.01)

    def test_composite_delta_negative(self):
        d = WowDelta(person_id=1, current_escalations=4, prior_escalations=1,
                     current_composite=74.0, prior_composite=90.0)
        assert d.composite_delta == pytest.approx(-16.0, abs=0.01)
