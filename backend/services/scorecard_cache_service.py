"""
backend/services/scorecard_cache_service.py
============================================
Write and read per-driver weekly scorecard snapshots from scorecard_cache.

Public API
----------
upsert_cache(scorecard, week_iso, db, source='cron') -> None
    Persist one DriverScorecard snapshot. UPSERT on (person_id, week_num, year).
    Called by scorecard_cron after computing each driver's score.

get_prior_week_composites(person_ids, week_start, db) -> dict[int, float | None]
    Return the previous week's composite_score per driver from cache.
    Used by compute_all_active_drivers() instead of re-running the full pipeline.

get_rolling_30d(person_id, week_start, db) -> dict with avg fields
    Return 30-day rolling average (last 4 ISO weeks) from cache.
    Used by the /api/data/reliability?window=30d endpoint.

get_weekly_trend(person_id, num_weeks, db) -> list[CacheTrendEntry]
    Return the last num_weeks snapshots for a single driver.
    Used by the public /scorecard/[token] page and the drill-in page.

get_fleet_trend(week_start, db) -> dict[int, WowDelta]
    Return last 2 weeks of cache data for every driver so the reliability
    table can show the Δ column without re-computing scores.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import text

from backend.services.driver_scorecard import DriverScorecard

logger = logging.getLogger("zpay.scorecard_cache")

UTC = timezone.utc


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CacheTrendEntry:
    week_iso: str
    week_num: int
    year: int
    composite_score: Optional[float]
    self_serve_pct: Optional[float]
    on_time_pct: Optional[float]
    escalation_count: Optional[int]
    total_trips: int


@dataclass(frozen=True)
class WowDelta:
    """Week-over-week escalation and composite delta for one driver."""
    person_id: int
    current_escalations: Optional[int]
    prior_escalations: Optional[int]
    current_composite: Optional[float]
    prior_composite: Optional[float]

    @property
    def escalation_delta(self) -> Optional[int]:
        """Positive = MORE escalations (worse). Negative = fewer (better)."""
        if self.current_escalations is None or self.prior_escalations is None:
            return None
        return self.current_escalations - self.prior_escalations

    @property
    def composite_delta(self) -> Optional[float]:
        if self.current_composite is None or self.prior_composite is None:
            return None
        return round(self.current_composite - self.prior_composite, 2)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _iso_to_week_parts(week_iso: str) -> tuple[int, int]:
    """Parse 'YYYY-Www' -> (year, week_num)."""
    parts = week_iso.split("-W")
    if len(parts) != 2:
        raise ValueError(f"Invalid week_iso: {week_iso!r}")
    return int(parts[0]), int(parts[1])


def _week_isos_before(week_start: date, n: int) -> list[str]:
    """Return the n ISO week strings for the weeks ending just before week_start.

    week_start is a Monday. Returns e.g. ['2026-W17', '2026-W16', ...] newest-first.
    """
    result = []
    cursor = week_start
    for _ in range(n):
        cursor -= timedelta(days=7)
        iso = cursor.isocalendar()
        result.append(f"{iso.year}-W{iso.week:02d}")
    return result


# ── Public API ────────────────────────────────────────────────────────────────

def upsert_cache(
    scorecard: DriverScorecard,
    week_iso: str,
    db: Session,
    *,
    source: str = "cron",
) -> None:
    """Persist one DriverScorecard snapshot. UPSERT on (person_id, week_num, year).

    Safe to call multiple times — second call in the same week updates the row.
    """
    year, week_num = _iso_to_week_parts(week_iso)

    on_time_ax = scorecard.axes.get("on_time_pickup_arrival")
    on_time_pct: Optional[float] = None
    if on_time_ax and on_time_ax.available and on_time_ax.sample_size > 0:
        on_time_pct = round(on_time_ax.raw_value * 100, 2)

    composite = float(scorecard.composite_score) if scorecard.composite_score is not None else None
    self_serve = float(scorecard.self_serve_pct) if scorecard.self_serve_pct is not None else None

    db.execute(
        text("""
            INSERT INTO scorecard_cache
                (person_id, week_num, year, week_iso,
                 self_serve_pct, on_time_pct, escalation_count,
                 composite_score, total_trips, computed_at, source)
            VALUES
                (:pid, :week_num, :year, :week_iso,
                 :self_serve_pct, :on_time_pct, :escalation_count,
                 :composite_score, :total_trips, NOW(), :source)
            ON CONFLICT (person_id, week_num, year)
            DO UPDATE SET
                self_serve_pct   = EXCLUDED.self_serve_pct,
                on_time_pct      = EXCLUDED.on_time_pct,
                escalation_count = EXCLUDED.escalation_count,
                composite_score  = EXCLUDED.composite_score,
                total_trips      = EXCLUDED.total_trips,
                computed_at      = NOW(),
                source           = EXCLUDED.source
        """),
        {
            "pid":              scorecard.person_id,
            "week_num":         week_num,
            "year":             year,
            "week_iso":         week_iso,
            "self_serve_pct":   self_serve,
            "on_time_pct":      on_time_pct,
            "escalation_count": scorecard.escalation_count,
            "composite_score":  composite,
            "total_trips":      scorecard.total_trips,
            "source":           source,
        },
    )
    db.commit()
    logger.debug(
        "[scorecard_cache] upsert person_id=%d week=%s composite=%.1f source=%s",
        scorecard.person_id, week_iso, composite or 0.0, source,
    )


def get_prior_week_composites(
    person_ids: list[int],
    week_start: date,
    db: Session,
) -> dict[int, Optional[float]]:
    """Return the previous week's composite_score per driver from cache.

    Falls back to None (no delta) for any driver not in cache yet.
    """
    if not person_ids:
        return {}
    prior_monday = week_start - timedelta(days=7)
    iso = prior_monday.isocalendar()
    prior_year = iso.year
    prior_week = iso.week

    rows = db.execute(
        text("""
            SELECT person_id, composite_score
            FROM scorecard_cache
            WHERE year = :year AND week_num = :week_num
              AND person_id = ANY(:pids)
        """),
        {"year": prior_year, "week_num": prior_week, "pids": list(person_ids)},
    ).mappings().all()

    result: dict[int, Optional[float]] = {pid: None for pid in person_ids}
    for row in rows:
        cs = row["composite_score"]
        result[row["person_id"]] = float(cs) if cs is not None else None
    return result


def get_rolling_30d(
    person_id: int,
    week_start: date,
    db: Session,
) -> dict:
    """Return 30-day rolling average for a single driver (last 4 ISO weeks).

    Returns a dict with:
        self_serve_pct   float | None — avg of last 4 weeks (NULLs excluded)
        on_time_pct      float | None
        escalation_count float | None — avg escalations per week
        composite_score  float | None
        total_trips      int   — total trips across the 4 weeks
        weeks_found      int   — how many cache rows were available
    """
    prior_isos = _week_isos_before(week_start, 4)
    rows = db.execute(
        text("""
            SELECT self_serve_pct, on_time_pct, escalation_count,
                   composite_score, total_trips
            FROM scorecard_cache
            WHERE person_id = :pid
              AND week_iso = ANY(:isos)
        """),
        {"pid": person_id, "isos": prior_isos},
    ).mappings().all()

    if not rows:
        return {
            "self_serve_pct": None, "on_time_pct": None,
            "escalation_count": None, "composite_score": None,
            "total_trips": 0, "weeks_found": 0,
        }

    def _avg(key: str) -> Optional[float]:
        vals = [float(r[key]) for r in rows if r[key] is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    return {
        "self_serve_pct":   _avg("self_serve_pct"),
        "on_time_pct":      _avg("on_time_pct"),
        "escalation_count": _avg("escalation_count"),
        "composite_score":  _avg("composite_score"),
        "total_trips":      sum(int(r["total_trips"]) for r in rows),
        "weeks_found":      len(rows),
    }


def get_weekly_trend(
    person_id: int,
    db: Session,
    *,
    num_weeks: int = 8,
) -> list[CacheTrendEntry]:
    """Return last num_weeks cache rows for a driver, newest-first.

    Used by the public /scorecard/[token] page and the drill-in history page.
    Returns an empty list if no cache rows exist yet.
    """
    rows = db.execute(
        text("""
            SELECT week_iso, week_num, year, composite_score,
                   self_serve_pct, on_time_pct, escalation_count, total_trips
            FROM scorecard_cache
            WHERE person_id = :pid
            ORDER BY year DESC, week_num DESC
            LIMIT :n
        """),
        {"pid": person_id, "n": num_weeks},
    ).mappings().all()

    return [
        CacheTrendEntry(
            week_iso=r["week_iso"],
            week_num=r["week_num"],
            year=r["year"],
            composite_score=float(r["composite_score"]) if r["composite_score"] is not None else None,
            self_serve_pct=float(r["self_serve_pct"]) if r["self_serve_pct"] is not None else None,
            on_time_pct=float(r["on_time_pct"]) if r["on_time_pct"] is not None else None,
            escalation_count=int(r["escalation_count"]) if r["escalation_count"] is not None else None,
            total_trips=int(r["total_trips"]),
        )
        for r in rows
    ]


def get_fleet_trend(
    week_start: date,
    db: Session,
) -> dict[int, WowDelta]:
    """Return WowDelta for every driver who has cache data in current or prior week.

    Current week = week_start. Prior = week_start - 7 days.
    Used by the /api/data/reliability endpoint to populate the Δ column.
    """
    current_iso_parts = week_start.isocalendar()
    current_year = current_iso_parts.year
    current_week = current_iso_parts.week

    prior_monday = week_start - timedelta(days=7)
    prior_iso_parts = prior_monday.isocalendar()
    prior_year = prior_iso_parts.year
    prior_week = prior_iso_parts.week

    rows = db.execute(
        text("""
            SELECT person_id, year, week_num, escalation_count, composite_score
            FROM scorecard_cache
            WHERE (year = :cy AND week_num = :cw)
               OR (year = :py AND week_num = :pw)
        """),
        {
            "cy": current_year, "cw": current_week,
            "py": prior_year,   "pw": prior_week,
        },
    ).mappings().all()

    current_map: dict[int, dict] = {}
    prior_map: dict[int, dict] = {}
    for row in rows:
        pid = row["person_id"]
        if row["year"] == current_year and row["week_num"] == current_week:
            current_map[pid] = row
        else:
            prior_map[pid] = row

    all_pids = set(current_map) | set(prior_map)
    result: dict[int, WowDelta] = {}
    for pid in all_pids:
        cur = current_map.get(pid)
        pri = prior_map.get(pid)
        result[pid] = WowDelta(
            person_id=pid,
            current_escalations=int(cur["escalation_count"]) if cur and cur["escalation_count"] is not None else None,
            prior_escalations=int(pri["escalation_count"]) if pri and pri["escalation_count"] is not None else None,
            current_composite=float(cur["composite_score"]) if cur and cur["composite_score"] is not None else None,
            prior_composite=float(pri["composite_score"]) if pri and pri["composite_score"] is not None else None,
        )
    return result
