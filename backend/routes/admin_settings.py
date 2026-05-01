"""Admin settings — Paychex sync. (Email scheduling removed 2026-05-01 walk-through cleanup.)"""

import csv
import os
from pathlib import Path

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from backend.utils.roles import require_role
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import Person

router = APIRouter(prefix="/admin", tags=["admin-settings"], dependencies=[Depends(require_role("admin"))])

_templates_dir = Path(__file__).resolve().parents[1] / "templates"
_templates = Jinja2Templates(directory=str(_templates_dir))


# ── Paychex Worker ID Sync ─────────────────────────────────────────────────

def _normalize_name(name: str) -> str:
    """Normalize a name for fuzzy matching."""
    name = name.strip().lower()
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        name = f"{parts[1]} {parts[0]}"
    return name.replace(".", "").replace("  ", " ")


def _load_paychex_csv() -> dict:
    """Load Paychex workers from the CSV bundled in the repo."""
    csv_path = Path(__file__).resolve().parents[2] / "data" / "paychex_workers.csv"
    if not csv_path.exists():
        return {}
    workers = {}
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            workers[row["paychex_id"].strip()] = row["name"].strip()
    return workers


@router.get("/paychex-sync")
async def paychex_sync_page(request: Request, db: Session = Depends(get_db)):
    """Show current Paychex ID mapping status and allow sync."""
    _wants_json = (
        "application/json" in request.headers.get("content-type", "")
        or "application/json" in request.headers.get("accept", "")
    )

    paychex = _load_paychex_csv()
    paychex_norm = {_normalize_name(name): (pid, name) for pid, name in paychex.items()}

    persons = db.query(Person).filter(Person.active == True).all()

    matched = []
    unmatched = []
    already_set = []

    for person in persons:
        zpay_name = person.full_name or ""
        zpay_norm = _normalize_name(zpay_name)

        if person.paycheck_code:
            px_name = paychex.get(person.paycheck_code, "")
            already_set.append({
                "person_id": person.person_id,
                "zpay_name": zpay_name,
                "paychex_id": person.paycheck_code,
                "paychex_name": px_name,
            })
            continue

        # Try exact normalized match
        if zpay_norm in paychex_norm:
            pid, px_name = paychex_norm[zpay_norm]
            matched.append({
                "person_id": person.person_id,
                "zpay_name": zpay_name,
                "paychex_id": pid,
                "paychex_name": px_name,
            })
            continue

        # Try partial match (first + last)
        zpay_parts = zpay_norm.split()
        found = False
        for norm_name, (pid, px_name) in paychex_norm.items():
            px_parts = norm_name.split()
            if len(zpay_parts) >= 2 and len(px_parts) >= 2:
                if zpay_parts[0] == px_parts[0] and zpay_parts[-1] == px_parts[-1]:
                    matched.append({
                        "person_id": person.person_id,
                        "zpay_name": zpay_name,
                        "paychex_id": pid,
                        "paychex_name": px_name,
                    })
                    found = True
                    break

        if not found:
            unmatched.append({
                "person_id": person.person_id,
                "zpay_name": zpay_name,
            })

    applied = request.query_params.get("applied", "")

    if _wants_json:
        try:
            return JSONResponse({
                "matched": sorted(matched, key=lambda x: x["zpay_name"]),
                "unmatched": sorted(unmatched, key=lambda x: x["zpay_name"]),
                "already_set": sorted(already_set, key=lambda x: x["zpay_name"]),
                "paychex_count": len(paychex),
                "applied": applied,
            })
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    return _templates.TemplateResponse(request, "admin/paychex_sync.html", {
        "matched": sorted(matched, key=lambda x: x["zpay_name"]),
        "unmatched": sorted(unmatched, key=lambda x: x["zpay_name"]),
        "already_set": sorted(already_set, key=lambda x: x["zpay_name"]),
        "paychex_count": len(paychex),
        "applied": applied,
    })


@router.post("/paychex-sync/apply")
async def paychex_sync_apply(request: Request, db: Session = Depends(get_db)):
    """Apply all matched Paychex codes to the database."""
    paychex = _load_paychex_csv()
    paychex_norm = {_normalize_name(name): (pid, name) for pid, name in paychex.items()}

    persons = db.query(Person).filter(Person.active == True, Person.paycheck_code.is_(None)).all()
    updated = 0

    for person in persons:
        zpay_norm = _normalize_name(person.full_name or "")

        pid = None
        if zpay_norm in paychex_norm:
            pid = paychex_norm[zpay_norm][0]
        else:
            zpay_parts = zpay_norm.split()
            for norm_name, (px_id, _) in paychex_norm.items():
                px_parts = norm_name.split()
                if len(zpay_parts) >= 2 and len(px_parts) >= 2:
                    if zpay_parts[0] == px_parts[0] and zpay_parts[-1] == px_parts[-1]:
                        pid = px_id
                        break

        if pid:
            person.paycheck_code = pid
            updated += 1

    db.commit()
    return RedirectResponse(url=f"/admin/paychex-sync?applied={updated}", status_code=302)
