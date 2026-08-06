"""
Season pool — S10 Season Assignment Board.

Rides arrive one-by-one (inbox auto-intake, already live via
backend.services.ride_intake_service) or via sheet upload. Either path lands
here: they pool as `season_ride` rows with status `unassigned` so mom can
batch-assign drivers on the board instead of deciding at accept time
(docs/SEASON-BOARD-PLAN.md §Business rule 1).

Three entry points:
  - upsert_from_intake: one RideIntake -> one or two SeasonRide rows
    (IB/OB), called from inbox_intake once an offer flips to `taken`.
  - import_sheet: a mom-uploaded xlsx/csv of the whole season's routes.
  - backfill_from_intakes: one-shot sweep of every already-`taken` intake,
    for turning this feature on after intakes already exist.

Dedupe key everywhere is the season_ride unique index:
  (season, source, route_school, route_direction, route_number, route_is_odt)
Upserts always find-then-update on that key — never duplicate rows.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from sqlalchemy.orm import Session

from backend.db.models import RideIntake, School, SeasonRide
from backend.services.city_extract import extract_city
from backend.services.school_service import (
    _normalize as _normalize_school_name,
    get_or_create_school,
)

DEFAULT_SEASON = "2026-27"

REQUIREMENT_FLAG_KEYS = ("wheelchair", "car_seat", "booster", "harness", "monitor")

# Requirements-text keyword mapping (plan doc §services/season_pool.py).
_REQUIREMENT_KEYWORDS: tuple[tuple[str, "re.Pattern"], ...] = (
    ("car_seat", re.compile(r"\bcar\s*seats?\b", re.IGNORECASE)),
    ("booster", re.compile(r"\bboosters?\b", re.IGNORECASE)),
    ("harness", re.compile(r"\b(harness(?:es)?|vest|safety\s*belts?)\b", re.IGNORECASE)),
    ("monitor", re.compile(r"\b(monitor|attendant|aide)\b", re.IGNORECASE)),
    ("wheelchair", re.compile(r"\b(wheelchair|w[/-]?c|hcv)\b", re.IGNORECASE)),
)


def parse_requirement_flags(source_text, extra_wheelchair: bool = False) -> dict:
    """Best-effort {wheelchair, car_seat, booster, harness, monitor} bools
    from free text (a string) or a list of requirement phrases. Never raises.

    `extra_wheelchair` ORs in a wheelchair flag already known from elsewhere
    (e.g. ride_intake_service's own WHEELCHAIR_RE / route_identity's HCV
    marker) so callers don't have to re-run keyword matching for it.
    """
    flags = {key: False for key in REQUIREMENT_FLAG_KEYS}
    if extra_wheelchair:
        flags["wheelchair"] = True
    if not source_text:
        return flags
    if isinstance(source_text, (list, tuple, set)):
        joined = " ".join(str(x) for x in source_text if x)
    else:
        joined = str(source_text)
    for key, pattern in _REQUIREMENT_KEYWORDS:
        if pattern.search(joined):
            flags[key] = True
    return flags


def _normalize_number(value) -> str:
    """Zero-pad a route number to two digits when it's purely numeric
    (matches route_identity.RouteIdentity.number convention); pass through
    unchanged otherwise (defensive — real data is occasionally non-numeric)."""
    if isinstance(value, float) and value == int(value):
        text = str(int(value))
    else:
        text = str(value).strip()
    return text.zfill(2) if text.isdigit() else text


def _identity_query(db: Session, season: str, source: str, school: str,
                     direction: str, number: str, is_odt: bool) -> Optional[SeasonRide]:
    # route_school is stored canonicalized (lower/single-spaced, same normal
    # form as school.name) so "Rose Hill MS" from an intake and "ROSE HILL MS"
    # from mom's sheet resolve to ONE row — casing must never fork identity.
    return (
        db.query(SeasonRide)
        .filter(
            SeasonRide.season == season,
            SeasonRide.source == source,
            SeasonRide.route_school == _normalize_school_name(school),
            SeasonRide.route_direction == direction,
            SeasonRide.route_number == number,
            SeasonRide.route_is_odt == is_odt,
        )
        .first()
    )


def _resolve_directions(parsed: dict) -> list[str]:
    """Which leg(s) to create from a parsed intake.

    - Explicit split pay (both net_pay_ib and net_pay_ob present) always
      means round trip -> both legs, regardless of any single `direction`
      guessed from a stray IB/OB token in the text.
    - A clean single `direction` -> that one leg.
    - Direction missing but the offer names a concrete pickup+dropoff pair
      (origin/destination) -> treated as a standing route that runs both
      ways (kid goes to school AND comes home) -> both legs; mom edits or
      dismisses whichever leg doesn't apply on the board.
    - Otherwise: not enough signal, caller should raise.
    """
    direction = parsed.get("direction")
    net_pay_ib = parsed.get("net_pay_ib")
    net_pay_ob = parsed.get("net_pay_ob")

    if net_pay_ib is not None and net_pay_ob is not None:
        return ["IB", "OB"]
    if direction in ("IB", "OB"):
        return [direction]
    if direction is None and parsed.get("origin") and parsed.get("destination"):
        return ["IB", "OB"]
    return []


def _apply_corridor_cities(row: SeasonRide, direction: str,
                            origin_city: Optional[str], destination_city: Optional[str]) -> None:
    """origin/destination -> pickup/dropoff city, per leg sidedness.

    Convention: origin/destination as extracted from offer text describe the
    IB leg (home -> school) — pickup=origin, dropoff=destination. The OB leg
    runs the corridor in reverse (school -> home), so its pickup/dropoff are
    swapped. Only fills NULL fields — never overwrites a value already set.
    """
    if direction == "IB":
        pickup, dropoff = origin_city, destination_city
    else:
        pickup, dropoff = destination_city, origin_city
    if pickup and row.pickup_city is None:
        row.pickup_city = pickup
    if dropoff and row.dropoff_city is None:
        row.dropoff_city = dropoff


def upsert_from_intake(db: Session, intake: RideIntake, season: str = DEFAULT_SEASON,
                        source: str = "firstalt") -> list[SeasonRide]:
    """Map a taken RideIntake's parsed JSON into one or two SeasonRide rows.

    Raises ValueError when the intake doesn't carry enough identity
    (school/number, or a resolvable direction) to pool it — callers (e.g.
    inbox_intake) wrap this and log, per plan doc §Wiring; it deliberately
    does not swallow the error itself so a genuinely-incomplete intake is
    never silently pooled as a bogus route.
    """
    parsed = intake.parsed or {}
    school_name = parsed.get("school")
    number_raw = parsed.get("number")
    if not school_name or not number_raw:
        raise ValueError("intake.parsed missing school/number — cannot pool without a route identity")

    # Explicit one-off trips (ER blocks, single-date specials) are not
    # standing season routes — pooling them would clutter the board with
    # rides that stop existing after one day. Unknown recurrence pools
    # normally; mom dismisses anything that doesn't belong.
    if parsed.get("is_recurring") is False:
        return []

    directions = _resolve_directions(parsed)
    if not directions:
        raise ValueError("intake.parsed missing direction — cannot pool without a route identity")

    is_odt = bool(parsed.get("is_odt") or False)
    wheelchair = bool(parsed.get("wheelchair") or False)
    flags = parse_requirement_flags(parsed.get("requirements"), extra_wheelchair=wheelchair)

    days = parsed.get("days")
    if isinstance(days, (list, tuple)):
        days_str = ",".join(days) or None
    elif isinstance(days, str):
        days_str = days or None
    else:
        days_str = None

    origin_city = extract_city(parsed.get("origin"))
    destination_city = extract_city(parsed.get("destination"))

    district = parsed.get("district")
    school = get_or_create_school(db, school_name)
    if district and not school.district:
        school.district = district
        db.flush()

    number = _normalize_number(number_raw)
    miles = parsed.get("miles")
    start_time = parsed.get("start_time")
    net_pay_ib = parsed.get("net_pay_ib")
    net_pay_ob = parsed.get("net_pay_ob")
    single_net_pay = parsed.get("net_pay")

    rows: list[SeasonRide] = []
    for direction in directions:
        if direction == "IB" and net_pay_ib is not None:
            net_pay = net_pay_ib
        elif direction == "OB" and net_pay_ob is not None:
            net_pay = net_pay_ob
        else:
            net_pay = single_net_pay

        row = _identity_query(db, season, source, school_name, direction, number, is_odt)
        if row is None:
            row = SeasonRide(
                season=season, source=source,
                route_school=_normalize_school_name(school_name),
                route_direction=direction, route_number=number, route_is_odt=is_odt,
            )
            db.add(row)

        row.intake_id = intake.intake_id
        row.school_id = school.school_id
        row.requires = flags
        if days_str is not None:
            row.days = days_str
        if start_time is not None and row.pickup_time is None:
            row.pickup_time = start_time
        if miles is not None:
            row.miles = miles
        if net_pay is not None:
            row.net_pay = net_pay
        _apply_corridor_cities(row, direction, origin_city, destination_city)

        db.flush()
        rows.append(row)

    return rows


def _season_cutoff(season: str) -> Optional[datetime]:
    """Earliest decided_at an intake can have and still belong to `season`.

    '2026-27' -> June 1 2026: offers taken before the summer belong to the
    PRIOR school year and must not flood the new season's board. Unparseable
    season strings return None (no cutoff, defensive).
    """
    try:
        year = int(season.split("-")[0])
        return datetime(year, 6, 1, tzinfo=timezone.utc)
    except (ValueError, IndexError):
        return None


def backfill_from_intakes(db: Session, season: str = DEFAULT_SEASON, source: str = "firstalt") -> dict:
    """One-shot: pool already-`taken` intakes into season_ride.

    Only intakes decided on/after the season cutoff (June 1 of the season's
    start year) are considered — last school year's offers are not this
    season's routes. Intakes with no decided_at are included (defensive).

    Never aborts the sweep — a single malformed intake's error is recorded
    and the rest of the batch still runs; each attempt runs in a SAVEPOINT
    so one failed flush can't poison the session for the rest.
    """
    cutoff = _season_cutoff(season)
    intakes = db.query(RideIntake).filter(RideIntake.status == "taken").all()
    if cutoff is not None:
        intakes = [
            i for i in intakes
            if i.decided_at is None or _as_utc(i.decided_at) >= cutoff
        ]
    rows_created = 0
    errors: list[dict] = []
    for intake in intakes:
        try:
            with db.begin_nested():
                rows = upsert_from_intake(db, intake, season=season, source=source)
            rows_created += len(rows)
        except Exception as exc:
            errors.append({"intake_id": intake.intake_id, "message": str(exc)})
    return {"processed": len(intakes), "rows": rows_created, "errors": errors}


def _as_utc(value: datetime) -> datetime:
    """Naive timestamps (sqlite test fixtures) are assumed UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


# ── sheet import ─────────────────────────────────────────────────────────────

@dataclass
class ImportReport:
    total_rows: int = 0
    created: int = 0
    updated: int = 0
    schools_created: int = 0
    errors: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "total_rows": self.total_rows,
            "created": self.created,
            "updated": self.updated,
            "schools_created": self.schools_created,
            "errors": self.errors,
        }


# (canonical field, hint substrings) — ordered most-specific-first so e.g.
# "Pickup Time" is claimed by pickup_time before the looser "school"/generic
# hints get a chance, and two columns never collide on the same target.
_COLUMN_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("pickup_time", ("pickup time", "pick up time")),
    ("dropoff_time", ("dropoff time", "drop off time", "drop-off time")),
    ("pickup_address", ("pickup address", "pick up address", "pickup addr")),
    ("dropoff_address", ("dropoff address", "drop off address", "drop-off address", "dropoff addr")),
    ("school", ("school",)),
    ("direction", ("direction", "ib/ob", "ib ob")),
    ("route_number", ("route number", "route #", "route no", "number", "route")),
    ("is_odt", ("odt",)),
    ("days", ("day",)),
    ("miles", ("mile",)),
    ("net_pay", ("net pay", "pay", "rate")),
    ("requirements", ("requirement", "need")),
    ("district", ("district",)),
    ("wheelchair", ("wheelchair", "hcv", "w/c")),
)


def _map_columns(columns) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for raw_col in columns:
        norm = re.sub(r"\s+", " ", str(raw_col)).strip().lower()
        for target, hints in _COLUMN_HINTS:
            if target in mapping:
                continue
            if any(hint in norm for hint in hints):
                mapping[target] = raw_col
                break
    return mapping


def _clean_str(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _clean_float(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _truthy(value) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and pd.isna(value):
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "y", "hcv", "wheelchair")


def _read_sheet(file_bytes: bytes, filename: str) -> pd.DataFrame:
    buf = io.BytesIO(file_bytes)
    if filename.lower().endswith(".csv"):
        return pd.read_csv(buf)
    return pd.read_excel(buf, engine="openpyxl")


def import_sheet(db: Session, file_bytes: bytes, filename: str,
                  season: str = DEFAULT_SEASON, source: str = "firstalt") -> ImportReport:
    """Import a mom-uploaded season roster sheet (xlsx/csv). Column mapping
    is tolerant/fuzzy (case-insensitive contains match). Unknown columns are
    ignored. Per-row errors are collected into the report; a bad row never
    aborts the rest of the batch.

    source defaults to "firstalt", NOT "sheet": source is part of the dedupe
    identity, and mom's sheet describes the same FA routes the inbox intake
    pools — the two paths must merge into one row, never fork into two."""
    report = ImportReport()

    try:
        df = _read_sheet(file_bytes, filename)
    except Exception as exc:
        report.errors.append({"row": None, "message": f"could not read file: {exc}"})
        return report

    mapping = _map_columns(df.columns)
    missing_required = [k for k in ("school", "direction", "route_number") if k not in mapping]
    if missing_required:
        report.errors.append({
            "row": None,
            "message": f"missing required column(s): {', '.join(missing_required)}",
        })
        return report

    report.total_rows = len(df)

    for idx, raw_row in df.iterrows():
        sheet_row_num = int(idx) + 2  # +1 for 0-index, +1 for the header row
        try:
            row_dict = raw_row.to_dict()
            school_name = _clean_str(row_dict.get(mapping["school"]))
            direction = _clean_str(row_dict.get(mapping["direction"]))
            number_raw = row_dict.get(mapping["route_number"])
            if not school_name or not direction or _clean_str(number_raw) is None:
                raise ValueError("missing school/direction/route number")

            direction = direction.strip().upper()
            if direction not in ("IB", "OB"):
                raise ValueError(f"unrecognized direction {direction!r} (expected IB or OB)")

            number = _normalize_number(number_raw)
            is_odt = _truthy(row_dict.get(mapping["is_odt"])) if "is_odt" in mapping else False
            days_val = _clean_str(row_dict.get(mapping["days"])) if "days" in mapping else None
            pickup_address = _clean_str(row_dict.get(mapping["pickup_address"])) if "pickup_address" in mapping else None
            dropoff_address = _clean_str(row_dict.get(mapping["dropoff_address"])) if "dropoff_address" in mapping else None
            pickup_time = _clean_str(row_dict.get(mapping["pickup_time"])) if "pickup_time" in mapping else None
            dropoff_time = _clean_str(row_dict.get(mapping["dropoff_time"])) if "dropoff_time" in mapping else None
            miles = _clean_float(row_dict.get(mapping["miles"])) if "miles" in mapping else None
            net_pay = _clean_float(row_dict.get(mapping["net_pay"])) if "net_pay" in mapping else None
            requirements_text = _clean_str(row_dict.get(mapping["requirements"])) if "requirements" in mapping else None
            district = _clean_str(row_dict.get(mapping["district"])) if "district" in mapping else None
            wheelchair_flag = _truthy(row_dict.get(mapping["wheelchair"])) if "wheelchair" in mapping else False

            school_existed = (
                db.query(School)
                .filter(School.name == _normalize_school_name(school_name))
                .first() is not None
            )
            school = get_or_create_school(db, school_name)
            if not school_existed:
                report.schools_created += 1
            if district and not school.district:
                school.district = district
            db.flush()

            existing = _identity_query(db, season, source, school_name, direction, number, is_odt)
            is_new = existing is None
            row = existing or SeasonRide(
                season=season, source=source,
                route_school=_normalize_school_name(school_name),
                route_direction=direction, route_number=number, route_is_odt=is_odt,
            )
            row.school_id = school.school_id
            sheet_flags = parse_requirement_flags(requirements_text, extra_wheelchair=wheelchair_flag)
            if is_new or not row.requires:
                row.requires = sheet_flags
            else:
                # Re-import merges by OR: a safety flag mom set by hand (car
                # seat, monitor, ...) must never be silently cleared by a
                # re-uploaded sheet that omits it. Clearing a wrong flag is
                # a deliberate act — she does it on the ride card (PATCH),
                # which replaces the flags outright.
                row.requires = {
                    key: bool(sheet_flags.get(key) or row.requires.get(key))
                    for key in REQUIREMENT_FLAG_KEYS
                }
            if days_val:
                row.days = days_val
            if pickup_address:
                row.pickup_address = pickup_address
                row.pickup_city = row.pickup_city or extract_city(pickup_address)
            if dropoff_address:
                row.dropoff_address = dropoff_address
                row.dropoff_city = row.dropoff_city or extract_city(dropoff_address)
            if pickup_time:
                row.pickup_time = pickup_time
            if dropoff_time:
                row.dropoff_time = dropoff_time
            if miles is not None:
                row.miles = miles
            if net_pay is not None:
                row.net_pay = net_pay

            # SAVEPOINT per row: a failed flush (constraint race, bad value)
            # must roll back this row alone, not poison the session and take
            # every later row down with it.
            with db.begin_nested():
                if is_new:
                    db.add(row)
                db.flush()

            if is_new:
                report.created += 1
            else:
                report.updated += 1
        except Exception as exc:
            report.errors.append({"row": sheet_row_num, "message": str(exc)})
            continue

    return report
