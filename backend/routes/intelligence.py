from pathlib import Path
from datetime import date
import json

from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.routes.analytics import _build_analytics, _get_companies, _get_batches
from backend.routes.pareto import _build_pareto
from backend.routes.insights import _build_snapshot, _call_claude

router = APIRouter(prefix="/intelligence", tags=["intelligence"])

_templates = None


def templates():
    global _templates
    if _templates is None:
        templates_dir = Path(__file__).resolve().parents[1] / "templates"
        _templates = Jinja2Templates(directory=str(templates_dir))
    return _templates


@router.get("/", name="intelligence_page")
def intelligence_page(
    request: Request,
    company: str | None = Query(None),
    batch_id: int | None = Query(None),
    start: date | None = Query(None),
    end: date | None = Query(None),
    tab: str | None = Query(None),
    db: Session = Depends(get_db),
):
    from sqlalchemy import func
    from backend.db.models import Ride

    companies = _get_companies(db)
    batches = _get_batches(db, company=company)

    analytics_data = _build_analytics(db, company=company, batch_id=batch_id, start=start, end=end)

    pareto_data = _build_pareto(db, company=company)

    snapshot = _build_snapshot(db, company=company)

    zero_rate_count = db.query(func.count(Ride.ride_id)).filter(Ride.z_rate == 0).scalar() or 0

    active_tab = tab if tab in ("analytics", "pareto", "insights") else "analytics"

    return templates().TemplateResponse(
        request,
        "intelligence.html",
        {
            "companies": companies,
            "selected_company": company,
            "batches": batches,
            "selected_batch_id": batch_id,
            "start": start,
            "end": end,
            "zero_rate_count": zero_rate_count,
            "active_tab": active_tab,
            # analytics
            **analytics_data,
            # pareto — prefix keys to avoid name collisions with analytics
            "pareto_driver_rows": pareto_data["driver_rows"],
            "pareto_least_profitable_rows": pareto_data["least_profitable_rows"],
            "pareto_driver_summary": pareto_data["driver_summary"],
            "pareto_service_by_volume": pareto_data["service_by_volume"],
            "pareto_service_by_profit": pareto_data["service_by_profit"],
            "pareto_service_summary": pareto_data["service_summary"],
            "pareto_period_rows": pareto_data["period_rows"],
            "pareto_period_summary": pareto_data["period_summary"],
            # insights
            "snapshot": snapshot,
            "narrative": None,  # generated on demand via POST
        },
    )


@router.post("/generate-insights", name="intelligence_generate_insights")
async def generate_insights(
    request: Request,
    company: str | None = Query(None),
    db: Session = Depends(get_db),
):
    snapshot = _build_snapshot(db, company=company)
    narrative = _call_claude(snapshot)
    return JSONResponse({"narrative": narrative})
