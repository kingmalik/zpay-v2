"""Tests for S1.5 partner-payment reconciliation (FA TPA §6b dispute clock).

Pure-logic tests against backend/services/partner_reconciliation.py —
classify_batch_payment takes plain values, no DB needed. Registry checks
read source text, matching the style of test_ingest_guards.py.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from backend.services.partner_reconciliation import (
    AT_RISK_DAYS,
    DISPUTE_WINDOW_DAYS,
    classify_batch_payment,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]

TODAY = date(2026, 7, 8)
TPA_ERA_WEEK_END = date(2026, 7, 4)     # after RECON_ENFORCE_SINCE default
HISTORICAL_WEEK_END = date(2026, 5, 1)  # before the TPA era


def _summary(deposited: float, deposit_date: date, disputed: bool = False) -> dict:
    return {
        "deposited": deposited,
        "first_deposit_date": deposit_date,
        "payment_count": 1,
        "disputed": disputed,
    }


class TestUntrackedVsUnpaid:
    def test_historical_batch_with_no_deposits_is_untracked(self):
        """Pre-TPA batches must not scream 'unpaid' forever."""
        # Arrange / Act
        status = classify_batch_payment(3050.50, None, HISTORICAL_WEEK_END, TODAY)
        # Assert
        assert status.payment_status == "untracked"
        assert status.dispute_deadline is None

    def test_tpa_era_batch_with_no_deposits_is_unpaid(self):
        status = classify_batch_payment(3050.50, None, TPA_ERA_WEEK_END, TODAY)
        assert status.payment_status == "unpaid"
        assert status.deposited == 0.0
        assert status.delta == -3050.50

    def test_batch_with_null_week_end_and_no_deposits_is_untracked(self):
        status = classify_batch_payment(100.0, None, None, TODAY)
        assert status.payment_status == "untracked"

    def test_historical_batch_with_a_recorded_deposit_still_classifies(self):
        """Once a deposit IS recorded, era no longer matters — diff it."""
        status = classify_batch_payment(
            100.0, _summary(100.0, date(2026, 5, 3)), HISTORICAL_WEEK_END, TODAY
        )
        assert status.payment_status == "match"


class TestMatchTolerance:
    def test_exact_deposit_matches(self):
        status = classify_batch_payment(
            2298.00, _summary(2298.00, date(2026, 7, 6)), TPA_ERA_WEEK_END, TODAY
        )
        assert status.payment_status == "match"
        assert status.delta == 0.0
        assert status.dispute_days_left is None

    def test_penny_difference_still_matches(self):
        status = classify_batch_payment(
            2298.00, _summary(2298.01, date(2026, 7, 6)), TPA_ERA_WEEK_END, TODAY
        )
        assert status.payment_status == "match"

    def test_two_cent_shortfall_is_underpaid(self):
        status = classify_batch_payment(
            2298.00, _summary(2297.98, date(2026, 7, 6)), TPA_ERA_WEEK_END, TODAY
        )
        assert status.payment_status == "underpaid"


class TestDisputeClock:
    def test_deadline_is_deposit_date_plus_window(self):
        deposit = date(2026, 7, 1)
        status = classify_batch_payment(
            1000.0, _summary(900.0, deposit), TPA_ERA_WEEK_END, TODAY
        )
        assert status.payment_status == "underpaid"
        assert status.dispute_deadline == date(2026, 7, 15)
        assert (status.dispute_deadline - deposit).days == DISPUTE_WINDOW_DAYS

    def test_days_left_counts_down_from_today(self):
        status = classify_batch_payment(
            1000.0, _summary(900.0, date(2026, 7, 1)), TPA_ERA_WEEK_END, TODAY
        )
        assert status.dispute_days_left == 7

    def test_closed_window_goes_negative(self):
        status = classify_batch_payment(
            1000.0, _summary(900.0, date(2026, 6, 1)), TPA_ERA_WEEK_END, TODAY
        )
        assert status.dispute_days_left is not None
        assert status.dispute_days_left < 0

    def test_overpaid_also_gets_a_deadline(self):
        """Overpayments need allocation review inside the same window."""
        status = classify_batch_payment(
            1000.0, _summary(1100.0, date(2026, 7, 6)), TPA_ERA_WEEK_END, TODAY
        )
        assert status.payment_status == "overpaid"
        assert status.dispute_deadline == date(2026, 7, 20)

    def test_disputed_flag_carries_through(self):
        status = classify_batch_payment(
            1000.0,
            _summary(900.0, date(2026, 7, 1), disputed=True),
            TPA_ERA_WEEK_END,
            TODAY,
        )
        assert status.disputed is True


class TestAtRiskThreshold:
    def test_at_risk_days_is_five(self):
        """The health check pages red at 5 days before waiver."""
        assert AT_RISK_DAYS == 5

    def test_window_is_fourteen_days_per_tpa_6b(self):
        assert DISPUTE_WINDOW_DAYS == 14


class TestWiring:
    """Source-text checks that the pieces are actually plugged in."""

    def test_health_monitor_registers_partner_reconciliation_check(self):
        src = (BACKEND_DIR / "services" / "health_monitor.py").read_text(encoding="utf-8")
        assert '"partner_reconciliation"' in src
        assert "_check_partner_reconciliation" in src

    def test_app_includes_partner_payments_router(self):
        src = (BACKEND_DIR / "app.py").read_text(encoding="utf-8")
        assert "partner_payments" in src

    def test_reconciliation_api_exposes_dispute_fields(self):
        src = (BACKEND_DIR / "routes" / "api_data.py").read_text(encoding="utf-8")
        for field in ("payment_status", "dispute_deadline", "dispute_days_left", "deposits_unconfirmed"):
            assert field in src, f"api_reconciliation missing {field}"
