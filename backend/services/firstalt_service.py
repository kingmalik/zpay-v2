"""
FirstAlt API service — authenticates via AWS Cognito and fetches
driver schedules from the spguardian.firstalt.com portal.
"""
import os
import json
import urllib.request
from datetime import date, datetime
from functools import lru_cache

_token_cache: dict = {}


def _get_token() -> str:
    """Return a valid Cognito ID token, re-authenticating if needed."""
    cached = _token_cache.get("token")
    exp = _token_cache.get("exp", 0)
    if cached and datetime.utcnow().timestamp() < exp - 60:
        return cached

    from pycognito import Cognito
    username = os.environ["FIRSTALT_USERNAME"]
    password = os.environ["FIRSTALT_PASSWORD"]
    pool_id  = os.environ.get("FIRSTALT_USER_POOL_ID", "us-east-1_0nRyLEyFg")
    client_id = os.environ.get("FIRSTALT_CLIENT_ID", "2do0la8ak2bj6kb1nqm0ipe5tu")

    u = Cognito(pool_id, client_id, username=username)
    u.authenticate(password=password)

    import base64
    raw = u.id_token.split(".")[1]
    padded = raw + "=" * (-len(raw) % 4)
    claims = json.loads(base64.b64decode(padded).decode())

    _token_cache["token"] = u.id_token
    _token_cache["exp"] = claims.get("exp", 0)
    return u.id_token


def _api(path: str, method: str = "GET", body: dict | None = None) -> dict | list:
    token = _get_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    base_onboard = "https://api.firstalt.com/api/onboarding"
    base_trips   = "https://api.firstalt.com/api/trip-scheduler-service"

    # Route to correct base
    if path.startswith("/v1/transportation") or path.startswith("/v1/partner"):
        url = base_trips + path
    else:
        url = base_onboard + path

    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def get_trips(for_date: date | None = None) -> list[dict]:
    """Fetch all trips for the given date (defaults to today)."""
    state = os.environ.get("FIRSTALT_STATE_CODE", "WA")
    d = (for_date or date.today()).isoformat()
    result = _api(
        "/v1/transportation-partner-trips",
        method="POST",
        body={"servicingStateCode": state, "date": d, "page": 0, "size": 500},
    )
    return result.get("trips", [])


def get_driver_profile(firstalt_driver_id: int) -> dict:
    """Fetch a single driver's full profile from FirstAlt."""
    return _api(f"/v1/drivers/{firstalt_driver_id}")


def get_all_drivers() -> list[dict]:
    """
    Return a deduplicated list of driver dicts for all drivers seen across a
    rolling window of trip data (past 7 days + today + next 7 days).

    FirstAlt has no native /v1/drivers list endpoint — the only way to
    enumerate drivers is via trips.  Each returned dict contains:
        driverId     (int)
        driverName   (str)  — "First Last"
        firstName    (str)
        middleName   (str)
        lastName     (str)

    Raises RuntimeError if no trips can be fetched at all.
    """
    from datetime import timedelta

    today = date.today()
    dates_to_fetch = [today + timedelta(days=offset) for offset in range(-7, 8)]

    seen: dict[int, dict] = {}
    errors: list[str] = []

    for d in dates_to_fetch:
        try:
            trips = get_trips(d)
        except Exception as e:
            errors.append(f"{d}: {e}")
            continue

        for t in trips:
            driver_id = t.get("driverId")
            if driver_id is None or driver_id in seen:
                continue
            first  = (t.get("driverFirstName") or "").strip()
            middle = (t.get("driverMiddleName") or "").strip()
            last   = (t.get("driverLastName")  or "").strip()
            full   = " ".join(part for part in [first, last] if part)
            if not full:
                continue
            seen[driver_id] = {
                "driverId":   driver_id,
                "driverName": full,
                "firstName":  first,
                "middleName": middle,
                "lastName":   last,
            }

    if not seen and errors:
        raise RuntimeError(
            f"FirstAlt get_all_drivers: all {len(errors)} date fetches failed. "
            f"First error: {errors[0]}"
        )

    return list(seen.values())


def get_dashboard(for_date: date | None = None) -> dict:
    """Fetch the SP dashboard counts for today."""
    state = os.environ.get("FIRSTALT_STATE_CODE", "WA")
    d = (for_date or date.today()).isoformat()
    return _api(f"/v1/transportation-partner-dashboard?date={d}&stateCode={state}")


def accept_trip(trip_id: int | str) -> dict:
    """Accept a single trip by ID. Returns the API response."""
    return _api(
        f"/v1/transportation-partner-trips/{trip_id}/accept",
        method="PUT",
        body={},
    )


def accept_all_trips(for_date: date | None = None) -> dict:
    """
    Fetch all open trips for the given date and accept each one.
    Returns a summary: {accepted: [...], failed: [...], already_accepted: [...]}
    """
    trips = get_trips(for_date)
    accepted = []
    failed = []
    skipped = []

    for trip in trips:
        trip_id = trip.get("tripId") or trip.get("id")
        if not trip_id:
            continue

        # Skip trips already in a terminal/accepted state
        status = (trip.get("tripStatus") or trip.get("status") or "").upper()
        if any(s in status for s in ("ACCEPT", "COMPLET", "CANCEL", "CLOSE")):
            skipped.append({"tripId": trip_id, "status": status})
            continue

        try:
            result = accept_trip(trip_id)
            accepted.append({"tripId": trip_id, "response": result})
        except Exception as e:
            failed.append({"tripId": trip_id, "error": str(e)})

    return {
        "accepted": accepted,
        "failed": failed,
        "already_accepted": skipped,
        "total_trips": len(trips),
    }
