"""
Unit tests for W15 audit rule logic in scripts/audit_w15.py.

Uses synthetic RideRow fixtures — no DB connection required.
Each test exercises one specific payroll rule and verifies the
violation type/severity returned.
"""

import sys
from decimal import Decimal
from pathlib import Path

import pytest

# Allow importing from scripts/ directory
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from audit_w15 import (
    RideRow,
    Violation,
    check_canceled_trip_rule,
    check_ed_wud_rad,
    check_net_pay_contamination,
    check_rate_49_72,
    check_rate_accuracy,
    build_driver_summaries,
    compute_totals,
    FA_BATCH_ID,
    MAZ_BATCH_ID,
)

# ── Helpers ────────────────────────────────────────────────────────────────────

def make_ride(
    ride_id: int = 1,
    payroll_batch_id: int = FA_BATCH_ID,
    person_id: int = 100,
    driver_name: str = "Test Driver",
    service_name: str = "Test School IB 01",
    source: str = "acumen",
    z_rate: str = "100.00",
    z_rate_source: str = "service_default",
    z_rate_service_id: int | None = 1,
    net_pay: str = "130.00",
    gross_pay: str = "100.00",
    deduction: str = "0.00",
    service_default_rate: str | None = "100.00",
) -> RideRow:
    return RideRow(
        ride_id=ride_id,
        payroll_batch_id=payroll_batch_id,
        person_id=person_id,
        driver_name=driver_name,
        service_name=service_name,
        source=source,
        z_rate=Decimal(z_rate),
        z_rate_source=z_rate_source,
        z_rate_service_id=z_rate_service_id,
        net_pay=Decimal(net_pay),
        gross_pay=Decimal(gross_pay),
        deduction=Decimal(deduction),
        service_default_rate=Decimal(service_default_rate) if service_default_rate else None,
    )


# ── Rate accuracy tests ────────────────────────────────────────────────────────

class TestRateAccuracy:

    def test_clean_ride_no_violations(self):
        """Ride with z_rate matching service_default_rate produces no violation."""
        ride = make_ride(z_rate="100.00", service_default_rate="100.00")
        violations: list[Violation] = []
        check_rate_accuracy(ride, violations)
        assert violations == []

    def test_rate_mismatch_produces_high_violation(self):
        """z_rate differs from service table default → HIGH violation."""
        ride = make_ride(z_rate="80.00", service_default_rate="100.00")
        violations: list[Violation] = []
        check_rate_accuracy(ride, violations)
        assert len(violations) == 1
        assert violations[0].severity == "HIGH"
        assert violations[0].rule == "RATE_MISMATCH"

    def test_manual_ride_exempt(self):
        """Manual adjustments are not validated against service table."""
        ride = make_ride(z_rate_source="manual", z_rate="999.00", service_default_rate="100.00")
        violations: list[Violation] = []
        check_rate_accuracy(ride, violations)
        assert violations == []

    def test_zero_rate_no_config_nonzero_rate_is_info(self):
        """zero_rate_no_config with a non-zero z_rate produces INFO (not CRITICAL)."""
        ride = make_ride(
            z_rate_source="zero_rate_no_config",
            z_rate="85.00",
            z_rate_service_id=None,
            service_default_rate=None,
        )
        violations: list[Violation] = []
        check_rate_accuracy(ride, violations)
        assert len(violations) == 1
        assert violations[0].severity == "INFO"
        assert violations[0].rule == "RATE_NO_CONFIG_ENTRY"

    def test_zero_rate_no_config_zero_rate_is_critical(self):
        """zero_rate_no_config with z_rate=0 means driver paid nothing → CRITICAL."""
        ride = make_ride(
            z_rate_source="zero_rate_no_config",
            z_rate="0.00",
            z_rate_service_id=None,
            service_default_rate=None,
        )
        violations: list[Violation] = []
        check_rate_accuracy(ride, violations)
        assert len(violations) == 1
        assert violations[0].severity == "CRITICAL"
        assert violations[0].rule == "RATE_ZERO_NO_CONFIG"

    def test_penny_tolerance_no_false_positive(self):
        """Floating-point rounding within 1¢ does not trigger a violation."""
        ride = make_ride(z_rate="100.00", service_default_rate="100.00")
        # Simulate tiny fp drift
        ride = RideRow(
            **{**ride.__dict__, "z_rate": Decimal("100.009"), "service_default_rate": Decimal("100.00")}
        )
        violations: list[Violation] = []
        check_rate_accuracy(ride, violations)
        # 0.009 < 0.01 penny threshold — no violation
        assert violations == []


# ── FA canceled-trip rule tests ────────────────────────────────────────────────

class TestFACanceledTripRule:

    def test_fa_canceled_fa_paid_driver_gets_rate(self):
        """FA canceled, net_pay > 0 → z_rate > 0 is correct. No violation."""
        ride = make_ride(
            z_rate_source="canceled_trip",
            source="acumen",
            z_rate="42.00",
            net_pay="42.00",
        )
        violations: list[Violation] = []
        check_canceled_trip_rule(ride, violations)
        assert violations == []

    def test_fa_canceled_fa_not_paid_driver_gets_zero(self):
        """FA canceled, net_pay = 0 → z_rate should be $0. If z_rate > 0, CRITICAL."""
        ride = make_ride(
            z_rate_source="canceled_trip",
            source="acumen",
            z_rate="42.00",
            net_pay="0.00",
        )
        violations: list[Violation] = []
        check_canceled_trip_rule(ride, violations)
        assert len(violations) == 1
        assert violations[0].severity == "CRITICAL"
        assert violations[0].rule == "FA_CANCELED_UNPAID_BUT_DRIVER_PAID"

    def test_fa_canceled_fa_paid_driver_zero_is_high(self):
        """FA paid (net_pay>0) but driver z_rate=0 → driver underpaid → HIGH."""
        ride = make_ride(
            z_rate_source="canceled_trip",
            source="acumen",
            z_rate="0.00",
            net_pay="42.00",
        )
        violations: list[Violation] = []
        check_canceled_trip_rule(ride, violations)
        assert len(violations) == 1
        assert violations[0].severity == "HIGH"
        assert violations[0].rule == "FA_CANCELED_PAID_BUT_DRIVER_ZERO"

    def test_non_canceled_ride_not_checked(self):
        """Normal ride (not canceled_trip) is not checked by this rule."""
        ride = make_ride(z_rate_source="service_default", net_pay="130.00", z_rate="100.00")
        violations: list[Violation] = []
        check_canceled_trip_rule(ride, violations)
        assert violations == []


# ── ED WUD/RAD tests ────────────────────────────────────────────────────────────

class TestEDWUDRAD:

    def test_ed_gross_equals_net_plus_deduction_no_violation(self):
        """ED ride: gross_pay = net_pay + deduction. Accounting invariant holds."""
        ride = make_ride(
            payroll_batch_id=MAZ_BATCH_ID,
            source="maz",
            gross_pay="45.00",
            net_pay="41.42",
            deduction="3.58",
            z_rate="38.00",
            service_default_rate="38.00",
        )
        violations: list[Violation] = []
        check_ed_wud_rad(ride, violations)
        assert violations == []

    def test_ed_gross_mismatch_produces_high(self):
        """ED gross_pay != net_pay + deduction → HIGH violation."""
        ride = make_ride(
            payroll_batch_id=MAZ_BATCH_ID,
            source="maz",
            gross_pay="50.00",   # wrong: should be 41.42 + 3.58 = 45.00
            net_pay="41.42",
            deduction="3.58",
            z_rate="38.00",
            service_default_rate="38.00",
        )
        violations: list[Violation] = []
        check_ed_wud_rad(ride, violations)
        assert len(violations) == 1
        assert violations[0].severity == "HIGH"
        assert violations[0].rule == "ED_GROSS_NET_DEDUCTION_MISMATCH"

    def test_ed_deduction_subtracted_from_driver_pay_is_critical(self):
        """If z_rate < service_default and deduction > 0, WUD/RAD may have been
        wrongly subtracted from driver pay → CRITICAL."""
        ride = make_ride(
            payroll_batch_id=MAZ_BATCH_ID,
            source="maz",
            gross_pay="45.00",
            net_pay="41.42",
            deduction="3.58",
            z_rate="34.42",    # wrong: should be 38.00 (service default)
            service_default_rate="38.00",
            z_rate_source="service_default",
        )
        violations: list[Violation] = []
        check_ed_wud_rad(ride, violations)
        critical = [v for v in violations if v.severity == "CRITICAL"]
        assert any(v.rule == "ED_DEDUCTION_SUBTRACTED_FROM_DRIVER_PAY" for v in critical)

    def test_fa_rides_not_checked(self):
        """ED WUD/RAD checks do not apply to FA (acumen) rides."""
        ride = make_ride(
            payroll_batch_id=FA_BATCH_ID,
            source="acumen",
            gross_pay="50.00",
            net_pay="41.42",
            deduction="3.58",
        )
        violations: list[Violation] = []
        check_ed_wud_rad(ride, violations)
        assert violations == []


# ── $49.72 contamination check ─────────────────────────────────────────────────

class TestRate4972:

    def test_rate_49_72_triggers_critical(self):
        """$49.72 is the contaminated FA partner rate — any ride at this rate is CRITICAL."""
        ride = make_ride(z_rate="49.72")
        violations: list[Violation] = []
        check_rate_49_72(ride, violations)
        assert len(violations) == 1
        assert violations[0].severity == "CRITICAL"
        assert violations[0].rule == "FA_PARTNER_RATE_CONTAMINATION"

    def test_other_rates_not_flagged(self):
        """Normal rates like $38, $100, $132 do not trigger the 49.72 check."""
        for rate in ("38.00", "100.00", "132.00", "46.00"):
            ride = make_ride(z_rate=rate)
            violations: list[Violation] = []
            check_rate_49_72(ride, violations)
            assert violations == [], f"Rate ${rate} should not trigger 49.72 check"


# ── Driver summary + payout tests ─────────────────────────────────────────────

class TestDriverSummaries:

    def _make_batch_infos(self):
        return {
            FA_BATCH_ID: {"source": "acumen", "company_name": "FirstAlt"},
            MAZ_BATCH_ID: {"source": "maz", "company_name": "EverDriven"},
        }

    def test_driver_paid_when_combined_over_threshold(self):
        """Driver with combined (z_rate + carry) >= $100 gets paid."""
        rides = [make_ride(z_rate="80.00", person_id=1, payroll_batch_id=FA_BATCH_ID)]
        carry_map = {1: (Decimal("30.00"), 84)}    # $30 carry-over
        driver_codes = {1: {"full_name": "Driver A", "paycheck_code": "1001", "paycheck_code_maz": None, "active": True, "status": "active"}}
        summaries = build_driver_summaries(rides, carry_map, driver_codes, set(), self._make_batch_infos())
        assert len(summaries) == 1
        s = summaries[0]
        assert s.withheld is False
        assert s.pay_this_period == Decimal("110.00")

    def test_driver_withheld_when_combined_under_threshold(self):
        """Driver with combined < $100 is withheld."""
        rides = [make_ride(z_rate="40.00", person_id=2, payroll_batch_id=FA_BATCH_ID)]
        carry_map = {}
        driver_codes = {2: {"full_name": "Driver B", "paycheck_code": "1002", "paycheck_code_maz": None, "active": True, "status": "active"}}
        summaries = build_driver_summaries(rides, carry_map, driver_codes, set(), self._make_batch_infos())
        assert len(summaries) == 1
        assert summaries[0].withheld is True
        assert summaries[0].pay_this_period == Decimal("0.00")

    def test_driver_withheld_when_missing_code(self):
        """Driver missing paycheck_code is auto-withheld regardless of amount."""
        rides = [make_ride(z_rate="500.00", person_id=3, payroll_batch_id=FA_BATCH_ID)]
        carry_map = {}
        driver_codes = {3: {"full_name": "Driver C", "paycheck_code": None, "paycheck_code_maz": None, "active": True, "status": "active"}}
        summaries = build_driver_summaries(rides, carry_map, driver_codes, set(), self._make_batch_infos())
        assert summaries[0].withheld is True
        assert summaries[0].missing_code is True
        assert summaries[0].pay_this_period == Decimal("0.00")

    def test_driver_withheld_by_manual_override(self):
        """Driver on payroll_manual_withhold is withheld regardless of amount."""
        rides = [make_ride(z_rate="500.00", person_id=4, payroll_batch_id=FA_BATCH_ID)]
        carry_map = {}
        driver_codes = {4: {"full_name": "Driver D", "paycheck_code": "1004", "paycheck_code_maz": None, "active": True, "status": "active"}}
        summaries = build_driver_summaries(rides, carry_map, driver_codes, {4}, self._make_batch_infos())
        assert summaries[0].withheld is True
        assert summaries[0].manual_withheld is True

    def test_carry_over_included_in_combined(self):
        """Carry-over from prior week is added to z_rate total for threshold check."""
        rides = [make_ride(z_rate="60.00", person_id=5, payroll_batch_id=FA_BATCH_ID)]
        carry_map = {5: (Decimal("50.00"), 84)}
        driver_codes = {5: {"full_name": "Driver E", "paycheck_code": "1005", "paycheck_code_maz": None, "active": True, "status": "active"}}
        summaries = build_driver_summaries(rides, carry_map, driver_codes, set(), self._make_batch_infos())
        s = summaries[0]
        assert s.carry_over == Decimal("50.00")
        assert s.combined == Decimal("110.00")
        assert s.withheld is False

    def test_maz_driver_uses_paycheck_code_maz(self):
        """Maz batch checks paycheck_code_maz, not paycheck_code."""
        rides = [make_ride(
            z_rate="200.00", person_id=6,
            payroll_batch_id=MAZ_BATCH_ID,
            source="maz",
        )]
        carry_map = {}
        # Has FA code but no Maz code
        driver_codes = {6: {"full_name": "Driver F", "paycheck_code": "1006", "paycheck_code_maz": None, "active": True, "status": "active"}}
        summaries = build_driver_summaries(
            rides, carry_map, driver_codes, set(),
            {MAZ_BATCH_ID: {"source": "maz", "company_name": "EverDriven"}}
        )
        assert summaries[0].missing_code is True
        assert summaries[0].withheld is True

    def test_fa_canceled_not_paid_excluded_from_z_rate_total(self):
        """FA canceled trip with net_pay=0 should not add to driver z_rate total
        in the summary (the DB z_rate on that row is $0, so sum naturally excludes it)."""
        rides = [
            make_ride(ride_id=1, z_rate="100.00", person_id=7),
            make_ride(
                ride_id=2, z_rate="0.00", person_id=7,
                z_rate_source="canceled_trip",
                source="acumen",
                net_pay="0.00",
            ),
        ]
        carry_map = {}
        driver_codes = {7: {"full_name": "Driver G", "paycheck_code": "1007", "paycheck_code_maz": None, "active": True, "status": "active"}}
        summaries = build_driver_summaries(rides, carry_map, driver_codes, set(), self._make_batch_infos())
        assert summaries[0].z_rate_total == Decimal("100.00")


# ── Totals tests ───────────────────────────────────────────────────────────────

class TestComputeTotals:

    def test_totals_sum_correctly(self):
        from dataclasses import replace
        from scripts.audit_w15 import DriverSummary  # type: ignore
        s1 = DriverSummary(
            person_id=1, driver_name="A", paycheck_code="1001", paycheck_code_maz=None,
            batch_source="acumen", rides=5, z_rate_total=Decimal("500"), carry_over=Decimal("0"),
            combined=Decimal("500"), withheld=False, pay_this_period=Decimal("500"), missing_code=False, manual_withheld=False,
        )
        s2 = DriverSummary(
            person_id=2, driver_name="B", paycheck_code=None, paycheck_code_maz=None,
            batch_source="acumen", rides=2, z_rate_total=Decimal("80"), carry_over=Decimal("0"),
            combined=Decimal("80"), withheld=True, pay_this_period=Decimal("0"), missing_code=True, manual_withheld=False,
        )
        totals = compute_totals([s1, s2])
        assert totals["total_payout"] == Decimal("500")
        assert totals["total_withheld_balance"] == Decimal("80")
        assert int(totals["paid_count"]) == 1
        assert int(totals["withheld_count"]) == 1
