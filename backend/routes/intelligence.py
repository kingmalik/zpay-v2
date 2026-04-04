from pathlib import Path
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import Ride, Person, PayrollBatch, DriverBalance
from backend.routes.insights import _build_snapshot
from backend.routes.analytics import _get_companies

router = APIRouter(prefix="/intelligence", tags=["intelligence"])

_templates = None


def templates():
    global _templates
    if _templates is None:
        templates_dir = Path(__file__).resolve().parents[1] / "templates"
        _templates = Jinja2Templates(directory=str(templates_dir))
    return _templates


# ---------------------------------------------------------------------------
# Section 2 — Alerts
# ---------------------------------------------------------------------------

def _check_upload_reminder(db: Session) -> list[dict]:
    """On Mondays only: alert if one company hasn't uploaded the latest school week yet.
    Only compares companies that have at least one batch ever — avoids false alarms
    for shops that only use one company.
    """
    from datetime import date
    if date.today().weekday() != 0:  # 0 = Monday
        return []

    # Count total batches per source — only flag companies that have ever uploaded
    from sqlalchemy import func as _func
    source_counts = {
        src: cnt for src, cnt in
        db.query(PayrollBatch.source, _func.count(PayrollBatch.payroll_batch_id))
        .group_by(PayrollBatch.source).all()
    }
    fa_active = source_counts.get("acumen", 0) > 0
    ed_active = source_counts.get("maz", 0) > 0

    # If only one company is active, no cross-company comparison makes sense
    if not (fa_active and ed_active):
        return []

    school_week_map = _get_school_week_map(db)
    fa_weeks = [wn for (src, _), wn in school_week_map.items() if src == "acumen"]
    ed_weeks = [wn for (src, _), wn in school_week_map.items() if src == "maz"]

    if not fa_weeks and not ed_weeks:
        return []

    max_fa = max(fa_weeks) if fa_weeks else 0
    max_ed = max(ed_weeks) if ed_weeks else 0
    expected = max(max_fa, max_ed)

    alerts = []
    if max_fa < expected:
        weeks_behind = expected - max_fa
        msg = (f"Week {expected}: FirstAlt not uploaded yet"
               if weeks_behind == 1 else
               f"Weeks {max_fa + 1}–{expected}: FirstAlt missing ({weeks_behind} weeks behind)")
        alerts.append({"type": "warning", "message": msg, "url": "/upload"})
    if max_ed < expected:
        weeks_behind = expected - max_ed
        msg = (f"Week {expected}: EverDriven not uploaded yet"
               if weeks_behind == 1 else
               f"Weeks {max_ed + 1}–{expected}: EverDriven missing ({weeks_behind} weeks behind)")
        alerts.append({"type": "warning", "message": msg, "url": "/upload"})
    return alerts


def _build_alerts(db: Session) -> list[dict]:
    alerts = []

    # 1. Rides with z_rate == 0
    zero_rate_count = (
        db.query(func.count(Ride.ride_id))
        .filter(Ride.z_rate == 0)
        .scalar()
        or 0
    )
    if zero_rate_count > 0:
        alerts.append({
            "type": "danger",
            "message": f"{zero_rate_count} rides have no rate assigned",
            "url": "/admin/rates",
        })

    # 2. Pay weeks present in one source but not the other
    # Use date-proximity matching (±7 days) — each company's school week
    # starts on a different calendar day so exact or ISO-week matching gives false gaps.
    def _week_dates(source: str) -> list:
        rows = (
            db.query(PayrollBatch.week_start)
            .filter(PayrollBatch.source == source, PayrollBatch.week_start.isnot(None))
            .distinct()
            .all()
        )
        return sorted(
            ws if hasattr(ws, "toordinal") else date.fromisoformat(str(ws))
            for (ws,) in rows
            if ws is not None
        )

    from datetime import timedelta
    acumen_dates = _week_dates("acumen")
    maz_dates    = _week_dates("maz")

    # For each EverDriven week, check if Acumen has a week within 7 days
    truly_missing = []
    for maz_d in maz_dates:
        has_match = any(abs((maz_d - ac_d).days) <= 7 for ac_d in acumen_dates)
        if not has_match:
            truly_missing.append(maz_d)

    if truly_missing:
        week_labels = ", ".join(d.strftime("%-m/%-d") for d in truly_missing)
        alerts.append({
            "type": "warning",
            "message": f"Acumen has no upload matching EverDriven week{'s' if len(truly_missing) != 1 else ''}: {week_labels}",
            "url": "/upload",
        })

    # 3. Drivers withheld (carried_over > 0) for 2+ batches
    withheld_subq = (
        db.query(DriverBalance.person_id)
        .filter(DriverBalance.carried_over > 0)
        .group_by(DriverBalance.person_id)
        .having(func.count(DriverBalance.payroll_batch_id) >= 2)
        .subquery()
    )
    withheld_count = (
        db.query(func.count())
        .select_from(withheld_subq)
        .scalar()
        or 0
    )
    if withheld_count > 0:
        alerts.append({
            "type": "warning",
            "message": f"{withheld_count} drivers withheld for 2+ weeks",
            "url": "/summary",
        })

    # 4. Monday upload reminder — alert if one company is behind on the latest week
    alerts += _check_upload_reminder(db)

    return alerts


# ---------------------------------------------------------------------------
# School week numbering helper
# ---------------------------------------------------------------------------

def _get_school_week_map(db: Session) -> dict:
    """Returns {(source, week_start_date): school_week_num}.

    EverDriven (maz): week number extracted from batch_ref e.g. "WASO291-OY2026W03" → 3.
    Acumen: week number assigned by rank of sorted week_start (earliest = W1).
    """
    import re
    result: dict = {}

    maz_rows = (
        db.query(PayrollBatch.week_start, PayrollBatch.batch_ref)
        .filter(
            PayrollBatch.source == "maz",
            PayrollBatch.week_start.isnot(None),
            PayrollBatch.batch_ref.isnot(None),
        )
        .distinct(PayrollBatch.week_start)
        .all()
    )
    for ws, batch_ref in maz_rows:
        m = re.search(r'W(\d+)$', batch_ref or '')
        if m:
            result[("maz", ws)] = int(m.group(1))

    acumen_rows = (
        db.query(PayrollBatch.week_start)
        .filter(PayrollBatch.source == "acumen", PayrollBatch.week_start.isnot(None))
        .distinct()
        .order_by(PayrollBatch.week_start)
        .all()
    )
    for rank, (ws,) in enumerate(acumen_rows, start=1):
        result[("acumen", ws)] = rank

    return result


# ---------------------------------------------------------------------------
# Section 3 — Trends
# ---------------------------------------------------------------------------

def _build_trends(db: Session) -> tuple[list[dict], dict]:
    school_week_map = _get_school_week_map(db)

    # Gather per-(source, week_start) aggregates from payroll_batch + rides
    rows = (
        db.query(
            PayrollBatch.source,
            PayrollBatch.week_start,
            PayrollBatch.week_end,
            func.sum(Ride.net_pay).label("revenue"),
            func.sum(Ride.net_pay - Ride.z_rate).label("profit"),
            func.count(Ride.ride_id).label("rides"),
        )
        .join(Ride, Ride.payroll_batch_id == PayrollBatch.payroll_batch_id)
        .filter(PayrollBatch.week_start.isnot(None))
        .group_by(PayrollBatch.source, PayrollBatch.week_start, PayrollBatch.week_end)
        .all()
    )

    # Aggregate by school week number (merging both sources into one row per week)
    by_week: dict[int, dict] = {}
    for r in rows:
        week_num = school_week_map.get((r.source, r.week_start))
        if week_num is None:
            continue
        if week_num not in by_week:
            by_week[week_num] = {
                "acumen_revenue": 0.0, "acumen_profit": 0.0,
                "maz_revenue": 0.0, "maz_profit": 0.0,
                "total_rides": 0,
            }
        entry = by_week[week_num]
        if r.source == "acumen":
            entry["acumen_revenue"] += float(r.revenue or 0)
            entry["acumen_profit"] += float(r.profit or 0)
        elif r.source == "maz":
            entry["maz_revenue"] += float(r.revenue or 0)
            entry["maz_profit"] += float(r.profit or 0)
        entry["total_rides"] += int(r.rides or 0)

    # Last 8 school weeks, ascending for display
    sorted_week_nums = sorted(by_week.keys(), reverse=True)[:8]
    sorted_week_nums = sorted(sorted_week_nums)

    trends = []
    for wn in sorted_week_nums:
        entry = by_week[wn]
        trends.append({
            "week_label": f"Week {wn}",
            "acumen_revenue": round(entry["acumen_revenue"], 2),
            "acumen_profit": round(entry["acumen_profit"], 2),
            "maz_revenue": round(entry["maz_revenue"], 2),
            "maz_profit": round(entry["maz_profit"], 2),
            "total_rides": entry["total_rides"],
        })

    # Projection: average last 4 weeks total revenue/profit, scale to full month
    projection = _build_projection(trends)

    # Comparison: recent 4 weeks vs prior 4 weeks
    comparison = _build_comparison(trends)

    return trends, projection, comparison


def _build_comparison(trends: list[dict]) -> dict:
    """Compare the most recent 4 weeks against the prior 4 weeks."""
    recent = trends[-4:] if len(trends) >= 4 else trends
    prior = trends[-8:-4] if len(trends) >= 8 else []

    def totals(weeks):
        rev = sum(w["acumen_revenue"] + w["maz_revenue"] for w in weeks)
        profit = sum(w["acumen_profit"] + w["maz_profit"] for w in weeks)
        return round(rev, 2), round(profit, 2)

    recent_revenue, recent_profit = totals(recent)
    prior_revenue, prior_profit = totals(prior)

    def pct_change(new_val, old_val):
        if old_val == 0:
            return None
        return round((new_val - old_val) / abs(old_val) * 100, 1)

    return {
        "recent_revenue": recent_revenue,
        "recent_profit": recent_profit,
        "prior_revenue": prior_revenue,
        "prior_profit": prior_profit,
        "revenue_change_pct": pct_change(recent_revenue, prior_revenue),
        "profit_change_pct": pct_change(recent_profit, prior_profit),
    }


def _build_projection(trends: list[dict]) -> dict:
    last_4 = trends[-4:] if len(trends) >= 4 else trends
    basis_weeks = len(last_4)

    if basis_weeks == 0:
        today = date.today()
        return {
            "month_name": today.strftime("%B"),
            "projected_revenue": 0.0,
            "projected_profit": 0.0,
            "basis_weeks": 0,
            "forecast_months": [],
            "is_school_active": True,
        }

    # Exponential weighted average — recent weeks matter more
    weights = [0.1, 0.2, 0.3, 0.4] if basis_weeks >= 4 else [1.0 / basis_weeks] * basis_weeks
    weights = weights[-basis_weeks:]  # trim to available
    total_weight = sum(weights)

    avg_revenue = sum(
        (w["acumen_revenue"] + w["maz_revenue"]) * wt
        for w, wt in zip(last_4, weights)
    ) / total_weight

    avg_profit = sum(
        (w["acumen_profit"] + w["maz_profit"]) * wt
        for w, wt in zip(last_4, weights)
    ) / total_weight

    today = date.today()
    import calendar

    # School year awareness: Sep-Jun active, Jul-Aug low (~10% of normal)
    SCHOOL_MONTHS = {9, 10, 11, 12, 1, 2, 3, 4, 5, 6}  # Sep–Jun

    def is_school_month(month: int) -> bool:
        return month in SCHOOL_MONTHS

    is_school_active = is_school_month(today.month)

    # Build 3-month forecast
    forecast_months = []
    for offset in range(3):
        month = (today.month + offset - 1) % 12 + 1
        year = today.year + ((today.month + offset - 1) // 12)
        month_name = calendar.month_name[month]
        days_in_m = calendar.monthrange(year, month)[1]
        weeks_in_m = days_in_m / 7.0

        # Apply school-year multiplier
        multiplier = 1.0 if is_school_month(month) else 0.10

        proj_rev = round(avg_revenue * weeks_in_m * multiplier, 2)
        proj_prof = round(avg_profit * weeks_in_m * multiplier, 2)
        confidence_low = round(proj_rev * 0.9, 2)
        confidence_high = round(proj_rev * 1.1, 2)

        forecast_months.append({
            "month_name": month_name,
            "year": year,
            "projected_revenue": proj_rev,
            "projected_profit": proj_prof,
            "confidence_low": confidence_low,
            "confidence_high": confidence_high,
            "is_school": is_school_month(month),
        })

    # Current month projection
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    total_weeks_in_month = days_in_month / 7.0
    multiplier = 1.0 if is_school_active else 0.10

    projected_revenue = round(avg_revenue * total_weeks_in_month * multiplier, 2)
    projected_profit = round(avg_profit * total_weeks_in_month * multiplier, 2)

    return {
        "month_name": today.strftime("%B"),
        "projected_revenue": projected_revenue,
        "projected_profit": projected_profit,
        "basis_weeks": basis_weeks,
        "forecast_months": forecast_months,
        "is_school_active": is_school_active,
    }


def _build_reliability(db: Session) -> list[dict]:
    """Attendance-based reliability score per driver.

    Reliability = (weeks with rides / total active weeks) * 100
    """
    from sqlalchemy import distinct as sa_distinct

    # Get all distinct week_starts
    all_weeks = (
        db.query(sa_distinct(PayrollBatch.week_start))
        .filter(PayrollBatch.week_start.isnot(None))
        .all()
    )
    total_weeks = len(all_weeks)
    if total_weeks == 0:
        return []

    # For each driver, count distinct weeks they have rides
    driver_weeks = (
        db.query(
            Person.person_id,
            Person.full_name,
            func.count(sa_distinct(PayrollBatch.week_start)).label("weeks_active"),
        )
        .join(Ride, Ride.person_id == Person.person_id)
        .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
        .filter(PayrollBatch.week_start.isnot(None))
        .group_by(Person.person_id, Person.full_name)
        .all()
    )

    # Get first and last ride week per driver to determine their active span
    driver_span = (
        db.query(
            Person.person_id,
            func.min(PayrollBatch.week_start).label("first_week"),
            func.max(PayrollBatch.week_start).label("last_week"),
        )
        .join(Ride, Ride.person_id == Person.person_id)
        .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
        .filter(PayrollBatch.week_start.isnot(None))
        .group_by(Person.person_id)
        .all()
    )
    span_map = {r.person_id: (r.first_week, r.last_week) for r in driver_span}

    # Count weeks within each driver's span
    week_list = sorted([w[0] for w in all_weeks])
    results = []
    for row in driver_weeks:
        first, last = span_map.get(row.person_id, (None, None))
        if first is None or last is None:
            continue

        # Count total weeks in their active span
        span_weeks = sum(1 for w in week_list if first <= w <= last)
        if span_weeks == 0:
            continue

        reliability = round(row.weeks_active / span_weeks * 100, 1)
        weeks_missed = span_weeks - row.weeks_active

        results.append({
            "name": row.full_name,
            "reliability": reliability,
            "weeks_active": row.weeks_active,
            "total_weeks": span_weeks,
            "weeks_missed": weeks_missed,
            "at_risk": reliability < 80,
        })

    # Sort by reliability descending
    results.sort(key=lambda x: x["reliability"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Section 4 — Driver Performance
# ---------------------------------------------------------------------------

def _build_driver_performance(db: Session) -> tuple[list[dict], list[dict], list[dict]]:
    # All drivers with rides in last 30 days, ordered by profit
    driver_rows = (
        db.query(
            Person.full_name.label("name"),
            PayrollBatch.company_name.label("company"),
            func.count(Ride.ride_id).label("rides"),
            func.sum(Ride.net_pay).label("revenue"),
            func.sum(Ride.net_pay - Ride.z_rate).label("profit"),
        )
        .join(Ride, Ride.person_id == Person.person_id)
        .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
        .filter(Ride.ride_start_ts >= text("now() - interval '30 days'"))
        .group_by(Person.full_name, PayrollBatch.company_name)
        .order_by(func.sum(Ride.net_pay - Ride.z_rate).desc())
        .all()
    )

    def to_dict(r) -> dict:
        rides = int(r.rides or 0)
        revenue = round(float(r.revenue or 0), 2)
        profit = round(float(r.profit or 0), 2)
        avg_revenue = round(revenue / rides, 2) if rides else 0.0
        avg_profit = round(profit / rides, 2) if rides else 0.0
        margin_pct = round(profit / revenue * 100, 1) if revenue else 0.0
        return {
            "name": r.name,
            "rides": rides,
            "revenue": revenue,
            "profit": profit,
            "avg_revenue": avg_revenue,
            "avg_profit": avg_profit,
            "margin_pct": margin_pct,
            "company": r.company,
        }

    all_drivers = [to_dict(r) for r in driver_rows]
    top_drivers = all_drivers[:10]
    bottom_drivers = all_drivers[-10:] if len(all_drivers) >= 10 else list(reversed(all_drivers))
    # bottom should be ordered worst first
    bottom_drivers = list(reversed(bottom_drivers))

    # Inactive drivers: Person with no rides in last 30 days, limit 15
    active_person_ids_subq = (
        db.query(Ride.person_id)
        .filter(Ride.ride_start_ts >= text("now() - interval '30 days'"))
        .distinct()
        .subquery()
    )

    last_ride_subq = (
        db.query(
            Ride.person_id,
            func.max(Ride.ride_start_ts).label("last_ride"),
        )
        .group_by(Ride.person_id)
        .subquery()
    )

    inactive_rows = (
        db.query(
            Person.full_name.label("name"),
            last_ride_subq.c.last_ride,
        )
        .outerjoin(last_ride_subq, last_ride_subq.c.person_id == Person.person_id)
        .filter(Person.person_id.notin_(
            db.query(active_person_ids_subq.c.person_id)
        ))
        .order_by(last_ride_subq.c.last_ride.desc().nullslast())
        .limit(15)
        .all()
    )

    def fmt_last_ride(ts) -> str:
        if ts is None:
            return "Never"
        if hasattr(ts, "strftime"):
            return ts.strftime("%-m/%-d/%Y")
        return str(ts)

    inactive_drivers = [
        {"name": r.name, "last_ride": fmt_last_ride(r.last_ride)}
        for r in inactive_rows
    ]

    return top_drivers, bottom_drivers, inactive_drivers


# ---------------------------------------------------------------------------
# Section 5 — Route Profitability
# ---------------------------------------------------------------------------

def _build_routes(db: Session, company: str | None = None) -> list[dict]:
    q = (
        db.query(
            Ride.service_name,
            func.count(Ride.ride_id).label("rides"),
            func.sum(Ride.net_pay).label("revenue"),
            func.sum(Ride.z_rate).label("cost"),
            func.sum(Ride.net_pay - Ride.z_rate).label("profit"),
        )
        .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
        .group_by(Ride.service_name)
        .order_by(func.sum(Ride.net_pay - Ride.z_rate).desc())
    )
    if company:
        q = q.filter(PayrollBatch.company_name == company)

    routes = []
    for r in q.all():
        rides = int(r.rides or 0)
        revenue = float(r.revenue or 0)
        cost = float(r.cost or 0)
        profit = float(r.profit or 0)
        margin_pct = round(profit / revenue * 100, 1) if revenue else 0.0
        avg_revenue = round(revenue / rides, 2) if rides else 0.0
        avg_profit = round(profit / rides, 2) if rides else 0.0
        routes.append({
            "service_name": r.service_name or "—",
            "rides": rides,
            "revenue": round(revenue, 2),
            "cost": round(cost, 2),
            "profit": round(profit, 2),
            "margin_pct": margin_pct,
            "avg_revenue": avg_revenue,
            "avg_profit": avg_profit,
        })
    return routes


# ---------------------------------------------------------------------------
# Snapshot mapping helpers
# ---------------------------------------------------------------------------

def _map_snapshot(raw: dict) -> dict:
    """Map _build_snapshot output keys to the intelligence data contract."""
    return {
        "revenue": raw.get("total_revenue", 0.0),
        "cost": raw.get("total_cost", 0.0),
        "profit": raw.get("total_profit", 0.0),
        "rides": raw.get("total_rides", 0),
        "active_drivers": raw.get("active_drivers", 0),
        "avg_profit": raw.get("avg_profit_per_ride", 0.0),
        "margin_pct": raw.get("margin_pct", 0.0),
    }


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

@router.get("/", name="intelligence_page")
def intelligence_page(
    request: Request,
    company: str | None = Query(None),
    db: Session = Depends(get_db),
):
    companies = _get_companies(db)

    # Section 1 — Company Snapshots
    raw_acumen = _build_snapshot(db, company="FirstAlt")
    raw_maz = _build_snapshot(db, company="EverDriven")
    snapshot_acumen = _map_snapshot(raw_acumen)
    snapshot_maz = _map_snapshot(raw_maz)

    # Section 2 — Alerts
    alerts = _build_alerts(db)

    # Section 3 — Trends
    trends, projection, comparison = _build_trends(db)

    # Section 4 — Driver Performance
    top_drivers, bottom_drivers, inactive_drivers = _build_driver_performance(db)

    # Section 5 — Route Profitability (per company)
    routes = _build_routes(db, company=company)
    routes_fa = _build_routes(db, company="FirstAlt")
    routes_ed = _build_routes(db, company="EverDriven")

    # Section 6 — Driver Reliability
    reliability = _build_reliability(db)

    return templates().TemplateResponse(
        request,
        "intelligence.html",
        {
            "companies": companies,
            "selected_company": company,
            # Section 1
            "snapshot_acumen": snapshot_acumen,
            "snapshot_maz": snapshot_maz,
            # Section 2
            "alerts": alerts,
            # Section 3
            "trends": trends,
            "projection": projection,
            "comparison": comparison,
            # Section 4
            "top_drivers": top_drivers,
            "bottom_drivers": bottom_drivers,
            "inactive_drivers": inactive_drivers,
            # Section 5
            "routes": routes,
            "routes_fa": routes_fa,
            "routes_ed": routes_ed,
            # Section 6
            "reliability": reliability,
        },
    )


@router.post("/generate-insights", name="intelligence_generate_insights")
async def generate_insights(
    request: Request,
    company: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return JSONResponse({"narrative": ""})
