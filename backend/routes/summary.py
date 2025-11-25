from fastapi import APIRouter, Depends, Request, Query, HTTPException
from fastapi.responses import HTMLResponse
from datetime import date
from sqlalchemy.orm import Session

from ..db import get_db
from ..db.crud import people_rollup

router = APIRouter(prefix="/summary", tags=["summary"])

_templates = None
def _get_templates():
    global _templates
    if _templates is not None:
        return _templates
    try:
        from starlette.templating import Jinja2Templates
    except Exception:
        raise HTTPException(500, "Jinja2 not installed. Add 'Jinja2>=3.1' to requirements and rebuild.")
    _templates = Jinja2Templates(directory="backend/templates")
    return _templates

@router.get("/", response_class=HTMLResponse, name="summary_index")
def summary_page(
    request: Request,
    start: date | None = Query(None),
    end:   date | None = Query(None),
    person_id: int | None = Query(None),
    code: str | None = Query(None),
    db: Session = Depends(get_db),
):
    data = people_rollup(db, start=start, end=end, person_id=person_id, code=code)
    return _get_templates().TemplateResponse(
        "summary.html",
        {"request": request, "rows": data["rows"], "totals": data["totals"], "start": start, "end": end},
    )
