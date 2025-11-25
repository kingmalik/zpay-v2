# backend/routes/people.py
from sqlalchemy import select, func, literal_column
from sqlalchemy.inspection import inspect as sa_inspect
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse

from backend.db import get_db
from backend.db.db import SessionLocal
from backend.models import Person, Ride  # adjust import if different
    
router = APIRouter(prefix="/people", tags=["people"])

def _coalesce(model, names, default_literal=""):
    cols = [getattr(model, n) for n in names if hasattr(model, n)]
    if not cols:
        return literal_column(f"'{default_literal}'")
    return cols[0] if len(cols) == 1 else func.coalesce(*cols)

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
@router.get("/people", response_class=HTMLResponse)
def people_index(request: Request, db: Session = Depends(get_db)):
    db: Session = SessionLocal()
    try:
        # --- primary key (dynamic) ---
        # --- PKs / columns ---
        p_insp = sa_inspect(Person)
        if not p_insp.primary_key:
            raise HTTPException(status_code=500, detail="Person model has no primary key")
        person_pk = p_insp.primary_key[0]  # instrumented attribute

        r_insp = sa_inspect(Ride)
        ride_pk_col = r_insp.primary_key[0] if r_insp.primary_key else None
        rides_count = func.count(ride_pk_col) if ride_pk_col is not None else func.count(literal_column("1"))

        # coalesced display columns (your helper _coalesce is fine to keep)
        code_col    = _coalesce(Person, ("code", "employee_code", "driver_code", "external"))
        name_col    = _coalesce(Person, ("full_name", "name", "display_name"))
        created_col = _coalesce(Person, ("created", "created_on", "inserted_at"))

        # IMPORTANT: use aggregates for display cols; group by ONLY the PK
        code_sel    = func.max(code_col).label("code")
        name_sel    = func.max(name_col).label("name")
        created_sel = func.max(created_col).label("created")

        # try to find a real FK on Ride to join
        ride_fk = None
        for fk_name in ("person_id", "employee_id", "person_fk", "personid"):
            cand = getattr(Ride, fk_name, None)
            if cand is not None:
                ride_fk = cand
                break

        if ride_fk is not None:
            # FK join path
            stmt = (
                select(
                    person_pk.label("pid"),
                    code_sel,
                    name_sel,
                    created_sel,
                    rides_count.label("rides"),
                )
                .select_from(Person)
                .join(Ride, ride_fk == person_pk, isouter=True)
                .group_by(person_pk)                # <-- only the PK here
                .order_by(name_sel.asc())
            )
        elif hasattr(Ride, "person"):
            # no FK; count rides by matching Ride.person text to the person's name
            rides_subq = (
                select(func.count(literal_column("1")))
                .where(Ride.person == name_col)
                .correlate(Person)
                .scalar_subquery()
            )
            stmt = (
                select(
                    person_pk.label("pid"),
                    code_sel,
                    name_sel,
                    created_sel,
                    rides_subq.label("rides"),
                )
                .select_from(Person)
                .group_by(person_pk)                # <-- only the PK here
                .order_by(name_sel.asc())
            )
        else:
            # last resort: no ride info
            stmt = (
                select(
                    person_pk.label("pid"),
                    code_sel,
                    name_sel,
                    created_sel,
                    literal_column("0").label("rides"),
                )
                .select_from(Person)
                .group_by(person_pk)                # <-- only the PK here
                .order_by(name_sel.asc())
            )

        rows = db.execute(stmt).all()

        # --- render simple HTML ---
        parts = [
            "<!doctype html><html><head><meta charset='utf-8'><title>People</title>",
            "<style>body{font-family:system-ui,Segoe UI,Arial,sans-serif;padding:20px;max-width:960px;margin:auto}"
            "table{border-collapse:collapse;width:100%}th,td{border:1px solid #eee;padding:8px}th{background:#fafafa}"
            "a{color:#0b6}.muted{color:#666}</style></head><body>",
            "<h1>People</h1><p class='muted'>Click a person to view rides and summary.</p>",
            "<table><thead><tr><th>ID</th><th>Code</th><th>Name</th><th>Created</th><th>Rides</th></tr></thead><tbody>",
        ]
        for pid, code, name, created, rides in rows:
            parts.append(
                "<tr>"
                f"<td>{pid}</td>"
                f"<td>{code or ''}</td>"
                f"<td><a href='/summary?person_id={pid}'>{name or '(no name)'}</a></td>"
                f"<td>{'' if created in (None, 'None') else created}</td>"
                f"<td><a href='/rides/data?person_id={pid}'>view</a> ({int(rides or 0)})</td>"
                "</tr>"
            )
        parts += ["</tbody></table>", "<p><a href='/upload'>Upload</a> · <a href='/docs'>API</a></p>", "</body></html>"]
        return HTMLResponse("\n".join(parts))
    finally:
        db.close()
