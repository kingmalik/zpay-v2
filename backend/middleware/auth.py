"""
Multi-user shared-password auth middleware.
Users are configured via env vars. Session cookie contains user identity.
"""

import os
import json
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

COOKIE_NAME = "zpay_session"
MAX_AGE = 30 * 24 * 60 * 60  # 30 days

PUBLIC_PREFIXES = ("/login", "/static", "/health", "/out")

# ── User registry (env-configurable) ──────────────────────────
def get_users() -> dict:
    return {
        "malik": {
            "display_name": os.environ.get("ZPAY_DISPLAY_MALIK", "Malik"),
            "password": os.environ.get("ZPAY_PASSWORD_MALIK", os.environ.get("ZPAY_PASSWORD", "zpay2026")),
            "color": "#667eea",
            "initials": "M",
        },
        "mom": {
            "display_name": os.environ.get("ZPAY_DISPLAY_MOM", "Mom"),
            "password": os.environ.get("ZPAY_PASSWORD_MOM", "mom2026"),
            "color": "#f093fb",
            "initials": "♡",
        },
    }

def _get_signer() -> URLSafeTimedSerializer:
    secret = os.environ.get("ZPAY_SECRET_KEY", "change-me-in-production-zpay-2026")
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

def create_session(username: str, display_name: str, color: str, initials: str) -> str:
    payload = {
        "username": username,
        "display_name": display_name,
        "color": color,
        "initials": initials,
    }
    return _get_signer().dumps(payload)

def authenticate(username: str, password: str) -> dict | None:
    """Return user dict if credentials match, else None."""
    users = get_users()
    user = users.get(username.lower().strip())
    if user and password.strip() == user["password"]:
        return {"username": username.lower().strip(), **user}
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
