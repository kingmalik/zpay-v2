"""
EverDriven (ALC) API service — authenticates via Azure B2C and fetches
driver runs from the sp-api.everdriven.com GraphQL API.

Auth notes:
  - ROPC is NOT supported by this tenant.
  - Initial auth uses a Playwright headless browser with PKCE.
  - Subsequent calls use the cached refresh_token to get new access tokens.
  - Token cache is persisted to /data/out/.everdriven_token.json so it
    survives container restarts.
"""
import base64
import hashlib
import json
import os
import secrets
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_TENANT      = "alcproviderportal"
_DOMAIN      = "alcproviderportal.b2clogin.com"
_POLICY      = "B2C_1_SignIn"
_CLIENT_ID   = "63cca938-16e4-4d66-8860-e2395b3e8a11"
_SCOPE       = "https://alcproviderportal.onmicrosoft.com/providerportal/user_impersonation"
_TOKEN_URL   = f"https://{_DOMAIN}/{_TENANT}.onmicrosoft.com/{_POLICY}/oauth2/v2.0/token"
_AUTH_URL    = f"https://{_DOMAIN}/{_TENANT}.onmicrosoft.com/{_POLICY}/oauth2/v2.0/authorize"
_API_URL     = "https://sp-api.everdriven.com/api/Graphql"
_CACHE_FILE  = Path("/data/out/.everdriven_token.json")

_RUN_STATES_CANCELLED = {"Declined"}
_RUN_STATES_ACTIVE    = {"Active", "AtStop"}
_RUN_STATES_COMPLETED = {"Completed"}


class EverDrivenAuthError(Exception):
    pass


# ---------------------------------------------------------------------------
# Token cache — file + DB for persistence across container restarts
# ---------------------------------------------------------------------------

_DB_CONFIG_KEY = "everdriven_token"


def _load_cache_from_db() -> dict:
    try:
        from backend.db import SessionLocal
        from backend.db.models import AppConfig
        db = SessionLocal()
        try:
            row = db.query(AppConfig).filter(AppConfig.key == _DB_CONFIG_KEY).first()
            if row:
                return json.loads(row.value)
        finally:
            db.close()
    except Exception:
        pass
    return {}


def _save_cache_to_db(data: dict):
    try:
        from backend.db import SessionLocal
        from backend.db.models import AppConfig
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        db = SessionLocal()
        try:
            stmt = pg_insert(AppConfig).values(
                key=_DB_CONFIG_KEY,
                value=json.dumps(data),
            ).on_conflict_do_update(
                index_elements=["key"],
                set_={"value": json.dumps(data), "updated_at": sa_now()},
            )
            db.execute(stmt)
            db.commit()
        finally:
            db.close()
    except Exception:
        pass


def sa_now():
    from sqlalchemy import text
    return text("NOW()")


def _load_cache() -> dict:
    # File first (fastest), fall back to DB (survives redeploys)
    try:
        if _CACHE_FILE.exists():
            data = json.loads(_CACHE_FILE.read_text())
            if data:
                return data
    except Exception:
        pass
    return _load_cache_from_db()


def _save_cache(data: dict):
    # Write to both — file for speed, DB for durability
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(data))
    except Exception:
        pass
    _save_cache_to_db(data)


_token_cache: dict = {}   # in-process mirror


def _cache() -> dict:
    global _token_cache
    if not _token_cache:
        _token_cache = _load_cache()
    return _token_cache


def _update_cache(data: dict):
    global _token_cache
    _token_cache.update(data)
    _save_cache(_token_cache)


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def _decode_jwt_claims(token: str) -> dict:
    payload = token.split(".")[1]
    padded  = payload + "=" * (-len(payload) % 4)
    return json.loads(base64.b64decode(padded).decode())


# ---------------------------------------------------------------------------
# Token acquisition
# ---------------------------------------------------------------------------

def _get_token() -> str:
    """
    Return a valid access token.

    Priority:
      1. Cached access token still fresh → return immediately
      2. Refresh token present → exchange for new tokens
      3. Refresh failed or absent → auto-login with EVERDRIVEN_USERNAME/PASSWORD env vars
      4. No credentials → raise EverDrivenAuthError
    """
    cache = _cache()
    access_token  = cache.get("access_token")
    expires_at    = cache.get("expires_at", 0)
    refresh_token = cache.get("refresh_token")

    if access_token and datetime.utcnow().timestamp() < expires_at - 60:
        return access_token

    if refresh_token:
        try:
            tokens = _refresh_tokens(refresh_token)
            _update_cache(tokens)
            return tokens["access_token"]
        except Exception:
            # Refresh token expired — clear stale credentials and fall through
            _update_cache({"refresh_token": None, "access_token": None, "expires_at": 0})

    # Auto-login from env vars (self-healing — no human needed)
    username = os.environ.get("EVERDRIVEN_USERNAME")
    password = os.environ.get("EVERDRIVEN_PASSWORD")
    if username and password:
        try:
            tokens = _login_via_playwright(username, password)
            return tokens["access_token"]
        except Exception as exc:
            raise EverDrivenAuthError(
                f"EverDriven auto-login failed: {exc}"
            ) from exc

    raise EverDrivenAuthError(
        "No valid EverDriven token and no EVERDRIVEN_USERNAME/PASSWORD env vars set."
    )


def _refresh_tokens(refresh_token: str) -> dict:
    """Exchange a refresh token for a new access + refresh token pair."""
    body = urllib.parse.urlencode({
        "grant_type":    "refresh_token",
        "client_id":     _CLIENT_ID,
        "refresh_token": refresh_token,
        "scope":         f"openid offline_access {_SCOPE}",
    }).encode()

    req = urllib.request.Request(
        _TOKEN_URL, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode())

    claims = _decode_jwt_claims(data["access_token"])
    return {
        "access_token":   data["access_token"],
        "refresh_token":  data.get("refresh_token", refresh_token),
        "expires_at":     claims.get("exp", 0),
        "provider_code":  claims.get("extension_ProviderCode", ""),
    }


def _login_via_playwright(username: str, password: str) -> dict:
    """
    Perform a headless PKCE login via Playwright.

    Returns a dict with keys:
        access_token, refresh_token, expires_at, provider_code
    """
    from playwright.sync_api import sync_playwright

    # PKCE setup
    code_verifier  = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b"=").decode()

    state        = secrets.token_urlsafe(16)
    redirect_uri = "https://sp.everdriven.com/"  # registered redirect URI for this B2C app

    params = urllib.parse.urlencode({
        "response_type":         "code",
        "client_id":             _CLIENT_ID,
        "redirect_uri":          redirect_uri,
        "scope":                 f"openid offline_access {_SCOPE}",
        "state":                 state,
        "code_challenge":        code_challenge,
        "code_challenge_method": "S256",
        "prompt":                "login",
    })
    authorize_url = f"{_AUTH_URL}?{params}"

    auth_code = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page    = context.new_page()

        # Intercept ALL requests — the SPA consumes ?code= immediately on redirect
        # so we must catch it in-flight before the React app strips it from the URL
        def _on_request(request):
            nonlocal auth_code
            url = request.url
            if redirect_uri in url and "code=" in url:
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
                if "code" in qs and not auth_code:
                    auth_code = qs["code"][0]

        context.on("request", _on_request)

        page.goto(authorize_url, timeout=30_000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)

        # keyboard.insert_text is the only method that sticks on this B2C page
        page.wait_for_selector("#email", timeout=30_000)
        page.locator("#email").click()
        page.keyboard.insert_text(username)

        page.wait_for_selector("#password", timeout=30_000)
        page.locator("#password").click()
        page.keyboard.insert_text(password)

        # Submit — confirmed: id="next" with text "Sign in"
        page.wait_for_selector("#next", timeout=10_000)
        page.click("#next")

        # Give the SPA time to make the redirect request
        page.wait_for_timeout(15_000)

        browser.close()

    if not auth_code:
        raise EverDrivenAuthError(
            "Playwright login did not capture an authorization code. "
            "Check credentials or the B2C login page structure."
        )

    # Exchange code for tokens
    body = urllib.parse.urlencode({
        "grant_type":    "authorization_code",
        "client_id":     _CLIENT_ID,
        "code":          auth_code,
        "redirect_uri":  redirect_uri,
        "code_verifier": code_verifier,
        "scope":         f"openid offline_access {_SCOPE}",
    }).encode()

    req = urllib.request.Request(
        _TOKEN_URL, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode())

    claims       = _decode_jwt_claims(data["access_token"])
    provider_code = claims.get("extension_ProviderCode", "")

    result = {
        "access_token":   data["access_token"],
        "refresh_token":  data.get("refresh_token", ""),
        "expires_at":     claims.get("exp", 0),
        "provider_code":  provider_code,
    }
    _update_cache(result)
    return result


# ---------------------------------------------------------------------------
# GraphQL helper
# ---------------------------------------------------------------------------

def _api(query: str, variables: dict | None = None) -> dict:
    token = _get_token()
    payload = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        _API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def _provider_code() -> str:
    return _cache().get("provider_code") or ""


# ---------------------------------------------------------------------------
# Normalised run shape (mirrors FirstAlt trip shape for easy merging)
# ---------------------------------------------------------------------------

def _normalise_run(run: dict) -> dict:
    """
    Flatten an EverDriven runsV2 result into the same shape used by
    dispatch.py for FirstAlt trips so both sources can be displayed /
    compared side-by-side.

    FirstAlt keys used by dispatch.html:
        name, firstPickUp, lastDropOff, tripStatus, students, driverId
    """
    payload      = run.get("payload") or {}
    driver_info  = payload.get("driverInfo") or {}
    fp           = run.get("firstPickup") or {}
    ld           = run.get("lastDropoff") or {}
    passenger_count = run.get("passengers") or 0  # Int field, not a list

    # Time strings — prefer local time (TLT), fall back to UTC
    pickup_time  = fp.get("dueTimeTLT") or (fp.get("dueDateTimeUTC") or "")[:16]
    dropoff_time = ld.get("dueTimeTLT") or (ld.get("dueDateTimeUTC") or "")[:16]

    run_state  = payload.get("runState") or ""
    route_name = payload.get("routeName") or run.get("keyValue") or ""

    return {
        # Shared dispatch shape
        "name":         route_name,
        "firstPickUp":  pickup_time,
        "lastDropOff":  dropoff_time,
        "tripStatus":   run_state,
        "students":     [{"name": f"Passenger {i+1}"} for i in range(passenger_count)],
        "driverId":     driver_info.get("driverCode"),  # EverDriven uses driverCode as ID

        # EverDriven-specific extras
        "keyValue":     run.get("keyValue"),
        "miles":        payload.get("miles"),
        "stops":        run.get("stops"),
        "driverGUID":   payload.get("driverGUID"),
        "driverName":   driver_info.get("driverName"),
        "vehicleMake":  driver_info.get("vehicleMake"),
        "vehicleModel": driver_info.get("vehicleModel"),
        "pickupAddress":  (fp.get("location") or {}).get("address1"),
        "dropoffAddress": (ld.get("location") or {}).get("address1"),
        "source":       "everdriven",
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_RUNS_QUERY = """
query GetRuns($mrmProvider: ID!, $providerId: ID!, $startDate: DateTime!, $endDate: DateTime!) {
  provider(mrmProvider: $mrmProvider, providerId: $providerId) {
    runsV2(
      startDate: $startDate
      endDate: $endDate
      bypassPagination: true
      maxItemCount: 500
    ) {
      totalItemCount
      results {
        keyValue
        stops
        passengers
        firstPickup { dueTimeTLT dueDateTimeUTC location { address1 } }
        lastDropoff { dueTimeTLT dueDateTimeUTC location { address1 } }
        payload {
          driverGUID
          routeName
          miles
          runState
          driverInfo {
            driverCode
            driverName
            vehicleMake
            vehicleModel
          }
        }
      }
    }
  }
}
"""


def get_runs(for_date: date | None = None) -> list[dict]:
    """Fetch all runs for the given date (defaults to today), normalised."""
    d = (for_date or date.today()).isoformat()
    # EverDriven expects DateTime, not bare date
    start_dt = f"{d}T00:00:00"
    end_dt   = f"{d}T23:59:59"
    pc = _provider_code()
    data = _api(_RUNS_QUERY, {
        "mrmProvider": pc,
        "providerId":  pc,
        "startDate":   start_dt,
        "endDate":     end_dt,
    })
    results = (
        (data.get("data") or {})
            .get("provider", {})
            .get("runsV2", {})
            .get("results", [])
    ) or []
    if data.get("errors"):
        print(f"[everdriven] get_runs errors: {data['errors']}")
    return [_normalise_run(r) for r in results]


_DRIVERS_QUERY = """
query GetDrivers($mrmProvider: ID!) {
  drivers(mrmProvider: $mrmProvider, bypassPagination: true) {
    totalItemCount
    results {
      keyValue
      payload {
        driverCode
        firstName
        lastName
        providerGUID
        picURL
        vehicleInfo {
          make
          model
          color
          licensePlate
        }
        eligibleFlag
        deleteFlag
      }
    }
  }
}
"""

_DRIVERS_QUERY_FALLBACKS: list[str] = []  # schema confirmed above, no fallbacks needed


def _extract_driver_results(data: dict) -> list[dict] | None:
    """
    Try to pull a results list from a GraphQL drivers response.
    Handles both top-level `drivers` query and legacy `provider.drivers` shape.
    Returns None if the response contains GraphQL errors or no recognisable shape.
    """
    if data.get("errors"):
        return None
    root = data.get("data") or {}
    # Primary: top-level drivers query
    if "drivers" in root:
        return (root["drivers"] or {}).get("results") or []
    # Legacy: nested under provider
    provider = root.get("provider") or {}
    for key in ("drivers", "driversList", "allDrivers"):
        node = provider.get(key)
        if node is not None:
            return node.get("results") or []
    return None


def _normalise_driver(raw: dict) -> dict:
    """
    Flatten a raw driver result into a consistent dict.
    OutputDriverPayloadType fields: driverCode, firstName, lastName,
    providerGUID, picURL, vehicleInfo{make,model,color,licensePlate},
    eligibleFlag, deleteFlag
    """
    payload      = raw.get("payload") or {}
    vehicle_info = payload.get("vehicleInfo") or {}
    first  = payload.get("firstName") or ""
    last   = payload.get("lastName")  or ""
    name   = f"{first} {last}".strip() or payload.get("driverCode") or ""
    return {
        "keyValue":      raw.get("keyValue"),
        "driverCode":    payload.get("driverCode"),
        "driverName":    name,
        "firstName":     first,
        "lastName":      last,
        "providerGUID":  payload.get("providerGUID"),
        "picURL":        payload.get("picURL"),
        "vehicleMake":   vehicle_info.get("make"),
        "vehicleModel":  vehicle_info.get("model"),
        "vehicleColor":  vehicle_info.get("color"),
        "licensePlate":  vehicle_info.get("licensePlate"),
        "eligibleFlag":  payload.get("eligibleFlag"),
        "deleteFlag":    payload.get("deleteFlag"),
    }


def get_all_drivers() -> list[dict]:
    """
    Fetch the full driver list from EverDriven.

    Tries the primary GraphQL query first, then falls back through alternative
    field-name shapes if the API returns errors or an unrecognised structure.

    Returns a list of normalised driver dicts with keys:
        keyValue, driverCode, driverName, driverGUID,
        cellphone, email, picURL, vehicleMake, vehicleModel
    """
    provider_code = _provider_code()
    variables = {"mrmProvider": provider_code}

    # Try primary query first
    data = _api(_DRIVERS_QUERY, variables)
    results = _extract_driver_results(data)

    if results is None:
        # Log the error for inspection and try fallbacks
        print(f"[everdriven] Primary drivers query failed: {data.get('errors')}")
        for i, fallback_query in enumerate(_DRIVERS_QUERY_FALLBACKS):
            print(f"[everdriven] Trying fallback query #{i + 1}")
            data = _api(fallback_query, variables)
            results = _extract_driver_results(data)
            if results is not None:
                print(f"[everdriven] Fallback #{i + 1} succeeded with {len(results)} drivers")
                break
            print(f"[everdriven] Fallback #{i + 1} failed: {data.get('errors')}")

    if results is None:
        raise Exception(
            f"All EverDriven driver queries failed. Last response errors: {data.get('errors')}"
        )

    return [_normalise_driver(r) for r in results]


def get_dashboard(for_date: date | None = None) -> dict:
    """Return run counts for the given date."""
    runs = get_runs(for_date)
    total     = len(runs)
    completed = sum(1 for r in runs if r["tripStatus"] in _RUN_STATES_COMPLETED)
    active    = sum(1 for r in runs if r["tripStatus"] in _RUN_STATES_ACTIVE)
    scheduled = sum(1 for r in runs if r["tripStatus"] not in
                    (_RUN_STATES_COMPLETED | _RUN_STATES_ACTIVE | _RUN_STATES_CANCELLED))
    cancelled = sum(1 for r in runs if r["tripStatus"] in _RUN_STATES_CANCELLED)
    return {
        "total":     total,
        "completed": completed,
        "active":    active,
        "scheduled": scheduled,
        "cancelled": cancelled,
    }
