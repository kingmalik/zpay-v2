from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from backend.routes import upload, summary, rides, people, email, dispatch, dispatch_everdriven, dispatch_assign
from backend.routes import admin_rates
from backend.routes import analytics
from backend.routes import pareto
from backend.routes import rates
from backend.routes import alerts
from backend.routes import batches
from backend.routes import payroll_history
from backend.routes import insights
from backend.routes import intelligence


app = FastAPI(title="ZPay", version="0.1.0")


# -----------------------------
# Templates (robust path)
# -----------------------------
BASE_DIR = Path(__file__).resolve().parent  # /app/backend
STATIC_DIR = BASE_DIR / "static" 
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.state.templates = templates

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/out", StaticFiles(directory="/data/out"), name="out")
# -----------------------------
# Routers
# -----------------------------
app.include_router(upload.router)
app.include_router(summary.router)
app.include_router(rides.router)
app.include_router(people.router)
app.include_router(email.router)
app.include_router(dispatch.router)
app.include_router(dispatch_everdriven.router)
app.include_router(dispatch_assign.router)

app.include_router(analytics.router)
app.include_router(pareto.router)
app.include_router(rates.router)
app.include_router(alerts.router)
app.include_router(batches.router)
app.include_router(payroll_history.router)
app.include_router(insights.router)
app.include_router(intelligence.router)

# Admin UI (mount under /admin)
app.include_router(admin_rates.router, prefix="/admin")


# Root: redirect to /upload
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return RedirectResponse(url="/summary", status_code=303)
