"""
backend/routes/admin_keys_health.py
====================================
External API key health dashboard + manual triggers.

Routes (all auth required):
  GET  /admin/keys-health
      Read-only status for every external key. Returns live check results
      (re-runs the checks fresh) so the page is never stale.

  POST /admin/keys-health/run
      Force one cron cycle now. Useful immediately after rotating a key
      to confirm it took without waiting for the next scheduled run.

  POST /admin/keys-health/gmail-keepalive
      Force the preventive Gmail keep-alive ping right now.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger("zpay.admin_keys_health")

router = APIRouter(prefix="/keys-health", tags=["admin-keys-health"])


@router.get("")
def list_status() -> JSONResponse:
    """Live status — every check runs fresh on each request."""
    from backend.services.key_health import run_all_checks
    results = run_all_checks()
    return JSONResponse({
        "checks": [r.to_dict() for r in results],
        "ok_count": sum(1 for r in results if r.ok),
        "dead_count": sum(1 for r in results if not r.ok),
    })


@router.post("/run")
def trigger_cycle() -> JSONResponse:
    """Trigger a watchdog cycle now (alerts on transitions)."""
    from backend.services.key_health import run_watchdog_cycle
    summary = run_watchdog_cycle()
    return JSONResponse(summary)


@router.post("/gmail-keepalive")
def trigger_gmail_keepalive() -> JSONResponse:
    """Force the Gmail keep-alive ping."""
    from backend.services.key_health import gmail_keepalive
    return JSONResponse(gmail_keepalive())
