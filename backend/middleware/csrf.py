"""
CSRF protection middleware — double-submit cookie pattern.

On safe methods (GET/HEAD/OPTIONS): sets a zpay_csrf cookie with a random token.
On state-changing methods (POST/PUT/DELETE/PATCH): validates _csrf_token form field
matches the cookie value.
"""

import os
import secrets
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, PlainTextResponse

_COOKIE_NAME = "zpay_csrf"
_FORM_FIELD = "_csrf_token"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_EXEMPT_PATHS = {"/health", "/login", "/webhooks/adobe-sign"}
_is_production = bool(os.environ.get("ZPAY_PRODUCTION") or os.environ.get("RAILWAY_ENVIRONMENT"))


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        method = request.method.upper()

        if method in _SAFE_METHODS:
            # Ensure a CSRF cookie exists for forms to read
            response = await call_next(request)
            if _COOKIE_NAME not in request.cookies:
                token = secrets.token_urlsafe(32)
                response.set_cookie(
                    _COOKIE_NAME,
                    token,
                    httponly=False,  # JS/templates need to read it
                    samesite="strict",
                    secure=_is_production,
                    max_age=60 * 60 * 24,  # 24h
                )
            return response

        # State-changing request — validate CSRF token
        path = request.url.path
        if path in _EXEMPT_PATHS:
            return await call_next(request)

        content_type = request.headers.get("content-type", "")

        # API requests from the Next.js frontend are exempt from CSRF —
        # they are protected by CORS (same-origin) + session cookies.
        # Only plain form-encoded submissions (Jinja2 templates) need
        # double-submit cookie validation.
        accept = request.headers.get("accept", "")
        if "application/json" in content_type or "application/json" in accept:
            return await call_next(request)

        cookie_token = request.cookies.get(_COOKIE_NAME)
        if not cookie_token:
            return PlainTextResponse("CSRF validation failed: missing cookie", status_code=403)

        # Read token from form data
        form_token = None
        if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
            form = await request.form()
            form_token = form.get(_FORM_FIELD)

        if not form_token or not secrets.compare_digest(str(form_token), str(cookie_token)):
            return PlainTextResponse("CSRF validation failed: token mismatch", status_code=403)

        response = await call_next(request)
        # Rotate CSRF token after each state-changing request
        new_token = secrets.token_urlsafe(32)
        response.set_cookie(
            _COOKIE_NAME,
            new_token,
            httponly=False,
            samesite="strict",
            secure=_is_production,
            max_age=60 * 60 * 24,
        )
        return response
