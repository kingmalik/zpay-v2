# backend/routes/people.py

from pathlib import Path
from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.db import get_db
from backend.models import Person, Ride

router = APIRouter(prefix="/people", tags=["people"])

_templates = None
def templates():
    global _templates
    if _templates is None:
        templates_dir = Path(__file__).resolve().parents[1] / "templates"
        _templates = Jinja2Templates(directory=str(templates_dir))
    return _templates


@router.get("/", name="people_index")
def people_index(request: Request, db: Session = Depends(get_db)):
    # ride counts by person_id
    counts = dict(
        db.query(Ride.person_id, func.count(Ride.ride_id))
          .group_by(Ride.person_id)
          .all()
    )

    people = []
    for p in db.query(Person).order_by(Person.person_id.asc()).all():
        pid = int(p.person_id)
        people.append({
            "id": pid,                               # template uses p.id
            "code": p.external_id,                   # template uses p.code
            "name": p.full_name,                     # template uses p.name
            "created_at": getattr(p, "created_at", ""),
            "ride_count": int(counts.get(pid, 0)),
        })

    return templates().TemplateResponse(
        "people.html",
        {"request": request, "people": people},
    )
