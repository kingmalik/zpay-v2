"""
Tests for the weekly window extension to GET /dispatch/manage/reliability

Run with:
    PYTHONPATH=. pytest backend/tests/test_reliability_weekly.py -v

Strategy: tests call the handler function directly with a mock DB session so
no HTTP layer or real Postgres is needed. The weekly path delegates to
driver_scorecard.compute_all_active_drivers — that function is patched with
a controlled list of DriverScorecard instances so we test routing logic,
serialization, sorting, and validation without re-testing scorecard math.

The rolling90 regression test patches the SQLAlchemy query chain and verifies
the original response shape is preserved.

Test matrix
-----------
 1. ?window=weekly, no week param      → defaults to current PT ISO week
 2. ?window=weekly&week=2026-W17       → calls service with 2026-04-20 week_start
 3. Invalid week format → 400
 4. ?window=rolling90 (explicit)       → returns original dict shape (regression)
 5. window omitted                     → rolling90 path, original shape (regression)
 6. ?window=bad_value                  → 400
 7. no_activity drivers omitted        → not present in weekly response
 8. sorted by composite_score desc     → gold driver appears before bronze
 9. WoW delta present when set         → wow_delta in response row
10. WoW delta null when None           → wow_delta=null in response row
"""

from __future__ import annotations

import sys
import os
import json
from datetime import date, timedelta
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.services.driver_scorecard import DriverScorecard, AxisScore, AXIS_WEIGHTS
from backend.routes.dispatch_manage import (
    driver_reliability,
    _parse_iso_week,
    _current_pt_week_start,
    _scorecard_to_dict,
)


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
    tier_label: str = "Tier 1",
    week_iso: str = "2026-W17",
    wow_delta: Optional[float] = None,
) -> DriverScorecard:
    return DriverScorecard(
        person_id=person_id,
        driver_name=driver_name,
        week_start=date(2026, 4, 20),
        week_iso=week_iso,
        total_trips=5 if composite is not None else 0,
        axes=_all_axes() if composite is not None else {},
        composite_score=composite,
        tier=tier,
        tier_label=tier_label,
        low_sample=False,
        week_over_week_delta=wow_delta,
        headline_metric="Acceptance 100% — top 10%",
        focus_area="",
        revenue_impact=0.0,
        revenue_impact_per_trip=0.0,
        revenue_rank=None,
    )


def _mock_db() -> MagicMock:
    return MagicMock()


# ── _parse_iso_week unit tests ────────────────────────────────────────────────

def test_parse_iso_week_valid():
    d = _parse_iso_week("2026-W17")
    assert d == date(2026, 4, 20)


def test_parse_iso_week_zero_padded():
    d = _parse_iso_week("2026-W01")
    assert d == date.fromisocalendar(2026, 1, 1)


def test_parse_iso_week_invalid_no_dash():
    with pytest.raises(ValueError):
        _parse_iso_week("202617")


def test_parse_iso_week_invalid_letters():
    with pytest.raises(ValueError):
        _parse_iso_week("2026-Wxx")


def test_parse_iso_week_week_out_of_range():
    with pytest.raises(ValueError):
        _parse_iso_week("2026-W54")


# ── _current_pt_week_start ────────────────────────────────────────────────────

def test_current_pt_week_start_is_monday():
    d = _current_pt_week_start()
    assert d.weekday() == 0, f"Expected Monday (0), got {d.weekday()} for {d}"


# ── _scorecard_to_dict ────────────────────────────────────────────────────────

def test_scorecard_to_dict_shape():
    sc = _make_scorecard(1, "Alice Driver", 95.0, tier="gold", wow_delta=3.5)
    row = _scorecard_to_dict(sc)

    assert row["person_id"] == 1
    assert row["driver_name"] == "Alice Driver"
    assert row["composite_score"] == 95.0
    assert row["tier"] == "gold"
    assert row["tier_label"] == "Tier 1"
    assert row["wow_delta"] == 3.5
    assert "axes" in row
    # Each axis entry has the required keys
    for axis_row in row["axes"].values():
        assert "raw" in axis_row
        assert "normalized" in axis_row
        assert "weighted" in axis_row
        assert "sample_size" in axis_row
        assert "available" in axis_row


def test_scorecard_to_dict_null_wow():
    sc = _make_scorecard(2, "Bob Driver", 80.0, wow_delta=None)
    row = _scorecard_to_dict(sc)
    assert row["wow_delta"] is None


# ── Handler: invalid window param → 400 ──────────────────────────────────────

def test_reliability_invalid_window_returns_400():
    response = driver_reliability(window="last7days", week=None, db=_mock_db())
    assert response.status_code == 400
    body = json.loads(response.body)
    assert "window" in body["error"]


# ── Handler: invalid week format → 400 ───────────────────────────────────────

def test_reliability_invalid_week_format_returns_400():
    response = driver_reliability(window="weekly", week="2026/17", db=_mock_db())
    assert response.status_code == 400
    body = json.loads(response.body)
    assert "Invalid" in body["error"] or "week" in body["error"].lower()


def test_reliability_invalid_week_letters_returns_400():
    response = driver_reliability(window="weekly", week="2026-Wab", db=_mock_db())
    assert response.status_code == 400


# ── Handler: weekly mode, explicit week ───────────────────────────────────────

def test_reliability_weekly_explicit_week():
    """?window=weekly&week=2026-W17 calls service with 2026-04-20 week_start."""
    sc_gold = _make_scorecard(1, "Alpha Driver", 95.0, tier="gold")
    sc_silver = _make_scorecard(2, "Beta Driver", 82.0, tier="silver", tier_label="Tier 2")

    with patch(
        "backend.routes.dispatch_manage.compute_all_active_drivers",
        return_value=[sc_gold, sc_silver],
    ) as mock_fn:
        response = driver_reliability(window="weekly", week="2026-W17", db=_mock_db())

    mock_fn.assert_called_once_with(date(2026, 4, 20), mock_fn.call_args[0][1])
    assert response.status_code == 200
    rows = json.loads(response.body)
    assert len(rows) == 2
    assert rows[0]["person_id"] == 1  # gold first (higher composite)
    assert rows[1]["person_id"] == 2


# ── Handler: weekly mode, no week → defaults to current PT week ───────────────

def test_reliability_weekly_defaults_to_current_week():
    """?window=weekly with no week param → week_start is the current PT Monday."""
    expected_week_start = _current_pt_week_start()

    with patch(
        "backend.routes.dispatch_manage.compute_all_active_drivers",
        return_value=[],
    ) as mock_fn:
        response = driver_reliability(window="weekly", week=None, db=_mock_db())

    called_week_start = mock_fn.call_args[0][0]
    assert called_week_start == expected_week_start
    assert response.status_code == 200


# ── Handler: no_activity drivers omitted ─────────────────────────────────────

def test_reliability_weekly_omits_no_activity():
    sc_active = _make_scorecard(1, "Active Driver", 88.0, tier="silver")
    sc_inactive = _make_scorecard(2, "Idle Driver", None, tier="no_activity", tier_label="No Activity")

    with patch(
        "backend.routes.dispatch_manage.compute_all_active_drivers",
        return_value=[sc_active, sc_inactive],
    ):
        response = driver_reliability(window="weekly", week="2026-W17", db=_mock_db())

    rows = json.loads(response.body)
    ids = [r["person_id"] for r in rows]
    assert 1 in ids
    assert 2 not in ids


# ── Handler: sorted by composite descending ───────────────────────────────────

def test_reliability_weekly_sorted_desc():
    sc_bronze = _make_scorecard(3, "Charlie", 72.0, tier="bronze", tier_label="Tier 3")
    sc_gold = _make_scorecard(1, "Alpha", 95.0, tier="gold")
    sc_silver = _make_scorecard(2, "Beta", 83.0, tier="silver", tier_label="Tier 2")

    # Return intentionally out of order
    with patch(
        "backend.routes.dispatch_manage.compute_all_active_drivers",
        return_value=[sc_bronze, sc_gold, sc_silver],
    ):
        response = driver_reliability(window="weekly", week="2026-W17", db=_mock_db())

    rows = json.loads(response.body)
    scores = [r["composite_score"] for r in rows]
    assert scores == sorted(scores, reverse=True), f"Expected descending order: {scores}"


# ── Handler: WoW delta present and null ──────────────────────────────────────

def test_reliability_weekly_wow_delta_populated():
    sc = _make_scorecard(1, "Driver A", 90.0, wow_delta=5.0)
    with patch(
        "backend.routes.dispatch_manage.compute_all_active_drivers",
        return_value=[sc],
    ):
        response = driver_reliability(window="weekly", week="2026-W17", db=_mock_db())

    rows = json.loads(response.body)
    assert rows[0]["wow_delta"] == 5.0


def test_reliability_weekly_wow_delta_null():
    sc = _make_scorecard(1, "Driver B", 80.0, wow_delta=None)
    with patch(
        "backend.routes.dispatch_manage.compute_all_active_drivers",
        return_value=[sc],
    ):
        response = driver_reliability(window="weekly", week="2026-W17", db=_mock_db())

    rows = json.loads(response.body)
    assert rows[0]["wow_delta"] is None


# ── Regression: rolling90 explicit and default paths unchanged ────────────────

def _make_trip_notification_row(person_id: int, total: int, accepted: int, started: int, escalated: int):
    row = MagicMock()
    row.person_id = person_id
    row.total = total
    row.accepted = accepted
    row.started = started
    row.escalated = escalated
    return row


def _mock_db_with_rows(rows):
    """Return a mock db session whose query().filter().group_by().all() returns rows."""
    mock_query = MagicMock()
    mock_query.filter.return_value = mock_query
    mock_query.group_by.return_value = mock_query
    mock_query.all.return_value = rows

    db = MagicMock()
    db.query.return_value = mock_query
    return db


def test_reliability_rolling90_explicit_returns_dict_shape():
    """?window=rolling90 → returns original dict keyed by person_id."""
    rows = [_make_trip_notification_row(person_id=42, total=10, accepted=9, started=8, escalated=0)]
    db = _mock_db_with_rows(rows)

    response = driver_reliability(window="rolling90", week=None, db=db)
    assert response.status_code == 200
    body = json.loads(response.body)

    # Original shape: dict keyed by person_id (as int or string)
    key = 42  # JSON keys are always strings in JSON
    body_by_str = {int(k): v for k, v in body.items()}
    assert 42 in body_by_str
    row = body_by_str[42]
    assert "total_trips" in row
    assert "acceptance_rate" in row
    assert "started_rate" in row
    assert "escalation_rate" in row
    assert "tier" in row


def test_reliability_window_omitted_returns_rolling90_shape():
    """No window param → same rolling90 shape as explicit rolling90."""
    rows = [_make_trip_notification_row(person_id=7, total=5, accepted=5, started=5, escalated=0)]
    db = _mock_db_with_rows(rows)

    response = driver_reliability(window=None, week=None, db=db)
    assert response.status_code == 200
    body = json.loads(response.body)
    body_by_int = {int(k): v for k, v in body.items()}
    assert 7 in body_by_int
    assert "tier" in body_by_int[7]
    assert "total_trips" in body_by_int[7]
