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
from backend.utils.roles import require_role


router = APIRouter(prefix="/upload", tags=["upload"])

UPLOAD_DIR = Path("/tmp/payroll_uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ACU_CFG_PATH = Path(__file__).resolve().parents[1] / "config" / "source" / "acumen.yml"
MAZ_CFG_PATH = Path(__file__).resolve().parents[1] / "config" / "source" / "maz.yml"

MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB

# Magic byte signatures for file type validation
_EXCEL_MAGIC = b"PK\x03\x04"  # .xlsx is a ZIP archive
_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK\x03\x04"


def _validate_file_size(raw: bytes, label: str = "File") -> None:
    if len(raw) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail=f"{label} exceeds 50 MB limit")


def _validate_magic_bytes(raw: bytes, expected: bytes, label: str) -> None:
    if not raw[:len(expected)] == expected:
        raise HTTPException(status_code=400, detail=f"{label}: file content does not match expected type")


def _save_temp(file: UploadFile) -> Path:
    import os as _os
    safe_name = _os.path.basename(file.filename or "upload").replace("..", "")
    if not safe_name:
        safe_name = "upload"
    path = UPLOAD_DIR / safe_name
    with path.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return path

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

    is_json = "json" in request.headers.get("accept", "")

    fname = (file.filename or "").lower()
    if not (fname.endswith(".xlsx") or fname.endswith(".xls")):
        msg = "FirstAlt upload requires an Excel file (.xlsx or .xls)"
        if is_json:
            return JSONResponse({"error": msg}, status_code=400)
        return RedirectResponse(url=f"/upload?error={msg}", status_code=303)

    raw = await file.read()
    _validate_file_size(raw, "Excel file")
    if fname.endswith(".xlsx"):
        _validate_magic_bytes(raw, _EXCEL_MAGIC, "Excel file")

    # Write validated bytes to temp file
    temp = UPLOAD_DIR / (fname or "upload.xlsx")
    temp.write_bytes(raw)
    try:
        result = import_payroll_excel(db, str(temp), ACU_CFG_PATH)
    except Exception as e:
        if is_json:
            return JSONResponse({"error": str(e)[:200]}, status_code=400)
        return RedirectResponse(url=f"/upload?error={str(e)[:120]}", status_code=303)

    company_name = result.get("company_name") or ""
    payroll_batch_id = result["payroll_batch_id"]
    already_imported = result.get("already_imported", False)

    # Set workflow status to rates_review after successful upload
    if not already_imported:
        from backend.db.models import PayrollBatch as _PB, BatchWorkflowLog
        batch = db.query(_PB).filter(_PB.payroll_batch_id == payroll_batch_id).first()
        if batch and batch.status == "uploaded":
            batch.status = "rates_review"
            db.add(BatchWorkflowLog(
                payroll_batch_id=payroll_batch_id,
                from_status="uploaded",
                to_status="rates_review",
                triggered_by="system",
                notes="Auto-advanced after upload",
            ))
            db.commit()

    if is_json:
        return JSONResponse({"ok": True, "batch_id": payroll_batch_id, "company": company_name, "already_imported": already_imported})

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

    is_json = "json" in request.headers.get("accept", "")

    fname = (file.filename or "").lower()
    if not fname.endswith(".pdf"):
        msg = "EverDriven upload requires a PDF file"
        if is_json:
            return JSONResponse({"error": msg}, status_code=400)
        return RedirectResponse(url=f"/upload?error={msg}", status_code=303)

    raw = await file.read()
    _validate_file_size(raw, "PDF file")
    if not raw or len(raw) < 10:
        msg = "File is empty or unreadable"
        if is_json:
            return JSONResponse({"error": msg}, status_code=400)
        return RedirectResponse(url=f"/upload?error={msg}", status_code=303)
    _validate_magic_bytes(raw, _PDF_MAGIC, "PDF file")

    try:
        tables = extract_tables(raw)
        pdf_text = extract_pdf_text(raw)
        week_start, week_end = parse_maz_period(pdf_text)
        batch_id = parse_maz_receipt_number(pdf_text)
        rides_df = normalize_details_tables(tables, source_file=file.filename)
        if rides_df.empty:
            msg = "No ride rows detected in PDF"
            if is_json:
                return JSONResponse({"error": msg}, status_code=400)
            return RedirectResponse(url=f"/upload?error={msg}", status_code=303)
        records = rides_df.to_dict(orient="records")
        result = bulk_insert_rides(db, week_start, week_end, batch_id, file.filename, records)
    except Exception as e:
        if is_json:
            return JSONResponse({"error": str(e)[:200]}, status_code=400)
        return RedirectResponse(url=f"/upload?error={str(e)[:120]}", status_code=303)

    already_imported = result.get("already_imported", False)
    latest = db.query(_PB).filter(_PB.source == "maz").order_by(_desc(_PB.uploaded_at)).first()

    # Set workflow status to rates_review after successful upload
    if not already_imported and latest and latest.status == "uploaded":
        from backend.db.models import BatchWorkflowLog
        latest.status = "rates_review"
        db.add(BatchWorkflowLog(
            payroll_batch_id=latest.payroll_batch_id,
            from_status="uploaded",
            to_status="rates_review",
            triggered_by="system",
            notes="Auto-advanced after upload",
        ))
        db.commit()

    if is_json:
        return JSONResponse({
            "ok": True,
            "batch_id": latest.payroll_batch_id if latest else None,
            "company": latest.company_name if latest else "EverDriven",
            "already_imported": already_imported,
        })

    if latest:
        params = {"company": latest.company_name, "batch_id": latest.payroll_batch_id}
        if already_imported:
            params["notice"] = "already_imported"
        return RedirectResponse(url=f"/summary?{_urlencode(params)}", status_code=303)
    return RedirectResponse(url="/summary", status_code=303)


# ✅ POST /upload/maz-multi – Merge multiple EverDriven PDFs into one batch
@router.post("/maz-multi")
async def upload_maz_multi(request: Request, files: list[UploadFile] = File(default=[]), db: Session = Depends(get_db)):
    """Accept 2+ EverDriven PDFs (e.g. split across a month boundary) and merge
    all their rides into a single payroll batch spanning the full week."""
    import traceback
    from ..services.data_extractor import parse_maz_period, parse_maz_receipt_number
    from backend.db.models import PayrollBatch as _PB, BatchWorkflowLog
    from sqlalchemy import desc as _desc

    try:
        if not files:
            return JSONResponse({"error": "No files provided"}, status_code=400)

        all_records: list[dict] = []
        week_starts: list[str] = []
        week_ends: list[str] = []
        batch_ref: str = ""

        for file in files:
            fname = (file.filename or "").lower()
            if not fname.endswith(".pdf"):
                return JSONResponse({"error": f"{file.filename} is not a PDF"}, status_code=400)

            raw = await file.read()
            _validate_file_size(raw, "PDF file")
            _validate_magic_bytes(raw, _PDF_MAGIC, "PDF file")

            try:
                tables = extract_tables(raw)
                pdf_text = extract_pdf_text(raw)
                week_start, week_end = parse_maz_period(pdf_text)
                # Convert date objects to ISO strings immediately to avoid JSON serialization errors
                week_start_str = week_start.isoformat() if hasattr(week_start, 'isoformat') else str(week_start)
                week_end_str = week_end.isoformat() if hasattr(week_end, 'isoformat') else str(week_end)
                ref = parse_maz_receipt_number(pdf_text)
                rides_df = normalize_details_tables(tables, source_file=file.filename)
                if rides_df.empty:
                    return JSONResponse({"error": f"No ride rows detected in {file.filename}"}, status_code=400)
                records = rides_df.to_dict(orient="records")
            except Exception as e:
                return JSONResponse({"error": f"{file.filename}: {str(e)[:300]}"}, status_code=400)

            all_records.extend(records)
            week_starts.append(week_start_str)
            week_ends.append(week_end_str)
            if ref and not batch_ref:
                batch_ref = ref

        merged_start = min(week_starts)
        merged_end = max(week_ends)

        try:
            result = bulk_insert_rides(db, merged_start, merged_end, batch_ref, "multi-pdf", all_records)
        except Exception as e:
            return JSONResponse({"error": f"DB insert failed: {str(e)[:300]}"}, status_code=400)

        already_imported = result.get("already_imported", False)
        latest = db.query(_PB).filter(_PB.source == "maz").order_by(_desc(_PB.uploaded_at)).first()

        if not already_imported and latest and latest.status == "uploaded":
            latest.status = "rates_review"
            db.add(BatchWorkflowLog(
                payroll_batch_id=latest.payroll_batch_id,
                from_status="uploaded",
                to_status="rates_review",
                triggered_by="system",
                notes="Auto-advanced after multi-PDF upload",
            ))
            db.commit()

        return JSONResponse({
            "ok": True,
            "batch_id": latest.payroll_batch_id if latest else None,
            "company": "EverDriven",
            "already_imported": already_imported,
            "files_merged": len(files),
            "week_start": merged_start,
            "week_end": merged_end,
        })

    except Exception as e:
        tb = traceback.format_exc()
        print(f"[maz-multi] Unhandled error: {e}\n{tb}")
        return JSONResponse({"error": f"Server error: {str(e)[:300]}"}, status_code=500)


# ✅ POST /upload/zip – Bulk historical import
@router.post("/zip", response_class=HTMLResponse)
async def upload_zip(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    import os
    from ..services.data_extractor import parse_maz_period, parse_maz_receipt_number

    fname = (file.filename or "").lower()
    if not fname.endswith(".zip"):
        return RedirectResponse(url="/upload?error=Please+upload+a+.zip+file", status_code=303)

    raw = await file.read()
    _validate_file_size(raw, "ZIP file")
    _validate_magic_bytes(raw, _ZIP_MAGIC, "ZIP file")
    results = []

    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = Path(tmpdir) / "upload.zip"
        zip_path.write_bytes(raw)
        tmpdir_resolved = Path(tmpdir).resolve()
        with zipfile.ZipFile(zip_path, "r") as zf:
            # Safe extraction: skip entries with path traversal
            for entry in zf.infolist():
                target = (tmpdir_resolved / entry.filename).resolve()
                if not str(target).startswith(str(tmpdir_resolved)):
                    continue  # skip path traversal attempts
                zf.extract(entry, tmpdir)

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


# ✅ POST /upload/finalize – Lock batch into permanent history (admin only)
@router.post("/finalize", response_class=HTMLResponse)
async def finalize_batch(request: Request, batch_id: int, db: Session = Depends(get_db), _=Depends(require_role("admin"))):
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

