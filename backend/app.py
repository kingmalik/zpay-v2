import os
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from backend.routes import upload, summary, rides, people, email, dispatch, dispatch_everdriven, dispatch_assign, dispatch_simulate, email_templates, dispatch_monitor, workflow
from backend.routes import admin_rates
from backend.routes import analytics
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
    yield
    # Shutdown
    if os.environ.get("MONITOR_ENABLED") == "1":
        from backend.services.trip_monitor import stop_monitor
        stop_monitor()


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
    allow_methods=["*"],
    allow_headers=["*"],
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

@app.get("/health/gmail-test")
def health_gmail_test():
    """Test Gmail API OAuth2 credentials for both accounts."""
    import os, traceback
    results = {}
    for label in ("ACUMEN", "MAZ"):
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            cid = os.environ.get("GMAIL_CLIENT_ID", "")
            csecret = os.environ.get("GMAIL_CLIENT_SECRET", "")
            rtok = os.environ.get(f"GMAIL_REFRESH_TOKEN_{label}", "")
            user = os.environ.get(f"GMAIL_USER_{label}", "")
            if not all([cid, csecret, rtok, user]):
                results[label] = {"ok": False, "error": "missing env vars"}
                continue
            creds = Credentials(
                token=None, refresh_token=rtok,
                client_id=cid, client_secret=csecret,
                token_uri="https://oauth2.googleapis.com/token",
                scopes=["https://www.googleapis.com/auth/gmail.send"],
            )
            creds.refresh(Request())
            results[label] = {"ok": True, "user": user, "token_valid": creds.valid}
        except Exception as e:
            results[label] = {"ok": False, "error": str(e), "trace": traceback.format_exc()[-300:]}
    return results

@app.get("/debug/headers")
def debug_headers(request: Request):
    return {"headers": dict(request.headers)}
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
app.include_router(email.router)
app.include_router(email_templates.router)
app.include_router(dispatch.router)
app.include_router(dispatch_everdriven.router)
app.include_router(dispatch_assign.router)
app.include_router(dispatch_simulate.router)
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

# Dedicated JSON API for Next.js frontend
from backend.routes import api_data
app.include_router(api_data.router)
app.include_router(workflow.router)
