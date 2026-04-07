"""
Dedicated JSON API endpoints for the Next.js frontend.
All routes under /api/data/* always return JSON.
No content negotiation needed.
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, Date

from backend.db import get_db
from backend.db.models import Person, Ride, PayrollBatch, DriverBalance, ActivityLog
from backend.routes.dashboard import _build_stats, _build_ytd_weeks
from backend.routes.summary import _build_summary
from backend.routes.analytics import _build_analytics
from backend.routes.pareto import _build_pareto
from backend.routes.insights import _build_snapshot as _insights_snapshot
from backend.routes.intelligence import (
    _build_alerts,
    _build_driver_performance,
    _map_snapshot,
)

router = APIRouter(prefix="/api/data", tags=["api-json"])


@router.get("/dashboard")
def api_dashboard(db: Session = Depends(get_db)):
    try:
        stats = _build_stats(db)
        ytd_weeks = _build_ytd_weeks(db, limit=8)
        weekly_data = []
        for item in ytd_weeks:
            weekly_data.append({
                "week": str(item.get("week_label") or item.get("week_start") or ""),
                "label": str(item.get("week_label") or item.get("label") or ""),
                "fa_revenue": float(item.get("fa_revenue", 0) or 0),
                "ed_revenue": float(item.get("ed_revenue", 0) or 0),
                "fa_rides": int(item.get("fa_rides", 0) or item.get("rides", 0) or 0),
                "ed_rides": int(item.get("ed_rides", 0) or 0),
                "profit": float(item.get("fa_profit", 0) or 0) + float(item.get("ed_profit", 0) or 0),
            })
        return JSONResponse({
            "revenue": float(stats.get("total_revenue", 0)),
            "cost": float(stats.get("total_cost", 0)),
            "profit": float(stats.get("total_profit", 0)),
            "rides": int(stats.get("total_rides", 0)),
            "margin": float(stats.get("total_margin_pct", 0)),
            "fa": {
                "revenue": float(stats.get("fa_revenue", 0)),
                "profit": float(stats.get("fa_profit", 0)),
                "rides": int(stats.get("fa_rides", 0)),
                "cost": float(stats.get("fa_cost", 0)),
            },
            "ed": {
                "revenue": float(stats.get("ed_revenue", 0)),
                "profit": float(stats.get("ed_profit", 0)),
                "rides": int(stats.get("ed_rides", 0)),
                "cost": float(stats.get("ed_cost", 0)),
            },
            "weekly_data": weekly_data,
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/people")
def api_people(db: Session = Depends(get_db)):
    try:
        ride_stats = (
            db.query(
                Ride.person_id,
                func.count(Ride.ride_id).label("ride_count"),
                func.max(Ride.ride_start_ts).label("last_active"),
            )
            .group_by(Ride.person_id)
            .subquery()
        )
        stats_map = {}
        for r in db.query(ride_stats).all():
            stats_map[r.person_id] = {
                "ride_count": int(r.ride_count or 0),
                "last_active": r.last_active,
            }

        rows = db.query(Person).order_by(Person.full_name.asc()).all()
        drivers = []
        for p in rows:
            st = stats_map.get(p.person_id, {})
            has_fa = bool(p.firstalt_driver_id)
            has_ed = bool(p.everdriven_driver_id)
            company_val = "Both" if (has_fa and has_ed) else ("FirstAlt" if has_fa else ("EverDriven" if has_ed else "Unknown"))
            last_active = st.get("last_active")
            drivers.append({
                "id": p.person_id,
                "name": p.full_name or "",
                "company": company_val,
                "fa_id": str(p.firstalt_driver_id) if p.firstalt_driver_id else None,
                "ed_id": str(p.everdriven_driver_id) if p.everdriven_driver_id else None,
                "phone": p.phone or "",
                "email": p.email or "",
                "pay_code": p.paycheck_code or "",
                "notes": p.notes or "",
                "rides": st.get("ride_count", 0),
                "last_active": last_active.isoformat() if last_active and hasattr(last_active, "isoformat") else None,
            })
        return JSONResponse(drivers)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/payroll-history")
def api_payroll_history(db: Session = Depends(get_db)):
    try:
        batches = db.query(PayrollBatch).order_by(PayrollBatch.uploaded_at.desc()).limit(100).all()
        result = []
        for b in batches:
            ride_count = db.query(func.count(Ride.ride_id)).filter(Ride.payroll_batch_id == b.payroll_batch_id).scalar() or 0
            result.append({
                "id": b.payroll_batch_id,
                "batch_ref": b.batch_ref or "",
                "source": b.source or "",
                "company": b.company_name or "",
                "period_start": b.period_start.isoformat() if b.period_start else None,
                "period_end": b.period_end.isoformat() if b.period_end else None,
                "uploaded_at": b.uploaded_at.isoformat() if b.uploaded_at else None,
                "notes": b.notes or "",
                "ride_count": ride_count,
            })
        return JSONResponse(result)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/payroll-history/{batch_id}")
def api_payroll_batch_detail(batch_id: int, db: Session = Depends(get_db)):
    try:
        b = db.query(PayrollBatch).filter(PayrollBatch.payroll_batch_id == batch_id).first()
        if not b:
            return JSONResponse({"error": "Not found"}, status_code=404)
        rides = db.query(Ride).filter(Ride.payroll_batch_id == batch_id).all()
        # Group by person
        from collections import defaultdict
        driver_map = defaultdict(lambda: {"rides": 0, "net_pay": 0.0, "cost": 0.0})
        person_names = {}
        for r in rides:
            driver_map[r.person_id]["rides"] += 1
            driver_map[r.person_id]["net_pay"] += float(r.net_pay or 0)
            driver_map[r.person_id]["cost"] += float(r.z_rate or 0)
            if r.person_id not in person_names:
                p = db.query(Person).filter(Person.person_id == r.person_id).first()
                person_names[r.person_id] = p.full_name if p else str(r.person_id)

        drivers = []
        for pid, d in driver_map.items():
            d["name"] = person_names.get(pid, str(pid))
            d["profit"] = round(d["net_pay"] - d["cost"], 2)
            d["net_pay"] = round(d["net_pay"], 2)
            d["cost"] = round(d["cost"], 2)
            drivers.append(d)
        drivers.sort(key=lambda x: x["name"])

        totals = {
            "rides": sum(d["rides"] for d in drivers),
            "net_pay": round(sum(d["net_pay"] for d in drivers), 2),
            "cost": round(sum(d["cost"] for d in drivers), 2),
            "profit": round(sum(d["profit"] for d in drivers), 2),
        }
        return JSONResponse({
            "batch": {
                "id": b.payroll_batch_id,
                "batch_ref": b.batch_ref or "",
                "source": b.source or "",
                "company": b.company_name or "",
                "period_start": b.period_start.isoformat() if b.period_start else None,
                "period_end": b.period_end.isoformat() if b.period_end else None,
                "uploaded_at": b.uploaded_at.isoformat() if b.uploaded_at else None,
            },
            "drivers": drivers,
            "totals": totals,
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Payroll Summary ───────────────────────────────────────────────────────────

@router.get("/summary")
def api_summary(
    company: str | None = Query(None),
    batch_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    try:
        companies = (
            db.query(PayrollBatch.company_name)
            .distinct()
            .order_by(PayrollBatch.company_name.asc())
            .all()
        )
        companies = [r[0] for r in companies]
        selected_company = company or (companies[0] if companies else None)

        batches = []
        if selected_company:
            batches = (
                db.query(PayrollBatch)
                .filter(PayrollBatch.company_name == selected_company)
                .order_by(PayrollBatch.period_start.desc())
                .all()
            )

        data = _build_summary(db, company=selected_company, batch_id=batch_id, auto_save=False)
        rows = data["rows"]
        totals = data["totals"]

        periods = [
            f"{b.period_start.strftime('%-m/%-d/%Y') if b.period_start else ''} - {b.period_end.strftime('%-m/%-d/%Y') if b.period_end else ''}"
            for b in batches
        ]

        drivers_out = []
        withheld_out = []
        for r in rows:
            entry = {
                "id": r["person_id"],
                "name": r["person"],
                "pay_code": r["code"],
                "days": r["days"],
                "net_pay": r["net_pay"],
                "carried_over": r["from_last_period"],
                "pay_this_period": r["pay_this_period"],
                "status": "withheld" if r["withheld"] else "paid",
                "override": False,
            }
            if r["withheld"]:
                withheld_out.append(entry)
            else:
                drivers_out.append(entry)

        total_withheld = sum(r["withheld_amount"] for r in rows if r["withheld"])
        return JSONResponse({
            "company": selected_company,
            "period": None,
            "periods": periods,
            "drivers": drivers_out,
            "withheld": withheld_out,
            "stats": {
                "driver_count": len(rows),
                "total_pay": totals["pay_this_period"],
                "withheld_amount": round(total_withheld, 2),
            },
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Analytics ─────────────────────────────────────────────────────────────────

@router.get("/analytics")
def api_analytics(db: Session = Depends(get_db)):
    try:
        data = _build_analytics(db)
        s = data["summary"]

        driver_profitability = []
        for d in data.get("driver_stats", []):
            cost = d.get("total_earnings", 0)
            profit = d.get("total_profit", 0)
            revenue = round(cost + profit, 2)
            driver_profitability.append({
                "driver": d.get("driver", ""),
                "rides": d.get("total_rides", 0),
                "revenue": revenue,
                "cost": cost,
                "profit": profit,
                "margin": d.get("profit_margin", 0),
            })

        route_profitability = [
            {
                "service": r.get("service_name", ""),
                "rides": r.get("total_rides", 0),
                "revenue": r.get("revenue", 0),
                "profit": r.get("profit", 0),
                "margin": r.get("margin_pct", 0),
            }
            for r in data.get("route_stats", [])
        ]

        def map_ride(r):
            return {
                "date": r.get("ride_date", ""),
                "driver": r.get("driver", ""),
                "service": r.get("service_name", ""),
                "net_pay": r.get("net_pay", 0),
                "profit": r.get("profit", 0),
            }

        period_map: dict = {}
        for p in data.get("period_rows", []):
            label = p.get("period_start", "")
            co = (p.get("company") or "").lower()
            if label not in period_map:
                period_map[label] = {"period": label, "fa_profit": 0.0, "ed_profit": 0.0, "total": 0.0}
            prof = float(p.get("profit", 0))
            if "first" in co or "fa" in co:
                period_map[label]["fa_profit"] = round(period_map[label]["fa_profit"] + prof, 2)
            else:
                period_map[label]["ed_profit"] = round(period_map[label]["ed_profit"] + prof, 2)
            period_map[label]["total"] = round(
                period_map[label]["fa_profit"] + period_map[label]["ed_profit"], 2
            )
        profit_by_period = list(period_map.values())

        return JSONResponse({
            "summary": {
                "revenue": s.get("total_revenue", 0),
                "driver_cost": s.get("total_cost", 0),
                "profit": s.get("total_profit", 0),
                "margin": s.get("margin_pct", 0),
                "rides": s.get("total_rides", 0),
                "avg_profit_per_ride": s.get("avg_profit_per_ride", 0),
            },
            "company_breakdown": [
                {
                    "company": r.get("company", ""),
                    "revenue": r.get("revenue", 0),
                    "cost": r.get("cost", 0),
                    "profit": r.get("profit", 0),
                    "rides": r.get("rides", 0),
                }
                for r in data.get("company_rows", [])
            ],
            "route_profitability": route_profitability,
            "top_rides": [map_ride(r) for r in data.get("top_rides", [])],
            "bottom_rides": [map_ride(r) for r in data.get("bottom_rides", [])],
            "driver_profitability": driver_profitability,
            "profit_by_period": profit_by_period,
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── YTD ───────────────────────────────────────────────────────────────────────

@router.get("/ytd")
def api_ytd(year: int | None = Query(None), db: Session = Depends(get_db)):
    try:
        if not year:
            year = date.today().year

        from sqlalchemy import extract

        base_batches = (
            db.query(PayrollBatch)
            .filter(
                PayrollBatch.finalized_at.isnot(None),
                extract("year", PayrollBatch.period_start) == year,
            )
            .all()
        )
        batch_ids = [b.payroll_batch_id for b in base_batches]

        if not batch_ids:
            return JSONResponse({"totals": {"fa": {}, "ed": {}}, "weeks": [], "drivers": []})

        co_rows = (
            db.query(
                PayrollBatch.company_name,
                func.count(Ride.ride_id).label("rides"),
                func.sum(Ride.net_pay).label("revenue"),
                func.sum(Ride.z_rate).label("cost"),
                func.sum(Ride.net_pay - Ride.z_rate).label("profit"),
            )
            .join(Ride, Ride.payroll_batch_id == PayrollBatch.payroll_batch_id)
            .filter(PayrollBatch.payroll_batch_id.in_(batch_ids))
            .group_by(PayrollBatch.company_name)
            .all()
        )
        fa_totals: dict = {}
        ed_totals: dict = {}
        for r in co_rows:
            co = (r.company_name or "").lower()
            d = {
                "revenue": round(float(r.revenue or 0), 2),
                "cost": round(float(r.cost or 0), 2),
                "profit": round(float(r.profit or 0), 2),
                "rides": int(r.rides or 0),
            }
            if "first" in co or "fa" in co:
                fa_totals = d
            else:
                ed_totals = d

        week_rows = (
            db.query(
                PayrollBatch.week_start,
                PayrollBatch.company_name,
                func.count(Ride.ride_id).label("rides"),
                func.sum(Ride.net_pay).label("revenue"),
                func.sum(Ride.net_pay - Ride.z_rate).label("profit"),
            )
            .join(Ride, Ride.payroll_batch_id == PayrollBatch.payroll_batch_id)
            .filter(PayrollBatch.payroll_batch_id.in_(batch_ids))
            .group_by(PayrollBatch.week_start, PayrollBatch.company_name)
            .order_by(PayrollBatch.week_start)
            .all()
        )
        weeks_dict: dict = {}
        for r in week_rows:
            k = r.week_start
            if k not in weeks_dict:
                weeks_dict[k] = {"week_start": k, "fa_revenue": 0.0, "fa_profit": 0.0, "ed_revenue": 0.0, "ed_profit": 0.0, "rides": 0}
            co = (r.company_name or "").lower()
            if "first" in co or "fa" in co:
                weeks_dict[k]["fa_revenue"] += float(r.revenue or 0)
                weeks_dict[k]["fa_profit"] += float(r.profit or 0)
            else:
                weeks_dict[k]["ed_revenue"] += float(r.revenue or 0)
                weeks_dict[k]["ed_profit"] += float(r.profit or 0)
            weeks_dict[k]["rides"] += int(r.rides or 0)

        cumulative = 0.0
        weeks_out = []
        for w in sorted(weeks_dict.values(), key=lambda x: x["week_start"] or date.min):
            cumulative += w["fa_profit"] + w["ed_profit"]
            ws = w["week_start"]
            weeks_out.append({
                "week": ws.isoformat() if ws and hasattr(ws, "isoformat") else str(ws) if ws else "",
                "fa_revenue": round(w["fa_revenue"], 2),
                "fa_profit": round(w["fa_profit"], 2),
                "ed_revenue": round(w["ed_revenue"], 2),
                "ed_profit": round(w["ed_profit"], 2),
                "rides": w["rides"],
                "cumulative_profit": round(cumulative, 2),
            })

        driver_rows = (
            db.query(
                Person.full_name,
                func.count(Ride.ride_id).label("rides"),
                func.sum(Ride.net_pay).label("revenue"),
                func.sum(Ride.z_rate).label("cost"),
                func.sum(Ride.net_pay - Ride.z_rate).label("profit"),
                func.count(func.distinct(PayrollBatch.payroll_batch_id)).label("weeks_active"),
            )
            .join(Ride, Ride.person_id == Person.person_id)
            .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
            .filter(PayrollBatch.payroll_batch_id.in_(batch_ids))
            .group_by(Person.person_id, Person.full_name)
            .order_by(func.sum(Ride.net_pay - Ride.z_rate).desc())
            .all()
        )
        drivers_out = [
            {
                "driver": r.full_name or "",
                "weeks_active": int(r.weeks_active or 0),
                "rides": int(r.rides or 0),
                "revenue": round(float(r.revenue or 0), 2),
                "cost": round(float(r.cost or 0), 2),
                "profit": round(float(r.profit or 0), 2),
            }
            for r in driver_rows
        ]

        return JSONResponse({
            "totals": {"fa": fa_totals, "ed": ed_totals},
            "weeks": weeks_out,
            "drivers": drivers_out,
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Insights ──────────────────────────────────────────────────────────────────

@router.get("/insights")
def api_insights(db: Session = Depends(get_db)):
    try:
        snap = _insights_snapshot(db)

        top_drivers = [
            {
                "driver": d.get("driver", ""),
                "rides": d.get("rides", 0),
                "profit": d.get("total_profit", 0),
                "margin": d.get("margin_pct", 0),
            }
            for d in snap.get("top_drivers", [])
        ]

        bottom_q = (
            db.query(
                Person.full_name.label("driver"),
                func.count(Ride.ride_id).label("rides"),
                func.sum(Ride.net_pay - Ride.z_rate).label("profit"),
            )
            .join(Ride, Ride.person_id == Person.person_id)
            .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
            .group_by(Person.person_id, Person.full_name)
            .order_by(func.sum(Ride.net_pay - Ride.z_rate).asc())
            .limit(5)
            .all()
        )
        bottom_drivers = [
            {"driver": r.driver or "", "rides": int(r.rides or 0), "profit": round(float(r.profit or 0), 2)}
            for r in bottom_q
        ]

        profitable_routes = [
            {"service": r.get("service", ""), "rides": r.get("ride_count", 0), "profit": r.get("profit", 0)}
            for r in snap.get("top_routes", [])
        ]
        unprofitable_routes = [
            {"service": r.get("service", ""), "rides": r.get("ride_count", 0), "profit": r.get("profit", 0)}
            for r in snap.get("bottom_routes", [])
        ]
        recent_periods = [
            {
                "period": f"{p.get('period_start', '')} – {p.get('period_end', '')}",
                "revenue": 0,
                "profit": p.get("profit", 0),
                "rides": p.get("rides", 0),
            }
            for p in snap.get("recent_periods", [])
        ]

        return JSONResponse({
            "summary": {
                "revenue": snap.get("total_revenue", 0),
                "cost": snap.get("total_cost", 0),
                "profit": snap.get("total_profit", 0),
                "margin": snap.get("margin_pct", 0),
                "rides": snap.get("total_rides", 0),
                "drivers": snap.get("active_drivers", 0),
                "avg_rate": snap.get("avg_profit_per_ride", 0),
            },
            "top_drivers": top_drivers,
            "bottom_drivers": bottom_drivers,
            "profitable_routes": profitable_routes,
            "unprofitable_routes": unprofitable_routes,
            "recent_periods": recent_periods,
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Intelligence ──────────────────────────────────────────────────────────────

@router.get("/intelligence")
def api_intelligence(db: Session = Depends(get_db)):
    try:
        raw_fa = _insights_snapshot(db, company="FirstAlt")
        raw_ed = _insights_snapshot(db, company="EverDriven")
        snap_fa = _map_snapshot(raw_fa)
        snap_ed = _map_snapshot(raw_ed)

        alerts_raw = _build_alerts(db)
        alerts_out = []
        for a in alerts_raw:
            sev = a.get("type", "info")
            title = "Issue Detected" if sev == "danger" else "Warning" if sev == "warning" else "Info"
            alerts_out.append({
                "type": sev,
                "severity": sev,
                "title": title,
                "message": a.get("message", ""),
            })

        top_drivers_raw, _, inactive_raw = _build_driver_performance(db)

        top_drivers_out = [
            {
                "driver": d.get("name", ""),
                "rides": d.get("rides", 0),
                "profit": d.get("profit", 0),
                "margin": d.get("margin_pct", 0),
            }
            for d in top_drivers_raw
        ]
        inactive_out = [
            {"driver": d.get("name", ""), "last_active": d.get("last_ride", ""), "rides": 0}
            for d in inactive_raw
        ]

        snapshots = [
            {
                "company": "FirstAlt",
                "revenue": snap_fa.get("revenue", 0),
                "cost": snap_fa.get("cost", 0),
                "profit": snap_fa.get("profit", 0),
                "margin": snap_fa.get("margin_pct", 0),
                "rides": snap_fa.get("rides", 0),
                "drivers": snap_fa.get("active_drivers", 0),
            },
            {
                "company": "EverDriven",
                "revenue": snap_ed.get("revenue", 0),
                "cost": snap_ed.get("cost", 0),
                "profit": snap_ed.get("profit", 0),
                "margin": snap_ed.get("margin_pct", 0),
                "rides": snap_ed.get("rides", 0),
                "drivers": snap_ed.get("active_drivers", 0),
            },
        ]

        return JSONResponse({
            "snapshots": snapshots,
            "alerts": alerts_out,
            "top_drivers": top_drivers_out,
            "inactive_drivers": inactive_out,
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Pareto ────────────────────────────────────────────────────────────────────

@router.get("/pareto")
def api_pareto(db: Session = Depends(get_db)):
    try:
        data = _build_pareto(db)

        drivers = [
            {
                "rank": r.get("rank", i + 1),
                "driver": r.get("driver", ""),
                "rides": r.get("rides", 0),
                "profit": r.get("profit", 0),
                "share": r.get("individual_pct", 0),
                "cumulative": r.get("cumulative_pct", 0),
            }
            for i, r in enumerate(data.get("driver_rows", []))
        ]
        least_profitable = [
            {"driver": r.get("driver", ""), "rides": r.get("rides", 0), "profit": r.get("profit", 0)}
            for r in data.get("least_profitable_rows", [])
        ]
        services_by_volume = [
            {"service": r.get("service", ""), "rides": r.get("ride_count", 0), "revenue": 0}
            for r in data.get("service_by_volume", [])
        ]
        services_by_profit = [
            {"service": r.get("service", ""), "profit": r.get("profit", 0), "margin": 0}
            for r in data.get("service_by_profit", [])
        ]
        periods = [
            {
                "period": f"{r.get('period_start', '')} – {r.get('period_end', '')}",
                "rides": r.get("rides", 0),
                "profit": r.get("profit", 0),
            }
            for r in data.get("period_rows", [])
        ]

        return JSONResponse({
            "drivers": drivers,
            "least_profitable": least_profitable,
            "services_by_volume": services_by_volume,
            "services_by_profit": services_by_profit,
            "periods": periods,
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Reconciliation ────────────────────────────────────────────────────────────

@router.get("/reconciliation")
def api_reconciliation(db: Session = Depends(get_db)):
    try:
        rows = (
            db.query(
                PayrollBatch.source,
                PayrollBatch.company_name,
                PayrollBatch.week_start,
                func.sum(Ride.net_pay).label("total_revenue"),
                func.sum(Ride.z_rate).label("total_cost"),
                func.sum(Ride.net_pay - Ride.z_rate).label("total_profit"),
                func.count(Ride.ride_id).label("ride_count"),
            )
            .outerjoin(Ride, Ride.payroll_batch_id == PayrollBatch.payroll_batch_id)
            .group_by(
                PayrollBatch.payroll_batch_id,
                PayrollBatch.source,
                PayrollBatch.company_name,
                PayrollBatch.week_start,
            )
            .order_by(PayrollBatch.week_start.desc().nullslast())
            .all()
        )

        batches = []
        healthy = 0
        needs_review = 0
        largest_issue = 0.0

        def fmt_week(d):
            return d.strftime("%-m/%-d/%Y") if d and hasattr(d, "strftime") else str(d) if d else "—"

        for row in rows:
            revenue = float(row.total_revenue or 0)
            cost = float(row.total_cost or 0)
            profit = float(row.total_profit or 0)
            has_zero_rates = cost == 0 and row.ride_count > 0
            is_ok = not has_zero_rates and profit >= 0

            if is_ok:
                healthy += 1
                status = "ok"
            else:
                needs_review += 1
                status = "loss" if profit < 0 else "warning"
                abs_diff = abs(profit)
                if abs_diff > largest_issue:
                    largest_issue = abs_diff

            batches.append({
                "week": fmt_week(row.week_start),
                "source": row.source or "",
                "company": row.company_name or "",
                "rides": int(row.ride_count or 0),
                "revenue": round(revenue, 2),
                "cost": round(cost, 2),
                "profit": round(profit, 2),
                "status": status,
            })

        return JSONResponse({
            "stats": {
                "total": len(batches),
                "healthy": healthy,
                "needs_review": needs_review,
                "largest_issue": round(largest_issue, 2),
            },
            "batches": batches,
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Validate ──────────────────────────────────────────────────────────────────

@router.get("/validate")
def api_validate():
    # File-based validation reads local upload directories not present on Railway.
    return JSONResponse({
        "source": "acumen",
        "stats": {"partner_net_pay": 0, "calc_driver_pay": 0, "stored_driver_pay": 0, "variance": 0},
        "weeks": [],
    })


# ── Activity ──────────────────────────────────────────────────────────────────

@router.get("/activity")
def api_activity(db: Session = Depends(get_db)):
    try:
        logs = (
            db.query(ActivityLog)
            .order_by(ActivityLog.created_at.desc())
            .limit(200)
            .all()
        )
        entries = []
        for log in logs:
            ts = log.created_at
            entries.append({
                "id": log.id,
                "user": log.username or "",
                "action": log.action or "",
                "entity_type": log.entity_type or "",
                "description": log.description or "",
                "timestamp": ts.isoformat() if ts and hasattr(ts, "isoformat") else None,
                "entity_id": log.entity_id,
            })
        return JSONResponse(entries)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
