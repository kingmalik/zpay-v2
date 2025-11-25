from __future__ import annotations
from datetime import datetime, time, date
from typing import Iterable, List, Dict, Any

from sqlalchemy import (
    MetaData, Table, select, func, cast, Date, literal, and_
)
from sqlalchemy.types import Float, String
from sqlalchemy.orm import Session

from .models import Person  # or wherever your Person model lives
# and reuse your helpers:
# _reflect_ride(db), _ride_column_map(ride)

# -----------------------------------------------------------------------------
# Payroll Excel import (new)
# -----------------------------------------------------------------------------
import pandas as pd
import yaml
import pytz
from datetime import datetime, date, time
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session
from . import models


def _ride_column_map(*a, **k):
    return _ride_colmap(*a, **k)
def _ride_colmap(ride: Table) -> dict[str, str | None]:
    cols = set(ride.c.keys())

    def pick(*names):
        for n in names:
            if n in cols:
                return n
        return None

    return {
        "pk":         pick("ride_id", "id"),
        "person_id":  pick("person_id"),
        "start_ts":   pick("ride_start_ts", "start_ts"),
        "job_key":    pick("job_key", "key"),
        "job_name":   pick("job_name", "name"),
        "miles":      pick("miles"),
        "gross":      pick("gross_amount", "gross"),
        "net_pay":    pick("net_pay_amount", "net_pay"),
        "code":       pick("code", "person_code"),
        "source_file":pick("source_file"),
        "source_page":pick("source_page"),
    }

def _reflect_ride(db: Session) -> Table:
    """Reflect the ride table so we can map to whatever column names exist."""
    md = MetaData()
    return Table("ride", md, autoload_with=db.bind)

def _get_or_create_person(db: Session, full_name: str) -> int:
    full_name = (full_name or "").strip()
    p = db.execute(
        select(Person).where(Person.full_name == full_name).limit(1)
    ).scalar_one_or_none()
    if p:
        return int(p.person_id)
    p = Person(full_name=full_name)
    db.add(p)
    db.flush()  # assigns person_id
    return int(p.person_id)


def bulk_insert_rides(db: Session, records: Iterable[dict]) -> tuple[int, int]:
    """
    Insert parsed PDF rows.

    Expected keys in each record (missing values are OK):
      Person, Date (date), Key, Name, Miles, Gross, Net Pay, Code,
      Source file, Source page
    Returns: (inserted_count, skipped_count)
    """
    ride = _reflect_ride(db)
    cm = _ride_colmap(ride)

    inserted, skipped = 0, 0
    for r in records:
        try:
            pid = _get_or_create_person(db, r.get("Person"))

            # timestamp: combine date + 08:00 (schema requires NOT NULL)
            d: date | None = r.get("Date")
            if not d:
                skipped += 1
                continue
            start_ts = datetime.combine(d, time(8, 0))

            vals = {cm["person_id"]: pid}
            if cm["start_ts"]:    vals[cm["start_ts"]] = start_ts
            if cm["job_key"] and r.get("Key") is not None:
                vals[cm["job_key"]] = str(r.get("Key"))
            if cm["job_name"] and r.get("Name") is not None:
                vals[cm["job_name"]] = str(r.get("Name"))
            if cm["miles"]      and r.get("Miles")    is not None: vals[cm["miles"]] = float(r.get("Miles") or 0)
            if cm["gross"]      and r.get("Gross")    is not None: vals[cm["gross"]] = float(r.get("Gross") or 0)
            if cm["net_pay"]    and r.get("Net Pay")  is not None: vals[cm["net_pay"]] = float(r.get("Net Pay") or 0)
            if cm["code"]       and r.get("Code")     is not None: vals[cm["code"]] = str(r.get("Code") or "")
            if cm["source_file"] and r.get("Source file") is not None:
                vals[cm["source_file"]] = str(r.get("Source file"))
            if cm["source_page"] and r.get("Source page") is not None:
                vals[cm["source_page"]] = int(r.get("Source page") or 0)

            # simple de-dupe: same person + ts + (job_key or job_name)
            q = select(ride.c[cm["pk"]]).where(ride.c[cm["person_id"]] == pid)
            if cm["start_ts"]:
                q = q.where(ride.c[cm["start_ts"]] == start_ts)
            if cm["job_key"] and r.get("Key") is not None:
                q = q.where(ride.c[cm["job_key"]] == str(r.get("Key")))
            elif cm["job_name"] and r.get("Name") is not None:
                q = q.where(ride.c[cm["job_name"]] == str(r.get("Name")))
            exists = db.execute(q.limit(1)).scalar_one_or_none()
            if exists:
                skipped += 1
                continue

            db.execute(insert(ride).values(**vals))
            inserted += 1
        except Exception:
            skipped += 1

    db.commit()
    return inserted, skipped

def person_rides(db: Session, person_id: int, limit: int = 200) -> List[Dict[str, Any]]:
    """
    Return normalized ride rows for a person.
    Keys in each row (missing values are None):
      date, ride_start_ts, key, name, miles, gross, net_pay, code, source_file, source_page
    """
    ride = _reflect_ride(db)
    cm = _ride_colmap(ride)

    cols = [ride.c[cm["pk"]].label("ride_id")]
    if cm["start_ts"]:    cols.append(ride.c[cm["start_ts"]].label("ride_start_ts"))
    if cm["job_key"]:     cols.append(ride.c[cm["job_key"]].label("job_key"))
    if cm["job_name"]:    cols.append(ride.c[cm["job_name"]].label("job_name"))
    if cm["miles"]:       cols.append(ride.c[cm["miles"]].label("miles"))
    if cm["gross"]:       cols.append(ride.c[cm["gross"]].label("gross"))
    if cm["net_pay"]:     cols.append(ride.c[cm["net_pay"]].label("net_pay"))
    if cm["code"]:        cols.append(ride.c[cm["code"]].label("code"))
    if cm["source_file"]: cols.append(ride.c[cm["source_file"]].label("source_file"))
    if cm["source_page"]: cols.append(ride.c[cm["source_page"]].label("source_page"))

    order_col = ride.c[cm["start_ts"]] if cm["start_ts"] else ride.c[cm["pk"]]
    stmt = (
        select(*cols)
        .where(ride.c[cm["person_id"]] == person_id)
        .order_by(order_col.asc())
        .limit(limit)
    )

    rows = db.execute(stmt).mappings().all()
    out: List[Dict[str, Any]] = []
    for r in rows:
        start_ts = r.get("ride_start_ts")
        out.append({
            "date":       (start_ts.date() if start_ts else None),
            "ride_start_ts": start_ts,
            "key":        r.get("job_key") if "job_key" in r else None,
            "name":       r.get("job_name") if "job_name" in r else None,
            "miles":      r.get("miles"),
            "gross":      r.get("gross"),
            "net_pay":    r.get("net_pay"),
            "code":       r.get("code"),
            "source_file":r.get("source_file"),
            "source_page":r.get("source_page"),
        })
    return out


def person_summary(db: Session, person_id: int) -> Dict[str, Any]:
    """
    Aggregate a single person's summary from the ride table.
    Falls back to zeros when columns aren’t present.
    Attempts to pull RAD/WUD from pay_summary if available; otherwise 0.
    """
    ride = _reflect_ride(db)
    cm = _ride_colmap(ride)

    p: Person | None = db.get(Person, person_id)

    # date range + counts
    start_col = ride.c[cm["start_ts"]] if cm["start_ts"] else None
    day_expr = cast(start_col, Date) if start_col is not None else None

    agg_cols = [
        func.count().label("runs"),
    ]
    if day_expr is not None:
        agg_cols.extend([
            func.min(day_expr).label("start_day"),
            func.max(day_expr).label("end_day"),
            func.count(func.distinct(day_expr)).label("days"),
        ])
    else:
        # Provide sane fallbacks if no timestamp column exists
        agg_cols.extend([
            literal(None).label("start_day"),
            literal(None).label("end_day"),
            literal(0).label("days"),
        ])

    # numeric sums with safe fallbacks
    miles_sum = (func.coalesce(ride.c[cm["miles"]], 0.0) if cm["miles"] else literal(0.0))
    gross_sum = (func.coalesce(ride.c[cm["gross"]], 0.0) if cm["gross"] else literal(0.0))
    net_sum   = (func.coalesce(ride.c[cm["net_pay"]], 0.0) if cm["net_pay"] else literal(0.0))

    agg_cols.extend([
        func.coalesce(func.sum(miles_sum), 0.0).label("miles"),
        func.coalesce(func.sum(gross_sum), 0.0).label("gross"),
        func.coalesce(func.sum(net_sum),   0.0).label("net_pay"),
    ])

    stmt = select(*agg_cols).where(ride.c[cm["person_id"]] == person_id)
    res = db.execute(stmt).mappings().one()

    # Optional: try to read RAD / WUD from a view if present
    rad = 0.0
    wud = 0.0
    try:
        md = MetaData()
        pay_summary = Table("pay_summary", md, autoload_with=db.bind)
        cols = set(pay_summary.c.keys())
        filt = []
        if "person_id" in cols:
            filt.append(pay_summary.c.person_id == person_id)
        elif "person" in cols and p:
            filt.append(pay_summary.c.person == p.full_name)
        if filt:
            sel_cols = []
            for c in ("rad", "wud"):
                if c in cols:
                    sel_cols.append(pay_summary.c[c].label(c))
            if sel_cols:
                row = db.execute(select(*sel_cols).where(and_(*filt)).limit(1)).mappings().first()
                if row:
                    rad = float(row.get("rad") or 0.0)
                    wud = float(row.get("wud") or 0.0)
    except Exception:
        pass  # view absent or different shape — harmless

    # Build pretty "Active Between"
    start_day: date | None = res.get("start_day")
    end_day:   date | None = res.get("end_day")
    if start_day and end_day:
        active_between = f"{start_day.strftime('%-m/%-d/%Y')} - {end_day.strftime('%-m/%-d/%Y')}"
    else:
        active_between = ""

    # If there’s no person.code column, try to surface a code from rides (first non-null)
    code_val = ""
    if cm["code"]:
        code_row = db.execute(
            select(ride.c[cm["code"]]).where(
                ride.c[cm["person_id"]] == person_id,
                ride.c[cm["code"]] != literal(None)
            ).limit(1)
        ).scalar_one_or_none()
        if code_row:
            code_val = str(code_row)

    return {
        "person_id": person_id,
        "person": p.full_name if p else "",
        "code": code_val,
        "active_between": active_between,
        "days": int(res.get("days") or 0),
        "runs": int(res.get("runs") or 0),
        "miles": float(res.get("miles") or 0.0),
        "gross": float(res.get("gross") or 0.0),
        "rad": float(rad),
        "wud": float(wud),
        "net_pay": float(res.get("net_pay") or 0.0),
    }   

def people_rollup(
    db: Session,
    start: date | None = None,
    end: date | None = None,
    person_id: int | None = None,
    code: str | None = None,
):
    ride = _reflect_ride(db)
    cmap = _ride_colmap(ride)

    c_pid   = ride.c[cmap["person_id"]]
    #c_rid   = ride.c[cmap["ride_id"]] if cmap["ride_id"] else None
    name = (cmap.get("ride_id") if isinstance(cmap, dict) else None) or ("ride_id" if hasattr(ride, "c") and "ride_id" in ride.c else None)
    c_rid = ride.c[name] if name else None
    c_day   = ride.c[cmap["date"]] if cmap["date"] else cast(ride.c[cmap["start_ts"]], Date)
    c_code  = ride.c[cmap["code"]] if cmap["code"] else cast(null(), String).label("code")
    c_miles = ride.c[cmap["miles"]] if cmap["miles"] else None
    c_gross = ride.c[cmap["gross"]] if cmap["gross"] else None
    c_net   = ride.c[cmap["net_pay"]] if cmap["net_pay"] else None

    stmt = (
        select(
            Person.person_id.label("person_id"),
            Person.full_name.label("person"),
            func.max(c_code).label("code"),
            func.min(c_day).label("first_date"),
            func.max(c_day).label("last_date"),
            func.count(func.distinct(c_day)).label("days"),
            (func.count(c_rid) if c_rid is not None else func.count()).label("runs"),
            (func.coalesce(func.sum(c_miles), 0.0) if c_miles is not None else cast(0.0, Float)).label("miles"),
            (func.coalesce(func.sum(c_gross), 0.0) if c_gross is not None else cast(0.0, Float)).label("gross"),
            (func.coalesce(func.sum(c_net),   0.0) if c_net   is not None else cast(0.0, Float)).label("net_pay"),
        )
        .select_from(Person)
        .join(ride, c_pid == Person.person_id, isouter=True)
        .group_by(Person.person_id, Person.full_name)
        .order_by(Person.full_name.asc())
    )

    if start is not None:
        stmt = stmt.where(c_day >= start)
    if end is not None:
        stmt = stmt.where(c_day <= end)
    if person_id is not None:
        stmt = stmt.where(Person.person_id == person_id)
    if code is not None:
        # when you don’t store code on person, we filter via rides
        stmt = stmt.where(c_code == code)

    rows = db.execute(stmt).all()

    def fmt_date(d):
        return None if d is None else d.strftime("%-m/%-d/%Y")

    out, totals = [], {"days":0, "runs":0, "miles":0.0, "gross":0.0, "rad":0.0, "wud":0.0, "net_pay":0.0}
    for r in rows:
        days  = int(r.days or 0)
        runs  = int(r.runs or 0)
        miles = float(r.miles or 0.0)
        gross = float(r.gross or 0.0)
        net   = float(r.net_pay or 0.0)

        # WUD = $2/run; RAD = gross − net − WUD  (matches your screenshot math)
        wud = round(runs * 2.00, 2)
        rad = round((gross - net) - wud, 2)

        out.append({
            "person_id": r.person_id,
            "person": r.person,
            "code": r.code,
            "active_between": f"{fmt_date(r.first_date)} - {fmt_date(r.last_date)}" if r.first_date and r.last_date else "",
            "days": days,
            "runs": runs,
            "miles": round(miles, 1),
            "gross": round(gross, 2),
            "rad": round(rad, 2),
            "wud": round(wud, 2),
            "net_pay": round(net, 2),
        })

        totals["days"] += days
        totals["runs"] += runs
        totals["miles"] += miles
        totals["gross"] += gross
        totals["rad"] += rad
        totals["wud"] += wud
        totals["net_pay"] += net

    for k in ("miles","gross","rad","wud","net_pay"):
        totals[k] = round(totals[k], 2)

    return {"rows": out, "totals": totals}

def load_excel_config(cfg_path: str):
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def _to_ts(d, t, tz):
    if pd.isna(d) and pd.isna(t):
        return None
    if isinstance(d, (pd.Timestamp, datetime)):
        d = d.to_pydatetime()
    elif isinstance(d, date):
        d = datetime.combine(d, time.min)
    elif pd.isna(d):
        d = datetime.combine(date.today(), time.min)

    if isinstance(t, (pd.Timestamp, datetime)):
        t = t.to_pydatetime().time()
    elif isinstance(t, time):
        t = t
    elif pd.isna(t):
        t = time.min

    dt = datetime.combine(d.date(), t)
    return tz.localize(dt).astimezone(pytz.UTC)

def upsert_person(session: Session, external_id: str, full_name: str | None):
    stmt = select(models.Person).where(models.Person.external_id == external_id)
    person = session.scalars(stmt).first()
    if person:
        if full_name and not person.full_name:
            person.full_name = full_name
        return person
    person = models.Person(external_id=external_id, full_name=full_name, active=True)
    session.add(person)
    session.flush()
    return person

def import_payroll_excel(db: Session, xlsx_path: str, cfg_path: str):
    """
    Reads the Excel payroll and inserts rides & persons.
    """
    cfg = load_excel_config(cfg_path)
    mapper = cfg["columns"]["details"]
    df = pd.read_excel(xlsx_path, sheet_name=cfg["sheet_names"]["details"]).rename(columns=mapper)
    df = df[list(mapper.keys())]

    for c in ("base_fare", "tips", "adjustments", "miles", "duration_min"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

    tz = pytz.timezone(cfg["defaults"].get("timezone", "America/New_York"))
    df["date"] = pd.to_datetime(df.get("date"), errors="coerce")
    df["start_ts"] = pd.to_datetime(df.get("start_ts"), errors="coerce")
    df["end_ts"] = pd.to_datetime(df.get("end_ts"), errors="coerce")

    df["ride_start_ts"] = [
        _to_ts(d, (s.to_pydatetime().time() if not pd.isna(s) else None), tz)
        for d, s in zip(df["date"], df["start_ts"])
    ]
    df["ride_end_ts"] = [
        _to_ts(d, (e.to_pydatetime().time() if not pd.isna(e) else None), tz)
        for d, e in zip(df["date"], df["end_ts"])
    ]

    # Convert miles → km
    df["distance_km"] = df["miles"] * 1.60934

    company = Path(xlsx_path).stem
    df["source_ref"] = df.apply(lambda r: f"{company}:{r.trip_id}", axis=1)
    df["currency"] = cfg["defaults"].get("currency", "USD")

    inserted, skipped = 0, 0
    for row in df.itertuples(index=False):
        person = upsert_person(db, row.driver_external_id, getattr(row, "driver_name", None))

        if row.ride_end_ts and row.ride_start_ts and row.ride_end_ts < row.ride_start_ts:
            skipped += 1
            continue

        ride = models.Ride(
            person_id=person.person_id,
            ride_start_ts=row.ride_start_ts,
            ride_end_ts=row.ride_end_ts,
            origin=getattr(row, "origin", None),
            destination=getattr(row, "destination", None),
            distance_km=float(getattr(row, "distance_km", 0) or 0),
            duration_min=float(getattr(row, "duration_min", 0) or 0),
            base_fare=float(getattr(row, "base_fare", 0) or 0),
            tips=float(getattr(row, "tips", 0) or 0),
            adjustments=float(getattr(row, "adjustments", 0) or 0),
            currency=row.currency,
            source_ref=row.source_ref,
        )
        db.add(ride)
        inserted += 1

    db.commit()
    return {"inserted": inserted, "skipped": skipped}




