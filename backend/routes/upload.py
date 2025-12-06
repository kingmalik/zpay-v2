from __future__ import annotations
from fastapi import APIRouter, Depends, Request, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from pathlib import Path
import shutil

from ..db import get_db
from ..db import crud
from ..db.db import SessionLocal
from ..services.pdf_reader import extract_tables, normalize_details_tables, bulk_insert_rides
from ..ingest_utils import load_source_cfg

router = APIRouter(prefix="/upload", tags=["upload"])

UPLOAD_DIR = Path("/tmp/payroll_uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _save_temp(file: UploadFile) -> Path:
    path = UPLOAD_DIR / file.filename
    with path.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return path


# ✅ GET /upload – just renders the page, no validation / file required
@router.get("/", response_class=HTMLResponse)
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
                        <button type="submit">Upload to Acumen</button>
                    </form>
                </div>

                <div class="card">
                    <h2>ACL Payroll</h2>
                    <form action="/upload/acl" method="post" enctype="multipart/form-data">
                        <label for="acl-file">Choose ACL Excel file</label>
                        <input id="acl-file" type="file" name="file" accept=".xls,.xlsx,.csv,.pdf" required />
                        <button type="submit">Upload to ACL</button>
                    </form>
                </div>
            </div>
        </body>
        </html>
        """
    )


# ✅ POST /upload/acumen – actually process Acumen file
@router.post("/acumen")
async def upload_acumen(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    temp = _save_temp(file)
    cfg = load_source_cfg("acumen")
    result = crud.import_payroll_excel(db, str(temp), cfg)
    return {"source": "acumen", **result}


# ✅ POST /upload/acl – actually process ACL file
@router.post("/acl", name="upload_pdf")
async def upload_acl(
    db: Session = Depends(get_db),
    file: UploadFile = File(...),
):
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail={
            "error": "no_file",
            "message": "No file uploaded."
        })
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail={
            "error": "bad_type",
            "message": "Only PDF files are supported by this endpoint."
        })

    raw = await file.read()
    if not raw or len(raw) < 10:
        raise HTTPException(status_code=400, detail={
            "error": "unreadable_or_empty_file",
            "message": "File is empty or unreadable."
        })

    try:
        tables = extract_tables(raw)
        rides_df = normalize_details_tables(tables, source_file=file.filename)
    except Exception as e:
        return JSONResponse(status_code=400, content={
            "detail": {
                "error": "pdf_parse_failed",
                "message": str(e),
                "filename": file.filename
            }
        })

    if rides_df.empty:
        return JSONResponse(status_code=400, content={
            "detail": {
                "error": "no_rides_detected",
                "message": "Could not detect any 'Details' rows in the PDF."
            }
        })

    records = rides_df.to_dict(orient="records")
    db: Session = SessionLocal()
    try:
        inserted, skipped = bulk_insert_rides(db, records)
    finally:
        db.close()

    by_person = {}
    for r in records:
        p = r.get("Person")
        if not p:
            continue
        if p not in by_person:
            by_person[p] = {"rides": 0, "miles": 0.0, "gross": 0.0, "net_pay": 0.0}
        by_person[p]["rides"] += 1
        by_person[p]["miles"] += float(r.get("Miles") or 0.0)
        by_person[p]["gross"] += float(r.get("Gross") or 0.0)
        by_person[p]["net_pay"] += float(r.get("Net Pay") or 0.0)

    for p, v in by_person.items():
        v["miles"] = round(v["miles"], 2)
        v["gross"] = round(v["gross"], 2)
        v["net_pay"] = round(v["net_pay"], 2)

    return {
        "ok": True,
        "filename": file.filename,
        "detected_rows": len(records),
        "inserted": inserted,
        "skipped_duplicates": skipped,
        "people": by_person
    }

