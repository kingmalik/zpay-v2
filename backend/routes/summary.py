from io import BytesIO
from pathlib import Path
from datetime import date, datetime

from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from backend.db import get_db
from backend.db.crud import people_rollup

router = APIRouter(prefix="/summary", tags=["summary"])

_templates = None
def templates():
    global _templates
    if _templates is None:
        templates_dir = Path(__file__).resolve().parents[1] / "templates"
        _templates = Jinja2Templates(directory=str(templates_dir))
    return _templates


COLUMNS = ["Driver", "Code", "Active Between", "Days", "Runs", "Miles", "Gross", "RAD", "WUD", "Net Pay"]


@router.get("/", name="summary_page")
def summary_page(
    request: Request,
    start: date | None = Query(None),
    end: date | None = Query(None),
    person_id: int | None = Query(None),
    code: str | None = Query(None),
    db: Session = Depends(get_db),
):
    data = people_rollup(db, start=start, end=end, person_id=person_id, code=code)
    return templates().TemplateResponse(
        request,
        "summary.html",
        {
            "rows": data.get("rows", []),
            "totals": data.get("totals", {}),
            "start": start,
            "end": end,
        },
    )


def _row_values(r: dict) -> list:
    return [
        r.get("person", ""),
        r.get("code", "") or "",
        r.get("active_between", "") or "",
        r.get("days", 0),
        r.get("runs", 0),
        round(float(r.get("miles", 0)), 1),
        round(float(r.get("gross", 0)), 2),
        round(float(r.get("rad", 0)), 2),
        round(float(r.get("wud", 0)), 2),
        round(float(r.get("net_pay", 0)), 2),
    ]


# ── Excel export ──────────────────────────────────────────────────────────────

@router.get("/export/excel")
def summary_excel(
    start: date | None = Query(None),
    end: date | None = Query(None),
    db: Session = Depends(get_db),
):
    data = people_rollup(db, start=start, end=end)
    rows = data.get("rows", [])
    totals = data.get("totals", {})

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Payroll Summary"

    # ── Header row ──
    header_fill = PatternFill("solid", fgColor="0F1729")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    center = Alignment(horizontal="center", vertical="center")
    right = Alignment(horizontal="right", vertical="center")
    thin = Side(style="thin", color="2D3A4A")
    border = Border(bottom=thin)

    for col_idx, col_name in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = center
        cell.border = border

    # ── Data rows ──
    row_fill_even = PatternFill("solid", fgColor="F8FAFC")
    row_fill_odd  = PatternFill("solid", fgColor="FFFFFF")
    money_fmt = '#,##0.00'
    num_fmt   = '#,##0'

    for row_idx, r in enumerate(rows, start=2):
        vals = _row_values(r)
        fill = row_fill_even if row_idx % 2 == 0 else row_fill_odd
        for col_idx, val in enumerate(vals, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.fill = fill
            cell.alignment = right if col_idx > 3 else Alignment(vertical="center")
            if col_idx in (7, 8, 9, 10):   # money columns
                cell.number_format = money_fmt
            elif col_idx in (4, 5, 6):
                cell.number_format = num_fmt

    # ── Totals row ──
    totals_row = len(rows) + 2
    totals_font = Font(bold=True, size=11)
    totals_fill = PatternFill("solid", fgColor="1E3A5F")
    totals_font_color = Font(bold=True, color="FFFFFF", size=11)
    totals_vals = [
        "TOTALS", "", "",
        totals.get("days", 0),
        totals.get("runs", 0),
        round(float(totals.get("miles", 0)), 1),
        round(float(totals.get("gross", 0)), 2),
        round(float(totals.get("rad", 0)), 2),
        round(float(totals.get("wud", 0)), 2),
        round(float(totals.get("net_pay", 0)), 2),
    ]
    for col_idx, val in enumerate(totals_vals, start=1):
        cell = ws.cell(row=totals_row, column=col_idx, value=val)
        cell.fill = totals_fill
        cell.font = totals_font_color
        cell.alignment = right if col_idx > 3 else Alignment(vertical="center")
        if col_idx in (7, 8, 9, 10):
            cell.number_format = money_fmt
        elif col_idx in (4, 5, 6):
            cell.number_format = num_fmt

    # ── Column widths ──
    widths = [28, 14, 22, 8, 8, 10, 12, 12, 12, 12]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws.row_dimensions[1].height = 24

    # ── Stream response ──
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"zpay_summary_{date.today().isoformat()}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── PDF export ────────────────────────────────────────────────────────────────

@router.get("/export/pdf")
def summary_pdf(
    start: date | None = Query(None),
    end: date | None = Query(None),
    db: Session = Depends(get_db),
):
    data = people_rollup(db, start=start, end=end)
    rows = data.get("rows", [])
    totals = data.get("totals", {})

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=36, rightMargin=36, topMargin=48, bottomMargin=36,
    )
    styles = getSampleStyleSheet()

    elements = []

    # Title
    title_style = styles["Title"]
    title_style.textColor = colors.HexColor("#0f1729")
    elements.append(Paragraph("Payroll Summary", title_style))

    subtitle = f"Generated {datetime.now().strftime('%m/%d/%Y')}"
    if start or end:
        subtitle += f"  ·  Period: {start or '—'} – {end or '—'}"
    elements.append(Paragraph(subtitle, styles["Normal"]))
    elements.append(Spacer(1, 16))

    # Table data
    table_data = [COLUMNS]
    for r in rows:
        vals = _row_values(r)
        # format numbers for PDF
        table_data.append([
            vals[0], vals[1], vals[2],
            str(vals[3]), str(vals[4]),
            f"{vals[5]:.1f}",
            f"${vals[6]:,.2f}", f"${vals[7]:,.2f}", f"${vals[8]:,.2f}",
            f"${vals[9]:,.2f}",
        ])

    # Totals row
    table_data.append([
        "TOTALS", "", "",
        str(totals.get("days", 0)),
        str(totals.get("runs", 0)),
        f"{float(totals.get('miles', 0)):.1f}",
        f"${float(totals.get('gross', 0)):,.2f}",
        f"${float(totals.get('rad', 0)):,.2f}",
        f"${float(totals.get('wud', 0)):,.2f}",
        f"${float(totals.get('net_pay', 0)):,.2f}",
    ])

    col_widths = [110, 45, 90, 30, 30, 38, 52, 52, 52, 52]
    t = Table(table_data, colWidths=col_widths, repeatRows=1)

    header_bg   = colors.HexColor("#0f1729")
    alt_row_bg  = colors.HexColor("#f1f5f9")
    totals_bg   = colors.HexColor("#1e3a5f")
    accent_green = colors.HexColor("#059669")

    style_cmds = [
        # Header
        ("BACKGROUND",  (0, 0), (-1, 0), header_bg),
        ("TEXTCOLOR",   (0, 0), (-1, 0), colors.white),
        ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, 0), 8),
        ("ALIGN",       (0, 0), (-1, 0), "CENTER"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING",    (0, 0), (-1, 0), 8),

        # Body
        ("FONTNAME",    (0, 1), (-1, -2), "Helvetica"),
        ("FONTSIZE",    (0, 1), (-1, -2), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, alt_row_bg]),
        ("ALIGN",       (3, 1), (-1, -2), "RIGHT"),
        ("ALIGN",       (0, 1), (2, -2), "LEFT"),
        ("BOTTOMPADDING", (0, 1), (-1, -2), 6),
        ("TOPPADDING",    (0, 1), (-1, -2), 6),

        # Net pay column in green
        ("TEXTCOLOR",   (-1, 1), (-1, -2), accent_green),
        ("FONTNAME",    (-1, 1), (-1, -2), "Helvetica-Bold"),

        # Totals row
        ("BACKGROUND",  (0, -1), (-1, -1), totals_bg),
        ("TEXTCOLOR",   (0, -1), (-1, -1), colors.white),
        ("FONTNAME",    (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE",    (0, -1), (-1, -1), 8),
        ("ALIGN",       (3, -1), (-1, -1), "RIGHT"),
        ("TOPPADDING",  (0, -1), (-1, -1), 8),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 8),

        # Grid
        ("LINEBELOW",   (0, 0), (-1, 0), 0.5, colors.HexColor("#1e3a5f")),
        ("LINEABOVE",   (0, -1), (-1, -1), 0.5, colors.HexColor("#3b82f6")),
        ("GRID",        (0, 0), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
    ]
    t.setStyle(TableStyle(style_cmds))
    elements.append(t)

    doc.build(elements)
    buf.seek(0)

    filename = f"zpay_summary_{date.today().isoformat()}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
