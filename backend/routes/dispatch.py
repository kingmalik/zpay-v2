import asyncio
import time
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

# ---------------------------------------------------------------------------
# In-memory dispatch cache
# ---------------------------------------------------------------------------
_dispatch_cache: dict = {}
CACHE_TTL = 90  # seconds

_templates = None
def templates():
    global _templates
    if _templates is None:
        templates_dir = Path(__file__).resolve().parents[1] / "templates"
        _templates = Jinja2Templates(directory=str(templates_dir))
    return _templates


def _ed_count(runs: list[dict], keyword: str) -> int:
    return sum(1 for r in runs if keyword.lower() in (r.get("tripStatus") or "").lower())


async def _fetch_dispatch_data(target_date: date, force_refresh: bool = False) -> dict:
    """
    Fetch trips from both FirstAlt and EverDriven concurrently.
    Returns cached data if fresh (< CACHE_TTL seconds old) unless force_refresh.
    Each source is caught independently so one failure does not block the other.
    """
    cache_key = str(target_date)
    cached = _dispatch_cache.get(cache_key)
    if cached and not force_refresh:
        age = time.time() - cached["ts"]
        if age < CACHE_TTL:
            return cached

    # Run both fetches concurrently in threads (both services are synchronous)
    fa_result, ed_result = await asyncio.gather(
        asyncio.to_thread(firstalt_service.get_trips, target_date),
        asyncio.to_thread(everdriven_service.get_runs, target_date),
        return_exceptions=True,
    )

    # Also fetch FA dashboard concurrently (lightweight, but parallelise anyway)
    fa_dashboard_result = await asyncio.to_thread(
        firstalt_service.get_dashboard, target_date
    ) if not isinstance(fa_result, Exception) else {}

    # --- FirstAlt result ---
    fa_trips: list[dict] = []
    fa_ok = False
    fa_error: str | None = None
    if isinstance(fa_result, Exception):
        fa_error = f"{type(fa_result).__name__}: {fa_result}"
    else:
        fa_trips = fa_result or []
        fa_ok = True

    # --- EverDriven result ---
    ed_runs: list[dict] = []
    ed_ok = False
    ed_error: str | None = None
    ed_auth_needed = False
    if isinstance(ed_result, Exception):
        if isinstance(ed_result, EverDrivenAuthError):
            ed_auth_needed = True
        else:
            ed_error = f"{type(ed_result).__name__}: {ed_result}"
    else:
        ed_runs = ed_result or []
        ed_ok = True

    fa_dashboard: dict = fa_dashboard_result if isinstance(fa_dashboard_result, dict) else {}

    payload = {
        "ts": time.time(),
        "fa_trips": fa_trips,
        "fa_dashboard": fa_dashboard,
        "fa_ok": fa_ok,
        "fa_error": fa_error,
        "ed_runs": ed_runs,
        "ed_ok": ed_ok,
        "ed_error": ed_error,
        "ed_auth_needed": ed_auth_needed,
    }
    _dispatch_cache[cache_key] = payload
    return payload


def _build_driver_cards(
    data: dict,
    db_persons: list,
    source: str | None,
) -> tuple[list[dict], list[dict], dict]:
    """
    Merge API data with DB persons into unified driver cards.
    Returns (drivers, unassigned, dashboard).
    """
    fa_trips = data["fa_trips"]
    ed_runs = data["ed_runs"]
    fa_dashboard = data["fa_dashboard"]

    # Build lookup maps
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
            "address":       getattr(p, "home_address", "") or "",
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

    # Unassigned
    assigned_fa_ids = {p.firstalt_driver_id for p in db_persons if p.firstalt_driver_id}
    assigned_ed_ids = {str(p.everdriven_driver_id) for p in db_persons if p.everdriven_driver_id}

    unassigned = (
        [t for t in fa_trips if t.get("driverId") not in assigned_fa_ids]
        + [r for r in ed_runs if str(r.get("driverId", "")) not in assigned_ed_ids]
    )

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

    return drivers, unassigned, dashboard


def _auto_link_drivers(data: dict, db_persons: list, db: Session) -> int:
    """
    Fix 4: Auto-link drivers by fuzzy name matching.

    - FA trips with a driverId not yet in Person.firstalt_driver_id:
      if the trip's driverName fuzzy-matches a Person that has everdriven_driver_id
      but no firstalt_driver_id → set firstalt_driver_id.
    - ED runs with a driverId not yet in Person.everdriven_driver_id:
      if the run's driverName fuzzy-matches a Person that has firstalt_driver_id
      but no everdriven_driver_id → set everdriven_driver_id.

    Returns the number of links created.
    """
    assigned_fa = {p.firstalt_driver_id for p in db_persons if p.firstalt_driver_id}
    assigned_ed = {p.everdriven_driver_id for p in db_persons if p.everdriven_driver_id}

    # Build name → person lookup for quick fuzzy checks
    def _norm(name: str) -> str:
        return " ".join(name.lower().split()) if name else ""

    # Persons missing firstalt_driver_id (have ED, not FA)
    ed_only_persons = {
        _norm(p.full_name): p
        for p in db_persons
        if p.everdriven_driver_id is not None and p.firstalt_driver_id is None
    }
    # Persons missing everdriven_driver_id (have FA, not ED)
    fa_only_persons = {
        _norm(p.full_name): p
        for p in db_persons
        if p.firstalt_driver_id is not None and p.everdriven_driver_id is None
    }

    linked = 0

    # Scan FA trips for unassigned drivers and try to match them to ED-only persons
    for t in data["fa_trips"]:
        did = t.get("driverId")
        if did is None or did in assigned_fa:
            continue
        raw_name = (
            t.get("driverName")
            or t.get("driver_name")
            or t.get("name")
            or ""
        ).strip()
        if not raw_name:
            continue
        norm_name = _norm(raw_name)
        match = ed_only_persons.get(norm_name)
        if match and match.firstalt_driver_id is None:
            try:
                match.firstalt_driver_id = int(did)
                db.add(match)
                db.flush()
                assigned_fa.add(did)
                del ed_only_persons[norm_name]
                linked += 1
            except Exception:
                db.rollback()

    # Scan ED runs for unassigned drivers and try to match them to FA-only persons
    for r in data["ed_runs"]:
        did = r.get("driverId")
        if did is None or did in assigned_ed:
            continue
        raw_name = (
            r.get("driverName")
            or r.get("driver_name")
            or r.get("name")
            or ""
        ).strip()
        if not raw_name:
            continue
        norm_name = _norm(raw_name)
        match = fa_only_persons.get(norm_name)
        if match and match.everdriven_driver_id is None:
            try:
                match.everdriven_driver_id = int(did)
                db.add(match)
                db.flush()
                assigned_ed.add(did)
                del fa_only_persons[norm_name]
                linked += 1
            except Exception:
                db.rollback()

    if linked:
        db.commit()

    return linked


def _auto_create_persons(data: dict, db_persons: list, db: Session) -> int:
    """
    For every FA trip or ED run whose driverId has no Person record at all,
    create a minimal Person card so the driver shows up in the roster.
    Returns the number of new Person records created.
    """
    assigned_fa = {p.firstalt_driver_id for p in db_persons if p.firstalt_driver_id}
    assigned_ed = {p.everdriven_driver_id for p in db_persons if p.everdriven_driver_id}

    created = 0

    def _get_name(obj: dict) -> str:
        return (
            obj.get("driverName")
            or obj.get("driver_name")
            or obj.get("name")
            or ""
        ).strip()

    seen_names: set[str] = set()

    # FirstAlt drivers with no Person
    for t in data["fa_trips"]:
        did = t.get("driverId")
        if did is None or did in assigned_fa:
            continue
        name = _get_name(t)
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        try:
            person = Person(full_name=name, firstalt_driver_id=int(did))
            db.add(person)
            db.flush()
            assigned_fa.add(did)
            created += 1
        except Exception:
            db.rollback()

    # EverDriven drivers with no Person
    for r in data["ed_runs"]:
        did = r.get("driverId")
        if did is None or int(did) in assigned_ed:
            continue
        name = _get_name(r)
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        try:
            person = Person(full_name=name, everdriven_driver_id=int(did))
            db.add(person)
            db.flush()
            assigned_ed.add(int(did))
            created += 1
        except Exception:
            db.rollback()

    if created:
        db.commit()

    return created


def _load_db_persons(db: Session) -> list:
    return (
        db.query(Person)
        .filter(
            (Person.firstalt_driver_id.isnot(None)) |
            (Person.everdriven_driver_id.isnot(None))
        )
        .order_by(Person.full_name.asc())
        .all()
    )


# ---------------------------------------------------------------------------
# Main dispatch page  (Fix 1: concurrent fetch + cache)
# ---------------------------------------------------------------------------

@router.get("/", name="dispatch_page")
async def dispatch_page(
    request: Request,
    for_date: date | None = Query(None, alias="date"),
    source: str | None = Query(None),
    refresh: int = Query(0),
    db: Session = Depends(get_db),
):
    target_date = for_date or date.today()
    force = bool(refresh)

    data = await _fetch_dispatch_data(target_date, force_refresh=force)

    db_persons = _load_db_persons(db)

    # Auto-link unassigned drivers whose names match existing persons
    _auto_link_drivers(data, db_persons, db)
    # Auto-create Person cards for any driver with no record at all
    _auto_create_persons(data, db_persons, db)
    # Re-load after potential links/creates
    db_persons = _load_db_persons(db)

    drivers, unassigned, dashboard = _build_driver_cards(data, db_persons, source)

    last_updated = int(time.time() - data["ts"])

    return templates().TemplateResponse(
        request,
        "dispatch.html",
        {
            "drivers":        drivers,
            "dashboard":      dashboard,
            "unassigned":     unassigned,
            "target_date":    target_date,
            "source_filter":  source,
            "fa_ok":          data["fa_ok"],
            "fa_error":       data["fa_error"],
            "ed_ok":          data["ed_ok"],
            "ed_error":       data["ed_error"],
            "ed_auth_needed": data["ed_auth_needed"],
            "last_updated":   last_updated,
            "cache_ttl":      CACHE_TTL,
        },
    )


# ---------------------------------------------------------------------------
# Fix 2: /dispatch/data  — JSON endpoint for auto-refresh polling
# ---------------------------------------------------------------------------

@router.get("/data", name="dispatch_data")
async def dispatch_data(
    for_date: date | None = Query(None, alias="date"),
    source: str | None = Query(None),
    refresh: int = Query(0),
    db: Session = Depends(get_db),
):
    """
    Returns the same driver/trip data as the main dispatch page but as JSON.
    Used by the auto-refresh JS to update the driver grid without a full page reload.
    """
    target_date = for_date or date.today()
    force = bool(refresh)

    data = await _fetch_dispatch_data(target_date, force_refresh=force)

    db_persons = _load_db_persons(db)
    _auto_link_drivers(data, db_persons, db)
    _auto_create_persons(data, db_persons, db)
    db_persons = _load_db_persons(db)

    drivers, unassigned, dashboard = _build_driver_cards(data, db_persons, source)

    return JSONResponse({
        "drivers":      drivers,
        "dashboard":    dashboard,
        "unassigned":   unassigned,
        "fa_ok":        data["fa_ok"],
        "fa_error":     data["fa_error"],
        "ed_ok":        data["ed_ok"],
        "ed_error":     data["ed_error"],
        "ed_auth_needed": data["ed_auth_needed"],
        "last_updated": int(time.time() - data["ts"]),
        "cache_ttl":    CACHE_TTL,
    })


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


@router.post("/firstalt/accept-today", name="dispatch_firstalt_accept_today")
def dispatch_firstalt_accept_today():
    """
    Accept all open FirstAlt trips for today.
    Returns a summary of accepted, failed, and already-accepted trips.
    """
    try:
        result = firstalt_service.accept_all_trips()
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
