# backend/routes/people.py
import sqlalchemy as sa

from pathlib import Path
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
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
    return RedirectResponse(url=redirect_url, status_code=303)


@router.post("/set-firstalt-id")
def set_firstalt_id(
    person_id: int = Form(...),
    firstalt_driver_id: str = Form(...),
    redirect_url: str = Form("/people"),
    db: Session = Depends(get_db),
):
    person = db.get(Person, person_id)
    if person:
        val = firstalt_driver_id.strip()
        person.firstalt_driver_id = int(val) if val else None
        db.commit()
    return RedirectResponse(url=redirect_url, status_code=303)

@router.post("/{person_id}/update")
def update_person(
    person_id: int,
    email: str = Form(None),
    phone: str = Form(None),
    home_address: str = Form(None),
    paycheck_code: str = Form(None),
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
    db.commit()
    dest = redirect_url or f"/people/{person_id}"
    return RedirectResponse(url=dest, status_code=303)
