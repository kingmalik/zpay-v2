"""
Backfill scheduled_dropoff on trip_notification
================================================
Populates the ``scheduled_dropoff`` column (added via migration zx3y4z5a6b7c)
for historical TripNotification rows that pre-date the column.

Coverage
--------
- EverDriven trips: fetches lastDropOff.dueTimeTLT from the EverDriven runsV2
  API for each unique trip_date in the backfill window, then matches by keyValue
  (trip_notification.trip_ref) and writes scheduled_dropoff.
- FirstAlt trips: no scheduled dropoff is available from the FA API.
  FA rows are left with scheduled_dropoff=NULL — this is correct behaviour.

Idempotent
----------
Only rows where scheduled_dropoff IS NULL are touched.  Safe to re-run.  If
a row already has scheduled_dropoff set it is skipped silently.

Backfill window
---------------
Defaults to the last 90 days.  Set BACKFILL_DAYS=N to override.
Set BACKFILL_DRY_RUN=1 to print what would happen without writing.

Usage
-----
  cd /path/to/zpay-v2-fresh
  DATABASE_URL="postgresql://..." python -m backend.scripts.backfill_scheduled_dropoff

DO NOT run this script automatically or from CI.
Malik runs it manually once after deploying migration zx3y4z5a6b7c.
"""

from __future__ import annotations

import logging
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# ── Path bootstrap ────────────────────────────────────────────────────────────
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
)
logger = logging.getLogger("backfill_scheduled_dropoff")

PT = ZoneInfo("America/Los_Angeles")
UTC = timezone.utc

DRY_RUN = os.environ.get("BACKFILL_DRY_RUN", "0") == "1"
BACKFILL_DAYS = int(os.environ.get("BACKFILL_DAYS", "90"))


# ── Time parsing (mirrors trip_monitor._parse_pickup_time logic) ──────────────

def _parse_dropoff_str(dropoff_str: str, trip_date: date) -> datetime | None:
    """Parse EverDriven dueTimeTLT into a UTC-aware datetime.

    ED returns either "HH:MM" or "YYYY-MM-DDTHH:MM" local time.
    Mirrors the same logic as trip_monitor._parse_pickup_time.
    """
    if not dropoff_str:
        return None
    try:
        if len(dropoff_str) <= 5 and ":" in dropoff_str:
            h, m = dropoff_str.split(":")
            local = datetime(trip_date.year, trip_date.month, trip_date.day,
                             int(h), int(m), tzinfo=PT)
            return local.astimezone(UTC)
        if "T" in dropoff_str:
            dt = datetime.fromisoformat(dropoff_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                local = datetime(trip_date.year, trip_date.month, trip_date.day,
                                 dt.hour, dt.minute, tzinfo=PT)
                return local.astimezone(UTC)
            return dt.astimezone(UTC)
    except (ValueError, TypeError) as exc:
        logger.warning("Could not parse dropoff_str=%r date=%s: %s", dropoff_str, trip_date, exc)
    return None


# ── Main backfill logic ───────────────────────────────────────────────────────

def run_backfill(db_url: str) -> None:
    engine = create_engine(db_url, echo=False)
    Session = sessionmaker(bind=engine)

    today = date.today()
    window_start = today - timedelta(days=BACKFILL_DAYS)
    logger.info(
        "Backfill window: %s → %s (%d days)  dry_run=%s",
        window_start, today, BACKFILL_DAYS, DRY_RUN,
    )

    # ── Step 1: Find all EverDriven rows that need backfilling ───────────────
    with Session() as db:
        rows = db.execute(
            text("""
                SELECT id, trip_ref, trip_date
                FROM trip_notification
                WHERE source = 'everdriven'
                  AND scheduled_dropoff IS NULL
                  AND trip_date >= :window_start
                  AND trip_date <= :today
                ORDER BY trip_date ASC
            """),
            {"window_start": window_start, "today": today},
        ).fetchall()

    if not rows:
        logger.info("No EverDriven rows with NULL scheduled_dropoff in window. Nothing to do.")
        return

    logger.info("Found %d EverDriven rows to attempt backfill.", len(rows))

    # Group by trip_date so we make one API call per day
    by_date: dict[date, list[tuple[int, str]]] = defaultdict(list)
    for notif_id, trip_ref, trip_date_raw in rows:
        td = trip_date_raw if isinstance(trip_date_raw, date) else trip_date_raw.date()
        by_date[td].append((notif_id, trip_ref))

    # ── Step 2: Fetch ED runs per day and map keyValue → lastDropOff ─────────
    from backend.services import everdriven_service  # lazy import — needs env vars

    total_updated = 0
    total_skipped_no_match = 0
    total_skipped_no_dropoff = 0

    for trip_date, notif_list in sorted(by_date.items()):
        logger.info(
            "  Fetching EverDriven runs for %s (%d rows to match)…",
            trip_date, len(notif_list),
        )
        try:
            ed_runs = everdriven_service.get_runs(trip_date)
        except Exception as exc:
            logger.error("  ED API error for %s: %s — skipping date", trip_date, exc)
            continue

        # Build key_value → lastDropOff lookup
        dropoff_map: dict[str, str] = {}
        for run in ed_runs:
            key = run.get("keyValue") or ""
            last_dropoff = run.get("lastDropOff") or ""
            if key and last_dropoff:
                dropoff_map[key] = last_dropoff

        logger.info(
            "  ED returned %d runs, %d with lastDropOff set",
            len(ed_runs), len(dropoff_map),
        )

        # ── Step 3: Write matches to DB ──────────────────────────────────────
        with Session() as db:
            for notif_id, trip_ref in notif_list:
                dropoff_str = dropoff_map.get(trip_ref)
                if not dropoff_str:
                    logger.debug(
                        "    No match for notif_id=%d trip_ref=%s on %s",
                        notif_id, trip_ref, trip_date,
                    )
                    total_skipped_no_match += 1
                    continue

                scheduled_dropoff_utc = _parse_dropoff_str(dropoff_str, trip_date)
                if not scheduled_dropoff_utc:
                    logger.warning(
                        "    Could not parse lastDropOff=%r for notif_id=%d — skipping",
                        dropoff_str, notif_id,
                    )
                    total_skipped_no_dropoff += 1
                    continue

                if DRY_RUN:
                    logger.info(
                        "    [DRY RUN] Would update notif_id=%d trip_ref=%s → %s",
                        notif_id, trip_ref, scheduled_dropoff_utc.isoformat(),
                    )
                    total_updated += 1
                    continue

                db.execute(
                    text("""
                        UPDATE trip_notification
                        SET scheduled_dropoff = :ts
                        WHERE id = :notif_id
                          AND scheduled_dropoff IS NULL
                    """),
                    {"ts": scheduled_dropoff_utc, "notif_id": notif_id},
                )
                db.commit()
                logger.debug(
                    "    Updated notif_id=%d trip_ref=%s → %s",
                    notif_id, trip_ref, scheduled_dropoff_utc.isoformat(),
                )
                total_updated += 1

    logger.info(
        "Backfill complete. updated=%d  skipped_no_match=%d  skipped_no_dropoff=%d",
        total_updated, total_skipped_no_match, total_skipped_no_dropoff,
    )
    if DRY_RUN:
        logger.info("[DRY RUN] No rows were actually written.")


if __name__ == "__main__":
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL env var is required.")
        sys.exit(1)
    run_backfill(db_url)
