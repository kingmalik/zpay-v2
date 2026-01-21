from __future__ import annotations
from fastapi import APIRouter, Depends, Request, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from pathlib import Path
import shutil
from collections import Counter

from fastapi.templating import Jinja2Templates


from ..db import get_db
from ..db import crud
from ..db.db import SessionLocal
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
    path = UPLOAD_DIR / file.filename
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


# ✅ GET /upload – just renders the page, no validation / file required
@router.get("/", name="upload_page")
async def upload_page(request: Request):
    return templates().TemplateResponse(
    request=request,
    name="upload.html",
    context={}
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


# ✅ POST /upload/acumen – actually process Acumen file
@router.post("/acumen", response_class=HTMLResponse)
async def upload_acumen(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    # ... your existing import logic ...
    temp = _save_temp(file)
    result = import_payroll_excel(db, str(temp), ACU_CFG_PATH)

    source = result["source"]
    payroll_batch_id = result["payroll_batch_id"]
    company_name = result.get("company_name") or ""

    return request.app.state.templates.TemplateResponse(
        "upload_success.html",
        {
            "request": request,
            "source": source,
            "company_name": company_name,
            "payroll_batch_id": payroll_batch_id,
            "inserted": result["inserted"],
            "skipped": result["skipped"],
        },
    )
# ✅ POST /upload/maz – actually process ACL file
@router.post("/maz", name="upload_pdf")
async def upload_maz(
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
        pdf_text = extract_pdf_text(raw)
        week_start, week_end = parse_maz_period(pdf_text)
        batch_id = parse_maz_receipt_number(pdf_text)
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
        #_show_debug(records)
        wanted = {"27117048", "27117069", "27117177"}
        hits = []
        for i, r in enumerate(records):
            # check common places the key might land
            candidates = [
                r.get("Key"),
                r.get("service_key"),
                r.get("Service Key"),
                r.get("Trip Key"),
            ]
            cand_str = [str(c).strip() for c in candidates if c is not None]

            if any(s in wanted for s in cand_str):
                hits.append((i, r.get("Date"), r.get("Person"), r.get("Code"), r.get("Key"), r.get("Name"), r.get("Miles"), r.get("Gross"), r.get("source_page")))

        print("WANTED HITS:", len(hits))
        for h in hits[:50]:
            print(h)
        inserted, skipped = bulk_insert_rides(db, week_start, week_end, batch_id, file.filename, records)
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

    """
    return {
        "ok": True,
        "filename": file.filename,
        "detected_rows": len(records),
        "inserted": inserted,
        "skipped_duplicates": skipped,
        "people": by_person
    }
    """
    # ✅ redirect to summary after success
    return RedirectResponse(url="/summary", status_code=303)

