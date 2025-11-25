from typing import Optional, Union
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.crud import person_rides, person_summary


router = APIRouter()
templates = Jinja2Templates(directory="backend/templates")

@router.get("/rides")
def rides_page(
    request: Request,
    person_id: Optional[int] = Query(None),
    person: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    target: Union[int, str, None] = person_id if person_id is not None else person
    if target is None:
        raise HTTPException(status_code=400, detail="Provide person_id or person")

    rows = person_rides(db, target, limit=limit)
    meta = person_summary(db, target)
    payload = {"rows": [ _row_to_dict(r) for r in rows ], **meta}

    if templates:
        # expects a template file: backend/templates/rides.html
        return templates.TemplateResponse(
            "rides.html",
            {"request": request, "rows": rows, **meta},
        )

    return JSONResponse(content=jsonable_encoder(payload))
def _row_to_dict(row):
    """Convert a SQLAlchemy row or object to a plain dict."""
    if hasattr(row, "__table__"):
        # ORM object
        return {c.name: getattr(row, c.name) for c in row.__table__.columns}
    elif isinstance(row, dict):
        return row
    else:
        # Row mapping (Row from text() or select())
        return dict(row._mapping)
