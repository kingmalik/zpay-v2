"""
Minimal RFC 6238 TOTP (SHA-1, 30s step, 6 digits) — stdlib only.

Used by the Paychex bot to answer the authenticator-app MFA prompt without a
human. The secret is the base32 key Paychex shows during authenticator
enrollment ("can't scan the QR? use this key"), stored as
PAYCHEX_TOTP_SECRET_<COMPANY> (or shared PAYCHEX_TOTP_SECRET) in Railway env.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import time

TOTP_STEP_SECONDS = 30
TOTP_DIGITS = 6


def _normalize_secret(secret: str) -> bytes:
    """Base32-decode an enrollment key, tolerating spaces/dashes/lowercase/loose padding."""
    cleaned = secret.replace(" ", "").replace("-", "").strip().upper()
    padded = cleaned + "=" * (-len(cleaned) % 8)
    return base64.b32decode(padded, casefold=True)


def totp_at(secret: str, unix_time: float) -> str:
    """RFC 6238 code for the given secret at the given unix timestamp."""
    key = _normalize_secret(secret)
    counter = int(unix_time // TOTP_STEP_SECONDS)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10 ** TOTP_DIGITS)).zfill(TOTP_DIGITS)


def totp_now(secret: str) -> str:
    """Current TOTP code for the secret."""
    return totp_at(secret, time.time())


def seconds_remaining(unix_time: float | None = None) -> int:
    """Seconds until the current TOTP window rolls over."""
    t = time.time() if unix_time is None else unix_time
    return TOTP_STEP_SECONDS - int(t % TOTP_STEP_SECONDS)
