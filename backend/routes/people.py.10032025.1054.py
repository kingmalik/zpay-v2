from __future__ import annotations
from typing import Dict
from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from sqlalchemy import select, func

from backend.db.db import SessionLocal
from backend.models import Person, Ride

# Keep in sync with db_people
CODE_FIELDS: tuple[str, ...] = ("code", "employee_code", "driver_code", "external")
NAME_FIELDS: tuple[str, ...] = ("name", "full_name", "display_name")

router = APIRouter()

def get_any_attr(obj, names):
    for n in names:
        if hasattr(obj, n):
            return getattr(obj, n)
    return None

def is_blank(v) -> bool:
    # Treat None, "", and NaN as blank
    if v is None:
        return True
    try:
        # float('nan') != float('nan')
        if isinstance(v, float) and v != v:
            return True
    except Exception:
        pass
    s = str(v).strip()
    return s == "" or s.lower() in {"nan", "none", "null"}

def fmt(v) -> str:
    return "" if is_blank(v) else str(v)

@router.get("/people", response_class=HTMLResponse)
def people():
    with SessionLocal() as db:
        people = db.execute(select(Person)).scalars().all()

        # Count rides in SQL on the Ride->Person FK (fallback to person_id)
        fk_col = getattr(Ride, "person_id", None)
        if fk_col is None:
            for c in Ride.__table__.columns:
                if c.name.endswith("_id"):
                    fk_col = getattr(Ride, c.name)
                    break
        counts: Dict[int, int] = {}
        if fk_col is not None:
            for pid, cnt in db.execute(select(fk_col, func.count()).group_by(fk_col)).all():
                if pid is not None:
                    counts[int(pid)] = int(cnt)

    # Figure out Person PK column
    pk_name = next(iter(Person.__table__.primary_key.columns)).name

    rows = []
    for p in people:
        pid = getattr(p, pk_name)
        code_val = get_any_attr(p, CODE_FIELDS)
        name_val = get_any_attr(p, NAME_FIELDS)
        created = getattr(p, "created", "")
        ride_cnt = counts.get(pid, 0)

        # Hide junk: both code and name blank AND no rides
        if is_blank(code_val) and is_blank(name_val) and ride_cnt == 0:
            continue

        rows.append((pid, fmt(code_val), fmt(name_val), fmt(created), ride_cnt))

    html = [
        "<!doctype html><html><body style='font-family: system-ui, sans-serif; padding:24px'>",
        "<h1>People</h1>",
        "<table border='1' cellspacing='0' cellpadding='6'>",
        "<tr><th>PK</th><th>Code</th><th>Name</th><th>Created</th><th>Rides</th></tr>",
        *[
            "<tr>"
            f"<td>{pid}</td>"
            f"<td>{code}</td>"
            f"<td>{name}</td>"
            f"<td>{created}</td>"
            f"<td><a href='/rides?person_id={pid}'>view</a> ({rides})</td>"
            "</tr>"
            for (pid, code, name, created, rides) in rows
        ],
        "</table>",
        "<p><a href='/'>Home</a> · <a href='/rides'>Rides</a> · <a href='/summary'>Summary</a></p>",
        "</body></html>",
    ]
    return HTMLResponse("\n".join(html))
