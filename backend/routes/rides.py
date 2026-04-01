# backend/routes/rides.py
import re
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from fastapi import APIRouter, Depends, Request, Query, Form
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import Any
from datetime import datetime, date
from decimal import Decimal


from backend.db import get_db
from backend.db.models import Ride, Person, PayrollBatch  # ✅ add PayrollBatch

router = APIRouter(prefix="/rides", tags=["rides"])


_templates = None
def templates():
    global _templates
    if _templates is None:
        templates_dir = Path(__file__).resolve().parents[1] / "templates"
        _templates = Jinja2Templates(directory=str(templates_dir))
    return _templates

def _fmt_date(d: Any) -> str:
    if d is None:
        return ""
    if isinstance(d, (datetime, date)):
        return d.strftime("%m/%d/%Y")
    s = str(d)
    return s[:10]

def _build_payweek(rows: list[dict[str, Any]]) -> str:
    # Prefer explicit "week" from your dataset
    for r in rows:
        w = (r.get("week") or "").strip()
        if w:
            return w

    # Fallback: derive from min/max date in rows
    ds = []
    for r in rows:
        d = r.get("date_raw")
        if isinstance(d, datetime):
            ds.append(d.date())
        elif isinstance(d, date):
            ds.append(d)
    if ds:
        lo, hi = min(ds), max(ds)
        return f"{lo.strftime('%m/%d/%Y')} - {hi.strftime('%m/%d/%Y')}"
    return "payweek"

def _safe_slug(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^\w\-]+", "_", s)
    return re.sub(r"_+", "_", s).strip("_")

def _build_rides_rows(db, person_id: int | None) -> tuple[list[dict[str, Any]], float, str]:
    # IMPORTANT: Use the SAME query basis as your HTML page.
    # If your HTML page already does joins, move that same query here.
    date_col = _ride_date_col()
    q = (
        db.query(
            Ride.ride_id.label("ride_id"),
            Ride.person_id.label("person_id"),
            date_col.label("ride_start_ts"),
            Ride.service_ref.label("service_ref"),
            Ride.service_ref_type.label("service_ref_type"),
            Ride.service_name.label("service_name"),
            Ride.miles.label("miles"),
            Ride.gross_pay.label("gross_pay"),
            Ride.net_pay.label("net_pay"),
            Ride.deduction.label("deduction"),
            Ride.spiff.label("spiff"),
            Ride.z_rate.label("z_rate"),
            Ride.z_rate_source.label("z_rate_source"),
            Ride.source_ref.label("source_ref"),
            Person.full_name.label("driver_name"),
            PayrollBatch.company_name.label("company_name"),
            PayrollBatch.week_start.label("week_start"),
            PayrollBatch.week_end.label("week_end"),
            PayrollBatch.batch_ref.label("batch_ref"),
        )
        .join(Person, Person.person_id == Ride.person_id)
        .outerjoin(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
    )
    if person_id is not None:
        q = q.filter(Ride.person_id == person_id)

    
    rows_raw = (
        q.order_by(date_col.asc().nullslast(), Ride.ride_id.asc())
         .limit(2000)
         .all()
    )
    rows: list[dict[str, Any]] = []
    total_net = 0.0

    for r in rows_raw:
        dt = r.ride_start_ts
        total_net += float(r.z_rate or 0)

        service_code = r.service_ref if (r.service_ref_type or "").upper() == "CODE" else ""
        service_key  = r.service_ref if (r.service_ref_type or "").upper() == "KEY" else ""

        rows.append({
            "ride_id": r.ride_id,
            "person_id": r.person_id,
            "date": dt.strftime("%m/%d/%Y") if dt else "",
            "date_raw": dt,
            "driver": r.driver_name or "",
            "company": r.company_name or "",
            "week": f"{r.week_start.strftime('%m/%d/%Y')} - {r.week_end.strftime('%m/%d/%Y')}" if (r.week_start and r.week_end) else "",
            "service_code": service_code,
            "service_key": service_key,
            "service_name": r.service_name or "",
            "miles": float(r.miles or 0),
            "rate": float(r.z_rate or 0),   # or change to whatever “rate” means in your UI
            "net": float(r.z_rate  or 0),

            # aliases so rides.html can use old names too
            "driver_name": r.driver_name or "",
            "company_name": r.company_name or "",
            "week_start": r.week_start.strftime("%m/%d/%Y") if r.week_start else "",
            "week_end": r.week_end.strftime("%m/%d/%Y") if r.week_end else "",
            "gross_pay": float(r.gross_pay or 0),
            "net_pay": float(r.net_pay or 0),
            "deduction": float(r.deduction or 0),
            "spiff": float(r.spiff or 0),
            "z_rate": float(r.z_rate or 0),
            "z_rate_source": r.z_rate_source or "",
            "source_ref": r.source_ref or "",
            "batch_ref": r.batch_ref or "",
        })

    payweek = _build_payweek(rows)
    return rows, total_net, payweek


def _ride_date_col():
    if hasattr(Ride, "ride_start_ts") and hasattr(Ride, "ride_start_ts"):
        return func.coalesce(Ride.ride_start_ts, Ride.ride_start_ts)

    if hasattr(Ride, "ride_start_ts"):
        return Ride.ride_start_ts
    if hasattr(Ride, "ride_start_ts"):
        return Ride.ride_start_ts

    raise AttributeError("Ride model has neither ride_date_ts ")

def _apply_person_filter(q, person_id: int):
    # Try common FK column names (adjust/add yours if needed)
    if hasattr(Ride, "person_id"):
        return q.filter(Ride.person_id == person_id)
    if hasattr(Ride, "driver_person_id"):
        return q.filter(Ride.driver_person_id == person_id)
    if hasattr(Ride, "person_fk"):
        return q.filter(Ride.person_fk == person_id)

    # If none match, fail loudly so you notice immediately
    raise AttributeError(
        "Ride model has no known person FK column (expected one of: person_id, driver_person_id, person_fk)"
    )

def format_miles(m):
    if m is None:
        return ""
    if isinstance(m, Decimal):
        # Remove trailing zeros (32.000 -> 32)
        m = m.normalize()
        # Avoid scientific notation
        return format(m, "f").rstrip("0").rstrip(".") or "0"
    # fallback for floats/ints
    s = str(m)
    return s.rstrip("0").rstrip(".")

@router.get("/", response_class=HTMLResponse)
def rides_page(
    request: Request,
    db: Session = Depends(get_db),
    person_id: int = Query(...),
    week_start: date | None = Query(None),
    week_end: date | None = Query(None),
    source: str | None = Query(None),
    company: str | None = Query(None),
):
    date_col = _ride_date_col()

    # columns (make tolerant)
    company_col = getattr(Ride, "company_name", None) or getattr(Ride, "company", None)
    source_col = getattr(Ride, "source", None) or getattr(Ride, "import_source", None)
    ws_col = getattr(Ride, "week_start", None)
    we_col = getattr(Ride, "week_end", None)

    rate_col = getattr(Ride, "rate", None) or getattr(Ride, "ride_rate", None)
    net_col = getattr(Ride, "net", None) or getattr(Ride, "net_amount", None)
    miles_col = getattr(Ride, "miles", None)

    person = db.query(Person).filter(Person.person_id == person_id).first()

    q = db.query(Ride).filter(Ride.person_id == person_id)

    if ws_col is not None and we_col is not None and week_start and week_end:
        q = q.filter(ws_col == week_start, we_col == week_end)
    if company_col is not None and company:
        q = q.filter(company_col == company)
    if source_col is not None and source:
        q = q.filter(source_col == source)

    rides = q.order_by(date_col.asc()).all()

    return templates().TemplateResponse(
        request,
        "rides_detail.html",
        {
            "person": person,
            "rides": rides,
            "week_start": week_start,
            "week_end": week_end,
            "source": source,
            "company": company,
            "date_col_name": date_col.key,
            "rate_col_name": rate_col.key if rate_col is not None else None,
            "net_col_name": net_col.key if net_col is not None else None,
            "miles_col_name": miles_col.key if miles_col is not None else None,
        },
    )

@router.post("/update")  # if your router already has prefix="/rides"
async def rides_update(request: Request, db: Session = Depends(get_db)):
    form = await request.form()

    company = form.get("company")
    batch_id = form.get("batch_id")
    person_id = form.get("person_id")
    week_start = form.get("week_start")
    week_end = form.get("week_end")

    updates = {}

    for k, v in form.items():
        if v is None or str(v).strip() == "":
            continue

        if k.startswith("rate_"):
            ride_id = int(k.split("_", 1)[1])
            updates.setdefault(ride_id, {})["z_rate"] = Decimal(v)

        elif k.startswith("deduction_"):
            ride_id = int(k.split("_", 1)[1])
            updates.setdefault(ride_id, {})["deduction"] = Decimal(v)

    for ride_id, fields in updates.items():
        ride = db.get(Ride, ride_id)
        if not ride:
            continue

        z_rate = fields.get("z_rate", ride.z_rate or Decimal("0"))
        deduction = fields.get("deduction", ride.deduction or Decimal("0"))

        # Only update z_rate — never overwrite gross_pay (that is the partner's billing amount)
        ride.z_rate = z_rate
        ride.deduction = deduction
        # net_pay reflects what the driver is owed after deductions
        ride.net_pay = (ride.gross_pay or Decimal("0")) - deduction

    db.commit()

    return RedirectResponse(
        url=(
            f"/people/?company={company}"
            f"&batch_id={batch_id}"
            f"&week_start={week_start}"
            f"&week_end={week_end}"
            f"&person_id={person_id}"
        ),
        status_code=303,
    )

@router.get("/data", response_class=JSONResponse, name="rides_data")
def rides_data(
    person_id: int | None = Query(None),
    limit: int = Query(500, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    date_col = _ride_date_col()
    
    q = (
        db.query(
            Ride.ride_id.label("ride_id"),
            Ride.person_id.label("person_id"),
            date_col.label("ride_date_ts"),
            Ride.service_ref.label("service_ref"),
            Ride.service_ref_type.label("service_ref_type"),
            Ride.service_name.label("service_name"),
            (Ride.miles).label("miles"),
            Ride.gross_pay.label("gross_pay"),
            Ride.net_pay.label("net_pay"),
            Ride.z_rate.label("z_rate"),
            Ride.z_rate_source.label("z_rate_source"),
        )
    )

    if person_id is not None:
        q = q.filter(Ride.person_id == person_id)

    rows = (
        q.order_by(date_col.asc().nullslast(), Ride.ride_id.asc())
         .limit(2000)
         .all()
    )

    return {
        "ok": True,
        "rows": [
            {
                "ride_id": r.ride_id,
                "person_id": r.person_id,
                "ride_date_ts": r.ride_date_ts.isoformat() if r.ride_date_ts else None,
                "service_ref": r.service_ref,
                "service_ref_type": r.service_ref_type,
                "service_name": r.service_name,
                "miles": float(r.miles or 0),
                "gross_pay": float(r.gross_pay or 0),
                "net_pay": float(r.net_pay or 0),
                "z_rate": float(r.z_rate or 0),
                "z_rate_source": r.z_rate_source,
            }
            for r in rows
        ],
    }

@router.post("/{z_rate_id}/update")
def update_rate(
    request: Request,
    z_rate_id: int,
    net: float = Form(...),   # value from the input box
    db: Session = Depends(get_db),
):
    zr = db.get(ZRate, z_rate_id)
    if not zr:
        return RedirectResponse(url="/rates?error=Rate not found", status_code=303)

    zr.net = net
    db.commit()  # commit() flushes changes before COMMIT
    return RedirectResponse(url="/rates?success=Saved", status_code=303)


OUT_DIR = Path("/data/out")  # container path; mapped to ./data/out on host


def _safe_slug(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "unknown"


@router.get("/pdf")
def rides_pdf(
    request: Request,
    company: str = Query(...),
    person_id: int = Query(...),
    db: Session = Depends(get_db),
):
    # 1) Fetch person name
    person = db.get(Person, person_id)
    full_name = (person.full_name if person else "unknown unknown").strip()
    parts = [p for p in full_name.split() if p]
    first = parts[0] if parts else "unknown"
    last = parts[-1] if len(parts) > 1 else "unknown"

    # 2) Use the SAME rows as the rides page
    rows, _total_net_unused, payweek = _build_rides_rows(db=db, person_id=person_id)

    # 3) Determine payweek label (fallback)
    if not payweek:
        if rows:
            payweek = (rows[0].get("week") or rows[0].get("week_label") or "payweek")
        else:
            payweek = "payweek"

    payweek_slug = _safe_slug(payweek)
    driver_slug = _safe_slug(full_name)

    out_dir = OUT_DIR / payweek_slug
    out_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = out_dir / f"{driver_slug}.pdf"

    # 4) Create PDF
    c = canvas.Canvas(str(pdf_path), pagesize=letter)
    width, height = letter

    COMPANY_COLORS = {
        "Acumen International": (0.55, 0.15, 0.15),   # Dark red
        "everDriven": (0.18, 0.24, 0.60),             # deep indigo
    }
    # ===== Company Header =====
    HEADER_HEIGHT = 48

    # Default color if company not listed
    header_color = COMPANY_COLORS.get(company, (0.15, 0.15, 0.15))

    c.setFillColorRGB(*header_color)   # ✅ unpack tuple into r,g,b
    c.rect(0, height - HEADER_HEIGHT, width, HEADER_HEIGHT, stroke=0, fill=1)

    c.setFillColorRGB(1, 1, 1)  # white text
    c.setFont("Helvetica-Bold", 18)
    c.drawString(40, height - HEADER_HEIGHT + 14, company)

    # Reset text color for rest of document
    c.setFillColorRGB(0, 0, 0)

    y = height - HEADER_HEIGHT - 30
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, f"Rides Report: {full_name}")
    y -= 18

    c.setFont("Helvetica", 11)
    c.drawString(50, y, f"Payweek: {payweek}")
    y -= 25

    # Table header
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "Date")
    c.drawString(130, y, "Service")
    c.drawRightString(380, y, "Miles")
    c.drawRightString(450, y, "Rate")
    c.drawRightString(520, y, "Deduct")
    c.drawRightString(580, y, "Net")
    y -= 14
    c.line(50, y, 580, y)
    y -= 14

    printed_total = Decimal("0")
    c.setFont("Helvetica", 10)

    for r in rows:
        if y < 80:
            c.showPage()
            y = height - 50
            c.setFont("Helvetica", 10)

        date_str = str(r.get("date") or "")
        service = str(r.get("service_name") or "")[:42]

        # Keep miles numeric; print as integer (no decimals)
        miles_val = r.get("miles") or 0
        try:
            miles_num = float(miles_val)
        except Exception:
            miles_num = 0.0

        # rate + deduction from rows
        rate = Decimal(str(r.get("rate") or "0"))
        deduction = Decimal(str(r.get("deduction") or "0"))

        # ✅ New rule: gross=rate, net=rate-deduction
        net = rate - deduction
        printed_total += net

        c.drawString(50, y, date_str)
        c.drawString(130, y, service)
        c.drawRightString(380, y, f"{miles_num:.0f}")
        c.drawRightString(450, y, f"{rate:.2f}")
        c.drawRightString(520, y, f"{deduction:.2f}")
        c.drawRightString(580, y, f"{net:.2f}")
        y -= 14

    y -= 10
    c.line(50, y, 580, y)
    y -= 16
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(580, y, f"Total Net: {printed_total:.2f}")

    c.save()

    # ✅ Fix filename f-string
    return FileResponse(
        str(pdf_path),
        media_type="application/pdf",
        filename=f"{driver_slug}.pdf",
    )
