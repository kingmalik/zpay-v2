import os
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from backend.routes import upload, summary, rides, people, email, dispatch, dispatch_everdriven, dispatch_manage, dispatch_monitor, dispatch_overrides, workflow, paychex_bot
from backend.routes import trip_monitor as trip_monitor_routes  # DEPRECATED — router kept for now, merge into dispatch/monitor in Stage 6
from backend.routes import whatsapp as whatsapp_routes
from backend.routes import webhooks as webhooks_routes
from backend.routes import admin_rates
from backend.routes import error_report as error_report_routes
from backend.routes import people_audit
from backend.routes import rates
from backend.routes import alerts
from backend.routes import batches
from backend.routes import payroll_history
from backend.routes import snapshot
from backend.routes import dashboard
from backend.routes import ytd
from backend.routes import auth as auth_routes
from backend.routes import reconciliation
from backend.routes import activity
from backend.routes import admin_settings
from backend.routes import gmail_reauth
from backend.routes import users as users_routes
from backend.routes import public as public_routes
# sops_routes and tasks_routes — DEPRECATED — routes removed, models kept in DB until next migration PR

from backend.middleware.auth import AuthMiddleware
from backend.middleware.security_headers import SecurityHeadersMiddleware
from backend.middleware.csrf import CSRFMiddleware
from backend.middleware.audit import AuditMiddleware
from backend.routes.auth import limiter

_is_production = bool(os.environ.get("ZPAY_PRODUCTION") or os.environ.get("RAILWAY_ENVIRONMENT"))
_logger = logging.getLogger("zpay.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    if os.environ.get("MONITOR_ENABLED") == "1":
        from backend.services.trip_monitor import start_monitor
        start_monitor()
        _logger.info("Trip monitor started")

        # Partner auth preflight — surface stale creds before cycles silently fail.
        try:
            from backend.services import firstalt_service
            firstalt_service._get_token()  # forces cognito auth; raises on failure
            _logger.info("FirstAlt auth preflight OK")
        except Exception as fa_err:
            _logger.error("FirstAlt auth preflight FAILED: %s", fa_err)
            try:
                from backend.services import notification_service
                notification_service.alert_admin(
                    f"FIRSTALT AUTH BROKEN at startup — {str(fa_err)[:200]}. "
                    "Trip monitor will silently miss all FA trips until creds refresh.",
                    spoken_message="FirstAlt credentials are broken. Trip monitor can't see FirstAlt trips.",
                )
            except Exception:
                pass

        try:
            from backend.services import everdriven_service
            import datetime as _dt
            everdriven_service.get_runs(_dt.date.today())  # forces auth; raises on failure
            _logger.info("EverDriven auth preflight OK")
        except Exception as ed_err:
            _logger.error("EverDriven auth preflight FAILED: %s", ed_err)
            try:
                from backend.services import notification_service
                notification_service.alert_admin(
                    f"EVERDRIVEN AUTH BROKEN at startup — {str(ed_err)[:200]}. "
                    "Trip monitor will silently miss all ED trips until creds refresh.",
                    spoken_message="EverDriven credentials are broken. Trip monitor can't see EverDriven trips.",
                )
            except Exception:
                pass

        try:
            from backend.services.onboarding_monitor import start_onboarding_monitor
            start_onboarding_monitor()
            _logger.info("Onboarding monitor started")
        except Exception as e:
            _logger.warning("Onboarding monitor failed to start: %s", e)

        try:
            from backend.services.firstalt_compliance import start_compliance_sync
            import threading
            threading.Thread(
                target=start_compliance_sync,
                daemon=True,
                name="compliance-startup",
            ).start()
            _logger.info("FirstAlt compliance sync started")
        except Exception as e:
            _logger.warning("FirstAlt compliance sync failed to start: %s", e)

    # ── Boot guard — empty-DB detection ────────────────────────────────────
    # If the ride table is empty AND ALLOW_EMPTY_DB != "1", refuse to start.
    # This prevents the silent 6-hour wipe that happened on 2026-05-03:
    # Railway reprovisioned Postgres → auto-restore ran → backend started
    # silently with 0 rows → ops continued as if nothing happened.
    #
    # Set ALLOW_EMPTY_DB=1 in Railway ONLY when intentionally provisioning a
    # fresh database (new environment, scratch DB, post-restore seed).
    try:
        import psycopg  # type: ignore
        import re as _re
        from urllib.parse import urlparse as _urlparse

        _db_url = os.environ.get("DATABASE_URL", "")
        _allow_empty = os.environ.get("ALLOW_EMPTY_DB", "0") == "1"

        if _db_url:
            _clean_url = _re.sub(r"^postgresql\+\w+://", "postgresql://", _db_url)
            _clean_url = _re.sub(r"^postgres://", "postgresql://", _clean_url)
            _parsed = _urlparse(_clean_url)
            _conn_info = dict(
                host=_parsed.hostname or "db",
                port=int(_parsed.port or 5432),
                user=_parsed.username or "app",
                password=_parsed.password or "",
                dbname=_parsed.path.lstrip("/") or "appdb",
                connect_timeout=5,
            )
            with psycopg.connect(**_conn_info) as _conn:
                with _conn.cursor() as _cur:
                    _cur.execute("SELECT COUNT(*) FROM ride;")
                    _ride_count = (_cur.fetchone() or [0])[0]

            if _ride_count == 0:
                _msg = (
                    f"BOOT GUARD: ride table is EMPTY (0 rows). "
                    f"This likely means Railway reprovisioned Postgres. "
                    f"Set ALLOW_EMPTY_DB=1 to permit empty-DB boot if intentional."
                )
                _logger.critical(_msg)

                # Fire Discord alert
                try:
                    import subprocess as _sp
                    _discord_script = str(
                        __import__("pathlib").Path.home() / ".claude" / "scripts" / "notify_discord.sh"
                    )
                    _sp.run(
                        [_discord_script, f"ZPay BOOT GUARD: DB is empty — possible Postgres wipe! {_msg}"],
                        timeout=10, capture_output=True,
                    )
                except Exception as _da:
                    _logger.warning("Boot guard Discord alert failed: %s", _da)

                if not _allow_empty:
                    _logger.critical("Refusing to start with empty DB. Set ALLOW_EMPTY_DB=1 to override.")
                    raise SystemExit(1)
                else:
                    _logger.critical(
                        "ALLOW_EMPTY_DB=1 is set — permitting empty-DB boot. "
                        "THIS IS A WARNING: verify data has been restored."
                    )
            else:
                _logger.info("Boot guard OK — ride table has %d rows", _ride_count)
        else:
            _logger.warning("Boot guard: DATABASE_URL not set, skipping ride count check")

    except SystemExit:
        raise
    except Exception as _bg_err:
        _logger.error("Boot guard check failed (non-fatal): %s", _bg_err)

    # Always warm the dispatch cache on startup so first page load is instant
    from backend.routes.dispatch import start_cache_warmer
    start_cache_warmer()
    _logger.info("Dispatch cache warmer started")

    # Health monitor — opt-in via HEALTH_MONITOR_ENABLED=1, independent of MONITOR_ENABLED
    try:
        from backend.services.health_monitor import start_health_monitor
        start_health_monitor()
    except Exception as e:
        _logger.warning("Health monitor failed to start: %s", e)

    if os.environ.get("WHATSAPP_INTEL_ENABLED") == "1":
        from backend.services.financial_intel_service import start_financial_intel
        start_financial_intel()
        _logger.info("Financial intelligence daily report scheduled")

    # B4: Gmail keepalive cron — runs every 2 days at 3 AM PT.
    # Calls _get_gmail_service() for each account (forces creds.refresh()) to
    # prevent Railway from evicting stale tokens and to surface expiry before
    # a payroll send.  Runs unconditionally (not gated on MONITOR_ENABLED) so
    # the keepalive fires even on lean deployments.
    # Non-fatal: any failure is logged; no email alert (pre-flight is the UX surface).
    _gmail_keepalive_scheduler = None
    try:
        import threading as _threading

        _gmail_keepalive_lock = _threading.Lock()

        def _gmail_keepalive_job() -> None:
            if not _gmail_keepalive_lock.acquire(blocking=False):
                _logger.info("Gmail keepalive: already running, skipping cycle")
                return
            try:
                from backend.services.email_service import _get_gmail_service
                for _acct in ("acumen", "maz"):
                    try:
                        _get_gmail_service(_acct)
                        _logger.info("Gmail keepalive: %s token refresh OK", _acct)
                    except Exception as _exc:
                        _logger.error(
                            "Gmail keepalive: %s token refresh FAILED — %s. "
                            "Gmail will be broken for this account until reauth.",
                            _acct, _exc,
                        )
            finally:
                _gmail_keepalive_lock.release()

        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        _gmail_keepalive_scheduler = BackgroundScheduler(timezone="America/Los_Angeles")
        _gmail_keepalive_scheduler.add_job(
            _gmail_keepalive_job,
            trigger=CronTrigger(hour=3, minute=0, day="*/2"),
            id="gmail_keepalive",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        _gmail_keepalive_scheduler.start()
        _logger.info("Gmail keepalive scheduler started (every 2 days at 3 AM PT)")
    except Exception as _ks_err:
        _logger.warning("Gmail keepalive scheduler failed to start: %s", _ks_err)

    yield

    # Shutdown
    if _gmail_keepalive_scheduler is not None:
        try:
            _gmail_keepalive_scheduler.shutdown(wait=False)
            _logger.info("Gmail keepalive scheduler stopped")
        except Exception:
            pass

    from backend.routes.dispatch import stop_cache_warmer
    stop_cache_warmer()

    if os.environ.get("WHATSAPP_INTEL_ENABLED") == "1":
        from backend.services.financial_intel_service import stop_financial_intel
        stop_financial_intel()

    try:
        from backend.services.health_monitor import stop_health_monitor
        stop_health_monitor()
    except Exception:
        pass

    if os.environ.get("MONITOR_ENABLED") == "1":
        from backend.services.trip_monitor import stop_monitor
        stop_monitor()

        try:
            from backend.services.onboarding_monitor import stop_onboarding_monitor
            stop_onboarding_monitor()
        except Exception:
            pass

        try:
            from backend.services.firstalt_compliance import stop_compliance_sync
            stop_compliance_sync()
        except Exception:
            pass


app = FastAPI(title="ZPay", version="0.1.0", lifespan=lifespan)

# Rate limiter state
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — allow Next.js frontend (set FRONTEND_URL env var after Vercel deploy)
from fastapi.middleware.cors import CORSMiddleware
_frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_frontend_url, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["Content-Type", "Authorization", "Accept", "Origin", "X-Requested-With", "X-CSRF-Token"],
)

# Middleware stack (order matters: first added = outermost)
# 1. Security headers on every response
app.add_middleware(SecurityHeadersMiddleware)
# 2. HTTPS redirect in production (custom: checks X-Forwarded-Proto, exempts /health)
if _is_production:
    from backend.middleware.https_redirect import ProxyHTTPSRedirectMiddleware
    app.add_middleware(ProxyHTTPSRedirectMiddleware)
# 3. Audit logging for state-changing requests
app.add_middleware(AuditMiddleware)
# 4. Auth — checks session cookie on all non-public routes
app.add_middleware(AuthMiddleware)
# 5. CSRF protection on POST/PUT/DELETE
app.add_middleware(CSRFMiddleware)


# -----------------------------
# Templates (robust path)
# -----------------------------
BASE_DIR = Path(__file__).resolve().parent  # /app/backend
STATIC_DIR = BASE_DIR / "static"
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.state.templates = templates

# CSRF helper available in all templates: {{ csrf_input() }}
from markupsafe import Markup
from jinja2 import pass_context

@pass_context
def _csrf_input_helper(context) -> Markup:
    request = context.get("request")
    token = request.cookies.get("zpay_csrf", "") if request else ""
    return Markup(f'<input type="hidden" name="_csrf_token" value="{token}">')

templates.env.globals["csrf_input"] = _csrf_input_helper

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# /data/out only exists in local Docker — skip gracefully on cloud deployments
_data_out = os.environ.get("DATA_OUT_DIR", "/data/out")
if os.path.isdir(_data_out):
    app.mount("/out", StaticFiles(directory=_data_out), name="out")


@app.get("/health")
def health():
    return {"status": "ok"}


# API-only mode: redirect all HTML routes to the Vercel frontend
_api_only = bool(os.environ.get("ZPAY_API_ONLY"))
if _api_only:
    @app.middleware("http")
    async def _redirect_html_to_frontend(request: Request, call_next):
        path = request.url.path
        # Pass through API, health, static, and onboarding join routes
        if (
            path.startswith("/api/")
            or path.startswith("/static/")
            or path.startswith("/health")
            or path.startswith("/out/")
            or path.startswith("/users")
            or path == "/favicon.ico"
        ):
            return await call_next(request)
        # Redirect everything else to the Vercel frontend
        frontend = os.environ.get("FRONTEND_URL", "https://frontend-ruddy-ten-82.vercel.app")
        return RedirectResponse(url=frontend, status_code=302)



@app.post("/health/upload-session/{company}")
async def health_upload_session(company: str, request: Request):
    """Public endpoint for uploading Paychex session cookies (internal-secret protected)."""
    secret = request.headers.get("X-Internal-Secret", "")
    expected = os.environ.get("ZPAY_INTERNAL_SECRET", "")
    if not expected:
        return JSONResponse({"error": "Internal secret not configured"}, status_code=503)
    if secret != expected:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    company = company.strip().lower()
    if company not in ("acumen", "maz"):
        return {"error": "Invalid company"}
    body = await request.json()
    cookies = body.get("cookies", [])
    if not cookies:
        return {"error": "No cookies"}
    from backend.db import SessionLocal as _SessionLocal
    from backend.db.models import PaychexSession
    from datetime import datetime, timezone
    db = _SessionLocal()
    try:
        row = db.query(PaychexSession).filter_by(company=company).first()
        if row:
            row.cookies = cookies
            row.captured_at = datetime.now(timezone.utc)
        else:
            row = PaychexSession(company=company, cookies=cookies, captured_at=datetime.now(timezone.utc))
            db.add(row)
        db.commit()
    finally:
        db.close()
    return {"ok": True, "company": company, "cookie_count": len(cookies)}


# -----------------------------
# Routers
# -----------------------------
# Auth routes (login/logout) — must be before dashboard
app.include_router(auth_routes.router)

# Dashboard must be first so / is not shadowed by summary redirect
app.include_router(dashboard.router)

app.include_router(upload.router)
app.include_router(summary.router)
app.include_router(rides.router)
app.include_router(people.router)
app.include_router(people_audit.router)
app.include_router(email.router)
app.include_router(dispatch.router)
app.include_router(dispatch_everdriven.router)
app.include_router(dispatch_manage.router)  # reliability + scorecard weekly endpoint
app.include_router(dispatch_monitor.router)
app.include_router(dispatch_overrides.router)
app.include_router(trip_monitor_routes.router)  # DEPRECATED — kept temporarily while /dispatch/monitor is updated to serve its data

app.include_router(rates.router)
app.include_router(alerts.router)
app.include_router(batches.router)
app.include_router(payroll_history.router)
app.include_router(snapshot.router)

app.include_router(ytd.router)
app.include_router(reconciliation.router)
app.include_router(activity.router)

# Admin UI (mount under /admin)
app.include_router(admin_rates.router, prefix="/admin")
app.include_router(admin_settings.router)
app.include_router(gmail_reauth.router)

# Dedicated JSON API for Next.js frontend
from backend.routes import api_data
app.include_router(api_data.router)
app.include_router(workflow.router)
from backend.routes import onboarding
from backend.routes import onboarding_files
from backend.routes import ops as ops_routes
app.include_router(onboarding.router, prefix="/api/data")
# Public onboarding join routes — no auth required, registered under /api/data
app.include_router(onboarding.public_router, prefix="/api/data")
# Public self-service apply — no auth required
app.include_router(onboarding.apply_router, prefix="/api/data")
app.include_router(onboarding_files.router, prefix="/api/data")
app.include_router(ops_routes.router, prefix="/api/data")

from backend.routes import ops_dashboard as ops_dashboard_routes
app.include_router(ops_dashboard_routes.router, prefix="/api/data")
from backend.routes import api_ops
app.include_router(api_ops.router, prefix="/api/data")
app.include_router(paychex_bot.router)
app.include_router(users_routes.router)
# sops and tasks routers removed — DB tables deprecated, drop in next migration PR
app.include_router(error_report_routes.router)
app.include_router(whatsapp_routes.router)
app.include_router(webhooks_routes.router)

from backend.routes import twilio_gather as twilio_gather_routes
app.include_router(twilio_gather_routes.router)

# Health monitor admin endpoints
from backend.routes import health_admin
app.include_router(health_admin.router)

# Public unauthenticated routes (no session required — bypass AuthMiddleware via PUBLIC_PREFIXES)
app.include_router(public_routes.router)

# Scorecard admin + unsubscribe endpoints (Phase 10)
from backend.routes import admin_scorecard as admin_scorecard_routes
app.include_router(admin_scorecard_routes.router, prefix="/admin")
app.include_router(admin_scorecard_routes.public_router)

# Paystub archive — Phase 1
from backend.routes import paystubs as paystubs_routes
app.include_router(paystubs_routes.router)
app.include_router(paystubs_routes.people_router)

