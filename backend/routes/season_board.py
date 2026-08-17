"""
S10 — Season Assignment Board API.

Contract lives in docs/SEASON-BOARD-PLAN.md §API — paths/shapes here mirror
it exactly, the frontend is built in parallel against this file. Auth: no
extra require_role, same precedent as backend/routes/assignment.py — global
AuthMiddleware already gates every /api/data/* path.

Endpoints span three surfaces under one router (prefix "/api/data"):
  - /season/*        board, import, loop propose/list/assign/dismiss, ride PATCH/unassign
  - /schools*         school address book
  - /people/capabilities*  driver equipment/skill flags
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, tuple_
from sqlalchemy.orm import Session, joinedload

from backend.db import get_db
from backend.db.models import (
    DriverLoop,
    Person,
    Ride,
    RouteBackup,
    RouteRoster,
    School,
    SeasonRide,
)
from backend.services import loop_builder
from backend.services.city_extract import extract_city
from backend.services.driver_suggest import (
    CandidateDriver,
    LoopShape,
    RideShape,
    suggest_drivers,
    suggest_for_ride,
)
from backend.services.loop_builder import Leg
from backend.services.school_service import apply_school_address, schools_overview
from backend.services.season_pool import (
    DEFAULT_SEASON,
    backfill_from_intakes,
    import_sheet,
)

router = APIRouter(prefix="/api/data", tags=["season-board"])

# person.capabilities keys (plan doc §Schema — person alter).
CAPABILITY_FLAG_KEYS = ("car_seat", "booster", "harness", "monitor_ok", "wheelchair_vehicle")

# season_ride.requires flag -> person.capabilities key (plan doc §Business rule 6).
_CAPABILITY_MAP = {
    "wheelchair": "wheelchair_vehicle",
    "monitor": "monitor_ok",
    "car_seat": "car_seat",
    "booster": "booster",
    "harness": "harness",
}

# Only wheelchair GATES assignment (Malik, 2026-08-06): car seat/booster/
# harness are equipment Maz hands the driver, and FirstAlt provides the
# monitor — the driver just gets told. A wheelchair ride physically needs
# a wheelchair vehicle; nothing else constrains who can take a ride. The
# other flags stay on rides/loops as tell-the-driver / hand-out-equipment
# info only.
_GATING_FLAGS = ("wheelchair",)


# ── shared helpers ───────────────────────────────────────────────────────────

def _name_lookup(db: Session, person_ids: set[int]) -> dict[int, str]:
    if not person_ids:
        return {}
    return {
        p.person_id: p.full_name
        for p in db.query(Person).filter(Person.person_id.in_(person_ids)).all()
    }


def _ride_out(ride: SeasonRide, name_lookup: dict[int, str]) -> dict:
    needs_address = not ride.pickup_city or not ride.dropoff_city
    needs_time = not ride.pickup_time or not ride.dropoff_time
    school_display = ride.school.display_name if ride.school is not None else ride.route_school
    assigned_person = None
    if ride.assigned_person_id:
        assigned_person = {
            "person_id": ride.assigned_person_id,
            "name": name_lookup.get(ride.assigned_person_id, "Unknown"),
        }
    return {
        "season_ride_id": ride.season_ride_id,
        "source": ride.source,
        "school_display": school_display,
        "direction": ride.route_direction,
        "number": ride.route_number,
        "is_odt": bool(ride.route_is_odt),
        "days": ride.days,
        "pickup_city": ride.pickup_city,
        "dropoff_city": ride.dropoff_city,
        "pickup_address": ride.pickup_address,
        "dropoff_address": ride.dropoff_address,
        "pickup_time": ride.pickup_time,
        "dropoff_time": ride.dropoff_time,
        "requires": ride.requires or {},
        "notes": ride.notes,
        "status": ride.status,
        "assigned_person": assigned_person,
        "loop_id": ride.loop_id,
        "needs": {"address": needs_address, "time": needs_time},
    }


def _leg_from_ride(ride: SeasonRide, resolve_school: bool = False) -> Leg:
    """Flatten a SeasonRide into the pure engine's Leg shape.

    resolve_school=True fills a missing side's city from the school's
    address by IB/OB sidedness (plan doc §API /loops/propose) — the board
    view (resolve_school=False) deliberately leaves gaps visible so the
    "needs" flags reflect real data, not a backfilled guess.
    """
    pickup_city = ride.pickup_city
    dropoff_city = ride.dropoff_city
    if resolve_school and ride.school is not None:
        if ride.route_direction == "IB" and not dropoff_city:
            dropoff_city = ride.school.city
        elif ride.route_direction == "OB" and not pickup_city:
            pickup_city = ride.school.city
    return Leg(
        ride_id=ride.season_ride_id,
        source=ride.source,
        school=ride.route_school,
        direction=ride.route_direction,
        number=ride.route_number,
        is_odt=bool(ride.route_is_odt),
        days=ride.days,
        pickup_city=pickup_city,
        dropoff_city=dropoff_city,
        pickup_time=ride.pickup_time,
        dropoff_time=ride.dropoff_time,
        requires=ride.requires or {},
    )


def _order_corridors(corridors_map: dict[tuple[str, str], list]) -> list[tuple[tuple[str, str], list]]:
    """Alphabetical by pickup_city; opposite corridor immediately follows
    (A->B then B->A) when both exist (plan doc §API /board)."""
    sorted_keys = sorted(corridors_map.keys(), key=lambda k: (k[0].lower(), k[1].lower()))
    emitted: set[tuple[str, str]] = set()
    ordered: list[tuple[tuple[str, str], list]] = []
    for key in sorted_keys:
        if key in emitted:
            continue
        ordered.append((key, corridors_map[key]))
        emitted.add(key)
        reverse_key = (key[1], key[0])
        if reverse_key in corridors_map and reverse_key not in emitted:
            ordered.append((reverse_key, corridors_map[reverse_key]))
            emitted.add(reverse_key)
    return ordered


_RIDE_STATUSES = ("unassigned", "assigned", "inactive")
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # season sheets are tiny; anything bigger is a mistake


async def _json_body(request: Request) -> dict:
    """Parse a JSON object body; malformed or non-object bodies are a client
    error (400), never an unhandled 500."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="request body must be valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object")
    return body


def _validate_day_part(value: Optional[str]) -> Optional[str]:
    if value is not None and value not in ("AM", "PM", "MID"):
        raise HTTPException(status_code=400, detail="day_part must be AM, PM, or MID")
    return value


def _validate_weekday(value: Optional[str]) -> Optional[str]:
    if value is not None and value not in loop_builder.ALL_WEEKDAYS:
        raise HTTPException(status_code=400, detail="weekday must be one of M,T,W,R,F")
    return value


# ── GET /season/board ────────────────────────────────────────────────────────

@router.get("/season/board")
def get_season_board(
    season: str = Query(DEFAULT_SEASON),
    district: Optional[str] = Query(None),
    day_part: Optional[str] = Query(None),
    weekday: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    _validate_day_part(day_part)
    _validate_weekday(weekday)

    all_rides = (
        db.query(SeasonRide)
        .options(joinedload(SeasonRide.school))
        .filter(SeasonRide.season == season)
        .all()
    )

    districts = sorted({r.school.district for r in all_rides if r.school and r.school.district})

    rides = all_rides
    if district:
        rides = [r for r in rides if r.school and r.school.district == district]
    if day_part:
        rides = [r for r in rides if loop_builder.day_part(_leg_from_ride(r)) == day_part]
    if weekday:
        rides = [r for r in rides if weekday in loop_builder.day_signature(_leg_from_ride(r))]

    name_lookup = _name_lookup(db, {r.assigned_person_id for r in rides if r.assigned_person_id})

    # Single-ride assignment mode (Malik's mom, 2026-08-17): at current volume
    # loops hand one driver four rides while others get zero, so each
    # unassigned ride carries best-fit driver suggestions ranked fairness-
    # first. Counts span the WHOLE season, unfiltered — board filters must
    # never hide a driver's existing load.
    ride_counts: dict[int, int] = {}
    for r in all_rides:
        if r.assigned_person_id and r.status == "assigned":
            ride_counts[r.assigned_person_id] = ride_counts.get(r.assigned_person_id, 0) + 1

    unassigned_with_time = [
        r for r in rides if r.status == "unassigned" and r.pickup_time and r.dropoff_time
    ]
    suggestions_by_ride = _ride_suggestions(db, season, unassigned_with_time, ride_counts)

    corridors_map: dict[tuple[str, str], list] = {}
    unplaced: list[dict] = []
    assigned_count = 0
    unassigned_count = 0

    for ride in rides:
        if ride.status == "assigned":
            assigned_count += 1
        elif ride.status == "unassigned":
            unassigned_count += 1

        ride_out = _ride_out(ride, name_lookup)
        if ride.season_ride_id in suggestions_by_ride:
            ride_out["suggestions"] = suggestions_by_ride[ride.season_ride_id]
        if ride_out["needs"]["address"] or ride_out["needs"]["time"]:
            unplaced.append(ride_out)
        else:
            key = (ride.pickup_city, ride.dropoff_city)
            corridors_map.setdefault(key, []).append(ride_out)

    corridors = [
        {"pickup_city": key[0], "dropoff_city": key[1], "rides": bucket}
        for key, bucket in _order_corridors(corridors_map)
    ]

    return JSONResponse({
        "stats": {
            "total": len(rides),
            "assigned": assigned_count,
            "unassigned": unassigned_count,
            "needs_info": len(unplaced),
        },
        "corridors": corridors,
        "unplaced": unplaced,
        "districts": districts,
        "driver_ride_counts": ride_counts,
    })


def _ride_suggestions(
    db: Session,
    season: str,
    unassigned: list[SeasonRide],
    ride_counts: dict[int, int],
) -> dict[int, list[dict]]:
    """Best-fit driver suggestions per unassigned ride (single-ride mode)."""
    if not unassigned:
        return {}

    # A driver's commitments for conflict checks: confirmed loops PLUS rides
    # assigned directly outside any loop — both mean "busy that day-part".
    commitments: dict[int, list[tuple[str, Optional[str]]]] = {}
    confirmed = (
        db.query(DriverLoop)
        .filter(DriverLoop.season == season,
                DriverLoop.status == "confirmed",
                DriverLoop.person_id.isnot(None))
        .all()
    )
    confirmed_ids = {cl.loop_id for cl in confirmed}
    for cl in confirmed:
        commitments.setdefault(cl.person_id, []).append((cl.day_part, cl.days))
    # Any assigned ride NOT inside a confirmed loop counts as a single-ride
    # commitment — including one still stamped with a proposed loop_id.
    single_assigned = (
        db.query(SeasonRide)
        .filter(SeasonRide.season == season,
                SeasonRide.status == "assigned",
                SeasonRide.assigned_person_id.isnot(None))
        .all()
    )
    for r in single_assigned:
        if r.loop_id in confirmed_ids:
            continue  # already counted via the confirmed loop above
        commitments.setdefault(r.assigned_person_id, []).append(
            (loop_builder.day_part(_leg_from_ride(r)), r.days)
        )

    candidates = [
        CandidateDriver(
            person_id=p.person_id,
            name=p.full_name,
            home_address=p.home_address,
            wheelchair_vehicle=bool((p.capabilities or {}).get("wheelchair_vehicle")),
            confirmed_loops=tuple(commitments.get(p.person_id, [])),
        )
        for p in _qualifying_people(db) if p.active
    ]
    if not candidates:
        return {}

    # Route familiarity from payroll history — same casing rule as list_loops.
    route_keys = {(r.route_school.lower(), r.route_number) for r in unassigned}
    history_by_route: dict[tuple[str, str], dict[int, int]] = {}
    if route_keys:
        hist_rows = (
            db.query(func.lower(Ride.route_school), Ride.route_number, Ride.person_id, func.count(Ride.ride_id))
            .filter(
                tuple_(func.lower(Ride.route_school), Ride.route_number).in_(list(route_keys)),
                Ride.person_id.isnot(None),
            )
            .group_by(func.lower(Ride.route_school), Ride.route_number, Ride.person_id)
            .all()
        )
        for school, number, pid, cnt in hist_rows:
            history_by_route.setdefault((school, number), {})[pid] = cnt

    out: dict[int, list[dict]] = {}
    for r in unassigned:
        shape = RideShape(
            day_part=loop_builder.day_part(_leg_from_ride(r)),
            days=r.days,
            requires_wheelchair=bool((r.requires or {}).get("wheelchair")),
            pickup_city=r.pickup_city,
            dropoff_city=r.dropoff_city,
        )
        prior = history_by_route.get((r.route_school.lower(), r.route_number), {})
        out[r.season_ride_id] = [
            s.as_dict()
            for s in suggest_for_ride(shape, candidates, ride_counts, prior_route_rides=prior)
        ]
    return out


# ── POST /season/import ──────────────────────────────────────────────────────

@router.post("/season/import")
async def import_season(request: Request, db: Session = Depends(get_db)):
    content_type = request.headers.get("content-type", "")
    schools_before = {sid for (sid,) in db.query(School.school_id).all()}

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise HTTPException(status_code=400, detail="file is required")
        file_bytes = await upload.read()
        if len(file_bytes) > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="sheet exceeds 10 MB limit")
        report = import_sheet(db, file_bytes, upload.filename or "upload.xlsx")
        db.commit()
        schools_after = {sid for (sid,) in db.query(School.school_id).all()}
        payload = report.as_dict()
        payload["schools_created"] = len(schools_after - schools_before)
        return JSONResponse(payload)

    body = await _json_body(request)
    if not body.get("from_intake"):
        raise HTTPException(
            status_code=400,
            detail="multipart file or {'from_intake': true} required",
        )

    season = body.get("season") or DEFAULT_SEASON
    result = backfill_from_intakes(db, season=season)
    db.commit()
    schools_after = {sid for (sid,) in db.query(School.school_id).all()}
    payload = {
        "total_rows": result["processed"],
        # backfill_from_intakes doesn't distinguish new-vs-updated rows —
        # "created" here is rows upserted (see report note in final summary).
        "created": result["rows"],
        "updated": 0,
        "errors": result["errors"],
        "schools_created": len(schools_after - schools_before),
    }
    return JSONResponse(payload)


# ── POST /season/loops/propose ───────────────────────────────────────────────

@router.post("/season/loops/propose")
async def propose_loops(request: Request, db: Session = Depends(get_db)):
    body = await _json_body(request)

    season = body.get("season") or DEFAULT_SEASON
    day_part_filter = _validate_day_part(body.get("day_part"))
    weekday_filter = _validate_weekday(body.get("weekday"))

    confirmed_loop_ids = {
        lid for (lid,) in db.query(DriverLoop.loop_id).filter(DriverLoop.status == "confirmed").all()
    }

    candidate_rides = (
        db.query(SeasonRide)
        .options(joinedload(SeasonRide.school))
        .filter(SeasonRide.season == season)
        .filter(SeasonRide.status.in_(("unassigned", "assigned")))
        .all()
    )
    # Exclude confirmed-loop rides AND single-assigned rides — a ride mom
    # hand-assigned via the picker must never be regrouped into a proposal
    # (which would tee it up for a silent overwrite on loop confirm).
    candidate_rides = [
        r for r in candidate_rides
        if r.loop_id not in confirmed_loop_ids and r.assigned_person_id is None
    ]

    ride_by_id: dict[int, SeasonRide] = {}
    legs: list[Leg] = []
    for ride in candidate_rides:
        leg = _leg_from_ride(ride, resolve_school=True)
        if day_part_filter and loop_builder.day_part(leg) != day_part_filter:
            continue
        if weekday_filter and weekday_filter not in loop_builder.day_signature(leg):
            continue
        ride_by_id[ride.season_ride_id] = ride
        legs.append(leg)

    result = loop_builder.build_loops(legs)

    # Clear previous unconfirmed system proposals for this scope only —
    # confirmed loops are filtered out above and never touched here.
    stale_q = db.query(DriverLoop).filter(
        DriverLoop.season == season,
        DriverLoop.status == "proposed",
        DriverLoop.origin == "system",
    )
    if day_part_filter:
        stale_q = stale_q.filter(DriverLoop.day_part == day_part_filter)
    stale_loops = stale_q.all()
    if weekday_filter:
        def _loop_signature(loop: DriverLoop) -> tuple[str, ...]:
            fake_leg = Leg(ride_id=0, source="", school="", direction="IB", number="", days=loop.days)
            return loop_builder.day_signature(fake_leg)

        stale_loops = [l for l in stale_loops if weekday_filter in _loop_signature(l)]

    stale_loop_ids = [l.loop_id for l in stale_loops]
    if stale_loop_ids:
        db.query(SeasonRide).filter(SeasonRide.loop_id.in_(stale_loop_ids)).update(
            {SeasonRide.loop_id: None, SeasonRide.loop_position: None}, synchronize_session=False,
        )
        db.query(DriverLoop).filter(DriverLoop.loop_id.in_(stale_loop_ids)).delete(synchronize_session=False)
        db.flush()

    new_loops: list[DriverLoop] = []
    for proposed in result.loops:
        loop_row = DriverLoop(
            season=season,
            label=proposed.label,
            day_part=proposed.day_part,
            days=",".join(proposed.days),
            status="proposed",
            origin="system",
            meta={
                "slack_minutes": proposed.slack_minutes,
                "requires_profile": proposed.requires_profile,
                "builder": "s10-v1",
            },
        )
        db.add(loop_row)
        db.flush()
        new_loops.append(loop_row)

        for position, ride_id in enumerate(proposed.ride_ids):
            ride = ride_by_id[ride_id]
            ride.loop_id = loop_row.loop_id
            ride.loop_position = position

    for idx, proposed in enumerate(result.loops):
        if proposed.companion_index is not None:
            companion_row = new_loops[proposed.companion_index]
            meta = dict(new_loops[idx].meta or {})
            meta["companion_loop_id"] = companion_row.loop_id
            new_loops[idx].meta = meta

    db.commit()

    return JSONResponse({
        "loops_created": len(result.loops),
        "ungroupable": [{"ride_id": rid, "reason": reason} for rid, reason in result.ungroupable],
    })


def _fits_confirmed(p_rides: list, c_rides: list) -> bool:
    """True if the proposed rides chain into the confirmed loop's rides as ONE
    valid loop under the engine's own rules (slack, length, day signatures)."""
    legs = [_leg_from_ride(r, resolve_school=True) for r in [*c_rides, *p_rides]]
    result = loop_builder.build_loops(legs)
    return (
        not result.ungroupable
        and len(result.loops) == 1
        and len(result.loops[0].ride_ids) == len(legs)
    )


# ── GET /season/loops ─────────────────────────────────────────────────────────

@router.get("/season/loops")
def list_loops(
    season: str = Query(DEFAULT_SEASON),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(DriverLoop).filter(DriverLoop.season == season)
    if status:
        q = q.filter(DriverLoop.status == status)
    loops = q.order_by(DriverLoop.day_part, DriverLoop.label).all()

    loop_ids = [l.loop_id for l in loops]
    rides_by_loop: dict[int, list[SeasonRide]] = {}
    ride_name_ids: set[int] = set()
    if loop_ids:
        all_rides = (
            db.query(SeasonRide)
            .options(joinedload(SeasonRide.school))
            .filter(SeasonRide.loop_id.in_(loop_ids))
            .all()
        )
        for r in all_rides:
            rides_by_loop.setdefault(r.loop_id, []).append(r)
            if r.assigned_person_id:
                ride_name_ids.add(r.assigned_person_id)
        for bucket in rides_by_loop.values():
            bucket.sort(key=lambda r: (r.loop_position if r.loop_position is not None else 0))

    person_ids = {l.person_id for l in loops if l.person_id} | ride_name_ids
    names = _name_lookup(db, person_ids)

    # Candidate pool for driver suggestions on proposed loops — built once.
    has_proposed = any(l.status == "proposed" for l in loops)
    candidates: list[CandidateDriver] = []
    if has_proposed:
        confirmed_by_person: dict[int, list[tuple[str, Optional[str]]]] = {}
        confirmed = (
            db.query(DriverLoop)
            .filter(DriverLoop.season == season,
                    DriverLoop.status == "confirmed",
                    DriverLoop.person_id.isnot(None))
            .all()
        )
        for cl in confirmed:
            confirmed_by_person.setdefault(cl.person_id, []).append((cl.day_part, cl.days))
        # Single-ride commitments count as busy too (mirrors _ride_suggestions
        # above) — a driver hand-assigned a ride outside any confirmed loop is
        # still physically unavailable for that day-part.
        confirmed_loop_ids = {cl.loop_id for cl in confirmed}
        single_assigned = (
            db.query(SeasonRide)
            .filter(SeasonRide.season == season,
                    SeasonRide.status == "assigned",
                    SeasonRide.assigned_person_id.isnot(None))
            .all()
        )
        for r in single_assigned:
            if r.loop_id in confirmed_loop_ids:
                continue
            confirmed_by_person.setdefault(r.assigned_person_id, []).append(
                (loop_builder.day_part(_leg_from_ride(r)), r.days)
            )
        candidates = [
            CandidateDriver(
                person_id=p.person_id,
                name=p.full_name,
                home_address=p.home_address,
                wheelchair_vehicle=bool((p.capabilities or {}).get("wheelchair_vehicle")),
                confirmed_loops=tuple(confirmed_by_person.get(p.person_id, [])),
            )
            for p in _qualifying_people(db) if p.active
        ]

    # Route familiarity: (route_school, route_number) -> {person_id: ride count}
    # from prior payroll history, one query for all loops' routes.
    # season_ride schools are canonicalized lowercase; payroll history kept
    # original casing — compare lowered on both sides.
    route_keys = {
        (r.route_school.lower(), r.route_number)
        for lr in rides_by_loop.values() for r in lr
    }
    history_by_route: dict[tuple[str, str], dict[int, int]] = {}
    if candidates and route_keys:
        hist_rows = (
            db.query(func.lower(Ride.route_school), Ride.route_number, Ride.person_id, func.count(Ride.ride_id))
            .filter(
                tuple_(func.lower(Ride.route_school), Ride.route_number).in_(list(route_keys)),
                Ride.person_id.isnot(None),
            )
            .group_by(func.lower(Ride.route_school), Ride.route_number, Ride.person_id)
            .all()
        )
        for school, number, pid, cnt in hist_rows:
            history_by_route.setdefault((school, number), {})[pid] = cnt

    confirmed_loops = [l for l in loops if l.status == "confirmed" and l.person_id]

    out = []
    for loop in loops:
        meta = loop.meta or {}
        loop_rides = rides_by_loop.get(loop.loop_id, [])

        # New ride fits an existing driver's confirmed day? Suggest, never auto-merge.
        extension_hint = None
        if loop.status == "proposed" and loop_rides:
            for cl in confirmed_loops:
                c_rides = rides_by_loop.get(cl.loop_id, [])
                if cl.day_part != loop.day_part or not c_rides:
                    continue
                if len(c_rides) + len(loop_rides) > loop_builder.DEFAULT_MAX_LEGS:
                    continue
                if _fits_confirmed(loop_rides, c_rides):
                    extension_hint = {
                        "loop_id": cl.loop_id,
                        "label": cl.label,
                        "driver": names.get(cl.person_id, "driver"),
                    }
                    break

        suggestions: list[dict] = []
        if loop.status == "proposed" and candidates and loop_rides:
            shape = LoopShape(
                day_part=loop.day_part,
                days=loop.days,
                requires_wheelchair=bool(meta.get("requires_profile", {}).get("wheelchair")),
                first_pickup_city=loop_rides[0].pickup_city,
                leg_cities=tuple(
                    c for r in loop_rides for c in (r.pickup_city, r.dropoff_city) if c
                ),
            )
            prior_counts: dict[int, int] = {}
            for r in loop_rides:
                for pid, cnt in history_by_route.get((r.route_school.lower(), r.route_number), {}).items():
                    prior_counts[pid] = prior_counts.get(pid, 0) + cnt
            suggestions = [
                s.as_dict()
                for s in suggest_drivers(shape, candidates, prior_route_rides=prior_counts)
            ]
        out.append({
            "loop_id": loop.loop_id,
            "label": loop.label,
            "day_part": loop.day_part,
            "days": loop.days,
            "status": loop.status,
            "origin": loop.origin,
            "slack_minutes": meta.get("slack_minutes", []),
            "requires_profile": meta.get("requires_profile", {}),
            "companion_loop_id": meta.get("companion_loop_id"),
            "person": (
                {"person_id": loop.person_id, "name": names.get(loop.person_id, "Unknown")}
                if loop.person_id else None
            ),
            "suggestions": suggestions,
            "extension_hint": extension_hint,
            "rides": [_ride_out(r, names) for r in loop_rides],
        })

    return JSONResponse({"loops": out})


# ── POST /season/loops/{id}/extend ───────────────────────────────────────────

@router.post("/season/loops/{loop_id}/extend")
async def extend_loop(loop_id: int, request: Request, db: Session = Depends(get_db)):
    """Fold a proposed loop's rides into an existing CONFIRMED loop (same
    driver). Only ever user-initiated — the board suggests, mom decides."""
    body = await _json_body(request)
    proposed_id = body.get("proposed_loop_id")
    if proposed_id is None:
        raise HTTPException(status_code=400, detail="proposed_loop_id required")

    confirmed = db.query(DriverLoop).filter(DriverLoop.loop_id == loop_id).first()
    proposed = db.query(DriverLoop).filter(DriverLoop.loop_id == proposed_id).first()
    if not confirmed or not proposed:
        raise HTTPException(status_code=404, detail="Loop not found")
    if confirmed.status != "confirmed" or not confirmed.person_id:
        raise HTTPException(status_code=409, detail="Target loop is not confirmed with a driver")
    if proposed.status != "proposed":
        raise HTTPException(status_code=409, detail="Source loop is not a proposal")

    c_rides = db.query(SeasonRide).filter(SeasonRide.loop_id == confirmed.loop_id).all()
    p_rides = db.query(SeasonRide).filter(SeasonRide.loop_id == proposed.loop_id).all()
    if not c_rides or not p_rides:
        raise HTTPException(status_code=409, detail="Loop has no rides")

    legs = [_leg_from_ride(r, resolve_school=True) for r in [*c_rides, *p_rides]]
    result = loop_builder.build_loops(legs)
    if result.ungroupable or len(result.loops) != 1 or len(result.loops[0].ride_ids) != len(legs):
        raise HTTPException(status_code=409, detail="These rides no longer chain into one loop")
    merged = result.loops[0]

    person = db.query(Person).filter(Person.person_id == confirmed.person_id).first()
    if merged.requires_profile.get("wheelchair") and not (person and (person.capabilities or {}).get("wheelchair_vehicle")):
        raise HTTPException(status_code=409, detail="Merged loop needs a wheelchair vehicle this driver does not have")

    order = {rid: i for i, rid in enumerate(merged.ride_ids)}
    for ride in [*c_rides, *p_rides]:
        ride.loop_id = confirmed.loop_id
        ride.loop_position = order[ride.season_ride_id]
    for ride in p_rides:
        ride.assigned_person_id = confirmed.person_id
        ride.status = "assigned"

    meta = dict(confirmed.meta or {})
    meta["slack_minutes"] = merged.slack_minutes
    meta["requires_profile"] = merged.requires_profile
    confirmed.meta = meta
    confirmed.days = ",".join(merged.days)
    prefix = confirmed.label.split(" — ")[0]
    suffix = merged.label.split(" — ", 1)[1] if " — " in merged.label else merged.label
    confirmed.label = f"{prefix} — {suffix}"

    # Drop dangling companion references to the proposal we're deleting.
    for other in db.query(DriverLoop).filter(DriverLoop.season == confirmed.season).all():
        m = other.meta or {}
        if m.get("companion_loop_id") == proposed.loop_id:
            m = dict(m)
            m.pop("companion_loop_id")
            other.meta = m

    db.delete(proposed)
    db.commit()
    return JSONResponse({"ok": True, "loop_id": confirmed.loop_id})


# ── POST /season/loops/{id}/assign ───────────────────────────────────────────

@router.post("/season/loops/{loop_id}/assign")
async def assign_loop(loop_id: int, request: Request, db: Session = Depends(get_db)):
    body = await _json_body(request)
    person_id = body.get("person_id")
    if person_id is None:
        raise HTTPException(status_code=400, detail="person_id required")
    override = bool(body.get("override", False))

    loop = db.query(DriverLoop).filter(DriverLoop.loop_id == loop_id).first()
    if not loop:
        raise HTTPException(status_code=404, detail="Loop not found")

    person = db.query(Person).filter(Person.person_id == person_id).first()
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    meta = loop.meta or {}
    requires_profile = meta.get("requires_profile") or {}
    capabilities = person.capabilities or {}
    missing = [
        flag for flag in _GATING_FLAGS
        if requires_profile.get(flag) and not capabilities.get(_CAPABILITY_MAP.get(flag, flag))
    ]

    if missing and not override:
        raise HTTPException(
            status_code=409,
            detail={"reason": "driver missing required capabilities", "missing": missing},
        )

    loop.person_id = person_id
    loop.status = "confirmed"
    db.flush()

    rides = db.query(SeasonRide).filter(SeasonRide.loop_id == loop_id).all()
    for ride in rides:
        ride.assigned_person_id = person_id
        ride.status = "assigned"

    db.commit()
    db.refresh(loop)

    return JSONResponse({
        "ok": True,
        "loop_id": loop.loop_id,
        "person_id": loop.person_id,
        "status": loop.status,
        "companion_loop_id": meta.get("companion_loop_id"),
    })


# ── POST /season/loops/{id}/dismiss ──────────────────────────────────────────

@router.post("/season/loops/{loop_id}/dismiss")
def dismiss_loop(loop_id: int, db: Session = Depends(get_db)):
    loop = db.query(DriverLoop).filter(DriverLoop.loop_id == loop_id).first()
    if not loop:
        raise HTTPException(status_code=404, detail="Loop not found")
    if loop.status == "confirmed":
        raise HTTPException(status_code=409, detail="cannot dismiss a confirmed loop")

    loop.status = "dismissed"
    db.flush()
    db.query(SeasonRide).filter(SeasonRide.loop_id == loop_id).update(
        {SeasonRide.loop_id: None, SeasonRide.loop_position: None}, synchronize_session=False,
    )
    db.commit()

    return JSONResponse({"ok": True, "loop_id": loop_id, "status": "dismissed"})


# ── PATCH /season/rides/{id} ─────────────────────────────────────────────────

_RIDE_DIRECT_FIELDS = ("pickup_time", "dropoff_time", "days", "notes", "loop_id", "loop_position")


@router.patch("/season/rides/{ride_id}")
async def patch_season_ride(ride_id: int, request: Request, db: Session = Depends(get_db)):
    body = await _json_body(request)

    ride = db.query(SeasonRide).filter(SeasonRide.season_ride_id == ride_id).first()
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")

    if "pickup_address" in body:
        ride.pickup_address = body["pickup_address"]
        if "pickup_city" not in body:
            ride.pickup_city = extract_city(body["pickup_address"])
    if "dropoff_address" in body:
        ride.dropoff_address = body["dropoff_address"]
        if "dropoff_city" not in body:
            ride.dropoff_city = extract_city(body["dropoff_address"])

    if "pickup_city" in body:
        ride.pickup_city = body["pickup_city"]
    if "dropoff_city" in body:
        ride.dropoff_city = body["dropoff_city"]

    for field in _RIDE_DIRECT_FIELDS:
        if field in body:
            setattr(ride, field, body[field])

    if "requires" in body:
        ride.requires = body["requires"] or {}

    if "assigned_person_id" in body:
        new_person_id = body["assigned_person_id"]
        if new_person_id:
            person = db.query(Person).filter(Person.person_id == new_person_id).first()
            if not person:
                raise HTTPException(status_code=404, detail="Person not found")
            # Same wheelchair gate as assign_loop — the UI disables uncovered
            # drivers, this is the server-side backstop.
            requires = ride.requires or {}
            capabilities = person.capabilities or {}
            missing = [
                flag for flag in _GATING_FLAGS
                if requires.get(flag) and not capabilities.get(_CAPABILITY_MAP.get(flag, flag))
            ]
            if missing and not bool(body.get("override", False)):
                raise HTTPException(
                    status_code=409,
                    detail={"reason": "driver missing required capabilities", "missing": missing},
                )
            # Single-assign detaches the ride from any PROPOSED loop, so the
            # loop lanes (propose regroup, assign_loop's bulk overwrite) can
            # never silently steal a ride mom assigned by hand. Confirmed
            # loops keep their rides — those are already-assigned anyway.
            if "loop_id" not in body and ride.loop_id is not None:
                loop = db.query(DriverLoop).filter(DriverLoop.loop_id == ride.loop_id).first()
                if loop is None or loop.status != "confirmed":
                    ride.loop_id = None
                    ride.loop_position = None
        ride.assigned_person_id = new_person_id
        if "status" not in body:
            ride.status = "assigned" if new_person_id else "unassigned"

    if "status" in body:
        if body["status"] not in _RIDE_STATUSES:
            raise HTTPException(
                status_code=422,
                detail=f"status must be one of {', '.join(_RIDE_STATUSES)}",
            )
        ride.status = body["status"]

    db.commit()
    db.refresh(ride)

    name_lookup = _name_lookup(db, {ride.assigned_person_id} if ride.assigned_person_id else set())
    return JSONResponse(_ride_out(ride, name_lookup))


# ── POST /season/rides/{id}/unassign ─────────────────────────────────────────

@router.post("/season/rides/{ride_id}/unassign")
def unassign_ride(ride_id: int, db: Session = Depends(get_db)):
    ride = db.query(SeasonRide).filter(SeasonRide.season_ride_id == ride_id).first()
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")

    ride.assigned_person_id = None
    ride.status = "unassigned"
    db.commit()

    return JSONResponse({"ok": True, "season_ride_id": ride.season_ride_id, "status": ride.status})


# ── schools ───────────────────────────────────────────────────────────────────

@router.get("/schools")
def list_schools(db: Session = Depends(get_db)):
    return JSONResponse({"schools": schools_overview(db)})


@router.patch("/schools/{school_id}")
async def patch_school(school_id: int, request: Request, db: Session = Depends(get_db)):
    body = await _json_body(request)
    try:
        apply_school_address(
            db, school_id,
            address=body.get("address"), city=body.get("city"), district=body.get("district"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if "notes" in body:
        school = db.query(School).filter(School.school_id == school_id).first()
        if school is not None:
            school.notes = body["notes"]

    db.commit()

    updated = next((s for s in schools_overview(db) if s["school_id"] == school_id), None)
    return JSONResponse(updated)


# ── people / capabilities ─────────────────────────────────────────────────────

def _qualifying_people(db: Session) -> list[Person]:
    """Driver pool for capabilities + suggestions: anyone who has ever run a
    ride, sits on a roster, or carries a partner driver id."""
    ride_person_ids = {
        pid for (pid,) in db.query(Ride.person_id).filter(Ride.person_id.isnot(None)).distinct().all()
    }
    roster_primary_ids = {
        pid for (pid,) in db.query(RouteRoster.primary_person_id)
        .filter(RouteRoster.primary_person_id.isnot(None)).distinct().all()
    }
    roster_backup_ids = {pid for (pid,) in db.query(RouteBackup.person_id).distinct().all()}
    qualifying_ids = ride_person_ids | roster_primary_ids | roster_backup_ids

    return (
        db.query(Person)
        .filter(
            or_(
                Person.person_id.in_(qualifying_ids),
                Person.firstalt_driver_id.isnot(None),
                Person.everdriven_driver_id.isnot(None),
            )
        )
        .order_by(Person.full_name.asc())
        .all()
    )


@router.get("/people/capabilities")
def list_people_capabilities(db: Session = Depends(get_db)):
    people = _qualifying_people(db)

    return JSONResponse([
        {"person_id": p.person_id, "name": p.full_name, "capabilities": p.capabilities or {}}
        for p in people
    ])


@router.patch("/people/{person_id}/capabilities")
async def patch_person_capabilities(person_id: int, request: Request, db: Session = Depends(get_db)):
    body = await _json_body(request)
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="body must be a JSON object of capability flags")

    unknown = set(body.keys()) - set(CAPABILITY_FLAG_KEYS)
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown capability key(s): {sorted(unknown)}")
    for key, value in body.items():
        if not isinstance(value, bool):
            raise HTTPException(status_code=422, detail=f"capability {key!r} must be a boolean")

    person = db.query(Person).filter(Person.person_id == person_id).first()
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    person.capabilities = dict(body)
    db.commit()

    return JSONResponse({
        "ok": True,
        "person_id": person.person_id,
        "name": person.full_name,
        "capabilities": person.capabilities,
    })
