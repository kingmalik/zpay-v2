#!/usr/bin/env python3
"""
rate_conflicts_report.py — READ-ONLY report of z_rate_service rows that
carry duplicate (source, service_name) groups with conflicting default_rate
values.

Background: z_rate_service has a unique index on (source, company_name,
service_name), but company_name is not a reliable key — the same route gets
imported over time under multiple spellings ("FirstAlt" / "Acumen
International" / "Acumen", "EverDriven" / "everDriven"). That produced
duplicate rows per (source, service_name); this report surfaces only the
groups where those duplicates disagree on default_rate — i.e. the ones where
a "Permanent" rate edit could silently land on a row payroll never reads.

Migration s14 soft-merges these (active=false + merged_into_id — nothing is
ever deleted) and, separately, adjusts the surviving row's default_rate to
the "last paid" rate when that signal is CONFIRMED (see
backend/services/rate_service_dedupe.py for the exact qualifying-ride rule
and confidence levels). This report shows both: which row will stay active
("will_be"), and what its final default_rate will be after the migration
("final_rate"), which is not always the same as the FK-survivor row's own
currently-stored default_rate.

This script makes NO writes. It only runs SELECT queries and reuses the pure
grouping/survivor/last-paid helpers in backend.services.rate_service_dedupe
— the same logic migration s14 uses — so the report and the migration always
agree.

Usage:
    DATABASE_URL=postgresql://... python3 scripts/rate_conflicts_report.py
    DATABASE_URL=sqlite:///... python3 scripts/rate_conflicts_report.py

Never point this at prod — it's read-only, but there's no reason to run it
against a live DB when the whole point is to review conflicts before the
migration runs. Output is markdown on stdout.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.db.models import PayrollBatch, Ride, ZRateService
from backend.services.rate_service_dedupe import (
    choose_survivor,
    find_duplicate_groups,
    last_paid_signal_for,
    ride_counts_for,
)


def _has_rate_conflict(group: list[ZRateService]) -> bool:
    """True if the group's rows don't all share the same default_rate."""
    rates = {row.default_rate for row in group}
    return len(rates) > 1


def _last_batch_id_for(db: Session, service_id: int) -> int | None:
    """Most recent payroll_batch_id (by period_end, falling back to
    uploaded_at) among rides referencing this z_rate_service_id."""
    row = (
        db.query(PayrollBatch.payroll_batch_id)
        .join(Ride, Ride.payroll_batch_id == PayrollBatch.payroll_batch_id)
        .filter(Ride.z_rate_service_id == service_id)
        .order_by(PayrollBatch.period_end.desc().nullslast(), PayrollBatch.uploaded_at.desc())
        .limit(1)
        .one_or_none()
    )
    return row[0] if row else None


def build_report_rows(db: Session) -> list[dict]:
    """Return one dict per conflicting group, ready for markdown rendering."""
    groups = find_duplicate_groups(db)
    conflicting = [g for g in groups if _has_rate_conflict(g)]

    report_rows: list[dict] = []
    for group in conflicting:
        ids = [row.z_rate_service_id for row in group]
        ride_counts = ride_counts_for(db, ids)
        survivor = choose_survivor(group, ride_counts)

        signal = last_paid_signal_for(db, source=group[0].source, service_name=group[0].service_name)
        # Mirrors dedupe_group()'s rule exactly: only a CONFIRMED signal
        # changes the survivor's rate; otherwise it keeps its own stored rate.
        if signal.confidence == "confirmed" and signal.rate is not None:
            final_rate = signal.rate
        else:
            final_rate = survivor.default_rate

        rows_out = []
        for row in sorted(group, key=lambda r: r.z_rate_service_id):
            is_survivor = row.z_rate_service_id == survivor.z_rate_service_id
            will_be = (
                "kept (active)"
                if is_survivor
                else f"switched off → merged into {survivor.z_rate_service_id}"
            )
            rows_out.append({
                "z_rate_service_id": row.z_rate_service_id,
                "company_name": row.company_name,
                "default_rate": row.default_rate,
                "ride_count": ride_counts.get(row.z_rate_service_id, 0),
                "last_payroll_batch_id": _last_batch_id_for(db, row.z_rate_service_id),
                "is_survivor": is_survivor,
                "will_be": will_be,
            })

        report_rows.append({
            "source": group[0].source,
            "service_name": group[0].service_name,
            "survivor_id": survivor.z_rate_service_id,
            "last_paid_rate": signal.rate,
            "last_paid_batch": signal.batch_id,
            "rides_at_that_rate": signal.rides_at_rate,
            "confidence": signal.confidence,
            "final_rate": final_rate,
            "rows": rows_out,
        })

    # Stable, readable order: by source then service_name.
    report_rows.sort(key=lambda r: ((r["source"] or ""), r["service_name"]))
    return report_rows


def render_markdown(report_rows: list[dict]) -> str:
    lines = []
    lines.append("# z_rate_service rate conflicts")
    lines.append("")
    lines.append(
        f"{len(report_rows)} group(s) of duplicate `(source, service_name)` rows "
        "with conflicting `default_rate` values."
    )
    lines.append("")

    if not report_rows:
        lines.append("No conflicts found.")
        return "\n".join(lines) + "\n"

    lines.append(
        "| service_name | source | z_rate_service_id | company_name | default_rate | "
        "ride_count | last_payroll_batch_id | will_be | last_paid_rate | last_paid_batch | "
        "rides_at_that_rate | confidence | final_rate |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for group in report_rows:
        for row in group["rows"]:
            lines.append(
                "| {service_name} | {source} | {id} | {company_name} | {rate} | "
                "{ride_count} | {last_batch} | {will_be} | {last_paid_rate} | {last_paid_batch} | "
                "{rides_at_that_rate} | {confidence} | {final_rate} |".format(
                    service_name=group["service_name"],
                    source=group["source"] or "",
                    id=row["z_rate_service_id"],
                    company_name=row["company_name"] or "",
                    rate=row["default_rate"],
                    ride_count=row["ride_count"],
                    last_batch=row["last_payroll_batch_id"] if row["last_payroll_batch_id"] is not None else "",
                    will_be=row["will_be"],
                    last_paid_rate=group["last_paid_rate"] if group["last_paid_rate"] is not None else "",
                    last_paid_batch=group["last_paid_batch"] if group["last_paid_batch"] is not None else "",
                    rides_at_that_rate=group["rides_at_that_rate"],
                    confidence=group["confidence"],
                    final_rate=group["final_rate"],
                )
            )
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is not set.", file=sys.stderr)
        sys.exit(1)

    engine = create_engine(database_url)
    SessionFactory = sessionmaker(bind=engine)
    db = SessionFactory()
    try:
        report_rows = build_report_rows(db)
        print(render_markdown(report_rows))
    finally:
        db.close()


if __name__ == "__main__":
    main()
