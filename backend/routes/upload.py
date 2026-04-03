from __future__ import annotations
from fastapi import APIRouter, Depends, Request, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from pathlib import Path
import shutil
import zipfile
import tempfile
from collections import Counter

from fastapi.templating import Jinja2Templates


from ..db import get_db
from ..db import crud
from ..services.pdf_reader import extract_tables, extract_pdf_text, normalize_details_tables, bulk_insert_rides
from ..services.excell_reader import import_payroll_excel
from ..services.data_extractor import parse_maz_period, parse_maz_receipt_number


from ..ingest_utils import load_source_cfg


router = APIRouter(prefix="/upload", tags=["upload"])

UPLOAD_DIR = Path("/tmp/payroll_uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ACU_CFG_PATH = Path(__file__).resolve().parents[1] / "config" / "source" / "acumen.yml"
MAZ_CFG_PATH = Path(__file__).resolve().parents[1] / "config" / "source" / "maz.yml"


def _save_temp(file: UploadFile) -> Path:
    import os as _os
    safe_name = _os.path.basename(file.filename or "upload").replace("..", "")
    if not safe_name:
        safe_name = "upload"
    path = UPLOAD_DIR / safe_name
    with path.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return path

def _show_debug(records):
    rows_92 = []
    for r in records:
        code = str(r.get("Code") or "").strip()
        dt = str(r.get("Date") or "").strip()
        key = str(r.get("Key") or "").strip()
        name = str(r.get("Name") or "").strip()
        if code == "141097" and (dt == "9/2/2025" or dt.startswith("2025-09-02")):
            rows_92.append((key, name, dt))

    print("DEBUG 9/2 rows count:", len(rows_92))
    print("DEBUG 9/2 keys:", rows_92[:50])
    print("DEBUG total keys count:", len([r for r in records if r.get("Key")]))
    print("DEBUG unique keys:", len(set(str(r.get("Key")) for r in records if r.get("Key"))))

_templates = None
def templates():
    global _templates
    if _templates is None:
        templates_dir = Path(__file__).resolve().parents[1] / "templates"
        _templates = Jinja2Templates(directory=str(templates_dir))
    return _templates


# ✅ GET /upload – renders upload form + recent batch summary
@router.get("/", name="upload_page")
async def upload_page(request: Request, db: Session = Depends(get_db)):
    from backend.db.models import Ride as RideModel, PayrollBatch as PB, Person as PersonModel
    from sqlalchemy import func as sqlfunc

    # Recent batches with aggregate stats (last 10)
    batches = (
        db.query(PB)
        .order_by(PB.uploaded_at.desc())
        .limit(10)
        .all()
    )

    recent_batches = []
    for b in batches:
        agg = db.query(
            sqlfunc.count(RideModel.ride_id).label("rides"),
            sqlfunc.sum(RideModel.net_pay).label("revenue"),
            sqlfunc.sum(RideModel.z_rate).label("cost"),
            sqlfunc.sum(RideModel.net_pay - RideModel.z_rate).label("profit"),
        ).filter(RideModel.payroll_batch_id == b.payroll_batch_id).one()

        recent_batches.append({
            "batch_id": b.payroll_batch_id,
            "company": b.company_name or "—",
            "source": b.source or "",
            "period": (
                (b.period_start.strftime("%-m/%-d") if b.period_start else "?")
                + " – "
                + (b.period_end.strftime("%-m/%-d/%Y") if b.period_end else "?")
            ),
            "rides": int(agg.rides or 0),
            "revenue": round(float(agg.revenue or 0), 2),
            "cost": round(float(agg.cost or 0), 2),
            "profit": round(float(agg.profit or 0), 2),
            "uploaded_at": b.uploaded_at.strftime("%-m/%-d %I:%M %p") if b.uploaded_at else "—",
        })

    return templates().TemplateResponse(
        request=request,
        name="upload.html",
        context={"recent_batches": recent_batches},
    )

#@router.get("/", response_class=HTMLResponse)
async def upload_home() -> HTMLResponse:
    return HTMLResponse(
        """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8" />
            <title>ZPay - Payroll Upload</title>
            <style>
                body { font-family: system-ui, -apple-system, BlinkMacSystemFont, sans-serif; padding: 2rem; }
                h1 { margin-bottom: 1.5rem; }
                .container { max-width: 600px; margin: 0 auto; }
                .card {
                    border: 1px solid #ddd;
                    border-radius: 8px;
                    padding: 1.5rem;
                    margin-bottom: 1.5rem;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.05);
                }
                .card h2 { margin-top: 0; }
                label { display: block; margin-bottom: 0.5rem; }
                input[type="file"] { margin-bottom: 1rem; }
                button {
                    padding: 0.5rem 1rem;
                    border-radius: 4px;
                    border: none;
                    cursor: pointer;
                    background: #2563eb;
                    color: white;
                    font-weight: 500;
                }
                button:hover { background: #1d4ed8; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>ZPay – Upload Payroll</h1>

                <div class="card">
                    <h2>Acumen Payroll</h2>
                    <form action="/upload/acumen" method="post" enctype="multipart/form-data">
                        <label for="acumen-file">Choose Acumen Excel file</label>
                        <input id="acumen-file" type="file" name="file" accept=".xlsx,.xls" required />
                        <button type="submit">Upload to AcumenYY</button>
                    </form>
                </div>

                <div class="card">
                    <h2>MAZ Payroll</h2>
                    <form action="/upload/maz" method="post" enctype="multipart/form-data">
                        <label for="maz-file">Choose MAZ PDF file</label>
                        <input id="maz-file" type="file" name="file" accept=".xls,.xlsx,.csv,.pdf" required />
                        <button type="submit">Upload to MAZ</button>
                    </form>
                </div>
            </div>
        </body>
        </html>
        """
    )


# ✅ POST /upload/acumen – FirstAlt Excel upload
@router.post("/acumen", response_class=HTMLResponse)
async def upload_acumen(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    from urllib.parse import urlencode as _urlencode

    fname = (file.filename or "").lower()
    if not (fname.endswith(".xlsx") or fname.endswith(".xls")):
        return RedirectResponse(url="/upload?error=FirstAlt+upload+requires+an+Excel+file+(.xlsx+or+.xls)", status_code=303)

    temp = _save_temp(file)
    try:
        result = import_payroll_excel(db, str(temp), ACU_CFG_PATH)
    except Exception as e:
        return RedirectResponse(url=f"/upload?error={str(e)[:120]}", status_code=303)

    company_name = result.get("company_name") or ""
    payroll_batch_id = result["payroll_batch_id"]
    already_imported = result.get("already_imported", False)

    params: dict = {"company": company_name, "batch_id": payroll_batch_id}
    if already_imported:
        params["notice"] = "already_imported"
    return RedirectResponse(url=f"/summary?{_urlencode(params)}", status_code=303)


# ✅ POST /upload/maz – EverDriven PDF upload
@router.post("/maz", response_class=HTMLResponse)
async def upload_maz(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    from ..services.data_extractor import parse_maz_period, parse_maz_receipt_number
    from backend.db.models import PayrollBatch as _PB
    from sqlalchemy import desc as _desc
    from urllib.parse import urlencode as _urlencode

    fname = (file.filename or "").lower()
    if not fname.endswith(".pdf"):
        return RedirectResponse(url="/upload?error=EverDriven+upload+requires+a+PDF+file", status_code=303)

    raw = await file.read()
    if not raw or len(raw) < 10:
        return RedirectResponse(url="/upload?error=File+is+empty+or+unreadable", status_code=303)

    try:
        tables = extract_tables(raw)
        pdf_text = extract_pdf_text(raw)
        week_start, week_end = parse_maz_period(pdf_text)
        batch_id = parse_maz_receipt_number(pdf_text)
        rides_df = normalize_details_tables(tables, source_file=file.filename)
        if rides_df.empty:
            return RedirectResponse(url="/upload?error=No+ride+rows+detected+in+PDF", status_code=303)
        records = rides_df.to_dict(orient="records")
        result = bulk_insert_rides(db, week_start, week_end, batch_id, file.filename, records)
    except Exception as e:
        return RedirectResponse(url=f"/upload?error={str(e)[:120]}", status_code=303)

    already_imported = result.get("already_imported", False)
    latest = db.query(_PB).filter(_PB.source == "maz").order_by(_desc(_PB.uploaded_at)).first()
    if latest:
        params = {"company": latest.company_name, "batch_id": latest.payroll_batch_id}
        if already_imported:
            params["notice"] = "already_imported"
        return RedirectResponse(url=f"/summary?{_urlencode(params)}", status_code=303)
    return RedirectResponse(url="/summary", status_code=303)


# ✅ POST /upload/zip – Bulk historical import
@router.post("/zip", response_class=HTMLResponse)
async def upload_zip(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    import os
    from ..services.data_extractor import parse_maz_period, parse_maz_receipt_number

    fname = (file.filename or "").lower()
    if not fname.endswith(".zip"):
        return RedirectResponse(url="/upload?error=Please+upload+a+.zip+file", status_code=303)

    raw = await file.read()
    results = []

    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = Path(tmpdir) / "upload.zip"
        zip_path.write_bytes(raw)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmpdir)

        for root, dirs, files in os.walk(tmpdir):
            dirs[:] = [d for d in dirs if not d.startswith("__") and not d.startswith(".")]
            for inner_name in sorted(files):
                if inner_name.startswith("._") or inner_name.startswith("."):
                    continue
                fpath = Path(root) / inner_name
                rel = str(fpath.relative_to(tmpdir))
                ext = inner_name.lower().rsplit(".", 1)[-1] if "." in inner_name else ""
                entry = {"file": rel, "type": "—", "inserted": 0, "skipped": 0, "error": None}
                try:
                    if ext in ("xlsx", "xls"):
                        entry["type"] = "FirstAlt"
                        res = import_payroll_excel(db, str(fpath), ACU_CFG_PATH)
                        entry["inserted"] = res.get("inserted", 0)
                        entry["skipped"] = res.get("skipped", 0)
                    elif ext == "pdf":
                        entry["type"] = "EverDriven"
                        file_bytes = fpath.read_bytes()
                        tables = extract_tables(file_bytes)
                        pdf_text = extract_pdf_text(file_bytes)
                        week_start, week_end = parse_maz_period(pdf_text)
                        batch_id_str = parse_maz_receipt_number(pdf_text)
                        rides_df = normalize_details_tables(tables, source_file=inner_name)
                        if rides_df.empty:
                            entry["error"] = "No ride rows detected"
                        else:
                            records = rides_df.to_dict(orient="records")
                            res = bulk_insert_rides(db, week_start, week_end, batch_id_str, inner_name, records)
                            entry["inserted"] = res.get("inserted", 0)
                            entry["skipped"] = res.get("skipped", 0)
                    else:
                        continue
                except Exception as e:
                    db.rollback()
                    entry["error"] = str(e)[:120]
                results.append(entry)

    total_inserted = sum(r["inserted"] for r in results)
    total_skipped = sum(r["skipped"] for r in results)
    return templates().TemplateResponse(
        request=request,
        name="upload_zip_results.html",
        context={"results": results, "total_inserted": total_inserted, "total_skipped": total_skipped},
    )


# ✅ POST /upload/finalize – Lock batch into permanent history
@router.post("/finalize", response_class=HTMLResponse)
async def finalize_batch(request: Request, batch_id: int, db: Session = Depends(get_db)):
    from backend.db.models import PayrollBatch as _PB
    from datetime import datetime, timezone
    from urllib.parse import urlencode as _urlencode
    batch = db.query(_PB).filter(_PB.payroll_batch_id == batch_id).first()
    if not batch:
        return RedirectResponse(url="/batches?error=Batch+not+found", status_code=303)
    if not batch.finalized_at:
        batch.finalized_at = datetime.now(timezone.utc)
        db.commit()
    params = {"company": batch.company_name, "batch_id": batch_id, "notice": "finalized"}
    return RedirectResponse(url=f"/summary?{_urlencode(params)}", status_code=303)

