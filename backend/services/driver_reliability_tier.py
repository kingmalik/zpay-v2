"""
Driver reliability tiers — Trusted / Watch / Chronic.

Powers the S2 exception-queue policy: most drivers never need a call; a small
chronic group eats all the phone time. Tiers are computed from trailing
trip_notification history and modulate WHEN the monitor starts nudging a
driver and WHO surfaces on the dispatcher's exception queue.

Tier semantics (locked in MASTER-PLAN-2026-07 §3/S4 intake):
    trusted — never surface unless actually late; SMS window shrinks
    watch   — default behavior (today's fleet-flat thresholds)
    chronic — surface earliest; SMS window widens so the nudge lands sooner

The live-send policy change is gated behind MONITOR_TIER_POLICY (default off)
so current prod behavior is unchanged until Malik flips it — the driver-comms
approval gate from the master plan.

Env knobs:
    MONITOR_TIER_POLICY                  "1"/"true" → tier-aware windows (default off)
    MONITOR_TIER_LOOKBACK_DAYS           trailing history window (default 56)
    MONITOR_TIER_MIN_TRIPS               below this → watch/insufficient history (default 5)
    MONITOR_TIER_TRUSTED_WINDOW_MINUTES  accept-SMS window for trusted (default 25)
    MONITOR_TIER_CHRONIC_WINDOW_MINUTES  accept-SMS window for chronic (default 90)
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func
from sqlalchemy.orm import Session

logger = logging.getLogger("zpay.reliability_tier")

TIER_TRUSTED = "trusted"
TIER_WATCH = "watch"
TIER_CHRONIC = "chronic"

_LOOKBACK_DAYS = int(os.environ.get("MONITOR_TIER_LOOKBACK_DAYS", "56"))
_MIN_TRIPS = int(os.environ.get("MONITOR_TIER_MIN_TRIPS", "5"))
_TRUSTED_WINDOW = int(os.environ.get("MONITOR_TIER_TRUSTED_WINDOW_MINUTES", "25"))
_CHRONIC_WINDOW = int(os.environ.get("MONITOR_TIER_CHRONIC_WINDOW_MINUTES", "90"))

# Classification thresholds — explainable on purpose (mom-facing evidence).
_CHRONIC_NUDGE_RATE = 0.15   # ≥15% of trips needed an SMS nudge
_TRUSTED_NUDGE_RATE = 0.05   # ≤5% nudge rate qualifies for trusted
_TRUSTED_MIN_TRIPS = 10      # trusted needs a real track record

# Recompute at most this often — the monitor polls every minute; the
# aggregate only needs to move as fast as history does.
_CACHE_TTL_SECONDS = 30 * 60

_cache_lock = threading.Lock()
_cache: dict[int, "TierResult"] = {}
_cache_computed_at: datetime | None = None


def tier_policy_enabled() -> bool:
    """True when tier-aware monitor timing is switched on (Malik's flag)."""
    return os.environ.get("MONITOR_TIER_POLICY", "0").lower().strip() in ("1", "true", "yes")


@dataclass(frozen=True)
class TierResult:
    person_id: int
    tier: str
    trips: int
    nudges: int          # accept SMS fired
    calls: int           # accept or start call fired
    ghosts: int          # escalated to admin AFTER a call — real non-response
    nudge_rate: float
    reason: str


def classify(trips: int, nudges: int, calls: int, ghosts: int) -> tuple[str, str]:
    """Pure tier rule — returns (tier, human-readable reason).

    Order matters: chronic signals override everything; trusted requires a
    clean record over a real sample; everyone else (including new drivers)
    sits in watch.
    """
    if trips < _MIN_TRIPS:
        return TIER_WATCH, f"only {trips} trips in window (need {_MIN_TRIPS}+ to tier)"

    nudge_rate = nudges / trips if trips else 0.0

    if ghosts > 0:
        return TIER_CHRONIC, f"ghosted {ghosts}× (call went unanswered) in window"
    if calls > 0:
        return TIER_CHRONIC, f"needed {calls} phone call(s) in window"
    if nudge_rate >= _CHRONIC_NUDGE_RATE:
        return TIER_CHRONIC, f"nudged on {nudge_rate:.0%} of trips (threshold {_CHRONIC_NUDGE_RATE:.0%})"

    if trips >= _TRUSTED_MIN_TRIPS and nudge_rate <= _TRUSTED_NUDGE_RATE:
        return TIER_TRUSTED, f"{trips} trips, {nudge_rate:.0%} nudge rate, zero calls"

    return TIER_WATCH, f"{trips} trips, {nudge_rate:.0%} nudge rate"


def effective_reminder_window(tier: str, default_window: int) -> int:
    """Accept-SMS window (minutes before pickup) for a tier.

    trusted shrinks the window (they self-manage — only nudge when close),
    chronic widens it (nudge lands as early as possible), watch keeps the
    fleet default. Never returns something more lenient than chronic's floor
    or tighter than trusted's ceiling relative to the default.
    """
    if tier == TIER_TRUSTED:
        return min(default_window, _TRUSTED_WINDOW)
    if tier == TIER_CHRONIC:
        return max(default_window, _CHRONIC_WINDOW)
    return default_window


def compute_tiers(db: Session, lookback_days: int | None = None) -> dict[int, TierResult]:
    """One aggregate pass over trip_notification → tier per driver seen in window."""
    from backend.db.models import TripNotification

    days = lookback_days if lookback_days is not None else _LOOKBACK_DAYS
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date()

    rows = (
        db.query(
            TripNotification.person_id,
            func.count().label("trips"),
            func.count(TripNotification.accept_sms_at).label("nudges"),
            (
                func.count(TripNotification.accept_call_at)
                + func.count(TripNotification.start_call_at)
            ).label("calls"),
            func.sum(
                # Real ghost: escalated after a call actually fired (the
                # no-phone-on-file path escalates without any call and is a
                # data problem, not a driver-reliability signal).
                case(
                    (
                        (TripNotification.accept_escalated_at.isnot(None))
                        & (TripNotification.accept_call_at.isnot(None)),
                        1,
                    ),
                    else_=0,
                )
            ).label("ghosts"),
        )
        .filter(TripNotification.trip_date >= since)
        .group_by(TripNotification.person_id)
        .all()
    )

    # Dispatcher-confirmed ghosts: one-tap "ghosted" dispositions on the
    # exception queue (notification_event.call_disposition). Human confirmation
    # counts even when the automated escalation chain didn't fire.
    from backend.db.models import NotificationEvent

    since_dt = datetime.now(timezone.utc) - timedelta(days=days)
    disposition_ghosts: dict[int, int] = dict(
        db.query(TripNotification.person_id, func.count())
        .join(NotificationEvent, NotificationEvent.trip_notification_id == TripNotification.id)
        .filter(
            NotificationEvent.event_type == "call_disposition",
            NotificationEvent.created_at >= since_dt,
            NotificationEvent.payload["disposition"].as_string() == "ghosted",
        )
        .group_by(TripNotification.person_id)
        .all()
    )

    results: dict[int, TierResult] = {}
    for row in rows:
        trips = int(row.trips or 0)
        nudges = int(row.nudges or 0)
        calls = int(row.calls or 0)
        ghosts = int(row.ghosts or 0) + disposition_ghosts.get(row.person_id, 0)
        tier, reason = classify(trips, nudges, calls, ghosts)
        results[row.person_id] = TierResult(
            person_id=row.person_id,
            tier=tier,
            trips=trips,
            nudges=nudges,
            calls=calls,
            ghosts=ghosts,
            nudge_rate=round(nudges / trips, 4) if trips else 0.0,
            reason=reason,
        )
    return results


def get_tier(db: Session, person_id: int) -> TierResult:
    """Cached tier lookup for the monitor's per-trip hot path.

    Unknown drivers (no history in window) default to watch — identical to
    today's fleet-flat behavior.
    """
    global _cache, _cache_computed_at
    now = datetime.now(timezone.utc)
    with _cache_lock:
        stale = (
            _cache_computed_at is None
            or (now - _cache_computed_at).total_seconds() > _CACHE_TTL_SECONDS
        )
        if stale:
            try:
                _cache = compute_tiers(db)
                _cache_computed_at = now
                logger.info(
                    "[tier] recomputed reliability tiers for %d drivers", len(_cache)
                )
            except Exception:
                # Tier layer must never break the monitor — fall back to watch.
                logger.exception("[tier] compute failed — defaulting to watch")
                if _cache_computed_at is None:
                    _cache = {}
                    _cache_computed_at = now
        result = _cache.get(person_id)

    if result is not None:
        return result
    return TierResult(
        person_id=person_id,
        tier=TIER_WATCH,
        trips=0, nudges=0, calls=0, ghosts=0, nudge_rate=0.0,
        reason="no history in window",
    )


def invalidate_cache() -> None:
    """Force recompute on next get_tier (tests / manual refresh endpoint)."""
    global _cache_computed_at
    with _cache_lock:
        _cache_computed_at = None
