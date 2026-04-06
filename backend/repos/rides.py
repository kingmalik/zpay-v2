# backend/repos/rides.py
from sqlalchemy.orm import Session
from backend.models import Ride, Person

def person_rides(
    db: Session,
    person_id: int | None = None,
    person_code: str | None = None,
    limit: int = 100,
):
    """Return rides for a given person by ID or code."""
    query = db.query(Ride)
    if person_id is not None:
        query = query.filter(Ride.person_id == person_id)
    elif person_code is not None:
        query = query.join(Person).filter(Person.person_code == person_code)
    query = query.order_by(Ride.id.desc()).limit(limit)
    rows = query.all()
    meta = {"count": len(rows)}
    return rows, meta
