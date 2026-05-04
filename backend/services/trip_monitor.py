"""
Trip acceptance & start monitor — background scheduler that checks live trip
data from FirstAlt and EverDriven, notifies drivers who haven't accepted or
started, and escalates to admin.

Uses APScheduler BackgroundScheduler (in-process, single instance).
WARNING: single-instance only — if Railway auto-scales, duplicates will occur.
"""

import os
import logging
import threading
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger("zpay.trip-monitor")

# R6: prevents overlapping cycles when one cycle exceeds the interval.
_cycle_lock = threading.Lock()
# R7: re-alert window for liveness — fresh alert after sustained outage.
_LIVENESS_REALERT_SECONDS = 2 * 60 * 60
# R3: ED API lags ~30-90s behind Accept taps; skip Stage 1 if notif < this old.
_API_LAG_GRACE_SECONDS = 90
# R2: reschedule threshold — only reset Start-stage state on shifts >= this.
_RESCHEDULE_RESET_MINUTES = 30

# ── Configuration from env ────────────────────────────────────
_INTERVAL = int(os.environ.get("MONITOR_INTERVAL_MINUTES", "5"))
_START_HOUR = int(os.environ.get("MONITOR_START_HOUR", "4"))
_END_HOUR = int(os.environ.get("MONITOR_END_HOUR", "22"))

# ── Adaptive cadence — Phase 3 ────────────────────────────────
# When enabled, the monitor runs two loops instead of one:
#   hot  — every 60s, trips within 30 min of pickup through completion
#   cold — every 10min, everything else still relevant
# Set MONITOR_ADAPTIVE_CADENCE=false to revert to the flat _INTERVAL loop.
_ADAPTIVE_CADENCE = os.environ.get("MONITOR_ADAPTIVE_CADENCE", "true").lower() == "true"
_HOT_INTERVAL_SECONDS  = int(os.environ.get("MONITOR_HOT_INTERVAL_SECONDS",  "60"))
_COLD_INTERVAL_SECONDS = int(os.environ.get("MONITOR_COLD_INTERVAL_SECONDS", "600"))
# How far before pickup a trip enters the hot window (minutes).
_HOT_WINDOW_LEAD_MINUTES = int(os.environ.get("MONITOR_HOT_WINDOW_LEAD_MINUTES", "30"))
# How far back (hours) we still care about a trip that has no completion yet.
_HOT_WINDOW_LOOKBACK_HOURS = int(os.environ.get("MONITOR_HOT_WINDOW_LOOKBACK_HOURS", "12"))
_REMINDER_WINDOW = int(os.environ.get("MONITOR_REMINDER_WINDOW_MINUTES", "75"))  # drivers can accept ~75 min before pickup
_CALL_DELAY = int(os.environ.get("MONITOR_CALL_DELAY_MINUTES", "30"))            # call 30 min after SMS if still unaccepted
_ESCALATION_DELAY = int(os.environ.get("MONITOR_ESCALATION_DELAY_MINUTES", "15")) # escalate 15 min after call goes unanswered
_TZ_NAME = os.environ.get("MONITOR_TIMEZONE", "America/Los_Angeles")

# Start stage timing — matches accept chain so driver has lead time to roll,
# not scrambling at the pickup minute. Overridable via env vars.
_START_REMINDER_MINUTES = int(os.environ.get("MONITOR_START_REMINDER_MINUTES", "15"))
_START_CALL_DELAY = int(os.environ.get("MONITOR_START_CALL_DELAY_MINUTES", "10"))
_START_ESCALATION_DELAY = int(os.environ.get("MONITOR_START_ESCALATION_DELAY_MINUTES", "0"))
_ACCEPT_ESC_WINDOW = int(os.environ.get("MONITOR_ACCEPT_ESC_WINDOW_MINUTES", "20"))
_START_ESC_WINDOW = int(os.environ.get("MONITOR_START_ESC_WINDOW_MINUTES", "10"))
_DRY_RUN = os.environ.get("MONITOR_DRY_RUN", "false").lower() == "true"
_OVERDUE_GRACE = int(os.environ.get("MONITOR_OVERDUE_GRACE_MINUTES", "15"))
# Only escalate start-stage to admin when trip is actually overdue
# (prevents false alarms on ED drivers who typically don't tap start in the app).
_START_OVERDUE_ONLY = os.environ.get("MONITOR_START_OVERDUE_ONLY", "true").lower() == "true"
# Phase 2 — stuck-trip re-escalation config
# Re-escalate if a trip has been escalated and still has no terminal state
# after _STUCK_TRIP_REESCALATE_MINUTES minutes.
_STUCK_TRIP_REESCALATE_MINUTES = int(os.environ.get("MONITOR_STUCK_REESCALATE_MINUTES", "120"))
# Cap re-escalations per trip per day to avoid alert fatigue.
_STUCK_TRIP_REESCALATE_MAX = int(os.environ.get("MONITOR_STUCK_REESCALATE_MAX", "2"))
_START_OVERDUE_GRACE = int(os.environ.get("MONITOR_START_OVERDUE_GRACE_MINUTES", "10"))

_scheduler = None
_last_run_info: dict = {"last_run": None, "summary": None, "error": None}
_last_run_info_hot: dict = {"last_run": None, "summary": None, "error": None}
_last_run_info_cold: dict = {"last_run": None, "summary": None, "error": None}
_blind_cycle_alerted: set = set()
_partner_fail_alerted: set = set()  # keyed by (date_iso, source) tuples
# R7: was a flag-only dict; now stores the timestamp of the last alert so we
# can re-alert after _LIVENESS_REALERT_SECONDS for sustained outages.
_liveness_alerted: dict = {}  # keyed by date_iso → datetime of last alert

# ── Trip classification — explicit, zero silent failures ─────────────
# Every trip pulled from the partner APIs is classified into EXACTLY ONE
# bucket. If we ever see a status string we don't recognize, we DO NOT
# silently skip — we alert Malik so he knows there's a gap AND can tell
# us which bucket to add it to.
#
# Buckets:
#   declined    — driver opted out / sub needed. Alert Malik immediately.
#   unaccepted  — driver assigned, needs to tap accept. SMS → call → escalate.
#   accepted    — driver accepted, not yet started. Start-stage tracking.
#   started     — driver is actively en route / on the run.
#   completed   — trip finished. No action.
#   cancelled   — trip cancelled by partner/rider. No action.
#   unknown     — we have NO idea. Alert Malik with the raw status.

# FirstAlt — keyword-based because FA occasionally varies status casing/phrasing.
# Checked in priority order: decline > complete/cancel > started > accepted > unaccepted.
_FA_DECLINED_MARKERS  = ("DECLIN", "SUBSTITUTE", "SUB_NEEDED", "REMOVED", "REJECT")
_FA_COMPLETED_MARKERS = ("COMPLET", "FINISH", "DONE")
_FA_CANCELLED_MARKERS = ("CANCEL", "CLOSE", "VOID")
_FA_STARTED_MARKERS   = ("IN_PROGRESS", "IN PROGRESS", "INPROGRESS", "PROGRESS",
                         "ENROUTE", "EN_ROUTE", "EN ROUTE", "PICKED_UP", "PICKED UP",
                         "ONBOARD", "ON_BOARD", "ARRIVED")
_FA_ACCEPTED_MARKERS  = ("ACCEPT",)
_FA_UNACCEPTED_MARKERS = ("DISPATCH", "PENDING", "ASSIGN", "OFFER", "OPEN",
                          "NOT_ACCEPTED", "NOT ACCEPTED", "AWAITING", "UNACCEPT")


def classify_fa(status: str) -> str:
    s = (status or "").upper().strip()
    if not s:
        return "unknown"
    # Exact-match check for ambiguous FA statuses that share substrings with
    # other markers. "SCHEDULED" = driver assigned, not yet accepted.
    if s == "SCHEDULED":
        return "unaccepted"
    # Priority order matters. Unaccepted checked BEFORE accepted because
    # strings like "NOT_ACCEPTED" / "AWAITING_ACCEPTANCE" contain "ACCEPT".
    if any(m in s for m in _FA_DECLINED_MARKERS):   return "declined"
    if any(m in s for m in _FA_COMPLETED_MARKERS):  return "completed"
    if any(m in s for m in _FA_CANCELLED_MARKERS):  return "cancelled"
    if any(m in s for m in _FA_STARTED_MARKERS):    return "started"
    if any(m in s for m in _FA_UNACCEPTED_MARKERS): return "unaccepted"
    if any(m in s for m in _FA_ACCEPTED_MARKERS):   return "accepted"
    return "unknown"


# EverDriven — enumerated states from ALC API + driverGUID presence.
_ED_STATE_MAP = {
    "Scheduled":       "accepted",   # with driverGUID; without → unaccepted (handled below)
    "Accepted":        "accepted",
    "Active":          "started",
    "AtStop":          "started",
    "ToStop":          "started",    # en route between pickup and dropoff
    "Completed":       "completed",
    "Declined":        "declined",
    "Cancelled":       "cancelled",
    "Canceled":        "cancelled",
    "NoShow":          "cancelled",  # rider didn't appear; driver did their job, no action needed
    "NoShowReported":  "cancelled",  # explicit report variant of NoShow — same outcome
    "RiderCanceled":   "cancelled",  # rider cancelled before pickup — partner-side cancel
    "Expired":         "cancelled",  # trip window lapsed without pickup — no action needed
}


def classify_ed(
    status: str,
    driver_guid: str | None,
    any_trip_progressing: bool = False,
) -> str:
    """Classify an EverDriven run into a monitor bucket.

    Parameters
    ----------
    status:
        The top-level runState string from the EverDriven API (e.g. "Accepted",
        "Scheduled", "Active").
    driver_guid:
        The driverGUID from payload.driverGUID — present when a driver is
        assigned.
    any_trip_progressing:
        True when at least one entry in payload.trips[].tripState is Active,
        OnBoard, or Completed.  ED's runState only flips Accepted→Active when
        the driver taps "At Pickup" in the app; most drivers skip this tap.
        Per-trip state updates more reliably, so we promote an "Accepted"
        run to "started" as soon as any trip shows progress.

    Returns
    -------
    One of: "unaccepted", "accepted", "started", "completed", "cancelled",
            "declined", or "unknown".
    """
    s = (status or "").strip()
    if not s and not driver_guid:
        return "unaccepted"  # no status, no driver = unassigned
    if not s:
        return "unknown"
    bucket = _ED_STATE_MAP.get(s)
    if bucket is None:
        return "unknown"
    # Scheduled without a driver = unaccepted; with driver = accepted
    if bucket == "accepted" and not driver_guid:
        return "unaccepted"
    # runState=Accepted but a per-trip state shows the driver is already
    # en route — promote to "started" so Stage 2 does not fire false alerts.
    if bucket == "accepted" and any_trip_progressing:
        return "started"
    return bucket


# ── Arrival detection helper ─────────────────────────────────
# Identifies raw partner status strings that signal the driver has arrived
# at the pickup location.  These map to classified bucket "started" in the
# existing escalation logic; we keep that mapping unchanged and detect the
# more-specific arrival event separately for scorecard purposes.
#
# ED: "AtStop"  — driver tapped "At Pickup" in the app.
# FA: "ARRIVED", "PICKED_UP", "PICKED UP" — sub-markers inside _FA_STARTED_MARKERS.
_ED_ARRIVAL_STATUSES: frozenset[str] = frozenset({"AtStop"})
_FA_ARRIVAL_MARKERS: tuple[str, ...] = ("ARRIVED", "PICKED_UP", "PICKED UP", "ONBOARD", "ON_BOARD")


def _is_arrival_raw_status(source: str, raw_status: str) -> bool:
    """Return True when the raw partner status indicates arrival at pickup."""
    if not raw_status:
        return False
    if source == "everdriven":
        return raw_status.strip() in _ED_ARRIVAL_STATUSES
    if source == "firstalt":
        s = raw_status.upper().strip()
        return any(m in s for m in _FA_ARRIVAL_MARKERS)
    return False


# ── Hot/cold window partition ────────────────────────────────
# A trip is "hot" when it needs tight (60s) polling:
#   - pickup_time is within the next _HOT_WINDOW_LEAD_MINUTES, OR
#   - pickup was within the past _HOT_WINDOW_LOOKBACK_HOURS (trip still running)
#   AND the trip has no completed_at yet (i.e. still in-flight)
#
# Everything else is "cold": pickup is far in the future, or it's a just-
# scheduled trip we don't need to watch closely yet.
#
# The partition operates on the same dicts the main cycle builds — each dict
# has a "pickup_time" text string and a "bucket" (classified status).
#
# NOTE: we partition by pickup_dt relative to now. Trips whose pickup_time
# can't be parsed fall into cold (we can't determine urgency → conservative).


def _is_hot_trip(trip: dict, now: datetime, today: "date", tz: "ZoneInfo") -> bool:  # noqa: F821
    """Return True when a trip should be polled on the fast (60s) loop.

    Hot criteria (either):
      1. Pickup is imminent: now is within _HOT_WINDOW_LEAD_MINUTES of pickup_time
         (i.e. pickup_time ≤ now + lead)
      2. Trip is already in-flight: pickup was in the past _HOT_WINDOW_LOOKBACK_HOURS
         and the trip is not yet completed (bucket != 'completed'/'cancelled'/'declined')

    Trips that can't be parsed → cold (safe default, won't miss anything; cold
    loop still processes them every 10 min).
    """
    # Completed/cancelled/declined trips don't need any active polling.
    if trip.get("bucket") in ("completed", "cancelled", "declined"):
        return False

    pickup_dt = _parse_pickup_time(trip.get("pickup_time", ""), today, tz)
    if pickup_dt is None:
        return False  # can't determine urgency → cold

    lead_threshold = now + timedelta(minutes=_HOT_WINDOW_LEAD_MINUTES)
    lookback_threshold = now - timedelta(hours=_HOT_WINDOW_LOOKBACK_HOURS)

    # Imminent: pickup hasn't passed yet but is close
    if now <= pickup_dt <= lead_threshold:
        return True

    # In-flight: pickup is in the past but within lookback window and not done
    if lookback_threshold <= pickup_dt < now:
        return True

    return False


def partition_trips_by_window(
    trips: list[dict],
    now: datetime,
    today: "date",  # noqa: F821
    tz: "ZoneInfo",  # noqa: F821
) -> tuple[list[dict], list[dict]]:
    """Split trips into (hot_trips, cold_trips).

    Disjoint by construction: a trip is hot XOR cold — never both.
    Completed/cancelled/declined trips are excluded from both lists; they
    require no further polling action.
    """
    terminal = {"completed", "cancelled", "declined"}
    hot: list[dict] = []
    cold: list[dict] = []
    for trip in trips:
        if trip.get("bucket") in terminal:
            continue  # no polling needed at all
        if _is_hot_trip(trip, now, today, tz):
            hot.append(trip)
        else:
            cold.append(trip)
    return hot, cold


# ── Speech-friendly time formatter ───────────────────────────
def _speak_time(raw: str) -> str:
    """Format pickup time strings for speech: '2026-04-21T08:17:30' -> '8:17 AM'.
    Pass-through strings already in human format (e.g. '07:40 AM').
    """
    if not raw:
        return "unknown time"
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            dt = datetime.strptime(raw[:19], fmt)
            return dt.strftime("%-I:%M %p")
        except ValueError:
            continue
    # Try short HH:MM (FirstAlt format like "07:40") — convert to 12-hr
    if len(raw) <= 5 and ":" in raw:
        try:
            h, m = raw.split(":")
            dt = datetime(2000, 1, 1, int(h), int(m))
            return dt.strftime("%-I:%M %p")
        except (ValueError, TypeError):
            pass
    return raw  # already readable (e.g. "7:40 AM") — leave alone


# ── Time parsing ──────────────────────────────────────────────
def _make_local_dt(trip_date: date, hour: int, minute: int, tz: ZoneInfo) -> datetime:
    """Build a tz-aware datetime, DST-safe (R5).

    fold=0 picks the earlier instant on ambiguous fall-back times. For
    spring-forward gaps, ZoneInfo still returns a usable datetime; the
    per-trip DST check in _process_one_trip warns when offsets disagree.
    """
    return datetime(trip_date.year, trip_date.month, trip_date.day,
                    hour, minute, tzinfo=tz, fold=0)


def _parse_pickup_time(pickup_str: str, trip_date: date, tz: ZoneInfo) -> datetime | None:
    """Parse pickup time string to a timezone-aware datetime (DST-safe)."""
    if not pickup_str:
        return None
    try:
        # Try HH:MM format (FirstAlt)
        if len(pickup_str) <= 5 and ":" in pickup_str:
            h, m = pickup_str.split(":")
            return _make_local_dt(trip_date, int(h), int(m), tz)
        # Try ISO-ish format (EverDriven: "2026-04-06T06:30")
        if "T" in pickup_str:
            dt = datetime.fromisoformat(pickup_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = _make_local_dt(trip_date, dt.hour, dt.minute, tz)
            return dt
        # Try HH:MM AM/PM
        for fmt in ("%I:%M %p", "%I:%M%p"):
            try:
                t = datetime.strptime(pickup_str, fmt)
                return _make_local_dt(trip_date, t.hour, t.minute, tz)
            except ValueError:
                continue
    except (ValueError, TypeError):
        pass
    return None


# ── Main monitoring cycle ─────────────────────────────────────
def run_monitoring_cycle(
    window: str = "all",
    poll_interval_seconds: int | None = None,
) -> dict:
    """
    Execute one monitoring cycle. Called by APScheduler on interval.
    Returns a summary dict for dashboard consumption.

    Parameters
    ----------
    window:
        'hot'  — only trips within _HOT_WINDOW_LEAD_MINUTES of pickup through
                 completion (used by the fast 60s loop).
        'cold' — everything else relevant (used by the slow 10min loop).
        'all'  — no partition (legacy flat-interval fallback).
    poll_interval_seconds:
        Expected max staleness of detected_at timestamps written into
        TripStatusEvent rows this cycle. Threaded down to Phase 2 transition
        detection so the scorecard can reason about timestamp confidence.
        Defaults to _INTERVAL * 60 when None (legacy behaviour).

    R6: Wrapped in a non-blocking lock acquire per window. Hot and cold loops
    share a single lock so they can't overlap each other either.
    """
    if not _cycle_lock.acquire(blocking=False):
        logger.warning(
            "[trip-monitor] Prior cycle still running — skipping this tick (window=%s)", window
        )
        return {"skipped": True, "reason": "prior cycle still running"}
    try:
        return _run_monitoring_cycle_impl(
            window=window,
            poll_interval_seconds=poll_interval_seconds,
        )
    finally:
        _cycle_lock.release()


def run_hot_cycle() -> dict:
    """Entry point for the hot (60s) APScheduler job."""
    return run_monitoring_cycle(window="hot", poll_interval_seconds=_HOT_INTERVAL_SECONDS)


def run_cold_cycle() -> dict:
    """Entry point for the cold (10min) APScheduler job."""
    return run_monitoring_cycle(window="cold", poll_interval_seconds=_COLD_INTERVAL_SECONDS)


def _run_monitoring_cycle_impl(
    window: str = "all",
    poll_interval_seconds: int | None = None,
) -> dict:
    """Inner cycle body — assumes the caller holds _cycle_lock.

    Parameters
    ----------
    window:
        'hot', 'cold', or 'all' — controls which trips are processed this cycle.
    poll_interval_seconds:
        Written into TripStatusEvent rows so the scorecard knows how stale
        detected_at can be. Defaults to _INTERVAL * 60 when None.
    """
    _poll_interval = poll_interval_seconds if poll_interval_seconds is not None else _INTERVAL * 60
    tz = ZoneInfo(_TZ_NAME)
    now = datetime.now(tz)

    # Operating hours gate
    if now.hour < _START_HOUR or now.hour >= _END_HOUR:
        logger.debug("[trip-monitor] Outside operating hours (%d:%02d), skipping", now.hour, now.minute)
        _last_run_info["last_run"] = now.isoformat()
        _last_run_info["summary"] = "Skipped — outside operating hours"
        return {"skipped": True}

    from backend.db import SessionLocal
    from backend.db.models import TripNotification, TripStatusEvent, Person, NotificationEvent
    from backend.services import notification_service as _notify_real
    from backend.services.call_scripts import get_call_script, get_sms_script
    from backend.services.ops_alert import route_dispatch_alert

    if _DRY_RUN:
        class _DryNotify:
            def send_sms(self, phone, msg): logger.info("[DRY RUN] SMS→%s: %s", phone, msg[:80])
            def make_call(self, phone, msg, **kw): logger.info("[DRY RUN] CALL→%s: %s", phone, msg[:80])
            def alert_admin(self, msg, **kw): logger.info("[DRY RUN] ADMIN: %s", msg[:100])
            def normalize_phone(self, phone): return phone
        notify = _DryNotify()
    else:
        notify = _notify_real

    db = SessionLocal()
    summary = {
        "trips_checked": 0,
        "accept_sms": 0, "accept_calls": 0, "accept_escalations": 0,
        "start_sms": 0, "start_calls": 0, "start_escalations": 0,
        "errors": [],
    }

    # ── Postgres advisory lock — prevents duplicate alerts when Railway
    # auto-scales to multiple backend instances. Each instance tries to
    # grab the same session-level lock; only one succeeds per cycle window.
    # Lock key: hashtext('zpay_monitor_cycle') — unique to this function,
    # no collision with any other advisory lock in this repo.
    from sqlalchemy import text as _sa_text
    try:
        _lock_result = db.execute(
            _sa_text("SELECT pg_try_advisory_lock(hashtext('zpay_monitor_cycle'))")
        ).scalar()
    except Exception as _lock_err:
        # If the DB doesn't support advisory locks (e.g. SQLite in tests),
        # log and continue — the thread-level _cycle_lock still protects.
        _lock_result = True
        logger.debug("[trip-monitor] advisory lock unavailable (non-PG?): %s", _lock_err)

    if not _lock_result:
        logger.info(
            "[trip-monitor] advisory lock busy — another instance is running this cycle, skipping."
        )
        db.close()
        summary["lock_unavailable"] = True
        _last_run_info["last_run"] = now.isoformat()
        _last_run_info["summary"] = summary
        return summary

    try:
        today = now.date()  # must match tz of `now` — Railway runs UTC, drivers are Pacific

        # ── Step 1: Pull live data ──
        fa_trips = []
        ed_runs = []

        fa_ok = False
        ed_ok = False
        try:
            from backend.services import firstalt_service
            fa_trips = firstalt_service.get_trips(today)
            fa_ok = True
        except Exception as e:
            summary["errors"].append(f"FirstAlt: {e}")
            logger.error("[trip-monitor] FirstAlt fetch failed: %s", e)

        try:
            from backend.services import everdriven_service
            ed_runs = everdriven_service.get_runs(today)
            ed_ok = True
        except Exception as e:
            summary["errors"].append(f"EverDriven: {e}")
            logger.error("[trip-monitor] EverDriven fetch failed: %s", e)

        # ── Per-partner failure alerts ──
        # If a single partner fetch fails (but the other is up), we still
        # process what we can — but Malik needs to know one side is blind.
        # Deduped per (source, day) so he only gets one alert per day per partner.
        if not fa_ok:
            _fa_key = (today.isoformat(), "firstalt")
            if _fa_key not in _partner_fail_alerted:
                _fa_err_str = summary["errors"][0] if summary["errors"] else "unknown error"
                try:
                    notify.alert_admin(
                        f"FIRSTALT API DOWN — fetch failed this cycle: {_fa_err_str}. "
                        "Trips from FA won't be monitored until this clears. "
                        "Check cognito/creds.",
                        spoken_message="FirstAlt is down. Trip monitor can't see FirstAlt trips.",
                    )
                except Exception as _fa_alert_err:
                    logger.error("[trip-monitor] Failed to send FA partner-fail alert: %s", _fa_alert_err)
                _partner_fail_alerted.add(_fa_key)

        if not ed_ok:
            _ed_key = (today.isoformat(), "everdriven")
            if _ed_key not in _partner_fail_alerted:
                _ed_err_str = next(
                    (e for e in summary["errors"] if "EverDriven" in e), summary["errors"][-1] if summary["errors"] else "unknown error"
                )
                try:
                    notify.alert_admin(
                        f"EVERDRIVEN API DOWN — fetch failed this cycle: {_ed_err_str}. "
                        "Trips from ED won't be monitored until this clears. "
                        "Check ALC credentials.",
                        spoken_message="EverDriven is down. Trip monitor can't see EverDriven trips.",
                    )
                except Exception as _ed_alert_err:
                    logger.error("[trip-monitor] Failed to send ED partner-fail alert: %s", _ed_alert_err)
                _partner_fail_alerted.add(_ed_key)

        # ── CRITICAL: Both partner APIs failed — monitor is BLIND this cycle ──
        # We can't see trips, so we can't call drivers or escalate. Alert Malik
        # so he knows the automation is down and he should check manually.
        # Deduped via a module-global set keyed to today — one alert per day.
        if not fa_ok and not ed_ok:
            if today.isoformat() not in _blind_cycle_alerted:
                try:
                    notify.alert_admin(
                        "MONITOR BLIND — both FirstAlt and EverDriven API fetches "
                        "failed this cycle. System cannot see any trips. "
                        "Check partner portals manually until this clears.",
                        spoken_message=(
                            "FirstAlt and EverDriven are both down. "
                            "The system can't see any trips."
                        ),
                    )
                except Exception as alert_err:
                    logger.error("[trip-monitor] Failed to send blind-cycle alert: %s", alert_err)
                _blind_cycle_alerted.add(today.isoformat())
                summary.setdefault("blind_cycle_alerts", 0)
                summary["blind_cycle_alerts"] += 1

        # ── Step 2: Build person lookup ──
        persons = db.query(Person).filter(Person.active == True).all()
        fa_id_to_person = {p.firstalt_driver_id: p for p in persons if p.firstalt_driver_id}
        ed_id_to_person = {str(p.everdriven_driver_id): p for p in persons if p.everdriven_driver_id}

        # ── Step 3: Process all trips ──
        all_trips = []

        for t in fa_trips:
            trip_id = str(t.get("tripId") or t.get("id") or "")
            if not trip_id:
                continue
            driver_id = t.get("driverId")
            person = fa_id_to_person.get(driver_id)
            status = t.get("tripStatus") or t.get("status") or ""
            bucket = classify_fa(status)
            all_trips.append({
                "source": "firstalt",
                "trip_ref": trip_id,
                "status": status,
                "bucket": bucket,
                "pickup_time": t.get("firstPickUp") or "",
                "person": person,
                "is_unaccepted": bucket == "unaccepted",
                "is_accepted": bucket == "accepted",
                "is_started": bucket == "started",
                "is_declined": bucket == "declined",
                "driver_name": ((t.get("driverFirstName") or "") + " " + (t.get("driverLastName") or "")).strip(),
            })

        for r in ed_runs:
            key = r.get("keyValue") or ""
            if not key:
                continue
            driver_id = r.get("driverId")
            person = ed_id_to_person.get(str(driver_id)) if driver_id else None
            status = r.get("tripStatus") or ""
            driver_guid = r.get("driverGUID")
            any_trip_progressing = r.get("any_trip_progressing", False)
            bucket = classify_ed(status, driver_guid, any_trip_progressing)
            all_trips.append({
                "source": "everdriven",
                "trip_ref": key,
                "status": status,
                "bucket": bucket,
                "pickup_time": r.get("firstPickUp") or "",
                "person": person,
                "is_unaccepted": bucket == "unaccepted",
                "is_accepted": bucket == "accepted",
                "is_started": bucket == "started",
                "is_declined": bucket == "declined",
                "driver_name": r.get("driverName") or "",
            })

        # ── Step 3b: Apply window partition ──────────────────────────────
        # hot/cold: filter to the relevant subset for this cycle.
        # 'all': no filter (legacy flat-interval path).
        if window == "hot":
            trips_to_process = [t for t in all_trips if _is_hot_trip(t, now, today, tz)]
            logger.info(
                "[trip-monitor] HOT cycle — %d/%d trips in hot window",
                len(trips_to_process), len(all_trips),
            )
        elif window == "cold":
            trips_to_process = [t for t in all_trips if not _is_hot_trip(t, now, today, tz)]
            logger.info(
                "[trip-monitor] COLD cycle — %d/%d trips in cold window",
                len(trips_to_process), len(all_trips),
            )
        else:
            trips_to_process = all_trips

        summary["trips_checked"] = len(trips_to_process)
        summary["name_mismatches"] = 0
        summary["unknown_status_alerts"] = 0
        summary["declines"] = 0
        summary["start_suppressed_concurrent"] = 0

        # Drivers currently mid-ride on any trip — used to suppress Start
        # alerts on their *other* trips. A driver dropping off kid A at
        # 08:08 cannot also be picking up kid B at 08:13.
        # Use all_trips for the busy-driver check regardless of window so we
        # never falsely nag a driver whose "started" trip is in the other window.
        busy_drivers: set[int] = {
            t["person"].person_id
            for t in all_trips
            if t.get("person") and t.get("is_started")
        }

        # ── Step 4: Upsert TripNotification rows + process ──
        # R1: each trip is processed in isolation by this nested helper.
        # `return` replaces the previous `continue`. Outer loop wraps each
        # call in try/except + per-trip commit so one bad trip can't wipe
        # the notification state of the others — preventing the duplicate-
        # SMS bug where a trip-50 exception rolled back trip-1..49's state.
        def _process_one_trip(trip):
            person = trip["person"]
            if not person:
                return  # Can't notify unlinked drivers

            # ── Safety: cross-verify API driver name against DB person ──
            # Partners sometimes reassign driver IDs. A mismatch means the DB
            # has stale data — we never silently skip; we alert Malik so the
            # mapping can be corrected at the source.
            name_mismatch = False
            api_name_raw = (trip.get("driver_name") or "").strip()
            db_name_raw  = (person.full_name or "").strip()
            api_name = api_name_raw.lower()
            db_name = db_name_raw.lower()
            if api_name and db_name:
                api_tokens = {tok for tok in api_name.split() if len(tok) > 1}
                db_tokens = {tok for tok in db_name.split() if len(tok) > 1}
                if api_tokens and db_tokens and not (api_tokens & db_tokens):
                    name_mismatch = True

            if name_mismatch:
                source_label = "FirstAlt" if trip["source"] == "firstalt" else "EverDriven"
                stale_id = getattr(person, f"{trip['source']}_driver_id", "?")
                logger.error(
                    "[trip-monitor] NAME MISMATCH — source=%s ref=%s API='%s' DB='%s' stale_id=%s",
                    trip["source"], trip["trip_ref"], api_name_raw, db_name_raw, stale_id,
                )

                # Upsert a notif so the alert is deduped per trip per day.
                mismatch_notif = db.query(TripNotification).filter(
                    TripNotification.source == trip["source"],
                    TripNotification.trip_ref == trip["trip_ref"],
                    TripNotification.trip_date == today,
                ).first()
                if not mismatch_notif:
                    mismatch_notif = TripNotification(
                        person_id=person.person_id,
                        trip_date=today,
                        source=trip["source"],
                        trip_ref=trip["trip_ref"],
                        trip_status=trip["status"],
                        pickup_time=trip["pickup_time"],
                    )
                    db.add(mismatch_notif)
                    db.flush()

                if not mismatch_notif.accept_escalated_at:
                    _mm_msg = (
                        f"NAME MISMATCH — {source_label} trip {trip['trip_ref']}: "
                        f"API says driver is '{api_name_raw or '?'}' but DB has "
                        f"'{db_name_raw or '?'}' (stored {trip['source']}_driver_id={stale_id}). "
                        f"Fix the mapping in Z-Pay before this driver's next trip."
                    )
                    notify.alert_admin(
                        _mm_msg,
                        spoken_message=(
                            f"Heads up — the API and the database disagree on who's driving trip "
                            f"{trip['trip_ref']}. Check the mapping."
                        ),
                    )
                    # Phase 3: operator attention needed but not time-critical → normal
                    # sms_already_sent=True: notify.alert_admin above handled SMS
                    route_dispatch_alert("normal", f"NAME MISMATCH — {source_label} {trip['trip_ref']}", _mm_msg, sms_already_sent=True)
                    mismatch_notif.dispatch_severity = "normal"
                    mismatch_notif.accept_escalated_at = now
                    summary["name_mismatches"] += 1
                # R1: per-trip commit happens in the outer loop after this
                # function returns successfully. We used to commit inline here.
                # Don't run stages — we don't trust the mapping. Alert fires; Malik fixes.
                return

            # Upsert TripNotification row FIRST so we can dedup alerts against it.
            notif = db.query(TripNotification).filter(
                TripNotification.source == trip["source"],
                TripNotification.trip_ref == trip["trip_ref"],
                TripNotification.trip_date == today,
            ).first()

            notif_is_new = False
            if not notif:
                notif = TripNotification(
                    person_id=person.person_id,
                    trip_date=today,
                    source=trip["source"],
                    trip_ref=trip["trip_ref"],
                    trip_status=trip["status"],
                    pickup_time=trip["pickup_time"],
                )
                db.add(notif)
                db.flush()
                notif_is_new = True
            else:
                notif.trip_status = trip["status"]

                # R2: Reschedule detection. Always sync pickup_time so timing
                # logic below uses the latest. Only reset Start-stage state
                # for meaningful shifts (>= _RESCHEDULE_RESET_MINUTES) — sub-
                # 30min deltas are API jitter. Accept-stage state is preserved:
                # the driver already knows the trip exists.
                old_pickup_str = notif.pickup_time or ""
                new_pickup_str = trip["pickup_time"] or ""
                if old_pickup_str != new_pickup_str:
                    old_dt = _parse_pickup_time(old_pickup_str, today, tz)
                    new_dt = _parse_pickup_time(new_pickup_str, today, tz)
                    delta_minutes = None
                    if old_dt and new_dt:
                        delta_minutes = (new_dt - old_dt).total_seconds() / 60
                    notif.pickup_time = new_pickup_str
                    if delta_minutes is not None and delta_minutes >= _RESCHEDULE_RESET_MINUTES:
                        logger.info(
                            "[trip-monitor] RESCHEDULE — %s ref=%s pickup %s -> %s (+%.0f min). "
                            "Resetting Start-stage state.",
                            trip["source"], trip["trip_ref"], old_pickup_str, new_pickup_str,
                            delta_minutes,
                        )
                        notif.start_sms_at = None
                        notif.start_call_at = None
                        notif.start_escalated_at = None
                        notif.overdue_alerted_at = None
                    else:
                        logger.info(
                            "[trip-monitor] pickup_time updated — %s ref=%s %s -> %s (delta=%s)",
                            trip["source"], trip["trip_ref"], old_pickup_str, new_pickup_str,
                            f"{delta_minutes:.0f}m" if delta_minutes is not None else "?",
                        )

            # ── UNKNOWN STATUS — no silent failures, deduped via accept_escalated_at.
            # R4: If the trip already moved through started (notif.started_at
            # set), the new unknown is likely a sub-state we haven't mapped
            # yet (completion variant, transient code). Fire one quieter alert
            # — never nag the driver — so Malik can extend the maps later.
            if trip["bucket"] == "unknown":
                logger.error(
                    "[trip-monitor] UNKNOWN STATUS — source=%s ref=%s status=%r driver=%s started_at=%s",
                    trip["source"], trip["trip_ref"], trip["status"], person.full_name,
                    notif.started_at,
                )
                already_started = notif.started_at is not None
                source_label = "FirstAlt" if trip["source"] == "firstalt" else "EverDriven"
                if not notif.accept_escalated_at and not already_started:
                    _unk_first = (person.full_name or "").split()[0] or "Driver"
                    notify.alert_admin(
                        f"UNKNOWN STATUS — {source_label} trip {trip['trip_ref']} "
                        f"for {person.full_name} at {trip['pickup_time'] or '?'}. "
                        f"Status: '{trip['status']}'. "
                        f"Check the dashboard now — system doesn't know how to handle this.",
                        spoken_message=(
                            f"{_unk_first}'s trip has a status I don't recognize. "
                            f"Check the dashboard."
                        ),
                    )
                    notif.accept_escalated_at = now
                    summary["unknown_status_alerts"] += 1
                elif already_started and not notif.accept_escalated_at:
                    notify.alert_admin(
                        f"UNKNOWN POST-START STATUS — {source_label} trip {trip['trip_ref']}: "
                        f"'{trip['status']}'. Trip already started. Likely a status code we "
                        f"haven't mapped — please add it to _ED_STATE_MAP / _FA markers.",
                    )
                    notif.accept_escalated_at = now
                    summary["unknown_status_alerts"] += 1
                return

            # ── Transition detection — scorecard data capture ─────────────────
            # Compare the previously-stored raw status against the new one.
            # On any classified-status change, append a trip_status_event row.
            # Also set arrived_at_pickup / completed_at on the notif (once,
            # on first observation) so scorecard queries don't need to touch
            # trip_status_event directly for the two key derived timestamps.
            #
            # Crucially: notif.trip_status holds the PREVIOUS raw status at
            # this point in the code — it was set on the prior cycle and has
            # not been overwritten yet for new trips (notif_is_new == False).
            # For brand-new notifs (notif_is_new == True) prev_status is None.
            _prev_raw = None if notif_is_new else (notif.trip_status or None)
            _new_raw = trip["status"] or None

            # Classify both sides using the same helpers the escalation logic
            # uses so the event log is consistent with dispatch decisions.
            if trip["source"] == "firstalt":
                _prev_classified = classify_fa(_prev_raw or "") if _prev_raw else None
                _new_classified = classify_fa(_new_raw or "") if _new_raw else None
            else:
                # For ED we don't have driver_guid / any_trip_progressing at
                # this scope, so use the already-computed trip["bucket"] for
                # the new side and re-classify prev with the same heuristic.
                _prev_classified = (
                    classify_ed(_prev_raw or "", None) if _prev_raw else None
                )
                _new_classified = trip["bucket"] if _new_raw else None

            _status_changed = (
                _new_classified is not None
                and _new_classified != "unknown"
                and _new_classified != _prev_classified
            )

            if _status_changed:
                _event = TripStatusEvent(
                    trip_notification_id=notif.id,
                    source=trip["source"],
                    trip_ref=trip["trip_ref"],
                    person_id=person.person_id,
                    prev_status=_prev_classified,
                    new_status=_new_classified,
                    detected_at=now,
                    poll_interval_seconds=_poll_interval,
                    raw_partner_status=_new_raw,
                )
                db.add(_event)
                logger.debug(
                    "[trip-monitor] STATUS TRANSITION — source=%s ref=%s %s→%s raw=%r",
                    trip["source"], trip["trip_ref"],
                    _prev_classified, _new_classified, _new_raw,
                )

                # Derived timestamp: arrived_at_pickup (set once on first arrival)
                if (
                    notif.arrived_at_pickup is None
                    and _is_arrival_raw_status(trip["source"], _new_raw or "")
                ):
                    notif.arrived_at_pickup = now

                # Derived timestamp: completed_at (set once on first completion)
                if notif.completed_at is None and _new_classified == "completed":
                    notif.completed_at = now

            # Update acceptance/start status
            just_accepted = False
            if trip["is_started"] and not notif.started_at:
                notif.started_at = now
            if (trip["is_accepted"] or trip["is_started"]) and not notif.accepted_at:
                notif.accepted_at = now
                just_accepted = True

            pickup_dt = _parse_pickup_time(trip["pickup_time"], today, tz)

            # R5: warn (don't crash) on DST transition days where the pickup's
            # UTC offset disagrees with now's offset — alerts may be mis-timed.
            try:
                if (
                    pickup_dt is not None
                    and pickup_dt.utcoffset() is not None
                    and now.utcoffset() is not None
                    and pickup_dt.date() == now.date()
                    and pickup_dt.utcoffset() != now.utcoffset()
                ):
                    logger.warning(
                        "[trip-monitor] DST OFFSET MISMATCH — %s ref=%s pickup=%s "
                        "(offset=%s) vs now offset=%s — DST transition day?",
                        trip["source"], trip["trip_ref"], trip["pickup_time"],
                        pickup_dt.utcoffset(), now.utcoffset(),
                    )
            except (AttributeError, TypeError) as _dst_err:
                logger.debug("[trip-monitor] DST check skipped: %s", _dst_err)

            driver_phone = person.phone
            # Title-case the first token so "ELZAKI abdala" becomes "Elzaki" not "ELZAKI"
            driver_name = ((person.full_name or "").split()[0] or "Driver").title()
            source_label = "FirstAlt" if trip["source"] == "firstalt" else "EverDriven"

            # ── STAGE 0: DECLINE — highest priority, alert Malik immediately ──
            # Driver tapped "Substitute Needed" / declined. We never contact the
            # driver (they opted out). We alert Malik so he can assign a sub
            # before the partner sees a missed trip. Dedup via accept_escalated_at.
            if trip.get("is_declined"):
                if not notif.accept_escalated_at:
                    mins_left = None
                    if pickup_dt:
                        mins_left = round((pickup_dt - now).total_seconds() / 60)
                    when = (
                        f"{mins_left} min away" if mins_left is not None and mins_left >= 0
                        else (f"{-mins_left} min OVERDUE" if mins_left is not None else trip["pickup_time"])
                    )
                    _dec_first = (person.full_name or "").split()[0] or "Driver"
                    _dec_msg = (
                        f"DECLINE — {person.full_name} declined {source_label} trip "
                        f"{trip['trip_ref']} at {trip['pickup_time']} ({when}). "
                        f"NEEDS SUB NOW."
                    )
                    _dec_spoken = (
                        f"{_dec_first} just declined the "
                        f"{_speak_time(trip['pickup_time'])} trip. Needs a sub."
                    )
                    notify.alert_admin(_dec_msg, spoken_message=_dec_spoken, notif_id=notif.id)
                    # Phase 3: decline needs sub — urgent (sms_already_sent via notify.alert_admin above)
                    route_dispatch_alert("urgent", f"DECLINE — {person.full_name}", _dec_msg, sms_already_sent=True, notif_id=notif.id)
                    notif.dispatch_severity = "urgent"
                    notif.accept_escalated_at = now
                    summary["accept_escalations"] += 1
                    summary.setdefault("declines", 0)
                    summary["declines"] += 1
                # Do not run accept/start stages for a declined trip.
                return
            driver_lang = person.language or "en"

            # ── PICKUP TIME PARSE FAILURE ──
            # If we can't parse the pickup time AND the trip is not already in
            # progress / done, we can't know when to act. Alert Malik so the
            # time format or the trip itself can be investigated. No silent skip.
            if pickup_dt is None and trip["bucket"] in ("unaccepted", "accepted"):
                if not notif.accept_escalated_at:
                    _tpf_first = (person.full_name or "").split()[0] or "Driver"
                    notify.alert_admin(
                        f"TIME PARSE FAIL — {source_label} trip {trip['trip_ref']} "
                        f"for {person.full_name}. Pickup='{trip['pickup_time']}' "
                        f"(can't read it). Status='{trip['status']}'. "
                        f"Check this trip manually NOW.",
                        spoken_message=(
                            f"Can't read the pickup time on {_tpf_first}'s trip. "
                            f"Check it manually."
                        ),
                    )
                    notif.accept_escalated_at = now
                    summary.setdefault("time_parse_failures", 0)
                    summary["time_parse_failures"] += 1
                return

            # ── OVERDUE — pickup time has passed and trip is NOT on the road ──
            # This is the most critical alert type. Driver either never accepted
            # or accepted but never started, and we're already past pickup time.
            # Fast-track: call Malik immediately, bypass SMS/wait chain entirely.
            #
            # Concurrent-trip guard: if this driver is currently mid-ride on
            # another trip, they're running back-to-back and the next trip
            # being "overdue" is expected. Suppress until the prior drop
            # completes; the next cycle will re-evaluate.
            if (
                pickup_dt is not None
                and now >= pickup_dt + timedelta(minutes=_OVERDUE_GRACE)
                and trip["bucket"] in ("unaccepted", "accepted")
                and person.person_id not in busy_drivers
            ):
                mins_overdue = round((now - pickup_dt).total_seconds() / 60)
                problem = (
                    "NEVER ACCEPTED" if trip["bucket"] == "unaccepted"
                    else "ACCEPTED BUT NEVER STARTED"
                )
                # Dedicated overdue_alerted_at field — independent of Stage 1 accept_escalated_at
                # so pre-pickup escalations never silence the overdue alert.
                if not notif.overdue_alerted_at:
                    _ov_first = (person.full_name or "").split()[0] or "Driver"
                    _ov_msg = (
                        f"OVERDUE {mins_overdue} MIN — {source_label} trip "
                        f"{trip['trip_ref']} | {person.full_name} | pickup was "
                        f"{trip['pickup_time']} | {problem}. ACT NOW."
                    )
                    _ov_spoken = (
                        f"{_ov_first} is {mins_overdue} minutes overdue. "
                        f"{'Accepted but never started' if trip['bucket'] == 'accepted' else 'Never accepted'}. "
                        f"Pickup was {_speak_time(trip['pickup_time'])}."
                    )
                    notify.alert_admin(_ov_msg, spoken_message=_ov_spoken, notif_id=notif.id)
                    # Phase 3: missed pickup → critical (life/safety adjacent)
                    # sms_already_sent=True because notify.alert_admin above handles SMS
                    route_dispatch_alert(
                        "critical",
                        f"OVERDUE {mins_overdue}MIN — {person.full_name}",
                        _ov_msg,
                        spoken_message=_ov_spoken,
                        sms_already_sent=True,
                        notif_id=notif.id,
                    )
                    notif.dispatch_severity = "critical"
                    notif.overdue_alerted_at = now
                    summary.setdefault("overdue_alerts", 0)
                    summary["overdue_alerts"] += 1
                # Do not run normal stages — Malik is already calling the shots.
                return

            # ── Skip trips that are not actionable (cancelled / completed / etc.) ──
            # Only unaccepted or accepted trips need the SMS/call/escalation chain.
            # Without this gate, cancelled trips fall through to Stage 1 because
            # notif.accepted_at is null — and we end up calling drivers for rides
            # that no longer exist.
            if trip["bucket"] not in ("unaccepted", "accepted", "started"):
                return

            # ── Phase 2: Operator override guards ────────────────────────────────
            # 1. Manually resolved — operator clicked "Got it". No more escalation.
            if getattr(notif, "manually_resolved_at", None) is not None:
                summary.setdefault("skipped_resolved", 0)
                summary["skipped_resolved"] += 1
                return

            # 2. Snoozed — operator set a snooze window. Skip until it expires.
            _snoozed_until = getattr(notif, "snoozed_until", None)
            if _snoozed_until is not None and _snoozed_until > now:
                summary.setdefault("skipped_snoozed", 0)
                summary["skipped_snoozed"] += 1
                return

            # 3. Driver admin-alert mute — operator muted this driver's escalations.
            _alert_profile = person.alert_profile or {}
            _muted_until_str = _alert_profile.get("muted_until")
            if _muted_until_str:
                try:
                    _muted_until_dt = datetime.fromisoformat(_muted_until_str)
                    if _muted_until_dt > now:
                        # Still muted — skip ALL escalation for this driver.
                        # Driver-facing SMS still fires (handled in stages below)
                        # but we guard admin calls at each stage individually.
                        summary.setdefault("skipped_muted_driver", 0)
                        summary["skipped_muted_driver"] += 1
                        # Set a flag so stage logic can skip admin-only paths
                        _driver_admin_muted = True
                    else:
                        _driver_admin_muted = False
                except Exception:
                    _driver_admin_muted = False
            else:
                _driver_admin_muted = False
            # ──────────────────────────────────────────────────────────────────────

            # R3: API-lag grace. ED can take 30-90s to reflect Accept taps.
            # On brand-new notif rows, skip Stage 1 within that window so we
            # don't text drivers who already tapped. Bounded by
            # _API_LAG_GRACE_SECONDS — next cycle runs normally.
            if notif_is_new and notif.created_at is not None:
                try:
                    age_seconds = (now - notif.created_at).total_seconds()
                except TypeError:
                    # tz-aware vs naive mismatch — treat as old (skip grace)
                    age_seconds = _API_LAG_GRACE_SECONDS + 1
                if age_seconds < _API_LAG_GRACE_SECONDS:
                    summary.setdefault("api_lag_grace_skips", 0)
                    summary["api_lag_grace_skips"] += 1
                    return

            # ── STAGE 1: Accept check ──
            if not notif.accepted_at and trip["is_unaccepted"]:
                mins_until_pickup = (pickup_dt - now).total_seconds() / 60 if pickup_dt else None

                if mins_until_pickup is not None and mins_until_pickup <= _REMINDER_WINDOW:
                    if not driver_phone or not notify.normalize_phone(driver_phone):
                        # No phone — immediate escalation within proximity window
                        if not notif.accept_escalated_at:
                            _accept_within_window = (
                                pickup_dt is None
                                or (pickup_dt - now).total_seconds() <= _ACCEPT_ESC_WINDOW * 60
                            )
                            if _accept_within_window:
                                _nph_first = (person.full_name or "").split()[0] or "Driver"
                                notify.alert_admin(
                                    f"{person.full_name} has an unaccepted {source_label} trip "
                                    f"at {trip['pickup_time']} but has no phone number on file.",
                                    spoken_message=(
                                        f"{_nph_first} has an unaccepted trip at "
                                        f"{_speak_time(trip['pickup_time'])} but no phone on file. "
                                        f"Reach them directly."
                                    ),
                                )
                            notif.accept_escalated_at = now
                            notif.last_escalated_at = now
                            summary["accept_escalations"] += 1
                    else:
                        # SMS
                        if not notif.accept_sms_at:
                            sms_text = get_sms_script(
                                driver_lang, "accept",
                                driver_name=driver_name,
                                source=source_label,
                                pickup_time=_speak_time(trip["pickup_time"]),
                            )
                            notify.send_sms(driver_phone, sms_text)
                            notif.accept_sms_at = now
                            summary["accept_sms"] += 1
                            # Backfill original_pickup_dt when first SMS is sent —
                            # used by the backwards-reschedule guard below.
                            if notif.original_pickup_dt is None and pickup_dt is not None:
                                notif.original_pickup_dt = pickup_dt
                        elif notif.accept_sms_at and notif.original_pickup_dt is not None:
                            # Backwards-reschedule guard: if pickup has been moved
                            # EARLIER than when we first texted, don't re-fire.
                            # (The driver already knows about the trip; a time shift
                            # backwards doesn't require a new SMS and can cause confusion.)
                            if pickup_dt is not None and pickup_dt < notif.original_pickup_dt:
                                logger.info(
                                    "[trip-monitor] backwards reschedule detected for trip %s, "
                                    "suppressing SMS re-fire (orig=%s new=%s)",
                                    trip["trip_ref"],
                                    notif.original_pickup_dt,
                                    pickup_dt,
                                )
                                # Skip re-fire — fall through to call/escalation if applicable

                        # Call (30 min after SMS)
                        elif not notif.accept_call_at and notif.accept_sms_at:
                            if (now - notif.accept_sms_at).total_seconds() >= _CALL_DELAY * 60:
                                call_text = get_call_script(
                                    driver_lang, "accept",
                                    driver_name=driver_name,
                                    pickup_time=_speak_time(trip["pickup_time"]),
                                )
                                notify.make_call(driver_phone, call_text, language=driver_lang)
                                notif.accept_call_at = now
                                summary["accept_calls"] += 1

                        # Escalation — immediate after call (_ESCALATION_DELAY=0 by default)
                        elif not notif.accept_escalated_at and notif.accept_call_at:
                            if (now - notif.accept_call_at).total_seconds() >= _ESCALATION_DELAY * 60:
                                mins_left = round((pickup_dt - now).total_seconds() / 60) if pickup_dt else "?"
                                route = trip.get("trip_ref", "?")
                                _accept_within_window = (
                                    pickup_dt is None
                                    or (pickup_dt - now).total_seconds() <= _ACCEPT_ESC_WINDOW * 60
                                )
                                if _accept_within_window:
                                    _esc_first = (person.full_name or "").split()[0] or "Driver"
                                    _esc_msg = (
                                        f"UNACCEPTED TRIP — {person.full_name} | {source_label} | "
                                        f"Pickup: {trip['pickup_time']} ({mins_left} min away). "
                                        f"SMS + call sent. No response. You need to handle this."
                                    )
                                    _esc_spoken = (
                                        f"{_esc_first} hasn't accepted the "
                                        f"{_speak_time(trip['pickup_time'])} trip. "
                                        f"Texted and called — no response."
                                    )
                                    notify.alert_admin(_esc_msg, spoken_message=_esc_spoken, notif_id=notif.id)
                                    # Phase 3: back-to-back / unaccepted escalation → urgent
                                    # sms_already_sent=True because notify.alert_admin above handles SMS
                                    route_dispatch_alert(
                                        "urgent",
                                        f"UNACCEPTED TRIP — {person.full_name}",
                                        _esc_msg,
                                        sms_already_sent=True,
                                        notif_id=notif.id,
                                    )
                                    notif.dispatch_severity = "urgent"
                                    try:
                                        from backend.services.notification_service import send_whatsapp_alert
                                        send_whatsapp_alert(
                                            f"🚨 *UNACCEPTED TRIP*\n"
                                            f"Driver: {person.full_name}\n"
                                            f"Route: {route} ({source_label})\n"
                                            f"Pickup: {trip['pickup_time']} — {mins_left} min away\n"
                                            f"SMS + call sent. No response. Handle now."
                                        )
                                    except Exception as _wa_err:
                                        logger.warning("WhatsApp escalation alert failed: %s", _wa_err)
                                notif.accept_escalated_at = now
                                notif.last_escalated_at = now
                                summary["accept_escalations"] += 1

            # ── STAGE 2: Start check ──
            elif notif.accepted_at and not notif.started_at and trip["is_accepted"] and not just_accepted:
                # Concurrent-trip suppression: if this driver is currently
                # mid-ride on another trip (ToPickup/ToStop/etc.), they
                # physically cannot start this one yet. Don't nag.
                if person.person_id in busy_drivers:
                    summary["start_suppressed_concurrent"] += 1
                    return

                mins_until_pickup = (pickup_dt - now).total_seconds() / 60 if pickup_dt else None

                if mins_until_pickup is not None and mins_until_pickup <= _START_REMINDER_MINUTES:
                    if not driver_phone or not notify.normalize_phone(driver_phone):
                        if not notif.start_escalated_at:
                            _start_within_window = (
                                pickup_dt is None
                                or (pickup_dt - now).total_seconds() <= _START_ESC_WINDOW * 60
                            )
                            # MONITOR_START_OVERDUE_ONLY: only alert admin when trip
                            # is actually overdue (now > pickup + grace). Driver had no
                            # phone so we never sent them a warning — still alert admin
                            # but only once genuinely overdue to suppress false positives
                            # on ED drivers who don't tap "Start" in the app.
                            _start_admin_overdue_ok = (
                                not _START_OVERDUE_ONLY
                                or pickup_dt is None
                                or now > pickup_dt + timedelta(minutes=_START_OVERDUE_GRACE)
                            )
                            if _start_within_window and _start_admin_overdue_ok:
                                _nph_s_first = (person.full_name or "").split()[0] or "Driver"
                                notify.alert_admin(
                                    f"{person.full_name} accepted their {source_label} trip at "
                                    f"{trip['pickup_time']} but hasn't started. No phone on file.",
                                    spoken_message=(
                                        f"{_nph_s_first} accepted the "
                                        f"{_speak_time(trip['pickup_time'])} trip but hasn't started. "
                                        f"No phone on file — reach them directly."
                                    ),
                                )
                            notif.start_escalated_at = now
                            notif.last_escalated_at = now
                            summary["start_escalations"] += 1
                    else:
                        # Start SMS
                        if not notif.start_sms_at:
                            sms_text = get_sms_script(
                                driver_lang, "start",
                                driver_name=driver_name,
                                source=source_label,
                                pickup_time=_speak_time(trip["pickup_time"]),
                            )
                            notify.send_sms(driver_phone, sms_text)
                            notif.start_sms_at = now
                            summary["start_sms"] += 1

                        # Start call (10 min after SMS)
                        elif not notif.start_call_at and notif.start_sms_at:
                            if (now - notif.start_sms_at).total_seconds() >= _START_CALL_DELAY * 60:
                                call_text = get_call_script(
                                    driver_lang, "start",
                                    driver_name=driver_name,
                                    pickup_time=_speak_time(trip["pickup_time"]),
                                )
                                notify.make_call(driver_phone, call_text, language=driver_lang)
                                notif.start_call_at = now
                                summary["start_calls"] += 1

                        # Start escalation — immediate after call
                        elif not notif.start_escalated_at and notif.start_call_at:
                            if (now - notif.start_call_at).total_seconds() >= _START_ESCALATION_DELAY * 60:
                                mins_left = round((pickup_dt - now).total_seconds() / 60) if pickup_dt else "?"
                                route = trip.get("trip_ref", "?")
                                _start_within_window = (
                                    pickup_dt is None
                                    or (pickup_dt - now).total_seconds() <= _START_ESC_WINDOW * 60
                                )
                                # MONITOR_START_OVERDUE_ONLY: only escalate admin when
                                # the trip is genuinely overdue (now > pickup + grace).
                                # Prevents false alarms for ED drivers who rarely tap
                                # Start but are actually on the road. Driver-facing
                                # SMS/call fired regardless; only admin escalation is gated.
                                _start_admin_overdue_ok = (
                                    not _START_OVERDUE_ONLY
                                    or pickup_dt is None
                                    or now > pickup_dt + timedelta(minutes=_START_OVERDUE_GRACE)
                                )
                                if _start_within_window and _start_admin_overdue_ok:
                                    _stesc_first = (person.full_name or "").split()[0] or "Driver"
                                    notify.alert_admin(
                                        f"NOT STARTED — {person.full_name} | {source_label} | "
                                        f"Pickup: {trip['pickup_time']} ({mins_left} min away). "
                                        f"Accepted but hasn't started. SMS + call sent. You need to handle this.",
                                        spoken_message=(
                                            f"{_stesc_first} accepted the "
                                            f"{_speak_time(trip['pickup_time'])} trip but hasn't started. "
                                            f"Texted and called — no response."
                                        ),
                                    )
                                    try:
                                        from backend.services.notification_service import send_whatsapp_alert
                                        send_whatsapp_alert(
                                            f"⚠️ *NOT STARTED*\n"
                                            f"Driver: {person.full_name}\n"
                                            f"Route: {route} ({source_label})\n"
                                            f"Pickup: {trip['pickup_time']} — {mins_left} min away\n"
                                            f"Accepted but hasn't started. SMS + call sent. Handle now."
                                        )
                                    except Exception as _wa_err:
                                        logger.warning("WhatsApp start-escalation alert failed: %s", _wa_err)
                                notif.start_escalated_at = now
                                notif.last_escalated_at = now
                                summary["start_escalations"] += 1

        # ── Phase 2: Cross-source dedup ─────────────────────────────────────────
        # If the same driver has notifications from BOTH FA and ED for trips
        # within ±15 minutes of each other today, suppress the ED one and keep
        # the FA one (FA is the primary contract source). Log an auto_escalated event.
        # This prevents Malik from getting double-escalated for the same student.
        _dedup_window_minutes = 15
        _today_trips_by_person: dict = {}
        for _dt in all_trips:
            _dp = _dt.get("person")
            if _dp:
                _today_trips_by_person.setdefault(_dp.person_id, []).append(_dt)

        for _dpid, _dp_trips in _today_trips_by_person.items():
            _fa_p = [t for t in _dp_trips if t["source"] == "firstalt"]
            _ed_p = [t for t in _dp_trips if t["source"] == "everdriven"]
            if not _fa_p or not _ed_p:
                continue
            for _fa_t in _fa_p:
                for _ed_t in _ed_p:
                    _fa_pu = _parse_pickup_time(_fa_t["pickup_time"], today, tz)
                    _ed_pu = _parse_pickup_time(_ed_t["pickup_time"], today, tz)
                    if _fa_pu and _ed_pu:
                        _dedup_delta = abs((_fa_pu - _ed_pu).total_seconds() / 60)
                        if _dedup_delta <= _dedup_window_minutes:
                            _ed_notif = db.query(TripNotification).filter(
                                TripNotification.source == "everdriven",
                                TripNotification.trip_ref == _ed_t["trip_ref"],
                                TripNotification.trip_date == today,
                            ).first()
                            _fa_notif = db.query(TripNotification).filter(
                                TripNotification.source == "firstalt",
                                TripNotification.trip_ref == _fa_t["trip_ref"],
                                TripNotification.trip_date == today,
                            ).first()
                            if _ed_notif and not _ed_notif.dedup_suppressed:
                                _ed_notif.dedup_suppressed = True
                                if _fa_notif:
                                    _ed_notif.dedup_primary_notif_id = _fa_notif.id
                                _dedup_person_name = _ed_t["person"].full_name if _ed_t.get("person") else "?"
                                _dedup_ev = NotificationEvent(
                                    trip_notification_id=_ed_notif.id,
                                    event_type="auto_escalated",
                                    payload={
                                        "reason": "cross_source_dedup",
                                        "fa_trip_ref": _fa_t["trip_ref"],
                                        "ed_trip_ref": _ed_t["trip_ref"],
                                        "delta_minutes": round(_dedup_delta, 1),
                                        "canonical_notif_id": _fa_notif.id if _fa_notif else None,
                                    },
                                )
                                db.add(_dedup_ev)
                                db.flush()
                                logger.info(
                                    "[trip-monitor] DEDUP — ED trip %s suppressed (FA trip %s, delta=%.1f min, driver=%s)",
                                    _ed_t["trip_ref"], _fa_t["trip_ref"], _dedup_delta, _dedup_person_name,
                                )
                                summary.setdefault("dedup_suppressed", 0)
                                summary["dedup_suppressed"] += 1
        try:
            db.commit()
        except Exception as _dedup_commit_err:
            logger.warning("[trip-monitor] dedup commit failed: %s", _dedup_commit_err)
            db.rollback()

        # ── Phase 2: Stuck-trip re-escalation ───────────────────────────────────
        # After all normal per-trip processing: if a trip has been escalated
        # but still has no terminal state after _STUCK_TRIP_REESCALATE_MINUTES,
        # fire one more admin alert. Capped at _STUCK_TRIP_REESCALATE_MAX.
        def _count_reescalations(notif_id: int) -> int:
            return (
                db.query(NotificationEvent)
                .filter(
                    NotificationEvent.trip_notification_id == notif_id,
                    NotificationEvent.event_type == "reescalated",
                )
                .count()
            )

        # R1: per-trip transactions — blast radius is the failing trip only.
        for trip in trips_to_process:
            try:
                _process_one_trip(trip)
                db.commit()
            except Exception as trip_err:
                db.rollback()
                trip_label = f"{trip.get('source')}:{trip.get('trip_ref')}"
                logger.exception(
                    "[trip-monitor] Trip processing failed (%s): %s", trip_label, trip_err
                )
                summary["errors"].append(f"trip {trip_label}: {trip_err}")

        # ── Phase 2: Stuck-trip re-escalation pass ──────────────────────────────
        # Scan today's escalated-but-still-open notifications. If
        # last_escalated_at is more than _STUCK_TRIP_REESCALATE_MINUTES ago,
        # fire one admin alert (capped at _STUCK_TRIP_REESCALATE_MAX per trip).
        try:
            _stuck_notifs = (
                db.query(TripNotification, Person)
                .join(Person, Person.person_id == TripNotification.person_id)
                .filter(
                    TripNotification.trip_date == today,
                    TripNotification.last_escalated_at.isnot(None),
                    TripNotification.manually_resolved_at.is_(None),
                )
                .all()
            )
            for _stuck_notif, _stuck_person in _stuck_notifs:
                # Only stuck if still in an open bucket
                _stuck_bucket = next(
                    (
                        t["bucket"]
                        for t in all_trips
                        if t.get("trip_ref") == _stuck_notif.trip_ref
                        and t.get("source") == _stuck_notif.source
                    ),
                    None,
                )
                if _stuck_bucket not in ("unaccepted", "accepted"):
                    continue
                try:
                    _since_esc = (now - _stuck_notif.last_escalated_at).total_seconds() / 60
                except TypeError:
                    continue
                if _since_esc < _STUCK_TRIP_REESCALATE_MINUTES:
                    continue
                _reesc_count = _count_reescalations(_stuck_notif.id)
                if _reesc_count >= _STUCK_TRIP_REESCALATE_MAX:
                    continue
                _stuck_first = (_stuck_person.full_name or "").split()[0] or "Driver"
                _source_label = "FirstAlt" if _stuck_notif.source == "firstalt" else "EverDriven"
                _reesc_msg = (
                    f"[STUCK] {_stuck_person.full_name} | {_source_label} trip {_stuck_notif.trip_ref} | "
                    f"Pickup: {_stuck_notif.pickup_time} | "
                    f"Escalated {round(_since_esc)}min ago — still no progress. "
                    f"Re-escalation #{_reesc_count + 1}."
                )
                try:
                    notify.alert_admin(
                        _reesc_msg,
                        spoken_message=(
                            f"{_stuck_first} is stuck. Still no progress on the "
                            f"{_speak_time(_stuck_notif.pickup_time)} trip. Check now."
                        ),
                    )
                except Exception as _reesc_notify_err:
                    logger.warning("[trip-monitor] stuck-trip alert send failed: %s", _reesc_notify_err)

                _reesc_ev = NotificationEvent(
                    trip_notification_id=_stuck_notif.id,
                    event_type="stuck_trip_alert",
                    payload={
                        "reesc_count": _reesc_count + 1,
                        "since_last_esc_min": round(_since_esc),
                        "trip_ref": _stuck_notif.trip_ref,
                        "source": _stuck_notif.source,
                    },
                )
                db.add(_reesc_ev)
                _stuck_notif.last_escalated_at = now
                summary.setdefault("reescalations", 0)
                summary["reescalations"] += 1
            db.commit()
        except Exception as _stuck_err:
            logger.warning("[trip-monitor] stuck-trip pass failed: %s", _stuck_err)
            db.rollback()

        logger.info(
            "[trip-monitor] window=%s poll_interval=%ds | Checked %d trips | "
            "Declines:%d | NameMismatch:%d | Unknown:%d | "
            "Accept SMS:%d Call:%d Esc:%d | "
            "Start SMS:%d Call:%d Esc:%d | Errors:%d",
            window, _poll_interval,
            summary["trips_checked"],
            summary.get("declines", 0),
            summary.get("name_mismatches", 0),
            summary.get("unknown_status_alerts", 0),
            summary["accept_sms"], summary["accept_calls"], summary["accept_escalations"],
            summary["start_sms"], summary["start_calls"], summary["start_escalations"],
            len(summary["errors"]),
        )

    except Exception as e:
        logger.exception("[trip-monitor] Cycle failed: %s", e)
        summary["errors"].append(str(e))
        db.rollback()
    finally:
        # Always release the advisory lock before closing the session so
        # subsequent cycles can proceed. Swallow errors so a lock-release
        # failure never crashes the scheduler.
        try:
            db.execute(_sa_text("SELECT pg_advisory_unlock(hashtext('zpay_monitor_cycle'))"))
            db.commit()
        except Exception as _unlock_err:
            logger.debug("[trip-monitor] advisory unlock skipped: %s", _unlock_err)
        db.close()

    _last_run_info["last_run"] = now.isoformat()
    _last_run_info["summary"] = summary
    _last_run_info["error"] = summary["errors"][-1] if summary["errors"] else None
    # Also update window-specific shards so get_status() can expose them.
    if window == "hot":
        _last_run_info_hot["last_run"] = now.isoformat()
        _last_run_info_hot["summary"] = summary
        _last_run_info_hot["error"] = _last_run_info["error"]
    elif window == "cold":
        _last_run_info_cold["last_run"] = now.isoformat()
        _last_run_info_cold["summary"] = summary
        _last_run_info_cold["error"] = _last_run_info["error"]
    return summary


# ── Scheduler management ──────────────────────────────────────


def check_liveness() -> dict:
    """
    Check whether the scheduler has been running cycles recently.
    Fires a one-per-day alert to Malik if the monitor appears stale
    (no cycle in > 3x the configured interval) during operating hours.

    Returns a dict with keys: healthy (bool), last_run (str|None), stale_minutes (float|None).
    """
    tz = ZoneInfo(_TZ_NAME)
    now = datetime.now(tz)
    last_run_str = _last_run_info.get("last_run")

    result: dict = {"healthy": True, "last_run": last_run_str, "stale_minutes": None}

    # Only check during operating hours — silence outside them.
    in_hours = _START_HOUR <= now.hour < _END_HOUR
    if _scheduler is None or not in_hours or not last_run_str:
        return result

    try:
        last_run_dt = datetime.fromisoformat(last_run_str)
        if last_run_dt.tzinfo is None:
            last_run_dt = last_run_dt.replace(tzinfo=tz)
        # Adaptive: stale threshold = 3× the cold interval (worst expected gap).
        # Flat: stale threshold = 3× the configured flat interval.
        if _ADAPTIVE_CADENCE:
            stale_threshold = _COLD_INTERVAL_SECONDS * 3
        else:
            stale_threshold = _INTERVAL * 3 * 60  # seconds
        elapsed = (now - last_run_dt).total_seconds()
        if elapsed > stale_threshold:
            stale_minutes = round(elapsed / 60, 1)
            result["healthy"] = False
            result["stale_minutes"] = stale_minutes
            today_iso = now.date().isoformat()
            # R7: re-alert after _LIVENESS_REALERT_SECONDS so a recover-then-
            # die-again scenario isn't silent (was one-shot per day).
            prior_alert_at = _liveness_alerted.get(today_iso)
            should_alert = prior_alert_at is None
            if not should_alert:
                try:
                    since_last = (now - prior_alert_at).total_seconds()
                    should_alert = since_last >= _LIVENESS_REALERT_SECONDS
                except TypeError:
                    # tz mismatch — fall back to alerting (better noisy than silent)
                    should_alert = True
            if should_alert:
                _stale_msg = (
                    f"TRIP MONITOR STALE — no cycle in {stale_minutes} min "
                    f"(interval={_INTERVAL}m). Scheduler may be frozen. "
                    "Check Railway logs and restart if needed."
                )
                try:
                    from backend.services import notification_service as notify_real
                    notify_real.alert_admin(
                        _stale_msg,
                        spoken_message="Trip monitor stopped running cycles.",
                    )
                except Exception as _lv_err:
                    logger.error("[trip-monitor] Failed to send liveness alert: %s", _lv_err)
                # Phase 3: heartbeat/liveness notification → silent
                try:
                    from backend.services.ops_alert import route_dispatch_alert as _rda
                    _rda("silent", "Trip monitor stale", _stale_msg)
                except Exception as _lv_rda_err:
                    logger.warning("[trip-monitor] route_dispatch_alert (liveness) failed: %s", _lv_rda_err)
                _liveness_alerted[today_iso] = now
    except (ValueError, TypeError) as e:
        logger.warning("[trip-monitor] check_liveness: could not parse last_run: %s", e)

    return result


def _startup_self_test() -> list[str]:
    """
    Verify that every env var needed to alert Malik is set. Returns a list
    of missing-var error strings; empty list means ready to run.
    """
    required = ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER", "ADMIN_PHONE"]
    missing = [v for v in required if not os.environ.get(v, "").strip()]
    return missing


def start_monitor():
    """Start the background monitoring scheduler."""
    global _scheduler
    if _scheduler is not None:
        logger.warning("[trip-monitor] Scheduler already running")
        return

    # Hard gate: refuse to start blind. If we can't alert Malik, don't run —
    # a running monitor with no alert channel is worse than no monitor.
    # Skip in dry-run mode — no real notifications will be sent anyway.
    if not _DRY_RUN:
        missing = _startup_self_test()
        if missing:
            logger.error(
                "[trip-monitor] REFUSING TO START — missing required env vars: %s. "
                "Monitor disabled until these are set on Railway.",
                ", ".join(missing),
            )
            return
    else:
        logger.info("[trip-monitor] DRY RUN mode — skipping credential check, no SMS/calls will be sent")

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.cron import CronTrigger

    _common_job_kwargs = dict(
        replace_existing=True,
        max_instances=1,  # never overlap cycles
        coalesce=True,    # collapse missed runs into one
        misfire_grace_time=300,
    )

    def _make_safe_wrapper(fn, label: str):
        """Wrap a cycle function so a crash never kills the scheduler."""
        def _safe():
            try:
                fn()
            except Exception as e:
                logger.exception("[trip-monitor] Uncaught cycle error (%s): %s", label, e)
                _crash_msg = (
                    f"Monitor cycle ({label}) crashed: {str(e)[:120]}. "
                    "Check Railway logs."
                )
                try:
                    from backend.services import notification_service as _real
                    _real.alert_admin(
                        _crash_msg,
                        spoken_message="The monitor crashed. Check the Railway logs.",
                    )
                except Exception:
                    pass
                # Phase 3: cycle crash is a system log event → silent
                try:
                    from backend.services.ops_alert import route_dispatch_alert as _rda_c
                    _rda_c("silent", f"Monitor cycle crash ({label})", _crash_msg)
                except Exception:
                    pass
        _safe.__name__ = f"_safe_{label}"
        return _safe

    _scheduler = BackgroundScheduler(timezone=_TZ_NAME)

    if _ADAPTIVE_CADENCE:
        # ── Two-loop adaptive cadence ────────────────────────────────────
        # Hot loop: every _HOT_INTERVAL_SECONDS (default 60s) — trips within
        # _HOT_WINDOW_LEAD_MINUTES of pickup through completion.
        # Cold loop: every _COLD_INTERVAL_SECONDS (default 600s) — everything else.
        _scheduler.add_job(
            _make_safe_wrapper(run_hot_cycle, "hot"),
            trigger=IntervalTrigger(seconds=_HOT_INTERVAL_SECONDS, timezone=_TZ_NAME),
            id="trip_monitor_hot",
            name="Trip Monitor — Hot Window (60s)",
            **_common_job_kwargs,
        )
        _scheduler.add_job(
            _make_safe_wrapper(run_cold_cycle, "cold"),
            trigger=IntervalTrigger(seconds=_COLD_INTERVAL_SECONDS, timezone=_TZ_NAME),
            id="trip_monitor_cold",
            name="Trip Monitor — Cold Window (10min)",
            **_common_job_kwargs,
        )
        logger.info(
            "[trip-monitor] ADAPTIVE CADENCE ON — "
            "hot_interval=%ds (lead_window=%dmin, lookback=%dh) | "
            "cold_interval=%ds | "
            "start_hour=%d, end_hour=%d, tz=%s | "
            "reminder_window=%dmin, call_delay=%dmin, escalation_delay=%dmin | "
            "start_reminder=%dmin, start_call_delay=%dmin, start_escalation_delay=%dmin | "
            "accept_esc_window=%dmin, start_esc_window=%dmin | "
            "overdue_grace=%dmin, dry_run=%s",
            _HOT_INTERVAL_SECONDS, _HOT_WINDOW_LEAD_MINUTES, _HOT_WINDOW_LOOKBACK_HOURS,
            _COLD_INTERVAL_SECONDS,
            _START_HOUR, _END_HOUR, _TZ_NAME,
            _REMINDER_WINDOW, _CALL_DELAY, _ESCALATION_DELAY,
            _START_REMINDER_MINUTES, _START_CALL_DELAY, _START_ESCALATION_DELAY,
            _ACCEPT_ESC_WINDOW, _START_ESC_WINDOW,
            _OVERDUE_GRACE, _DRY_RUN,
        )
    else:
        # ── Flat interval fallback — pre-Phase-3 behaviour ───────────────
        # Exactly one job, same as before. poll_interval_seconds defaults to
        # _INTERVAL * 60 inside run_monitoring_cycle when None is passed.
        if 60 % _INTERVAL == 0:
            cron_minute = f"*/{_INTERVAL}"
        else:
            cron_minute = f"*/{_INTERVAL}"

        def _flat_cycle():
            run_monitoring_cycle(window="all", poll_interval_seconds=_INTERVAL * 60)

        _scheduler.add_job(
            _make_safe_wrapper(_flat_cycle, "flat"),
            trigger=CronTrigger(minute=cron_minute, timezone=_TZ_NAME),
            id="trip_monitor",
            name="Trip Acceptance & Start Monitor",
            **_common_job_kwargs,
        )
        logger.info(
            "[trip-monitor] ADAPTIVE CADENCE OFF — "
            "cycle_interval=%dmin, start_hour=%d, end_hour=%d, tz=%s, "
            "reminder_window=%dmin, call_delay=%dmin, escalation_delay=%dmin, "
            "start_reminder=%dmin, start_call_delay=%dmin, start_escalation_delay=%dmin, "
            "accept_esc_window=%dmin, start_esc_window=%dmin, "
            "overdue_grace=%dmin, dry_run=%s",
            _INTERVAL, _START_HOUR, _END_HOUR, _TZ_NAME,
            _REMINDER_WINDOW, _CALL_DELAY, _ESCALATION_DELAY,
            _START_REMINDER_MINUTES, _START_CALL_DELAY, _START_ESCALATION_DELAY,
            _ACCEPT_ESC_WINDOW, _START_ESC_WINDOW,
            _OVERDUE_GRACE, _DRY_RUN,
        )

    # WhatsApp delivery polling — every 5 min (lightweight Twilio API call)
    def _safe_wa_poll():
        try:
            from backend.services.whatsapp_poll import poll_whatsapp_delivery
            poll_whatsapp_delivery()
        except Exception as _wa_poll_err:
            logger.warning("[trip-monitor] WhatsApp poll job failed: %s", _wa_poll_err)

    _scheduler.add_job(
        _safe_wa_poll,
        trigger=CronTrigger(minute="*/5", timezone=_TZ_NAME),
        id="whatsapp_delivery_poll",
        name="WhatsApp Delivery Status Poll",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
    )

    # ── Weekly scorecard SMS + email cron — Phase 10 ─────────────────────────
    # Fires Sunday at 20:00 PT (America/Los_Angeles).
    # Gated by SCORECARD_CRON_ENABLED=1 — no-op if env var not set.
    def _safe_scorecard_cron():
        try:
            from backend.services.scorecard_cron import run_scorecard_cron
            result = run_scorecard_cron()
            logger.info(
                "[trip-monitor] scorecard cron complete: sent=%d skipped=%d errors=%d",
                result.get("sent", 0),
                result.get("skipped", 0),
                result.get("errors", 0),
            )
        except Exception as _sc_err:
            logger.exception("[trip-monitor] scorecard cron crashed: %s", _sc_err)

    _scheduler.add_job(
        _safe_scorecard_cron,
        trigger=CronTrigger(day_of_week="sun", hour=20, minute=0, timezone=_TZ_NAME),
        id="scorecard_weekly_send",
        name="Weekly Scorecard SMS + Email",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    logger.info("[trip-monitor] Scorecard weekly cron registered (Sun 20:00 PT)")

    # ── Hourly DB backup + daily CSV export ─────────────────────────────────
    # Gated by BACKUP_CRON_ENABLED=1. No-op if env var is "0".
    try:
        from backend.services.backup_service import register_backup_jobs
        register_backup_jobs(_scheduler)
    except Exception as _bk_err:
        logger.warning("[trip-monitor] Backup jobs failed to register: %s", _bk_err)

    _scheduler.start()


def stop_monitor():
    """Shut down the background scheduler gracefully."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("[trip-monitor] Scheduler stopped")


def get_status() -> dict:
    """Return current monitor status for the dashboard."""
    base = {
        "enabled": _scheduler is not None,
        "last_run": _last_run_info.get("last_run"),
        "summary": _last_run_info.get("summary"),
        "error": _last_run_info.get("error"),
        "interval_minutes": _INTERVAL,
        "operating_hours": f"{_START_HOUR}:00 - {_END_HOUR}:00 {_TZ_NAME}",
        "adaptive_cadence": _ADAPTIVE_CADENCE,
    }
    if _ADAPTIVE_CADENCE:
        base["hot_interval_seconds"] = _HOT_INTERVAL_SECONDS
        base["cold_interval_seconds"] = _COLD_INTERVAL_SECONDS
        base["hot_window_lead_minutes"] = _HOT_WINDOW_LEAD_MINUTES
        base["hot_window_lookback_hours"] = _HOT_WINDOW_LOOKBACK_HOURS
        base["last_run_hot"] = _last_run_info_hot.get("last_run")
        base["last_run_cold"] = _last_run_info_cold.get("last_run")
    return base
