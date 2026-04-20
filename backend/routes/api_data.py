"""
Dedicated JSON API endpoints for the Next.js frontend.
All routes under /api/data/* always return JSON.
No content negotiation needed.
"""

import os
from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, Date, extract

from backend.db import get_db
from backend.db.models import Person, Ride, PayrollBatch, DriverBalance, ActivityLog, BatchCorrectionLog
from backend.routes.dashboard import _build_stats, _build_ytd_weeks
from backend.routes.summary import _build_summary
from backend.routes.analytics import _build_analytics
from backend.routes.insights import _build_snapshot as _insights_snapshot
from backend.routes.intelligence import (
    _build_alerts,
    _build_driver_performance,
    _map_snapshot,
)
from backend.routes.pareto import _build_pareto, _get_companies as _pareto_companies
from backend.routes.rides import _build_rides_rows
from backend.services import everdriven_service
from backend.services.everdriven_service import EverDrivenAuthError

router = APIRouter(prefix="/api/data", tags=["api-json"])


def _display_company(raw: str) -> str:
    """Map raw DB company name to display name."""
    co = (raw or "").lower()
    if "ever" in co:
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
        batches = db.query(PayrollBatch).order_by(PayrollBatch.week_start.desc().nullslast()).limit(100).all()

        batch_ids = [b.payroll_batch_id for b in batches]

        # Aggregate financials per batch in one query
        agg_rows = (
            db.query(
                Ride.payroll_batch_id,
                func.count(Ride.ride_id).label("rides"),
                func.sum(Ride.gross_pay).label("gross_paid"),
                func.sum(Ride.net_pay).label("partner_paid"),
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

        # Compute sequential week number per source (1st batch = Week 1, 2nd = Week 2, ...)
        from collections import OrderedDict, defaultdict
        _src_batches: dict = defaultdict(list)
        for b in batches:
            _src_batches[b.source or ""].append(b)
        batch_week_num: dict[int, int] = {}
        for _src, _sbs in _src_batches.items():
            _sorted = sorted(_sbs, key=lambda x: x.period_start or __import__('datetime').date(2000, 1, 1))
            for _i, _sb in enumerate(_sorted, 1):
                batch_week_num[_sb.payroll_batch_id] = _i

        # Group batches by week_start so FA+ED for same week are combined
        from backend.utils.week_label import week_label as _wl
        weeks: dict = OrderedDict()
        for b in batches:
            ws = b.week_start or b.period_start
            week_key = ws.isoformat() if ws else b.batch_ref or str(b.payroll_batch_id)

            a = agg.get(b.payroll_batch_id)
            rides = int(a.rides) if a else 0
            gross_paid = float(a.gross_paid or 0) if a else 0.0
            partner_paid = float(a.partner_paid or 0) if a else 0.0
            driver_cost = float(a.driver_cost or 0) if a else 0.0

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
                    "week_label": f"Week {batch_week_num.get(b.payroll_batch_id, '')}",
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
            overhead = w["gross_paid"] - w["partner_paid"]
            w["profit"] = round(w["partner_paid"] - w["driver_cost"] - overhead, 2)
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
    """Sequential week number for this batch within its source."""
    src = b.source or ""
    count = (
        db.query(func.count(PayrollBatch.payroll_batch_id))
        .filter(
            PayrollBatch.source == src,
            PayrollBatch.period_start <= b.period_start,
        )
        .scalar()
    ) or 1
    return int(count)


@router.get("/payroll-history/{batch_id}")
def api_payroll_batch_detail(batch_id: int, db: Session = Depends(get_db)):
    try:
        b = db.query(PayrollBatch).filter(PayrollBatch.payroll_batch_id == batch_id).first()
        if not b:
            return JSONResponse({"error": "Not found"}, status_code=404)
        rides = db.query(Ride).filter(Ride.payroll_batch_id == batch_id).all()
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
                "deduction": float(r.deduction or 0),
                "gross_pay": float(r.gross_pay or 0),
                "margin": round(float(r.net_pay or 0) - float(r.z_rate or 0), 2),
            })

        total_net = round(sum(r["net_pay"] for r in ride_list), 2)
        total_z_rate = round(sum(r["z_rate"] for r in ride_list), 2)
        total_deduction = round(sum(r["deduction"] for r in ride_list), 2)
        total_miles = round(sum(r["miles"] for r in ride_list), 1)

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
                "rides": len(ride_list),
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

        data = _build_summary(db, source=source_filter, batch_id=batch_id, auto_save=False)
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
        if batches and batches[0].period_start and batches[0].period_end:
            from backend.utils.week_label import week_label as _wl
            wl = _wl(batches[0].period_start, batches[0].period_end)

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
            if "ever" not in co:
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
                    "company": _display_company(r.get("company", "")),
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
        # Get actual company names that have ride data
        company_rows = (
            db.query(PayrollBatch.company_name)
            .join(Ride, Ride.payroll_batch_id == PayrollBatch.payroll_batch_id)
            .distinct()
            .all()
        )
        active_companies = [r[0] for r in company_rows]

        # Build one snapshot per active company
        snapshots = []
        raw_fa = None
        raw_ed = None
        for co in active_companies:
            snap_raw = _insights_snapshot(db, company=co)
            snap = _map_snapshot(snap_raw)
            co_lower = co.lower()
            display = "FirstAlt" if ("acumen" in co_lower or "fa" in co_lower or "first" in co_lower) else "EverDriven"
            snapshots.append({
                "company": display,
                "revenue": snap.get("revenue", 0),
                "cost": snap.get("cost", 0),
                "profit": snap.get("profit", 0),
                "margin": snap.get("margin_pct", 0),
                "rides": snap.get("rides", 0),
                "drivers": snap.get("active_drivers", 0),
            })
            if "ever" in co_lower or "ed" in co_lower:
                raw_ed = snap_raw
            else:
                raw_fa = snap_raw

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

        return JSONResponse({
            "snapshots": snapshots,
            "alerts": alerts_out,
            "top_drivers": top_drivers_out,
            "inactive_drivers": inactive_out,
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


# ── Rides ────────────────────────────────────────────────────────────────────

@router.get("/rides")
def api_rides(
    person_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    try:
        rows, total_net, payweek = _build_rides_rows(db, person_id=person_id)
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
    """Natural-language dispatch agent. Reads only; proposes actions for user confirmation."""
    from backend.services.dispatch_agent import run_agent

    try:
        body = await request.json()
        message = (body.get("message") or "").strip()
        history = body.get("history") or []
        if not message:
            return JSONResponse({"error": "message required"}, status_code=400)

        result = run_agent(db, message, history=history)
        return JSONResponse(result)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Pareto ───────────────────────────────────────────────────────────────────

@router.get("/pareto")
def api_pareto(
    company: str | None = Query(None),
    db: Session = Depends(get_db),
):
    try:
        companies = _pareto_companies(db)
        data = _build_pareto(db, company=company)

        # Map driver_rows to frontend expected shape
        drivers = []
        for r in data.get("driver_rows", []):
            drivers.append({
                "rank": r.get("rank"),
                "driver": r.get("driver", ""),
                "rides": r.get("rides", 0),
                "profit": r.get("profit", 0),
                "share": r.get("individual_pct", 0),
                "cumulative": r.get("cumulative_pct", 0),
                "is_cutoff": r.get("is_cutoff", False),
            })

        least_profitable = [
            {"driver": r.get("driver", ""), "rides": r.get("rides", 0), "profit": r.get("profit", 0)}
            for r in data.get("least_profitable_rows", [])
        ]

        services_by_volume = [
            {
                "service": r.get("service", ""),
                "rides": r.get("ride_count", 0),
                "revenue": r.get("profit", 0),
            }
            for r in data.get("service_by_volume", [])
        ]

        services_by_profit = []
        for r in data.get("service_by_profit", []):
            profit = r.get("profit", 0)
            rides = r.get("ride_count", 0)
            margin = round((profit / rides) * 100, 1) if rides else 0.0
            services_by_profit.append({
                "service": r.get("service", ""),
                "profit": profit,
                "margin": margin,
            })

        periods = [
            {
                "period": f"{r.get('period_start', '')} – {r.get('period_end', '')}",
                "rides": r.get("rides", 0),
                "profit": r.get("profit", 0),
            }
            for r in data.get("period_rows", [])
        ]

        return JSONResponse({
            "companies": companies,
            "selected_company": company,
            "drivers": drivers,
            "least_profitable": least_profitable,
            "services_by_volume": services_by_volume,
            "services_by_profit": services_by_profit,
            "periods": periods,
            "driver_summary": data.get("driver_summary", {}),
            "service_summary": data.get("service_summary", {}),
            "period_summary": data.get("period_summary", {}),
        })
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

        # Aggregate ride stats per service: avg miles, avg net_pay, latest period
        ride_stats_q = (
            db.query(
                Ride.z_rate_service_id,
                func.avg(Ride.miles).label("avg_miles"),
                func.avg(Ride.net_pay).label("avg_net_pay"),
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
                "avg_miles": round(float(r.avg_miles or 0), 1),
                "avg_net_pay": round(float(r.avg_net_pay or 0), 2),
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
                "avg_miles": stats.get("avg_miles", 0),
                "avg_net_pay": stats.get("avg_net_pay", 0),
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


@router.post("/rides")
async def api_create_ride(request: Request, db: Session = Depends(get_db)):
    """Manually add a ride to the system. Creates a manual batch if needed."""
    import uuid
    from datetime import datetime, date as date_type
    from decimal import Decimal

    body = await request.json()

    service_name = body.get("service_name", "").strip()
    ride_date_str = body.get("date", "")
    source = body.get("source", "firstalt").lower()  # "firstalt" or "maz"
    person_id = body.get("person_id")  # optional — can be unassigned
    driver_pay = Decimal(str(body.get("driver_pay", 0)))
    miles = Decimal(str(body.get("miles", 0)))
    pickup_time = body.get("pickup_time", "")
    notes = body.get("notes", "")

    if not service_name or not ride_date_str:
        return JSONResponse({"error": "service_name and date are required"}, status_code=400)

    try:
        ride_date = date_type.fromisoformat(ride_date_str)
    except ValueError:
        return JSONResponse({"error": "Invalid date format, expected YYYY-MM-DD"}, status_code=400)

    company_name = "FirstAlt" if source == "firstalt" else "EverDriven"
    batch_ref = f"manual-{ride_date_str}-{source}"

    # Find or create a manual batch for this date + source
    batch = db.query(PayrollBatch).filter(
        PayrollBatch.batch_ref == batch_ref,
        PayrollBatch.source == source,
    ).first()

    if not batch:
        batch = PayrollBatch(
            source=source,
            company_name=company_name,
            batch_ref=batch_ref,
            period_start=ride_date,
            period_end=ride_date,
            week_start=ride_date,
            week_end=ride_date,
            notes=f"Manual rides — {ride_date_str}",
            status="uploaded",
        )
        db.add(batch)
        db.flush()

    UNASSIGNED_PERSON_ID = 227
    if not person_id:
        person_id = UNASSIGNED_PERSON_ID

    # Build a unique source_ref
    source_ref = f"manual-{uuid.uuid4().hex[:12]}"

    ride_ts = None
    if pickup_time:
        try:
            ride_ts = datetime.fromisoformat(f"{ride_date_str}T{pickup_time}:00")
        except Exception:
            ride_ts = datetime(ride_date.year, ride_date.month, ride_date.day, 8, 0, 0)
    else:
        ride_ts = datetime(ride_date.year, ride_date.month, ride_date.day, 8, 0, 0)

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
        net_pay=driver_pay,
        gross_pay=driver_pay,
        miles=miles,
        deduction=Decimal("0"),
        spiff=Decimal("0"),
    )
    db.add(ride)
    db.commit()
    db.refresh(ride)

    person = db.query(Person).filter(Person.person_id == int(person_id)).first()
    return JSONResponse({
        "ok": True,
        "ride_id": ride.ride_id,
        "driver": person.full_name if person else "",
        "service_name": ride.service_name,
        "date": ride_date_str,
        "driver_pay": float(ride.net_pay),
        "batch_ref": batch_ref,
    })


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
