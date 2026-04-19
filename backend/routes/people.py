# backend/routes/people.py
import sqlalchemy as sa

from pathlib import Path
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, literal, text, Date

from datetime import datetime, date 
from decimal import Decimal

from backend.db import get_db
from backend.db.models import Person, Ride, PayrollBatch, DriverBalance


router = APIRouter(prefix="/people", tags=["people"])



_templates = None
def templates():
    global _templates
    if _templates is None:
        templates_dir = Path(__file__).resolve().parents[1] / "templates"
        _templates = Jinja2Templates(directory=str(templates_dir))

        # ---- filters ----
        from datetime import datetime, date as _date
        def _as_date(v):
            if v is None:
                return None
            if isinstance(v, _date) and not isinstance(v, datetime):
                return v
            if isinstance(v, datetime):
                return v.date()
            return v

        _templates.env.filters["currency"] = lambda v: "" if v is None else f"${float(v):,.2f}"
        _templates.env.filters["mmddyyyy"] = lambda v: "" if v is None else _as_date(v).strftime("%m/%d/%Y")
        _templates.env.filters["weeklabel"] = lambda ws, we: f"{_as_date(ws).strftime('%m/%d/%Y')} - {_as_date(we).strftime('%m/%d/%Y')}"
    return _templates

def _week_cols(db: Session):
    # 1) If Ride really has week_start/week_end, use them
    if hasattr(Ride, "week_start") and hasattr(Ride, "week_end"):
        return Ride.week_start, Ride.week_end, None  # no join needed

    # 2) If rides link to PayrollBatch that has week_start/week_end, use that
    # (common in your project)
    try:
        from backend.db.models import PayrollBatch  # adjust if named differently
        if hasattr(Ride, "payroll_batch_id") and hasattr(PayrollBatch, "week_start") and hasattr(PayrollBatch, "week_end"):
            return PayrollBatch.week_start, PayrollBatch.week_end, PayrollBatch
    except Exception:
        pass

    # 3) Fallback: compute week from ride date
    ws, we = _computed_week_cols_from_date()
    return ws, we, None

def _source_col():
    # "maz" / "acumen"
    if hasattr(Ride, "source"):
        return Ride.source
    if hasattr(Ride, "import_source"):
        return Ride.import_source
    # fallback to company_name only if you truly don't store source
    return None

def _company_source_cols():
    """
    Returns (company_col, source_col, join_model_or_none)

    - If company/source exist on Ride, returns them with join_model=None
    - Otherwise tries PayrollBatch (common in this project) and returns join_model=PayrollBatch
    """
    # Try Ride first
    company_col = getattr(Ride, "company_name", None) or getattr(Ride, "company", None)
    source_col = getattr(Ride, "source", None) or getattr(Ride, "import_source", None)

    if company_col is not None or source_col is not None:
        return company_col, source_col, None

    # Try PayrollBatch
    try:
        from backend.db.models import PayrollBatch  # adjust name if different
        company_col = getattr(PayrollBatch, "company_name", None) or getattr(PayrollBatch, "company", None)
        source_col = getattr(PayrollBatch, "source", None) or getattr(PayrollBatch, "import_source", None)

        if company_col is None and source_col is None:
            raise AttributeError(
                "No company/source columns found on Ride or PayrollBatch. "
                "Add your real column names to _company_source_cols()."
            )

        return company_col, source_col, PayrollBatch
    except Exception as e:
        raise AttributeError(
            "No company/source columns found on Ride, and PayrollBatch import failed or lacks columns. "
            "Update _company_source_cols() with your schema."
        ) from e

def _rate_col():
    for name in ["rate", "ride_rate", "pay_rate", "driver_rate"]:
        if hasattr(Ride, name):
            return getattr(Ride, name)
    return None

def _miles_or_units_col():
    for name in ["miles", "trip_miles", "loaded_miles", "units", "quantity"]:
        if hasattr(Ride, name):
            return getattr(Ride, name)
    return None

def _net_expr():
    """
    Temporary safe net expression.
    Returns 0 for each ride until real payroll logic is wired in.
    This prevents crashes and allows UI flow to work.
    """
    return literal(0).label("net_amount"), None




def _ride_date_col():
    """
    Return the Ride date/datetime column used to compute week groupings.
    Tries common names first, then falls back to the first Date/DateTime column found.
    """
    # 1) common names (add yours here if different)
    candidates = [
        "ride_start_ts",
        "ride_date",
        "date",
        "service_date",
        "trip_date",
        "pickup_date",
        "pickup_ts",
        "start_ts",
        "created_at",
    ]

    for name in candidates:
        if hasattr(Ride, name):
            return getattr(Ride, name)

    # 2) fallback: first Date/DateTime-like column in the table
    if hasattr(Ride, "__table__"):
        for col in Ride.__table__.columns:
            # covers Date, DateTime, TIMESTAMP, etc.
            if isinstance(col.type, (sa.Date, sa.DateTime)):
                return col

    raise AttributeError(
        "Could not find a ride date column on Ride. "
        "Add your actual date column name to candidates in _ride_date_col()."
    )

def _parse_date(s: str | None):
    if not s:
        return None
    # Handles "2025-10-20" or "2025-10-20 00:00:00"
    return datetime.fromisoformat(s.replace("Z", "")).date()


def _computed_week_cols_from_date():
    """
    Compute Monday-Friday week range from a ride date in Postgres.
    """
    d = cast(_ride_date_col(), sa.Date)

    dow = func.extract("dow", d)  # 0=Sun .. 6=Sat
    days_since_monday = (dow + 6) % 7  # Mon->0 ... Sun->6

    week_start = (
        d - (cast(days_since_monday, sa.Integer) * sa.literal_column("INTERVAL '1 day'"))
    ).label("week_start")

    week_end = (week_start + sa.literal_column("INTERVAL '4 days'")).label("week_end")
    return week_start, week_end

@router.get("/directory", response_class=HTMLResponse, name="people_directory")
def people_directory(
    request: Request,
    db: Session = Depends(get_db),
    status_filter: str = Query("active"),  # active | dormant | inactive | all
):
    """Driver directory — filterable by status. Defaults to active-only."""
    from sqlalchemy import func as sqlfunc

    ride_stats = (
        db.query(
            Ride.person_id,
            sqlfunc.count(Ride.ride_id).label("ride_count"),
            sqlfunc.max(Ride.ride_start_ts).label("last_active"),
        )
        .group_by(Ride.person_id)
        .subquery()
    )

    latest_batch_subq = (
        db.query(Ride.person_id, PayrollBatch.company_name)
        .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
        .distinct(Ride.person_id)
        .order_by(Ride.person_id, PayrollBatch.uploaded_at.desc())
        .subquery()
    )

    q = db.query(Person).order_by(Person.full_name.asc())
    if status_filter != "all":
        q = q.filter(Person.status == status_filter)

    rows = q.all()

    company_map: dict[int, str] = {}
    for r in db.query(latest_batch_subq.c.person_id, latest_batch_subq.c.company_name).all():
        if r.person_id not in company_map:
            company_map[r.person_id] = r.company_name or ""

    stats_map: dict[int, dict] = {}
    for r in db.query(ride_stats).all():
        stats_map[r.person_id] = {
            "ride_count": int(r.ride_count or 0),
            "last_active": r.last_active,
        }

    # Status counts for tab badges
    status_counts = {
        row.status: row.cnt
        for row in db.query(Person.status, sqlfunc.count(Person.person_id).label("cnt")).group_by(Person.status).all()
    }

    people = []
    for p in rows:
        st = stats_map.get(p.person_id, {})
        people.append({
            "person_id": p.person_id,
            "full_name": p.full_name,
            "email": p.email or "",
            "phone": p.phone or "",
            "notes": p.notes or "",
            "active": p.active if p.active is not None else True,
            "status": p.status or "active",
            "firstalt_driver_id": p.firstalt_driver_id,
            "everdriven_driver_id": p.everdriven_driver_id,
            "company": company_map.get(p.person_id, ""),
            "ride_count": st.get("ride_count", 0),
            "last_active": st.get("last_active"),
            "vehicle_make": p.vehicle_make or "",
            "vehicle_model": p.vehicle_model or "",
            "vehicle_year": p.vehicle_year or "",
            "vehicle_plate": p.vehicle_plate or "",
            "vehicle_color": p.vehicle_color or "",
        })

    return templates().TemplateResponse(
        request,
        "people_list.html",
        {
            "people": people,
            "status_filter": status_filter,
            "status_counts": status_counts,
        },
    )


@router.get("/", response_class=HTMLResponse)
def people_page(
    request: Request,
    db: Session = Depends(get_db),
    company: str | None = Query(None),
    batch_id: int | None = Query(None),
    week_start: date | None = Query(None),
    week_end: date | None = Query(None),
    person_id: int | None = Query(None),
):
    _wants_json = (
        "application/json" in request.headers.get("content-type", "")
        or "application/json" in request.headers.get("accept", "")
    )

    if _wants_json:
        try:
            from sqlalchemy import func as sqlfunc
            ride_stats = (
                db.query(
                    Ride.person_id,
                    sqlfunc.count(Ride.ride_id).label("ride_count"),
                    sqlfunc.max(Ride.ride_start_ts).label("last_active"),
                )
                .group_by(Ride.person_id)
                .subquery()
            )
            stats_map: dict = {}
            for r in db.query(ride_stats).all():
                stats_map[r.person_id] = {
                    "ride_count": int(r.ride_count or 0),
                    "last_active": r.last_active,
                }

            status_param = request.query_params.get("status", "active")
            q = db.query(Person).order_by(Person.full_name.asc())
            if status_param != "all":
                q = q.filter(Person.status == status_param)
            rows = q.all()
            drivers = []
            for p in rows:
                st = stats_map.get(p.person_id, {})
                has_fa = bool(p.firstalt_driver_id)
                has_ed = bool(p.everdriven_driver_id)
                if has_fa and has_ed:
                    company_val = "Both"
                elif has_fa:
                    company_val = "FirstAlt"
                elif has_ed:
                    company_val = "EverDriven"
                else:
                    company_val = "Unknown"
                last_active = st.get("last_active")
                drivers.append({
                    "id": p.person_id,
                    "name": p.full_name or "",
                    "company": company_val,
                    "fa_id": str(p.firstalt_driver_id) if p.firstalt_driver_id else None,
                    "ed_id": str(p.everdriven_driver_id) if p.everdriven_driver_id else None,
                    "phone": p.phone or "",
                    "email": p.email or "",
                    "notes": p.notes or "",
                    "rides": st.get("ride_count", 0),
                    "last_active": last_active.isoformat() if last_active and hasattr(last_active, "isoformat") else (str(last_active) if last_active else None),
                    "active": p.active if p.active is not None else True,
                    "status": p.status or "active",
                })
            return JSONResponse(drivers)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    # -----------------------
    # Step 0: companies
    # -----------------------
    if not company:
        companies = (
            db.query(PayrollBatch.company_name)
            .distinct()
            .order_by(PayrollBatch.company_name.asc())
            .all()
        )
        companies = [c[0] for c in companies]
        return templates().TemplateResponse(
            request,
            "people_companies.html",
            {"companies": companies},
        )

    # -----------------------
    # Step 0.5: batches
    # -----------------------
    if company and not batch_id:
        batches = (
            db.query(PayrollBatch)
            .filter(PayrollBatch.company_name == company)
            .order_by(PayrollBatch.payroll_batch_id.desc())
            .all()
        )
        return templates().TemplateResponse(
            request,
            "people_batches.html",
            {"company": company, "batches": batches},
        )

    # We have company + batch_id from here onward
    bid = int(batch_id)

    # -----------------------
    # Step 1: weeks for batch  ✅ (this was missing and caused the blank page)
    # -----------------------
    if not week_start or not week_end:
        ws_col, we_col, join_model = _week_cols(db)

        q = db.query(
            ws_col.label("week_start"),
            we_col.label("week_end"),
            func.count(Ride.ride_id).label("ride_count"),
            func.count(sa.distinct(Ride.person_id)).label("driver_count"),
        ).select_from(Ride)

        # join to PayrollBatch if the week columns come from it
        if join_model is PayrollBatch:
            q = q.join(PayrollBatch, Ride.payroll_batch_id == PayrollBatch.payroll_batch_id)

        q = (
            q.filter(Ride.payroll_batch_id == bid)
             .group_by(ws_col, we_col)
             .order_by(ws_col.desc())
        )

        weeks = [
            {
                "week_start": r.week_start,
                "week_end": r.week_end,
                "ride_count": int(r.ride_count or 0),
                "driver_count": int(r.driver_count or 0),
            }
            for r in q.all()
        ]

        batch = db.query(PayrollBatch).filter(PayrollBatch.payroll_batch_id == bid).first()

        return templates().TemplateResponse(
            request,
            "people_weeks.html",
            {
                "company": company,
                "batch": batch,
                "batch_id": bid,
                "weeks": weeks,
            },
        )

    # -----------------------
    # Step 2 (optional): people for selected week
    # If you already have this template, keep it; otherwise you can remove this block.
    # -----------------------
    if week_start and week_end and not person_id:
        ride_ts = _ride_date_col()  # uses your helper to pick a real date/datetime col
        start_dt = datetime.combine(week_start, datetime.min.time())
        end_dt = datetime.combine(week_end, datetime.max.time())

        rows = (
            db.query(
                Person.person_id.label("person_id"),
                (getattr(Person, "display_name", None) or getattr(Person, "full_name", None) or Person.name).label("name"),
                Person.email.label("email"),
                Person.firstalt_driver_id.label("firstalt_driver_id"),
                Person.everdriven_driver_id.label("everdriven_driver_id"),
                func.count(Ride.ride_id).label("ride_count"),
                func.coalesce(func.sum(Ride.z_rate), 0).label("total_net_pay"),
            )
            .join(Ride, Ride.person_id == Person.person_id)
            .filter(
                Ride.payroll_batch_id == bid,
                ride_ts >= start_dt,
                ride_ts <= end_dt,
            )
            .group_by(Person.person_id, "name", Person.email, Person.firstalt_driver_id, Person.everdriven_driver_id)
            .order_by(func.coalesce(func.sum(Ride.z_rate), 0).desc())
            .all()
        )

        # Build a set of withheld person_ids for this batch from driver_balance
        withheld_ids = {
            b.person_id
            for b in db.query(DriverBalance)
            .filter(DriverBalance.payroll_batch_id == bid)
            .all()
        }

        people = [
            {
                "person_id": r.person_id,
                "name": r.name,
                "email": r.email or "",
                "firstalt_driver_id": r.firstalt_driver_id,
                "everdriven_driver_id": r.everdriven_driver_id,
                "ride_count": int(r.ride_count or 0),
                "total_net_pay": float(r.total_net_pay or 0),
                "withheld": r.person_id in withheld_ids,
            }
            for r in rows
        ]

        batch = db.query(PayrollBatch).filter(PayrollBatch.payroll_batch_id == bid).first()
        people = sorted(people, key=lambda p: (p.get("name") or "").lower())

        return templates().TemplateResponse(
            request,
            "people_week_people.html",
            {
                "company": company,
                "batch": batch,
                "batch_id": bid,
                "week_start": week_start,
                "week_end": week_end,
                "people": people,
                "params": request.query_params,
            },
        )

    # -----------------------
    # Step 3: rides for person + week  ✅
    # -----------------------
    ride_ts = _ride_date_col()
    start_dt = datetime.combine(week_start, datetime.min.time())
    end_dt = datetime.combine(week_end, datetime.max.time())

    batch = db.query(PayrollBatch).filter(PayrollBatch.payroll_batch_id == bid).first()
    person = db.query(Person).filter(Person.person_id == int(person_id)).first()

    rides = (
        db.query(Ride)
        .filter(
            Ride.payroll_batch_id == bid,
            Ride.person_id == int(person_id),
            ride_ts >= start_dt,
            ride_ts <= end_dt,
        )
        .order_by(ride_ts.asc(), Ride.ride_id.asc())
        .all()
    )
    total_net = sum((r.z_rate or Decimal("0")) for r in rides)

    # Check withheld status for this driver in this batch
    driver_balance_record = (
        db.query(DriverBalance)
        .filter(
            DriverBalance.person_id == int(person_id),
            DriverBalance.payroll_batch_id == bid,
        )
        .first()
    )
    withheld = driver_balance_record is not None

    return templates().TemplateResponse(
        request,
        "people_person_rides.html",
        {
            "company": company,
            "batch": batch,
            "person": person,
            "week_start": week_start,
            "week_end": week_end,
            "rides": rides,
            "total_net": total_net,
            "withheld": withheld,
        },
    )


@router.get("/{person_id}/paystub", response_class=HTMLResponse, name="person_paystub")
def person_paystub(
    person_id: int,
    request: Request,
    batch_id: int = Query(...),
    db: Session = Depends(get_db),
):
    """Direct pay stub view for a driver in a specific batch — no week-picker needed."""
    person = db.get(Person, person_id)
    if not person:
        return HTMLResponse("<h2>Driver not found</h2>", status_code=404)

    batch = db.query(PayrollBatch).filter(PayrollBatch.payroll_batch_id == batch_id).first()
    if not batch:
        return HTMLResponse("<h2>Batch not found</h2>", status_code=404)

    rides = (
        db.query(Ride)
        .filter(Ride.payroll_batch_id == batch_id, Ride.person_id == person_id)
        .order_by(Ride.ride_start_ts.asc(), Ride.ride_id.asc())
        .all()
    )

    total_net = sum((r.z_rate or Decimal("0")) for r in rides)

    driver_balance = (
        db.query(DriverBalance)
        .filter(DriverBalance.person_id == person_id, DriverBalance.payroll_batch_id == batch_id)
        .first()
    )
    withheld = driver_balance is not None

    week_start = batch.period_start
    week_end = batch.period_end

    return templates().TemplateResponse(
        request,
        "people_person_rides.html",
        {
            "company": batch.company_name,
            "batch": batch,
            "person": person,
            "week_start": week_start,
            "week_end": week_end,
            "rides": rides,
            "total_net": total_net,
            "withheld": withheld,
            "back_url": f"/summary?company={batch.company_name}&batch_id={batch_id}",
        },
    )


@router.post("/set-everdriven-id")
def set_everdriven_id(
    person_id: int = Form(...),
    everdriven_driver_id: str = Form(...),
    redirect_url: str = Form("/people"),
    db: Session = Depends(get_db),
):
    person = db.get(Person, person_id)
    if person:
        val = everdriven_driver_id.strip()
        person.everdriven_driver_id = int(val) if val else None
        db.commit()
    from backend.utils.redirect import safe_redirect
    return RedirectResponse(url=safe_redirect(redirect_url), status_code=303)


@router.post("/set-firstalt-id")
def set_firstalt_id(
    person_id: int = Form(...),
    firstalt_driver_id: str = Form(...),
    redirect_url: str = Form("/people"),
    db: Session = Depends(get_db),
):
    from backend.utils.redirect import safe_redirect
    person = db.get(Person, person_id)
    if person:
        val = firstalt_driver_id.strip()
        person.firstalt_driver_id = int(val) if val else None
        db.commit()
    return RedirectResponse(url=safe_redirect(redirect_url), status_code=303)

@router.post("/{person_id}/set-notes")
def set_notes(
    person_id: int,
    request: Request,
    notes: str = Form(""),
    next: str = Form(None),
    db: Session = Depends(get_db),
):
    from backend.utils.redirect import safe_redirect
    person = db.query(Person).filter(Person.person_id == person_id).first()
    if person:
        person.notes = notes.strip() or None
        db.commit()
    dest = safe_redirect(next or request.headers.get("referer") or "/people")
    return RedirectResponse(url=dest, status_code=303)


@router.post("/{person_id}/update")
def update_person(
    person_id: int,
    email: str = Form(None),
    phone: str = Form(None),
    home_address: str = Form(None),
    paycheck_code: str = Form(None),
    active: str = Form(None),
    vehicle_make: str = Form(None),
    vehicle_model: str = Form(None),
    vehicle_year: str = Form(None),
    vehicle_plate: str = Form(None),
    vehicle_color: str = Form(None),
    redirect_url: str = Form(None),
    db: Session = Depends(get_db),
):
    from fastapi import HTTPException
    person = db.query(Person).filter(Person.person_id == person_id).first()
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    if email is not None:
        person.email = email.strip() or None
    if phone is not None:
        person.phone = phone.strip() or None
    if home_address is not None:
        person.home_address = home_address.strip() or None
    if paycheck_code is not None:
        person.paycheck_code = paycheck_code.strip() or None
    if active is not None:
        person.active = active.lower() in ("1", "true", "yes", "on")
    if vehicle_make is not None:
        person.vehicle_make = vehicle_make.strip() or None
    if vehicle_model is not None:
        person.vehicle_model = vehicle_model.strip() or None
    if vehicle_year is not None:
        val = vehicle_year.strip()
        person.vehicle_year = int(val) if val.isdigit() else None
    if vehicle_plate is not None:
        person.vehicle_plate = vehicle_plate.strip() or None
    if vehicle_color is not None:
        person.vehicle_color = vehicle_color.strip() or None
    db.commit()
    from backend.utils.redirect import safe_redirect
    dest = safe_redirect(redirect_url or f"/people/{person_id}/rides")
    return RedirectResponse(url=dest, status_code=303)


@router.patch("/{person_id}/update-json")
async def update_person_json(person_id: int, request: Request, db: Session = Depends(get_db)):
    """JSON-based person update for Next.js frontend."""
    from fastapi import HTTPException
    body = await request.json()
    person = db.query(Person).filter(Person.person_id == person_id).first()
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    str_fields = ["email", "phone", "home_address", "paycheck_code", "notes",
                  "vehicle_make", "vehicle_model", "vehicle_plate", "vehicle_color"]
    for f in str_fields:
        if f in body:
            val = body[f]
            setattr(person, f, str(val).strip() or None if val is not None else None)
    if "vehicle_year" in body:
        val = body["vehicle_year"]
        person.vehicle_year = int(val) if val and str(val).strip().isdigit() else None
    if "active" in body:
        person.active = body["active"] in (True, "true", "1", "yes")
        if not person.active and person.status == "active":
            person.status = "inactive"
        elif person.active:
            person.status = "active"
    if "status" in body:
        val = body["status"]
        if val in ("active", "dormant", "inactive"):
            person.status = val
            person.active = val == "active"
    if "firstalt_driver_id" in body:
        val = body["firstalt_driver_id"]
        person.firstalt_driver_id = int(val) if val and str(val).strip().isdigit() else None
    if "everdriven_driver_id" in body:
        val = body["everdriven_driver_id"]
        person.everdriven_driver_id = int(val) if val and str(val).strip().isdigit() else None

    db.commit()
    return JSONResponse({
        "ok": True,
        "person_id": person.person_id,
        "name": person.full_name,
        "email": person.email,
        "phone": person.phone,
        "paycheck_code": person.paycheck_code,
        "notes": person.notes,
        "active": person.active if person.active is not None else True,
        "status": person.status or "active",
    })


@router.post("/{person_id}/toggle-active", name="person_toggle_active")
def person_toggle_active(person_id: int, db: Session = Depends(get_db)):
    person = db.query(Person).filter(Person.person_id == person_id).first()
    if not person:
        return JSONResponse({"error": "Not found"}, status_code=404)
    person.active = not person.active
    db.commit()
    return JSONResponse({"ok": True, "person_id": person_id, "active": person.active})


@router.post("/sync-firstalt-profiles")
def sync_firstalt_profiles(db: Session = Depends(get_db)):
    """Pull phone, address, and vehicle info from FirstAlt for all active drivers."""
    from backend.services.firstalt_service import get_driver_profile

    drivers = db.query(Person).filter(
        Person.active == True,
        Person.firstalt_driver_id.isnot(None),
    ).all()

    updated, skipped, errors = 0, 0, 0
    for p in drivers:
        try:
            profile = get_driver_profile(p.firstalt_driver_id)
            driver = profile.get("driver", profile)

            phone = (driver.get("phoneNumber") or driver.get("phone") or "").strip() or None
            addr_parts = [
                driver.get("address1", ""), driver.get("address2", ""),
                driver.get("city", ""), driver.get("state", ""), driver.get("zip", "")
            ]
            address = ", ".join(x for x in addr_parts if x).strip() or None

            vehicles = driver.get("vehicles") or []
            vehicle = vehicles[0] if vehicles else {}
            make  = (vehicle.get("make") or "").strip() or None
            model = (vehicle.get("model") or "").strip() or None
            year  = vehicle.get("year") or None
            plate = (vehicle.get("licensePlate") or "").strip() or None
            color = (vehicle.get("color") or "").strip() or None

            if not any([phone, address, make, model, year, plate, color]):
                skipped += 1
                continue

            if phone and not p.phone: p.phone = phone
            if address and not p.home_address: p.home_address = address
            if make and not p.vehicle_make: p.vehicle_make = make
            if model and not p.vehicle_model: p.vehicle_model = model
            if year and not p.vehicle_year: p.vehicle_year = year
            if plate and not p.vehicle_plate: p.vehicle_plate = plate
            if color and not p.vehicle_color: p.vehicle_color = color
            updated += 1
        except Exception:
            errors += 1

    db.commit()
    return {"updated": updated, "skipped": skipped, "errors": errors}


@router.post("/create")
async def create_person(request: Request, db: Session = Depends(get_db)):
    """Create a new driver."""
    body = await request.json()
    name = body.get("full_name", "").strip()
    if not name:
        return JSONResponse({"error": "full_name is required"}, status_code=400)

    person = Person(
        full_name=name,
        email=body.get("email", "").strip() or None,
        phone=body.get("phone", "").strip() or None,
        paycheck_code=body.get("paycheck_code", "").strip() or None,
        notes=body.get("notes", "").strip() or None,
        home_address=body.get("home_address", "").strip() or None,
        firstalt_driver_id=int(body["firstalt_driver_id"]) if body.get("firstalt_driver_id") else None,
        everdriven_driver_id=int(body["everdriven_driver_id"]) if body.get("everdriven_driver_id") else None,
        vehicle_make=body.get("vehicle_make", "").strip() or None,
        vehicle_model=body.get("vehicle_model", "").strip() or None,
        vehicle_year=int(body["vehicle_year"]) if body.get("vehicle_year") and str(body["vehicle_year"]).strip().isdigit() else None,
        vehicle_plate=body.get("vehicle_plate", "").strip() or None,
        vehicle_color=body.get("vehicle_color", "").strip() or None,
        active=True,
    )
    db.add(person)
    db.commit()
    db.refresh(person)
    return JSONResponse({"ok": True, "person_id": person.person_id, "name": person.full_name, "active": True}, status_code=201)
