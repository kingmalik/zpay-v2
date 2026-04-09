"""
backend/routes/people_audit.py
--------------------------------
FastAPI router — prefix="/people/audit"

Endpoints:
  GET  /people/audit/duplicates      — probable duplicate Person records
  POST /people/audit/merge           — merge two Person records
  GET  /people/audit/missing         — active drivers missing critical fields
  POST /people/audit/import-csv      — bulk phone/email update from CSV upload
  POST /people/audit/auto-inactivate — mark stale drivers inactive
"""

import csv
import difflib
import io
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.db import get_db
from backend.db.models import (
    DispatchAssignment,
    DriverBalance,
    Person,
    Ride,
    TripNotification,
)

router = APIRouter(prefix="/people/audit", tags=["people-audit"])

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
DUPLICATE_NAME_THRESHOLD = 0.78
IMPORT_MATCH_THRESHOLD = 0.82
STALE_DAYS = 35


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _normalize(name: str) -> str:
    """Lowercase, strip — handles "First Last" DB format."""
    return name.lower().strip()


def _fuzzy_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def _person_dict(p: Person) -> dict:
    return {
        "person_id": p.person_id,
        "full_name": p.full_name,
        "email": p.email,
        "phone": p.phone,
        "paycheck_code": p.paycheck_code,
        "everdriven_driver_id": p.everdriven_driver_id,
        "firstalt_driver_id": p.firstalt_driver_id,
        "home_address": p.home_address,
        "vehicle_make": p.vehicle_make,
        "vehicle_model": p.vehicle_model,
        "vehicle_year": p.vehicle_year,
        "vehicle_plate": p.vehicle_plate,
        "vehicle_color": p.vehicle_color,
        "active": p.active,
    }


def _best_match_db(
    norm_name: str,
    db_persons: list[Person],
    db_norms: list[str],
    threshold: float,
) -> tuple[Optional[Person], float]:
    """Return (Person, ratio) for best fuzzy match above threshold, or (None, 0)."""
    best_person: Optional[Person] = None
    best_ratio = 0.0
    for person, dn in zip(db_persons, db_norms):
        if norm_name == dn:
            return person, 1.0
        ratio = _fuzzy_ratio(norm_name, dn)
        if ratio > best_ratio:
            best_ratio = ratio
            best_person = person
    if best_ratio >= threshold:
        return best_person, best_ratio
    return None, best_ratio


# ---------------------------------------------------------------------------
# GET /people/audit/duplicates
# ---------------------------------------------------------------------------

@router.get("/duplicates")
def get_duplicates(db: Session = Depends(get_db)):
    """
    Find probable duplicate Person records.

    - Groups by normalized name; flags pairs with difflib ratio > 0.78
    - Also flags any two persons sharing the same non-null paycheck_code
    - Returns list of {person_a, person_b, similarity, reason}
    """
    persons: list[Person] = db.query(Person).order_by(Person.person_id).all()
    norms = [_normalize(p.full_name) for p in persons]

    pairs: dict[tuple[int, int], dict] = {}

    # --- Name similarity pairs ---
    for i in range(len(persons)):
        for j in range(i + 1, len(persons)):
            ratio = _fuzzy_ratio(norms[i], norms[j])
            if ratio >= DUPLICATE_NAME_THRESHOLD:
                key = (persons[i].person_id, persons[j].person_id)
                pairs[key] = {
                    "person_a": _person_dict(persons[i]),
                    "person_b": _person_dict(persons[j]),
                    "similarity": round(ratio, 4),
                    "reason": "name_match",
                }

    # --- Shared paycheck_code pairs ---
    code_map: dict[str, list[Person]] = {}
    for p in persons:
        if p.paycheck_code:
            code_map.setdefault(p.paycheck_code, []).append(p)

    for code, group in code_map.items():
        if len(group) < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                key = (
                    min(group[i].person_id, group[j].person_id),
                    max(group[i].person_id, group[j].person_id),
                )
                if key in pairs:
                    pairs[key]["reason"] = "name_match|same_paycode"
                else:
                    ratio = _fuzzy_ratio(
                        _normalize(group[i].full_name),
                        _normalize(group[j].full_name),
                    )
                    pairs[key] = {
                        "person_a": _person_dict(group[i]),
                        "person_b": _person_dict(group[j]),
                        "similarity": round(ratio, 4),
                        "reason": "same_paycode",
                    }

    return list(pairs.values())


# ---------------------------------------------------------------------------
# POST /people/audit/merge
# ---------------------------------------------------------------------------

class MergeRequest(BaseModel):
    keep_id: int
    remove_id: int


@router.post("/merge")
def merge_persons(body: MergeRequest, db: Session = Depends(get_db)):
    """
    Merge two Person records.

    - Reassigns all related records (Ride, TripNotification, DriverBalance,
      DispatchAssignment) from remove_id → keep_id
    - Copies non-null fields from remove record to fill nulls on keep record
    - Deletes the remove record
    """
    if body.keep_id == body.remove_id:
        raise HTTPException(status_code=400, detail="keep_id and remove_id must differ.")

    keep: Optional[Person] = db.query(Person).filter(Person.person_id == body.keep_id).first()
    remove: Optional[Person] = db.query(Person).filter(Person.person_id == body.remove_id).first()

    if keep is None:
        raise HTTPException(status_code=404, detail=f"Person {body.keep_id} not found.")
    if remove is None:
        raise HTTPException(status_code=404, detail=f"Person {body.remove_id} not found.")

    # --- Reassign related records ---
    merged_rides = (
        db.query(Ride)
        .filter(Ride.person_id == body.remove_id)
        .update({"person_id": body.keep_id}, synchronize_session=False)
    )

    merged_notifications = (
        db.query(TripNotification)
        .filter(TripNotification.person_id == body.remove_id)
        .update({"person_id": body.keep_id}, synchronize_session=False)
    )

    # DriverBalance has a unique constraint on (person_id, payroll_batch_id).
    # For each balance row on remove that would collide, we aggregate by adding
    # carried_over values; otherwise just reassign.
    remove_balances = (
        db.query(DriverBalance)
        .filter(DriverBalance.person_id == body.remove_id)
        .all()
    )
    for rb in remove_balances:
        collision = (
            db.query(DriverBalance)
            .filter(
                DriverBalance.person_id == body.keep_id,
                DriverBalance.payroll_batch_id == rb.payroll_batch_id,
            )
            .first()
        )
        if collision:
            collision.carried_over = float(collision.carried_over or 0) + float(rb.carried_over or 0)
            db.delete(rb)
        else:
            rb.person_id = body.keep_id

    db.query(DispatchAssignment).filter(
        DispatchAssignment.person_id == body.remove_id
    ).update({"person_id": body.keep_id}, synchronize_session=False)

    # --- Copy non-null fields from remove → keep (fill nulls only) ---
    _nullable_fields = [
        "phone",
        "email",
        "paycheck_code",
        "everdriven_driver_id",
        "firstalt_driver_id",
        "home_address",
        "vehicle_make",
        "vehicle_model",
        "vehicle_year",
        "vehicle_plate",
        "vehicle_color",
    ]
    for field in _nullable_fields:
        keep_val = getattr(keep, field)
        remove_val = getattr(remove, field)
        if keep_val is None and remove_val is not None:
            setattr(keep, field, remove_val)

    # --- Delete remove record ---
    db.delete(remove)
    db.commit()

    return {
        "ok": True,
        "merged_rides": merged_rides,
        "merged_notifications": merged_notifications,
    }


# ---------------------------------------------------------------------------
# GET /people/audit/missing
# ---------------------------------------------------------------------------

@router.get("/missing")
def get_missing(db: Session = Depends(get_db)):
    """
    Return active drivers missing critical fields.

    Critical fields: paycheck_code, everdriven_driver_id, phone, email
    """
    persons: list[Person] = (
        db.query(Person)
        .filter(Person.active == True)  # noqa: E712
        .order_by(Person.full_name)
        .all()
    )

    critical_fields = {
        "paycheck_code": "paycheck_code",
        "everdriven_driver_id": "everdriven_driver_id",
        "phone": "phone",
        "email": "email",
    }

    results = []
    for p in persons:
        missing = [
            label
            for label, attr in critical_fields.items()
            if getattr(p, attr) is None
        ]
        if missing:
            entry = _person_dict(p)
            entry["missing_fields"] = missing
            results.append(entry)

    return results


# ---------------------------------------------------------------------------
# POST /people/audit/import-csv
# ---------------------------------------------------------------------------

@router.post("/import-csv")
async def import_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Bulk update phone/email from uploaded CSV.

    CSV format: name,phone,email  (header row required)
    Matches by name using the same fuzzy logic (ratio > 0.82).
    """
    raw = await file.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    required_headers = {"name", "phone", "email"}
    if reader.fieldnames is None or not required_headers.issubset(
        {h.lower().strip() for h in reader.fieldnames}
    ):
        raise HTTPException(
            status_code=400,
            detail="CSV must have header row with columns: name, phone, email",
        )

    rows = [
        {
            "raw_name": (r.get("name") or r.get("Name") or "").strip(),
            "phone": (r.get("phone") or r.get("Phone") or "").strip() or None,
            "email": (r.get("email") or r.get("Email") or "").strip() or None,
        }
        for r in reader
        if (r.get("name") or r.get("Name") or "").strip()
    ]

    if not rows:
        return {"updated": 0, "unmatched": []}

    db_persons: list[Person] = db.query(Person).order_by(Person.person_id).all()
    db_norms = [_normalize(p.full_name) for p in db_persons]

    updated = 0
    unmatched: list[str] = []

    for row in rows:
        norm = _normalize(row["raw_name"])
        match, _ratio = _best_match_db(norm, db_persons, db_norms, IMPORT_MATCH_THRESHOLD)
        if match is None:
            unmatched.append(row["raw_name"])
            continue

        changed = False
        if row["phone"] is not None:
            match.phone = row["phone"]
            changed = True
        if row["email"] is not None:
            match.email = row["email"]
            changed = True
        if changed:
            updated += 1

    db.commit()
    return {"updated": updated, "unmatched": unmatched}


# ---------------------------------------------------------------------------
# POST /people/audit/auto-inactivate
# ---------------------------------------------------------------------------

@router.post("/auto-inactivate")
def auto_inactivate(db: Session = Depends(get_db)):
    """
    Mark stale drivers inactive.

    Stale = active=True AND no Ride in last 35 days AND no DispatchAssignment in last 35 days.
    """
    cutoff: date = date.today() - timedelta(days=STALE_DAYS)

    # Persons with a recent ride
    recent_ride_ids: set[int] = {
        pid
        for (pid,) in db.query(Ride.person_id)
        .filter(Ride.ride_start_ts >= cutoff)
        .distinct()
        .all()
    }

    # Persons with a recent dispatch assignment
    recent_dispatch_ids: set[int] = {
        pid
        for (pid,) in db.query(DispatchAssignment.person_id)
        .filter(DispatchAssignment.assigned_date >= cutoff)
        .distinct()
        .all()
    }

    active_persons: list[Person] = (
        db.query(Person)
        .filter(Person.active == True)  # noqa: E712
        .all()
    )

    stale = [
        p
        for p in active_persons
        if p.person_id not in recent_ride_ids
        and p.person_id not in recent_dispatch_ids
    ]

    for p in stale:
        p.active = False

    db.commit()

    return {
        "inactivated": len(stale),
        "driver_names": [p.full_name for p in stale],
    }
