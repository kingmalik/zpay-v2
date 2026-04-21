"""
Z-Pay health monitor admin endpoints.

Routes (all under /api/data/health):
    GET  /status           — dashboard JSON: per-check status + alerts
    GET  /alerts           — recent alerts (paginated)
    POST /pause/{check}    — mute a check for N hours
    POST /resume/{check}   — clear mute
    POST /ack/{alert_id}   — acknowledge an alert
    POST /run/{check}      — fire a check on demand (admin)
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from backend.db import SessionLocal
from backend.services import health_monitor

router = APIRouter(prefix="/api/data/health", tags=["health"])


@router.get("/status")
def health_status() -> JSONResponse:
    with SessionLocal() as db:
        checks = db.execute(
            text("""
                SELECT check_name, status, last_checked_at, last_ok_at,
                       consecutive_failures, latency_ms, detail, enabled, muted_until
                FROM health_check
                ORDER BY check_name
            """)
        ).fetchall()
        open_alerts_count = db.execute(
            text("SELECT COUNT(*) FROM health_alert WHERE resolved_at IS NULL")
        ).scalar() or 0

    rows = []
    any_red = False
    any_yellow = False
    for row in checks:
        status = row[1]
        if status == "red":
            any_red = True
        elif status == "yellow":
            any_yellow = True
        rows.append({
            "name": row[0],
            "status": status,
            "last_checked_at": row[2].isoformat() if row[2] else None,
            "last_ok_at": row[3].isoformat() if row[3] else None,
            "consecutive_failures": int(row[4] or 0),
            "latency_ms": int(row[5] or 0),
            "detail": row[6] if isinstance(row[6], dict) else (json.loads(row[6]) if row[6] else {}),
            "enabled": bool(row[7]),
            "muted_until": row[8].isoformat() if row[8] else None,
        })

    overall = "red" if any_red else "yellow" if any_yellow else ("green" if rows else "unknown")
    return JSONResponse({
        "overall": overall,
        "checks": rows,
        "open_alerts": int(open_alerts_count),
        "scheduler": health_monitor.scheduler_status(),
        "server_time": datetime.now(timezone.utc).isoformat(),
    })


@router.get("/alerts")
def health_alerts(
    limit: int = Query(50, ge=1, le=500),
    only_open: bool = Query(False),
) -> JSONResponse:
    with SessionLocal() as db:
        where = "WHERE resolved_at IS NULL" if only_open else ""
        rows = db.execute(
            text(f"""
                SELECT alert_id, check_name, severity, message, created_at,
                       resolved_at, acked_at, notified
                FROM health_alert
                {where}
                ORDER BY created_at DESC
                LIMIT :lim
            """),
            {"lim": limit},
        ).fetchall()

    out = [{
        "alert_id": int(r[0]),
        "check_name": r[1],
        "severity": r[2],
        "message": r[3],
        "created_at": r[4].isoformat() if r[4] else None,
        "resolved_at": r[5].isoformat() if r[5] else None,
        "acked_at": r[6].isoformat() if r[6] else None,
        "notified": r[7] if isinstance(r[7], list) else (json.loads(r[7]) if r[7] else []),
    } for r in rows]
    return JSONResponse({"alerts": out})


@router.post("/pause/{check_name}")
def pause_check(check_name: str, hours: int = Query(4, ge=1, le=168)) -> JSONResponse:
    muted_until = datetime.now(timezone.utc) + timedelta(hours=hours)
    with SessionLocal() as db:
        db.execute(
            text("""
                INSERT INTO health_check (check_name, muted_until, enabled)
                VALUES (:n, :u, TRUE)
                ON CONFLICT (check_name) DO UPDATE SET muted_until = EXCLUDED.muted_until
            """),
            {"n": check_name, "u": muted_until},
        )
        db.commit()
    return JSONResponse({"ok": True, "check_name": check_name, "muted_until": muted_until.isoformat()})


@router.post("/resume/{check_name}")
def resume_check(check_name: str) -> JSONResponse:
    with SessionLocal() as db:
        db.execute(
            text("UPDATE health_check SET muted_until = NULL WHERE check_name = :n"),
            {"n": check_name},
        )
        db.commit()
    return JSONResponse({"ok": True, "check_name": check_name})


@router.post("/ack/{alert_id}")
def ack_alert(alert_id: int) -> JSONResponse:
    with SessionLocal() as db:
        res = db.execute(
            text("""
                UPDATE health_alert
                SET acked_at = NOW()
                WHERE alert_id = :id AND acked_at IS NULL
                RETURNING alert_id
            """),
            {"id": alert_id},
        ).first()
        db.commit()
    if not res:
        raise HTTPException(status_code=404, detail="alert not found or already acked")
    return JSONResponse({"ok": True, "alert_id": alert_id})


@router.post("/run/{check_name}")
def run_check_now(check_name: str) -> JSONResponse:
    match = next((c for c in health_monitor.CHECKS if c[0] == check_name), None)
    if not match:
        raise HTTPException(status_code=404, detail=f"unknown check: {check_name}")
    name, fn, _, catastrophic = match
    try:
        result = fn()
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": str(e)[:300]},
        )
    health_monitor._upsert_check_result(name, result)
    return JSONResponse({
        "ok": True,
        "name": name,
        "status": result.status,
        "latency_ms": result.latency_ms,
        "detail": result.detail,
    })


@router.post("/digest")
def run_digest_now() -> JSONResponse:
    try:
        health_monitor.run_daily_digest()
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)[:300]})
