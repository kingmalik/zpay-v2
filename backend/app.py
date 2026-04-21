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

from backend.routes import upload, summary, rides, people, email, dispatch, dispatch_everdriven, dispatch_assign, dispatch_simulate, dispatch_manage, email_templates, dispatch_monitor, workflow, paychex_bot
from backend.routes import whatsapp as whatsapp_routes
from backend.routes import admin_rates
from backend.routes import analytics
from backend.routes import error_report as error_report_routes
from backend.routes import people_audit
from backend.routes import rates
from backend.routes import alerts
from backend.routes import batches
from backend.routes import payroll_history
from backend.routes import insights
from backend.routes import intelligence
from backend.routes import validate
from backend.routes import snapshot
from backend.routes import dashboard
from backend.routes import ytd
from backend.routes import auth as auth_routes
from backend.routes import reconciliation
from backend.routes import activity
from backend.routes import admin_settings
from backend.routes import gmail_reauth
from backend.routes import users as users_routes
from backend.routes import sops as sops_routes
from backend.routes import tasks as tasks_routes
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

    yield

    # Shutdown
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
            or path.startswith("/sops")
            or path.startswith("/tasks")
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
app.include_router(email_templates.router)
app.include_router(dispatch.router)
app.include_router(dispatch_everdriven.router)
app.include_router(dispatch_assign.router)
app.include_router(dispatch_simulate.router)
app.include_router(dispatch_manage.router)
app.include_router(dispatch_monitor.router)

app.include_router(analytics.router)
app.include_router(rates.router)
app.include_router(alerts.router)
app.include_router(batches.router)
app.include_router(payroll_history.router)
app.include_router(insights.router)
app.include_router(intelligence.router)
app.include_router(validate.router)
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
from backend.routes import api_ops
app.include_router(api_ops.router, prefix="/api/data")
app.include_router(paychex_bot.router)
app.include_router(users_routes.router)
app.include_router(sops_routes.router)
app.include_router(tasks_routes.router)
app.include_router(error_report_routes.router)
app.include_router(whatsapp_routes.router)

# Health monitor admin endpoints
from backend.routes import health_admin
app.include_router(health_admin.router)

