from io import BytesIO
from pathlib import Path
from datetime import date, datetime

from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import StreamingResponse
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
from backend.db.models import Person, Ride, PayrollBatch

router = APIRouter(prefix="/summary", tags=["summary"])

_templates = None
def templates():
    global _templates
    if _templates is None:
        templates_dir = Path(__file__).resolve().parents[1] / "templates"
        _templates = Jinja2Templates(directory=str(templates_dir))
    return _templates


COLUMNS = ["Driver", "Code", "Active Between", "Days", "Net Pay"]


def _get_companies(db: Session) -> list[str]:
    rows = (
        db.query(PayrollBatch.company_name)
        .distinct()
        .order_by(PayrollBatch.company_name.asc())
        .all()
    )
    return [r[0] for r in rows]


def _build_summary(
    db: Session,
    company: str | None = None,
    batch_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
) -> dict:
    """
    Returns rows + totals for the summary page.
    Each row: person, code, active_between, days, net_pay
    """
    ride_date = func.coalesce(
        cast(Ride.ride_start_ts, Date),
    )

    q = (
        db.query(
            Person.full_name.label("person"),
            Person.external_id.label("code"),
            func.min(ride_date).label("first_date"),
            func.max(ride_date).label("last_date"),
            func.count(func.distinct(ride_date)).label("days"),
            func.coalesce(func.sum(Ride.net_pay), 0).label("net_pay"),
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

    def fmt(d):
        return d.strftime("%-m/%-d/%Y") if d else ""

    rows = []
    total_days = 0
    total_net = 0.0

    for r in rows_raw:
        net = round(float(r.net_pay or 0), 2)
        days = int(r.days or 0)
        active = f"{fmt(r.first_date)} – {fmt(r.last_date)}" if r.first_date else ""
        rows.append({
            "person": r.person or "",
            "code": r.code or "",
            "active_between": active,
            "days": days,
            "net_pay": net,
        })
        total_days += days
        total_net += net

    totals = {
        "days": total_days,
        "net_pay": round(total_net, 2),
    }

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

    data = _build_summary(db, company=selected_company, batch_id=batch_id, start=start, end=end)

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
        },
    )


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
    ws.merge_cells("A1:E1")
    title_cell = ws["A1"]
    title_cell.value = f"{company or 'All Companies'} — Payroll Summary"
    if company:
        title_cell.value += f""
    title_cell.font = Font(bold=True, size=13, color="0F1729")
    title_cell.alignment = left
    ws.row_dimensions[1].height = 22

    if start or end:
        ws.merge_cells("A2:E2")
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
        vals = [r["person"], r["code"], r["active_between"], r["days"], r["net_pay"]]
        for col_idx, val in enumerate(vals, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.fill = fill
            cell.alignment = right if col_idx >= 4 else left
            if col_idx == 5:
                cell.number_format = money_fmt

    # Totals
    totals_row = header_row + 1 + len(rows)
    totals_fill = PatternFill("solid", fgColor="1E3A5F")
    totals_font = Font(bold=True, color="FFFFFF", size=11)
    totals_vals = ["TOTALS", "", "", totals["days"], totals["net_pay"]]
    for col_idx, val in enumerate(totals_vals, start=1):
        cell = ws.cell(row=totals_row, column=col_idx, value=val)
        cell.fill = totals_fill
        cell.font = totals_font
        cell.alignment = right if col_idx >= 4 else left
        if col_idx == 5:
            cell.number_format = money_fmt

    # Column widths
    for i, w in enumerate([32, 14, 24, 8, 14], start=1):
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
        table_data.append([
            r["person"],
            r["code"] or "—",
            r["active_between"] or "—",
            str(r["days"]),
            f"${r['net_pay']:,.2f}",
        ])

    table_data.append([
        "TOTALS", "", "",
        str(totals["days"]),
        f"${totals['net_pay']:,.2f}",
    ])

    col_widths = [2.2*inch, 0.9*inch, 1.8*inch, 0.5*inch, 1.1*inch]
    t = Table(table_data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        # Header
        ("BACKGROUND",    (0,0), (-1,0), colors.HexColor("#0f1729")),
        ("TEXTCOLOR",     (0,0), (-1,0), colors.white),
        ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",      (0,0), (-1,0), 9),
        ("ALIGN",         (0,0), (-1,0), "CENTER"),
        ("BOTTOMPADDING", (0,0), (-1,0), 8),
        ("TOPPADDING",    (0,0), (-1,0), 8),
        # Body
        ("FONTNAME",      (0,1), (-1,-2), "Helvetica"),
        ("FONTSIZE",      (0,1), (-1,-2), 8.5),
        ("ROWBACKGROUNDS",(0,1), (-1,-2), [colors.white, colors.HexColor("#f1f5f9")]),
        ("ALIGN",         (3,1), (-1,-2), "RIGHT"),
        ("ALIGN",         (0,1), (2,-2), "LEFT"),
        ("BOTTOMPADDING", (0,1), (-1,-2), 6),
        ("TOPPADDING",    (0,1), (-1,-2), 6),
        # Net pay green
        ("TEXTCOLOR",     (-1,1), (-1,-2), colors.HexColor("#059669")),
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
