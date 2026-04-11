"""
Multi-user shared-password auth middleware.
Users are configured via env vars. Session cookie contains user identity.
Passwords must be bcrypt-hashed and stored in ZPAY_PASSWORD_HASH_* env vars.
"""

import os
import json
import logging
import bcrypt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

logger = logging.getLogger("zpay.auth")

COOKIE_NAME = "zpay_session"
MAX_AGE = 30 * 24 * 60 * 60  # 30 days

PUBLIC_PREFIXES = ("/login", "/static", "/health", "/out", "/debug", "/api/data/paychex-bot/store-session", "/api/data/onboarding/join")

_WEAK_SECRET = "change-me-in-production-zpay-2026"

# ── User registry (env-configurable) ──────────────────────────
def get_users() -> dict:
    return {
        "malik": {
            "display_name": os.environ.get("ZPAY_DISPLAY_MALIK", "Malik"),
            "password_hash": os.environ.get("ZPAY_PASSWORD_HASH_MALIK", ""),
            "role": "admin",
            "color": "#4facfe",
            "initials": "M",
        },
        "mom": {
            "display_name": os.environ.get("ZPAY_DISPLAY_MOM", "Mom"),
            "password_hash": os.environ.get("ZPAY_PASSWORD_HASH_MOM", ""),
            "role": "admin",
            "color": "#764ba2",
            "initials": "♡",
        },
    }

def _get_signer() -> URLSafeTimedSerializer:
    secret = os.environ.get("ZPAY_SECRET_KEY", "")
    if not secret or secret == _WEAK_SECRET:
        raise RuntimeError(
            "ZPAY_SECRET_KEY is missing or set to the default. "
            "Generate a strong key: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
        )
    return URLSafeTimedSerializer(secret)

def verify_session(cookie_value: str) -> dict | None:
    """Return user dict if valid, else None."""
    try:
        data = _get_signer().loads(cookie_value, max_age=MAX_AGE)
        if isinstance(data, dict) and "username" in data:
            return data
        return None
    except (BadSignature, SignatureExpired):
        return None

def create_session(username: str, display_name: str, color: str, initials: str, role: str = "viewer") -> str:
    payload = {
        "username": username,
        "display_name": display_name,
        "color": color,
        "initials": initials,
        "role": role,
    }
    return _get_signer().dumps(payload)

def authenticate(username: str, password: str) -> dict | None:
    """Return user dict if credentials match (bcrypt), else None."""
    users = get_users()
    user = users.get(username.lower().strip())
    if not user:
        return None
    stored_hash = user.get("password_hash", "")
    if not stored_hash:
        logger.warning("No password hash configured for user: %s", username)
        return None
    try:
        if bcrypt.checkpw(password.strip().encode("utf-8"), stored_hash.encode("utf-8")):
            safe_user = {k: v for k, v in user.items() if k != "password_hash"}
            return {"username": username.lower().strip(), **safe_user}
    except (ValueError, TypeError) as e:
        logger.error("Bcrypt verification error for user %s: %s", username, e)
    return None


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path

        if any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return await call_next(request)

        cookie = request.cookies.get(COOKIE_NAME)
        user = verify_session(cookie) if cookie else None
        if user:
            request.state.user = user
            return await call_next(request)

        return RedirectResponse(url="/login", status_code=302)
