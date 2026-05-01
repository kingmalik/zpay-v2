"""
Unit tests for backend/services/trip_margin.py

Covers:
  1. Standard FA trip (normal completed ride)
  2. Standard ED trip with WUD+RAD deduction stored on ride
  3. Canceled FA trip where FA paid (driver earns full z_rate)
  4. Canceled FA trip where FA did NOT pay (driver gets $0)
  5. Edge case: missing partner_paid (net_pay=0, z_rate>0)
  6. Aggregation: totals + per-route breakdown + sort order
  7. Aggregation with empty input
"""

import pytest
from backend.services.trip_margin import (
    TripMargin,
    aggregate_margins,
    calculate_trip_margin,
    calculate_trip_margin_from_orm,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_margin(
    ride_id: int = 1,
    source: str = "acumen",
    service_name: str = "Redmond _D",
    net_pay: float = 100.0,
    z_rate: float = 80.0,
    z_rate_source: str = "service_default",
    deduction: float = 0.0,
) -> TripMargin:
    return calculate_trip_margin(
        ride_id=ride_id,
        source=source,
        service_name=service_name,
        net_pay=net_pay,
        z_rate=z_rate,
        z_rate_source=z_rate_source,
        deduction=deduction,
    )


class FakeRide:
    """Minimal stand-in for a SQLAlchemy Ride ORM row."""
    def __init__(self, ride_id, source, service_name, net_pay, z_rate,
                 z_rate_source="service_default", deduction=0.0):
        self.ride_id = ride_id
        self.source = source
        self.service_name = service_name
        self.net_pay = net_pay
        self.z_rate = z_rate
        self.z_rate_source = z_rate_source
        self.deduction = deduction


# ── Test 1: Standard FA trip ───────────────────────────────────────────────────

def test_standard_fa_trip_margin():
    """FA trip: partner_paid=100, driver_pay=80 → margin=20, 20%."""
    m = _make_margin(net_pay=100.0, z_rate=80.0, source="acumen")

    assert m.partner_paid == 100.0
    assert m.driver_pay == 80.0
    assert m.margin == 20.0
    assert m.margin_pct == 20.0
    assert m.source == "acumen"
    assert "FirstAlt" in m.notes


# ── Test 2: Standard ED trip with WUD+RAD ─────────────────────────────────────

def test_standard_ed_trip_with_deduction():
    """
    ED trip: ED pays Maz net_pay=$44.86 (already net of WUD+RAD=$3.50).
    Driver earns flat $40. deduction stored for audit but NOT re-subtracted.
    margin = 44.86 - 40.00 = 4.86
    """
    m = _make_margin(
        source="maz",
        service_name="EverDriven Route 7",
        net_pay=44.86,
        z_rate=40.0,
        deduction=3.50,
    )

    assert m.partner_paid == 44.86
    assert m.driver_pay == 40.0
    assert m.margin == pytest.approx(4.86, abs=0.01)
    assert m.margin_pct == pytest.approx(10.8, abs=0.2)
    assert "EverDriven" in m.notes
    assert "WUD" in m.notes or "deduction" in m.notes.lower() or "3.50" in m.notes


# ── Test 3: Canceled FA trip — FA paid Maz ────────────────────────────────────

def test_canceled_fa_trip_fa_paid():
    """
    FA canceled but still paid Maz. Driver earns full z_rate.
    net_pay=90, z_rate=90 (ingest sets z_rate_source='canceled_trip').
    margin = 90 - 90 = 0 (Maz breaks even on canceled paid trips).
    """
    m = _make_margin(
        source="acumen",
        service_name="Timberline",
        net_pay=90.0,
        z_rate=90.0,
        z_rate_source="canceled_trip",
    )

    assert m.partner_paid == 90.0
    assert m.driver_pay == 90.0
    assert m.margin == 0.0
    assert "canceled" in m.notes.lower()
    assert "FirstAlt" in m.notes


# ── Test 4: Canceled FA trip — FA did NOT pay ─────────────────────────────────

def test_canceled_fa_trip_fa_not_paid():
    """
    FA canceled and did NOT pay Maz. Driver gets $0.
    net_pay=0, z_rate=0 → margin=0, margin_pct=None.
    """
    m = _make_margin(
        source="acumen",
        service_name="Ella Baker 01_B",
        net_pay=0.0,
        z_rate=0.0,
        z_rate_source="canceled_trip",
    )

    assert m.partner_paid == 0.0
    assert m.driver_pay == 0.0
    assert m.margin == 0.0
    assert m.margin_pct is None
    assert "$0" in m.notes or "0.00" in m.notes


# ── Test 5: Missing partner_paid ──────────────────────────────────────────────

def test_missing_partner_paid_negative_margin():
    """
    Edge: net_pay=0 but z_rate>0 (no SP Itemized row matched yet).
    Margin is negative — signals data gap, not a real loss.
    """
    m = _make_margin(
        source="acumen",
        service_name="Risalah 04_G",
        net_pay=0.0,
        z_rate=38.0,
    )

    assert m.partner_paid == 0.0
    assert m.driver_pay == 38.0
    assert m.margin == -38.0
    assert m.margin_pct is None
    # Notes should warn about no partner payment
    assert "warning" in m.notes.lower() or "no partner" in m.notes.lower()


# ── Test 6: ORM convenience wrapper ───────────────────────────────────────────

def test_calculate_trip_margin_from_orm():
    """calculate_trip_margin_from_orm correctly reads ORM-like object attributes."""
    ride = FakeRide(
        ride_id=42,
        source="acumen",
        service_name="Redmond _D",
        net_pay=100.0,
        z_rate=80.0,
        z_rate_source="service_default",
        deduction=0.0,
    )
    m = calculate_trip_margin_from_orm(ride)
    assert m.ride_id == 42
    assert m.margin == 20.0


# ── Test 7: aggregate_margins — totals + route ranking ────────────────────────

def test_aggregate_margins_totals_and_routes():
    """
    Three rides across two routes. Aggregation should:
    - Sum totals correctly
    - Group by route
    - Sort by margin ascending (worst first)
    """
    margins = [
        _make_margin(ride_id=1, service_name="Route A", net_pay=100.0, z_rate=80.0),
        _make_margin(ride_id=2, service_name="Route A", net_pay=100.0, z_rate=80.0),
        _make_margin(ride_id=3, service_name="Route B", net_pay=50.0,  z_rate=45.0),
    ]

    agg = aggregate_margins(margins)

    assert agg["ride_count"] == 3
    assert agg["total_partner_paid"] == 250.0
    assert agg["total_driver_pay"] == 205.0
    assert agg["total_margin"] == 45.0
    assert agg["margin_pct"] == pytest.approx(18.0, abs=0.2)

    routes = agg["by_route"]
    assert len(routes) == 2

    # Route B has lower margin ($5) so should come first (worst first)
    assert routes[0]["service_name"] == "Route B"
    assert routes[0]["margin"] == 5.0
    assert routes[1]["service_name"] == "Route A"
    assert routes[1]["margin"] == 40.0


# ── Test 8: aggregate_margins — empty input ───────────────────────────────────

def test_aggregate_margins_empty():
    """Empty input returns zeroed-out structure with empty by_route."""
    agg = aggregate_margins([])

    assert agg["ride_count"] == 0
    assert agg["total_partner_paid"] == 0.0
    assert agg["total_margin"] == 0.0
    assert agg["margin_pct"] is None
    assert agg["by_route"] == []


# ── Test 9: TripMargin is immutable ───────────────────────────────────────────

def test_trip_margin_is_frozen():
    """TripMargin dataclass must be frozen (immutable)."""
    m = _make_margin()
    with pytest.raises((AttributeError, TypeError)):
        m.margin = 999.0  # type: ignore[misc]
