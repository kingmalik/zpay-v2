"""
Trip-level margin calculation service.

Schema facts (confirmed by code inspection):
  ride.net_pay   = what the partner (FA or ED) pays Maz per trip
  ride.z_rate    = what Maz pays the driver per trip
  ride.deduction = RAD + WUD combined (for ED, already baked into net_pay; stored for audit)
  ride.source    = 'acumen' (FA/FirstAlt) or 'maz' (EverDriven)

Margin formula (same for both partners):
  margin = net_pay - z_rate

Canceled-trip rule (FA):
  - FA paid Maz → net_pay > 0 → driver gets full z_rate → margin = net_pay - z_rate
  - FA didn't pay → net_pay == 0 → driver gets $0 (z_rate == 0) → margin == 0
  (The ingest layer already encodes this: see excell_reader.py line 279)

ED note:
  net_pay from the PDF is already net of WUD + RAD (EverDriven deducts before paying Maz).
  deduction column stores RAD+WUD for auditability but must NOT be double-subtracted.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class TripMargin:
    ride_id: int
    source: str                   # 'acumen' | 'maz'
    service_name: Optional[str]
    partner_paid: float           # ride.net_pay  — what partner pays Maz
    driver_pay: float             # ride.z_rate   — what Maz pays driver
    margin: float                 # partner_paid - driver_pay
    margin_pct: Optional[float]   # None when partner_paid == 0
    notes: str                    # human-readable explanation


def calculate_trip_margin(
    ride_id: int,
    source: str,
    service_name: Optional[str],
    net_pay: float,
    z_rate: float,
    z_rate_source: Optional[str] = None,
    deduction: float = 0.0,
) -> TripMargin:
    """
    Compute margin for a single ride row.

    Args:
        ride_id:       ride.ride_id
        source:        ride.source ('acumen' or 'maz')
        service_name:  ride.service_name (route label)
        net_pay:       ride.net_pay  — partner-paid amount to Maz
        z_rate:        ride.z_rate   — driver pay
        z_rate_source: ride.z_rate_source (for canceled-trip detection)
        deduction:     ride.deduction (RAD+WUD for ED; stored for audit only)

    Returns:
        TripMargin dataclass (immutable).
    """
    partner_paid = float(net_pay or 0)
    driver_pay = float(z_rate or 0)
    margin = round(partner_paid - driver_pay, 2)
    margin_pct: Optional[float] = None

    if partner_paid > 0:
        margin_pct = round(margin / partner_paid * 100, 1)

    # Build a human-readable explanation
    src_label = "FirstAlt" if source == "acumen" else "EverDriven"

    if partner_paid == 0 and driver_pay == 0:
        notes = f"Canceled trip — {src_label} did not pay; driver earns $0. Margin $0."
    elif z_rate_source == "canceled_trip":
        notes = (
            f"Canceled trip — {src_label} paid ${partner_paid:.2f}; "
            f"driver earns full z_rate ${driver_pay:.2f}."
        )
    elif source == "maz" and deduction > 0:
        notes = (
            f"EverDriven: net_pay ${partner_paid:.2f} is already net of "
            f"WUD+RAD ${deduction:.2f}. Driver pay ${driver_pay:.2f}."
        )
    elif partner_paid == 0 and driver_pay > 0:
        notes = (
            f"Warning: no partner payment recorded for this ride. "
            f"Driver paid ${driver_pay:.2f} from rate table. Margin negative."
        )
    else:
        notes = f"{src_label} paid ${partner_paid:.2f}; driver earns ${driver_pay:.2f}."

    return TripMargin(
        ride_id=ride_id,
        source=source,
        service_name=service_name,
        partner_paid=partner_paid,
        driver_pay=driver_pay,
        margin=margin,
        margin_pct=margin_pct,
        notes=notes,
    )


def calculate_trip_margin_from_orm(ride) -> TripMargin:
    """
    Convenience wrapper that accepts a SQLAlchemy Ride ORM object directly.
    """
    return calculate_trip_margin(
        ride_id=int(ride.ride_id),
        source=str(ride.source or ""),
        service_name=ride.service_name,
        net_pay=float(ride.net_pay or 0),
        z_rate=float(ride.z_rate or 0),
        z_rate_source=ride.z_rate_source,
        deduction=float(ride.deduction or 0),
    )


def aggregate_margins(margins: list[TripMargin]) -> dict:
    """
    Aggregate a list of TripMargin objects into totals + per-route breakdown.

    Returns:
        {
          total_partner_paid: float,
          total_driver_pay:   float,
          total_margin:       float,
          margin_pct:         float | None,
          ride_count:         int,
          by_route: [
            { service_name, ride_count, partner_paid, driver_pay, margin, margin_pct }
            ... sorted ascending by margin (worst first)
          ]
        }
    """
    if not margins:
        return {
            "total_partner_paid": 0.0,
            "total_driver_pay": 0.0,
            "total_margin": 0.0,
            "margin_pct": None,
            "ride_count": 0,
            "by_route": [],
        }

    total_partner = sum(m.partner_paid for m in margins)
    total_driver = sum(m.driver_pay for m in margins)
    total_margin = round(total_partner - total_driver, 2)
    margin_pct = round(total_margin / total_partner * 100, 1) if total_partner > 0 else None

    # Group by route
    route_map: dict[str, dict] = {}
    for m in margins:
        key = m.service_name or "(unknown)"
        if key not in route_map:
            route_map[key] = {
                "service_name": key,
                "ride_count": 0,
                "partner_paid": 0.0,
                "driver_pay": 0.0,
            }
        route_map[key]["ride_count"] += 1
        route_map[key]["partner_paid"] += m.partner_paid
        route_map[key]["driver_pay"] += m.driver_pay

    by_route = []
    for r in route_map.values():
        r_margin = round(r["partner_paid"] - r["driver_pay"], 2)
        r_pct = (
            round(r_margin / r["partner_paid"] * 100, 1)
            if r["partner_paid"] > 0
            else None
        )
        by_route.append({
            "service_name": r["service_name"],
            "ride_count": r["ride_count"],
            "partner_paid": round(r["partner_paid"], 2),
            "driver_pay": round(r["driver_pay"], 2),
            "margin": r_margin,
            "margin_pct": r_pct,
        })

    # Sort ascending by margin — worst-performing routes first
    by_route.sort(key=lambda x: x["margin"])

    return {
        "total_partner_paid": round(total_partner, 2),
        "total_driver_pay": round(total_driver, 2),
        "total_margin": total_margin,
        "margin_pct": margin_pct,
        "ride_count": len(margins),
        "by_route": by_route,
    }
