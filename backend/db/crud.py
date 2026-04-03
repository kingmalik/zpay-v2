from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Mapping

import pandas as pd
import pytz
import yaml
import re
import sqlalchemy as sa
from sqlalchemy import Date, MetaData, Table, and_, cast, func, literal, null, select, tuple_
from sqlalchemy.orm import Session
from sqlalchemy.types import Float, String
from sqlalchemy.orm.exc import MultipleResultsFound
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert

from backend.db.models import Person, Ride, ZRateService



KM_TO_MILES = 0.621371

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
        "ride_id":       pick("ride_id", "id"),
        "pk":            pick("ride_id", "id"),
        "person_id":     pick("person_id"),
        "start_ts":      pick("ride_start_ts", "start_ts"),
        "date":          pick("ride_date", "date"),
        "miles":         pick("miles", "distance_miles"),
        "gross":         pick("gross_pay", "gross"),
        "net_pay":       pick("net_pay"),
        "deduction":     pick("deduction"),
        "spiff":         pick("spiff"),
        "distance_miles":pick("distance_miles", "miles"),
        "base_fare":     pick("base_fare"),
        "tips":          pick("tips"),
        "adjustments":   pick("adjustments"),
        "source_ref":    pick("source_ref"),
        "job_key":       pick("service_ref", "source_ref", "key"),
        "job_name":      pick("service_name"),
        "service_key":   pick("service_ref", "key"),
        "source_file":   pick("source_file"),
        "source_page":   pick("source_page"),
        "code":          pick("code"),
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


def bulk_insert_rides(db: Session, rides: list[dict[str, Any]]) -> int:
    if not rides:
        return 0

    ride = _reflect_ride(db)
    cmap = _ride_colmap(ride)

    c_pid = ride.c[cmap["person_id"]]
    c_key = ride.c[cmap["service_key"]] if cmap.get("service_key") else None

    # Build set of existing (person_id, key)
    existing = set()
    if c_key is not None:
        pairs = []
        for r in rides:
            pid = r.get("person_id")
            k = r.get("key")
            if pid is not None and k:
                pairs.append((int(pid), str(k)))

        pairs = list({p for p in pairs})
        if pairs:
            stmt = select(c_pid, c_key).where(tuple_(c_pid, c_key).in_(pairs))
            for pid, k in db.execute(stmt).all():
                existing.add((int(pid), str(k)))

    to_insert = []
    for r in rides:
        pid = r.get("person_id")
        k = r.get("key")

        if c_key is not None and pid is not None and k:
            uniq = (int(pid), str(k))
            if uniq in existing:
                continue
            existing.add(uniq)

        to_insert.append(r)

    if not to_insert:
        return 0

    db.execute(ride.insert(), to_insert)
    db.commit()
    return len(to_insert)


def person_rides(db: Session, person_id: int, limit: int = 200) -> List[Dict[str, Any]]:
    """
    Return normalized ride rows for a person.
    Keys in each row (missing values are None):
      date, ride_start_ts, key, name, miles, gross, net_pay, code, source_file, source_page
    """
    ride = _reflect_ride(db)
    cm = _ride_colmap(ride)

    pk_col = cm.get("pk") or cm.get("ride_id")
    cols = [ride.c[pk_col].label("ride_id")]
    if cm.get("start_ts"):    cols.append(ride.c[cm["start_ts"]].label("ride_start_ts"))
    if cm.get("job_key"):     cols.append(ride.c[cm["job_key"]].label("job_key"))
    if cm.get("job_name"):    cols.append(ride.c[cm["job_name"]].label("job_name"))
    if cm.get("miles"):       cols.append(ride.c[cm["miles"]].label("miles"))
    if cm.get("gross"):       cols.append(ride.c[cm["gross"]].label("gross"))
    if cm.get("net_pay"):     cols.append(ride.c[cm["net_pay"]].label("net_pay"))
    if cm.get("code"):        cols.append(ride.c[cm["code"]].label("code"))
    if cm.get("source_file"): cols.append(ride.c[cm["source_file"]].label("source_file"))
    if cm.get("source_page"): cols.append(ride.c[cm["source_page"]].label("source_page"))

    order_col = ride.c[cm["start_ts"]] if cm.get("start_ts") else ride.c[pk_col]
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

KM_TO_MILES = 0.621371  # define once near top of file


def people_rollup(db: Session, start: date | None = None, end: date | None = None,
                  person_id: int | None = None, code: str | None = None):

    ride = _reflect_ride(db)
    cmap = _ride_colmap(ride)

    def col(name: str):
        # safe column getter (returns None if missing)
        if name in (cmap or {}):
            key = cmap[name]
            return ride.c[key] if key else None
        return ride.c[name] if hasattr(ride, "c") and name in ride.c else None

    c_pid = col("person_id")
    if c_pid is None:
        raise RuntimeError("ride table is missing person_id column mapping")

    # ✅ Use ride_date_ts and CAST TO DATE (for grouping)
    c_day_ts = col("ride_start_ts") 
    if c_day_ts is None:
        raise RuntimeError("ride table is missing ride_date_ts/ride_start_ts column mapping")
    c_day = cast(c_day_ts, Date)

    # ✅ Count runs: prefer service_key, else ride_id
    c_run_id = col("service_key") or col("ride_key") or col("ride_id")

    # ✅ Person code: use ride_code (or person.external_id)
    c_code = col("ride_code")  # your ride table has ride_code
    # if ride_code is not stored per ride, you can also use Person.external_id instead

    # ✅ Miles: your distance_miles d column is currently storing miles (based on your DB output)
    c_miles = col("distance_miles")

    # ✅ Gross/Net: use stored columns gross_pay/net_pay if present
    c_gross = col("gross_pay")
    c_net   = col("net_pay")

    # gross components (adjust if your schema differs)
    base = col("base_fare")
    tips = col("tips")
    adj  = col("adjustments")
    
    if base is None: base = literal(0)
    else: base = func.coalesce(base, 0)

    if tips is None: tips = literal(0)
    else: tips = func.coalesce(tips, 0)

    if adj is None: adj = literal(0)
    else: adj = func.coalesce(adj, 0)

    #c_gross = base + tips + adj

    # if you store net directly use it, otherwise compute later
    c_net = col("net_pay")

    stmt = (
        select(
            Person.person_id.label("person_id"),
            Person.full_name.label("person"),
            Person.external_id.label("code"),
            func.min(c_day).label("first_date"),
            func.max(c_day).label("last_date"),
            func.count(func.distinct(c_day)).label("days"),
            func.count(c_run_id).label("runs"),
            func.coalesce(c_miles).label("miles"),
            func.coalesce(func.sum(c_gross), 0.0).label("gross_pay"),
            func.coalesce(func.sum(c_net), 0.0).label("net_pay"),
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
    if code is not None and c_code is not None:
        stmt = stmt.where(c_code == code)

    rows = db.execute(stmt).all()

    def fmt_date(d):
        return None if d is None else d.strftime("%-m/%-d/%Y")

    out = []
    totals = {"days": 0, "runs": 0, "miles": 0.0, "gross": 0.0, "rad": 0.0, "wud": 0.0, "net_pay": 0.0}

    for r in rows:
        days  = int(r.days or 0)
        runs  = int(r.runs or 0)          # <-- IMPORTANT: this must be an int
        miles = float(r.miles or 0.0)
        gross = float(r.gross_pay or 0.0)
        net   = float(r.net_pay or 0.0)

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
            "rad": rad,
            "wud": wud,
            "net_pay": round(net, 2),
        })

        totals["days"] += days
        totals["runs"] += runs
        totals["miles"] += miles
        totals["gross"] += gross
        totals["rad"] += rad
        totals["wud"] += wud
        totals["net_pay"] += net

    for k in ("miles", "gross", "rad", "wud", "net_pay"):
        totals[k] = round(totals[k], 2)

    return {"rows": out, "totals": totals}


    #SP PAY SUMMARY
    #SP ITEMIZED REPORT

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
def normalize_name(full_name: str) -> str:
    # trim, collapse internal whitespace, lowercase
    return re.sub(r"\s+", " ", full_name.strip()).lower()

def upsert_person(db: Session, external_id: str | None, full_name: str | None) -> Person | None:
    external_id = external_id.strip() if isinstance(external_id, str) else None
    full_name = full_name.strip() if isinstance(full_name, str) else None

    # cannot create person without name (DB constraint)
    if not full_name:
        # If you want to allow anonymous people, change schema to nullable full_name.
        return None

    # 1) Try by external_id if present
    if external_id:
        person = db.query(Person).filter(Person.external_id == external_id).one_or_none()
        if person:
            if person.full_name.strip() != full_name:
                person.full_name = full_name
            return person

    # 2) Try by normalized name when no external_id (or ext missing)
    # NOTE: match your DB normalization if you used regexp_replace index
    norm = " ".join(full_name.lower().split())
    person = (
        db.query(Person)
        .filter(sa.func.lower(sa.func.regexp_replace(sa.func.trim(Person.full_name), r"\s+", " ", "g")) == norm)
        .filter(Person.external_id.is_(None))
        .one_or_none()
    )
    if person:
        return person

    # 3) Insert new
    person = Person(external_id=external_id, full_name=full_name)
    db.add(person)
    db.flush()  # get person_id
    return person

def ensure_rate_services(
    db: Session,
    services: Iterable[Mapping[str, Any]],
    *,
    source: str,
    company_name: str,
) -> None:
    # Must match the DB unique index/constraint:
    # uq_z_rate_service_scope_service_name => (source, company_name, service_name)
    seen: set[tuple[str, str, str]] = set()
    payload: list[dict[str, Any]] = []

    src = (source or "").strip()
    comp = (company_name or "").strip()

    if not src or not comp:
        return

    for s in services:
        service_name = (s.get("service_name") or "").strip()
        service_key = (s.get("service_key") or "").strip()

        if not service_name:
            continue

        # service_key can be optional depending on your data,
        # but if you require it, keep this guard:
        if not service_key:
            continue

        scope_key = (src, comp, service_name)
        if scope_key in seen:
            continue
        seen.add(scope_key)

        currency = (s.get("currency") or "USD")
        currency = (currency.strip() if isinstance(currency, str) else "USD") or "USD"

        payload.append(
            {
                "source": src,
                "company_name": comp,
                "service_key": service_key,
                "service_name": service_name,
                "currency": currency,
                "active": bool(s.get("active", True)),
                "default_rate": s.get("default_rate", 0),
            }
        )

    if not payload:
        return

    stmt = (
        insert(ZRateService)
        .values(payload)
        .on_conflict_do_nothing(
            index_elements=["source", "company_name", "service_key"]
        )
    )
    db.execute(stmt)