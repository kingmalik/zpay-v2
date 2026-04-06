"""
Audit logging middleware — logs all state-changing requests (POST/PUT/DELETE/PATCH).
"""

import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("zpay.audit")


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            user = getattr(request.state, "user", None)
            username = user.get("username", "anonymous") if user else "anonymous"
            logger.info(
                "AUDIT user=%s method=%s path=%s status=%s",
                username,
                request.method,
                request.url.path,
                response.status_code,
            )

        return response
