from pathlib import Path
from datetime import date

from fastapi import APIRouter, Depends, Form, Request, Query
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import Person
from backend.services import everdriven_service
from backend.services.everdriven_service import EverDrivenAuthError

router = APIRouter(prefix="/dispatch/everdriven", tags=["dispatch-everdriven"])

_templates = None


def templates():
    global _templates
    if _templates is None:
        templates_dir = Path(__file__).resolve().parents[1] / "templates"
        _templates = Jinja2Templates(directory=str(templates_dir))
    return _templates


@router.get("/", name="dispatch_everdriven_page")
def dispatch_everdriven_page(
    request: Request,
    for_date: date | None = Query(None, alias="date"),
    db: Session = Depends(get_db),
):
    target_date = for_date or date.today()

    # Fetch live runs from EverDriven
    try:
        runs      = everdriven_service.get_runs(target_date)
        dashboard = everdriven_service.get_dashboard(target_date)
        ed_ok     = True
        auth_needed = False
    except EverDrivenAuthError:
        runs        = []
        dashboard   = {}
        ed_ok       = False
        auth_needed = True
    except Exception:
        runs        = []
        dashboard   = {}
        ed_ok       = False
        auth_needed = False

    # Build driver-code → runs map
    driver_run_map: dict[str, list] = {}
    for run in runs:
        did = run.get("driverId")
        if not did:
            continue
        driver_run_map.setdefault(did, []).append(run)

    # Load DB drivers who have an everdriven_driver_id
    db_drivers = (
        db.query(Person)
        .filter(Person.everdriven_driver_id.isnot(None))
        .order_by(Person.full_name.asc())
        .all()
    )

    # Merge DB info with live schedule
    drivers = []
    for p in db_drivers:
        run_list = driver_run_map.get(str(p.everdriven_driver_id), [])
        run_list_sorted = sorted(
            run_list,
            key=lambda r: r.get("firstPickUp") or "99:99"
        )
        drivers.append({
            "person_id":         p.person_id,
            "name":              p.full_name,
            "email":             p.email or "",
            "phone":             p.phone or "",
            "address":           p.home_address or "",
            "everdriven_id":     p.everdriven_driver_id,
            "trips":             run_list_sorted,
            "trip_count":        len(run_list_sorted),
        })

    # Runs with no matched DB driver
    matched_ids = {str(p.everdriven_driver_id) for p in db_drivers}
    unassigned = [r for r in runs if r.get("driverId") not in matched_ids]

    return templates().TemplateResponse(
        request,
        "dispatch_everdriven.html",
        {
            "drivers":      drivers,
            "dashboard":    dashboard,
            "unassigned":   unassigned,
            "target_date":  target_date,
            "ed_ok":        ed_ok,
            "auth_needed":  auth_needed,
        },
    )


@router.get("/auth", name="dispatch_everdriven_auth")
def dispatch_everdriven_auth_page(request: Request):
    return templates().TemplateResponse(
        request,
        "dispatch_everdriven_auth.html",
        {},
    )


@router.post("/auth", name="dispatch_everdriven_auth_submit")
async def dispatch_everdriven_auth_submit(
    request: Request,
    username: str | None = Form(None),
    password: str | None = Form(None),
):
    # Support both Form data (Jinja2 templates) and JSON (Next.js frontend)
    if not username or not password:
        try:
            body = await request.json()
            username = body.get("email") or body.get("username", "")
            password = body.get("password", "")
        except Exception:
            pass

    if not username or not password:
        return JSONResponse({"error": "Email and password required"}, status_code=400)

    error = None
    try:
        import asyncio
        import concurrent.futures

        def _login_in_thread(u, p):
            asyncio.set_event_loop(asyncio.new_event_loop())
            everdriven_service._login_via_playwright(u, p)

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _login_in_thread, username, password)
    except EverDrivenAuthError as e:
        error = str(e)
    except Exception as e:
        error = f"Login failed: {e}"

    # JSON response for API clients
    accept = request.headers.get("accept", "")
    content_type = request.headers.get("content-type", "")
    is_json = "json" in accept or "json" in content_type

    if error:
        if is_json:
            return JSONResponse({"error": error}, status_code=400)
        return templates().TemplateResponse(
            request,
            "dispatch_everdriven_auth.html",
            {"error": error},
            status_code=400,
        )

    if is_json:
        return JSONResponse({"ok": True})
    return RedirectResponse(url="/dispatch/everdriven/", status_code=303)


# ---------------------------------------------------------------------------
# Driver sync endpoints
# ---------------------------------------------------------------------------

@router.get("/sync-drivers", name="dispatch_everdriven_sync_drivers_preview")
def dispatch_everdriven_sync_drivers_preview(db: Session = Depends(get_db)):
    """
    Preview mode — fetch the driver list from EverDriven and return it as JSON
    without writing anything to the database. Useful for debugging the API shape.
    """
    try:
        drivers = everdriven_service.get_all_drivers()
    except EverDrivenAuthError as e:
        return JSONResponse({"error": str(e), "auth_required": True}, status_code=401)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    return JSONResponse({
        "count": len(drivers),
        "drivers": drivers,
    })


@router.post("/sync-drivers", name="dispatch_everdriven_sync_drivers")
def dispatch_everdriven_sync_drivers(db: Session = Depends(get_db)):
    """
    Fetch all drivers from EverDriven and sync them into the Person table:

    - If a Person with a matching full_name (case-insensitive) exists and has no
      everdriven_driver_id, set it from the driver's keyValue.
    - If no Person matches, create a new one with name/email/phone from EverDriven.
    - Drivers whose Person record already has an everdriven_driver_id are skipped.

    Returns a JSON summary: {matched, created, skipped, drivers}
    """
    try:
        ed_drivers = everdriven_service.get_all_drivers()
    except EverDrivenAuthError as e:
        return JSONResponse({"error": str(e), "auth_required": True}, status_code=401)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    matched = 0
    created = 0
    skipped = 0
    result_drivers = []

    for drv in ed_drivers:
        driver_name  = (drv.get("driverName") or "").strip()
        driver_code  = drv.get("driverCode")   # integer ID we store in everdriven_driver_id

        if not driver_name or driver_code is None:
            skipped += 1
            result_drivers.append({**drv, "action": "skipped", "reason": "missing name or driverCode"})
            continue

        try:
            driver_code_int = int(driver_code)
        except (ValueError, TypeError):
            skipped += 1
            result_drivers.append({**drv, "action": "skipped", "reason": f"non-integer driverCode: {driver_code}"})
            continue

        # Skip if this driverCode is already linked to any person
        already_linked = (
            db.query(Person)
            .filter(Person.everdriven_driver_id == driver_code_int)
            .first()
        )
        if already_linked:
            skipped += 1
            result_drivers.append({**drv, "action": "skipped", "reason": "driverCode already linked", "person_id": already_linked.person_id})
            continue

        # Normalize name: collapse whitespace + lower for matching
        norm = " ".join(driver_name.lower().split())

        # Match by normalized name (handles double-spaces and case differences)
        person = (
            db.query(Person)
            .filter(
                func.lower(func.regexp_replace(func.trim(Person.full_name), r'\s+', ' ', 'g')) == norm
            )
            .first()
        )

        if person:
            if person.everdriven_driver_id is not None:
                skipped += 1
                result_drivers.append({
                    **drv,
                    "action": "skipped",
                    "reason": "already has everdriven_driver_id",
                    "person_id": person.person_id,
                })
            else:
                person.everdriven_driver_id = driver_code_int
                db.add(person)
                matched += 1
                result_drivers.append({
                    **drv,
                    "action": "matched",
                    "person_id": person.person_id,
                })
        else:
            # Create new Person; skip if name collision (race condition or duplicate)
            new_person = Person(
                full_name=driver_name,
                everdriven_driver_id=driver_code_int,
                active=True,
            )
            db.add(new_person)
            try:
                db.flush()
                created += 1
                result_drivers.append({
                    **drv,
                    "action": "created",
                    "person_id": new_person.person_id,
                })
            except IntegrityError:
                db.rollback()
                # Name already exists — find that person and link them
                person2 = (
                    db.query(Person)
                    .filter(
                        func.lower(func.regexp_replace(func.trim(Person.full_name), r'\s+', ' ', 'g')) == norm
                    )
                    .first()
                )
                if person2 and person2.everdriven_driver_id is None:
                    person2.everdriven_driver_id = driver_code_int
                    db.add(person2)
                    matched += 1
                    result_drivers.append({**drv, "action": "matched_after_retry", "person_id": person2.person_id})
                else:
                    skipped += 1
                    result_drivers.append({**drv, "action": "skipped", "reason": "name collision"})

    db.commit()

    return JSONResponse({
        "matched": matched,
        "created": created,
        "skipped": skipped,
        "total_from_everdriven": len(ed_drivers),
        "drivers": result_drivers,
    })
