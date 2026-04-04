"""
Simple shared-password auth middleware.

Checks for a signed session cookie on every request except public paths.
Redirects unauthenticated users to /login.
"""

import os
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

COOKIE_NAME = "zpay_session"
MAX_AGE = 30 * 24 * 60 * 60  # 30 days in seconds

# Paths that don't require auth
PUBLIC_PREFIXES = ("/login", "/static", "/health", "/out")


def _get_signer() -> URLSafeTimedSerializer:
    secret = os.environ.get("ZPAY_SECRET_KEY", "change-me-in-production-zpay-2026")
    return URLSafeTimedSerializer(secret)


def verify_session(cookie_value: str) -> bool:
    """Return True if the cookie is valid and not expired."""
    try:
        _get_signer().loads(cookie_value, max_age=MAX_AGE)
        return True
    except (BadSignature, SignatureExpired):
        return False


def create_session() -> str:
    """Create a signed session token."""
    return _get_signer().dumps({"authenticated": True})


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path

        # Allow public paths through
        if any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return await call_next(request)

        # Check session cookie
        cookie = request.cookies.get(COOKIE_NAME)
        if cookie and verify_session(cookie):
            return await call_next(request)

        # Not authenticated — redirect to login
        return RedirectResponse(url="/login", status_code=302)
