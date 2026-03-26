from pathlib import Path
from datetime import date

from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import Person
from backend.services import firstalt_service
from backend.services import everdriven_service
from backend.services.everdriven_service import EverDrivenAuthError

router = APIRouter(prefix="/dispatch", tags=["dispatch"])

_templates = None
def templates():
    global _templates
    if _templates is None:
        templates_dir = Path(__file__).resolve().parents[1] / "templates"
        _templates = Jinja2Templates(directory=str(templates_dir))
    return _templates


def _ed_count(runs: list[dict], keyword: str) -> int:
    return sum(1 for r in runs if keyword.lower() in (r.get("tripStatus") or "").lower())


@router.get("/", name="dispatch_page")
def dispatch_page(
    request: Request,
    for_date: date | None = Query(None, alias="date"),
    source: str | None = Query(None),   # "firstalt" | "everdriven" | None = all
    db: Session = Depends(get_db),
):
    target_date = for_date or date.today()

    # ── FirstAlt ──────────────────────────────────────────────────────────────
    fa_error: str | None = None
    fa_trips: list[dict] = []
    fa_dashboard: dict = {}
    try:
        fa_trips = firstalt_service.get_trips(target_date)
        fa_dashboard = firstalt_service.get_dashboard(target_date)
        fa_ok = True
    except Exception as e:
        fa_ok = False
        fa_error = f"{type(e).__name__}: {e}"

    # ── EverDriven ────────────────────────────────────────────────────────────
    ed_error: str | None = None
    ed_runs: list[dict] = []
    ed_auth_needed = False
    try:
        ed_runs = everdriven_service.get_runs(target_date)
        ed_ok = True
    except EverDrivenAuthError:
        ed_ok = False
        ed_auth_needed = True
    except Exception as e:
        ed_ok = False
        ed_error = f"{type(e).__name__}: {e}"

    # ── Build lookup maps ─────────────────────────────────────────────────────
    fa_trip_map: dict[int, list] = {}
    for t in fa_trips:
        did = t.get("driverId")
        if did is not None:
            fa_trip_map.setdefault(did, []).append(t)

    ed_run_map: dict[str, list] = {}
    for r in ed_runs:
        did = r.get("driverId")
        if did is not None:
            ed_run_map.setdefault(str(did), []).append(r)

    # ── Load persons that have at least one dispatch ID ───────────────────────
    db_persons = (
        db.query(Person)
        .filter(
            (Person.firstalt_driver_id.isnot(None)) |
            (Person.everdriven_driver_id.isnot(None))
        )
        .order_by(Person.full_name.asc())
        .all()
    )

    # ── Merge into unified driver cards ───────────────────────────────────────
    drivers = []
    for p in db_persons:
        fa_list = sorted(
            fa_trip_map.get(p.firstalt_driver_id, []),
            key=lambda t: t.get("firstPickUp") or "99:99",
        )
        ed_list = sorted(
            ed_run_map.get(str(p.everdriven_driver_id or ""), []),
            key=lambda r: r.get("firstPickUp") or "99:99",
        )

        for t in fa_list:
            t["_source"] = "firstalt"
        for r in ed_list:
            r["_source"] = "everdriven"

        all_trips = sorted(
            fa_list + ed_list,
            key=lambda x: x.get("firstPickUp") or "99:99",
        )

        sources = []
        if p.firstalt_driver_id is not None:
            sources.append("firstalt")
        if p.everdriven_driver_id is not None:
            sources.append("everdriven")

        drivers.append({
            "person_id":     p.person_id,
            "name":          p.full_name,
            "email":         p.email or "",
            "phone":         p.phone or "",
            "address":       p.home_address or "",
            "firstalt_id":   p.firstalt_driver_id,
            "everdriven_id": p.everdriven_driver_id,
            "sources":       sources,
            "trips":         all_trips,
            "trip_count":    len(all_trips),
        })

    # Apply source filter
    if source == "firstalt":
        drivers = [d for d in drivers if "firstalt" in d["sources"]]
    elif source == "everdriven":
        drivers = [d for d in drivers if "everdriven" in d["sources"]]

    # Drivers with trips today first, then alphabetical
    drivers.sort(key=lambda d: (0 if d["trip_count"] > 0 else 1, d["name"].lower()))

    # ── Unassigned ────────────────────────────────────────────────────────────
    assigned_fa_ids = {p.firstalt_driver_id for p in db_persons if p.firstalt_driver_id}
    assigned_ed_ids = {str(p.everdriven_driver_id) for p in db_persons if p.everdriven_driver_id}

    unassigned = (
        [t for t in fa_trips if t.get("driverId") not in assigned_fa_ids]
        + [r for r in ed_runs if str(r.get("driverId", "")) not in assigned_ed_ids]
    )

    # ── Combined dashboard ────────────────────────────────────────────────────
    fa_counts = fa_dashboard.get("tripsCount", {})
    dashboard = {
        "total":     (fa_counts.get("TOTAL") or 0) + len(ed_runs),
        "completed": (fa_counts.get("COMPLETED") or 0) + _ed_count(ed_runs, "Completed"),
        "active":    (fa_counts.get("IN_PROGRESS") or 0) + _ed_count(ed_runs, "ToStop") + _ed_count(ed_runs, "AtStop"),
        "scheduled": (fa_counts.get("SCHEDULED") or 0) + _ed_count(ed_runs, "Active"),
        "cancelled": (fa_counts.get("CANCELLED") or 0) + _ed_count(ed_runs, "Declined"),
        "fa_total":  fa_counts.get("TOTAL") or 0,
        "ed_total":  len(ed_runs),
    }

    return templates().TemplateResponse(
        request,
        "dispatch.html",
        {
            "drivers":        drivers,
            "dashboard":      dashboard,
            "unassigned":     unassigned,
            "target_date":    target_date,
            "source_filter":  source,
            "fa_ok":          fa_ok,
            "fa_error":       fa_error,
            "ed_ok":          ed_ok,
            "ed_error":       ed_error,
            "ed_auth_needed": ed_auth_needed,
        },
    )


# ---------------------------------------------------------------------------
# FirstAlt driver sync endpoints
# ---------------------------------------------------------------------------

@router.get("/sync-drivers/firstalt", name="dispatch_sync_drivers_firstalt_preview")
def dispatch_sync_drivers_firstalt_preview(db: Session = Depends(get_db)):
    """
    Preview mode — fetch the driver list from FirstAlt and return it as JSON
    without writing anything to the database. Useful for inspecting the API shape.
    """
    try:
        drivers = firstalt_service.get_all_drivers()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    return JSONResponse({
        "count": len(drivers),
        "drivers": drivers,
    })


@router.post("/sync-drivers/firstalt", name="dispatch_sync_drivers_firstalt")
def dispatch_sync_drivers_firstalt(db: Session = Depends(get_db)):
    """
    Fetch all drivers from FirstAlt and sync them into the Person table:

    - If a Person with a matching full_name (case-insensitive, whitespace-collapsed)
      exists and has no firstalt_driver_id, set it from the driver record.
    - If no Person matches, create a new one.
    - Drivers whose Person record already has a firstalt_driver_id are skipped.

    Returns a JSON summary: {matched, created, skipped, total_from_firstalt, drivers}
    """
    try:
        fa_drivers = firstalt_service.get_all_drivers()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    matched = 0
    created = 0
    skipped = 0
    result_drivers = []

    for drv in fa_drivers:
        # FirstAlt driver records may use different field names — handle both
        driver_name = (
            drv.get("driverName")
            or drv.get("name")
            or drv.get("fullName")
            or ""
        ).strip()
        driver_code = drv.get("driverId") or drv.get("driverCode") or drv.get("id")

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
            .filter(Person.firstalt_driver_id == driver_code_int)
            .first()
        )
        if already_linked:
            skipped += 1
            result_drivers.append({
                **drv,
                "action": "skipped",
                "reason": "driverCode already linked",
                "person_id": already_linked.person_id,
            })
            continue

        # Normalize name: collapse whitespace + lower for matching
        norm = " ".join(driver_name.lower().split())

        # Match by normalized name
        person = (
            db.query(Person)
            .filter(
                func.lower(func.regexp_replace(func.trim(Person.full_name), r'\s+', ' ', 'g')) == norm
            )
            .first()
        )

        if person:
            if person.firstalt_driver_id is not None:
                skipped += 1
                result_drivers.append({
                    **drv,
                    "action": "skipped",
                    "reason": "already has firstalt_driver_id",
                    "person_id": person.person_id,
                })
            else:
                person.firstalt_driver_id = driver_code_int
                db.add(person)
                matched += 1
                result_drivers.append({
                    **drv,
                    "action": "matched",
                    "person_id": person.person_id,
                })
        else:
            # Create new Person; use savepoint to handle race-condition duplicates
            new_person = Person(
                full_name=driver_name,
                firstalt_driver_id=driver_code_int,
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
                if person2 and person2.firstalt_driver_id is None:
                    person2.firstalt_driver_id = driver_code_int
                    db.add(person2)
                    matched += 1
                    result_drivers.append({
                        **drv,
                        "action": "matched_after_retry",
                        "person_id": person2.person_id,
                    })
                else:
                    skipped += 1
                    result_drivers.append({**drv, "action": "skipped", "reason": "name collision"})

    db.commit()

    return JSONResponse({
        "matched": matched,
        "created": created,
        "skipped": skipped,
        "total_from_firstalt": len(fa_drivers),
        "drivers": result_drivers,
    })
