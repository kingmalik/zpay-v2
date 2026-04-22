"""
Adobe Acrobat Sign REST API v6 service.

Required env vars:
    ADOBE_SIGN_INTEGRATION_KEY       — integration key from Adobe Sign account
    ADOBE_SIGN_CONSENT_TEMPLATE_ID   — library template ID for the consent form
    ADOBE_SIGN_CONTRACT_TEMPLATE_ID  — library template ID for the Acumen driver contract

All functions raise ValueError / RuntimeError on failure with descriptive messages.
Uses httpx if available, falls back to requests.
"""

import os
import logging

from backend.utils.test_mode import redirect_email

_logger = logging.getLogger("zpay.adobe_sign")

# ---------------------------------------------------------------------------
# HTTP helper — httpx preferred, requests fallback
# ---------------------------------------------------------------------------

def _http_get(url: str, headers: dict) -> dict:
    try:
        import httpx
        resp = httpx.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except ImportError:
        import requests
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()


def _http_get_bytes(url: str, headers: dict) -> bytes:
    try:
        import httpx
        resp = httpx.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.content
    except ImportError:
        import requests
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.content


def _http_post(url: str, headers: dict, json_body: dict) -> dict:
    try:
        import httpx
        resp = httpx.post(url, headers=headers, json=json_body, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except ImportError:
        import requests
        resp = requests.post(url, headers=headers, json=json_body, timeout=30)
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _integration_key() -> str:
    key = os.environ.get("ADOBE_SIGN_INTEGRATION_KEY", "").strip()
    if not key:
        raise ValueError(
            "ADOBE_SIGN_INTEGRATION_KEY env var is not set. "
            "Set it in Railway or your local .env file."
        )
    return key


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {_integration_key()}"}


# Cache the base URI per process so we don't call it on every request
_cached_base_uri: str | None = None


# ---------------------------------------------------------------------------
# Public API functions
# ---------------------------------------------------------------------------

def get_base_uri() -> str:
    """
    GET /api/rest/v6/baseUris

    Returns the apiAccessPoint URL for this Adobe Sign account.
    Result is cached for the lifetime of the process.
    """
    global _cached_base_uri
    if _cached_base_uri:
        return _cached_base_uri

    url = "https://api.na4.adobesign.com/api/rest/v6/baseUris"
    try:
        data = _http_get(url, headers=_auth_headers())
    except Exception as exc:
        raise RuntimeError(f"Adobe Sign: failed to fetch base URI — {exc}") from exc

    api_access_point = data.get("apiAccessPoint")
    if not api_access_point:
        raise RuntimeError(
            f"Adobe Sign: /baseUris response missing apiAccessPoint. Response: {data}"
        )

    _cached_base_uri = api_access_point.rstrip("/")
    _logger.info("Adobe Sign base URI resolved: %s", _cached_base_uri)
    return _cached_base_uri


def send_envelope(
    signer_email: str,
    signer_name: str,
    doc_type: str,
    template_id: str | None = None,
) -> dict:
    """
    POST /api/rest/v6/agreements

    Creates an agreement (envelope) for the driver to sign.

    doc_type must be "consent_form" or "acumen_contract".
    If template_id is not provided, it is read from env vars:
        ADOBE_SIGN_CONSENT_TEMPLATE_ID   for doc_type="consent_form"
        ADOBE_SIGN_CONTRACT_TEMPLATE_ID  for doc_type="acumen_contract"

    Returns the raw Adobe Sign response dict, which includes:
        {
            "id": "<agreementId>",
            "status": "OUT_FOR_SIGNATURE",
            ...
        }
    """
    if doc_type not in ("consent_form", "acumen_contract"):
        raise ValueError(
            f"send_envelope: doc_type must be 'consent_form' or 'acumen_contract', got {doc_type!r}"
        )

    # TEST MODE: redirect signer to test email before sending the envelope
    signer_email = redirect_email(signer_email)

    # Resolve template ID
    if not template_id:
        env_var = (
            "ADOBE_SIGN_CONSENT_TEMPLATE_ID"
            if doc_type == "consent_form"
            else "ADOBE_SIGN_CONTRACT_TEMPLATE_ID"
        )
        template_id = os.environ.get(env_var, "").strip()
        if not template_id:
            raise ValueError(
                f"send_envelope: {env_var} env var is not set. "
                "Add the Adobe Sign library template ID to this env var."
            )

    doc_names = {
        "consent_form": "Driver Consent Form",
        "acumen_contract": "Acumen Driver Contract",
    }
    doc_label = doc_names[doc_type]

    base = get_base_uri()
    url = f"{base}/api/rest/v6/agreements"

    payload = {
        "fileInfos": [
            {
                "libraryDocumentId": template_id,
            }
        ],
        "name": doc_label,
        "participantSetsInfo": [
            {
                "memberInfos": [
                    {
                        "email": signer_email,
                        "name": signer_name,
                    }
                ],
                "order": 1,
                "role": "SIGNER",
            }
        ],
        "signatureType": "ESIGN",
        "state": "IN_PROCESS",
    }

    try:
        data = _http_post(url, headers=_auth_headers(), json_body=payload)
    except Exception as exc:
        raise RuntimeError(
            f"Adobe Sign: failed to create agreement for {signer_email} "
            f"(doc_type={doc_type!r}) — {exc}"
        ) from exc

    if "id" not in data:
        raise RuntimeError(
            f"Adobe Sign: agreement creation response missing 'id'. Response: {data}"
        )

    _logger.info(
        "Adobe Sign envelope created: id=%s doc_type=%s signer=%s",
        data["id"],
        doc_type,
        signer_email,
    )
    return data


def get_envelope_status(agreement_id: str) -> dict:
    """
    GET /api/rest/v6/agreements/{agreementId}

    Returns the full agreement status dict from Adobe Sign.
    Useful for polling or verifying webhook events.
    """
    if not agreement_id:
        raise ValueError("get_envelope_status: agreement_id is required")

    base = get_base_uri()
    url = f"{base}/api/rest/v6/agreements/{agreement_id}"

    try:
        data = _http_get(url, headers=_auth_headers())
    except Exception as exc:
        raise RuntimeError(
            f"Adobe Sign: failed to fetch status for agreement {agreement_id!r} — {exc}"
        ) from exc

    return data


def download_signed_document(agreement_id: str) -> bytes:
    """
    GET /api/rest/v6/agreements/{agreementId}/combinedDocument

    Downloads the fully signed PDF as raw bytes.
    Raises RuntimeError if the download fails.
    """
    if not agreement_id:
        raise ValueError("download_signed_document: agreement_id is required")

    base = get_base_uri()
    url = f"{base}/api/rest/v6/agreements/{agreement_id}/combinedDocument"

    headers = {**_auth_headers(), "Accept": "application/pdf"}

    try:
        pdf_bytes = _http_get_bytes(url, headers=headers)
    except Exception as exc:
        raise RuntimeError(
            f"Adobe Sign: failed to download signed document for agreement {agreement_id!r} — {exc}"
        ) from exc

    if not pdf_bytes:
        raise RuntimeError(
            f"Adobe Sign: downloaded 0 bytes for agreement {agreement_id!r}"
        )

    _logger.info(
        "Adobe Sign signed PDF downloaded: agreement_id=%s size=%d bytes",
        agreement_id,
        len(pdf_bytes),
    )
    return pdf_bytes


def send_drug_test_consent(person_id: int) -> dict:
    """
    Send Priority Solutions drug test consent form from library template.

    Loads full_name from the person record and creates an agreement using the
    drug test library template. Pre-fills EnrolleeName only. SSN last 4,
    signature, and date are filled by the driver in Adobe's guided signing flow.
    Stores agreement ID and sent_at timestamp in person table.

    Args:
        person_id: ID of the person (driver) record in the database

    Returns:
        dict with keys:
            - "id": Adobe Sign agreement ID
            - "status": agreement status ("OUT_FOR_SIGNATURE", etc.)
            - "created_at": timestamp when sent
            - "full_name": driver's full name
            - "email": driver's email address

    Raises:
        ValueError if person not found or missing email
        RuntimeError if Adobe Sign API call fails
    """
    from datetime import datetime, timezone
    from backend.db import SessionLocal
    from backend.db.models import Person

    db = SessionLocal()
    try:
        person = db.query(Person).filter(Person.person_id == person_id).first()
        if not person:
            raise ValueError(f"Person {person_id} not found in database")

        if not person.email:
            raise ValueError(f"Person {person_id} has no email address on file")

        signer_email = redirect_email(person.email)
        signer_name = person.full_name or f"Driver {person_id}"

        # Get the drug test template ID from env
        template_id = os.environ.get("ADOBE_SIGN_DRUG_TEST_TEMPLATE_ID", "").strip()
        if not template_id:
            raise ValueError(
                "ADOBE_SIGN_DRUG_TEST_TEMPLATE_ID env var is not set. "
                "Set it in Railway or your local .env file."
            )

        base = get_base_uri()
        url = f"{base}/api/rest/v6/agreements"

        payload = {
            "fileInfos": [
                {
                    "libraryDocumentId": template_id,
                }
            ],
            "name": "Priority Solutions Drug Test Consent",
            "mergeFieldInfo": [
                {
                    "fieldName": "EnrolleeName",
                    "defaultValue": signer_name,
                },
            ],
            "participantSetsInfo": [
                {
                    "memberInfos": [
                        {
                            "email": signer_email,
                            "name": signer_name,
                        }
                    ],
                    "order": 1,
                    "role": "signer1",
                }
            ],
            "signatureType": "ESIGN",
            "state": "IN_PROCESS",
        }

        try:
            data = _http_post(url, headers=_auth_headers(), json_body=payload)
        except Exception as exc:
            raise RuntimeError(
                f"Adobe Sign: failed to create drug test consent agreement for {signer_email} — {exc}"
            ) from exc

        if "id" not in data:
            raise RuntimeError(
                f"Adobe Sign: agreement creation response missing 'id'. Response: {data}"
            )

        agreement_id = data["id"]
        now = datetime.now(timezone.utc)

        # Store agreement ID and sent timestamp in person table
        person.drug_test_agreement_id = agreement_id
        person.drug_test_sent_at = now
        db.commit()

        _logger.info(
            "Adobe Sign drug test consent sent: person_id=%s agreement_id=%s signer=%s",
            person_id,
            agreement_id,
            signer_email,
        )

        return {
            "id": agreement_id,
            "status": data.get("status"),
            "created_at": now.isoformat(),
            "full_name": signer_name,
            "email": signer_email,
        }

    finally:
        db.close()
