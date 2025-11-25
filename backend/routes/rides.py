from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from backend.db import get_db
from datetime import datetime

router = APIRouter()

def _row_to_dict(row):
    if hasattr(row, "__table__"):
        return {c.name: getattr(row, c.name) for c in row.__table__.columns}
    try:
        return dict(row._mapping)
    except Exception:
        return dict(row)

def _fmt_ts(ts):
    if not ts:
        return ""
    if isinstance(ts, str):
        return ts
    if isinstance(ts, datetime):
        # show local-ish ISO string without microseconds
        return ts.isoformat(timespec="seconds")
    return str(ts)

@router.get("/rides/data")
def rides_data(request: Request, person_id: Optional[int] = None, limit: int = 100, db: Session = Depends(get_db)):
    if person_id is None:
        raise HTTPException(status_code=400, detail="person_id is required")

    rows = db.execute(text("""
        SELECT person, code, date, key, name, miles, gross, net_pay
        FROM ride_report_v
        WHERE person_id = :pid
        ORDER BY date DESC, key DESC
        LIMIT :lim
    """), {"pid": person_id, "lim": limit}).mappings().all()

    items = [dict(r) for r in rows]
    payload = {"rows": items, "count": len(items)}

    wants_html = "text/html" in request.headers.get("accept", "") or request.query_params.get("view") == "html"
    if wants_html:
        # simple Tailwind table
        head = ["Person", "Code", "Date", "Key", "Name", "Miles", "Gross", "Net Pay"]
        body = "".join(
            f"""<tr class="border-b hover:bg-gray-50">
                <td class="px-3 py-2">{r['person'] or ''}</td>
                <td class="px-3 py-2 font-mono">{r.get('code') or ''}</td>
                <td class="px-3 py-2">{r['date']}</td>
                <td class="px-3 py-2 font-mono">{r.get('key') or ''}</td>
                <td class="px-3 py-2">{r.get('name') or ''}</td>
                <td class="px-3 py-2 text-right">{r.get('miles') or ''}</td>
                <td class="px-3 py-2 text-right">${r.get('gross') or 0:.2f}</td>
                <td class="px-3 py-2 text-right">${r.get('net_pay') or 0:.2f}</td>
              </tr>"""
            for r in items
        )
        html = f"""<!doctype html><html><head>
          <meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
          <title>Rides</title><script src="https://cdn.tailwindcss.com"></script>
        </head><body class="bg-gray-100">
          <div class="max-w-7xl mx-auto p-6">
            <h1 class="text-2xl font-semibold mb-4">Rides</h1>
            <div class="bg-white rounded-xl shadow overflow-x-auto">
              <table class="min-w-full text-sm">
                <thead class="bg-blue-700 text-white">
                  <tr>{"".join(f'<th class="px-3 py-2 text-left">{h}</th>' for h in head)}</tr>
                </thead>
                <tbody>{body or '<tr><td class="px-3 py-6 text-center text-gray-500" colspan="8">No data</td></tr>'}</tbody>
              </table>
            </div>
          </div>
        </body></html>"""
        return HTMLResponse(html)

    return JSONResponse(payload)