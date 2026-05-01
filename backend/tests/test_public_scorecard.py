"""
backend/tests/test_public_scorecard.py
=======================================
Tests for GET /api/public/driver/{person_id}/scorecard

Run with:
    PYTHONPATH=. pytest backend/tests/test_public_scorecard.py -x -v

Strategy: patch compute_driver_scorecard + DB session — no HTTP layer, no
real Postgres. Tests verify routing logic, serialization shape, and that the
public endpoint never leaks internal fields.

Test matrix
-----------
 1. 200 with seeded driver that has rides
 2. 404 with missing driver (no person row)
 3. Response excludes paycheck_code, paycheck_code_maz, person_id, internal IDs
 4. Response includes correct axis labels (AXIS_LABELS values, not raw keys)
 5. Inactive driver still resolves — drivers share old links
"""

from __future__ import annotations

import sys
import os
import json
from datetime import date
from typing import Optional
from unittest.mock import MagicMock, patch  # patch used in individual test cases

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.services.driver_scorecard import (
    DriverScorecard,
    AxisScore,
    AXIS_WEIGHTS,
    AXIS_LABELS,
)
from backend.routes.public import _scorecard_response


# ── Fixture helpers ───────────────────────────────────────────────────────────

def _make_axis(name: str, raw: float = 0.88, n: int = 5) -> AxisScore:
    w = AXIS_WEIGHTS.get(name, 0.0)
    return AxisScore(
        name=name,
        raw_value=raw,
        normalized_value=raw,
        weight=w,
        weighted_score=raw * w * 100,
        sample_size=n,
        available=name != "on_time_completion",
        low_confidence=False,
    )


def _all_axes(raw: float = 0.88) -> dict:
    return {k: _make_axis(k, raw=raw) for k in AXIS_WEIGHTS}


def _make_scorecard(
    person_id: int = 1,
    composite: Optional[float] = 85.0,
    tier: str = "silver",
    tier_label: str = "Tier 2",
    total_trips: int = 6,
) -> DriverScorecard:
    week_start = date(2026, 4, 27)
    week_iso = f"{week_start.isocalendar().year}-W{week_start.isocalendar().week:02d}"
    return DriverScorecard(
        person_id=person_id,
        driver_name="Ahmed Abdi",
        week_start=week_start,
        week_iso=week_iso,
        total_trips=total_trips if composite is not None else 0,
        axes=_all_axes() if composite is not None else {},
        composite_score=composite,
        tier=tier,
        tier_label=tier_label,
        low_sample=total_trips < 3,
        week_over_week_delta=None,
        headline_metric="Acceptance 88% — top 25%",
        focus_area="",
    )


def _mock_person(
    person_id: int = 1,
    full_name: str = "Ahmed Abdi",
    paycheck_code: str = "1099",
    paycheck_code_maz: Optional[str] = "2055",
    active: bool = True,
) -> MagicMock:
    p = MagicMock()
    p.person_id = person_id
    p.full_name = full_name
    p.paycheck_code = paycheck_code
    p.paycheck_code_maz = paycheck_code_maz
    p.active = active
    return p


def _mock_db(person: Optional[MagicMock] = None) -> MagicMock:
    db = MagicMock()
    q = MagicMock()
    db.query.return_value = q
    q.filter.return_value = q
    q.first.return_value = person
    return db


def _call(person_id: int, db: MagicMock):
    """Call the inner logic function directly (no HTTP/limiter layer)."""
    return _scorecard_response(person_id=person_id, db=db)


# ── Test 1: 200 with seeded driver ────────────────────────────────────────────

def test_public_scorecard_200_driver_with_rides():
    person = _mock_person(person_id=42)
    db = _mock_db(person=person)
    sc = _make_scorecard(person_id=42, composite=85.0, tier="silver")

    with patch(
        "backend.routes.public.compute_driver_scorecard",
        return_value=sc,
    ):
        response = _call(42, db)

    assert response.status_code == 200
    body = json.loads(response.body)

    assert body["first_name"] == "Ahmed"
    assert body["tier"] == "silver"
    assert body["tier_label"] == "Tier 2"
    assert body["composite_score"] == 85.0
    assert "axes" in body
    assert "trend" in body
    assert len(body["trend"]) == 5  # 4 prior + current


# ── Test 2: 404 with missing driver ───────────────────────────────────────────

def test_public_scorecard_404_missing_driver():
    db = _mock_db(person=None)

    response = _call(9999, db)

    assert response.status_code == 404
    body = json.loads(response.body)
    assert "error" in body
    assert "not found" in body["error"].lower()


# ── Test 3: Response excludes internal fields ─────────────────────────────────

def test_public_scorecard_excludes_internal_fields():
    """paycheck_code, paycheck_code_maz, person_id must NOT appear in response."""
    person = _mock_person(person_id=7, paycheck_code="1042", paycheck_code_maz="2033")
    db = _mock_db(person=person)
    sc = _make_scorecard(person_id=7, composite=78.0)

    with patch(
        "backend.routes.public.compute_driver_scorecard",
        return_value=sc,
    ):
        response = _call(7, db)

    body = json.loads(response.body)
    raw_text = response.body.decode()

    # Hard checks: these strings must not appear anywhere in the response body
    assert "paycheck_code" not in raw_text
    assert "person_id" not in raw_text
    # first_name only — full name "Ahmed Abdi" → only "Ahmed" should appear
    assert "Abdi" not in raw_text

    # Per-axis data must also be clean
    for axis_val in body["axes"].values():
        assert "weight" not in axis_val
        assert "weighted_score" not in axis_val
        assert "normalized_value" not in axis_val


# ── Test 4: Response includes correct axis labels ─────────────────────────────

def test_public_scorecard_axis_labels_are_human_readable():
    """Axes use AXIS_LABELS values, not raw snake_case keys."""
    person = _mock_person()
    db = _mock_db(person=person)
    sc = _make_scorecard(composite=90.0)

    with patch(
        "backend.routes.public.compute_driver_scorecard",
        return_value=sc,
    ):
        response = _call(1, db)

    body = json.loads(response.body)
    axes = body["axes"]

    assert len(axes) > 0
    for axis_key, axis_data in axes.items():
        assert "label" in axis_data
        assert "value_pct" in axis_data
        assert "available" in axis_data
        # Label must match AXIS_LABELS (not the raw snake_case key)
        expected_label = AXIS_LABELS.get(axis_key)
        if expected_label:
            assert axis_data["label"] == expected_label, (
                f"axis '{axis_key}': expected label '{expected_label}', got '{axis_data['label']}'"
            )


# ── Test 5: Inactive driver still resolves ────────────────────────────────────

def test_public_scorecard_inactive_driver_resolves():
    """active=False drivers must still return 200 — they share old SMS links."""
    person = _mock_person(person_id=55, active=False)
    db = _mock_db(person=person)
    sc = _make_scorecard(person_id=55, composite=72.0, tier="bronze", tier_label="Tier 3")

    with patch(
        "backend.routes.public.compute_driver_scorecard",
        return_value=sc,
    ):
        response = _call(55, db)

    assert response.status_code == 200
    body = json.loads(response.body)
    assert body["tier"] == "bronze"
    assert body["composite_score"] == 72.0
