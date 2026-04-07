import csv
import io
from io import BytesIO
from pathlib import Path
from datetime import date, datetime

from fastapi import APIRouter, Depends, Form, Request, Query
from fastapi.responses import StreamingResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, cast, Date
from sqlalchemy.orm import Session
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from backend.db import get_db
from backend.db.models import Person, Ride, PayrollBatch, DriverBalance

router = APIRouter(prefix="/summary", tags=["summary"])

_templates = None
def templates():
    global _templates
    if _templates is None:
        templates_dir = Path(__file__).resolve().parents[1] / "templates"
        _templates = Jinja2Templates(directory=str(templates_dir))
    return _templates


COLUMNS = ["Driver", "Code", "Active Between", "Days", "Net Pay", "From Last Period", "Pay This Period"]


def _get_companies(db: Session) -> list[str]:
    rows = (
        db.query(PayrollBatch.company_name)
        .distinct()
        .order_by(PayrollBatch.company_name.asc())
        .all()
    )
    return [r[0] for r in rows]


PAY_THRESHOLD = 100.0


def _build_summary(
    db: Session,
    company: str | None = None,
    batch_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
    auto_save: bool = False,
    override_ids: set[int] | None = None,
) -> dict:
    """
    Returns rows + totals for the summary page.

    When batch_id is provided:
    - Looks up the previous batch for the same company
    - Reads driver_balance for that previous batch as "from_last_period"
    - combined = net_pay + from_last_period
    - If combined < $100 → withheld; auto-saves combined to driver_balance for this batch
    - If combined >= $100 → driver gets paid; clears any driver_balance record for this batch
    """
    ride_date = func.coalesce(
        cast(Ride.ride_start_ts, Date),
    )

    q = (
        db.query(
            Person.person_id.label("person_id"),
            Person.full_name.label("person"),
            Person.external_id.label("code"),
            func.min(ride_date).label("first_date"),
            func.max(ride_date).label("last_date"),
            func.count(func.distinct(ride_date)).label("days"),
            func.coalesce(func.sum(Ride.net_pay), 0).label("gross_earned"),
            func.coalesce(func.sum(Ride.deduction), 0).label("total_deduction"),
            func.coalesce(func.sum(Ride.z_rate), 0).label("z_rate_total"),
        )
        .join(Ride, Ride.person_id == Person.person_id)
        .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
    )

    if company:
        q = q.filter(PayrollBatch.company_name == company)
    if batch_id:
        q = q.filter(PayrollBatch.payroll_batch_id == batch_id)
    if start:
        q = q.filter(ride_date >= start)
    if end:
        q = q.filter(ride_date <= end)

    q = q.group_by(Person.person_id, Person.full_name, Person.external_id)
    q = q.order_by(Person.full_name.asc())

    rows_raw = q.all()

    # ── Carried-over amounts from previous batch ───────────────────────────────
    carried_map: dict[int, float] = {}
    if batch_id:
        current_batch = db.query(PayrollBatch).filter(
            PayrollBatch.payroll_batch_id == batch_id
        ).first()
        if current_batch:
            prev_batch = (
                db.query(PayrollBatch)
                .filter(
                    PayrollBatch.company_name == current_batch.company_name,
                    PayrollBatch.period_start < current_batch.period_start,
                )
                .order_by(PayrollBatch.period_start.desc())
                .first()
            )
            if prev_batch:
                prev_balances = (
                    db.query(DriverBalance)
                    .filter(DriverBalance.payroll_batch_id == prev_batch.payroll_batch_id)
                    .all()
                )
                carried_map = {b.person_id: round(float(b.carried_over or 0), 2) for b in prev_balances}

    def fmt(d):
        return d.strftime("%-m/%-d/%Y") if d else ""

    rows = []
    total_days = 0
    total_net = 0.0
    total_pay = 0.0

    for r in rows_raw:
        # net_pay = what the partner says the driver earned, minus deductions
        gross_earned = round(float(r.gross_earned or 0), 2)
        total_deduction = round(float(r.total_deduction or 0), 2)
        net = round(gross_earned - total_deduction, 2)
        days = int(r.days or 0)
        active = f"{fmt(r.first_date)} – {fmt(r.last_date)}" if r.first_date else ""
        from_last = carried_map.get(r.person_id, 0.0)
        combined = round(net + from_last, 2)
        withheld = combined < PAY_THRESHOLD
        if override_ids and r.person_id in override_ids:
            withheld = False  # force pay regardless of threshold
        pay_this_period = 0.0 if withheld else combined

        rows.append({
            "person_id": r.person_id,
            "person": r.person or "",
            "code": r.code or "",
            "active_between": active,
            "days": days,
            "net_pay": net,
            "from_last_period": from_last,
            "pay_this_period": pay_this_period,
            "withheld": withheld,
            "withheld_amount": combined if withheld else 0.0,
        })
        total_days += days
        total_net += net
        total_pay += pay_this_period

    totals = {
        "days": total_days,
        "net_pay": round(total_net, 2),
        "pay_this_period": round(total_pay, 2),
    }

    # ── Auto-save withheld balances for the current batch ─────────────────────
    if batch_id and auto_save:
        for row in rows:
            existing = (
                db.query(DriverBalance)
                .filter(
                    DriverBalance.person_id == row["person_id"],
                    DriverBalance.payroll_batch_id == batch_id,
                )
                .first()
            )
            if row["withheld"]:
                # Store the combined withheld amount so the NEXT batch can carry it forward
                if existing:
                    existing.carried_over = row["withheld_amount"]
                else:
                    db.add(DriverBalance(
                        person_id=row["person_id"],
                        payroll_batch_id=batch_id,
                        carried_over=row["withheld_amount"],
                    ))
            else:
                # Driver is being paid this period — clear any stale balance record
                if existing:
                    db.delete(existing)
        db.commit()

    return {"rows": rows, "totals": totals}


# ── Summary page ──────────────────────────────────────────────────────────────

@router.get("/", name="summary_page")
def summary_page(
    request: Request,
    company: str | None = Query(None),
    batch_id: int | None = Query(None),
    start: date | None = Query(None),
    end: date | None = Query(None),
    db: Session = Depends(get_db),
):
    _wants_json = (
        "application/json" in request.headers.get("content-type", "")
        or "application/json" in request.headers.get("accept", "")
    )

    companies = _get_companies(db)

    # Default to first company if none selected
    selected_company = company or (companies[0] if companies else None)

    # Batches for the selected company
    batches = []
    if selected_company:
        batches = (
            db.query(PayrollBatch)
            .filter(PayrollBatch.company_name == selected_company)
            .order_by(PayrollBatch.period_start.desc())
            .all()
        )

    # GET is always read-only — never auto-save on page load
    data = _build_summary(db, company=selected_company, batch_id=batch_id, start=start, end=end, auto_save=False)

    if _wants_json:
        try:
            rows = data["rows"]
            totals = data["totals"]
            periods = [
                f"{b.period_start.strftime('%-m/%-d/%Y') if b.period_start else ''} - {b.period_end.strftime('%-m/%-d/%Y') if b.period_end else ''}"
                for b in batches
            ]
            drivers_out = []
            withheld_out = []
            for r in rows:
                entry = {
                    "id": r["person_id"],
                    "name": r["person"],
                    "pay_code": r["code"],
                    "days": r["days"],
                    "net_pay": r["net_pay"],
                    "carried_over": r["from_last_period"],
                    "pay_this_period": r["pay_this_period"],
                    "status": "withheld" if r["withheld"] else "paid",
                    "override": False,
                    "withheld": r["withheld_amount"],
                }
                if r["withheld"]:
                    withheld_out.append(entry)
                else:
                    drivers_out.append(entry)
            total_withheld = sum(r["withheld_amount"] for r in rows if r["withheld"])
            return JSONResponse({
                "company": selected_company,
                "period": f"{start} - {end}" if start or end else None,
                "periods": periods,
                "drivers": drivers_out,
                "withheld": withheld_out,
                "stats": {
                    "driver_count": len(rows),
                    "total_pay": totals["pay_this_period"],
                    "withheld_amount": round(total_withheld, 2),
                },
            })
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    return templates().TemplateResponse(
        request,
        "summary.html",
        {
            "rows": data["rows"],
            "totals": data["totals"],
            "companies": companies,
            "selected_company": selected_company,
            "batches": batches,
            "selected_batch_id": batch_id,
            "start": start,
            "end": end,
            "payroll_run": False,
        },
    )


# ── Run Payroll (POST — commits withheld balances) ────────────────────────────

@router.post("/run", name="summary_run")
def summary_run(
    request: Request,
    overrides: str = Form(""),
    company: str | None = Query(None),
    batch_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    """
    Explicitly run payroll for a batch. This is the only place that writes
    DriverBalance records — the GET route is strictly read-only.
    Must have a batch_id to commit withheld balances.

    overrides: comma-separated person_id values for drivers who should be
    force-paid this period regardless of the $100 threshold.
    """
    override_ids = set(int(x) for x in overrides.split(",") if x.strip().isdigit())

    if not batch_id:
        # No batch selected — redirect back with an error flag
        redirect = f"/summary/?company={company}" if company else "/summary/"
        return RedirectResponse(url=redirect + "&error=no_batch", status_code=303)

    companies = _get_companies(db)
    selected_company = company or (companies[0] if companies else None)

    # Run with auto_save=True to commit balances
    _build_summary(db, company=selected_company, batch_id=batch_id, auto_save=True, override_ids=override_ids)

    redirect = f"/summary/?company={company}&batch_id={batch_id}&ran=1" if company else f"/summary/?batch_id={batch_id}&ran=1"
    return RedirectResponse(url=redirect, status_code=303)


# ── Excel export ──────────────────────────────────────────────────────────────

@router.get("/export/excel")
def summary_excel(
    company: str | None = Query(None),
    batch_id: int | None = Query(None),
    start: date | None = Query(None),
    end: date | None = Query(None),
    db: Session = Depends(get_db),
):
    data = _build_summary(db, company=company, batch_id=batch_id, start=start, end=end)
    rows = data["rows"]
    totals = data["totals"]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Payroll Summary"

    header_fill = PatternFill("solid", fgColor="0F1729")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    center = Alignment(horizontal="center", vertical="center")
    right = Alignment(horizontal="right", vertical="center")
    left = Alignment(horizontal="left", vertical="center")
    money_fmt = '"$"#,##0.00'

    # Title row
    ws.merge_cells("A1:G1")
    title_cell = ws["A1"]
    title_cell.value = f"{company or 'All Companies'} — Payroll Summary"
    title_cell.font = Font(bold=True, size=13, color="0F1729")
    title_cell.alignment = left
    ws.row_dimensions[1].height = 22

    if start or end:
        ws.merge_cells("A2:G2")
        ws["A2"].value = f"Period: {start or '—'} to {end or '—'}"
        ws["A2"].font = Font(size=10, color="666666")
        ws.row_dimensions[2].height = 16
        header_row = 3
    else:
        header_row = 2

    # Header
    for col_idx, col_name in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=header_row, column=col_idx, value=col_name)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = right if col_idx >= 4 else center
        ws.row_dimensions[header_row].height = 22

    # Data
    row_fill_even = PatternFill("solid", fgColor="F8FAFC")
    row_fill_odd  = PatternFill("solid", fgColor="FFFFFF")

    for i, r in enumerate(rows):
        row_idx = header_row + 1 + i
        fill = row_fill_even if i % 2 == 0 else row_fill_odd
        pay_cell = "Withheld" if r["withheld"] else r["pay_this_period"]
        vals = [
            r["person"], r["code"], r["active_between"], r["days"],
            r["net_pay"], r["from_last_period"] or None, pay_cell,
        ]
        for col_idx, val in enumerate(vals, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.fill = fill
            cell.alignment = right if col_idx >= 4 else left
            if col_idx in (5, 6, 7) and isinstance(val, float):
                cell.number_format = money_fmt

    # Totals
    totals_row = header_row + 1 + len(rows)
    totals_fill = PatternFill("solid", fgColor="1E3A5F")
    totals_font = Font(bold=True, color="FFFFFF", size=11)
    totals_vals = ["TOTALS", "", "", totals["days"], totals["net_pay"], "", totals["pay_this_period"]]
    for col_idx, val in enumerate(totals_vals, start=1):
        cell = ws.cell(row=totals_row, column=col_idx, value=val)
        cell.fill = totals_fill
        cell.font = totals_font
        cell.alignment = right if col_idx >= 4 else left
        if col_idx in (5, 7) and isinstance(val, float):
            cell.number_format = money_fmt

    # Column widths
    for i, w in enumerate([32, 14, 24, 8, 14, 16, 16], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    co_slug = (company or "all").lower().replace(" ", "_")
    filename = f"zpay_{co_slug}_{date.today().isoformat()}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── PDF export ────────────────────────────────────────────────────────────────

@router.get("/export/pdf")
def summary_pdf(
    company: str | None = Query(None),
    batch_id: int | None = Query(None),
    start: date | None = Query(None),
    end: date | None = Query(None),
    db: Session = Depends(get_db),
):
    data = _build_summary(db, company=company, batch_id=batch_id, start=start, end=end)
    rows = data["rows"]
    totals = data["totals"]

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=(8.5 * inch, 11 * inch),
        leftMargin=0.5*inch, rightMargin=0.5*inch,
        topMargin=0.5*inch, bottomMargin=0.5*inch,
    )
    styles = getSampleStyleSheet()
    elements = []

    title_style = styles["Title"]
    title_style.textColor = colors.HexColor("#0f1729")
    elements.append(Paragraph(f"{company or 'All Companies'} — Payroll Summary", title_style))

    sub = f"Generated {datetime.now().strftime('%m/%d/%Y')}"
    if start or end:
        sub += f"  ·  {start or '—'} to {end or '—'}"
    elements.append(Paragraph(sub, styles["Normal"]))
    elements.append(Spacer(1, 14))

    table_data = [COLUMNS]
    for r in rows:
        from_last = f"${r['from_last_period']:,.2f}" if r["from_last_period"] else "—"
        pay_col = "Withheld" if r["withheld"] else f"${r['pay_this_period']:,.2f}"
        table_data.append([
            r["person"],
            r["code"] or "—",
            r["active_between"] or "—",
            str(r["days"]),
            f"${r['net_pay']:,.2f}",
            from_last,
            pay_col,
        ])

    table_data.append([
        "TOTALS", "", "",
        str(totals["days"]),
        f"${totals['net_pay']:,.2f}",
        "",
        f"${totals['pay_this_period']:,.2f}",
    ])

    col_widths = [1.9*inch, 0.75*inch, 1.5*inch, 0.4*inch, 0.9*inch, 1.0*inch, 1.0*inch]
    t = Table(table_data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        # Header
        ("BACKGROUND",    (0,0), (-1,0), colors.HexColor("#0f1729")),
        ("TEXTCOLOR",     (0,0), (-1,0), colors.white),
        ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",      (0,0), (-1,0), 8),
        ("ALIGN",         (0,0), (-1,0), "CENTER"),
        ("BOTTOMPADDING", (0,0), (-1,0), 8),
        ("TOPPADDING",    (0,0), (-1,0), 8),
        # Body
        ("FONTNAME",      (0,1), (-1,-2), "Helvetica"),
        ("FONTSIZE",      (0,1), (-1,-2), 8),
        ("ROWBACKGROUNDS",(0,1), (-1,-2), [colors.white, colors.HexColor("#f1f5f9")]),
        ("ALIGN",         (3,1), (-1,-2), "RIGHT"),
        ("ALIGN",         (0,1), (2,-2), "LEFT"),
        ("BOTTOMPADDING", (0,1), (-1,-2), 5),
        ("TOPPADDING",    (0,1), (-1,-2), 5),
        # Net pay column green
        ("TEXTCOLOR",     (4,1), (4,-2), colors.HexColor("#059669")),
        ("FONTNAME",      (4,1), (4,-2), "Helvetica-Bold"),
        # Pay This Period column green/red handled as text
        ("FONTNAME",      (-1,1), (-1,-2), "Helvetica-Bold"),
        # Totals row
        ("BACKGROUND",    (0,-1), (-1,-1), colors.HexColor("#1e3a5f")),
        ("TEXTCOLOR",     (0,-1), (-1,-1), colors.white),
        ("FONTNAME",      (0,-1), (-1,-1), "Helvetica-Bold"),
        ("ALIGN",         (3,-1), (-1,-1), "RIGHT"),
        ("TOPPADDING",    (0,-1), (-1,-1), 8),
        ("BOTTOMPADDING", (0,-1), (-1,-1), 8),
        # Grid
        ("LINEBELOW",     (0,0), (-1,0), 0.5, colors.HexColor("#1e3a5f")),
        ("LINEABOVE",     (0,-1), (-1,-1), 0.5, colors.HexColor("#3b82f6")),
        ("GRID",          (0,0), (-1,-1), 0.25, colors.HexColor("#e2e8f0")),
    ]))
    elements.append(t)
    doc.build(elements)
    buf.seek(0)

    co_slug = (company or "all").lower().replace(" ", "_")
    filename = f"zpay_{co_slug}_{date.today().isoformat()}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Paychex CSV export ────────────────────────────────────────────────────────
# Standard Payroll Import (SPI) format — 16 columns, no header row.
# Cols: Client ID, Worker ID, Org, Job#, Pay Component, Rate, Rate#,
#       Hours, Units, Line Date, Amount, Check Seq#, Override State,
#       Override Local, Override Local Juris, Labor Assignment

PAYCHEX_CLIENT_ID = "70189220"  # Acumen International

@router.get("/export/paycheck-csv")
def export_paycheck_csv(
    payroll_batch_id: int = Query(...),
    db: Session = Depends(get_db),
):
    """
    Export drivers paid this period in Paychex SPI format.
    Only includes drivers who are NOT withheld (pay_this_period > 0).
    """
    data = _build_summary(db, batch_id=payroll_batch_id)
    rows = data["rows"]

    # Pull Person records to get paycheck_code (= Paychex Worker ID)
    person_ids = [r["person_id"] for r in rows if not r["withheld"] and r["pay_this_period"] > 0]
    persons = {
        p.person_id: p
        for p in db.query(Person).filter(Person.person_id.in_(person_ids)).all()
    } if person_ids else {}

    output = io.StringIO()
    writer = csv.writer(output)
    # NO header row — SPI format uses fixed column positions

    for r in rows:
        if r["withheld"] or r["pay_this_period"] <= 0:
            continue

        person = persons.get(r["person_id"])
        # Worker ID: must be the Paychex-assigned ID (paycheck_code field)
        worker_id = ""
        if person:
            worker_id = getattr(person, "paycheck_code", None) or ""

        if not worker_id:
            continue  # Skip drivers without a Paychex ID — can't import them

        writer.writerow([
            PAYCHEX_CLIENT_ID,  # Col A: Client ID
            worker_id,           # Col B: Worker ID
            "",                  # Col C: Org (blank)
            "",                  # Col D: Job Number (blank)
            "[Pay]",             # Col E: Pay Component — [Pay] = standard pay check
            "",                  # Col F: Rate (blank — use amount)
            "",                  # Col G: Rate Number (blank)
            "",                  # Col H: Hours (blank — not hourly)
            "",                  # Col I: Units (blank)
            "",                  # Col J: Line Date (blank)
            f"{r['pay_this_period']:.2f}",  # Col K: Amount
            "",                  # Col L: Check Seq Number (blank)
            "",                  # Col M: Override State (blank)
            "",                  # Col N: Override Local (blank)
            "",                  # Col O: Override Local Jurisdiction (blank)
            "",                  # Col P: Labor Assignment (blank)
        ])

    output.seek(0)
    filename = f"paychex_spi_{date.today().isoformat()}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
