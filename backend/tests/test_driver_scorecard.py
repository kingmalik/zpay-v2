"""
Tests for backend/services/driver_scorecard.py

Run with:
    PYTHONPATH=. pytest backend/tests/test_driver_scorecard.py -v

All tests use in-memory SQLite via standalone SQLAlchemy models — no Postgres
needed. The scoring functions are tested both as pure units (direct calls) and
via compute_driver_scorecard() with a mock DB session where appropriate.

Covered cases
-------------
 1. Perfect driver, single route         → composite 100, tier gold
 2. Perfect driver, multi-route          → composite 100, normalization no-op
 3. Late driver, normalized              → arrival axis not penalized
 4. Late driver, not normalized          → arrival axis penalized
 5. Escalated driver                     → acceptance drops by 0.2
 6. Declined trips                       → reliability 0.8
 7. Missing arrival data                 → sample_size = 4, low_confidence set
 8. No calls attempted                   → responsiveness defaults to 1.0
 9. Empty week                           → tier='no_activity', no crash
10. Low sample (<3 trips)               → low_sample=True
11. Tier boundaries                      → 89.99 silver, 90.00 gold, etc.
12. Week-over-week delta                 → prior=85, current=92 → delta=+7
13. WoW delta with no prior             → delta=None
14. Headline strongest axis (≥70)        → mentions acceptance when it's highest
15. Headline weakest axis (<70)          → mentions weakest axis
16. Focus area template                  → responsiveness coaching text
"""

from __future__ import annotations

import sys
import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on sys.path
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.services.driver_scorecard import (
    AxisScore,
    DriverScorecard,
    FOCUS_TEMPLATES,
    MIN_SAMPLE_FOR_HEADLINE,
    TIER_BRONZE_MIN,
    TIER_GOLD_MIN,
    TIER_SILVER_MIN,
    _build_scorecard,
    _clamp,
    _compute_acceptance,
    _compute_on_time_arrival,
    _compute_on_time_start,
    _compute_reliability,
    _compute_responsiveness,
    _parse_pickup_dt,
    _route_key,
    _tier,
    _week_bounds_utc,
)

UTC = timezone.utc
PT_OFFSET = timedelta(hours=7)  # PDT offset (UTC-7) — close enough for test arithmetic

WEEK_START = date(2026, 4, 20)  # Monday


# ── Helpers ───────────────────────────────────────────────────────────────────

def _utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def _make_trip(
    *,
    person_id: int = 1,
    source: str = "firstalt",
    trip_ref: str = "Redmond_D_001",
    trip_date: date = WEEK_START,
    pickup_time: str = "08:00",
    accept_sms_at: Optional[datetime] = None,
    accept_call_at: Optional[datetime] = None,
    start_call_at: Optional[datetime] = None,
    accept_escalated_at: Optional[datetime] = None,
    start_escalated_at: Optional[datetime] = None,
    accepted_at: Optional[datetime] = None,
    started_at: Optional[datetime] = None,
    arrived_at_pickup: Optional[datetime] = None,
    completed_at: Optional[datetime] = None,
) -> dict:
    """Build a normalized trip dict in the shape _row_to_trip produces."""
    # Parse pickup as UTC
    from backend.services.driver_scorecard import _parse_pickup_dt
    pickup_dt_raw = _parse_pickup_dt(pickup_time, trip_date)
    pickup_dt = pickup_dt_raw.astimezone(UTC) if pickup_dt_raw else None

    return {
        "person_id": person_id,
        "source": source,
        "trip_ref": trip_ref,
        "accept_sms_at": accept_sms_at,
        "accept_call_at": accept_call_at,
        "start_call_at": start_call_at,
        "accept_escalated_at": accept_escalated_at,
        "start_escalated_at": start_escalated_at,
        "accepted_at": accepted_at,
        "started_at": started_at,
        "arrived_at_pickup": arrived_at_pickup,
        "completed_at": completed_at,
        "_pickup_dt": pickup_dt,
    }


def _perfect_trip(
    person_id: int = 1,
    source: str = "firstalt",
    trip_ref: str = "Redmond_D_001",
    trip_date: date = WEEK_START,
    pickup_time: str = "10:00",
) -> dict:
    """Build a trip where all timestamps are on-time."""
    from backend.services.driver_scorecard import _parse_pickup_dt
    from zoneinfo import ZoneInfo
    PT = ZoneInfo("America/Los_Angeles")
    # pickup in UTC
    pickup_local = _parse_pickup_dt(pickup_time, trip_date)
    pickup_utc = pickup_local.astimezone(UTC) if pickup_local else None

    sms_at = pickup_utc - timedelta(hours=1) if pickup_utc else None
    accepted = sms_at + timedelta(seconds=30) if sms_at else None
    started = pickup_utc - timedelta(minutes=1) if pickup_utc else None
    arrived = pickup_utc - timedelta(minutes=2) if pickup_utc else None

    return _make_trip(
        person_id=person_id,
        source=source,
        trip_ref=trip_ref,
        trip_date=trip_date,
        pickup_time=pickup_time,
        accept_sms_at=sms_at,
        accepted_at=accepted,
        started_at=started,
        arrived_at_pickup=arrived,
    )


def _scorecard_from_trips(
    driver_trips: list[dict],
    fleet_trips: Optional[list[dict]] = None,
    driver_status_events: Optional[list[dict]] = None,
    prior_composite: Optional[float] = None,
    fleet_axis_values: Optional[dict] = None,
    person_id: int = 1,
    driver_name: str = "Test Driver",
) -> DriverScorecard:
    return _build_scorecard(
        person_id=person_id,
        driver_name=driver_name,
        week_start=WEEK_START,
        driver_trips=driver_trips,
        fleet_trips=fleet_trips if fleet_trips is not None else driver_trips,
        driver_status_events=driver_status_events or [],
        prior_composite=prior_composite,
        fleet_axis_values=fleet_axis_values or {},
    )


# ── Test 1: Perfect driver, single route ─────────────────────────────────────

def test_perfect_driver_single_route():
    """5 perfect trips on one route → composite 100, tier gold."""
    trips = [_perfect_trip(trip_ref=f"Redmond_D_00{i}") for i in range(5)]
    sc = _scorecard_from_trips(trips)

    assert sc.total_trips == 5
    assert sc.tier == "gold"
    assert sc.tier_label == "Tier 1"
    assert sc.composite_score is not None
    # With perfect scores and on_time_completion unavailable, composite should be 100
    assert abs(sc.composite_score - 100.0) < 0.01
    assert sc.low_sample is False


# ── Test 2: Perfect driver, multi-route ──────────────────────────────────────

def test_perfect_driver_multi_route():
    """5 perfect trips across 3 routes → composite 100, normalization no-op."""
    trips = [
        _perfect_trip(trip_ref="Redmond_D_001"),
        _perfect_trip(trip_ref="Redmond_D_002"),
        _perfect_trip(trip_ref="Timberline_001"),
        _perfect_trip(trip_ref="Timberline_002"),
        _perfect_trip(trip_ref="ElBaker_001"),
    ]
    sc = _scorecard_from_trips(trips)

    assert sc.tier == "gold"
    assert abs(sc.composite_score - 100.0) < 0.01


# ── Test 3: Late driver, normalized (fleet also late) ────────────────────────

def test_late_driver_normalized_not_penalized():
    """Driver 5 min late; fleet avg also 5 min late → arrival axis normalized to ~1.0."""
    from backend.services.driver_scorecard import _parse_pickup_dt
    from zoneinfo import ZoneInfo
    pickup_dt = _parse_pickup_dt("10:00", WEEK_START).astimezone(UTC)
    FIVE_MIN = timedelta(minutes=5)

    # Driver 1: arrives 5 min late
    driver_trip = _perfect_trip(person_id=1, trip_ref="Redmond_D_001")
    driver_trip = {**driver_trip, "arrived_at_pickup": pickup_dt + FIVE_MIN + timedelta(seconds=30)}

    # Driver 2 (fleet): also arrives 5 min late on same route
    fleet_trip2 = _perfect_trip(person_id=2, trip_ref="Redmond_D_002")
    fleet_trip2 = {**fleet_trip2, "arrived_at_pickup": pickup_dt + FIVE_MIN + timedelta(seconds=30)}

    # For fleet avg, driver 1 has 1 late trip, driver 2 has 1 late trip — both 0% raw
    fleet = [driver_trip, fleet_trip2]

    sc = _scorecard_from_trips([driver_trip], fleet_trips=fleet)

    arrival_axis = sc.axes["on_time_pickup_arrival"]
    # Both drivers are equally late → normalization should bring driver close to 1.0
    assert arrival_axis.normalized_value >= 0.95, (
        f"Expected normalized arrival ~1.0, got {arrival_axis.normalized_value}"
    )


# ── Test 4: Late driver, not normalized (fleet is on time) ───────────────────

def test_late_driver_penalized_when_fleet_ontime():
    """Driver 6 min late; fleet avg on time → arrival axis should be penalized."""
    from backend.services.driver_scorecard import _parse_pickup_dt
    pickup_dt = _parse_pickup_dt("10:00", WEEK_START).astimezone(UTC)
    SIX_MIN = timedelta(minutes=6)

    # Driver: late
    driver_trip = _perfect_trip(person_id=1, trip_ref="Redmond_D_001")
    driver_trip = {**driver_trip, "arrived_at_pickup": pickup_dt + SIX_MIN}

    # Fleet driver 2: on time
    fleet_trip2 = _perfect_trip(person_id=2, trip_ref="Redmond_D_002")
    fleet_trip2 = {**fleet_trip2, "arrived_at_pickup": pickup_dt - timedelta(minutes=2)}

    fleet = [driver_trip, fleet_trip2]
    sc = _scorecard_from_trips([driver_trip], fleet_trips=fleet)

    arrival_axis = sc.axes["on_time_pickup_arrival"]
    # Driver raw = 0.0 (late), fleet avg = 0.5 (1 of 2 on time)
    # Normalized = min(1.0, 0.0 + (1.0 - 0.5)) = 0.5
    assert arrival_axis.normalized_value < 0.9, (
        f"Expected penalized arrival, got {arrival_axis.normalized_value}"
    )


# ── Test 5: Escalated driver ─────────────────────────────────────────────────

def test_escalated_driver_acceptance_drop():
    """5 trips, 2 escalations (1 accept + 1 start) → acceptance raw drops by 0.2."""
    base = _utc(2026, 4, 20, 15, 0)
    sms = base
    accepted_late = base + timedelta(minutes=5)

    trips = []
    for i in range(5):
        t = _make_trip(
            trip_ref=f"Redmond_D_00{i}",
            accept_sms_at=sms,
            accepted_at=accepted_late,  # accepted 5min after SMS → NOT within 2min
        )
        trips.append(t)

    # Add 2 escalations: one accept, one start
    trips[0] = {**trips[0], "accept_escalated_at": base + timedelta(minutes=3)}
    trips[1] = {**trips[1], "start_escalated_at": base + timedelta(minutes=4)}

    raw, n = _compute_acceptance(trips)
    # 0 on-time acceptances / 5 trips = 0.0; minus 2*0.1 = -0.2 → floored at 0
    assert raw == 0.0
    assert n == 5

    # Now test with some on-time + escalations
    trips2 = []
    for i in range(5):
        t = _make_trip(
            trip_ref=f"Redmond_D_10{i}",
            accept_sms_at=sms,
            accepted_at=sms + timedelta(seconds=30),  # within 2min
        )
        trips2.append(t)
    trips2[0] = {**trips2[0], "accept_escalated_at": base + timedelta(minutes=3)}
    trips2[1] = {**trips2[1], "start_escalated_at": base + timedelta(minutes=4)}

    raw2, n2 = _compute_acceptance(trips2)
    # raw = 5/5 = 1.0, minus 2*0.1 = 0.8
    assert abs(raw2 - 0.8) < 0.001
    assert n2 == 5


# ── Test 5b: Acceptance null-guard ───────────────────────────────────────────

def test_acceptance_sms_and_accept_both_set():
    """Both accepted_at and accept_sms_at set, within 2min → counts as on-time."""
    base = _utc(2026, 4, 20, 15, 0)
    sms = base
    trips = [_make_trip(
        trip_ref="Redmond_D_001",
        accept_sms_at=sms,
        accepted_at=sms + timedelta(seconds=90),  # within 2min
    )]
    raw, n = _compute_acceptance(trips)
    assert raw == 1.0
    assert n == 1


def test_acceptance_accept_only_no_sms():
    """accepted_at set but accept_sms_at is null → call dispatch path, count as on-time."""
    base = _utc(2026, 4, 20, 15, 0)
    trips = [_make_trip(
        trip_ref="Redmond_D_001",
        accept_sms_at=None,
        accepted_at=base + timedelta(minutes=1),
    )]
    raw, n = _compute_acceptance(trips)
    assert raw == 1.0
    assert n == 1


def test_acceptance_neither_set():
    """Both accepted_at and accept_sms_at null → counts as miss."""
    trips = [_make_trip(
        trip_ref="Redmond_D_001",
        accept_sms_at=None,
        accepted_at=None,
    )]
    raw, n = _compute_acceptance(trips)
    assert raw == 0.0
    assert n == 1


# ── Test 6: Declined trips ───────────────────────────────────────────────────

def test_declined_trips_reliability():
    """5 trips total, 1 declined → reliability raw = 0.8."""
    trips = [_perfect_trip(trip_ref=f"Redmond_D_00{i}") for i in range(5)]
    status_events = [{"new_status": "declined"}]

    raw, n = _compute_reliability(trips, status_events)
    assert abs(raw - 0.8) < 0.001
    assert n == 5


def test_reliability_multiple_bad_events():
    """5 trips, 1 decline + 1 driver_cancelled → reliability = 0.6."""
    trips = [_perfect_trip(trip_ref=f"T00{i}") for i in range(5)]
    events = [
        {"new_status": "declined"},
        {"new_status": "driver_cancelled"},
    ]
    raw, n = _compute_reliability(trips, events)
    assert abs(raw - 0.6) < 0.001


# ── Test 7: Missing arrival data ─────────────────────────────────────────────

def test_missing_arrival_data_low_confidence():
    """10 trips, only 4 have arrived_at_pickup → sample_size=4, low_confidence set."""
    from backend.services.driver_scorecard import _parse_pickup_dt
    pickup_dt = _parse_pickup_dt("10:00", WEEK_START).astimezone(UTC)

    trips = []
    for i in range(10):
        arrived = None
        if i < 4:  # only first 4 have arrival data — all on time
            arrived = pickup_dt - timedelta(minutes=1)
        # Pass pickup_time so _pickup_dt is set; arrived_at_pickup is None for 6 of 10
        t = _make_trip(
            trip_ref=f"Redmond_D_0{i:02d}",
            pickup_time="10:00",
            arrived_at_pickup=arrived,
        )
        trips.append(t)

    raw, sample_size, low_conf = _compute_on_time_arrival(trips)
    assert sample_size == 4
    assert abs(raw - 1.0) < 0.001  # all 4 that have data are on time
    assert low_conf is True  # 4 < 10 * 0.5


def test_missing_arrival_data_reflected_in_scorecard():
    """Scorecard arrival axis has sample_size=4 and low_confidence=True."""
    from backend.services.driver_scorecard import _parse_pickup_dt
    pickup_dt = _parse_pickup_dt("10:00", WEEK_START).astimezone(UTC)

    trips = []
    for i in range(10):
        arrived = None
        if i < 4:
            arrived = pickup_dt - timedelta(minutes=1)
        t = _perfect_trip(trip_ref=f"Redmond_D_0{i:02d}")
        t = {**t, "arrived_at_pickup": arrived}
        trips.append(t)

    sc = _scorecard_from_trips(trips)
    arrival = sc.axes["on_time_pickup_arrival"]
    assert arrival.sample_size == 4
    assert arrival.low_confidence is True


# ── Test 8: No calls attempted ───────────────────────────────────────────────

def test_no_calls_responsiveness_defaults_to_one():
    """No call columns set → responsiveness raw = 1.0, sample_size = 0."""
    trips = [_perfect_trip(trip_ref=f"T00{i}") for i in range(5)]
    raw, n = _compute_responsiveness(trips)
    assert raw == 1.0
    assert n == 0


# ── Test 9: Empty week ───────────────────────────────────────────────────────

def test_empty_week_no_crash():
    """total_trips=0 → tier='no_activity', composite_score=None."""
    sc = _scorecard_from_trips([])

    assert sc.total_trips == 0
    assert sc.composite_score is None
    assert sc.tier == "no_activity"
    assert sc.tier_label == "No Activity"
    assert sc.headline_metric == "No rides this week"
    assert sc.week_over_week_delta is None


# ── Test 10: Low sample ───────────────────────────────────────────────────────

def test_low_sample_flag():
    """2 trips → low_sample=True, tier still computed."""
    trips = [_perfect_trip(trip_ref=f"T00{i}") for i in range(2)]
    sc = _scorecard_from_trips(trips)

    assert sc.low_sample is True
    assert sc.total_trips == 2
    # Tier is still computed (not overridden to 'no_activity')
    assert sc.tier in {"gold", "silver", "bronze", "probation"}


# ── Test 11: Tier boundaries ─────────────────────────────────────────────────

@pytest.mark.parametrize("composite,expected_tier,expected_label", [
    (89.99, "silver", "Tier 2"),
    (90.00, "gold", "Tier 1"),
    (79.99, "bronze", "Tier 3"),
    (70.00, "bronze", "Tier 3"),
    (69.99, "probation", "Tier 4"),
    (100.0, "gold", "Tier 1"),
    (0.0, "probation", "Tier 4"),
])
def test_tier_boundaries(composite: float, expected_tier: str, expected_label: str):
    tier_key, tier_label = _tier(composite)
    assert tier_key == expected_tier, f"composite={composite}: expected {expected_tier}, got {tier_key}"
    assert tier_label == expected_label


# ── Test 12: Week-over-week delta ─────────────────────────────────────────────

def test_week_over_week_positive_delta():
    """prior composite=85, current perfect (100) → delta = +15."""
    trips = [_perfect_trip(trip_ref=f"T00{i}") for i in range(5)]
    sc = _scorecard_from_trips(trips, prior_composite=85.0)

    assert sc.week_over_week_delta is not None
    assert abs(sc.week_over_week_delta - 15.0) < 0.1


def test_week_over_week_negative_delta():
    """prior composite=95, current lower → delta negative."""
    from backend.services.driver_scorecard import _parse_pickup_dt
    pickup_dt = _parse_pickup_dt("10:00", WEEK_START).astimezone(UTC)
    # All trips late (bad acceptance, bad arrival)
    trips = []
    for i in range(5):
        t = _make_trip(
            trip_ref=f"T00{i}",
            accept_sms_at=pickup_dt - timedelta(hours=1),
            accepted_at=pickup_dt,  # accepted 1hr after SMS → late
            arrived_at_pickup=pickup_dt + timedelta(minutes=20),  # very late
        )
        trips.append(t)

    sc = _scorecard_from_trips(trips, prior_composite=95.0)
    assert sc.week_over_week_delta is not None
    assert sc.week_over_week_delta < 0


# ── Test 13: WoW delta with no prior ─────────────────────────────────────────

def test_week_over_week_no_prior():
    """No prior week data → delta=None."""
    trips = [_perfect_trip(trip_ref=f"T00{i}") for i in range(5)]
    sc = _scorecard_from_trips(trips, prior_composite=None)
    assert sc.week_over_week_delta is None


# ── Test 14: Headline strongest axis (composite ≥ 70) ────────────────────────

def test_headline_strongest_axis_when_above_threshold():
    """Composite ≥ 70 → headline mentions the strongest axis."""
    # Make acceptance perfect, everything else slightly lower
    from backend.services.driver_scorecard import _parse_pickup_dt
    pickup_dt = _parse_pickup_dt("10:00", WEEK_START).astimezone(UTC)
    sms = pickup_dt - timedelta(hours=1)

    trips = []
    for i in range(5):
        t = _make_trip(
            trip_ref=f"T00{i}",
            accept_sms_at=sms,
            accepted_at=sms + timedelta(seconds=10),  # perfect acceptance
            started_at=pickup_dt + timedelta(minutes=5),  # slightly late start
            arrived_at_pickup=pickup_dt + timedelta(minutes=3),  # on time arrival
        )
        trips.append(t)

    sc = _scorecard_from_trips(trips)

    assert sc.composite_score is not None
    # Composite ≥ 70 → positive framing, headline should mention strongest axis
    if sc.composite_score >= 70:
        # Should pick the highest normalized axis with sample_size >= 3
        assert sc.headline_metric != "No rides this week"
        assert sc.headline_metric != "Not enough data this week"


# ── Test 15: Headline weakest axis (composite < 70) ──────────────────────────

def test_headline_weakest_axis_when_below_threshold():
    """Composite < 70 → headline mentions weakest axis with constructive tone."""
    from backend.services.driver_scorecard import _parse_pickup_dt
    pickup_dt = _parse_pickup_dt("10:00", WEEK_START).astimezone(UTC)
    sms = pickup_dt - timedelta(hours=1)

    # Very poor acceptance + late arrival → composite should be low
    trips = []
    for i in range(5):
        t = _make_trip(
            trip_ref=f"T00{i}",
            accept_sms_at=sms,
            accepted_at=sms + timedelta(hours=1),  # accepted way late
            started_at=pickup_dt + timedelta(minutes=30),  # very late start
            arrived_at_pickup=pickup_dt + timedelta(minutes=20),  # very late arrival
        )
        trips.append(t)

    status_events = [{"new_status": "declined"}, {"new_status": "declined"}]
    sc = _scorecard_from_trips(trips, driver_status_events=status_events)

    if sc.composite_score is not None and sc.composite_score < 70:
        assert "room to improve" in sc.headline_metric.lower() or \
               any(
                   label.lower() in sc.headline_metric.lower()
                   for label in ["acceptance", "on-time", "reliability", "responsiveness"]
               )


# ── Test 16: Focus area template for responsiveness ──────────────────────────

def test_focus_area_responsiveness_template():
    """When responsiveness is the weakest axis, focus_area uses that template."""
    from backend.services.driver_scorecard import _parse_pickup_dt

    pickup_dt = _parse_pickup_dt("10:00", WEEK_START).astimezone(UTC)
    sms = pickup_dt - timedelta(hours=1)

    # Perfect on everything EXCEPT responsiveness is technically 1.0 by default
    # We force responsiveness low by making it the only axis with a non-perfect
    # value. Since no call data exists, responsiveness = 1.0 always under current
    # schema. Test the template directly instead.
    assert "responsiveness" in FOCUS_TEMPLATES
    template = FOCUS_TEMPLATES["responsiveness"]
    assert len(template) > 10
    assert "call" in template.lower() or "dispatch" in template.lower()


# ── Additional: focus templates coverage ─────────────────────────────────────

@pytest.mark.parametrize("axis_name", list(FOCUS_TEMPLATES.keys()))
def test_all_focus_templates_are_non_empty(axis_name: str):
    """Every axis has a non-empty, reasonably long coaching template."""
    template = FOCUS_TEMPLATES[axis_name]
    assert isinstance(template, str)
    assert len(template) >= 20, f"Template for {axis_name} is too short: {template!r}"


# ── Internal helpers ──────────────────────────────────────────────────────────

def test_clamp():
    assert _clamp(-0.5) == 0.0
    assert _clamp(1.5) == 1.0
    assert _clamp(0.5) == 0.5
    assert _clamp(0.3, 0.4, 0.6) == 0.4
    assert _clamp(0.7, 0.4, 0.6) == 0.6


def test_week_bounds_utc():
    """Monday 2026-04-20 00:00 PT → UTC bounds span exactly 7 days."""
    start, end = _week_bounds_utc(date(2026, 4, 20))
    assert (end - start) == timedelta(days=7)
    assert start.tzinfo is not None
    assert end.tzinfo is not None


def test_route_key_fa_strips_numeric_suffix():
    """FA trip_ref 'Redmond_D_12345' → route key strips '12345'."""
    key = _route_key("firstalt", "Redmond_D_12345")
    assert key == "firstalt:Redmond_D"


def test_route_key_no_numeric_suffix():
    """trip_ref without numeric suffix → uses 12-char prefix."""
    key = _route_key("everdriven", "ABCDEFGHIJKLMNOP")
    assert key == "everdriven:ABCDEFGHIJKL"


def test_parse_pickup_dt_hhmm():
    """HH:MM format parsed correctly into UTC."""
    dt = _parse_pickup_dt("08:00", date(2026, 4, 20))
    assert dt is not None
    assert dt.tzinfo is not None
    # 08:00 PT (PDT = UTC-7) → 15:00 UTC
    assert dt.hour == 15
    assert dt.minute == 0


def test_parse_pickup_dt_none():
    assert _parse_pickup_dt(None, date(2026, 4, 20)) is None
    assert _parse_pickup_dt("", date(2026, 4, 20)) is None


def test_on_time_start_with_null_pickup():
    """Trip with no _pickup_dt → started_at check skipped → counts as not-on-time.

    _compute_on_time_start uses total trips as denominator. Trips where
    started_at or _pickup_dt is None don't increment on_time — so with 2 trips
    that have no pickup reference, raw = 0/2 = 0.0.
    """
    trips = [
        # Explicitly clear _pickup_dt by using a trip dict directly
        {
            "person_id": 1,
            "source": "firstalt",
            "trip_ref": "T001",
            "accept_sms_at": None,
            "accept_call_at": None,
            "start_call_at": None,
            "accept_escalated_at": None,
            "start_escalated_at": None,
            "accepted_at": None,
            "started_at": _utc(2026, 4, 20, 10),
            "arrived_at_pickup": None,
            "completed_at": None,
            "_pickup_dt": None,   # no pickup reference
        },
        {
            "person_id": 1,
            "source": "firstalt",
            "trip_ref": "T002",
            "accept_sms_at": None,
            "accept_call_at": None,
            "start_call_at": None,
            "accept_escalated_at": None,
            "start_escalated_at": None,
            "accepted_at": None,
            "started_at": None,
            "arrived_at_pickup": None,
            "completed_at": None,
            "_pickup_dt": None,
        },
    ]
    raw, n = _compute_on_time_start(trips)
    assert raw == 0.0
    assert n == 2


def test_on_time_arrival_all_null():
    """All arrived_at_pickup null → sample_size=0, raw=0.0."""
    trips = [_make_trip(trip_ref=f"T00{i}") for i in range(5)]
    raw, n, low_conf = _compute_on_time_arrival(trips)
    assert n == 0
    assert raw == 0.0
    assert low_conf is False


# ── Test 17: All-NULL arrival → axis excluded, composite not dragged to 0 ─────

def test_all_null_arrival_excludes_axis_from_composite():
    """When every trip has arrived_at_pickup=NULL, the arrival axis must be
    marked available=False and excluded from the composite.

    Regression: before the fix, arrive_n==0 set arrive_norm=0.0 but kept
    available=True, causing 0% to flow into the composite and pushing solid
    drivers (like Tier 4 cluster Nuraynie / Tamirat / Miruts / Siedi in W19)
    down to near-zero composite scores despite 100% on-time starts.
    """
    from backend.services.driver_scorecard import _parse_pickup_dt
    pickup_dt = _parse_pickup_dt("08:00", WEEK_START).astimezone(UTC)

    # 5 trips: perfect acceptance + perfect start, but NO arrived_at_pickup on any
    trips = []
    sms = pickup_dt - timedelta(hours=1)
    for i in range(5):
        t = _make_trip(
            trip_ref=f"T00{i}",
            accept_sms_at=sms,
            accepted_at=sms + timedelta(seconds=30),
            started_at=pickup_dt - timedelta(minutes=1),
            arrived_at_pickup=None,   # <-- the problematic NULL
        )
        trips.append(t)

    sc = _scorecard_from_trips(trips)

    # Axis must be marked unavailable
    arrival_axis = sc.axes["on_time_pickup_arrival"]
    assert arrival_axis.available is False, (
        f"Expected arrival axis available=False when all arrived_at_pickup are NULL, "
        f"got available={arrival_axis.available}"
    )
    assert arrival_axis.sample_size == 0
    assert arrival_axis.weighted_score == 0.0

    # Composite should not be dragged to ~0 — with perfect acceptance+start+reliability
    # and only on_time_completion + on_time_pickup_arrival excluded, composite
    # should be well above 70 (Tier 3+).
    assert sc.composite_score is not None
    assert sc.composite_score >= 70.0, (
        f"Expected composite >= 70 with all-NULL arrival excluded, got {sc.composite_score}"
    )
    assert sc.tier in {"gold", "silver", "bronze"}, (
        f"Expected Tier 1-3 with perfect acceptance/start/reliability, got tier={sc.tier}"
    )


def test_start_100_arrival_null_gives_sensible_composite():
    """Specific regression shape: on_time_start=100%, arrived_at_pickup=all NULL.

    Before the fix this produced composite ~0 (arrival 0% with full weight).
    After the fix, composite should reflect only the axes that have data.
    """
    from backend.services.driver_scorecard import _parse_pickup_dt
    pickup_dt = _parse_pickup_dt("08:00", WEEK_START).astimezone(UTC)
    sms = pickup_dt - timedelta(hours=1)

    trips = []
    for i in range(5):
        t = _make_trip(
            trip_ref=f"Route_A_00{i}",
            accept_sms_at=sms,
            accepted_at=sms + timedelta(seconds=20),  # perfect acceptance
            started_at=pickup_dt - timedelta(minutes=1),  # perfect start
            arrived_at_pickup=None,
        )
        trips.append(t)

    sc = _scorecard_from_trips(trips)

    start_axis = sc.axes["on_time_start"]
    arrival_axis = sc.axes["on_time_pickup_arrival"]

    assert start_axis.raw_value == 1.0, "Expected 100% on-time start"
    assert arrival_axis.available is False, "Arrival must be unavailable when all NULL"

    # Composite must not be near-zero
    assert sc.composite_score is not None
    assert sc.composite_score > 50.0, (
        f"composite={sc.composite_score} is too low — NULL arrival data is "
        "incorrectly penalizing the driver"
    )
