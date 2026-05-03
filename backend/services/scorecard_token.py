"""
backend/services/scorecard_token.py
=====================================
HMAC-signed token generator and verifier for public driver scorecards.

Token format (URL-safe base64 of JSON payload + HMAC-SHA256 signature):
    <base64url(payload)>.<base64url(sig)>

Payload fields:
    pid   — int   — person_id
    week  — str   — ISO week string "YYYY-Www"
    iat   — int   — issued-at unix timestamp (UTC)

Expiration: 14 days from iat.

Environment variable:
    SCORECARD_HMAC_SECRET — required in production, falls back to a weak
    dev-only constant if not set (will log a warning).

Mint links from anywhere:
    from backend.services.scorecard_token import mint_token, verify_token
    token = mint_token(person_id=42, week_iso="2026-W18")
    payload = verify_token(token)  # raises on invalid/expired
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass

logger = logging.getLogger("zpay.scorecard_token")

_TOKEN_TTL_SECONDS = 14 * 24 * 60 * 60  # 14 days

_WEAK_DEV_SECRET = "dev-only-scorecard-secret-do-not-use-in-production"


# ── Errors ─────────────────────────────────────────────────────────────────────

class TokenError(Exception):
    """Base class for token validation failures."""


class TokenExpiredError(TokenError):
    """Token was valid but is older than TOKEN_TTL_SECONDS."""


class TokenInvalidError(TokenError):
    """Token is malformed, tampered, or has an unknown version."""


# ── Payload ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TokenPayload:
    person_id: int
    week_iso: str     # "YYYY-Www"
    issued_at: int    # unix timestamp (UTC)


# ── Internal helpers ───────────────────────────────────────────────────────────

def _get_secret() -> bytes:
    secret = os.environ.get("SCORECARD_HMAC_SECRET", "")
    if not secret:
        logger.warning(
            "SCORECARD_HMAC_SECRET is not set — using insecure dev-only secret. "
            "Set this env var in production."
        )
        secret = _WEAK_DEV_SECRET
    return secret.encode()


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    # Restore padding
    pad = 4 - len(s) % 4
    if pad != 4:
        s += "=" * pad
    try:
        return base64.urlsafe_b64decode(s)
    except Exception as exc:
        raise TokenInvalidError("Base64 decode failed") from exc


def _sign(payload_b64: str, secret: bytes) -> str:
    sig = hmac.new(secret, payload_b64.encode(), hashlib.sha256).digest()
    return _b64url_encode(sig)


# ── Public API ─────────────────────────────────────────────────────────────────

def mint_token(person_id: int, week_iso: str, *, issued_at: int | None = None) -> str:
    """Create a signed HMAC token for a driver scorecard link.

    Args:
        person_id: The driver's person_id (int).
        week_iso:  ISO week string, e.g. "2026-W18".
        issued_at: Unix timestamp override — only used in tests for determinism.

    Returns:
        URL-safe token string of the form "<payload_b64>.<sig_b64>".
    """
    iat = issued_at if issued_at is not None else int(time.time())
    payload_dict = {"pid": person_id, "week": week_iso, "iat": iat}
    payload_bytes = json.dumps(payload_dict, separators=(",", ":")).encode()
    payload_b64 = _b64url_encode(payload_bytes)
    sig_b64 = _sign(payload_b64, _get_secret())
    return f"{payload_b64}.{sig_b64}"


def verify_token(token: str) -> TokenPayload:
    """Verify and decode a scorecard token.

    Raises:
        TokenInvalidError:  malformed token, wrong format, or bad signature.
        TokenExpiredError:  token is older than 14 days.

    Returns:
        TokenPayload with person_id, week_iso, issued_at.
    """
    parts = token.split(".")
    if len(parts) != 2:  # noqa: PLR2004
        raise TokenInvalidError("Token must have exactly one '.' separator")

    payload_b64, provided_sig = parts[0], parts[1]

    # Constant-time signature comparison
    secret = _get_secret()
    expected_sig = _sign(payload_b64, secret)
    if not hmac.compare_digest(expected_sig, provided_sig):
        raise TokenInvalidError("Token signature is invalid")

    # Decode payload
    try:
        payload_bytes = _b64url_decode(payload_b64)
        payload_dict = json.loads(payload_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise TokenInvalidError("Token payload is not valid JSON") from exc

    # Validate required fields
    try:
        pid = int(payload_dict["pid"])
        week = str(payload_dict["week"])
        iat = int(payload_dict["iat"])
    except (KeyError, ValueError) as exc:
        raise TokenInvalidError("Token payload is missing required fields") from exc

    # Check expiration
    age = int(time.time()) - iat
    if age > _TOKEN_TTL_SECONDS:
        raise TokenExpiredError(
            f"Token expired {age - _TOKEN_TTL_SECONDS}s ago "
            f"(TTL is {_TOKEN_TTL_SECONDS}s)"
        )

    return TokenPayload(person_id=pid, week_iso=week, issued_at=iat)


def mint_scorecard_url(person_id: int, week_iso: str, base_url: str = "") -> str:
    """Convenience wrapper — returns the full public URL for a scorecard.

    Args:
        person_id: Driver's person_id.
        week_iso:  ISO week string.
        base_url:  Frontend base, e.g. "https://frontend-ruddy-ten-82.vercel.app".
                   If empty, returns a relative path.

    Returns:
        Full URL like "https://.../scorecard/<token>" or "/scorecard/<token>".
    """
    token = mint_token(person_id, week_iso)
    return f"{base_url}/scorecard/{token}"
