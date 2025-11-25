
from __future__ import annotations
from fastapi import APIRouter, Depends, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..db.db import SessionLocal
from ..services.pdf_reader import extract_tables, normalize_details_tables, bulk_insert_rides
from ..services.pdf_reader import bulk_insert_rides
from ..db.crud import bulk_insert_rides

router = APIRouter(prefix="/upload", tags=["upload"])


@router.get("/", name="upload_page")
def upload_page(request: Request):
    return HTMLResponse("""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Upload Payroll PDF</title>
  <style>
    :root { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; }
    body { max-width: 780px; margin: 40px auto; padding: 0 16px; }
    .card { border: 1px solid #eee; border-radius: 12px; padding: 20px; }
    .row { display:flex; gap:12px; align-items:center; flex-wrap:wrap; }
    .btn { background:#0b6; color:#fff; border:0; padding:10px 16px; border-radius:10px; cursor:pointer; }
    .btn[disabled] { opacity:.6; cursor:not-allowed; }
    .muted { color:#666; font-size: .9rem; }
    .drop { border:2px dashed #ccc; padding:20px; text-align:center; border-radius:12px; margin:12px 0;}
    .drop.drag { border-color:#0b6; background:#f6fffb; }
    pre { background:#111; color:#e7e7e7; padding:12px; border-radius:10px; overflow:auto; max-height: 360px;}
    .nav { margin: 16px 0; }
    .nav a { margin-right:10px; color:#0b6; text-decoration:none; }
  </style>
</head>
<body>
  <h1>Upload Payroll PDF</h1>
  <p class="muted">Select the batch PDF (the one with the <em>Details</em> grid) and click Upload. We’ll parse rides and save to the database.</p>

  <div class="card">
    <div id="drop" class="drop">Drag & drop PDF here, or use the button below</div>
    <div class="row">
      <input id="file" type="file" accept="application/pdf" />
      <button id="btn" class="btn">Upload PDF</button>
      <label class="muted"><input id="pretty" type="checkbox" /> Pretty-print</label>
    </div>
    <div id="status" class="muted" style="margin-top:8px;"></div>
    <pre id="out" hidden></pre>
  </div>

  <div class="nav">
    <a href="/people">People</a>
    <a href="/summary">Summary</a>
    <a href="/docs">API Docs</a>
  </div>

<script>
const fileInput = document.getElementById('file');
const btn = document.getElementById('btn');
const out = document.getElementById('out');
const pretty = document.getElementById('pretty');
const statusEl = document.getElementById('status');
const drop = document.getElementById('drop');

// When the router is mounted with prefix="/upload", this absolute path is correct:
const endpoint = "/upload/pdf";

function setStatus(msg){ statusEl.textContent = msg || ""; }
function setOutput(obj){
  out.hidden = false;
  out.textContent = pretty.checked
    ? JSON.stringify(obj, null, 2)
    : JSON.stringify(obj);
}

async function send(file){
  if(!file){ setStatus("Pick a PDF first."); return; }
  if(file.type !== "application/pdf" && !file.name.endsWith(".pdf")){
    setStatus("Please upload a .pdf file."); return;
  }
  btn.disabled = true; setStatus("Uploading…");
  const fd = new FormData();
  fd.append("file", file, file.name);
  try{
    const res = await fetch(endpoint, { method: "POST", body: fd });
    const data = await res.json().catch(()=> ({}));
    setOutput(data);
    setStatus(res.ok ? "Done." : `Error ${res.status}`);
  }catch(err){
    setStatus("Network error: " + err);
  }finally{
    btn.disabled = false;
  }
}

btn.addEventListener('click', () => send(fileInput.files[0]));
pretty.addEventListener('change', () => {
  if(out.hidden) return;
  try {
    const obj = JSON.parse(out.textContent);
    out.textContent = pretty.checked ? JSON.stringify(obj, null, 2) : JSON.stringify(obj);
  } catch(_) {}
});

['dragenter','dragover'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); e.stopPropagation(); drop.classList.add('drag'); }));
['dragleave','drop'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); e.stopPropagation(); drop.classList.remove('drag'); }));
drop.addEventListener('drop', e => {
  const f = e.dataTransfer?.files?.[0];
  if(f){ fileInput.files = e.dataTransfer.files; setStatus(`Selected: ${f.name}`); }
});
</script>
</body></html>
    """)

# -------- Upload API (POST) --------
# NOTE: because we mount this router with prefix="/upload", this path becomes /upload/pdf
@router.post("/pdf", name="upload_pdf")
async def upload_pdf(
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
        rides_data = extract_tables(raw)
        result = bulk_insert_rides(db, rides_data)
        #rides_df = normalize_details_tables(tables, source_file=file.filename)

    except Exception as e:
        return JSONResponse(status_code=400, content={
            "detail": {
                "error": "pdf_parse_failed",
                "message": str(e),
                "filename": file.filename
            }
        })
    return {
        "ok": True,
        "filename": file.filename,
        "detected_rows": len(records),
        "inserted": inserted,
        "skipped_duplicates": skipped,
        "people": by_person
    }
    """
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
    """