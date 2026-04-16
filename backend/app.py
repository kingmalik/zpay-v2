import os
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from backend.routes import upload, summary, rides, people, email, dispatch, dispatch_everdriven, dispatch_assign, dispatch_simulate, dispatch_manage, email_templates, dispatch_monitor, workflow, paychex_bot
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

        try:
            from backend.services.onboarding_monitor import start_onboarding_monitor
            start_onboarding_monitor()
            _logger.info("Onboarding monitor started")
        except Exception as e:
            _logger.warning("Onboarding monitor failed to start: %s", e)

    yield

    # Shutdown
    if os.environ.get("MONITOR_ENABLED") == "1":
        from backend.services.trip_monitor import stop_monitor
        stop_monitor()

        try:
            from backend.services.onboarding_monitor import stop_onboarding_monitor
            stop_onboarding_monitor()
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
app.include_router(paychex_bot.router)
app.include_router(users_routes.router)
app.include_router(sops_routes.router)
app.include_router(tasks_routes.router)
app.include_router(error_report_routes.router)


@app.post("/api/admin/migrate-one-shot-disabled")
async def run_migration(request: Request):
    """One-shot migration endpoint — delete after use."""
    from sqlalchemy import text as sqla_text
    from backend.db import engine

    steps = []
    try:
        with engine.begin() as conn:
            # Check if already migrated
            exists = conn.execute(sqla_text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='sop')"
            )).scalar()
            if exists:
                return {"status": "already_migrated", "steps": []}

            conn.execute(sqla_text("""
                CREATE TABLE sop (
                    sop_id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    category TEXT,
                    owner_role TEXT NOT NULL DEFAULT 'operator',
                    trigger_when TEXT,
                    content TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    created_by INTEGER REFERENCES user_account(user_id),
                    updated_by INTEGER REFERENCES user_account(user_id),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    archived BOOLEAN NOT NULL DEFAULT false
                )
            """))
            conn.execute(sqla_text("CREATE INDEX ix_sop_category ON sop (category)"))
            conn.execute(sqla_text("CREATE INDEX ix_sop_archived ON sop (archived)"))
            steps.append("created sop table")

            conn.execute(sqla_text("""
                CREATE TABLE sop_field_note (
                    id SERIAL PRIMARY KEY,
                    sop_id INTEGER NOT NULL REFERENCES sop(sop_id) ON DELETE CASCADE,
                    author_user_id INTEGER NOT NULL REFERENCES user_account(user_id),
                    note TEXT NOT NULL,
                    promoted BOOLEAN NOT NULL DEFAULT false,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """))
            conn.execute(sqla_text("CREATE INDEX ix_sop_field_note_sop ON sop_field_note (sop_id)"))
            steps.append("created sop_field_note table")

            conn.execute(sqla_text("""
                CREATE TABLE task (
                    task_id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT,
                    assignee_id INTEGER REFERENCES user_account(user_id),
                    created_by INTEGER REFERENCES user_account(user_id),
                    priority TEXT NOT NULL DEFAULT 'normal',
                    status TEXT NOT NULL DEFAULT 'todo',
                    due_at TIMESTAMPTZ,
                    linked_sop_id INTEGER REFERENCES sop(sop_id),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    completed_at TIMESTAMPTZ
                )
            """))
            conn.execute(sqla_text("CREATE INDEX ix_task_assignee ON task (assignee_id)"))
            conn.execute(sqla_text("CREATE INDEX ix_task_status ON task (status)"))
            steps.append("created task table")

            conn.execute(sqla_text("""
                CREATE TABLE task_checklist_item (
                    id SERIAL PRIMARY KEY,
                    task_id INTEGER NOT NULL REFERENCES task(task_id) ON DELETE CASCADE,
                    label TEXT NOT NULL,
                    done BOOLEAN NOT NULL DEFAULT false,
                    order_index INTEGER NOT NULL DEFAULT 0
                )
            """))
            conn.execute(sqla_text("CREATE INDEX ix_task_checklist_task ON task_checklist_item (task_id)"))
            steps.append("created task_checklist_item table")

            conn.execute(sqla_text("""
                CREATE TABLE task_comment (
                    id SERIAL PRIMARY KEY,
                    task_id INTEGER NOT NULL REFERENCES task(task_id) ON DELETE CASCADE,
                    author_user_id INTEGER NOT NULL REFERENCES user_account(user_id),
                    body TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """))
            conn.execute(sqla_text("CREATE INDEX ix_task_comment_task ON task_comment (task_id)"))
            steps.append("created task_comment table")

            # Seed SOPs
            sop_seeds = [
                ("Register Twilio A2P 10DLC", "admin", "operator",
                 "Before any SMS alerts can go out to drivers — one-time setup.",
                 "# Register Twilio A2P 10DLC\n\nFollow Twilio console steps to register MAZ Services brand and campaign."),
                ("Weekly Payroll Batch Upload", "payroll", "operator",
                 "Every Monday after FirstAlt + EverDriven files arrive.",
                 "# Weekly Payroll Batch Upload\n\nUpload CSVs in Z-Pay → Payroll → Upload Files, verify totals, apply to Paychex."),
                ("Handling a Declined Trip (Substitute Needed)", "dispatch", "operator",
                 "Trip monitor alerts — driver declines or doesn't confirm.",
                 "# Handling a Declined Trip\n\nOpen Dispatch → Live Dispatch, reassign to a substitute driver."),
                ("Adding a New Driver (FirstAlt + EverDriven)", "onboarding", "operator",
                 "New hire joins the network.",
                 "# Adding a New Driver\n\nGo to People → All Drivers → Add New, fill details, send invite token."),
                ("Monthly Reconciliation", "payroll", "admin",
                 "Last business day of each month.",
                 "# Monthly Reconciliation\n\nZ-Pay → Reconciliation. Review unmatched rows and fix each mismatch."),
            ]
            a2p_sop_id = None
            for title, cat, role, trigger, content in sop_seeds:
                row = conn.execute(sqla_text(
                    "INSERT INTO sop (title, category, owner_role, trigger_when, content) "
                    "VALUES (:t, :c, :r, :tr, :co) RETURNING sop_id"
                ), {"t": title, "c": cat, "r": role, "tr": trigger, "co": content}).fetchone()
                if "A2P" in title:
                    a2p_sop_id = row[0]
            steps.append("seeded 5 SOPs")

            # Seed A2P task for mom
            mom = conn.execute(sqla_text(
                "SELECT user_id FROM user_account WHERE username='mom' LIMIT 1"
            )).fetchone()
            malik = conn.execute(sqla_text(
                "SELECT user_id FROM user_account WHERE username='malik' LIMIT 1"
            )).fetchone()
            if mom and a2p_sop_id:
                task_row = conn.execute(sqla_text(
                    "INSERT INTO task (title, description, assignee_id, created_by, priority, status, linked_sop_id) "
                    "VALUES (:title, :desc, :assignee, :creator, 'high', 'todo', :sop) RETURNING task_id"
                ), {
                    "title": "Register Twilio A2P 10DLC",
                    "desc": "SMS alerts are silently failing without registration. Follow the linked SOP.",
                    "assignee": mom[0],
                    "creator": malik[0] if malik else None,
                    "sop": a2p_sop_id,
                }).fetchone()
                task_id = task_row[0]
                for i, label in enumerate([
                    "Log into Twilio Console", "Create Brand (MAZ Services)",
                    "Create Campaign with sample messages", "Submit for approval",
                    "Verify test SMS once approved", "Notify Malik and mark done",
                ]):
                    conn.execute(sqla_text(
                        "INSERT INTO task_checklist_item (task_id, label, order_index) VALUES (:t, :l, :o)"
                    ), {"t": task_id, "l": label, "o": i})
                steps.append("seeded A2P task for mom")

            # Mark migration in alembic_version
            conn.execute(sqla_text(
                "INSERT INTO alembic_version (version_num) VALUES ('y4z5a6b7c8d9') "
                "ON CONFLICT (version_num) DO NOTHING"
            ))
            steps.append("stamped alembic version y4z5a6b7c8d9")

        return {"status": "ok", "steps": steps}
    except Exception as e:
        return {"status": "error", "error": str(e), "steps": steps}
