"""
Dedicated JSON API endpoints for the Next.js frontend.
All routes under /api/data/* always return JSON.
No content negotiation needed.
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.db import get_db
from backend.db.models import Person, Ride, PayrollBatch, DriverBalance

# Import the existing builder functions to avoid code duplication
from backend.routes.dashboard import _build_stats, _build_ytd_weeks
from backend.routes.summary import _build_summary

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
