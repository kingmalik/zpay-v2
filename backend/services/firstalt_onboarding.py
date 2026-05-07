"""
FirstAlt / Acumen 8-step onboarding orchestrator.

Step definitions:
  1. firstalt_invite   — send driver the FirstAlt app install link (priority_email_status)
  2. bgc               — BGC handoff to Brandon via email (bgc_status / brandon_email_status)
  3. fadv_bgc          — Pre-run First Advantage BGC via API before FirstAlt's check (fadv_status)
  4. drug_test_consent — Adobe Sign Web Form link emailed to driver (consent_status / drug_test_sent_at)
  5. training          — FirstAlt in-app training (training_status)
  6. files             — DL + vehicle registration + inspection uploaded (files_status)
  7. contract          — Acumen contract signed via Adobe Sign (contract_status)
  8. paychex           — Paychex enrollment + W-9 (paychex_status)

All write operations go through the route layer; this service owns API calls + email composition.

FADV Integration notes:
  - Base URL: https://api.fadv.com  (confirmed: fadv.com/integrations-and-apis/)
  - Auth: OAuth 2.0 client_credentials, token at /oauth/token
  - Create order: POST /orders
  - Fetch status: GET /orders/{report_id}
  - Webhook: configure via FADV portal, delivers POST to FADV_WEBHOOK_URL
  - Required env vars: FADV_CLIENT_ID, FADV_CLIENT_SECRET
  - If env vars absent: service logs error and returns degraded result — NEVER fakes data
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger("zpay.firstalt-onboarding")

# ── FADV constants ───────────────────────────────────────────────────────────

_FADV_BASE_URL = os.environ.get("FADV_BASE_URL", "https://api.fadv.com")
_FADV_CLIENT_ID = os.environ.get("FADV_CLIENT_ID", "")
_FADV_CLIENT_SECRET = os.environ.get("FADV_CLIENT_SECRET", "")

_fadv_token_cache: dict[str, Any] = {}


def _fadv_token() -> str | None:
    """Return a valid FADV OAuth token, refreshing if expired."""
    if not _FADV_CLIENT_ID or not _FADV_CLIENT_SECRET:
        return None

    now = datetime.now(timezone.utc).timestamp()
    cached = _fadv_token_cache.get("token")
    exp = _fadv_token_cache.get("exp", 0)
    if cached and now < exp - 60:
        return cached

    try:
        resp = requests.post(
            f"{_FADV_BASE_URL}/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": _FADV_CLIENT_ID,
                "client_secret": _FADV_CLIENT_SECRET,
            },
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
        token = payload.get("access_token")
        expires_in = int(payload.get("expires_in", 3600))
        _fadv_token_cache["token"] = token
        _fadv_token_cache["exp"] = now + expires_in
        return token
    except Exception as exc:
        logger.error("[fadv] Token fetch failed: %s", exc)
        return None


# ── FADV public API ──────────────────────────────────────────────────────────

def fadv_initiate_bgc(
    *,
    person_id: int,
    full_name: str,
    email: str,
    phone: str,
    home_address: str,
    ssn_last4: str,
) -> dict:
    """
    Initiate a First Advantage background check for the given driver.

    Returns:
        {
          "ok": True,
          "report_id": "...",
          "status": "initiated",
          "raw": {...}
        }
    or on failure:
        {
          "ok": False,
          "error": "...",
          "env_missing": True  # set when FADV creds are absent
        }

    NEVER returns fake data. If credentials are missing this fails loudly.
    """
    if not _FADV_CLIENT_ID or not _FADV_CLIENT_SECRET:
        msg = (
            "FADV credentials not configured. "
            "Set FADV_CLIENT_ID and FADV_CLIENT_SECRET in Railway env vars."
        )
        logger.error("[fadv] %s", msg)
        return {"ok": False, "error": msg, "env_missing": True}

    token = _fadv_token()
    if not token:
        return {"ok": False, "error": "Failed to obtain FADV OAuth token", "env_missing": False}

    # Split name
    name_parts = full_name.strip().split()
    first_name = name_parts[0] if name_parts else ""
    last_name = name_parts[-1] if len(name_parts) > 1 else ""

    payload: dict[str, Any] = {
        "applicant": {
            "firstName": first_name,
            "lastName": last_name,
            "email": email,
            "phone": phone,
            "address": home_address,
            "ssnLast4": ssn_last4,
        },
        "packageType": "MVR_CRIMINAL_7YEAR",  # standard for school transport subcontractors
        "referenceId": f"zpay-{person_id}",
    }

    try:
        resp = requests.post(
            f"{_FADV_BASE_URL}/orders",
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        report_id = data.get("reportId") or data.get("orderId") or data.get("id")
        status = (data.get("status") or "initiated").lower()
        logger.info("[fadv] BGC initiated person_id=%d report_id=%s", person_id, report_id)
        return {"ok": True, "report_id": str(report_id), "status": status, "raw": data}
    except requests.HTTPError as exc:
        body = ""
        try:
            body = exc.response.text[:500]
        except Exception:
            pass
        logger.error("[fadv] BGC initiation HTTP error person_id=%d: %s %s", person_id, exc, body)
        return {"ok": False, "error": f"FADV HTTP {exc.response.status_code}: {body}", "env_missing": False}
    except Exception as exc:
        logger.error("[fadv] BGC initiation failed person_id=%d: %s", person_id, exc)
        return {"ok": False, "error": str(exc), "env_missing": False}


def fadv_get_status(report_id: str) -> dict:
    """
    Fetch current status of a FADV background check by report ID.

    Returns:
        {
          "ok": True,
          "report_id": "...",
          "status": "clear" | "consider" | "pending" | "suspended",
          "raw": {...}
        }
    """
    if not _FADV_CLIENT_ID or not _FADV_CLIENT_SECRET:
        return {
            "ok": False,
            "error": "FADV credentials not configured — set FADV_CLIENT_ID and FADV_CLIENT_SECRET",
            "env_missing": True,
        }

    token = _fadv_token()
    if not token:
        return {"ok": False, "error": "Failed to obtain FADV OAuth token", "env_missing": False}

    try:
        resp = requests.get(
            f"{_FADV_BASE_URL}/orders/{report_id}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        status = (data.get("status") or "pending").lower()
        return {"ok": True, "report_id": report_id, "status": status, "raw": data}
    except Exception as exc:
        logger.error("[fadv] Status fetch failed report_id=%s: %s", report_id, exc)
        return {"ok": False, "error": str(exc), "env_missing": False}


# ── Brandon email builder ────────────────────────────────────────────────────

_BRANDON_EMAIL = os.environ.get("BRANDON_EMAIL", "Branden.Seeberger@firststudentinc.com")


def build_brandon_email_body(person) -> str:
    """Build the pre-filled BGC notification email body for Brandon at FirstAlt."""
    name = getattr(person, "full_name", None) or "N/A"
    email = getattr(person, "email", None) or "N/A"
    phone = getattr(person, "phone", None) or "N/A"
    address = getattr(person, "home_address", None) or "N/A"

    vehicle_parts = [
        str(person.vehicle_year) if getattr(person, "vehicle_year", None) else None,
        getattr(person, "vehicle_color", None),
        getattr(person, "vehicle_make", None),
        getattr(person, "vehicle_model", None),
    ]
    vehicle = " ".join(p for p in vehicle_parts if p) or "N/A"
    plate = getattr(person, "vehicle_plate", None) or "N/A"

    return (
        f"Hi Brandon,\n\n"
        f"Please find the details below for a new driver we are onboarding with Acumen International. "
        f"Kindly initiate the background check at your earliest convenience.\n\n"
        f"DRIVER INFORMATION\n"
        f"------------------\n"
        f"Name:           {name}\n"
        f"Email:          {email}\n"
        f"Phone:          {phone}\n"
        f"Address:        {address}\n\n"
        f"VEHICLE INFORMATION\n"
        f"-------------------\n"
        f"Vehicle:        {vehicle}\n"
        f"License Plate:  {plate}\n\n"
        f"Please let us know if you need any additional information or documentation.\n\n"
        f"Thank you,\n"
        f"Acumen International\n"
    )


def send_brandon_bgc_email(person) -> dict:
    """
    Send pre-filled BGC email to Brandon at FirstAlt.

    Returns {"ok": True} or {"ok": False, "error": "..."}.
    """
    from backend.services.email_service import send_plain_email

    subject = f"New Driver Onboarding — {getattr(person, 'full_name', 'Driver')}"
    body = build_brandon_email_body(person)
    try:
        send_plain_email(to=_BRANDON_EMAIL, subject=subject, body=body)
        logger.info("[fa-onboarding] Brandon BGC email sent for person_id=%d", person.person_id)
        return {"ok": True}
    except Exception as exc:
        logger.error("[fa-onboarding] Brandon email failed person_id=%d: %s", person.person_id, exc)
        return {"ok": False, "error": str(exc)}


# ── Drug test consent (Adobe Sign Web Form) ──────────────────────────────────

def send_drug_test_consent(person, record) -> dict:
    """
    Email the Adobe Sign drug-test consent Web Form URL to the driver.
    Uses the blank consortium form (never Acumen-branded — Priority Solutions strategy).

    Returns {"ok": True, "web_form_url": "..."} or {"ok": False, "error": "..."}.
    """
    from backend.services import adobe_sign
    try:
        result = adobe_sign.send_drug_test_consent(person.person_id)
        return result
    except Exception as exc:
        logger.error("[fa-onboarding] Consent email failed person_id=%d: %s", person.person_id, exc)
        return {"ok": False, "error": str(exc)}


# ── FirstAlt app install link ────────────────────────────────────────────────

_FIRSTALT_APP_IOS = "https://apps.apple.com/us/app/id6444050593"
_FIRSTALT_APP_ANDROID = "https://play.google.com/store/apps/details?id=com.firstalt.driver"
_FIRSTALT_SPGUARDIAN_URL = "https://spguardian.firstalt.com"


def send_firstalt_invite(person) -> dict:
    """
    Email the driver their FirstAlt Driver App install links + SP Guardian registration URL.

    Returns {"ok": True} or {"ok": False, "error": "..."}.
    """
    from backend.services.email_service import send_plain_email

    name = getattr(person, "full_name", "Driver")
    to_email = getattr(person, "email", None)

    if not to_email:
        return {"ok": False, "error": "Driver has no email address on file"}

    body = (
        f"Hi {name.split()[0] if name else 'there'},\n\n"
        f"Welcome to Acumen International! Please follow the steps below to complete your onboarding with FirstAlt.\n\n"
        f"STEP 1 — Download the FirstAlt Driver App\n"
        f"  iPhone: {_FIRSTALT_APP_IOS}\n"
        f"  Android: {_FIRSTALT_APP_ANDROID}\n\n"
        f"STEP 2 — Create your account at: {_FIRSTALT_SPGUARDIAN_URL}\n"
        f"  Use this email address to register: {to_email}\n\n"
        f"STEP 3 — Sign the Driver Acknowledgement form inside the app\n\n"
        f"STEP 4 — Upload a clear photo of your Driver's License inside the app\n\n"
        f"If you need any help, reply to this email or call us directly.\n\n"
        f"Thank you,\n"
        f"Acumen International\n"
    )

    try:
        send_plain_email(
            to=to_email,
            subject="Welcome to Acumen — Your FirstAlt Onboarding Steps",
            body=body,
        )
        logger.info("[fa-onboarding] FirstAlt invite sent person_id=%d to=%s", person.person_id, to_email)
        return {"ok": True}
    except Exception as exc:
        logger.error("[fa-onboarding] FirstAlt invite failed person_id=%d: %s", person.person_id, exc)
        return {"ok": False, "error": str(exc)}


# ── Paychex CSV export helper ────────────────────────────────────────────────

def build_paychex_csv_row(person) -> dict:
    """
    Return a dict representing a Paychex-formatted CSV row for this driver.
    Used by the admin to bulk-import new drivers into Paychex (no Paychex API yet).
    """
    name = (getattr(person, "full_name", "") or "").strip()
    parts = name.split()
    last = parts[-1] if len(parts) > 1 else ""
    first = parts[0] if parts else ""

    return {
        "Last Name": last,
        "First Name": first,
        "Email": getattr(person, "email", "") or "",
        "Phone": getattr(person, "phone", "") or "",
        "Address": getattr(person, "home_address", "") or "",
        "Worker Type": "1099",
        "Client": "Acumen (70189220)",
    }
