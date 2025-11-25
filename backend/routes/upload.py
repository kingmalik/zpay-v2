from __future__ import annotations
from fastapi import APIRouter, Depends, Request, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from pathlib import Path
import shutil

from ..db import get_db
from ..db import crud
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
                        <input id="acl-file" type="file" name="file" accept=".xlsx,.xls" required />
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
@router.post("/acl")
async def upload_acl(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    temp = _save_temp(file)
    cfg = load_source_cfg("acl")
    result = crud.import_payroll_excel(db, str(temp), cfg)
    return {"source": "acl", **result}
