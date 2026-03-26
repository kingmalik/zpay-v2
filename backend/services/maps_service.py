"""
Google Maps Distance Matrix service + driver scoring logic for dispatch assignment.

Scoring tiers (lower number = better):
  1 — Best Fit:    last run ends ≤45 min before pickup, last dropoff ≤20 min drive away
  2 — Good Fit:    no conflict, home ≤20 min drive to pickup
  3 — Available:   no rides today, home ≤30 min drive to pickup
  4 — Last Resort: no rides today, home >30 min drive (only option)
  5 — Conflict:    existing ride overlaps the requested time window
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import date, datetime
from typing import Optional

# ---------------------------------------------------------------------------
# In-process geocoding / travel-time cache
# ---------------------------------------------------------------------------
_geo_cache: dict[str, dict] = {}   # origin|destination -> {duration_seconds, distance_meters}


def _maps_api_key() -> str:
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not key:
        raise RuntimeError("GOOGLE_MAPS_API_KEY env var is not set")
    return key


def get_drive_minutes(origin: str, destination: str) -> Optional[float]:
    """
    Return driving time in minutes between origin and destination using the
    Distance Matrix API.  Returns None if either address is empty or the API
    call fails.  Results are cached in-process.
    """
    if not origin or not destination:
        return None

    cache_key = f"{origin.strip().lower()}|{destination.strip().lower()}"
    if cache_key in _geo_cache:
        return _geo_cache[cache_key]

    try:
        params = urllib.parse.urlencode({
            "origins":      origin,
            "destinations": destination,
            "mode":         "driving",
            "key":          _maps_api_key(),
        })
        url = f"https://maps.googleapis.com/maps/api/distancematrix/json?{params}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        element = data["rows"][0]["elements"][0]
        if element.get("status") != "OK":
            _geo_cache[cache_key] = None
            return None

        minutes = element["duration"]["value"] / 60.0
        _geo_cache[cache_key] = minutes
        return minutes
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def _parse_hhmm(t: str) -> Optional[int]:
    """Parse a 'HH:MM' or 'H:MM AM/PM' string to minutes-since-midnight."""
    if not t:
        return None
    t = t.strip()
    try:
        # Try 24-hour first
        parts = t.split(":")
        if len(parts) >= 2:
            h, m = int(parts[0]), int(parts[1][:2])
            return h * 60 + m
    except ValueError:
        pass
    # Try AM/PM
    for fmt in ("%I:%M %p", "%I:%M%p", "%I:%M:%S %p"):
        try:
            dt = datetime.strptime(t.upper(), fmt)
            return dt.hour * 60 + dt.minute
        except ValueError:
            continue
    return None


def _times_overlap(start_a: int, end_a: int, start_b: int, end_b: int, buffer: int = 10) -> bool:
    """Return True if two time windows overlap (with a buffer in minutes)."""
    return not (end_a + buffer <= start_b or end_b + buffer <= start_a)


# ---------------------------------------------------------------------------
# Public scoring function
# ---------------------------------------------------------------------------

TIER_LABELS = {
    1: "Best Fit",
    2: "Good Fit",
    3: "Available",
    4: "Last Resort",
    5: "Conflict",
}

TIER_COLORS = {
    1: ("#34d399", "rgba(52,211,153,0.15)", "rgba(52,211,153,0.35)"),   # green
    2: ("#93c5fd", "rgba(59,130,246,0.15)", "rgba(59,130,246,0.35)"),   # blue
    3: ("#fbbf24", "rgba(251,191,36,0.12)", "rgba(251,191,36,0.35)"),   # yellow
    4: ("#fb923c", "rgba(251,146,60,0.12)", "rgba(251,146,60,0.35)"),   # orange
    5: ("#f87171", "rgba(248,113,113,0.10)", "rgba(248,113,113,0.30)"), # red
}


def score_drivers(
    drivers: list[dict],
    pickup_address: str,
    pickup_time_str: str,
    dropoff_time_str: str,
) -> list[dict]:
    """
    Score and rank a list of driver dicts (same shape as dispatch page).

    Each driver dict must have:
      - person_id, name, phone, address (home_address), trips (list of trip dicts)
      - Each trip dict: firstPickUp (str HH:MM), lastDropOff (str HH:MM),
        lastDropoffAddress (str, optional), tripStatus (str)

    Returns a sorted list of result dicts:
      {
        person_id, name, phone, address, sources,
        tier (1-5), tier_label, reason,
        color_text, color_bg, color_border,
        drive_from_home_minutes,
        last_dropoff_address, drive_from_last_dropoff_minutes,
      }
    """
    pickup_min  = _parse_hhmm(pickup_time_str)
    dropoff_min = _parse_hhmm(dropoff_time_str)

    results = []

    for d in drivers:
        trips = [
            t for t in (d.get("trips") or [])
            if not any(
                kw in (t.get("tripStatus") or "")
                for kw in ("CANCELLED", "Declined")
            )
        ]

        home_addr = (d.get("address") or "").strip()

        # Drive time from home to pickup
        home_drive = get_drive_minutes(home_addr, pickup_address) if home_addr else None

        # Find last trip ending before pickup_min (non-cancelled)
        last_trip = None
        last_end_min = None
        for t in sorted(trips, key=lambda x: _parse_hhmm(x.get("lastDropOff") or "") or 0, reverse=True):
            end = _parse_hhmm(t.get("lastDropOff") or "")
            if end is not None and pickup_min is not None and end <= pickup_min:
                last_trip = t
                last_end_min = end
                break

        # Drive from last dropoff to pickup
        last_dropoff_addr = None
        last_dropoff_drive = None
        if last_trip:
            last_dropoff_addr = (
                last_trip.get("lastDropoffAddress")
                or last_trip.get("dropoffAddress")
                or last_trip.get("dropOff")
                or ""
            ).strip()
            if last_dropoff_addr:
                last_dropoff_drive = get_drive_minutes(last_dropoff_addr, pickup_address)

        # Check for schedule conflicts
        has_conflict = False
        if pickup_min is not None and dropoff_min is not None:
            for t in trips:
                t_start = _parse_hhmm(t.get("firstPickUp") or "")
                t_end   = _parse_hhmm(t.get("lastDropOff") or "")
                if t_start is not None and t_end is not None:
                    if _times_overlap(t_start, t_end, pickup_min, dropoff_min):
                        has_conflict = True
                        break

        # --- Compute tier ---
        tier: int
        reason: str

        if has_conflict:
            tier = 5
            reason = "Has a ride that overlaps this time window — scheduling conflict."

        elif (
            last_trip is not None
            and last_end_min is not None
            and pickup_min is not None
            and (pickup_min - last_end_min) <= 45
            and last_dropoff_drive is not None
            and last_dropoff_drive <= 20
        ):
            gap_min = pickup_min - last_end_min
            tier = 1
            reason = (
                f"Last run ends {gap_min} min before pickup and last dropoff is "
                f"{last_dropoff_drive:.0f} min away — perfect handoff."
            )

        elif not trips and home_drive is not None and home_drive <= 20:
            tier = 2
            reason = f"No rides today and lives {home_drive:.0f} min from the pickup — easy assignment."

        elif not trips and home_drive is not None and home_drive <= 30:
            tier = 3
            reason = f"No rides today, {home_drive:.0f} min from pickup — good availability."

        elif not trips:
            drive_desc = f"{home_drive:.0f} min away" if home_drive is not None else "distance unknown"
            tier = 4
            reason = f"No rides today but {drive_desc} from pickup — last resort."

        else:
            # Has trips but no conflict and last trip doesn't qualify for tier 1
            if home_drive is not None and home_drive <= 20:
                tier = 2
                reason = (
                    f"Has {len(trips)} ride(s) today with no conflict. "
                    f"Lives {home_drive:.0f} min from pickup — good fit."
                )
            elif home_drive is not None and home_drive <= 30:
                tier = 3
                reason = (
                    f"Has {len(trips)} ride(s) today with no conflict. "
                    f"Lives {home_drive:.0f} min from pickup — available."
                )
            else:
                drive_desc = f"{home_drive:.0f} min away" if home_drive is not None else "distance unknown"
                tier = 4
                reason = (
                    f"Has {len(trips)} ride(s) today with no conflict, but {drive_desc} from pickup."
                )

        colors = TIER_COLORS.get(tier, TIER_COLORS[4])
        results.append({
            "person_id":                  d["person_id"],
            "name":                       d["name"],
            "phone":                      d.get("phone") or "",
            "address":                    home_addr,
            "sources":                    d.get("sources") or [],
            "tier":                       tier,
            "tier_label":                 TIER_LABELS[tier],
            "reason":                     reason,
            "color_text":                 colors[0],
            "color_bg":                   colors[1],
            "color_border":               colors[2],
            "drive_from_home_minutes":    round(home_drive, 1) if home_drive is not None else None,
            "last_dropoff_address":       last_dropoff_addr or "",
            "drive_from_last_dropoff_minutes": round(last_dropoff_drive, 1) if last_dropoff_drive is not None else None,
            "trip_count":                 len(trips),
        })

    # Sort: tier asc, then drive_from_home asc within tier
    results.sort(key=lambda r: (
        r["tier"],
        r["drive_from_home_minutes"] if r["drive_from_home_minutes"] is not None else 9999,
    ))
    return results
