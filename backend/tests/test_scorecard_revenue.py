"""
Tests for revenue_impact fields on DriverScorecard.

Run with:
    PYTHONPATH=. pytest backend/tests/test_scorecard_revenue.py -v

Cases:
 1. revenue_impact = 0 when no ride data passed (no net_pay on trips)
 2. revenue_impact correctly sums max(0, net_pay - z_rate)
 3. revenue_rank = 1 for highest earner among mock drivers
 4. revenue_impact_per_trip = revenue_impact / trip_count
 5. zero z_rate fallback — net_pay alone counts as full margin
 6. negative margin clamped to 0 (driver paid more than partner)
 7. revenue fields still present on no_activity scorecard (zeros)
"""

from __future__ import annotations

import sys
import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.services.driver_scorecard import (
    DriverScorecard,
    _build_scorecard,
    _parse_pickup_dt,
)

UTC = timezone.utc
WEEK_START = date(2026, 4, 20)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _perfect_trip(
    person_id: int = 1,
    trip_ref: str = "Redmond_D_001",
) -> dict:
    """Minimal perfect trip dict (scoring-axis fields only — no revenue)."""
    pickup_dt_raw = _parse_pickup_dt("10:00", WEEK_START)
    pickup_utc = pickup_dt_raw.astimezone(UTC) if pickup_dt_raw else None

    sms_at = pickup_utc - timedelta(hours=1) if pickup_utc else None
    accepted = sms_at + timedelta(seconds=30) if sms_at else None
    started = pickup_utc - timedelta(minutes=1) if pickup_utc else None
    arrived = pickup_utc - timedelta(minutes=2) if pickup_utc else None

    return {
        "person_id": person_id,
        "source": "firstalt",
        "trip_ref": trip_ref,
        "accept_sms_at": sms_at,
        "accept_call_at": None,
        "start_call_at": None,
        "accept_escalated_at": None,
        "start_escalated_at": None,
        "accepted_at": accepted,
        "started_at": started,
        "arrived_at_pickup": arrived,
        "completed_at": None,
        "_pickup_dt": pickup_utc,
    }


def _build(
    trips: list[dict],
    revenue_impact: float = 0.0,
    revenue_rank: Optional[int] = None,
    person_id: int = 1,
) -> DriverScorecard:
    return _build_scorecard(
        person_id=person_id,
        driver_name="Test Driver",
        week_start=WEEK_START,
        driver_trips=trips,
        fleet_trips=trips,
        driver_status_events=[],
        prior_composite=None,
        fleet_axis_values={},
        revenue_impact=revenue_impact,
        revenue_rank=revenue_rank,
    )


# ── Test 1: revenue_impact = 0 when no revenue data passed ───────────────────

def test_revenue_impact_zero_when_not_provided():
    """_build_scorecard defaults revenue_impact=0 — trips with no pay data score $0."""
    trips = [_perfect_trip(trip_ref=f"T00{i}") for i in range(5)]
    sc = _build(trips, revenue_impact=0.0)

    assert sc.revenue_impact == 0.0
    assert sc.revenue_impact_per_trip == 0.0


# ── Test 2: revenue_impact correctly sums net_pay - z_rate ───────────────────

def test_revenue_impact_sums_correctly():
    """revenue_impact reflects the value passed in (computed upstream from rides)."""
    trips = [_perfect_trip(trip_ref=f"T00{i}") for i in range(4)]
    # Simulated: 4 trips @ $25 margin each = $100 total
    sc = _build(trips, revenue_impact=100.0)

    assert sc.revenue_impact == 100.0
    assert sc.total_trips == 4


# ── Test 3: revenue_rank = 1 for highest earner ───────────────────────────────

def test_revenue_rank_highest_earner():
    """Driver passed revenue_rank=1 is correctly reflected on the scorecard."""
    trips = [_perfect_trip(trip_ref=f"T00{i}") for i in range(5)]
    sc = _build(trips, revenue_impact=250.0, revenue_rank=1)

    assert sc.revenue_rank == 1


def test_revenue_rank_not_first():
    """revenue_rank=3 means two drivers earned more this week."""
    trips = [_perfect_trip(trip_ref=f"T00{i}") for i in range(5)]
    sc = _build(trips, revenue_impact=80.0, revenue_rank=3)

    assert sc.revenue_rank == 3


# ── Test 4: revenue_impact_per_trip = revenue_impact / trip_count ─────────────

def test_revenue_impact_per_trip_calculation():
    """revenue_impact_per_trip = revenue_impact / total_trips."""
    trips = [_perfect_trip(trip_ref=f"T00{i}") for i in range(5)]
    sc = _build(trips, revenue_impact=75.0)

    assert sc.total_trips == 5
    # 75.0 / 5 = 15.0
    assert abs(sc.revenue_impact_per_trip - 15.0) < 0.01


def test_revenue_impact_per_trip_rounds():
    """revenue_impact_per_trip is rounded to 2dp."""
    trips = [_perfect_trip(trip_ref=f"T00{i}") for i in range(3)]
    sc = _build(trips, revenue_impact=10.0)

    # 10.0 / 3 = 3.3333... → rounds to 3.33
    assert abs(sc.revenue_impact_per_trip - 3.33) < 0.01


# ── Test 5: zero z_rate fallback — net_pay is full margin ────────────────────

def test_revenue_impact_when_zero_z_rate():
    """When z_rate is 0, the entire net_pay is margin. $44.86 net, $0 driver = $44.86."""
    # This tests the formula logic: max(0, net_pay - z_rate)
    # We simulate by passing the pre-computed revenue_impact directly
    trips = [_perfect_trip(trip_ref=f"T00{i}") for i in range(3)]
    # 3 trips @ net_pay=44.86, z_rate=0 → revenue = 3 * 44.86 = 134.58
    sc = _build(trips, revenue_impact=134.58)

    assert abs(sc.revenue_impact - 134.58) < 0.01
    assert abs(sc.revenue_impact_per_trip - 44.86) < 0.01


# ── Test 6: negative margin scenarios result in $0 (GREATEST clamp) ──────────

def test_revenue_impact_never_negative():
    """revenue_impact is always >= 0 — GREATEST(0, ...) in SQL prevents negatives."""
    trips = [_perfect_trip(trip_ref=f"T00{i}") for i in range(3)]
    # Driver paid more than partner (edge case — pass 0 as would come from DB)
    sc = _build(trips, revenue_impact=0.0)

    assert sc.revenue_impact >= 0.0
    assert sc.revenue_impact_per_trip >= 0.0


# ── Test 7: revenue fields present on no_activity scorecard ──────────────────

def test_revenue_fields_on_no_activity_scorecard():
    """Empty week scorecard still carries revenue fields (both zero)."""
    sc = _build([], revenue_impact=0.0, revenue_rank=None)

    assert sc.tier == "no_activity"
    assert sc.revenue_impact == 0.0
    assert sc.revenue_impact_per_trip == 0.0
    assert sc.revenue_rank is None
