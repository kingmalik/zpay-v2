"""
HTTPS redirect middleware that works behind a reverse proxy (Railway, Heroku, etc.).

Checks X-Forwarded-Proto instead of the raw scheme, and exempts health check endpoints
so internal load balancer probes don't get redirected.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

_EXEMPT_PATHS = {"/health"}


class ProxyHTTPSRedirectMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip health checks (Railway's internal probes use HTTP)
        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        # Check the proxy header, not the raw scheme
        proto = request.headers.get("x-forwarded-proto", "https")
        if proto != "https":
            url = request.url.replace(scheme="https")
            return RedirectResponse(url=str(url), status_code=307)

        return await call_next(request)
