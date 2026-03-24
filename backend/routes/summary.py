from pathlib import Path
from datetime import date

from fastapi import APIRouter, Depends, Request, Query
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.crud import people_rollup

router = APIRouter(prefix="/summary", tags=["summary"])

_templates = None
def templates():
    global _templates
    if _templates is None:
        templates_dir = Path(__file__).resolve().parents[1] / "templates"
        _templates = Jinja2Templates(directory=str(templates_dir))
    return _templates


@router.get("/", name="summary_page")
def summary_page(
    request: Request,
    start: date | None = Query(None),
    end: date | None = Query(None),
    person_id: int | None = Query(None),
    code: str | None = Query(None),
    db: Session = Depends(get_db),
):
    data = people_rollup(db, start=start, end=end, person_id=person_id, code=code)
    return templates().TemplateResponse(
        request,
        "summary.html",
        {
            "rows": data.get("rows", []),
            "totals": data.get("totals", {}),
            "start": start,
            "end": end,
        },
    )
