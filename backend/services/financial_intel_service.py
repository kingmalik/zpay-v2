import asyncio
import logging
import os
from datetime import datetime, timezone, time
from zoneinfo import ZoneInfo

logger = logging.getLogger("zpay.financial_intel")

_task: asyncio.Task | None = None
_TZ_NAME = os.environ.get("MONITOR_TIMEZONE", "America/Los_Angeles")


def build_daily_report() -> str:
    from backend.db import SessionLocal
    from backend.db.models import Ride, PayrollBatch, Person, ZRateService
    from sqlalchemy import func, cast, Date

    tz = ZoneInfo(_TZ_NAME)
    today = datetime.now(tz).date()

    db = SessionLocal()
    try:
        # Today's rides from active batch(es)
        ride_rows = (
            db.query(Ride)
            .join(PayrollBatch, Ride.payroll_batch_id == PayrollBatch.payroll_batch_id)
            .filter(
                PayrollBatch.period_start <= today,
                PayrollBatch.period_end >= today,
            )
            .all()
        )

        ride_count = len(ride_rows)
        total_z_pay = sum(float(r.z_rate or 0) for r in ride_rows)
        avg_rate = (total_z_pay / ride_count) if ride_count else 0

        # Estimated revenue = rides × avg rate (already captured as z_rate per ride)
        est_revenue = total_z_pay

        # Unassigned rides: pull from DB dispatches missing person linkage
        # Using ride rows where person_id is null or person is inactive as proxy
        unassigned_count = (
            db.query(func.count(Ride.ride_id))
            .join(PayrollBatch, Ride.payroll_batch_id == PayrollBatch.payroll_batch_id)
            .join(Person, Ride.person_id == Person.person_id)
            .filter(
                PayrollBatch.period_start <= today,
                PayrollBatch.period_end >= today,
                Person.active == False,
            )
            .scalar()
        ) or 0

        # Drivers missing Paychex codes
        missing_paychex = (
            db.query(Person)
            .filter(
                Person.active == True,
                (Person.paycheck_code == None) | (Person.paycheck_code == ""),
            )
            .all()
        )
        missing_names = [p.full_name for p in missing_paychex[:10]]

        lines = [
            f"📊 *Z-Pay Daily Report — {today}*",
            "",
            f"Rides today: *{ride_count}*",
            f"Unassigned: *{unassigned_count}*",
            f"Est. revenue: *${est_revenue:,.2f}*",
            f"Avg rate/ride: ${avg_rate:.2f}",
        ]

        if missing_names:
            lines.append("")
            lines.append(f"⚠️ *Missing Paychex codes ({len(missing_paychex)}):*")
            for name in missing_names:
                lines.append(f"  • {name}")
            if len(missing_paychex) > 10:
                lines.append(f"  ...and {len(missing_paychex) - 10} more")
        else:
            lines.append("✅ All active drivers have Paychex codes")

        return "\n".join(lines)

    except Exception as e:
        logger.error("Failed to build daily report: %s", e)
        return f"Daily report failed to generate: {e}"
    finally:
        db.close()


async def _daily_intel_loop():
    tz = ZoneInfo(_TZ_NAME)
    logger.info("[financial-intel] Daily report task started, targeting 8:00 AM %s", _TZ_NAME)

    while True:
        try:
            now = datetime.now(tz)
            target = datetime(now.year, now.month, now.day, 8, 0, 0, tzinfo=tz)
            if now >= target:
                # Already past 8am today — schedule for tomorrow
                from datetime import timedelta
                target = target + timedelta(days=1)

            wait_seconds = (target - now).total_seconds()
            logger.debug("[financial-intel] Next report in %.0f seconds", wait_seconds)
            await asyncio.sleep(wait_seconds)

            report = build_daily_report()
            from backend.services.notification_service import send_whatsapp_alert
            send_whatsapp_alert(report)
            logger.info("[financial-intel] Daily report sent")

            # Sleep 70 seconds to avoid double-firing within the same minute
            await asyncio.sleep(70)

        except asyncio.CancelledError:
            logger.info("[financial-intel] Task cancelled")
            break
        except Exception as e:
            logger.error("[financial-intel] Report failed: %s", e)
            # Back off 5 min on error before retrying loop
            await asyncio.sleep(300)


def start_financial_intel():
    global _task
    if _task is not None and not _task.done():
        logger.warning("[financial-intel] Already running")
        return
    _task = asyncio.create_task(_daily_intel_loop())
    logger.info("[financial-intel] Scheduled daily 8am WhatsApp report")


def stop_financial_intel():
    global _task
    if _task and not _task.done():
        _task.cancel()
        _task = None
    logger.info("[financial-intel] Stopped")
