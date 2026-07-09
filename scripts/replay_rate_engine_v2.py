"""
Pricing Engine v2 — replay harness (S2 exit gate).

Replays every historical rate-review item against v2 and diffs v2's answer
against the human decision that actually shipped.

Ground truth: z_rate_service rows whose rate was NOT confidently known at
import time (default_rate_source IN ('unknown_route','inherited_from_sibling'))
and that now carry a human-accepted rate (> 0). For each, we hide that row
from v2 and ask: what would v2 have priced this route at when it appeared?

Two candidate-pool modes, both reported:
  naive    — exclude only the target row (candidates = today's full pool)
  temporal — additionally exclude any service whose first ride is NOT
             earlier than the target's first ride (approximates "what
             existed when this route first appeared")

Exit gate (MASTER-PLAN §S2): v2 auto-prices ≥90% of items with ZERO wrong
rates. A refusal (tier none) is a miss, not an error — refusals fall to rate
review exactly like today.

Usage:
    DATABASE_URL=postgresql://... PYTHONPATH=. python3 scripts/replay_rate_engine_v2.py
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine, func, text
from sqlalchemy.orm import sessionmaker

from backend.services.rate_engine_v2 import (
    TIER_NONE,
    load_pricing_context,
    resolve_rate_v2,
)


def main() -> int:
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        print("DATABASE_URL required", file=sys.stderr)
        return 2
    engine = create_engine(db_url.replace("postgresql+psycopg", "postgresql"))
    db = sessionmaker(bind=engine)()

    from backend.db.models import Ride, ZRateService

    targets = (
        db.query(ZRateService)
        .filter(
            func.lower(func.coalesce(ZRateService.source, "")) == "acumen",
            ZRateService.default_rate_source.in_(["unknown_route", "inherited_from_sibling"]),
            ZRateService.default_rate > 0,
        )
        .all()
    )
    print(f"ground-truth set: {len(targets)} human-priced rate-review items\n")

    # First-ride timestamp per service_name (temporal guard).
    first_ride_rows = (
        db.query(Ride.service_name, func.min(Ride.ride_start_ts).label("first_ts"))
        .filter(Ride.source == "acumen", Ride.removed_at.is_(None))
        .group_by(Ride.service_name)
        .all()
    )
    first_ride = {r.service_name: r.first_ts for r in first_ride_rows}

    # Median miles per service_name (the ride's miles at appearance time).
    miles_rows = (
        db.query(
            Ride.service_name,
            func.percentile_cont(0.5).within_group(Ride.miles).label("mm"),
        )
        .filter(Ride.source == "acumen", Ride.removed_at.is_(None), Ride.miles > 0)
        .group_by(Ride.service_name)
        .all()
    )
    median_miles = {r.service_name: float(r.mm) for r in miles_rows if r.mm is not None}

    # One in-memory pool for everything — per-target pools are filtered
    # views of this list (the earlier per-target rebuild hammered prod with
    # ~250k queries and got the connection killed).
    full_pool = load_pricing_context(db, source="acumen")
    truth_rate = {p.service_name.lower(): p.rate for p in full_pool}
    print(f"candidate pool: {len(full_pool)} rate-bearing parseable services\n")

    for mode in ("naive", "temporal"):
        stats = {"resolved_correct": 0, "resolved_wrong": 0, "refused": 0, "no_truth": 0}
        wrong: list[str] = []
        refused: list[str] = []

        for svc in targets:
            name = (svc.service_name or "").strip()
            accepted = truth_rate.get(name.lower())
            if not accepted or accepted <= 0:
                stats["no_truth"] += 1
                continue

            exclude = {name.lower()}
            if mode == "temporal":
                target_first = first_ride.get(name)
                if target_first is not None:
                    exclude |= {
                        n.lower() for n, ts in first_ride.items()
                        if ts is not None and ts >= target_first
                    }

            pool = [p for p in full_pool if p.service_name.lower() not in exclude]
            r = resolve_rate_v2(name, median_miles.get(name), pool)

            if r.tier == TIER_NONE or r.rate <= 0:
                stats["refused"] += 1
                refused.append(f"{name}: {r.evidence}")
            elif Decimal(str(r.rate)) == Decimal(str(accepted)):
                stats["resolved_correct"] += 1
            else:
                stats["resolved_wrong"] += 1
                wrong.append(
                    f"{name}: v2 said ${r.rate} [{r.tier}] but human accepted ${accepted}"
                    f" — {r.evidence}"
                )

        judged = stats["resolved_correct"] + stats["resolved_wrong"] + stats["refused"]
        auto = stats["resolved_correct"] + stats["resolved_wrong"]
        print(f"── {mode.upper()} pool ──")
        print(f"  judged: {judged} (skipped {stats['no_truth']} with no usable truth)")
        if judged:
            print(f"  auto-priced: {auto}/{judged} ({auto/judged:.1%})")
            print(f"  correct:     {stats['resolved_correct']}/{auto if auto else 1}"
                  f" ({(stats['resolved_correct']/auto if auto else 0):.1%} of auto-priced)")
            print(f"  WRONG:       {stats['resolved_wrong']}")
            print(f"  refused:     {stats['refused']} (fall to rate review, like today)")
        for w in wrong:
            print(f"    ✗ {w}")
        if mode == "temporal" and refused:
            print("  refusals (temporal):")
            for rf in refused[:15]:
                print(f"    · {rf}")
        print()

    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
