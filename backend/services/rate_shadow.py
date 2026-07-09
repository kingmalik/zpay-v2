"""
Shadow mode (S3) — run Pricing v2 next to v1 on every FA upload.

Never touches pay. Writes one rate_shadow_result row per priced ride and
returns a batch summary. The go-live rule (MASTER-PLAN §S3): two consecutive
payroll cycles where v2's decisions match the humans' (or are provably
better) → RATE_ENGINE_V2=1.

Disagreement semantics:
    agrees=True   v2 refused (defers to review — no claim) OR v2 == v1
    agrees=False  v2 resolved a rate different from what v1 assigned
"""
from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.services.rate_engine_v2 import (
    MODE_OFF,
    TIER_NONE,
    load_pricing_context,
    resolve_rate_v2,
    v2_mode,
)

logger = logging.getLogger("zpay.rate_shadow")


def run_shadow_for_batch(db: Session, payroll_batch_id: int) -> dict | None:
    """Shadow-price every acumen ride in the batch. Returns summary or None.

    Own error boundary + own commit; a shadow failure must never break an
    import. Returns None when v2 is off or the batch has no acumen rides.
    """
    if v2_mode() == MODE_OFF:
        return None
    try:
        return _run(db, payroll_batch_id)
    except Exception:
        logger.exception("[rate-shadow] batch %s shadow run failed", payroll_batch_id)
        db.rollback()
        return None


def _run(db: Session, payroll_batch_id: int) -> dict | None:
    from backend.db.models import RateShadowResult, Ride

    rides = (
        db.query(Ride)
        .filter(
            Ride.payroll_batch_id == payroll_batch_id,
            Ride.source == "acumen",
            Ride.removed_at.is_(None),
        )
        .all()
    )
    if not rides:
        return None

    pool = load_pricing_context(db, source="acumen")

    summary = {
        "batch_id": payroll_batch_id,
        "rides": len(rides),
        "v2_resolved": 0,
        "v2_refused": 0,
        "agree": 0,
        "disagree": 0,
        "disagreements": [],
    }

    for ride in rides:
        v1_rate = Decimal(str(ride.z_rate or 0))
        r = resolve_rate_v2(
            ride.service_name or "",
            float(ride.miles) if ride.miles else None,
            pool,
        )
        refused = r.tier == TIER_NONE or r.rate <= 0
        agrees = refused or r.rate == v1_rate

        if refused:
            summary["v2_refused"] += 1
        else:
            summary["v2_resolved"] += 1
        if agrees:
            summary["agree"] += 1
        else:
            summary["disagree"] += 1
            if len(summary["disagreements"]) < 20:
                summary["disagreements"].append({
                    "service_name": ride.service_name,
                    "v1_rate": str(v1_rate),
                    "v1_source": ride.z_rate_source,
                    "v2_rate": str(r.rate),
                    "v2_tier": r.tier,
                    "evidence": r.evidence,
                })

        db.add(RateShadowResult(
            payroll_batch_id=payroll_batch_id,
            ride_id=ride.ride_id,
            service_name=ride.service_name or "",
            miles=ride.miles,
            v1_rate=v1_rate,
            v1_source=ride.z_rate_source or "",
            v2_rate=r.rate,
            v2_tier=r.tier,
            v2_evidence=r.evidence,
            agrees=agrees,
        ))

    db.commit()
    logger.info(
        "[rate-shadow] batch %s: %d rides, v2 resolved %d / refused %d, "
        "%d disagreements",
        payroll_batch_id, summary["rides"], summary["v2_resolved"],
        summary["v2_refused"], summary["disagree"],
    )

    # Report lands in Malik's hands (§S3): one admin SMS per upload with a
    # disagreement count. Admin-facing only — never driver-facing.
    try:
        from backend.services import notification_service as _notify
        if summary["disagree"] > 0:
            _first = summary["disagreements"][0]
            _notify.alert_admin(
                f"RATE SHADOW — batch {payroll_batch_id}: v2 disagrees on "
                f"{summary['disagree']}/{summary['rides']} rides. First: "
                f"{_first['service_name']} v1=${_first['v1_rate']} vs "
                f"v2=${_first['v2_rate']}. Review: /admin/rates/review",
            )
    except Exception:
        logger.exception("[rate-shadow] admin alert failed (non-fatal)")

    return summary
