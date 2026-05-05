"""
backend/services/driver_scorecard.py
=====================================
Pure computation module for weekly per-driver scorecards.

No DB writes. Read-only on trip_notification, trip_status_event, person.
All heavy work done in Python after 2-3 bulk queries — no N+1 queries.

Schema notes / degradations
----------------------------
- scheduled_pickup: not a datetime column — parsed from pickup_time (text) +
  trip_date using the same logic as trip_monitor._parse_pickup_time.
- scheduled_dropoff: column does not exist → on_time_completion axis is
  marked unavailable (sample_size=0, raw_value=0.0) and excluded from the
  composite denominator so weights redistribute correctly.
- responsiveness: notification_event.call_attempted/call_answered event types
  don't exist yet. We instead count trips where accept_call_at or start_call_at
  is non-null as "call attempted/answered". If no calls were attempted this
  week the axis defaults to 1.0 (no penalty for drivers who weren't called).
- escalations: read from accept_escalated_at / start_escalated_at columns
  on trip_notification (populated by trip_monitor). Each non-null escalation
  column on a trip counts as one escalation event.
- route normalization: trip_notification has no route column. Route key is
  derived from trip_ref prefix (everything before the first underscore for FA,
  full trip_ref for ED as a proxy). Single-driver routes skip normalization.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session
from sqlalchemy import text

PT = ZoneInfo("America/Los_Angeles")
UTC = timezone.utc

# ── Axis metadata ─────────────────────────────────────────────────────────────

AXIS_LABELS: dict[str, str] = {
    "acceptance": "Acceptance",
    "on_time_start": "On-time start",
    "on_time_pickup_arrival": "On-time pickup",
    "on_time_completion": "On-time dropoff",
    "responsiveness": "Responsiveness",
    "reliability": "Reliability",
}

AXIS_WEIGHTS: dict[str, float] = {
    "acceptance": 0.25,
    "on_time_start": 0.20,
    "on_time_pickup_arrival": 0.25,
    "on_time_completion": 0.10,
    "responsiveness": 0.10,
    "reliability": 0.10,
}

# Focus-area coaching templates (one per axis, non-judgmental).
FOCUS_TEMPLATES: dict[str, str] = {
    "acceptance": (
        "Try accepting ride offers within 2 minutes of the text — "
        "early responses unlock priority dispatch."
    ),
    "on_time_start": (
        "Aim to mark yourself en-route within 2 minutes of your scheduled pickup — "
        "families are watching for that status update."
    ),
    "on_time_pickup_arrival": (
        "Getting to the pickup spot on time is the #1 thing families notice — "
        "leaving 5 minutes earlier usually covers it."
    ),
    "on_time_completion": (
        "Try to complete drop-offs within 10 minutes of the scheduled time — "
        "it helps the next driver's day start smoothly."
    ),
    "responsiveness": (
        "When dispatch calls, picking up quickly helps us resolve issues faster — "
        "keep your phone volume up on driving days."
    ),
    "reliability": (
        "Fewer last-minute declines and cancellations means families always "
        "have a driver — let dispatch know early if something comes up."
    ),
}

LOW_CONFIDENCE_THRESHOLD = 0.50  # axis sample_size < 50% of total → skip normalization
MIN_SAMPLE_FOR_HEADLINE = 3  # axis needs this many trips to appear in headline/focus

# Tier thresholds
TIER_GOLD_MIN = 90.0
TIER_SILVER_MIN = 80.0
TIER_BRONZE_MIN = 70.0


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AxisScore:
    name: str
    raw_value: float           # 0.0 – 1.0 (or 0.0 when unavailable)
    normalized_value: float    # after route-normalization (0.0 – 1.0)
    weight: float              # e.g. 0.25
    weighted_score: float      # normalized_value * weight * 100
    sample_size: int           # trips that contributed
    available: bool = True     # False when axis cannot be computed (missing data)
    low_confidence: bool = False  # True when sample_size < 50% of total_trips


@dataclass(frozen=True)
class DriverScorecard:
    person_id: int
    driver_name: str
    week_start: date
    week_iso: str              # 'YYYY-WW'
    total_trips: int
    axes: dict                 # dict[str, AxisScore] — frozen dict via tuple storage
    composite_score: Optional[float]   # None when no activity
    tier: str                  # 'gold' | 'silver' | 'bronze' | 'probation' | 'no_activity'
    tier_label: str
    low_sample: bool           # True when total_trips < 3
    week_over_week_delta: Optional[float]
    headline_metric: str
    focus_area: str
    # ── Revenue contribution ──────────────────────────────────────────────────
    revenue_impact: float          # sum(max(0, net_pay - z_rate)) across window trips
    revenue_impact_per_trip: float # revenue_impact / total_trips (0 when no trips)
    revenue_rank: Optional[int]    # rank among active drivers by revenue_impact (1=highest); None when not yet ranked


# ── Internal helpers ──────────────────────────────────────────────────────────

def _week_bounds_utc(week_start: date) -> tuple[datetime, datetime]:
    """Return [start, end) UTC datetimes for the given Monday (PT midnight)."""
    # Monday 00:00 PT → UTC
    start_pt = datetime(week_start.year, week_start.month, week_start.day, 0, 0, 0, tzinfo=PT)
    end_pt = start_pt + timedelta(days=7)
    return start_pt.astimezone(UTC), end_pt.astimezone(UTC)


def _parse_pickup_dt(pickup_time: Optional[str], trip_date: date) -> Optional[datetime]:
    """Parse pickup_time text + trip_date into a UTC-aware datetime.

    Mirrors trip_monitor._parse_pickup_time but returns UTC.
    """
    if not pickup_time:
        return None
    try:
        if len(pickup_time) <= 5 and ":" in pickup_time:
            h, m = pickup_time.split(":")
            local = datetime(trip_date.year, trip_date.month, trip_date.day,
                             int(h), int(m), tzinfo=PT)
            return local.astimezone(UTC)
        if "T" in pickup_time:
            dt = datetime.fromisoformat(pickup_time.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = datetime(trip_date.year, trip_date.month, trip_date.day,
                              dt.hour, dt.minute, tzinfo=PT).astimezone(UTC)
            return dt.astimezone(UTC)
        for fmt in ("%I:%M %p", "%I:%M%p"):
            try:
                t = datetime.strptime(pickup_time, fmt)
                local = datetime(trip_date.year, trip_date.month, trip_date.day,
                                 t.hour, t.minute, tzinfo=PT)
                return local.astimezone(UTC)
            except ValueError:
                continue
    except (ValueError, TypeError):
        pass
    return None


def _route_key(source: str, trip_ref: str) -> str:
    """Derive a stable route identifier from source + trip_ref.

    FA trip_refs look like 'Redmond_D_T001' or 'ElBaker01_B_T099'.
    We take the portion before the last underscore-separated token that is
    purely numeric (the tripId suffix). For ED, the keyValue already encodes
    route context — use a 12-char prefix to group similar keys.
    """
    if not trip_ref:
        return f"{source}:unknown"
    parts = trip_ref.rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return f"{source}:{parts[0]}"
    # Fallback: use first 12 chars as a route cluster key
    return f"{source}:{trip_ref[:12]}"


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _tier(composite: float) -> tuple[str, str]:
    if composite >= TIER_GOLD_MIN:
        return "gold", "Tier 1"
    if composite >= TIER_SILVER_MIN:
        return "silver", "Tier 2"
    if composite >= TIER_BRONZE_MIN:
        return "bronze", "Tier 3"
    return "probation", "Tier 4"


def _percentile_label(driver_val: float, fleet_vals: list[float]) -> str:
    """Return a simple ranking label relative to the fleet distribution."""
    if len(fleet_vals) < 2:
        return "only driver this week"
    rank = sum(1 for v in fleet_vals if v <= driver_val)
    pct = rank / len(fleet_vals)
    if pct >= 0.90:
        return "top 10%"
    if pct >= 0.75:
        return "top 25%"
    if pct >= 0.50:
        return "above fleet avg"
    return "below fleet avg"


# ── Per-driver axis computation ───────────────────────────────────────────────

def _compute_acceptance(trips: list[dict]) -> tuple[float, int]:
    """Return (raw_value, sample_size).

    accepted_at ≤ accept_sms_at + 2min counts as "on time".
    Each non-null accept_escalated_at or start_escalated_at subtracts 0.1
    from the raw score (floored at 0).
    """
    total = len(trips)
    if total == 0:
        return 0.0, 0
    on_time = 0
    escalation_count = 0
    TWO_MIN = timedelta(minutes=2)
    for t in trips:
        accepted_at = t.get("accepted_at")
        sms_at = t.get("accept_sms_at")
        if accepted_at and sms_at:
            # Both timestamps present — apply the 2-minute window check
            if accepted_at <= sms_at + TWO_MIN:
                on_time += 1
        elif accepted_at:
            # Driver accepted via call dispatch; no SMS to compare against — count as on-time
            on_time += 1
        if t.get("accept_escalated_at"):
            escalation_count += 1
        if t.get("start_escalated_at"):
            escalation_count += 1
    raw = on_time / total
    raw = _clamp(raw - escalation_count * 0.1)
    return raw, total


def _compute_on_time_start(trips: list[dict]) -> tuple[float, int]:
    """started_at ≤ scheduled_pickup + 2min."""
    total = len(trips)
    if total == 0:
        return 0.0, 0
    TWO_MIN = timedelta(minutes=2)
    on_time = 0
    for t in trips:
        started_at = t.get("started_at")
        pickup_dt = t.get("_pickup_dt")
        if started_at and pickup_dt:
            if started_at <= pickup_dt + TWO_MIN:
                on_time += 1
    return on_time / total, total


def _compute_on_time_arrival(trips: list[dict]) -> tuple[float, int, bool]:
    """arrived_at_pickup ≤ scheduled_pickup + 5min. NULLs excluded from denominator.

    Returns (raw_value, sample_size, low_confidence).
    """
    total = len(trips)
    if total == 0:
        return 0.0, 0, False
    FIVE_MIN = timedelta(minutes=5)
    on_time = 0
    eligible = 0
    for t in trips:
        arrived = t.get("arrived_at_pickup")
        pickup_dt = t.get("_pickup_dt")
        if arrived is None or pickup_dt is None:
            continue  # NULL → excluded from denominator
        eligible += 1
        if arrived <= pickup_dt + FIVE_MIN:
            on_time += 1
    if eligible == 0:
        return 0.0, 0, False
    raw = on_time / eligible
    low_conf = eligible < total * LOW_CONFIDENCE_THRESHOLD
    return raw, eligible, low_conf


def _compute_responsiveness(trips: list[dict]) -> tuple[float, int]:
    """Calls answered ÷ calls attempted.

    'Attempted' = trip has accept_call_at or start_call_at non-null.
    Since we can only observe whether a call was placed (the column is set when
    we initiate the call), we treat every non-null call column as both attempted
    and answered (we don't currently record unanswered calls as a separate event).
    If no calls were placed this week, default to 1.0.

    When notification_event starts logging call outcomes, this function should
    be updated to read those rows instead.
    """
    attempted = sum(
        1 for t in trips
        if t.get("accept_call_at") or t.get("start_call_at")
    )
    if attempted == 0:
        return 1.0, 0  # no calls — no penalty
    # All recorded calls are "answered" under the current schema
    return 1.0, attempted


def _compute_reliability(trips: list[dict], status_events: list[dict]) -> tuple[float, int]:
    """1.0 - (declines + driver_cancellations + sub_requests) / total."""
    total = len(trips)
    if total == 0:
        return 1.0, 0
    bad_statuses = {"declined", "driver_cancelled", "sub_requested"}
    bad_count = sum(
        1 for ev in status_events
        if ev.get("new_status") in bad_statuses
    )
    raw = _clamp(1.0 - bad_count / total)
    return raw, total


# ── Route normalization ───────────────────────────────────────────────────────

def _route_normalize(
    driver_trips: list[dict],
    fleet_trips: list[dict],
    axis_fn,
    *,
    skip_on_low_conf: bool = False,
) -> tuple[float, int, bool]:
    """Apply per-route fleet-average normalization for one axis.

    Algorithm:
      For each route the driver ran this week, compute the fleet-average raw
      value on that route. Then the driver's normalized value = avg over their
      trips of min(1.0, driver_per_route_raw + (1.0 - fleet_per_route_avg)).
      Routes with only this driver (no fleet avg) → use raw without adjustment.

    Returns (normalized_value, sample_size, low_confidence).
    """
    # Group driver trips by route
    route_driver_trips: dict[str, list[dict]] = {}
    for t in driver_trips:
        rk = _route_key(t["source"], t["trip_ref"])
        route_driver_trips.setdefault(rk, []).append(t)

    # Group all fleet trips by route
    route_fleet_trips: dict[str, list[dict]] = {}
    for t in fleet_trips:
        rk = _route_key(t["source"], t["trip_ref"])
        route_fleet_trips.setdefault(rk, []).append(t)

    route_adjustments: list[tuple[float, int]] = []  # (normalized_raw, n_trips)

    for route, drv_trips in route_driver_trips.items():
        fleet_for_route = route_fleet_trips.get(route, [])
        drv_raw, drv_n = axis_fn(drv_trips)[:2]
        if drv_n == 0:
            continue
        # Only 1 driver on this route → skip normalization, use raw
        unique_drivers = {t["person_id"] for t in fleet_for_route}
        if len(unique_drivers) <= 1:
            route_adjustments.append((drv_raw, drv_n))
            continue
        fleet_raw, fleet_n = axis_fn(fleet_for_route)[:2]
        if fleet_n == 0:
            route_adjustments.append((drv_raw, drv_n))
            continue
        adjusted = _clamp(drv_raw + (1.0 - fleet_raw))
        route_adjustments.append((adjusted, drv_n))

    if not route_adjustments:
        # Fall back: compute raw over all driver trips
        raw, n = axis_fn(driver_trips)[:2]
        return raw, n, False

    total_n = sum(n for _, n in route_adjustments)
    weighted_avg = sum(v * n for v, n in route_adjustments) / total_n
    return _clamp(weighted_avg), total_n, False


# ── Fleet percentile maps ─────────────────────────────────────────────────────

def _build_fleet_axis_values(
    all_scorecards_raw: list[dict],  # list of {person_id, axes_raw}
    axis_name: str,
) -> list[float]:
    """Collect per-driver raw values for a given axis across the fleet."""
    return [
        sc["axes_raw"][axis_name]
        for sc in all_scorecards_raw
        if sc["axes_raw"].get(axis_name) is not None
    ]


# ── Per-driver scorecard builder ──────────────────────────────────────────────

def _build_scorecard(
    person_id: int,
    driver_name: str,
    week_start: date,
    driver_trips: list[dict],
    fleet_trips: list[dict],
    driver_status_events: list[dict],
    prior_composite: Optional[float],
    fleet_axis_values: dict[str, list[float]],  # axis_name → [fleet_normalized_values]
    revenue_impact: float = 0.0,
    revenue_rank: Optional[int] = None,
) -> DriverScorecard:
    """Build a DriverScorecard for one driver. Called per-driver after bulk fetch."""
    total_trips = len(driver_trips)
    week_iso = f"{week_start.isocalendar().year}-{week_start.isocalendar().week:02d}"

    if total_trips == 0:
        return DriverScorecard(
            person_id=person_id,
            driver_name=driver_name,
            week_start=week_start,
            week_iso=week_iso,
            total_trips=0,
            axes={},
            composite_score=None,
            tier="no_activity",
            tier_label="No Activity",
            low_sample=False,
            week_over_week_delta=None,
            headline_metric="No rides this week",
            focus_area="",
            revenue_impact=0.0,
            revenue_impact_per_trip=0.0,
            revenue_rank=revenue_rank,
        )

    low_sample = total_trips < 3

    # ── Acceptance ────────────────────────────────────────────────────────────
    accept_raw, accept_n = _compute_acceptance(driver_trips)
    accept_norm, accept_n_norm, _ = _route_normalize(
        driver_trips, fleet_trips,
        lambda trips: (_compute_acceptance(trips)[0], len(trips)),
    )
    # For acceptance, prefer the route-normalized value but keep raw-derived escalation penalty
    # Recompute properly: we need the escalation-adjusted raw per driver trip
    accept_norm = _clamp(accept_norm)

    # ── On-time start ─────────────────────────────────────────────────────────
    start_raw, start_n = _compute_on_time_start(driver_trips)
    start_norm, start_n_norm, _ = _route_normalize(
        driver_trips, fleet_trips,
        lambda trips: (_compute_on_time_start(trips)[0], _compute_on_time_start(trips)[1]),
    )

    # ── On-time arrival ───────────────────────────────────────────────────────
    arrive_raw, arrive_n, arrive_low_conf = _compute_on_time_arrival(driver_trips)
    if arrive_n >= 1:
        arrival_available = True
        if arrive_low_conf or arrive_n < total_trips * LOW_CONFIDENCE_THRESHOLD:
            # Skip route normalization on low confidence — use raw
            arrive_norm = arrive_raw
        else:
            arrive_norm, _, _ = _route_normalize(
                driver_trips, fleet_trips,
                lambda trips: (_compute_on_time_arrival(trips)[0], _compute_on_time_arrival(trips)[1]),
            )
            arrive_norm = _clamp(arrive_norm)
    else:
        # No trips have arrived_at_pickup data (all NULL) → axis unavailable.
        # Treat identically to on_time_completion: exclude from composite so
        # weights redistribute to the remaining axes. Scoring 0% when the signal
        # simply doesn't exist (common for ED trips) would unfairly tank Tier 4
        # drivers whose trips closed normally without a recorded arrival timestamp.
        arrival_available = False
        arrive_norm = 0.0
        arrive_low_conf = False

    # ── On-time completion — UNAVAILABLE (no scheduled_dropoff column) ────────
    # Axis is excluded from composite by setting available=False.
    # Weights for remaining axes are renormalized below.
    completion_available = False

    # ── Responsiveness ────────────────────────────────────────────────────────
    resp_raw, resp_n = _compute_responsiveness(driver_trips)
    # No route normalization for responsiveness (call routing is dispatch-side, not route-dependent)
    resp_norm = resp_raw

    # ── Reliability ───────────────────────────────────────────────────────────
    rely_raw, rely_n = _compute_reliability(driver_trips, driver_status_events)
    rely_norm, rely_n_norm, _ = _route_normalize(
        driver_trips, fleet_trips,
        lambda trips: (_compute_reliability(trips, driver_status_events)[0], len(trips)),
    )

    # ── Build AxisScore objects ───────────────────────────────────────────────
    # Renormalize weights for unavailable axes:
    #   on_time_completion — always False (no scheduled_dropoff column in DB)
    #   on_time_pickup_arrival — False when no trips have arrived_at_pickup data
    available_axes = {
        "acceptance": True,
        "on_time_start": True,
        "on_time_pickup_arrival": arrival_available,
        "on_time_completion": False,  # no scheduled_dropoff
        "responsiveness": True,
        "reliability": True,
    }
    total_available_weight = sum(
        AXIS_WEIGHTS[k] for k, avail in available_axes.items() if avail
    )
    # Scale factor so available axes still sum to 100
    weight_scale = 1.0 / total_available_weight if total_available_weight > 0 else 1.0

    def _scaled_weight(axis: str) -> float:
        return AXIS_WEIGHTS[axis] * weight_scale if available_axes[axis] else 0.0

    axis_data = {
        "acceptance": AxisScore(
            name="acceptance",
            raw_value=accept_raw,
            normalized_value=accept_norm,
            weight=_scaled_weight("acceptance"),
            weighted_score=accept_norm * _scaled_weight("acceptance") * 100,
            sample_size=accept_n,
            available=True,
            low_confidence=accept_n < MIN_SAMPLE_FOR_HEADLINE,
        ),
        "on_time_start": AxisScore(
            name="on_time_start",
            raw_value=start_raw,
            normalized_value=start_norm,
            weight=_scaled_weight("on_time_start"),
            weighted_score=start_norm * _scaled_weight("on_time_start") * 100,
            sample_size=start_n,
            available=True,
            low_confidence=start_n < MIN_SAMPLE_FOR_HEADLINE,
        ),
        "on_time_pickup_arrival": AxisScore(
            name="on_time_pickup_arrival",
            raw_value=arrive_raw,
            normalized_value=arrive_norm,
            weight=_scaled_weight("on_time_pickup_arrival"),
            weighted_score=arrive_norm * _scaled_weight("on_time_pickup_arrival") * 100,
            sample_size=arrive_n,
            available=arrival_available,
            low_confidence=arrive_low_conf,
        ),
        "on_time_completion": AxisScore(
            name="on_time_completion",
            raw_value=0.0,
            normalized_value=0.0,
            weight=0.0,
            weighted_score=0.0,
            sample_size=0,
            available=False,
            low_confidence=False,
        ),
        "responsiveness": AxisScore(
            name="responsiveness",
            raw_value=resp_raw,
            normalized_value=resp_norm,
            weight=_scaled_weight("responsiveness"),
            weighted_score=resp_norm * _scaled_weight("responsiveness") * 100,
            sample_size=resp_n,
            available=True,
            low_confidence=resp_n < MIN_SAMPLE_FOR_HEADLINE,
        ),
        "reliability": AxisScore(
            name="reliability",
            raw_value=rely_raw,
            normalized_value=rely_norm,
            weight=_scaled_weight("reliability"),
            weighted_score=rely_norm * _scaled_weight("reliability") * 100,
            sample_size=rely_n,
            available=True,
            low_confidence=rely_n < MIN_SAMPLE_FOR_HEADLINE,
        ),
    }

    composite = sum(ax.weighted_score for ax in axis_data.values())
    composite = _clamp(composite, 0.0, 100.0)

    tier_key, tier_label = _tier(composite)

    # ── Week-over-week delta ──────────────────────────────────────────────────
    wow_delta: Optional[float] = None
    if prior_composite is not None:
        wow_delta = round(composite - prior_composite, 2)

    # ── Headline metric ───────────────────────────────────────────────────────
    eligible_axes = [
        ax for ax in axis_data.values()
        if ax.available and ax.sample_size >= MIN_SAMPLE_FOR_HEADLINE
    ]

    if not eligible_axes:
        headline = "Not enough data this week"
        focus = ""
    elif composite >= TIER_BRONZE_MIN:
        # Positive framing: strongest axis
        best = max(eligible_axes, key=lambda ax: ax.normalized_value)
        pct = round(best.normalized_value * 100)
        fleet_vals = fleet_axis_values.get(best.name, [])
        ranking = _percentile_label(best.normalized_value, fleet_vals)
        headline = f"{AXIS_LABELS[best.name]} {pct}% — {ranking}"
        # Focus: lowest axis (constructive)
        worst = min(eligible_axes, key=lambda ax: ax.normalized_value)
        focus = FOCUS_TEMPLATES[worst.name]
    else:
        # Constructive framing: weakest axis
        worst = min(eligible_axes, key=lambda ax: ax.normalized_value)
        pct = round(worst.normalized_value * 100)
        headline = f"{AXIS_LABELS[worst.name]} {pct}% — room to improve"
        focus = FOCUS_TEMPLATES[worst.name]

    revenue_impact_per_trip = round(revenue_impact / total_trips, 4) if total_trips > 0 else 0.0

    return DriverScorecard(
        person_id=person_id,
        driver_name=driver_name,
        week_start=week_start,
        week_iso=week_iso,
        total_trips=total_trips,
        axes=axis_data,
        composite_score=round(composite, 4),
        tier=tier_key,
        tier_label=tier_label,
        low_sample=low_sample,
        week_over_week_delta=wow_delta,
        headline_metric=headline,
        focus_area=focus,
        revenue_impact=round(revenue_impact, 2),
        revenue_impact_per_trip=round(revenue_impact_per_trip, 2),
        revenue_rank=revenue_rank,
    )


# ── Public API ────────────────────────────────────────────────────────────────

def compute_driver_scorecard(
    person_id: int,
    week_start: date,
    db_session: Session,
    prior_week_composite: Optional[float] = None,
) -> DriverScorecard:
    """Compute scorecard for a single driver for the given ISO week.

    Pulls fleet-wide data for route normalization. Prefer
    compute_all_active_drivers() for batch work — it issues only 3 queries
    total vs one set of queries per driver here.
    """
    week_start_utc, week_end_utc = _week_bounds_utc(week_start)

    # All trip_notification rows for the week (fleet-wide, for normalization)
    fleet_rows = db_session.execute(
        text("""
            SELECT
                tn.id, tn.person_id, tn.trip_date, tn.source, tn.trip_ref,
                tn.accept_sms_at, tn.accept_call_at,
                tn.accept_escalated_at, tn.start_escalated_at,
                tn.accepted_at, tn.started_at,
                tn.arrived_at_pickup, tn.completed_at,
                tn.pickup_time, tn.start_call_at,
                p.full_name
            FROM trip_notification tn
            JOIN person p ON p.person_id = tn.person_id
            WHERE tn.created_at >= :start AND tn.created_at < :end
              AND p.active = true
        """),
        {"start": week_start_utc, "end": week_end_utc},
    ).mappings().all()

    # Status events for the week
    status_rows = db_session.execute(
        text("""
            SELECT person_id, new_status
            FROM trip_status_event
            WHERE detected_at >= :start AND detected_at < :end
        """),
        {"start": week_start_utc, "end": week_end_utc},
    ).mappings().all()

    fleet_trips = [_row_to_trip(r) for r in fleet_rows]
    driver_trips = [t for t in fleet_trips if t["person_id"] == person_id]

    # Driver name
    driver_name = "Unknown"
    if fleet_rows:
        for r in fleet_rows:
            if r["person_id"] == person_id:
                driver_name = r["full_name"]
                break
    if driver_name == "Unknown":
        row = db_session.execute(
            text("SELECT full_name FROM person WHERE person_id = :pid"),
            {"pid": person_id},
        ).fetchone()
        if row:
            driver_name = row[0]

    driver_status_events = [
        {"new_status": r["new_status"]}
        for r in status_rows
        if r["person_id"] == person_id
    ]

    # Fleet axis values for percentile ranking (single-driver call, limited fleet)
    fleet_axis_values = _compute_fleet_axis_values(fleet_trips, [])

    # Query 3 — revenue impact: sum(max(0, net_pay - z_rate)) for this driver in the window
    revenue_row = db_session.execute(
        text("""
            SELECT
                COALESCE(SUM(GREATEST(0, COALESCE(r.net_pay, r.gross_pay, 0) - COALESCE(r.z_rate, 0))), 0) AS revenue_impact
            FROM ride r
            WHERE r.person_id = :pid
              AND DATE(r.ride_start_ts) >= :start_date
              AND DATE(r.ride_start_ts) < :end_date
        """),
        {
            "pid": person_id,
            "start_date": week_start_utc.date(),
            "end_date": (week_start_utc + timedelta(days=7)).date(),
        },
    ).fetchone()
    revenue_impact = float(revenue_row[0]) if revenue_row else 0.0

    return _build_scorecard(
        person_id=person_id,
        driver_name=driver_name,
        week_start=week_start,
        driver_trips=driver_trips,
        fleet_trips=fleet_trips,
        driver_status_events=driver_status_events,
        prior_composite=prior_week_composite,
        fleet_axis_values=fleet_axis_values,
        revenue_impact=revenue_impact,
        revenue_rank=None,  # single-driver call — no fleet ranking available
    )


def compute_all_active_drivers(
    week_start: date,
    db_session: Session,
) -> list[DriverScorecard]:
    """Compute scorecards for every active driver who had trips this week.

    Issues exactly 3 queries: trip_notification, trip_status_event,
    prior-week composites. Groups by driver in Python.
    """
    week_start_utc, week_end_utc = _week_bounds_utc(week_start)

    # Query 1 — all trip rows for the week
    fleet_rows = db_session.execute(
        text("""
            SELECT
                tn.id, tn.person_id, tn.trip_date, tn.source, tn.trip_ref,
                tn.accept_sms_at, tn.accept_call_at,
                tn.accept_escalated_at, tn.start_escalated_at,
                tn.accepted_at, tn.started_at,
                tn.arrived_at_pickup, tn.completed_at,
                tn.pickup_time, tn.start_call_at,
                p.full_name
            FROM trip_notification tn
            JOIN person p ON p.person_id = tn.person_id
            WHERE tn.created_at >= :start AND tn.created_at < :end
              AND p.active = true
        """),
        {"start": week_start_utc, "end": week_end_utc},
    ).mappings().all()

    # Query 2 — all status events for the week
    status_rows = db_session.execute(
        text("""
            SELECT person_id, new_status
            FROM trip_status_event
            WHERE detected_at >= :start AND detected_at < :end
        """),
        {"start": week_start_utc, "end": week_end_utc},
    ).mappings().all()

    # Group by driver
    fleet_trips = [_row_to_trip(r) for r in fleet_rows]
    driver_ids: list[int] = []
    driver_names: dict[int, str] = {}
    by_driver: dict[int, list[dict]] = {}
    for t in fleet_trips:
        pid = t["person_id"]
        if pid not in by_driver:
            by_driver[pid] = []
            driver_ids.append(pid)
        by_driver[pid].append(t)

    for r in fleet_rows:
        pid = r["person_id"]
        if pid not in driver_names:
            driver_names[pid] = r["full_name"]

    status_by_driver: dict[int, list[dict]] = {}
    for r in status_rows:
        pid = r["person_id"]
        status_by_driver.setdefault(pid, []).append({"new_status": r["new_status"]})

    # Query 3 — prior week composites (for week-over-week delta)
    prior_week_start = week_start - timedelta(days=7)
    prior_bounds_utc = _week_bounds_utc(prior_week_start)
    prior_rows = db_session.execute(
        text("""
            SELECT tn.person_id, COUNT(*) as trips
            FROM trip_notification tn
            JOIN person p ON p.person_id = tn.person_id
            WHERE tn.created_at >= :start AND tn.created_at < :end
              AND p.active = true
            GROUP BY tn.person_id
        """),
        {"start": prior_bounds_utc[0], "end": prior_bounds_utc[1]},
    ).mappings().all()
    # We don't store computed composites yet — prior_composite will be None
    # until we add a scorecard_cache table in a future phase.
    prior_composites: dict[int, Optional[float]] = {r["person_id"]: None for r in prior_rows}

    # Fleet axis values for percentile ranking
    fleet_axis_values = _compute_fleet_axis_values(fleet_trips, driver_ids)

    # Query 4 — revenue impact per driver: sum(max(0, net_pay - z_rate)) in the window
    # Note: ride table uses ride_start_ts (DateTime), not trip_date (that column is on
    # trip_notification). Cast to DATE for the date range filter.
    revenue_rows = db_session.execute(
        text("""
            SELECT
                r.person_id,
                COALESCE(SUM(GREATEST(0, COALESCE(r.net_pay, r.gross_pay, 0) - COALESCE(r.z_rate, 0))), 0) AS revenue_impact
            FROM ride r
            WHERE DATE(r.ride_start_ts) >= :start_date
              AND DATE(r.ride_start_ts) < :end_date
            GROUP BY r.person_id
        """),
        {
            "start_date": week_start_utc.date(),
            "end_date": (week_start_utc + timedelta(days=7)).date(),
        },
    ).mappings().all()
    revenue_by_driver: dict[int, float] = {
        r["person_id"]: float(r["revenue_impact"]) for r in revenue_rows
    }

    # Compute revenue rank (1 = highest) among drivers active this week
    ranked_pids = sorted(
        driver_ids,
        key=lambda pid: revenue_by_driver.get(pid, 0.0),
        reverse=True,
    )
    revenue_rank_map: dict[int, int] = {pid: i + 1 for i, pid in enumerate(ranked_pids)}

    results: list[DriverScorecard] = []
    for pid in driver_ids:
        sc = _build_scorecard(
            person_id=pid,
            driver_name=driver_names.get(pid, "Unknown"),
            week_start=week_start,
            driver_trips=by_driver[pid],
            fleet_trips=fleet_trips,
            driver_status_events=status_by_driver.get(pid, []),
            prior_composite=prior_composites.get(pid),
            fleet_axis_values=fleet_axis_values,
            revenue_impact=revenue_by_driver.get(pid, 0.0),
            revenue_rank=revenue_rank_map.get(pid),
        )
        results.append(sc)

    return results


# ── Internal utilities ────────────────────────────────────────────────────────

def _row_to_trip(r: dict) -> dict:
    """Convert a DB row mapping to a normalized trip dict for scoring."""
    trip_date = r["trip_date"]
    if isinstance(trip_date, datetime):
        trip_date = trip_date.date()

    pickup_dt = _parse_pickup_dt(r.get("pickup_time"), trip_date)

    def _utc(v):
        """Ensure a datetime value is UTC-aware."""
        if v is None:
            return None
        if isinstance(v, datetime):
            if v.tzinfo is None:
                return v.replace(tzinfo=UTC)
            return v.astimezone(UTC)
        return None

    return {
        "person_id": r["person_id"],
        "source": r["source"],
        "trip_ref": r["trip_ref"],
        "accept_sms_at": _utc(r.get("accept_sms_at")),
        "accept_call_at": _utc(r.get("accept_call_at")),
        "start_call_at": _utc(r.get("start_call_at")),
        "accept_escalated_at": _utc(r.get("accept_escalated_at")),
        "start_escalated_at": _utc(r.get("start_escalated_at")),
        "accepted_at": _utc(r.get("accepted_at")),
        "started_at": _utc(r.get("started_at")),
        "arrived_at_pickup": _utc(r.get("arrived_at_pickup")),
        "completed_at": _utc(r.get("completed_at")),
        "_pickup_dt": _utc(pickup_dt) if pickup_dt else None,
    }


def _compute_fleet_axis_values(
    fleet_trips: list[dict],
    driver_ids: list[int],
) -> dict[str, list[float]]:
    """Pre-compute per-axis fleet distribution for percentile ranking.

    Returns dict[axis_name, list[normalized_value]] — one entry per driver
    with at least 3 trips, for use in _percentile_label().
    """
    by_driver: dict[int, list[dict]] = {}
    for t in fleet_trips:
        by_driver.setdefault(t["person_id"], []).append(t)

    result: dict[str, list[float]] = {k: [] for k in AXIS_WEIGHTS}

    for pid, trips in by_driver.items():
        if len(trips) < MIN_SAMPLE_FOR_HEADLINE:
            continue
        raw_a, _ = _compute_acceptance(trips)
        raw_s, _ = _compute_on_time_start(trips)
        raw_ar, n_ar, _ = _compute_on_time_arrival(trips)
        raw_r, _ = _compute_responsiveness(trips)
        raw_re, _ = _compute_reliability(trips, [])

        result["acceptance"].append(raw_a)
        result["on_time_start"].append(raw_s)
        if n_ar > 0:
            result["on_time_pickup_arrival"].append(raw_ar)
        result["on_time_completion"].append(0.0)  # unavailable
        result["responsiveness"].append(raw_r)
        result["reliability"].append(raw_re)

    return result
