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
    Send Priority Solutions drug test consent form via email with Adobe Web Form URL.

    No Adobe API key required. Loads person from DB, reads ADOBE_SIGN_CONSENT_WEB_FORM_URL
    from env, and emails the driver a link to complete the form. Adobe automatically
    emails the signed PDF back to mazservices3@gmail.com once the driver submits.

    Args:
        person_id: ID of the person (driver) record in the database

    Returns:
        dict with keys:
            - "method": "web_form_email"
            - "email": driver's email address
            - "url": the Adobe Web Form URL sent to driver
            - "sent_at": ISO timestamp when email was sent

    Raises:
        ValueError if person not found, missing email, or env var not set
        RuntimeError if email send fails
    """
    from datetime import datetime, timezone
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    import base64
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

        # Get the web form URL from env
        web_form_url = os.environ.get("ADOBE_SIGN_CONSENT_WEB_FORM_URL", "").strip()
        if not web_form_url:
            raise ValueError(
                "ADOBE_SIGN_CONSENT_WEB_FORM_URL env var is not set. "
                "Set it in Railway or your local .env file."
            )

        # Send email via Gmail API
        try:
            from backend.services.email_service import _get_gmail_service, _body_to_html

            gmail_service, from_email = _get_gmail_service("maz")

            first_name = signer_name.split()[0] if signer_name else "Driver"
            subject = "Drug Test Consortium Consent — please complete"
            body = (
                f"Hi {first_name},\n\n"
                "To complete your onboarding, please fill out and sign the Priority Solutions "
                "Drug Test Consortium consent form here:\n\n"
                f"{web_form_url}\n\n"
                "This takes about 2 minutes. Reach out if you have questions.\n\n"
                "— Maz Services"
            )
            html = _body_to_html(body, "maz", subject)

            msg = MIMEMultipart("alternative")
            msg["To"] = signer_email
            msg["From"] = from_email
            msg["Subject"] = test_subject(subject)
            msg.attach(MIMEText(body, "plain"))
            msg.attach(MIMEText(html, "html"))

            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
            gmail_service.users().messages().send(userId="me", body={"raw": raw}).execute()

        except Exception as exc:
            raise RuntimeError(
                f"Failed to send drug test consent email to {signer_email} — {exc}"
            ) from exc

        # Store placeholder agreement ID and sent timestamp in onboarding_record
        now = datetime.now(timezone.utc)
        agreement_id = f"WEBFORM:{now.timestamp()}"

        # Update onboarding_record with drug_test tracking
        from backend.db.models import OnboardingRecord
        onboarding_rec = db.query(OnboardingRecord).filter(
            OnboardingRecord.person_id == person_id
        ).first()

        if onboarding_rec:
            onboarding_rec.drug_test_agreement_id = agreement_id
            onboarding_rec.drug_test_sent_at = now
            db.commit()
            _logger.info(
                "Drug test consent web form emailed: onboarding_id=%d person_id=%d email=%s agreement_id=%s",
                onboarding_rec.id,
                person_id,
                signer_email,
                agreement_id,
            )
        else:
            # Fallback: update person table for backwards compat
            person.drug_test_agreement_id = agreement_id
            person.drug_test_sent_at = now
            db.commit()
            _logger.info(
                "Drug test consent web form emailed: person_id=%d email=%s (no onboarding_record, fallback to person)",
                person_id,
                signer_email,
            )

        return {
            "method": "web_form_email",
            "email": signer_email,
            "url": web_form_url,
            "sent_at": now.isoformat(),
        }

    finally:
        db.close()


# DEPRECATED: register_drug_test_webhook is no longer needed.
# Drug test consent now uses web form email (free approach) instead of Adobe API.
# Left in place for reference but not called anywhere.
#
# def register_drug_test_webhook(webhook_url: str) -> dict:
#     """
#     Register a webhook with Adobe Sign for drug test consent completion events.
#
#     This endpoint is called once at system startup (or manually by admin) to register
#     the /webhooks/adobe-sign path with Adobe Sign so they know where to POST events.
#
#     Args:
#         webhook_url: Full HTTPS URL where Adobe will POST events, e.g.
#                      https://myapp.example.com/api/data/webhooks/adobe-sign
#
#     Returns:
#         dict with keys:
#             - "id": Adobe webhook ID
#             - "status": "ACTIVE" or similar
#             - ...full Adobe response
#
#     Raises:
#         RuntimeError if webhook registration fails
#     """
#     template_id = os.environ.get("ADOBE_SIGN_DRUG_TEST_TEMPLATE_ID", "").strip()
#     if not template_id:
#         raise ValueError(
#             "ADOBE_SIGN_DRUG_TEST_TEMPLATE_ID env var is not set. "
#             "Cannot register webhook without the library template ID."
#         )
#
#     base = get_base_uri()
#     url = f"{base}/api/rest/v6/webhooks"
#
#     payload = {
#         "url": webhook_url,
#         "name": "Drug Test Consent Completion",
#         "events": ["AGREEMENT_ACTION_COMPLETED"],
#         "scope": "LIBRARY_DOCUMENT",
#         "resourceId": template_id,
#     }
#
#     try:
#         data = _http_post(url, headers=_auth_headers(), json_body=payload)
#     except Exception as exc:
#         raise RuntimeError(
#             f"Adobe Sign: failed to register webhook at {webhook_url!r} — {exc}"
#         ) from exc
#
#     if "id" not in data:
#         raise RuntimeError(
#             f"Adobe Sign: webhook registration response missing 'id'. Response: {data}"
#         )
#
#     _logger.info(
#         "Adobe Sign webhook registered: id=%s url=%s events=%s",
#         data.get("id"),
#         webhook_url,
#         payload["events"],
#     )
#     return data
