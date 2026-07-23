"""
Dedicated JSON API endpoints for the Next.js frontend.
All routes under /api/data/* always return JSON.
No content negotiation needed.
"""

import os
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, Date, extract

from backend.db import get_db
from backend.db.models import AuditLog, Person, Ride, PayrollBatch, DriverBalance, ActivityLog, BatchCorrectionLog
from backend.utils.roles import require_role
from backend.routes.dispatch_manage import (
    _scorecard_to_dict,
    _current_pt_week_start,
    _parse_iso_week,
)
from backend.services.driver_scorecard import (
    compute_driver_scorecard,
    AXIS_LABELS,
    AXIS_WEIGHTS,
)
from backend.routes.dashboard import _build_stats, _build_ytd_weeks
from backend.routes.summary import _build_summary
from backend.routes.rides import _build_rides_rows
from backend.services import everdriven_service
from backend.services.everdriven_service import EverDrivenAuthError

router = APIRouter(prefix="/api/data", tags=["api-json"])


def _display_company(raw: str) -> str:
    """Map raw DB company name to display name."""
    co = (raw or "").lower()
    if "ever" in co or "maz" in co:
        return "EverDriven"
    return "FirstAlt"


@router.get("/dashboard")
def api_dashboard(view: str = Query("weekly"), db: Session = Depends(get_db)):
    try:
        from sqlalchemy import extract
        stats = _build_stats(db)

        year = date.today().year
        MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

        if view == "monthly":
            # Group by year-month across all years with data
            month_rows = (
                db.query(
                    extract("year", PayrollBatch.week_start).label("yr"),
                    extract("month", PayrollBatch.week_start).label("mo"),
                    PayrollBatch.source,
                    func.sum(Ride.net_pay).label("revenue"),
                    func.sum(Ride.net_pay - Ride.z_rate).label("profit"),
                    func.count(Ride.ride_id).label("rides"),
                )
                .join(Ride, Ride.payroll_batch_id == PayrollBatch.payroll_batch_id)
                .group_by("yr", "mo", PayrollBatch.source)
                .order_by("yr", "mo")
                .all()
            )
            months_map: dict = {}
            for r in month_rows:
                k = (int(r.yr), int(r.mo))
                if k not in months_map:
                    months_map[k] = {"yr": int(r.yr), "mo": int(r.mo),
                                     "fa_revenue": 0.0, "fa_profit": 0.0,
                                     "ed_revenue": 0.0, "ed_profit": 0.0,
                                     "fa_rides": 0, "ed_rides": 0}
                is_fa = r.source != "maz"
                if is_fa:
                    months_map[k]["fa_revenue"] += float(r.revenue or 0)
                    months_map[k]["fa_profit"] += float(r.profit or 0)
                    months_map[k]["fa_rides"] += int(r.rides or 0)
                else:
                    months_map[k]["ed_revenue"] += float(r.revenue or 0)
                    months_map[k]["ed_profit"] += float(r.profit or 0)
                    months_map[k]["ed_rides"] += int(r.rides or 0)

            sorted_months = sorted(months_map.values(), key=lambda x: (x["yr"], x["mo"]))[-12:]
            weekly_data = []
            for m in sorted_months:
                label = f"{MONTHS[m['mo'] - 1]} {m['yr']}"
                weekly_data.append({
                    "week": label,
                    "label": label,
                    "fa_revenue": round(m["fa_revenue"], 2),
                    "ed_revenue": round(m["ed_revenue"], 2),
                    "fa_rides": m["fa_rides"],
                    "ed_rides": m["ed_rides"],
                    "profit": round(m["fa_profit"] + m["ed_profit"], 2),
                })
        else:
            # Weekly view — last 8 weeks of current year
            week_rows = (
                db.query(
                    PayrollBatch.week_start,
                    PayrollBatch.source,
                    func.sum(Ride.net_pay).label("revenue"),
                    func.sum(Ride.net_pay - Ride.z_rate).label("profit"),
                    func.count(Ride.ride_id).label("rides"),
                )
                .join(Ride, Ride.payroll_batch_id == PayrollBatch.payroll_batch_id)
                .filter(extract("year", PayrollBatch.week_start) == year)
                .group_by(PayrollBatch.week_start, PayrollBatch.source)
                .order_by(PayrollBatch.week_start.desc())
                .limit(16)
                .all()
            )
            weeks_map: dict = {}
            for r in week_rows:
                k = r.week_start
                if k not in weeks_map:
                    weeks_map[k] = {"week_start": k, "fa_revenue": 0.0, "fa_profit": 0.0,
                                     "ed_revenue": 0.0, "ed_profit": 0.0,
                                     "fa_rides": 0, "ed_rides": 0}
                is_fa = r.source != "maz"
                if is_fa:
                    weeks_map[k]["fa_revenue"] += float(r.revenue or 0)
                    weeks_map[k]["fa_profit"] += float(r.profit or 0)
                    weeks_map[k]["fa_rides"] += int(r.rides or 0)
                else:
                    weeks_map[k]["ed_revenue"] += float(r.revenue or 0)
                    weeks_map[k]["ed_profit"] += float(r.profit or 0)
                    weeks_map[k]["ed_rides"] += int(r.rides or 0)

            sorted_weeks = sorted(weeks_map.values(), key=lambda x: x["week_start"] or date.min)[-8:]
            weekly_data = []
            for i, w in enumerate(sorted_weeks, 1):
                ws = w["week_start"]
                label = ws.strftime("%-m/%-d") if ws and hasattr(ws, "strftime") else f"W{i}"
                weekly_data.append({
                    "week": label,
                    "label": label,
                    "fa_revenue": round(w["fa_revenue"], 2),
                    "ed_revenue": round(w["ed_revenue"], 2),
                    "fa_rides": w["fa_rides"],
                    "ed_rides": w["ed_rides"],
                    "profit": round(w["fa_profit"] + w["ed_profit"], 2),
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
                "home_address": p.home_address or "",
                "vehicle_make": p.vehicle_make or "",
                "vehicle_model": p.vehicle_model or "",
                "vehicle_year": p.vehicle_year,
                "vehicle_plate": p.vehicle_plate or "",
                "vehicle_color": p.vehicle_color or "",
                "active": p.active if p.active is not None else True,
                "language": p.language or None,
                "sex": p.sex or None,
            })
        return JSONResponse(drivers)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.post("/people/create")
async def api_create_person(request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    name = body.get("full_name", "").strip()
    if not name:
        return JSONResponse({"error": "full_name is required"}, status_code=400)
    person = Person(
        full_name=name,
        email=body.get("email", "").strip() or None,
        phone=body.get("phone", "").strip() or None,
        paycheck_code=body.get("paycheck_code", "").strip() or None,
        notes=body.get("notes", "").strip() or None,
        home_address=body.get("home_address", "").strip() or None,
        firstalt_driver_id=int(body["firstalt_driver_id"]) if body.get("firstalt_driver_id") else None,
        everdriven_driver_id=int(body["everdriven_driver_id"]) if body.get("everdriven_driver_id") else None,
        vehicle_make=body.get("vehicle_make", "").strip() or None,
        vehicle_model=body.get("vehicle_model", "").strip() or None,
        vehicle_year=int(body["vehicle_year"]) if body.get("vehicle_year") and str(body["vehicle_year"]).strip().isdigit() else None,
        vehicle_plate=body.get("vehicle_plate", "").strip() or None,
        vehicle_color=body.get("vehicle_color", "").strip() or None,
        active=True,
    )
    db.add(person)
    db.commit()
    db.refresh(person)
    return JSONResponse({"ok": True, "person_id": person.person_id, "name": person.full_name, "active": True}, status_code=201)


@router.patch("/people/{person_id}/language")
async def api_patch_person_language(
    person_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Set preferred language for automated calls/SMS on a driver."""
    from fastapi import HTTPException
    body = await request.json()
    lang = (body.get("language") or "").strip().lower()
    if lang not in ("en", "ar", "am", ""):
        raise HTTPException(status_code=400, detail="language must be 'en', 'ar', or 'am'")

    person = db.query(Person).filter(Person.person_id == person_id).first()
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    person.language = lang or None
    db.commit()
    return JSONResponse({
        "ok": True,
        "person_id": person.person_id,
        "name": person.full_name,
        "language": person.language,
    })


@router.patch("/people/{person_id}/home")
async def api_patch_person_home(
    person_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Set a driver's home area/zip — S5 assignment scoring seam (proximity tie-break)."""
    from fastapi import HTTPException
    HOME_AREA_MAX, HOME_ZIP_MAX = 120, 20
    body = await request.json()
    home_area = (body.get("home_area") or "").strip() or None
    home_zip = (body.get("home_zip") or "").strip() or None
    if home_area and len(home_area) > HOME_AREA_MAX:
        raise HTTPException(status_code=400, detail=f"home_area max {HOME_AREA_MAX} chars")
    if home_zip and len(home_zip) > HOME_ZIP_MAX:
        raise HTTPException(status_code=400, detail=f"home_zip max {HOME_ZIP_MAX} chars")

    person = db.query(Person).filter(Person.person_id == person_id).first()
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    person.home_area = home_area
    person.home_zip = home_zip
    db.commit()
    return JSONResponse({"ok": True})


@router.get("/tts/{cache_key}")
def api_tts_audio(cache_key: str):
    """
    Serve cached ElevenLabs TTS audio bytes as MP3.
    Twilio fetches this URL during a call to play the driver notification audio.
    """
    from fastapi.responses import Response
    from backend.services.notification_service import get_cached_tts_audio
    audio = get_cached_tts_audio(cache_key)
    if not audio:
        return JSONResponse({"error": "Audio not found or expired"}, status_code=404)
    return Response(content=audio, media_type="audio/mpeg")


@router.get("/payroll-history")
def api_payroll_history(db: Session = Depends(get_db)):
    try:
        batches = (
            db.query(PayrollBatch)
            .filter(PayrollBatch.status != "archived")
            .order_by(PayrollBatch.week_start.desc().nullslast())
            .limit(100)
            .all()
        )

        batch_ids = [b.payroll_batch_id for b in batches]

        # Aggregate financials per batch in one query.
        # partner_paid semantics differ by import era:
        #   - W14 and earlier:        gross_pay >= net_pay  (partner pays in gross_pay)
        #   - W15 FA passthrough fmt: net_pay   >  gross_pay (partner pays in net_pay)
        #   - ED (maz):               gross_pay  > net_pay   (partner pays in gross_pay)
        # GREATEST handles all three eras: partner_paid is always the larger of
        # gross_pay/net_pay since the partner pays >= the driver gets per ride.
        from sqlalchemy import func as _f
        agg_rows = (
            db.query(
                Ride.payroll_batch_id,
                func.count(Ride.ride_id).label("rides"),
                func.sum(Ride.gross_pay).label("gross_paid"),
                func.sum(_f.greatest(Ride.gross_pay, Ride.net_pay)).label("partner_paid"),
                func.sum(Ride.z_rate).label("driver_cost"),
            )
            .filter(Ride.payroll_batch_id.in_(batch_ids))
            .group_by(Ride.payroll_batch_id)
            .all()
        )
        agg = {r.payroll_batch_id: r for r in agg_rows}

        # Withheld amounts per batch from driver_balance
        from backend.db.models import DriverBalance
        withheld_rows = (
            db.query(
                DriverBalance.payroll_batch_id,
                func.sum(DriverBalance.carried_over).label("withheld_total"),
            )
            .filter(DriverBalance.payroll_batch_id.in_(batch_ids))
            .group_by(DriverBalance.payroll_batch_id)
            .all()
        )
        withheld_map = {r.payroll_batch_id: float(r.withheld_total or 0) for r in withheld_rows}

        # Group batches by week_start so FA+ED for same week are combined
        from collections import OrderedDict
        from backend.utils.week_label import week_label as _wl, canonical_week_label as _cwl
        weeks: dict = OrderedDict()
        for b in batches:
            ws = b.week_start or b.period_start
            week_key = ws.isoformat() if ws else b.batch_ref or str(b.payroll_batch_id)

            a = agg.get(b.payroll_batch_id)
            rides = int(a.rides) if a else 0
            gross_paid = float(a.gross_paid or 0) if a else 0.0
            partner_paid = float(a.partner_paid or 0) if a else 0.0
            driver_cost = float(a.driver_cost or 0) if a else 0.0
            # Reconstruction imports (e.g. W14) set partner_gross_total because
            # per-ride partner billing was not recoverable.  Use it when present
            # so history shows real margin instead of $0.
            if b.partner_gross_total is not None:
                partner_paid = float(b.partner_gross_total)

            if week_key not in weeks:
                # Format period string from week_start
                if b.period_start and b.period_end:
                    period = f"{b.period_start.strftime('%-m/%-d')} – {b.period_end.strftime('%-m/%-d/%y')}"
                elif b.period_start:
                    period = b.period_start.strftime("%-m/%-d/%y")
                else:
                    period = b.batch_ref or ""

                weeks[week_key] = {
                    "id": b.payroll_batch_id,
                    "batch_ids": [],
                    "batch_ref": b.batch_ref or "",
                    "companies": [],
                    "status": getattr(b, 'status', None) or ("Final" if b.finalized_at else "Uploaded"),
                    "week_label": _cwl(b.period_start, b.batch_ref),
                    "period": period,
                    "week_start": ws.isoformat() if ws else None,
                    "uploaded": b.uploaded_at.isoformat() if b.uploaded_at else None,
                    "rides": 0,
                    "gross_paid": 0.0,
                    "partner_paid": 0.0,
                    "driver_cost": 0.0,
                    "profit": 0.0,
                    "withheld": 0.0,
                    "driver_payout": 0.0,
                }

            w = weeks[week_key]
            w["batch_ids"].append(b.payroll_batch_id)
            co = _display_company(b.company_name or "")
            if co not in w["companies"]:
                w["companies"].append(co)
            withheld = withheld_map.get(b.payroll_batch_id, 0.0)
            w["rides"] += rides
            w["gross_paid"] = round(w["gross_paid"] + gross_paid, 2)
            w["partner_paid"] = round(w["partner_paid"] + partner_paid, 2)
            w["driver_cost"] = round(w["driver_cost"] + driver_cost, 2)
            w["profit"] = round(w["partner_paid"] - w["driver_cost"], 2)
            w["withheld"] = round(w["withheld"] + withheld, 2)
            w["driver_payout"] = round(w["driver_cost"] - withheld, 2)

        result = []
        for w in weeks.values():
            w["company"] = " + ".join(w["companies"]) if len(w["companies"]) > 1 else (w["companies"][0] if w["companies"] else "")
            del w["companies"]
            del w["batch_ids"]
            result.append(w)

        return JSONResponse(result)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


def _batch_week_num(db: Session, b: PayrollBatch) -> int:
    """Canonical payroll week number for this batch."""
    from backend.utils.week_label import canonical_week_num as _cwn
    return _cwn(b.period_start, b.batch_ref) or 1


@router.get("/payroll-history/{batch_id}")
def api_payroll_batch_detail(batch_id: int, db: Session = Depends(get_db)):
    try:
        b = db.query(PayrollBatch).filter(PayrollBatch.payroll_batch_id == batch_id).first()
        if not b:
            return JSONResponse({"error": "Not found"}, status_code=404)
        # Exclude soft-deleted rides from batch-level payout aggregation.
        # Revenue rows (gross_pay / net_pay) are preserved on the ride; only
        # z_rate (driver payout) must be zeroed out for removed rides.
        rides = (
            db.query(Ride)
            .filter(Ride.payroll_batch_id == batch_id, Ride.removed_at.is_(None))
            .all()
        )
        # Group by person
        from collections import defaultdict
        driver_map = defaultdict(lambda: {"rides": 0, "gross": 0.0, "net_pay": 0.0, "cost": 0.0})
        person_names = {}
        for r in rides:
            driver_map[r.person_id]["rides"] += 1
            driver_map[r.person_id]["gross"] += float(r.gross_pay or 0)
            driver_map[r.person_id]["net_pay"] += float(r.net_pay or 0)
            driver_map[r.person_id]["cost"] += float(r.z_rate or 0)
            if r.person_id not in person_names:
                p = db.query(Person).filter(Person.person_id == r.person_id).first()
                person_names[r.person_id] = p.full_name if p else str(r.person_id)

        drivers = []
        for pid, d in driver_map.items():
            d["id"] = pid
            d["name"] = person_names.get(pid, str(pid))
            d["profit"] = round(d["net_pay"] - d["cost"] - (d["gross"] - d["net_pay"]), 2)
            d["net_pay"] = round(d["net_pay"], 2)
            d["cost"] = round(d["cost"], 2)
            del d["gross"]
            drivers.append(d)
        drivers.sort(key=lambda x: x["name"])

        totals = {
            "rides": sum(d["rides"] for d in drivers),
            "net_pay": round(sum(d["net_pay"] for d in drivers), 2),
            "cost": round(sum(d["cost"] for d in drivers), 2),
            "profit": round(sum(d["profit"] for d in drivers), 2),
        }

        # Build withheld list: drivers with rides in this batch + driver_balance record with carried_over > 0
        withheld = []
        withheld_balances = (
            db.query(DriverBalance)
            .filter(DriverBalance.payroll_batch_id == batch_id, DriverBalance.carried_over > 0)
            .all()
        )
        for db_row in withheld_balances:
            if db_row.person_id in driver_map:
                d = driver_map[db_row.person_id]
                withheld.append({
                    "id": db_row.person_id,
                    "name": person_names.get(db_row.person_id, str(db_row.person_id)),
                    "rides": d["rides"],
                    "net_pay": round(d["net_pay"], 2),
                    "cost": round(d["cost"], 2),
                    "carried_over": round(float(db_row.carried_over), 2),
                })
        withheld.sort(key=lambda x: x["name"])

        return JSONResponse({
            "batch": {
                "id": b.payroll_batch_id,
                "batch_ref": b.batch_ref or "",
                "source": b.source or "",
                "company": _display_company(b.company_name or ""),
                "week_label": f"Week {_batch_week_num(db, b)}",
                "period_start": b.period_start.isoformat() if b.period_start else None,
                "period_end": b.period_end.isoformat() if b.period_end else None,
                "uploaded_at": b.uploaded_at.isoformat() if b.uploaded_at else None,
            },
            "drivers": drivers,
            "totals": totals,
            "withheld": withheld,
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/payroll-history/{batch_id}/driver/{person_id}")
def api_driver_paystub(batch_id: int, person_id: int, db: Session = Depends(get_db)):
    """Ride-level pay stub for a specific driver in a specific batch."""
    try:
        b = db.query(PayrollBatch).filter(PayrollBatch.payroll_batch_id == batch_id).first()
        if not b:
            return JSONResponse({"error": "Batch not found"}, status_code=404)

        person = db.query(Person).filter(Person.person_id == person_id).first()
        if not person:
            return JSONResponse({"error": "Driver not found"}, status_code=404)

        # Fetch ALL rides (active + removed) so the UI can render removed rows
        # with a strikethrough audit trail — but server-side totals only count
        # active rides (removed_at IS NULL). Client must NOT recompute totals.
        rides = (
            db.query(Ride)
            .filter(Ride.payroll_batch_id == batch_id, Ride.person_id == person_id)
            .order_by(Ride.ride_start_ts.asc())
            .all()
        )

        ride_list = []
        for r in rides:
            ride_list.append({
                "ride_id": r.ride_id,
                "date": r.ride_start_ts.strftime("%m/%d/%Y") if r.ride_start_ts else None,
                "service_name": r.service_name or "—",
                "miles": float(r.miles or 0),
                "net_pay": float(r.net_pay or 0),
                "z_rate": float(r.z_rate or 0),
                "z_rate_source": r.z_rate_source or "service_default",
                "deduction": float(r.deduction or 0),
                "gross_pay": float(r.gross_pay or 0),
                "margin": round(float(r.net_pay or 0) - float(r.z_rate or 0), 2),
                # Soft-delete fields — None means active; non-None means removed from payout
                "removed_at": r.removed_at.isoformat() if r.removed_at else None,
                "removed_by": r.removed_by,
                "removed_reason": r.removed_reason,
            })

        # Totals exclude removed rides — server-truth must be correct.
        active_rides = [r for r in ride_list if r["removed_at"] is None]
        total_net = round(sum(r["net_pay"] for r in active_rides), 2)
        total_z_rate = round(sum(r["z_rate"] for r in active_rides), 2)
        total_deduction = round(sum(r["deduction"] for r in active_rides), 2)
        total_miles = round(sum(r["miles"] for r in active_rides), 1)

        return JSONResponse({
            "driver": {
                "id": person.person_id,
                "name": person.full_name,
                "email": person.email,
                "phone": person.phone,
                "pay_code": person.paycheck_code,
            },
            "batch": {
                "id": b.payroll_batch_id,
                "company": _display_company(b.company_name or ""),
                "source": b.source,
                "period_start": b.period_start.isoformat() if b.period_start else None,
                "period_end": b.period_end.isoformat() if b.period_end else None,
                "batch_ref": b.batch_ref,
            },
            "rides": ride_list,
            "totals": {
                "rides": len(active_rides),
                "miles": total_miles,
                "net_pay": total_net,
                "z_rate": total_z_rate,
                "deduction": total_deduction,
                "margin": round(total_net - total_z_rate, 2),
            },
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Payroll Summary ───────────────────────────────────────────────────────────

@router.get("/summary")
def api_summary(
    company: str | None = Query(None),  # "fa", "ed", or "all"
    batch_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    try:
        # Map frontend company param to DB source
        source_filter: str | None = None
        display_label = "All"
        if company == "fa":
            source_filter = "acumen"
            display_label = "FirstAlt"
        elif company == "ed":
            source_filter = "maz"
            display_label = "EverDriven"

        # Get batches for period list display
        batch_q = db.query(PayrollBatch).filter(PayrollBatch.payroll_batch_id > 0)
        if source_filter:
            batch_q = batch_q.filter(PayrollBatch.source == source_filter)
        batches = batch_q.order_by(PayrollBatch.period_start.desc()).limit(20).all()

        # When no explicit batch_id is given, _build_summary tries to find the latest
        # open (finalized_at IS NULL) batch. If all batches are finalized (e.g. after an
        # emergency restore), it returns empty rows with no_active_batch=True. In that
        # case fall back to the most recent batch regardless of finalized state so the
        # payroll page always shows real data instead of an empty state.
        resolved_batch_id = batch_id
        if not resolved_batch_id and batches:
            from backend.routes.summary import _resolve_latest_open_batch
            open_bid = _resolve_latest_open_batch(db, source=source_filter)
            resolved_batch_id = open_bid or batches[0].payroll_batch_id

        data = _build_summary(db, source=source_filter, batch_id=resolved_batch_id, auto_save=False)
        rows = data["rows"]
        totals = data["totals"]

        periods = [
            {
                "label": f"{b.period_start.strftime('%-m/%-d/%Y') if b.period_start else ''} – {b.period_end.strftime('%-m/%-d/%Y') if b.period_end else ''}",
                "batch_id": b.payroll_batch_id,
            }
            for b in batches if b.period_start
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

        # Include batch ID: selected one if filtering, otherwise most recent
        batch_info = batch_id if batch_id else (batches[0].payroll_batch_id if batches else None)

        # Derive week label from the most recent batch
        wl = None
        if batches:
            from backend.utils.week_label import canonical_week_label as _cwl
            wl = _cwl(batches[0].period_start, batches[0].batch_ref) or None

        return JSONResponse({
            "company": display_label,
            "period": None,
            "periods": periods,
            "batch_id": batch_info,
            "week_label": wl,
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


@router.get("/summary/overview")
def api_summary_overview(
    week: str | None = Query(None),   # "latest" or ignored; future: week number
    batch_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    """
    Returns FA + ED latest batch summaries side by side.
    Default: most-recent batch of each source (finalized or open).
    ?batch_id=X: use that specific batch (applies to whichever source it belongs to).
    """
    try:
        from backend.routes.summary import _build_summary as _bs, _batch_period_label, _build_week_rank_map

        def _latest_batch(source: str) -> PayrollBatch | None:
            return (
                db.query(PayrollBatch)
                .filter(PayrollBatch.source == source)
                .order_by(PayrollBatch.period_end.desc().nullslast(), PayrollBatch.uploaded_at.desc())
                .first()
            )

        def _batch_drivers(bid: int, source: str) -> dict:
            data = _bs(db, source=source, batch_id=bid, auto_save=False)
            batch_obj = db.query(PayrollBatch).filter(PayrollBatch.payroll_batch_id == bid).first()
            rows_raw = data.get("rows", [])
            totals = data.get("totals", {})
            drivers_out = []
            for r in rows_raw:
                drivers_out.append({
                    "person_id": r["person_id"],
                    "name": r["person"],
                    "paycheck_code": r["code"] or "",
                    "rides": r["rides"],
                    "gross": round(r["driver_pay"], 2),       # z_rate sum — driver earned
                    "partner_net": round(r["net_pay"], 2),    # net_pay — partner paid Maz
                    "carried_over": round(r["from_last_period"], 2),
                    "pay_this_period": round(r["pay_this_period"], 2),
                    "withheld": r["withheld"],
                    "withheld_amount": round(r["withheld_amount"], 2),
                })
            all_batches = db.query(PayrollBatch).filter(PayrollBatch.source == source).order_by(PayrollBatch.period_start.desc()).all()
            rank_map = _build_week_rank_map(all_batches)
            period_label = _batch_period_label(batch_obj, rank_map.get(bid)) if batch_obj else None
            return {
                "batch_id": bid,
                "period": period_label,
                "status": batch_obj.status if batch_obj else None,
                "week_start": batch_obj.period_start.isoformat() if batch_obj and batch_obj.period_start else None,
                "week_end": batch_obj.period_end.isoformat() if batch_obj and batch_obj.period_end else None,
                "drivers": drivers_out,
                "totals": {
                    "rides": totals.get("rides", 0),
                    "gross": round(totals.get("driver_pay", 0), 2),
                    "partner_net": round(totals.get("partner_pays", 0), 2),
                    "payout": round(totals.get("pay_this_period", 0), 2),
                    "withheld": round(totals.get("carried_over", 0), 2),
                    "margin": round(totals.get("partner_pays", 0) - totals.get("driver_pay", 0), 2),
                },
            }

        # Resolve FA batch
        if batch_id:
            fa_batch = db.query(PayrollBatch).filter(PayrollBatch.payroll_batch_id == batch_id).first()
            fa_bid = batch_id if (fa_batch and fa_batch.source == "acumen") else None
            ed_bid_batch = _latest_batch("maz")
            ed_bid = ed_bid_batch.payroll_batch_id if ed_bid_batch else None
            if fa_bid is None:
                ed_bid = batch_id if (fa_batch and fa_batch.source == "maz") else ed_bid
                fa_bid_batch = _latest_batch("acumen")
                fa_bid = fa_bid_batch.payroll_batch_id if fa_bid_batch else None
        else:
            fa_bid_batch = _latest_batch("acumen")
            fa_bid = fa_bid_batch.payroll_batch_id if fa_bid_batch else None
            ed_bid_batch = _latest_batch("maz")
            ed_bid = ed_bid_batch.payroll_batch_id if ed_bid_batch else None

        fa_data = _batch_drivers(fa_bid, "acumen") if fa_bid else None
        ed_data = _batch_drivers(ed_bid, "maz") if ed_bid else None

        return JSONResponse({
            "fa": fa_data,
            "ed": ed_data,
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
            .join(Ride, Ride.payroll_batch_id == PayrollBatch.payroll_batch_id)
            .filter(extract("year", PayrollBatch.period_start) == year)
            .distinct()
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
            if "ever" not in co:
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
            if "ever" not in co:
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


# ── Reconciliation ────────────────────────────────────────────────────────────

@router.get("/reconciliation")
def api_reconciliation(db: Session = Depends(get_db)):
    from backend.services.partner_reconciliation import (
        classify_batch_payment,
        payment_summary_by_batch,
    )

    try:
        rows = (
            db.query(
                PayrollBatch.payroll_batch_id,
                PayrollBatch.source,
                PayrollBatch.company_name,
                PayrollBatch.week_start,
                PayrollBatch.week_end,
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
                PayrollBatch.week_end,
            )
            .order_by(PayrollBatch.week_start.desc().nullslast())
            .all()
        )
        payment_summaries = payment_summary_by_batch(db)

        batches = []
        healthy = 0
        needs_review = 0
        largest_issue = 0.0
        deposits_unconfirmed = 0
        dispute_at_risk = 0

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

            pay = classify_batch_payment(
                revenue,
                payment_summaries.get(row.payroll_batch_id),
                row.week_end,
            )
            if pay.payment_status == "unpaid":
                deposits_unconfirmed += 1
            if (
                pay.payment_status == "underpaid"
                and not pay.disputed
                and pay.dispute_days_left is not None
                and pay.dispute_days_left <= 5
            ):
                dispute_at_risk += 1

            batches.append({
                "batch_id": row.payroll_batch_id,
                "week": fmt_week(row.week_start),
                "source": row.source or "",
                "company": row.company_name or "",
                "rides": int(row.ride_count or 0),
                "revenue": round(revenue, 2),
                "cost": round(cost, 2),
                "profit": round(profit, 2),
                "status": status,
                "payment_status": pay.payment_status,
                "deposited": pay.deposited,
                "payment_delta": pay.delta,
                "deposit_date": (
                    pay.first_deposit_date.isoformat() if pay.first_deposit_date else None
                ),
                "dispute_deadline": (
                    pay.dispute_deadline.isoformat() if pay.dispute_deadline else None
                ),
                "dispute_days_left": pay.dispute_days_left,
                "disputed": pay.disputed,
            })

        return JSONResponse({
            "stats": {
                "total": len(batches),
                "healthy": healthy,
                "needs_review": needs_review,
                "largest_issue": round(largest_issue, 2),
                "deposits_unconfirmed": deposits_unconfirmed,
                "dispute_at_risk": dispute_at_risk,
            },
            "batches": batches,
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


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


# ── Rides ────────────────────────────────────────────────────────────────────

@router.get("/rides")
def api_rides(
    person_id: int | None = Query(None),
    batch_id: int | None = Query(None),
    source: str | None = Query(None),
    db: Session = Depends(get_db),
):
    try:
        rows, total_net, payweek = _build_rides_rows(db, person_id=person_id, batch_id=batch_id, source=source)
        out = []
        for r in rows:
            out.append({
                "id": r.get("ride_id"),
                "date": r.get("date", ""),
                "driver": r.get("driver", ""),
                "company": r.get("company", ""),
                "service_code": r.get("service_code", ""),
                "service_name": r.get("service_name", ""),
                "miles": r.get("miles", 0),
                "rate": r.get("rate", 0),
                "net_pay": r.get("net_pay", 0),
                "gross_pay": r.get("gross_pay", 0),
                "z_rate": r.get("z_rate", 0),
                "deduction": r.get("deduction", 0),
                "batch_ref": r.get("batch_ref", ""),
                # partner_paid − driver_pay per trip
                "margin": round(float(r.get("net_pay", 0) or 0) - float(r.get("z_rate", 0) or 0), 2),
            })
        return JSONResponse(out)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/rides/search")
def api_rides_search(
    q: str = Query(""),
    unassigned_only: bool = Query(False),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """Search rides by service_name. Optionally filter to unassigned only and by date range."""
    UNASSIGNED_PERSON_ID = 227
    try:
        query = db.query(Ride, Person).join(Person, Ride.person_id == Person.person_id)
        if unassigned_only:
            query = query.filter(Ride.person_id == UNASSIGNED_PERSON_ID)
        if q:
            query = query.filter(Ride.service_name.ilike(f"%{q}%"))
        if date_from:
            query = query.filter(cast(Ride.ride_start_ts, Date) >= date_from)
        if date_to:
            query = query.filter(cast(Ride.ride_start_ts, Date) <= date_to)
        rows = query.order_by(Ride.ride_start_ts.asc()).limit(200).all()
        out = []
        for ride, person in rows:
            out.append({
                "ride_id": ride.ride_id,
                "service_name": ride.service_name or "",
                "date": ride.ride_start_ts.date().isoformat() if ride.ride_start_ts else "",
                "pickup_time": ride.ride_start_ts.strftime("%H:%M") if ride.ride_start_ts else "",
                "source": ride.source,
                "driver_pay": float(ride.net_pay or 0),
                "miles": float(ride.miles or 0),
                "notes": ride.service_ref or "",
                "person_id": person.person_id,
                "driver": person.full_name if person.full_name != "Unassigned" else None,
                "is_unassigned": person.person_id == UNASSIGNED_PERSON_ID,
            })
        return JSONResponse(out)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/routes/current")
def api_routes_current(db: Session = Depends(get_db)):
    """Most recent driver per route — for dispatch planning."""
    try:
        from sqlalchemy import text
        rows = db.execute(text("""
            SELECT DISTINCT ON (r.service_name)
              r.service_name,
              r.net_pay,
              r.miles,
              p.person_id,
              p.full_name as driver_name,
              DATE(r.ride_start_ts) as last_date
            FROM ride r
            JOIN person p ON r.person_id = p.person_id
            WHERE p.full_name != 'Unassigned'
              AND r.source != 'manual'
            ORDER BY r.service_name, r.ride_start_ts DESC
        """)).fetchall()
        return JSONResponse([{
            "service_name": r.service_name,
            "net_pay": float(r.net_pay or 0),
            "miles": float(r.miles or 0),
            "person_id": r.person_id,
            "driver": r.driver_name,
            "last_date": str(r.last_date) if r.last_date else "",
        } for r in rows])
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.post("/routes/driver-history")
async def api_routes_driver_history(request: Request, db: Session = Depends(get_db)):
    """For a list of service_names, return driver ride counts per route (for experience ranking)."""
    try:
        from sqlalchemy import text
        body = await request.json()
        service_names = body.get("service_names", [])
        if not service_names:
            return JSONResponse({})
        rows = db.execute(text("""
            SELECT r.service_name, p.person_id, p.full_name as driver_name, COUNT(*) as ride_count
            FROM ride r
            JOIN person p ON r.person_id = p.person_id
            WHERE r.service_name = ANY(:names)
              AND p.full_name != 'Unassigned'
            GROUP BY r.service_name, p.person_id, p.full_name
            ORDER BY r.service_name, COUNT(*) DESC
        """), {"names": service_names}).fetchall()
        result: dict = {}
        for row in rows:
            if row.service_name not in result:
                result[row.service_name] = []
            result[row.service_name].append({
                "person_id": row.person_id,
                "driver": row.driver_name,
                "ride_count": int(row.ride_count),
            })
        return JSONResponse(result)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.post("/rides/{ride_id}/assign")
async def api_assign_ride(ride_id: int, request: Request, db: Session = Depends(get_db)):
    """Assign a driver to a ride (replaces Unassigned placeholder or current driver)."""
    body = await request.json()
    person_id = body.get("person_id")
    if not person_id:
        return JSONResponse({"error": "person_id required"}, status_code=400)

    ride = db.query(Ride).filter(Ride.ride_id == ride_id).first()
    if not ride:
        return JSONResponse({"error": "Ride not found"}, status_code=404)

    person = db.query(Person).filter(Person.person_id == int(person_id)).first()
    if not person:
        return JSONResponse({"error": "Driver not found"}, status_code=404)

    ride.person_id = int(person_id)
    db.commit()
    return JSONResponse({"ok": True, "ride_id": ride_id, "driver": person.full_name})


# ── Dispatch Agent ───────────────────────────────────────────────────────────

@router.post("/dispatch/agent/chat")
async def api_dispatch_agent_chat(request: Request, db: Session = Depends(get_db)):
    """Natural-language dispatch agent. Reads only; proposes actions for user confirmation.

    Accepts an optional ``mode`` field in the JSON body (default: "dispatcher").
    Unknown modes fall back to "dispatcher" so existing callers are unaffected.
    """
    from backend.services.dispatch_agent import run_agent
    from backend.services.agent_modes import get_system_prompt

    try:
        body = await request.json()
        message = (body.get("message") or "").strip()
        history = body.get("history") or []
        mode = (body.get("mode") or "dispatcher").strip().lower()

        if not message:
            return JSONResponse({"error": "message required"}, status_code=400)

        system_prompt = get_system_prompt(mode)
        result = run_agent(db, message, history=history, system_prompt=system_prompt, mode=mode)
        return JSONResponse(result)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Dispatch ─────────────────────────────────────────────────────────────────

@router.get("/dispatch")
async def api_dispatch(
    for_date: date | None = Query(None, alias="date"),
    source: str | None = Query(None),
    refresh: int = Query(0),
    db: Session = Depends(get_db),
):
    """Proxy to dispatch logic for consistency with /api/data/* pattern."""
    from backend.routes.dispatch import (
        _fetch_dispatch_data,
        _load_db_persons,
        _auto_link_drivers,
        _auto_create_persons,
        _build_driver_cards,
        CACHE_TTL,
    )
    import time as _time

    try:
        target_date = for_date or date.today()
        data = await _fetch_dispatch_data(target_date, force_refresh=bool(refresh))

        db_persons = _load_db_persons(db)
        _auto_link_drivers(data, db_persons, db)
        _auto_create_persons(data, db_persons, db)
        db_persons = _load_db_persons(db)

        drivers, unassigned, dashboard = _build_driver_cards(data, db_persons, source)

        return JSONResponse({
            "drivers": drivers,
            "dashboard": dashboard,
            "unassigned": unassigned,
            "fa_ok": data["fa_ok"],
            "fa_error": data["fa_error"],
            "ed_ok": data["ed_ok"],
            "ed_error": data["ed_error"],
            "ed_auth_needed": data["ed_auth_needed"],
            "last_updated": int(_time.time() - data["ts"]),
            "cache_ttl": CACHE_TTL,
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── EverDriven Dispatch ──────────────────────────────────────────────────────

@router.get("/dispatch-everdriven")
def api_dispatch_everdriven(
    for_date: str | None = Query(None, alias="date"),
    db: Session = Depends(get_db),
):
    from datetime import date as _date

    try:
        target_date = _date.fromisoformat(for_date) if for_date else _date.today()
    except ValueError:
        target_date = _date.today()

    try:
        runs = everdriven_service.get_runs(target_date)
        dashboard = everdriven_service.get_dashboard(target_date)
        authenticated = True
    except EverDrivenAuthError:
        runs = []
        dashboard = {}
        authenticated = False
    except Exception:
        runs = []
        dashboard = {}
        authenticated = False

    driver_run_map: dict[str, list] = {}
    for run in runs:
        did = run.get("driverId")
        if not did:
            continue
        driver_run_map.setdefault(did, []).append(run)

    db_drivers = (
        db.query(Person)
        .filter(Person.everdriven_driver_id.isnot(None))
        .order_by(Person.full_name.asc())
        .all()
    )

    drivers = []
    for p in db_drivers:
        run_list = driver_run_map.get(str(p.everdriven_driver_id), [])
        run_list_sorted = sorted(run_list, key=lambda r: r.get("firstPickUp") or "99:99")
        mapped_runs = []
        for r in run_list_sorted:
            students = r.get("students", [])
            mapped_runs.append({
                "id": r.get("keyValue") or r.get("tripId", ""),
                "time": r.get("firstPickUp", ""),
                "status": r.get("tripStatus", ""),
                "students": len(students) if isinstance(students, list) else 0,
                "miles": r.get("miles", 0),
            })
        drivers.append({
            "id": p.person_id,
            "name": p.full_name,
            "phone": p.phone or "",
            "address": p.home_address or "",
            "trip_count": len(run_list_sorted),
            "runs": mapped_runs,
        })

    matched_ids = {str(p.everdriven_driver_id) for p in db_drivers}
    unmatched = []
    for r in runs:
        if r.get("driverId") not in matched_ids:
            students = r.get("students", [])
            unmatched.append({
                "id": r.get("keyValue") or r.get("tripId", ""),
                "time": r.get("firstPickUp", ""),
                "status": r.get("tripStatus", ""),
                "students": len(students) if isinstance(students, list) else 0,
                "miles": r.get("miles", 0),
            })

    total = len(runs)
    completed = sum(1 for r in runs if "complete" in (r.get("tripStatus") or "").lower())
    active = sum(1 for r in runs if "active" in (r.get("tripStatus") or "").lower() or "start" in (r.get("tripStatus") or "").lower())
    cancelled = sum(1 for r in runs if "cancel" in (r.get("tripStatus") or "").lower())
    scheduled = total - completed - active - cancelled

    return JSONResponse({
        "authenticated": authenticated,
        "drivers": drivers,
        "unmatched": unmatched,
        "stats": {
            "total": total,
            "completed": completed,
            "active": active,
            "scheduled": scheduled,
            "cancelled": cancelled,
        },
    })


# ── Admin Rates ──────────────────────────────────────────────────────────────

@router.get("/rates")
def api_rates(db: Session = Depends(get_db)):
    from backend.db.models import ZRateService, ZRateOverride, PayrollBatch
    try:
        services = (
            db.query(ZRateService)
            .order_by(ZRateService.service_name.asc())
            .all()
        )

        override_counts = dict(
            db.query(
                ZRateOverride.z_rate_service_id,
                func.count(ZRateOverride.z_rate_override_id),
            )
            .group_by(ZRateOverride.z_rate_service_id)
            .all()
        )

        # Ride stats per service: use MAX miles and MAX net_pay (not averages —
        # rates are discrete set numbers per route, never averaged across trips).
        # MAX is the safe aggregation here: miles and partner pay are fixed per
        # route; MAX returns the true value without fabricating a blended figure.
        ride_stats_q = (
            db.query(
                Ride.z_rate_service_id,
                func.max(Ride.miles).label("route_miles"),
                func.max(Ride.net_pay).label("route_net_pay"),
                func.count(Ride.ride_id).label("ride_count"),
                func.max(PayrollBatch.period_end).label("latest_period_end"),
                func.min(PayrollBatch.period_start).label("earliest_period_start"),
            )
            .join(PayrollBatch, Ride.payroll_batch_id == PayrollBatch.payroll_batch_id)
            .filter(Ride.z_rate_service_id.isnot(None))
            .group_by(Ride.z_rate_service_id)
            .all()
        )
        ride_stats = {
            r.z_rate_service_id: {
                "route_miles": round(float(r.route_miles or 0), 1),
                "route_net_pay": round(float(r.route_net_pay or 0), 2),
                "ride_count": int(r.ride_count or 0),
                "latest_period_end": r.latest_period_end.isoformat() if r.latest_period_end else None,
                "earliest_period_start": r.earliest_period_start.isoformat() if r.earliest_period_start else None,
            }
            for r in ride_stats_q
        }

        # Driver names per service (who drives this route)
        driver_names_q = (
            db.query(
                Ride.z_rate_service_id,
                Person.full_name,
            )
            .join(Person, Ride.person_id == Person.person_id)
            .filter(Ride.z_rate_service_id.isnot(None))
            .group_by(Ride.z_rate_service_id, Person.full_name)
            .all()
        )
        driver_names_map: dict[int, list[str]] = {}
        for row in driver_names_q:
            driver_names_map.setdefault(row.z_rate_service_id, []).append(row.full_name)

        unmatched_services = (
            db.query(Ride.service_name, func.count(Ride.ride_id).label("count"))
            .filter(Ride.z_rate == 0, Ride.service_name.isnot(None))
            .group_by(Ride.service_name)
            .order_by(func.count(Ride.ride_id).desc())
            .all()
        )
        unmatched_names = {r.service_name for r in unmatched_services}

        rates = []
        for s in services:
            stats = ride_stats.get(s.z_rate_service_id, {})
            rates.append({
                "id": s.z_rate_service_id,
                "service_code": s.service_key,
                "service_name": s.service_name,
                "default_rate": float(s.default_rate) if s.default_rate is not None else 0,
                "source": s.source,
                "company_name": s.company_name,
                "override_count": override_counts.get(s.z_rate_service_id, 0),
                "unmatched": s.service_name in unmatched_names,
                "route_miles": stats.get("route_miles", 0),
                "route_net_pay": stats.get("route_net_pay", 0),
                "ride_count": stats.get("ride_count", 0),
                "latest_period_end": stats.get("latest_period_end"),
                "earliest_period_start": stats.get("earliest_period_start"),
                "driver_names": driver_names_map.get(s.z_rate_service_id, []),
            })

        unmatched_out = [
            {"service_code": r.service_name, "count": int(r.count)}
            for r in unmatched_services
        ]

        return JSONResponse({"rates": rates, "unmatched": unmatched_out})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.post("/rates/{service_id}/set")
async def api_set_rate(service_id: int, request: Request, db: Session = Depends(get_db)):
    from backend.db.models import ZRateService
    from decimal import Decimal

    # Accept JSON body with {"rate": 38.00}
    body = await request.json()
    rate_val = body.get("rate")
    if rate_val is None:
        return JSONResponse({"error": "rate is required"}, status_code=400)

    svc = db.query(ZRateService).filter(ZRateService.z_rate_service_id == service_id).one_or_none()
    if not svc:
        return JSONResponse({"error": "Service not found"}, status_code=404)

    svc.default_rate = Decimal(str(rate_val))
    db.add(svc)

    # Also update rides with z_rate=0 for this service
    updated = (
        db.query(Ride)
        .filter(Ride.z_rate_service_id == service_id, Ride.z_rate == 0)
        .update({"z_rate": float(rate_val)}, synchronize_session=False)
    )

    db.commit()
    return JSONResponse({"ok": True, "rides_updated": updated})


@router.post("/rides/{ride_id}/set-rate")
async def api_set_ride_rate(ride_id: int, request: Request, db: Session = Depends(get_db)):
    """Set the z_rate (driver pay) for a single ride.
    If update_default=true, also updates the ZRateService default_rate for this route."""
    from backend.db.models import ZRateService
    from decimal import Decimal
    body = await request.json()
    rate_val = body.get("rate")
    update_default = body.get("update_default", False)
    if rate_val is None:
        return JSONResponse({"error": "rate is required"}, status_code=400)

    ride = db.query(Ride).filter(Ride.ride_id == ride_id).one_or_none()
    if not ride:
        return JSONResponse({"error": "Ride not found"}, status_code=404)

    if ride.z_rate_locked_at is not None:
        return JSONResponse(
            {"error": f"ride {ride_id} z_rate is locked since {ride.z_rate_locked_at}; cannot modify"},
            status_code=409,
        )

    ride.z_rate = float(rate_val)

    service_updated = False
    if update_default and ride.service_name:
        svc = db.query(ZRateService).filter(ZRateService.service_name == ride.service_name).first()
        if svc:
            svc.default_rate = Decimal(str(rate_val))
        else:
            svc = ZRateService(service_name=ride.service_name, default_rate=Decimal(str(rate_val)))
            db.add(svc)
        service_updated = True

    db.commit()
    return JSONResponse({"ok": True, "ride_id": ride_id, "z_rate": float(rate_val), "service_updated": service_updated})


# ── Remove ride (soft-delete) — Malik or Mom (admin/operator) ────────────────

@router.patch(
    "/rides/{ride_id}/remove",
    dependencies=[Depends(require_role("admin", "operator"))],
)
async def api_remove_ride(
    ride_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Soft-delete a ride from driver payout — Malik or Mom (admin/operator).

    The ride row is NOT deleted. Revenue columns (gross_pay, net_pay) are kept
    intact so Z-Pay's revenue numbers stay correct. Only z_rate is excluded from
    all payout sums (SUM(z_rate)) while removed_at IS NOT NULL.

    This is the correct way to remove an already-paid back-pay line without
    corrupting revenue — per the 2026-05-20 incident where hard-deleting ride
    13715 silently removed FA revenue Malik was actively tracking.

    Body: { "reason": "string (required, ≤200 chars)" }

    Returns: { "ok": true, "ride_id": int, "removed_at": iso-timestamp,
               "removed_by": username, "removed_reason": reason }

    Idempotent: re-removing an already-removed ride is a no-op (returns same data).
    """
    from datetime import datetime, timezone

    body = await request.json()
    reason = (body.get("reason") or "").strip()
    if not reason:
        return JSONResponse({"error": "reason is required"}, status_code=400)
    if len(reason) > 200:
        return JSONResponse({"error": "reason must be 200 characters or fewer"}, status_code=400)

    ride = db.query(Ride).filter(Ride.ride_id == ride_id).one_or_none()
    if not ride:
        return JSONResponse({"error": "Ride not found"}, status_code=404)

    # Idempotent — already removed
    if ride.removed_at is not None:
        return JSONResponse({
            "ok": True,
            "ride_id": ride_id,
            "removed_at": ride.removed_at.isoformat(),
            "removed_by": ride.removed_by,
            "removed_reason": ride.removed_reason,
        })

    # Resolve the admin's username from the request session (same as require_role reads it)
    user = getattr(request.state, "user", {}) or {}
    admin_username: str = user.get("username") or user.get("display_name") or "admin"

    now = datetime.now(timezone.utc)
    ride.removed_at = now
    ride.removed_by = admin_username
    ride.removed_reason = reason

    audit_row = AuditLog(
        actor_user_id=user.get("user_id"),
        actor_email=user.get("email"),
        action="ride.remove",
        target_type="ride",
        target_id=ride_id,
        before_value={"removed_at": None, "batch_id": ride.payroll_batch_id},
        after_value={
            "removed_at": now.isoformat(),
            "removed_by": admin_username,
            "removed_reason": reason,
            "batch_id": ride.payroll_batch_id,
        },
        ip=(request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
    )
    db.add(audit_row)
    db.commit()

    return JSONResponse({
        "ok": True,
        "ride_id": ride_id,
        "removed_at": now.isoformat(),
        "removed_by": admin_username,
        "removed_reason": reason,
    })


@router.patch(
    "/rides/{ride_id}/restore",
    dependencies=[Depends(require_role("admin", "operator"))],
)
async def api_restore_ride(
    ride_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Restore a previously soft-deleted ride back into payout calculations — Malik or Mom (admin/operator).

    Clears removed_at / removed_by / removed_reason.
    Idempotent: restoring an active ride is a no-op.
    """
    from datetime import datetime, timezone

    ride = db.query(Ride).filter(Ride.ride_id == ride_id).one_or_none()
    if not ride:
        return JSONResponse({"error": "Ride not found"}, status_code=404)

    if ride.removed_at is None:
        return JSONResponse({"ok": True, "ride_id": ride_id, "already_active": True})

    user = getattr(request.state, "user", {}) or {}
    admin_username: str = user.get("username") or user.get("display_name") or "admin"

    prev_removed_at = ride.removed_at.isoformat() if ride.removed_at else None
    prev_removed_by = ride.removed_by
    prev_removed_reason = ride.removed_reason

    ride.removed_at = None
    ride.removed_by = None
    ride.removed_reason = None

    audit_row = AuditLog(
        actor_user_id=user.get("user_id"),
        actor_email=user.get("email"),
        action="ride.restore",
        target_type="ride",
        target_id=ride_id,
        before_value={
            "removed_at": prev_removed_at,
            "removed_by": prev_removed_by,
            "removed_reason": prev_removed_reason,
            "batch_id": ride.payroll_batch_id,
        },
        after_value={"removed_at": None, "batch_id": ride.payroll_batch_id},
        ip=(request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
    )
    db.add(audit_row)
    db.commit()

    return JSONResponse({"ok": True, "ride_id": ride_id, "restored": True})


# ── Maz Earnings — internal machine-to-machine endpoint ──────────────────────
# Used by Life OS dashboard to pull current-month earnings without a user session.
# Protected by ZPAY_INTERNAL_SECRET header (same secret used by health/upload-session).

@router.get("/maz-earnings")
def api_maz_earnings(request: Request, db: Session = Depends(get_db)):
    """
    Returns a monthly earnings summary for the Life OS money page sync.
    Auth: X-Internal-Secret header must match ZPAY_INTERNAL_SECRET env var.
    Response: { totalEarnings, periodStart, periodEnd, driverCount, batchCount }
    """
    secret = request.headers.get("X-Internal-Secret", "")
    expected = os.environ.get("ZPAY_INTERNAL_SECRET", "")

    if not expected:
        return JSONResponse({"error": "Internal secret not configured on server"}, status_code=503)
    if secret != expected:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        today = date.today()
        current_year = today.year
        current_month = today.month

        # Pull all finalized batches in the current calendar month
        batches_this_month = (
            db.query(PayrollBatch)
            .filter(
                PayrollBatch.finalized_at.isnot(None),
                extract("year", PayrollBatch.period_start) == current_year,
                extract("month", PayrollBatch.period_start) == current_month,
            )
            .order_by(PayrollBatch.period_start.asc())
            .all()
        )

        batch_ids = [b.payroll_batch_id for b in batches_this_month]

        if not batch_ids:
            # Fall back: any finalized batch regardless of date — return the most recent
            latest_batch = (
                db.query(PayrollBatch)
                .filter(PayrollBatch.finalized_at.isnot(None))
                .order_by(PayrollBatch.period_start.desc())
                .first()
            )
            if not latest_batch:
                return JSONResponse({
                    "totalEarnings": 0,
                    "periodStart": None,
                    "periodEnd": None,
                    "driverCount": 0,
                    "batchCount": 0,
                    "note": "no_finalized_batches",
                })
            batch_ids = [latest_batch.payroll_batch_id]
            batches_this_month = [latest_batch]

        # Aggregate: total net_pay (what Maz collects from partners) across all batches
        agg = (
            db.query(
                func.coalesce(func.sum(Ride.net_pay), 0).label("total_earnings"),
                func.count(func.distinct(Ride.person_id)).label("driver_count"),
            )
            .join(PayrollBatch, PayrollBatch.payroll_batch_id == Ride.payroll_batch_id)
            .filter(Ride.payroll_batch_id.in_(batch_ids))
            .one()
        )

        period_start = min(
            b.period_start for b in batches_this_month if b.period_start
        ) if batches_this_month else None
        period_end = max(
            b.period_end for b in batches_this_month if b.period_end
        ) if batches_this_month else None

        return JSONResponse({
            "totalEarnings": round(float(agg.total_earnings), 2),
            "periodStart": period_start.isoformat() if period_start else None,
            "periodEnd": period_end.isoformat() if period_end else None,
            "driverCount": int(agg.driver_count),
            "batchCount": len(batch_ids),
        })

    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# Batch Correction Log
# ---------------------------------------------------------------------------

@router.get("/payroll-history/{batch_id}/corrections")
def list_corrections(batch_id: int, db: Session = Depends(get_db)):
    rows = (
        db.query(BatchCorrectionLog)
        .filter(BatchCorrectionLog.batch_id == batch_id)
        .order_by(BatchCorrectionLog.corrected_at.desc())
        .all()
    )
    return JSONResponse([
        {
            "id": r.id,
            "batch_id": r.batch_id,
            "person_id": r.person_id,
            "field": r.field,
            "old_value": r.old_value,
            "new_value": r.new_value,
            "reason": r.reason,
            "corrected_by": r.corrected_by,
            "corrected_at": r.corrected_at.isoformat() if r.corrected_at else None,
        }
        for r in rows
    ])


# TODO: add auth dependency once auth system is wired (see workflow.py / batches.py for pattern:
#       _=Depends(require_role("admin")) from backend.utils.roles)
@router.post("/rides")
async def api_create_ride(request: Request, db: Session = Depends(get_db)):
    """Manually add a ride/adjustment to an existing payroll batch.

    Two modes:
    - Free-form: provide ``service_name`` + ``driver_pay`` (amount > 0) + optional ``reason``.
    - Route:     provide ``z_rate_service_id`` to auto-resolve service_name, rate, and last
                 known miles from historical rides for that route. Optionally supply
                 ``override_rate`` to override the resolver result.

    ``source`` is no longer caller-controlled — it is always set to ``'manual'``.

    DEPRECATED silent behaviours (removed 2026-04-20):
      - Auto-creation of ghost 'manual-{date}-{source}' batches is no longer supported.
      - Fallback to UNASSIGNED_PERSON_ID=227 is no longer supported.
    Both fields are now required; missing or invalid values return HTTP 400.
    """
    import json
    import uuid
    import logging
    from datetime import datetime, date as date_type
    from decimal import Decimal
    import pytz

    from backend.db.models import ZRateService
    from backend.services.rates import resolve_rate_for_ride

    _LA = pytz.timezone("America/Los_Angeles")

    logger = logging.getLogger(__name__)
    body = await request.json()

    # ── Request fields ────────────────────────────────────────────────────────
    person_id = body.get("person_id")
    payroll_batch_id = body.get("payroll_batch_id")
    ride_date_str = body.get("date", "")
    pickup_time = body.get("pickup_time", "")
    notes = body.get("notes", "")
    reason = body.get("reason", "")
    corrected_by = body.get("corrected_by") or "user"

    # Route-mode fields
    z_rate_service_id = body.get("z_rate_service_id")

    # Free-form fields (only used when z_rate_service_id is absent)
    service_name_raw = body.get("service_name", "").strip()
    miles_raw = body.get("miles", 0)
    driver_pay_raw = body.get("driver_pay", 0)

    # Override rate (route mode only)
    override_rate_raw = body.get("override_rate")

    # ── Basic required-field validation ───────────────────────────────────────
    if not person_id:
        return JSONResponse(
            {"error": "person_id is required. Assigning rides to an unassigned driver is not permitted."},
            status_code=400,
        )

    if not payroll_batch_id:
        return JSONResponse(
            {"error": "payroll_batch_id is required. Auto-creation of manual batches is not permitted."},
            status_code=400,
        )

    if not ride_date_str:
        return JSONResponse({"error": "date is required"}, status_code=400)

    if len(reason) > 200:
        return JSONResponse({"error": "Reason text capped at 200 characters."}, status_code=400)

    try:
        ride_date = date_type.fromisoformat(ride_date_str)
    except ValueError:
        return JSONResponse({"error": "Invalid date format, expected YYYY-MM-DD"}, status_code=400)

    # ── Validate person ───────────────────────────────────────────────────────
    person = db.query(Person).filter(Person.person_id == int(person_id)).first()
    if not person:
        return JSONResponse({"error": f"person_id {person_id} not found"}, status_code=400)

    # ── Bug C fix: lock the batch row and reject if already closed ────────────
    from sqlalchemy import text as _text

    batch = (
        db.query(PayrollBatch)
        .filter(PayrollBatch.payroll_batch_id == int(payroll_batch_id))
        .with_for_update()
        .first()
    )
    if not batch:
        return JSONResponse({"error": f"payroll_batch_id {payroll_batch_id} not found"}, status_code=400)

    if batch.status == "complete" or batch.paychex_exported_at is not None or batch.finalized_at is not None:
        return JSONResponse(
            {"error": "This batch is locked (finalized, complete, or already exported to Paychex). Adjustments cannot be added."},
            status_code=409,
        )

    # ── Resolve mode: route vs free-form ─────────────────────────────────────
    is_route_mode = z_rate_service_id is not None
    audit_mode = "route" if is_route_mode else "freeform"
    z_rate_service_id_resolved: int | None = None
    default_rate: Decimal | None = None

    if is_route_mode:
        svc = db.query(ZRateService).filter(
            ZRateService.z_rate_service_id == int(z_rate_service_id)
        ).first()
        if not svc:
            return JSONResponse(
                {"error": f"z_rate_service_id {z_rate_service_id} not found"},
                status_code=400,
            )

        # service_name comes from the ZRateService row — not operator input
        service_name = svc.service_name

        # Resolve default driver rate via the same lookup the auto-ingest uses
        resolved_rate, _src, _svc_id, _ov_id = resolve_rate_for_ride(
            db,
            source=svc.source or "",
            company_name=svc.company_name or "",
            service_name=svc.service_name,
            ride_date=ride_date,
            currency=svc.currency or "USD",
        )
        default_rate = resolved_rate
        z_rate_service_id_resolved = int(z_rate_service_id)

        if override_rate_raw is not None:
            driver_pay = Decimal(str(override_rate_raw))
            if driver_pay <= Decimal("0"):
                return JSONResponse(
                    {"error": "override_rate must be greater than 0."},
                    status_code=400,
                )
        else:
            if resolved_rate == Decimal("0"):
                return JSONResponse(
                    {"error": "This route has no driver rate configured. Use Free-form, or add a rate in rate-services admin first."},
                    status_code=400,
                )
            driver_pay = resolved_rate

        # Source miles from most-recent non-manual ride for this route
        miles_row = db.execute(
            _text("""
                SELECT miles
                FROM ride
                WHERE service_name = :sname
                  AND source != 'manual'
                ORDER BY ride_start_ts DESC
                LIMIT 1
            """),
            {"sname": svc.service_name},
        ).fetchone()
        miles = Decimal(str(miles_row.miles)) if miles_row and miles_row.miles is not None else Decimal("0")

    else:
        # Free-form mode
        if not service_name_raw:
            return JSONResponse(
                {"error": "service_name is required for free-form adjustments"},
                status_code=400,
            )
        service_name = service_name_raw
        driver_pay = Decimal(str(driver_pay_raw))
        miles = Decimal(str(miles_raw))

    # driver_pay may be positive (rides, makeups, bonuses) or negative
    # (deductions, loan repayments, damages). Route mode still requires
    # a positive amount because it represents a real trip at a real rate;
    # deductions must go through free-form so they carry an explicit reason.
    if driver_pay == Decimal("0"):
        return JSONResponse(
            {"error": "driver_pay must be non-zero."},
            status_code=400,
        )
    if is_route_mode and driver_pay < Decimal("0"):
        return JSONResponse(
            {"error": "Route-mode rides must be positive. Use free-form for deductions."},
            status_code=400,
        )

    # ── Bug A fix: source is always 'manual', never caller-controlled ─────────
    source = "manual"
    source_ref = f"manual-{uuid.uuid4().hex[:12]}"

    # Honor the caller-supplied ride_date. If a pickup_time was passed use it,
    # otherwise anchor to 08:00 on the ride_date. All datetimes are localized
    # to America/Los_Angeles — DB column is DateTime(timezone=True).
    if pickup_time:
        try:
            ride_ts = _LA.localize(datetime.fromisoformat(f"{ride_date_str}T{pickup_time}:00"))
        except Exception:
            ride_ts = _LA.localize(datetime(ride_date.year, ride_date.month, ride_date.day, 8, 0, 0))
    else:
        ride_ts = _LA.localize(datetime(ride_date.year, ride_date.month, ride_date.day, 8, 0, 0))

    # ── Bug B fix: net_pay = 0 (gross_pay = z_rate preserves the invariant) ───
    ride = Ride(
        payroll_batch_id=batch.payroll_batch_id,
        person_id=int(person_id),
        ride_start_ts=ride_ts,
        service_name=service_name,
        service_ref=notes or service_name,
        service_ref_type="manual",
        source=source,
        source_ref=source_ref,
        z_rate=driver_pay,
        z_rate_source="manual",
        z_rate_service_id=z_rate_service_id_resolved,
        net_pay=Decimal("0"),       # Bug B fix — manuals never inflate partner_paid
        gross_pay=driver_pay,       # gross_pay == z_rate invariant preserved
        miles=miles,
        deduction=Decimal("0"),
        spiff=Decimal("0"),
    )
    db.add(ride)
    db.flush()  # obtain ride_id before writing the audit log in the same transaction

    # ── Bug D fix: write BatchCorrectionLog entry ─────────────────────────────
    audit_new: dict = {
        "ride_id": ride.ride_id,
        "service_name": service_name,
        "z_rate": float(driver_pay),
        "mode": audit_mode,
    }
    if is_route_mode and default_rate is not None and override_rate_raw is not None:
        audit_new["default_rate"] = float(default_rate)
        audit_new["override_rate"] = float(driver_pay)

    audit_log = BatchCorrectionLog(
        batch_id=batch.payroll_batch_id,
        person_id=int(person_id),
        field="manual_ride",
        old_value=None,
        new_value=json.dumps(audit_new),
        reason=reason or notes or None,
        corrected_by=corrected_by,
    )
    db.add(audit_log)
    db.commit()
    db.refresh(ride)

    # ── Risk #12: warn if driver lacks a Paychex code for this company ────────
    company_lower = (batch.company_name or "").lower()
    needs_maz_code = any(kw in company_lower for kw in ("maz", "ever"))
    paychex_code = person.paycheck_code_maz if needs_maz_code else person.paycheck_code
    warning: str | None = None
    if not paychex_code:
        warning = (
            "This driver has no Paychex Worker ID for this company — "
            "adjustment will appear in workflow total but will NOT export to Paychex CSV."
        )

    response: dict = {
        "ok": True,
        "ride_id": ride.ride_id,
        "driver": person.full_name if person else "",
        "service_name": ride.service_name,
        "date": ride_date_str,
        "driver_pay": float(ride.gross_pay),
        "batch_ref": batch.batch_ref,
        "mode": audit_mode,
    }
    if warning:
        response["warning"] = warning

    return JSONResponse(response)


# TODO: add auth dependency once auth system is wired (see workflow.py / batches.py for pattern)
@router.delete("/rides/{ride_id}")
async def api_delete_ride(ride_id: int, request: Request, db: Session = Depends(get_db)):
    """Delete a manual ride/adjustment. Returns 403 for non-manual rides.

    Also gated by batch lock: returns 409 if the batch is complete or already
    exported to Paychex.
    """
    import json
    import logging

    logger = logging.getLogger(__name__)

    ride = db.query(Ride).filter(Ride.ride_id == ride_id).first()
    if not ride:
        return JSONResponse({"error": f"ride_id {ride_id} not found"}, status_code=404)

    if ride.source != "manual":
        return JSONResponse(
            {"error": "Only manual adjustments can be deleted. Real rides are immutable."},
            status_code=403,
        )

    # Lock the batch and check status
    batch = (
        db.query(PayrollBatch)
        .filter(PayrollBatch.payroll_batch_id == ride.payroll_batch_id)
        .with_for_update()
        .first()
    )
    if batch and (batch.status == "complete" or batch.paychex_exported_at is not None or batch.finalized_at is not None):
        return JSONResponse(
            {"error": "This batch is locked (finalized, complete, or already exported to Paychex). Adjustments cannot be added."},
            status_code=409,
        )

    # Snapshot before delete for the audit log
    audit_old: dict = {
        "ride_id": ride.ride_id,
        "service_name": ride.service_name,
        "z_rate": float(ride.z_rate),
        "gross_pay": float(ride.gross_pay),
        "person_id": ride.person_id,
    }

    audit_log = BatchCorrectionLog(
        batch_id=ride.payroll_batch_id,
        person_id=ride.person_id,
        field="manual_ride_deleted",
        old_value=json.dumps(audit_old),
        new_value=None,
        reason=None,
        corrected_by="user",
    )
    db.add(audit_log)
    db.delete(ride)
    db.commit()

    return JSONResponse({"ok": True, "deleted_ride_id": ride_id})


@router.post("/payroll-history/{batch_id}/corrections")
async def add_correction(batch_id: int, request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    entry = BatchCorrectionLog(
        batch_id=batch_id,
        person_id=body.get("person_id"),
        field=body.get("field", ""),
        old_value=str(body.get("old_value", "")) if body.get("old_value") is not None else None,
        new_value=str(body.get("new_value", "")) if body.get("new_value") is not None else None,
        reason=body.get("reason"),
        corrected_by=body.get("corrected_by", "user"),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return JSONResponse({"ok": True, "id": entry.id})



# ── Health / Audit ────────────────────────────────────────────────────────────

@router.get("/health")
def api_health(db: Session = Depends(get_db)):
    """
    DB-only health check. Returns a list of issues found across all batches.
    Green = no issues. Red = issues list with details.
    """
    try:
        from sqlalchemy import text as _text

        issues = []

        # 1. Batches with zero-rate rides (driver not getting paid)
        zero_rate_batches = (
            db.query(
                PayrollBatch.payroll_batch_id,
                PayrollBatch.source,
                PayrollBatch.company_name,
                PayrollBatch.week_start,
                func.count(Ride.ride_id).label("zero_count"),
            )
            .join(Ride, Ride.payroll_batch_id == PayrollBatch.payroll_batch_id)
            .filter(Ride.z_rate == 0)
            .group_by(
                PayrollBatch.payroll_batch_id,
                PayrollBatch.source,
                PayrollBatch.company_name,
                PayrollBatch.week_start,
            )
            .all()
        )
        for row in zero_rate_batches:
            week = row.week_start.strftime("%-m/%-d/%Y") if row.week_start else "unknown week"
            issues.append({
                "severity": "error",
                "type": "zero_rate",
                "title": f"{row.zero_count} ride(s) with $0 driver rate",
                "detail": f"{row.company_name or row.source} — week of {week}",
                "batch_id": row.payroll_batch_id,
            })

        # 2. Batches where total cost > total revenue (paying out more than received)
        loss_batches = (
            db.query(
                PayrollBatch.payroll_batch_id,
                PayrollBatch.source,
                PayrollBatch.company_name,
                PayrollBatch.week_start,
                func.sum(Ride.net_pay).label("revenue"),
                func.sum(Ride.z_rate).label("cost"),
            )
            .join(Ride, Ride.payroll_batch_id == PayrollBatch.payroll_batch_id)
            .group_by(
                PayrollBatch.payroll_batch_id,
                PayrollBatch.source,
                PayrollBatch.company_name,
                PayrollBatch.week_start,
            )
            .having(func.sum(Ride.z_rate) > func.sum(Ride.net_pay))
            .all()
        )
        for row in loss_batches:
            week = row.week_start.strftime("%-m/%-d/%Y") if row.week_start else "unknown week"
            revenue = float(row.revenue or 0)
            cost = float(row.cost or 0)
            gap = round(cost - revenue, 2)
            issues.append({
                "severity": "error",
                "type": "negative_margin",
                "title": f"Paying out ${gap} more than received",
                "detail": f"{row.company_name or row.source} — week of {week} (revenue ${round(revenue,2)}, cost ${round(cost,2)})",
                "batch_id": row.payroll_batch_id,
            })

        # 3. Batches with rides but net_pay = 0 (partner didn't pay)
        unpaid_batches = (
            db.query(
                PayrollBatch.payroll_batch_id,
                PayrollBatch.source,
                PayrollBatch.company_name,
                PayrollBatch.week_start,
                func.count(Ride.ride_id).label("ride_count"),
            )
            .join(Ride, Ride.payroll_batch_id == PayrollBatch.payroll_batch_id)
            .filter(Ride.net_pay == 0)
            .group_by(
                PayrollBatch.payroll_batch_id,
                PayrollBatch.source,
                PayrollBatch.company_name,
                PayrollBatch.week_start,
            )
            .all()
        )
        for row in unpaid_batches:
            week = row.week_start.strftime("%-m/%-d/%Y") if row.week_start else "unknown week"
            issues.append({
                "severity": "warning",
                "type": "unpaid_rides",
                "title": f"{row.ride_count} ride(s) with $0 partner payment",
                "detail": f"{row.company_name or row.source} — week of {week}",
                "batch_id": row.payroll_batch_id,
            })

        # 4. Active drivers with no paycheck code (can't run payroll for them)
        no_code = (
            db.query(func.count(Person.person_id))
            .filter(Person.active == True)
            .filter(
                (Person.paycheck_code == None) | (Person.paycheck_code == "")
            )
            .scalar()
        ) or 0
        if no_code > 0:
            issues.append({
                "severity": "warning",
                "type": "missing_paycheck_code",
                "title": f"{no_code} active driver(s) missing paycheck code",
                "detail": "These drivers cannot be included in Paychex export",
                "batch_id": None,
            })

        errors = [i for i in issues if i["severity"] == "error"]
        warnings = [i for i in issues if i["severity"] == "warning"]

        return JSONResponse({
            "ok": len(issues) == 0,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "issues": issues,
        })

    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Batches (JSON) ────────────────────────────────────────────────────────────

# TODO: add auth dependency once auth system is wired (see batches.py for pattern)
@router.get("/batches")
def api_batches(
    limit: int = Query(50, ge=1, le=500),
    include_locked: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Return recent payroll batches for the frontend batch picker.

    By default (``include_locked=false``) returns only unlocked batches:
    ``finalized_at IS NULL AND paychex_exported_at IS NULL AND status != 'complete'``.
    Pass ``include_locked=true`` to include all batches (history view, etc.).

    Response shape::

        [
          {
            "payroll_batch_id": int,
            "batch_ref": str | null,
            "company_name": str | null,
            "source": str | null,
            "week_start": "YYYY-MM-DD" | null,
            "week_end": "YYYY-MM-DD" | null,
            "period_start": "YYYY-MM-DD" | null,
            "period_end": "YYYY-MM-DD" | null,
            "status": str | null,
            "finalized_at": ISO-8601 | null,
            "paychex_exported_at": ISO-8601 | null
          },
          ...
        ]
    """
    try:
        q = db.query(PayrollBatch)
        if not include_locked:
            q = q.filter(
                PayrollBatch.finalized_at.is_(None),
                PayrollBatch.paychex_exported_at.is_(None),
                func.coalesce(PayrollBatch.status, "") != "complete",
            )
        rows = q.order_by(PayrollBatch.payroll_batch_id.desc()).limit(limit).all()

        def _iso(val):
            return val.isoformat() if val is not None else None

        result = [
            {
                "payroll_batch_id": b.payroll_batch_id,
                "batch_ref": b.batch_ref,
                "company_name": b.company_name,
                "source": b.source,
                "week_start": _iso(b.week_start),
                "week_end": _iso(b.week_end),
                "period_start": _iso(b.period_start),
                "period_end": _iso(b.period_end),
                "status": b.status,
                "finalized_at": _iso(b.finalized_at),
                "paychex_exported_at": _iso(b.paychex_exported_at),
            }
            for b in rows
        ]
        return JSONResponse(result)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Today's Ops ───────────────────────────────────────────────────────────────

@router.get("/today")
def api_today(db: Session = Depends(get_db)):
    """Today's operational snapshot: trip acceptance by source + avg rides/day goal tracker."""
    try:
        from datetime import date as _date
        from backend.db.models import TripNotification, Person as PersonModel
        from backend.routes.dashboard import _build_stats

        today = _date.today()

        notifs = (
            db.query(TripNotification, PersonModel)
            .join(PersonModel, PersonModel.person_id == TripNotification.person_id)
            .filter(TripNotification.trip_date == today)
            .all()
        )

        fa = {"total": 0, "accepted": 0, "not_accepted": 0, "started": 0, "not_started": 0, "escalations": 0}
        ed = {"total": 0, "accepted": 0, "not_accepted": 0, "started": 0, "not_started": 0, "escalations": 0}

        for notif, _ in notifs:
            src = ed if (notif.source or "").lower() == "maz" else fa
            src["total"] += 1
            if notif.accepted_at:
                src["accepted"] += 1
                if notif.started_at:
                    src["started"] += 1
                else:
                    src["not_started"] += 1
            else:
                src["not_accepted"] += 1
            if notif.accept_escalated_at or notif.start_escalated_at:
                src["escalations"] += 1

        total_today = fa["total"] + ed["total"]

        # Avg rides/day from historical data
        stats = _build_stats(db)
        avg_rides_per_day = float(stats.get("avg_rides_per_day", 0))
        goal = 300

        return JSONResponse({
            "fa": fa,
            "ed": ed,
            "total_today": total_today,
            "avg_rides_per_day": avg_rides_per_day,
            "goal": goal,
            "goal_pct": round(min(avg_rides_per_day / goal * 100, 100), 1),
        })

    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Daily Dashboard Summary ───────────────────────────────────────────────────

@router.get("/dashboard/summary")
def api_dashboard_summary(db: Session = Depends(get_db)):
    """
    Single-payload endpoint for the /dashboard page.

    Returns:
      today_trips     — counts by partner (fa/ed), live/completed/canceled
      active_drivers  — count + idle_over_2h callout
      health          — overall + per-check green/yellow/red from health_monitor
      inflight_alerts — open trip-notification escalation count
      last_payroll    — most recent finalized batch: total paid, driver count
      week_progress   — current school week number, days in, projected total
      money_flow      — partner receipts this week minus driver pay = margin
    """
    try:
        from datetime import date as _date, timedelta, datetime as _dt
        from backend.db.models import TripNotification, Person as PersonModel
        from backend.routes.dashboard import _build_stats, _get_school_week_map
        from sqlalchemy import text as _text

        today = _date.today()
        now_utc = _dt.now()

        # ── Today's Trips ────────────────────────────────────────────────────
        notifs = (
            db.query(TripNotification, PersonModel)
            .join(PersonModel, PersonModel.person_id == TripNotification.person_id)
            .filter(TripNotification.trip_date == today)
            .all()
        )

        def _blank_bucket():
            return {"total": 0, "live": 0, "completed": 0, "canceled": 0, "escalations": 0}

        fa_trips = _blank_bucket()
        ed_trips = _blank_bucket()

        _CANCELED_STATUSES = {
            "noshowreported", "noshow", "ridercanceled", "expired",
            "cancelled", "canceled",
        }
        _COMPLETED_STATUSES = {"completed", "complete", "done", "dropoff"}

        for notif, _ in notifs:
            is_ed = (notif.source or "").lower() in ("maz", "everdriven")
            bucket = ed_trips if is_ed else fa_trips
            bucket["total"] += 1
            raw_status = (notif.trip_status or "").lower().replace("_", "").replace("-", "")
            if raw_status in _CANCELED_STATUSES:
                bucket["canceled"] += 1
            elif raw_status in _COMPLETED_STATUSES or notif.started_at is not None:
                bucket["completed"] += 1
            else:
                bucket["live"] += 1
            if notif.accept_escalated_at or notif.start_escalated_at:
                bucket["escalations"] += 1

        total_today = fa_trips["total"] + ed_trips["total"]

        # ── Active Drivers ───────────────────────────────────────────────────
        active_driver_ids = {notif.person_id for notif, _ in notifs}
        active_count = len(active_driver_ids)

        # Idle >2h: drivers present today with no started_at in the last 2h
        two_h_ago = now_utc - timedelta(hours=2)
        recently_active = {
            notif.person_id
            for notif, _ in notifs
            if notif.started_at and notif.started_at.replace(tzinfo=None) >= two_h_ago
        }
        live_count = fa_trips["live"] + ed_trips["live"]
        idle_over_2h = max(0, active_count - len(recently_active) - live_count)
        idle_over_2h = min(idle_over_2h, active_count)

        # ── Health Checks ────────────────────────────────────────────────────
        try:
            from sqlalchemy import text as _htext
            health_rows = db.execute(
                _htext(
                    "SELECT check_name, status, last_checked_at, consecutive_failures "
                    "FROM health_check ORDER BY check_name"
                )
            ).fetchall()
            health_checks = [
                {
                    "name": r[0],
                    "status": r[1],
                    "last_checked_at": r[2].isoformat() if r[2] else None,
                    "consecutive_failures": int(r[3] or 0),
                }
                for r in health_rows
            ]
            any_red = any(c["status"] == "red" for c in health_checks)
            any_yellow = any(c["status"] == "yellow" for c in health_checks)
            health_overall = (
                "red" if any_red
                else "yellow" if any_yellow
                else ("green" if health_checks else "unknown")
            )
            open_alerts_count = db.execute(
                _htext("SELECT COUNT(*) FROM health_alert WHERE resolved_at IS NULL")
            ).scalar() or 0
        except Exception:
            health_checks = []
            health_overall = "unknown"
            open_alerts_count = 0

        # ── In-Flight Escalations ────────────────────────────────────────────
        inflight_alerts = sum(
            1 for notif, _ in notifs
            if (notif.accept_escalated_at or notif.start_escalated_at)
        )

        # ── Last Payroll Batch ────────────────────────────────────────────────
        last_batch = (
            db.query(PayrollBatch)
            .filter(PayrollBatch.finalized_at.isnot(None))
            .order_by(PayrollBatch.finalized_at.desc())
            .first()
        )
        last_payroll = None
        if last_batch:
            ride_agg = db.execute(
                _text(
                    "SELECT COUNT(DISTINCT person_id) as driver_count, "
                    "COALESCE(SUM(z_rate), 0) as total_paid "
                    "FROM ride WHERE payroll_batch_id = :bid"
                ),
                {"bid": last_batch.payroll_batch_id},
            ).one()
            last_payroll = {
                "batch_id": last_batch.payroll_batch_id,
                "batch_ref": last_batch.batch_ref or "",
                "company_name": last_batch.company_name,
                "source": last_batch.source,
                "finalized_at": (
                    last_batch.finalized_at.isoformat() if last_batch.finalized_at else None
                ),
                "week_start": (
                    last_batch.week_start.isoformat() if last_batch.week_start else None
                ),
                "week_end": (
                    last_batch.week_end.isoformat() if last_batch.week_end else None
                ),
                "total_paid": float(ride_agg.total_paid or 0),
                "driver_count": int(ride_agg.driver_count or 0),
            }

        # ── Week Progress ─────────────────────────────────────────────────────
        week_day_count = 5
        days_into_week = min(today.weekday() + 1, 5)  # Mon=1 … Fri=5, cap at 5

        school_week_num = None
        recent_batch = (
            db.query(PayrollBatch)
            .filter(PayrollBatch.week_start.isnot(None))
            .order_by(PayrollBatch.week_start.desc())
            .first()
        )
        if recent_batch:
            school_week_map = _get_school_week_map(db)
            school_week_num = school_week_map.get(
                (recent_batch.source, recent_batch.week_start)
            )

        four_weeks_ago = today - timedelta(weeks=4)
        hist = db.execute(
            _text(
                "SELECT COUNT(*) as cnt FROM trip_notification "
                "WHERE trip_date >= :start AND trip_date < :today"
            ),
            {"start": four_weeks_ago, "today": today},
        ).one()
        hist_total = int(hist.cnt or 0)
        avg_daily = round(hist_total / 20.0, 1)  # 4 weeks × 5 weekdays = 20
        projected_week_total = int(round(avg_daily * week_day_count, 0))

        week_progress = {
            "school_week": school_week_num,
            "days_into_week": days_into_week,
            "week_day_count": week_day_count,
            "today_total": total_today,
            "avg_daily_last_4w": avg_daily,
            "projected_week_total": projected_week_total,
        }

        # ── Money Flow (current school week) ──────────────────────────────────
        week_monday = today - timedelta(days=today.weekday())
        week_sunday = week_monday + timedelta(days=6)

        money_agg = db.execute(
            _text(
                "SELECT "
                "  COALESCE(SUM(r.net_pay), 0) AS partner_receipts, "
                "  COALESCE(SUM(r.z_rate), 0)  AS driver_pay "
                "FROM ride r "
                "JOIN payroll_batch pb ON pb.payroll_batch_id = r.payroll_batch_id "
                "WHERE pb.week_start >= :mon AND pb.week_start <= :sun"
            ),
            {"mon": week_monday, "sun": week_sunday},
        ).one()

        partner_receipts = float(money_agg.partner_receipts or 0)
        driver_pay_week = float(money_agg.driver_pay or 0)
        margin = round(partner_receipts - driver_pay_week, 2)
        margin_pct = round(margin / partner_receipts * 100, 1) if partner_receipts > 0 else 0.0

        money_flow = {
            "week_start": week_monday.isoformat(),
            "week_end": week_sunday.isoformat(),
            "partner_receipts": round(partner_receipts, 2),
            "driver_pay": round(driver_pay_week, 2),
            "margin": margin,
            "margin_pct": margin_pct,
        }

        return JSONResponse({
            "today_trips": {
                "fa": fa_trips,
                "ed": ed_trips,
                "total": total_today,
            },
            "active_drivers": {
                "count": active_count,
                "idle_over_2h": idle_over_2h,
            },
            "health": {
                "overall": health_overall,
                "checks": health_checks,
                "open_alerts": int(open_alerts_count),
            },
            "inflight_alerts": inflight_alerts,
            "last_payroll": last_payroll,
            "week_progress": week_progress,
            "money_flow": money_flow,
            "server_time": now_utc.isoformat(),
        })

    except Exception as exc:
        import traceback
        return JSONResponse(
            {"error": str(exc), "detail": traceback.format_exc()},
            status_code=500,
        )


# ── Trip-level margin endpoints ───────────────────────────────────────────────

@router.get("/margin/trips")
def api_margin_trips(
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
    source: str | None = Query(None),   # 'acumen' | 'maz'
    limit: int = Query(500, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    """
    Trip-level margins for all rides in the requested date range.

    Query params:
      from=YYYY-MM-DD   (default: 30 days ago)
      to=YYYY-MM-DD     (default: today)
      source=acumen|maz (optional filter)
      limit=N           (max 2000, default 500)

    Returns:
      {
        from, to, ride_count,
        totals: { total_partner_paid, total_driver_pay, total_margin, margin_pct },
        trips:  [ { ride_id, date, source, service_name, driver_name,
                    partner_paid, driver_pay, margin, margin_pct, notes } ],
        by_route: [ { service_name, ride_count, partner_paid, driver_pay,
                      margin, margin_pct } sorted asc by margin ]
      }
    """
    try:
        from datetime import date, timedelta
        from sqlalchemy import cast, Date as SADate
        from backend.services.trip_margin import (
            calculate_trip_margin_from_orm,
            aggregate_margins,
        )

        today = date.today()
        if from_date:
            try:
                start = date.fromisoformat(from_date)
            except ValueError:
                return JSONResponse({"error": "Invalid from date, expected YYYY-MM-DD"}, status_code=400)
        else:
            start = today - timedelta(days=30)

        if to_date:
            try:
                end = date.fromisoformat(to_date)
            except ValueError:
                return JSONResponse({"error": "Invalid to date, expected YYYY-MM-DD"}, status_code=400)
        else:
            end = today

        q = (
            db.query(Ride, Person)
            .join(Person, Ride.person_id == Person.person_id)
            .filter(cast(Ride.ride_start_ts, SADate) >= start)
            .filter(cast(Ride.ride_start_ts, SADate) <= end)
        )
        if source:
            q = q.filter(Ride.source == source)

        rows = q.order_by(Ride.ride_start_ts.desc()).limit(limit).all()

        margins = []
        trips_out = []
        for ride, person in rows:
            tm = calculate_trip_margin_from_orm(ride)
            margins.append(tm)
            trips_out.append({
                "ride_id": ride.ride_id,
                "date": ride.ride_start_ts.date().isoformat() if ride.ride_start_ts else None,
                "source": ride.source,
                "service_name": ride.service_name or "",
                "driver_name": person.full_name if person else "",
                "partner_paid": tm.partner_paid,
                "driver_pay": tm.driver_pay,
                "margin": tm.margin,
                "margin_pct": tm.margin_pct,
                "notes": tm.notes,
            })

        agg = aggregate_margins(margins)

        return JSONResponse({
            "from": start.isoformat(),
            "to": end.isoformat(),
            "ride_count": len(trips_out),
            "totals": {
                "total_partner_paid": agg["total_partner_paid"],
                "total_driver_pay": agg["total_driver_pay"],
                "total_margin": agg["total_margin"],
                "margin_pct": agg["margin_pct"],
            },
            "trips": trips_out,
            "by_route": agg["by_route"],
        })

    except Exception as exc:
        import traceback
        return JSONResponse({"error": str(exc), "detail": traceback.format_exc()}, status_code=500)


@router.get("/margin/routes")
def api_margin_routes(
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
    source: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """
    Per-route margin ranking — worst-margin routes listed first.

    Same date/source params as /margin/trips.
    Returns only the by_route aggregation + totals (no per-trip rows).
    Useful for the route-ranking widget on the dashboard.
    """
    try:
        from datetime import date, timedelta
        from sqlalchemy import cast, Date as SADate
        from backend.services.trip_margin import (
            calculate_trip_margin_from_orm,
            aggregate_margins,
        )

        today = date.today()
        start = date.fromisoformat(from_date) if from_date else today - timedelta(days=30)
        end = date.fromisoformat(to_date) if to_date else today

        q = (
            db.query(Ride)
            .filter(cast(Ride.ride_start_ts, SADate) >= start)
            .filter(cast(Ride.ride_start_ts, SADate) <= end)
        )
        if source:
            q = q.filter(Ride.source == source)

        rides = q.all()
        margins = [calculate_trip_margin_from_orm(r) for r in rides]
        agg = aggregate_margins(margins)

        return JSONResponse({
            "from": start.isoformat(),
            "to": end.isoformat(),
            "ride_count": agg["ride_count"],
            "totals": {
                "total_partner_paid": agg["total_partner_paid"],
                "total_driver_pay": agg["total_driver_pay"],
                "total_margin": agg["total_margin"],
                "margin_pct": agg["margin_pct"],
            },
            "by_route": agg["by_route"],
        })

    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Pricing v2 shadow report (S3) ──────────────────────────────────────────────

@router.get("/rate-shadow/latest")
def rate_shadow_latest(db: Session = Depends(get_db)):
    """Latest shadow-mode batch report: v1 vs v2 per ride, newest batch first.

    GET /api/data/rate-shadow/latest
    """
    from backend.db.models import RateShadowResult
    from backend.services.rate_engine_v2 import v2_mode

    try:
        latest_batch = (
            db.query(RateShadowResult.payroll_batch_id)
            .order_by(RateShadowResult.created_at.desc())
            .limit(1)
            .scalar()
        )
        if latest_batch is None:
            return JSONResponse({"mode": v2_mode(), "batch_id": None, "rows": []})

        rows = (
            db.query(RateShadowResult)
            .filter(RateShadowResult.payroll_batch_id == latest_batch)
            .order_by(RateShadowResult.agrees, RateShadowResult.id)
            .all()
        )
        return JSONResponse({
            "mode": v2_mode(),
            "batch_id": latest_batch,
            "total": len(rows),
            "resolved": sum(1 for r in rows if r.v2_tier != "none"),
            "refused": sum(1 for r in rows if r.v2_tier == "none"),
            "disagreements": sum(1 for r in rows if not r.agrees),
            "rows": [
                {
                    "ride_id": r.ride_id,
                    "service_name": r.service_name,
                    "miles": float(r.miles) if r.miles is not None else None,
                    "v1_rate": str(r.v1_rate),
                    "v1_source": r.v1_source,
                    "v2_rate": str(r.v2_rate),
                    "v2_tier": r.v2_tier,
                    "evidence": r.v2_evidence,
                    "agrees": r.agrees,
                }
                for r in rows
            ],
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Reliability tiers (S2 exception-queue policy) ─────────────────────────────

@router.get("/reliability/tiers")
def reliability_tiers(
    refresh: bool = Query(False, description="Force recompute (bypass 30-min cache)"),
    db: Session = Depends(get_db),
):
    """Fleet Trusted/Watch/Chronic tiers with evidence.

    GET /api/data/reliability/tiers[?refresh=true]

    Powers the exception-queue tier chips and the tier-policy preview.
    Drivers with no trip_notification history in the lookback window are
    omitted (they default to watch inside the monitor).
    """
    from backend.services import driver_reliability_tier as drt

    try:
        if refresh:
            drt.invalidate_cache()
        tiers = drt.compute_tiers(db)
        names = {
            p.person_id: p.full_name
            for p in db.query(Person).filter(Person.person_id.in_(list(tiers))).all()
        } if tiers else {}
        drivers = [
            {
                "person_id": t.person_id,
                "name": names.get(t.person_id, f"#{t.person_id}"),
                "tier": t.tier,
                "trips": t.trips,
                "nudges": t.nudges,
                "calls": t.calls,
                "ghosts": t.ghosts,
                "nudge_rate": t.nudge_rate,
                "reason": t.reason,
            }
            for t in sorted(
                tiers.values(),
                key=lambda t: ({"chronic": 0, "watch": 1, "trusted": 2}[t.tier], -t.nudge_rate),
            )
        ]
        counts = {"chronic": 0, "watch": 0, "trusted": 0}
        for d in drivers:
            counts[d["tier"]] += 1
        return JSONResponse({
            "policy_enabled": drt.tier_policy_enabled(),
            "counts": counts,
            "drivers": drivers,
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Driver Scorecard Drilldown (Phase 8) ──────────────────────────────────────

@router.get("/reliability/driver/{person_id}")
def driver_reliability_drilldown(
    person_id: int,
    week: Optional[str] = Query(None),
    windows: int = Query(12, ge=1, le=52),
    db: Session = Depends(get_db),
):
    """Per-driver scorecard drill-in.

    GET /api/data/reliability/driver/{person_id}[?week=YYYY-WW&windows=N]

    windows: how many prior weeks to include in weekly_history (default 12, max 52).

    Returns:
      - driver basic info (name, paycheck_codes)
      - current week tier + composite + axis breakdown
      - last 4 weeks of weekly composites (sparkline data)
      - recent significant events (empty array until override table lands)
        TODO: events when override table lands
    """
    from datetime import timedelta

    # ── Resolve target week ───────────────────────────────────────────────────
    if week is not None:
        try:
            week_start = _parse_iso_week(week)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
    else:
        week_start = _current_pt_week_start()

    # ── Driver must exist ─────────────────────────────────────────────────────
    person = db.query(Person).filter(Person.person_id == person_id).first()
    if not person:
        return JSONResponse({"error": "Driver not found"}, status_code=404)

    # ── Current week scorecard ────────────────────────────────────────────────
    current_sc = compute_driver_scorecard(person_id, week_start, db)
    current_dict = _scorecard_to_dict(current_sc)

    # Annotate each axis with its label and nominal weight (for display bars)
    axes_annotated = {}
    for axis_key, axis_data in current_dict["axes"].items():
        axes_annotated[axis_key] = {
            **axis_data,
            "label": AXIS_LABELS.get(axis_key, axis_key),
            "nominal_weight": AXIS_WEIGHTS.get(axis_key, 0.0),
        }

    # ── Last N weeks of composites (trend chart) ─────────────────────────────
    weekly_history: list[dict] = []
    for weeks_back in range(windows, 0, -1):
        hist_week_start = week_start - timedelta(weeks=weeks_back)
        hist_sc = compute_driver_scorecard(person_id, hist_week_start, db)
        hist_iso = f"{hist_week_start.isocalendar().year}-W{hist_week_start.isocalendar().week:02d}"
        weekly_history.append({
            "week_iso": hist_iso,
            "week_start": hist_week_start.isoformat(),
            "composite_score": hist_sc.composite_score,
            "tier": hist_sc.tier,
            "total_trips": hist_sc.total_trips,
        })
    # Append current week
    weekly_history.append({
        "week_iso": current_dict["week_iso"],
        "week_start": week_start.isoformat(),
        "composite_score": current_dict["composite_score"],
        "tier": current_dict["tier"],
        "total_trips": current_dict["total_trips"],
    })

    # ── Per-trip table for current week ──────────────────────────────────────
    from backend.db.models import TripNotification as TN

    week_end = week_start + timedelta(days=7)
    trip_rows = (
        db.query(TN)
        .filter(
            TN.person_id == person_id,
            TN.trip_date >= week_start,
            TN.trip_date < week_end,
        )
        .order_by(TN.trip_date, TN.accept_sms_at)
        .all()
    )

    def _iso(dt):
        return dt.isoformat() if dt is not None else None

    trips_this_week: list[dict] = [
        {
            "id": tn.id,
            "trip_date": tn.trip_date.isoformat() if tn.trip_date else None,
            "source": tn.source,
            "trip_ref": tn.trip_ref,
            "status": tn.trip_status,
            "pickup_time": tn.pickup_time,
            "accepted_at": _iso(tn.accepted_at),
            "started_at": _iso(tn.started_at),
            "arrived_at_pickup": _iso(tn.arrived_at_pickup),
            "completed_at": _iso(tn.completed_at),
            "accept_sms_at": _iso(tn.accept_sms_at),
            "escalated": (tn.accept_escalated_at is not None or tn.start_escalated_at is not None),
        }
        for tn in trip_rows
    ]

    # ── Recent events (stub — no override table yet) ──────────────────────────
    # TODO: events when override table lands — pull from driver_override or
    # scorecard_event table once it exists (Phase 9+).
    recent_events: list[dict] = []

    return JSONResponse({
        "driver": {
            "person_id": person.person_id,
            "name": person.full_name,
            "paycheck_code": person.paycheck_code,
            "paycheck_code_maz": person.paycheck_code_maz,
            "active": person.active,
        },
        "current_week": {
            **current_dict,
            "axes": axes_annotated,
        },
        "weekly_history": weekly_history,
        "trips_this_week": trips_this_week,
        "recent_events": recent_events,
    })


# ── Driver Certification (S7) ─────────────────────────────────────────────────

@router.get("/certification/status")
def certification_status(db: Session = Depends(get_db)):
    """Fleet certification status for active drivers.

    GET /api/data/certification/status

    Powers the onboarding admin view's Certification column — surfaces who
    is certified on the current COURSE_VERSION, who has never certified, and
    who needs recertification (certified before, but on a stale course
    version). Read-only; session-authed like the rest of /api/data/* (global
    AuthMiddleware), no additional role restriction — mirrors reliability/tiers.
    """
    from backend.db.models import DriverCertification
    from backend.services import certification as cert_service

    people = (
        db.query(Person)
        .filter(Person.active.is_(True))
        .filter(Person.status == "active")
        .all()
    )
    person_ids = [p.person_id for p in people]

    rows = (
        db.query(DriverCertification)
        .filter(DriverCertification.person_id.in_(person_ids))
        .order_by(
            DriverCertification.person_id,
            DriverCertification.certified_at.desc(),
            DriverCertification.cert_id.desc(),
        )
        .all()
        if person_ids else []
    )

    latest_by_person: dict[int, DriverCertification] = {}
    for row in rows:
        latest_by_person.setdefault(row.person_id, row)

    drivers = []
    for p in people:
        latest = latest_by_person.get(p.person_id)
        certified = bool(latest and latest.course_version == cert_service.COURSE_VERSION)
        recert_needed = bool(latest and latest.course_version != cert_service.COURSE_VERSION)
        drivers.append({
            "person_id": p.person_id,
            "name": p.full_name,
            "certified": certified,
            "course_version": latest.course_version if latest else None,
            "certified_at": latest.certified_at.isoformat() if latest else None,
            "needs_recert": recert_needed,
        })

    drivers.sort(key=lambda d: (d["certified"], (d["name"] or "").lower()))
    return JSONResponse({"drivers": drivers})
