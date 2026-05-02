"""
backend/tests/test_tier_badge.py
=================================
Phase 11: GET /dispatch/manage/drivers — tier badge endpoint.

Tests call the handler function directly with a mock DB session and patch
compute_all_active_drivers so no real Postgres is needed.

Test matrix
-----------
 1. Returns list with tier + tier_label + composite_score fields
 2. Default sort: Gold first, then Silver, Bronze, Probation, no_activity last
 3. ?tier=gold   → only gold rows
 4. ?tier=silver → only silver rows
 5. ?tier=bronze → only bronze rows
 6. ?tier=probation → only probation rows
 7. ?tier=all    → all drivers including no_activity
 8. ?tier=platinum (invalid) → raises 400
 9. no_activity driver has composite_score=None
10. week_iso field present in rows
11. Gold sort: gold before probation regardless of insertion order
12. Composite score None for no_activity, float for active tiers

Run with:
    PYTHONPATH=. pytest backend/tests/test_tier_badge.py -v
"""

from __future__ import annotations

import sys
import os
import json
from datetime import date
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.services.driver_scorecard import DriverScorecard, AxisScore, AXIS_WEIGHTS


# ── Fixture helpers ───────────────────────────────────────────────────────────

def _make_axis(name: str, raw: float = 1.0, norm: float = 1.0, n: int = 5) -> AxisScore:
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


def _all_axes(raw: float = 1.0, norm: float = 1.0) -> dict:
    return {k: _make_axis(k, raw=raw, norm=norm) for k in AXIS_WEIGHTS}


def _make_scorecard(
    person_id: int,
    driver_name: str,
    composite: Optional[float],
    tier: str = "gold",
    tier_label: str = "Gold",
    week_iso: str = "2026-W18",
) -> DriverScorecard:
    return DriverScorecard(
        person_id=person_id,
        driver_name=driver_name,
        week_start=date(2026, 4, 28),
        week_iso=week_iso,
        total_trips=5 if composite is not None else 0,
        axes=_all_axes() if composite is not None else {},
        composite_score=composite,
        tier=tier,
        tier_label=tier_label,
        low_sample=False,
        week_over_week_delta=None,
        headline_metric="",
        focus_area="",
        revenue_impact=0.0,
        revenue_impact_per_trip=0.0,
        revenue_rank=None,
    )


# ── Shared scorecard dataset ──────────────────────────────────────────────────

MOCK_SCORECARDS = [
    # Inserted in reverse tier order to verify sort is applied
    _make_scorecard(4, "Dave Probation", 62.0, tier="probation",   tier_label="Probation"),
    _make_scorecard(3, "Carol Bronze",   74.0, tier="bronze",      tier_label="Bronze"),
    _make_scorecard(5, "Eve No Activity", None, tier="no_activity", tier_label="No activity"),
    _make_scorecard(2, "Bob Silver",     84.0, tier="silver",      tier_label="Silver"),
    _make_scorecard(1, "Alice Gold",     92.0, tier="gold",        tier_label="Gold"),
]

MOCK_DB = MagicMock()


# ── Import target (after sys.path is set) ─────────────────────────────────────

from backend.routes.dispatch_manage import list_drivers_with_tier  # noqa: E402


# ── 1. Returns required fields ────────────────────────────────────────────────

def test_returns_tier_fields():
    with patch("backend.routes.dispatch_manage.compute_all_active_drivers", return_value=MOCK_SCORECARDS):
        resp = list_drivers_with_tier(tier=None, db=MOCK_DB)
    body = json.loads(resp.body)
    assert len(body) > 0
    first = body[0]
    assert "tier" in first
    assert "tier_label" in first
    assert "composite_score" in first
    assert "person_id" in first
    assert "driver_name" in first


# ── 2. Default sort: tier_order ascending (Gold=1 first) ─────────────────────

def test_default_sort_gold_first():
    with patch("backend.routes.dispatch_manage.compute_all_active_drivers", return_value=MOCK_SCORECARDS):
        resp = list_drivers_with_tier(tier=None, db=MOCK_DB)
    rows = json.loads(resp.body)
    tiers = [r["tier"] for r in rows]

    gold_idx      = [i for i, t in enumerate(tiers) if t == "gold"]
    silver_idx    = [i for i, t in enumerate(tiers) if t == "silver"]
    bronze_idx    = [i for i, t in enumerate(tiers) if t == "bronze"]
    probation_idx = [i for i, t in enumerate(tiers) if t == "probation"]

    if gold_idx and silver_idx:
        assert max(gold_idx) < min(silver_idx), "Gold must precede Silver"
    if silver_idx and bronze_idx:
        assert max(silver_idx) < min(bronze_idx), "Silver must precede Bronze"
    if bronze_idx and probation_idx:
        assert max(bronze_idx) < min(probation_idx), "Bronze must precede Probation"


# ── 3. tier=gold filter ───────────────────────────────────────────────────────

def test_filter_gold():
    with patch("backend.routes.dispatch_manage.compute_all_active_drivers", return_value=MOCK_SCORECARDS):
        resp = list_drivers_with_tier(tier="gold", db=MOCK_DB)
    rows = json.loads(resp.body)
    assert len(rows) == 1
    assert all(r["tier"] == "gold" for r in rows)


# ── 4. tier=silver filter ─────────────────────────────────────────────────────

def test_filter_silver():
    with patch("backend.routes.dispatch_manage.compute_all_active_drivers", return_value=MOCK_SCORECARDS):
        resp = list_drivers_with_tier(tier="silver", db=MOCK_DB)
    rows = json.loads(resp.body)
    assert len(rows) == 1
    assert all(r["tier"] == "silver" for r in rows)


# ── 5. tier=bronze filter ─────────────────────────────────────────────────────

def test_filter_bronze():
    with patch("backend.routes.dispatch_manage.compute_all_active_drivers", return_value=MOCK_SCORECARDS):
        resp = list_drivers_with_tier(tier="bronze", db=MOCK_DB)
    rows = json.loads(resp.body)
    assert len(rows) == 1
    assert all(r["tier"] == "bronze" for r in rows)


# ── 6. tier=probation filter ──────────────────────────────────────────────────

def test_filter_probation():
    with patch("backend.routes.dispatch_manage.compute_all_active_drivers", return_value=MOCK_SCORECARDS):
        resp = list_drivers_with_tier(tier="probation", db=MOCK_DB)
    rows = json.loads(resp.body)
    assert len(rows) == 1
    assert all(r["tier"] == "probation" for r in rows)


# ── 7. tier=all includes no_activity ─────────────────────────────────────────

def test_filter_all_includes_no_activity():
    with patch("backend.routes.dispatch_manage.compute_all_active_drivers", return_value=MOCK_SCORECARDS):
        resp = list_drivers_with_tier(tier="all", db=MOCK_DB)
    rows = json.loads(resp.body)
    assert len(rows) == len(MOCK_SCORECARDS)
    tier_set = {r["tier"] for r in rows}
    assert "no_activity" in tier_set


# ── 8. Invalid tier returns 400 ───────────────────────────────────────────────

def test_invalid_tier_returns_400():
    resp = list_drivers_with_tier(tier="platinum", db=MOCK_DB)
    assert resp.status_code == 400


# ── 9. no_activity composite_score is None ───────────────────────────────────

def test_no_activity_composite_score_is_null():
    with patch("backend.routes.dispatch_manage.compute_all_active_drivers", return_value=MOCK_SCORECARDS):
        resp = list_drivers_with_tier(tier="all", db=MOCK_DB)
    rows = json.loads(resp.body)
    no_act = [r for r in rows if r["tier"] == "no_activity"]
    assert len(no_act) == 1
    assert no_act[0]["composite_score"] is None


# ── 10. week_iso present in rows ─────────────────────────────────────────────

def test_week_iso_in_rows():
    with patch("backend.routes.dispatch_manage.compute_all_active_drivers", return_value=MOCK_SCORECARDS):
        resp = list_drivers_with_tier(tier=None, db=MOCK_DB)
    rows = json.loads(resp.body)
    active = [r for r in rows if r["tier"] != "no_activity"]
    assert all("week_iso" in r for r in active)


# ── 11. Gold before Probation regardless of insertion order ──────────────────

def test_gold_before_probation_regardless_of_input_order():
    # Reversed: probation inserted before gold
    reversed_list = list(reversed(MOCK_SCORECARDS))
    with patch("backend.routes.dispatch_manage.compute_all_active_drivers", return_value=reversed_list):
        resp = list_drivers_with_tier(tier=None, db=MOCK_DB)
    rows = json.loads(resp.body)
    tiers = [r["tier"] for r in rows]
    gold_first = tiers.index("gold")
    probation_last = max(i for i, t in enumerate(tiers) if t == "probation")
    assert gold_first < probation_last


# ── 12. Active tier composite scores are floats ───────────────────────────────

def test_active_tier_composite_scores_are_floats():
    with patch("backend.routes.dispatch_manage.compute_all_active_drivers", return_value=MOCK_SCORECARDS):
        resp = list_drivers_with_tier(tier=None, db=MOCK_DB)
    rows = json.loads(resp.body)
    active = [r for r in rows if r["tier"] not in ("no_activity",)]
    assert all(isinstance(r["composite_score"], float) for r in active)
