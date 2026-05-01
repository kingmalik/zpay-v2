"""
Tests for GET /api/data/reliability/driver/{person_id}

Run with:
    PYTHONPATH=. pytest backend/tests/test_reliability_drilldown.py -x -v

Strategy: patch compute_driver_scorecard and the DB session — no HTTP layer,
no real Postgres. Tests verify routing logic, serialization shape, and error
cases.

Test matrix
-----------
 1. driver exists, has rides       → 200, correct shape
 2. driver missing (no person row) → 404
 3. driver exists, no rides        → 200, composite_score=null, empty axes, history ok
 4. invalid week format            → 400
 5. week_history has 5 entries     → last 4 prior weeks + current
 6. recent_events always a list    → empty array (stub)
 7. axes include label + nominal_weight annotations
"""

from __future__ import annotations

import sys
import os
import json
from datetime import date, timedelta
from typing import Optional
from unittest.mock import MagicMock, patch, call

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.services.driver_scorecard import DriverScorecard, AxisScore, AXIS_WEIGHTS
from backend.routes.api_data import driver_reliability_drilldown


# ── Fixture helpers ───────────────────────────────────────────────────────────

def _make_axis(name: str, raw: float = 0.9, norm: float = 0.9, n: int = 5) -> AxisScore:
    w = AXIS_WEIGHTS.get(name, 0.0)
    return AxisScore(
        name=name,
        raw_value=raw,
        normalized_value=norm,
        weight=w,
        weighted_score=norm * w * 100,
        sample_size=n,
        available=name != "on_time_completion",
        low_confidence=False,
    )


def _all_axes(raw: float = 0.9, norm: float = 0.9) -> dict:
    return {k: _make_axis(k, raw=raw, norm=norm) for k in AXIS_WEIGHTS}


def _make_scorecard(
    person_id: int,
    week_start: date,
    composite: Optional[float],
    tier: str = "gold",
    tier_label: str = "Tier 1",
    total_trips: int = 5,
) -> DriverScorecard:
    week_iso = f"{week_start.isocalendar().year}-W{week_start.isocalendar().week:02d}"
    return DriverScorecard(
        person_id=person_id,
        driver_name="Test Driver",
        week_start=week_start,
        week_iso=week_iso,
        total_trips=total_trips if composite is not None else 0,
        axes=_all_axes() if composite is not None else {},
        composite_score=composite,
        tier=tier,
        tier_label=tier_label,
        low_sample=total_trips < 3,
        week_over_week_delta=None,
        headline_metric="Acceptance 90% — top 25%",
        focus_area="",
        revenue_impact=0.0,
        revenue_impact_per_trip=0.0,
        revenue_rank=None,
    )


def _mock_person(person_id: int = 1, name: str = "Test Driver") -> MagicMock:
    p = MagicMock()
    p.person_id = person_id
    p.full_name = name
    p.paycheck_code = "1042"
    p.paycheck_code_maz = None
    p.active = True
    return p


def _mock_db(person: Optional[MagicMock] = None) -> MagicMock:
    """Return a mock DB session whose query chain returns the given person (or None)."""
    db = MagicMock()
    q = MagicMock()
    db.query.return_value = q
    q.filter.return_value = q
    q.first.return_value = person
    return db


CURRENT_WEEK = date(2026, 4, 27)  # a known Monday


# ── Test 1: driver exists, has rides → 200 + correct shape ───────────────────

def test_drilldown_driver_exists():
    person = _mock_person(person_id=42)
    db = _mock_db(person=person)

    sc = _make_scorecard(42, CURRENT_WEEK, composite=88.5, tier="silver")

    with patch(
        "backend.routes.api_data.compute_driver_scorecard",
        return_value=sc,
    ):
        response = driver_reliability_drilldown(
            person_id=42,
            week="2026-W18",
            db=db,
        )

    assert response.status_code == 200
    body = json.loads(response.body)

    # Top-level keys
    assert "driver" in body
    assert "current_week" in body
    assert "weekly_history" in body
    assert "recent_events" in body

    # Driver info
    d = body["driver"]
    assert d["person_id"] == 42
    assert d["name"] == "Test Driver"
    assert d["paycheck_code"] == "1042"
    assert d["active"] is True

    # Current week
    cw = body["current_week"]
    assert cw["composite_score"] == 88.5
    assert cw["tier"] == "silver"
    assert "axes" in cw


# ── Test 2: driver missing → 404 ─────────────────────────────────────────────

def test_drilldown_driver_missing_returns_404():
    db = _mock_db(person=None)

    response = driver_reliability_drilldown(
        person_id=9999,
        week="2026-W18",
        db=db,
    )

    assert response.status_code == 404
    body = json.loads(response.body)
    assert "not found" in body["error"].lower()


# ── Test 3: driver exists, no rides → 200, composite null, history ok ─────────

def test_drilldown_driver_no_rides():
    person = _mock_person(person_id=7)
    db = _mock_db(person=person)

    empty_sc = _make_scorecard(7, CURRENT_WEEK, composite=None, tier="no_activity", total_trips=0)

    with patch(
        "backend.routes.api_data.compute_driver_scorecard",
        return_value=empty_sc,
    ):
        response = driver_reliability_drilldown(
            person_id=7,
            week="2026-W18",
            db=db,
        )

    assert response.status_code == 200
    body = json.loads(response.body)
    assert body["current_week"]["composite_score"] is None
    assert body["current_week"]["tier"] == "no_activity"
    # weekly_history is always 5 entries (4 prior + current)
    assert len(body["weekly_history"]) == 5


# ── Test 4: invalid week format → 400 ────────────────────────────────────────

def test_drilldown_invalid_week_returns_400():
    db = _mock_db(person=_mock_person())

    response = driver_reliability_drilldown(
        person_id=1,
        week="2026/18",
        db=db,
    )

    assert response.status_code == 400
    body = json.loads(response.body)
    assert "error" in body


# ── Test 5: weekly_history has exactly 5 entries ──────────────────────────────

def test_drilldown_weekly_history_length():
    person = _mock_person(person_id=3)
    db = _mock_db(person=person)

    sc = _make_scorecard(3, CURRENT_WEEK, composite=75.0, tier="bronze")

    with patch(
        "backend.routes.api_data.compute_driver_scorecard",
        return_value=sc,
    ):
        response = driver_reliability_drilldown(
            person_id=3,
            week="2026-W18",
            db=db,
        )

    body = json.loads(response.body)
    history = body["weekly_history"]
    # 4 prior weeks + current week = 5 entries
    assert len(history) == 5
    # Each entry has the required keys
    for entry in history:
        assert "week_iso" in entry
        assert "week_start" in entry
        assert "composite_score" in entry
        assert "tier" in entry
        assert "total_trips" in entry


# ── Test 6: recent_events is always a list ────────────────────────────────────

def test_drilldown_recent_events_is_empty_list():
    person = _mock_person()
    db = _mock_db(person=person)
    sc = _make_scorecard(1, CURRENT_WEEK, composite=92.0)

    with patch(
        "backend.routes.api_data.compute_driver_scorecard",
        return_value=sc,
    ):
        response = driver_reliability_drilldown(
            person_id=1,
            week="2026-W18",
            db=db,
        )

    body = json.loads(response.body)
    assert isinstance(body["recent_events"], list)


# ── Test 7: axes include label + nominal_weight annotations ───────────────────

def test_drilldown_axes_annotated():
    person = _mock_person()
    db = _mock_db(person=person)
    sc = _make_scorecard(1, CURRENT_WEEK, composite=88.0)

    with patch(
        "backend.routes.api_data.compute_driver_scorecard",
        return_value=sc,
    ):
        response = driver_reliability_drilldown(
            person_id=1,
            week="2026-W18",
            db=db,
        )

    body = json.loads(response.body)
    axes = body["current_week"]["axes"]
    assert len(axes) > 0

    for axis_key, axis_data in axes.items():
        assert "label" in axis_data, f"Missing 'label' on axis {axis_key}"
        assert "nominal_weight" in axis_data, f"Missing 'nominal_weight' on axis {axis_key}"
        assert isinstance(axis_data["label"], str)
        assert isinstance(axis_data["nominal_weight"], float)
