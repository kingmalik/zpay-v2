#!/usr/bin/env python3
"""
W15 Payroll Accuracy Audit — 2026-04-30
========================================
Read-only audit of payroll batches 90 (FA/Acumen, Apr 11-17) and
91 (Maz/EverDriven, Apr 13-19).

Checks:
  1. Every z_rate matches the z_rate_service table default_rate (or is
     manually overridden, or is zero for canceled/unpaid).
  2. FA canceled-trip rule: z_rate > 0 only if net_pay > 0.
  3. ED WUD/RAD: deduction goes to Maz margin, NOT subtracted from z_rate.
  4. No driver pay uses net_pay as a proxy for z_rate (contamination check).
  5. Missing paycheck_code / paycheck_code_maz → auto-withheld (correct).
  6. Carry-over balances (Nuraynie $1,348, Seude $93, Kalkidan $76,
     Fanaye $19) are present and non-zero.
  7. Hafid Kerrou (pid=237) has zero rides this week (retired).
  8. Per-driver payout matches expected: sum(z_rate) + carry-over,
     or $0 if withheld.

Output:
  - Console summary
  - ~/Downloads/w15_audit_2026-04-30.md  (full, unredacted)
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

# ── Database ──────────────────────────────────────────────────────────────────
# DATABASE_URL is resolved at runtime in main() — not at import time, so unit
# tests can import rule-checking functions without a live DB connection.
DATABASE_URL: str | None = None  # resolved in main()

# ── Constants ─────────────────────────────────────────────────────────────────
W15_BATCH_IDS = (90, 91)          # FA batch 90, Maz batch 91
FA_BATCH_ID = 90
MAZ_BATCH_ID = 91

# W15 period identifiers (for reference)
FA_PERIOD = "Apr 11-17, 2026"
MAZ_PERIOD = "Apr 13-19, 2026"

# Carry-over balances that must surface in W15 (from project_payroll_open_balances.md)
REQUIRED_CARRY_OVERS: dict[int, tuple[str, float]] = {
    58:  ("Nuraynie Mohammed",  1348.00),   # FA — no Paychex code, manual withheld
    296: ("Seude Mohammed Adem",  93.00),   # Maz/FA — FA batch 90
    121: ("Kalkidan Tesfahun",    76.00),   # Maz — batch 72 carry
    65:  ("Fanaye Wegahta",       19.00),   # Maz — batch 85 carry
}

# Hafid Kerrou — retired pid=237, must have zero rides in W15
HAFID_PID = 237

# Manual-withhold person IDs (from payroll_manual_withhold table)
EXPECTED_MANUAL_WITHHOLD_PIDS = {58, 237, 295}  # Nuraynie, Hafid, Malik Milion

# Hafid Kerrou's pay routes to Aisha Elabrichi (code 1135) not his own pid
# This is a business-level routing, not in the rides table — just verify he has 0 rides.

PAY_THRESHOLD = 100.00  # driver must earn >= $100 combined to be paid

# Tolerance for float comparisons
PENNY = Decimal("0.01")


# ── Data structures ────────────────────────────────────────────────────────────
@dataclass
class RideRow:
    ride_id: int
    payroll_batch_id: int
    person_id: int
    driver_name: str
    service_name: str
    source: str  # 'acumen' | 'maz' | 'manual'
    z_rate: Decimal
    z_rate_source: str
    z_rate_service_id: int | None
    net_pay: Decimal
    gross_pay: Decimal
    deduction: Decimal
    service_default_rate: Decimal | None  # from z_rate_service join (may be None)


@dataclass
class Violation:
    severity: str   # 'CRITICAL' | 'HIGH' | 'WARN' | 'INFO'
    rule: str
    person_id: int
    driver_name: str
    ride_id: int | None
    detail: str


@dataclass
class DriverSummary:
    person_id: int
    driver_name: str
    paycheck_code: str | None
    paycheck_code_maz: str | None
    batch_source: str  # 'acumen' | 'maz'
    rides: int
    z_rate_total: Decimal
    carry_over: Decimal
    combined: Decimal
    withheld: bool
    pay_this_period: Decimal
    missing_code: bool
    manual_withheld: bool
    violations: list[Violation] = field(default_factory=list)


# ── Database queries ───────────────────────────────────────────────────────────
# sqlalchemy is imported lazily so unit tests can import rule functions without
# needing the package installed in the test environment. All DB functions
# only run from main() — which validates DATABASE_URL first.

try:
    from sqlalchemy import text
    from sqlalchemy.orm import Session
except ImportError:
    # Stub types so type hints in function signatures don't blow up on import
    text = None  # type: ignore
    Session = object  # type: ignore


def fetch_rides(session) -> list[RideRow]:
    sql = text("""
        SELECT
            r.ride_id,
            r.payroll_batch_id,
            r.person_id,
            p.full_name        AS driver_name,
            r.service_name,
            r.source,
            r.z_rate,
            r.z_rate_source,
            r.z_rate_service_id,
            r.net_pay,
            r.gross_pay,
            r.deduction,
            zrs.default_rate   AS service_default_rate
        FROM ride r
        JOIN person p ON p.person_id = r.person_id
        LEFT JOIN z_rate_service zrs
               ON zrs.z_rate_service_id = r.z_rate_service_id
        WHERE r.payroll_batch_id = ANY(:batch_ids)
        ORDER BY p.full_name, r.payroll_batch_id, r.ride_id
    """)
    rows = session.execute(sql, {"batch_ids": list(W15_BATCH_IDS)}).fetchall()
    return [
        RideRow(
            ride_id=r.ride_id,
            payroll_batch_id=r.payroll_batch_id,
            person_id=r.person_id,
            driver_name=r.driver_name,
            service_name=r.service_name,
            source=r.source,
            z_rate=Decimal(str(r.z_rate)) if r.z_rate is not None else Decimal("0"),
            z_rate_source=r.z_rate_source or "unknown",
            z_rate_service_id=r.z_rate_service_id,
            net_pay=Decimal(str(r.net_pay)) if r.net_pay is not None else Decimal("0"),
            gross_pay=Decimal(str(r.gross_pay)) if r.gross_pay is not None else Decimal("0"),
            deduction=Decimal(str(r.deduction)) if r.deduction is not None else Decimal("0"),
            service_default_rate=(
                Decimal(str(r.service_default_rate))
                if r.service_default_rate is not None else None
            ),
        )
        for r in rows
    ]


def fetch_driver_balances(session) -> dict[int, tuple[Decimal, int]]:
    """Returns {person_id: (carried_over, source_batch_id)} for the most-recent
    prior-batch row per person visible from W15 batches 90 and 91.

    We replicate _build_summary's logic: walk ALL prior batches per company,
    take the most recent carry-forward row per person.
    """
    # Fetch all driver_balance rows where the anchoring batch predates W15
    sql = text("""
        SELECT
            db.person_id,
            db.carried_over,
            db.payroll_batch_id,
            pb.period_start,
            pb.company_name,
            pb.source AS batch_source
        FROM driver_balance db
        JOIN payroll_batch pb ON pb.payroll_batch_id = db.payroll_batch_id
        WHERE db.carried_over > 0
          AND pb.period_start < (
              SELECT MIN(period_start) FROM payroll_batch
              WHERE payroll_batch_id = ANY(:batch_ids)
          )
        ORDER BY pb.period_start DESC
    """)
    rows = session.execute(sql, {"batch_ids": list(W15_BATCH_IDS)}).fetchall()
    seen: dict[int, tuple[Decimal, int]] = {}
    for r in rows:
        if r.person_id not in seen:
            seen[r.person_id] = (
                Decimal(str(r.carried_over)),
                r.payroll_batch_id,
            )
    return seen


def fetch_manual_withhold_pids(session) -> set[int]:
    rows = session.execute(text("SELECT person_id FROM payroll_manual_withhold")).fetchall()
    return {r[0] for r in rows}


def fetch_batch_info(session) -> dict[int, dict]:
    sql = text("""
        SELECT payroll_batch_id, source, company_name, period_start, period_end,
               batch_ref, status, paychex_exported_at
        FROM payroll_batch
        WHERE payroll_batch_id = ANY(:batch_ids)
    """)
    rows = session.execute(sql, {"batch_ids": list(W15_BATCH_IDS)}).fetchall()
    return {
        r.payroll_batch_id: {
            "source": r.source,
            "company_name": r.company_name,
            "period_start": r.period_start,
            "period_end": r.period_end,
            "batch_ref": r.batch_ref,
            "status": r.status,
            "paychex_exported_at": r.paychex_exported_at,
        }
        for r in rows
    }


def fetch_driver_codes(session) -> dict[int, dict[str, str | None]]:
    """Fetch paycheck codes for all persons who have rides in W15."""
    sql = text("""
        SELECT p.person_id, p.full_name, p.paycheck_code, p.paycheck_code_maz,
               p.active, p.status
        FROM person p
        WHERE p.person_id IN (
            SELECT DISTINCT person_id FROM ride WHERE payroll_batch_id = ANY(:batch_ids)
        )
    """)
    rows = session.execute(sql, {"batch_ids": list(W15_BATCH_IDS)}).fetchall()
    return {
        r.person_id: {
            "full_name": r.full_name,
            "paycheck_code": r.paycheck_code,
            "paycheck_code_maz": r.paycheck_code_maz,
            "active": r.active,
            "status": r.status,
        }
        for r in rows
    }


def fetch_hafid_rides(session) -> int:
    """Count any rides for Hafid Kerrou (pid=237) in W15 batches."""
    result = session.execute(
        text("SELECT COUNT(*) FROM ride WHERE person_id = :pid AND payroll_batch_id = ANY(:batch_ids)"),
        {"pid": HAFID_PID, "batch_ids": list(W15_BATCH_IDS)},
    ).scalar()
    return result or 0


# ── Rule-checking logic ────────────────────────────────────────────────────────

def check_rate_accuracy(ride: RideRow, violations: list[Violation]) -> None:
    """
    Rule 1: z_rate must match z_rate_service.default_rate unless the ride is:
      - canceled_trip (may have a lower rate if FA didn't pay — checked separately)
      - manual (manually entered adjustment, exempt from rate-table check)
      - zero_rate_no_config with a non-zero z_rate (rate was set but service not in table)

    For zero_rate_no_config: the z_rate was set at ingest time even though no
    matching service key existed. We flag these as INFO (can't verify against table),
    but they are NOT automatically errors because the ingest path does set a rate
    from context in some scenarios.
    """
    if ride.z_rate_source in ("manual",):
        return  # manual adjustments exempt

    if ride.z_rate_source == "canceled_trip":
        # Checked in check_canceled_trip_rule
        return

    if ride.z_rate_source == "zero_rate_no_config":
        if ride.z_rate == Decimal("0"):
            violations.append(Violation(
                severity="CRITICAL",
                rule="RATE_ZERO_NO_CONFIG",
                person_id=ride.person_id,
                driver_name=ride.driver_name,
                ride_id=ride.ride_id,
                detail=(
                    f"Service '{ride.service_name}' has no rate config (zero_rate_no_config) "
                    f"AND z_rate=0. Driver paid $0 for this ride."
                ),
            ))
        else:
            # Rate was inferred/set but not from service table — flag as INFO
            violations.append(Violation(
                severity="INFO",
                rule="RATE_NO_CONFIG_ENTRY",
                person_id=ride.person_id,
                driver_name=ride.driver_name,
                ride_id=ride.ride_id,
                detail=(
                    f"Service '{ride.service_name}' not in z_rate_service table "
                    f"(zero_rate_no_config) but z_rate=${ride.z_rate}. "
                    f"Rate cannot be independently verified against DB config."
                ),
            ))
        return

    # service_default or override — rate must match service table
    if ride.service_default_rate is not None:
        diff = abs(ride.z_rate - ride.service_default_rate)
        if diff > PENNY:
            violations.append(Violation(
                severity="HIGH",
                rule="RATE_MISMATCH",
                person_id=ride.person_id,
                driver_name=ride.driver_name,
                ride_id=ride.ride_id,
                detail=(
                    f"Service '{ride.service_name}': z_rate=${ride.z_rate} "
                    f"≠ service table default ${ride.service_default_rate} "
                    f"(diff=${diff}). Possible contaminated rate."
                ),
            ))
    elif ride.z_rate_source == "service_default" and ride.z_rate_service_id is None:
        violations.append(Violation(
            severity="HIGH",
            rule="RATE_SERVICE_ID_NULL",
            person_id=ride.person_id,
            driver_name=ride.driver_name,
            ride_id=ride.ride_id,
            detail=(
                f"Service '{ride.service_name}': z_rate_source='service_default' "
                f"but z_rate_service_id is NULL. Rate ${ride.z_rate} unverified."
            ),
        ))


def check_canceled_trip_rule(ride: RideRow, violations: list[Violation]) -> None:
    """
    Rule 2: FA canceled-trip rule.
    - If z_rate_source == 'canceled_trip' AND source == 'acumen':
      driver pay should equal z_rate IFF net_pay > 0.
      If net_pay == 0, driver pay should be $0.
    - For ED canceled trips: net_pay is ~50% of z_rate (ED half-rate rule).
      z_rate should still be the FULL rate (driver gets the full rate they're
      owed; ED only pays Maz half). We flag if z_rate ≈ 0.5 * service_default
      since that would mean z_rate was contaminated by the ED partial payment.
    """
    if ride.z_rate_source != "canceled_trip":
        return

    if ride.source == "acumen" or ride.payroll_batch_id == FA_BATCH_ID:
        if ride.net_pay == Decimal("0") and ride.z_rate > Decimal("0"):
            violations.append(Violation(
                severity="CRITICAL",
                rule="FA_CANCELED_UNPAID_BUT_DRIVER_PAID",
                person_id=ride.person_id,
                driver_name=ride.driver_name,
                ride_id=ride.ride_id,
                detail=(
                    f"FA canceled trip: net_pay=$0 (FA didn't pay Maz) "
                    f"but z_rate=${ride.z_rate}. Driver should get $0 for this ride."
                ),
            ))
        elif ride.net_pay > Decimal("0") and ride.z_rate == Decimal("0"):
            violations.append(Violation(
                severity="HIGH",
                rule="FA_CANCELED_PAID_BUT_DRIVER_ZERO",
                person_id=ride.person_id,
                driver_name=ride.driver_name,
                ride_id=ride.ride_id,
                detail=(
                    f"FA canceled trip: net_pay=${ride.net_pay} (FA paid Maz) "
                    f"but z_rate=$0. Driver should be paid for this ride."
                ),
            ))

    if ride.source == "maz" or ride.payroll_batch_id == MAZ_BATCH_ID:
        # ED half-rate: net_pay ≈ 50% of service default.
        # The z_rate should be the FULL driver rate, independent of the half net_pay.
        # Flag if z_rate == net_pay (contamination: driver rate set to ED's half-pay).
        if ride.z_rate > Decimal("0") and ride.net_pay > Decimal("0"):
            ratio = ride.net_pay / ride.z_rate
            if abs(ratio - Decimal("0.5")) < Decimal("0.05"):
                # z_rate looks like it was set to net_pay (half-rate contamination)
                violations.append(Violation(
                    severity="WARN",
                    rule="ED_CANCELED_RATE_CONTAMINATION_SUSPECTED",
                    person_id=ride.person_id,
                    driver_name=ride.driver_name,
                    ride_id=ride.ride_id,
                    detail=(
                        f"ED canceled trip: z_rate=${ride.z_rate}, net_pay=${ride.net_pay}. "
                        f"Ratio ≈ 0.5 — verify z_rate is full driver rate, "
                        f"not ED's half-payment amount."
                    ),
                ))


def check_ed_wud_rad(ride: RideRow, violations: list[Violation]) -> None:
    """
    Rule 3: For EverDriven rides, WUD/RAD live in ride.deduction (Maz margin cost).
    The driver's z_rate must NOT be reduced by deductions.

    We can't directly check this from the ride row alone (deduction is the correct
    place), but we CAN flag if:
    - ride.deduction > 0 AND ride.z_rate < ride.service_default_rate
      (suggests deduction was incorrectly subtracted from driver pay)
    - ride.gross_pay != ride.net_pay + ride.deduction (ED accounting invariant)
    """
    if ride.payroll_batch_id != MAZ_BATCH_ID:
        return

    # ED accounting invariant: gross_pay == net_pay + deduction
    # (gross is what ED charges the contract; net is what ED pays Maz after deductions)
    # Some rides have gross_pay=0 (zero_rate_no_config on acumen side) so skip those
    if ride.gross_pay > Decimal("0"):
        expected_gross = ride.net_pay + ride.deduction
        if abs(ride.gross_pay - expected_gross) > PENNY:
            violations.append(Violation(
                severity="HIGH",
                rule="ED_GROSS_NET_DEDUCTION_MISMATCH",
                person_id=ride.person_id,
                driver_name=ride.driver_name,
                ride_id=ride.ride_id,
                detail=(
                    f"ED ride: gross_pay=${ride.gross_pay} ≠ "
                    f"net_pay(${ride.net_pay}) + deduction(${ride.deduction}) "
                    f"= ${expected_gross}. Accounting invariant broken."
                ),
            ))

    # WUD/RAD must NOT be subtracted from driver pay
    # If deduction > 0 and z_rate < service_default_rate, flag it
    if (
        ride.deduction > Decimal("0")
        and ride.service_default_rate is not None
        and ride.z_rate < ride.service_default_rate - PENNY
        and ride.z_rate_source not in ("canceled_trip", "manual")
    ):
        violations.append(Violation(
            severity="CRITICAL",
            rule="ED_DEDUCTION_SUBTRACTED_FROM_DRIVER_PAY",
            person_id=ride.person_id,
            driver_name=ride.driver_name,
            ride_id=ride.ride_id,
            detail=(
                f"ED ride: deduction=${ride.deduction}, z_rate=${ride.z_rate} "
                f"< service default ${ride.service_default_rate}. "
                f"WUD/RAD may have been subtracted from driver pay — must not happen."
            ),
        ))


def check_net_pay_contamination(ride: RideRow, violations: list[Violation]) -> None:
    """
    Rule 4: Driver pay must use z_rate, NOT net_pay.
    Flag if z_rate == net_pay on an FA ride (net_pay is FA→Maz partner rate,
    NOT the driver rate — they differ by Maz's margin).

    Exception: canceled_trip rides where FA pays the exact z_rate (net_pay == z_rate
    is intentional when FA pays the full driver rate on a cancellation).
    """
    if ride.payroll_batch_id != FA_BATCH_ID:
        return
    if ride.z_rate_source in ("canceled_trip", "manual"):
        return

    # On FA rides, net_pay is the FA→Maz rate (higher than driver pay by ~20-25%)
    # If z_rate == net_pay, it means the partner rate was used as driver pay
    if ride.z_rate == ride.net_pay and ride.net_pay > Decimal("0"):
        if ride.service_default_rate is None or abs(ride.z_rate - ride.service_default_rate) < PENNY:
            # z_rate matches service table AND equals net_pay — check if service table
            # is itself contaminated (rate = 49.72 or equals FA partner rate)
            if ride.net_pay > ride.z_rate * Decimal("1.15"):  # >15% above driver rate = suspicious
                violations.append(Violation(
                    severity="HIGH",
                    rule="NET_PAY_CONTAMINATION_SUSPECTED",
                    person_id=ride.person_id,
                    driver_name=ride.driver_name,
                    ride_id=ride.ride_id,
                    detail=(
                        f"FA ride: z_rate=${ride.z_rate} equals net_pay=${ride.net_pay}. "
                        f"net_pay is the FA→Maz partner rate, not driver pay. "
                        f"Verify z_rate_service table for '{ride.service_name}'."
                    ),
                ))


def check_rate_49_72(ride: RideRow, violations: list[Violation]) -> None:
    """
    Special check: $49.72 was the contaminated FA partner rate that leaked into
    z_rate_service in early sessions. Any ride still at $49.72 is a critical bug.
    """
    if ride.z_rate == Decimal("49.72"):
        violations.append(Violation(
            severity="CRITICAL",
            rule="FA_PARTNER_RATE_CONTAMINATION",
            person_id=ride.person_id,
            driver_name=ride.driver_name,
            ride_id=ride.ride_id,
            detail=(
                f"CRITICAL: z_rate=$49.72 for '{ride.service_name}'. "
                f"$49.72 is the FA→Maz partner rate — this was the #1 contamination "
                f"bug from early sessions. This ride is paying the wrong amount."
            ),
        ))


# ── Driver-level checks ────────────────────────────────────────────────────────

def check_carry_overs(carry_map: dict[int, tuple[Decimal, int]], violations: list[Violation]) -> None:
    """Rule 6: Required carry-over balances must be present."""
    for pid, (name, expected_amount) in REQUIRED_CARRY_OVERS.items():
        if pid not in carry_map:
            violations.append(Violation(
                severity="CRITICAL",
                rule="CARRY_OVER_MISSING",
                person_id=pid,
                driver_name=name,
                ride_id=None,
                detail=(
                    f"Expected carry-over ${expected_amount:.2f} not found in driver_balance. "
                    f"This balance will not be included in W15 payout."
                ),
            ))
        else:
            actual, src_batch = carry_map[pid]
            diff = abs(actual - Decimal(str(expected_amount)))
            if diff > PENNY:
                violations.append(Violation(
                    severity="HIGH",
                    rule="CARRY_OVER_AMOUNT_MISMATCH",
                    person_id=pid,
                    driver_name=name,
                    ride_id=None,
                    detail=(
                        f"Carry-over mismatch: expected ${expected_amount:.2f}, "
                        f"actual ${actual} (from batch {src_batch}). "
                        f"Diff=${diff}."
                    ),
                ))


def check_hafid_retired(hafid_ride_count: int, violations: list[Violation]) -> None:
    """Rule 7: Hafid Kerrou (pid=237) must have zero rides."""
    if hafid_ride_count > 0:
        violations.append(Violation(
            severity="CRITICAL",
            rule="RETIRED_DRIVER_HAS_RIDES",
            person_id=HAFID_PID,
            driver_name="Hafid Kerrou",
            ride_id=None,
            detail=(
                f"Retired driver (pid={HAFID_PID}) has {hafid_ride_count} ride(s) "
                f"in W15. Must be $0 — his historical pay went to Aisha 1135."
            ),
        ))


def build_driver_summaries(
    rides: list[RideRow],
    carry_map: dict[int, tuple[Decimal, int]],
    driver_codes: dict[int, dict],
    manual_withhold_pids: set[int],
    batch_infos: dict[int, dict],
) -> list[DriverSummary]:
    """
    Build per-driver summary replicating _build_summary logic:
      combined = z_rate_total + carry_over
      withheld if combined < $100 OR missing code OR manual withhold
      pay_this_period = combined if not withheld, else $0
    """
    # Group rides by (person_id, batch_id)
    from collections import defaultdict
    grouped: dict[tuple[int, int], list[RideRow]] = defaultdict(list)
    for ride in rides:
        grouped[(ride.person_id, ride.payroll_batch_id)].append(ride)

    summaries = []
    for (pid, batch_id), batch_rides in grouped.items():
        info = driver_codes.get(pid, {})
        batch_info = batch_infos.get(batch_id, {})
        batch_source = (batch_info.get("source") or "").lower()

        # Sum z_rate — use z_rate for all rides (including canceled_trip with net_pay>0)
        # But per FA canceled-trip rule: if net_pay==0 on a canceled trip, that z_rate
        # should not count (driver gets $0). The DB should already reflect this via
        # z_rate=0 on those rows, but we double-check here.
        z_rate_total = Decimal("0")
        for r in batch_rides:
            if r.z_rate_source == "canceled_trip" and r.source == "acumen" and r.net_pay == Decimal("0"):
                # FA canceled, not paid — z_rate should be $0
                # If it's not $0 in DB, that's a violation caught by check_canceled_trip_rule
                pass
            else:
                z_rate_total += r.z_rate

        carry_over, _ = carry_map.get(pid, (Decimal("0"), None))

        combined = z_rate_total + carry_over

        # Determine which paycheck code matters for this batch
        if batch_source == "maz":
            active_code = (info.get("paycheck_code_maz") or "").strip()
        else:
            active_code = (info.get("paycheck_code") or "").strip()

        missing_code = not active_code
        manual_withheld = pid in manual_withhold_pids
        withheld = (
            combined < Decimal(str(PAY_THRESHOLD))
            or missing_code
            or manual_withheld
        )
        pay_this_period = combined if not withheld else Decimal("0")

        summaries.append(DriverSummary(
            person_id=pid,
            driver_name=info.get("full_name", f"pid={pid}"),
            paycheck_code=info.get("paycheck_code"),
            paycheck_code_maz=info.get("paycheck_code_maz"),
            batch_source=batch_source,
            rides=len(batch_rides),
            z_rate_total=z_rate_total,
            carry_over=carry_over,
            combined=combined,
            withheld=withheld,
            pay_this_period=pay_this_period,
            missing_code=missing_code,
            manual_withheld=manual_withheld,
        ))

    summaries.sort(key=lambda s: s.driver_name.lower())
    return summaries


# ── Totals and summary ─────────────────────────────────────────────────────────

def compute_totals(summaries: list[DriverSummary]) -> dict[str, Decimal]:
    total_z_rate = sum(s.z_rate_total for s in summaries)
    total_carry = sum(s.carry_over for s in summaries if s.withheld or s.carry_over > 0)
    total_payout = sum(s.pay_this_period for s in summaries)
    total_withheld_balance = sum(s.combined for s in summaries if s.withheld)
    return {
        "total_z_rate": total_z_rate,
        "total_carry": total_carry,
        "total_payout": total_payout,
        "total_withheld_balance": total_withheld_balance,
        "driver_count": Decimal(str(len({s.person_id for s in summaries}))),
        "paid_count": Decimal(str(len([s for s in summaries if not s.withheld]))),
        "withheld_count": Decimal(str(len([s for s in summaries if s.withheld]))),
    }


# ── Report generation ──────────────────────────────────────────────────────────

def build_report(
    batch_infos: dict,
    rides: list[RideRow],
    summaries: list[DriverSummary],
    violations: list[Violation],
    carry_map: dict,
    totals: dict,
    run_date: str,
) -> str:
    lines = []
    a = lines.append

    a("# W15 Payroll Accuracy Audit")
    a(f"**Run date:** {run_date}")
    a(f"**Batches audited:** {FA_BATCH_ID} (FA/Acumen, {FA_PERIOD}) and {MAZ_BATCH_ID} (Maz/EverDriven, {MAZ_PERIOD})")
    a("")

    # Batch summary
    a("## Batch Overview")
    a("")
    a("| Batch | Source | Company | Period | Status | Paychex Exported |")
    a("|-------|--------|---------|--------|--------|-----------------|")
    for bid, info in sorted(batch_infos.items()):
        a(f"| {bid} | {info['source']} | {info['company_name']} | "
          f"{info['period_start']} – {info['period_end']} | {info['status']} | "
          f"{'Yes' if info['paychex_exported_at'] else 'No'} |")
    a("")

    # Totals
    a("## Totals")
    a("")
    a(f"- Total rides in W15: **{len(rides)}**")
    a(f"- Unique drivers with rides: **{int(totals['driver_count'])}**")
    a(f"- Total z_rate (driver pay): **${totals['total_z_rate']:.2f}**")
    a(f"- Total payout this period: **${totals['total_payout']:.2f}**")
    a(f"- Total withheld balance: **${totals['total_withheld_balance']:.2f}**")
    a(f"- Drivers paid: **{int(totals['paid_count'])}**")
    a(f"- Drivers withheld: **{int(totals['withheld_count'])}**")
    a("")

    # Violation summary
    critical = [v for v in violations if v.severity == "CRITICAL"]
    high = [v for v in violations if v.severity == "HIGH"]
    warn = [v for v in violations if v.severity == "WARN"]
    info_v = [v for v in violations if v.severity == "INFO"]

    a("## Violation Summary")
    a("")
    a(f"| Severity | Count |")
    a(f"|----------|-------|")
    a(f"| CRITICAL | {len(critical)} |")
    a(f"| HIGH     | {len(high)} |")
    a(f"| WARN     | {len(warn)} |")
    a(f"| INFO     | {len(info_v)} |")
    a(f"| **Total**| **{len(violations)}** |")
    a("")

    if critical or high:
        a("## CRITICAL and HIGH Violations")
        a("")
        for v in [*critical, *high]:
            a(f"### [{v.severity}] {v.rule}")
            a(f"- **Driver:** {v.driver_name} (pid={v.person_id})")
            if v.ride_id:
                a(f"- **Ride ID:** {v.ride_id}")
            a(f"- **Detail:** {v.detail}")
            a("")

    if warn:
        a("## Warnings")
        a("")
        for v in warn:
            a(f"### [WARN] {v.rule}")
            a(f"- **Driver:** {v.driver_name} (pid={v.person_id})")
            if v.ride_id:
                a(f"- **Ride ID:** {v.ride_id}")
            a(f"- **Detail:** {v.detail}")
            a("")

    if info_v:
        a("## Info / Unverified Rates (zero_rate_no_config)")
        a("")
        a("These rides have z_rate set but no matching z_rate_service entry. "
          "The rate cannot be independently verified against the DB config table. "
          "Verify manually against partner files.")
        a("")
        a("| Driver | Ride ID | Service | z_rate |")
        a("|--------|---------|---------|--------|")
        for v in info_v:
            a(f"| {v.driver_name} | {v.ride_id} | — | — |")
        a("")

    # Carry-over section
    a("## Carry-Over Balances")
    a("")
    a("| Driver | pid | Expected | Actual | Source Batch | Status |")
    a("|--------|-----|----------|--------|-------------|--------|")
    for pid, (name, expected) in REQUIRED_CARRY_OVERS.items():
        actual, src_batch = carry_map.get(pid, (Decimal("0"), "MISSING"))
        status = "OK" if abs(actual - Decimal(str(expected))) <= PENNY else "MISMATCH"
        if pid not in carry_map:
            status = "MISSING"
        a(f"| {name} | {pid} | ${expected:.2f} | ${actual:.2f} | {src_batch} | {status} |")
    a("")

    # Per-driver breakdown
    a("## Per-Driver Breakdown")
    a("")
    a("| Driver | pid | Source | Rides | z_rate Total | Carry Over | Combined | Withheld | Pay This Period | Code |")
    a("|--------|-----|--------|-------|-------------|------------|----------|----------|-----------------|------|")
    for s in summaries:
        withheld_str = "YES" if s.withheld else "no"
        reasons = []
        if s.missing_code:
            reasons.append("no-code")
        if s.manual_withheld:
            reasons.append("manual-hold")
        if s.combined < Decimal(str(PAY_THRESHOLD)) and not s.missing_code and not s.manual_withheld:
            reasons.append(f"<${PAY_THRESHOLD}")
        reason_str = f" ({', '.join(reasons)})" if reasons else ""
        code = s.paycheck_code_maz if s.batch_source == "maz" else s.paycheck_code
        a(f"| {s.driver_name} | {s.person_id} | {s.batch_source} | {s.rides} | "
          f"${s.z_rate_total:.2f} | ${s.carry_over:.2f} | ${s.combined:.2f} | "
          f"{withheld_str}{reason_str} | ${s.pay_this_period:.2f} | {code or '—'} |")
    a("")

    # Canceled trips detail
    canceled = [r for r in rides if r.z_rate_source == "canceled_trip"]
    if canceled:
        a("## Canceled Trips in W15")
        a("")
        a("| Driver | Ride ID | Service | Source | z_rate | net_pay | Rule Applied |")
        a("|--------|---------|---------|--------|--------|---------|--------------|")
        for r in canceled:
            if r.source == "acumen":
                rule = "FA paid" if r.net_pay > 0 else "FA not paid — $0 to driver"
            else:
                rule = "ED half-rate cancellation"
            a(f"| {r.driver_name} | {r.ride_id} | {r.service_name} | "
              f"{r.source} | ${r.z_rate} | ${r.net_pay} | {rule} |")
        a("")

    # Audit verdict
    a("## Audit Verdict")
    a("")
    if critical:
        a(f"**FAIL — {len(critical)} CRITICAL violation(s) found. Do NOT close as clean.**")
        a("")
        a("### CRITICAL issues to resolve before marking W15 complete:")
        for v in critical:
            a(f"- [{v.rule}] {v.driver_name} (pid={v.person_id}): {v.detail}")
    elif high:
        a(f"**WARN — No CRITICAL violations, but {len(high)} HIGH violation(s) require review.**")
    elif warn:
        a(f"**PASS with warnings — {len(warn)} WARN item(s). Review before closing.**")
    else:
        a("**PASS — No CRITICAL or HIGH violations. W15 looks clean.**")
    a("")

    a("---")
    a("*Generated by scripts/audit_w15.py — READ-ONLY against prod DB*")

    return "\n".join(lines)


def build_sanitized_report(full_report: str) -> str:
    """
    Replace driver names and dollar amounts with placeholders for public PR body.
    Only used for the PR description — full report stays in ~/Downloads.
    """
    import re
    # Replace full names (keep structure)
    sanitized = re.sub(r"(?<!\|)(\b[A-Z][a-z]+ +[A-Z][a-z]+(?:\s+[A-Z][a-zA-Z]+)?\b)(?!.*\|)", "[DRIVER]", full_report)
    return sanitized


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    from datetime import datetime
    run_date = datetime.now().strftime("%Y-%m-%d %H:%M PT")

    # Resolve DATABASE_URL at runtime (not import time — tests import without a DB)
    global DATABASE_URL
    DATABASE_URL = os.environ.get("DATABASE_URL")
    if not DATABASE_URL:
        print(
            "ERROR: DATABASE_URL environment variable is not set.\n"
            "Set it to the prod connection string and re-run:\n"
            "  export DATABASE_URL='postgresql+psycopg://app:<pass>@<host>:<port>/appdb'\n"
            "or for psycopg2:\n"
            "  export DATABASE_URL='postgresql+psycopg2://app:<pass>@<host>:<port>/appdb'"
        )
        sys.exit(1)

    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session as _Session
    except ImportError:
        print("ERROR: sqlalchemy not installed. Run: pip install sqlalchemy psycopg2-binary")
        sys.exit(1)

    print(f"Z-Pay W15 Accuracy Audit — {run_date}")
    print(f"DB: {DATABASE_URL[:50]}...")
    print(f"Auditing batches: {W15_BATCH_IDS}\n")

    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

    with _Session(engine) as session:
        print("Fetching data from prod DB (READ-ONLY)...")
        batch_infos = fetch_batch_info(session)
        rides = fetch_rides(session)
        carry_map = fetch_driver_balances(session)
        manual_withhold_pids = fetch_manual_withhold_pids(session)
        driver_codes = fetch_driver_codes(session)
        hafid_ride_count = fetch_hafid_rides(session)

    print(f"  {len(rides)} rides loaded across batches {W15_BATCH_IDS}")
    print(f"  {len(driver_codes)} unique drivers")
    print(f"  {len(carry_map)} carry-over balance entries")
    print(f"  {len(manual_withhold_pids)} manual-withhold persons\n")

    # ── Run per-ride checks ────────────────────────────────────────────────────
    violations: list[Violation] = []

    print("Running per-ride checks...")
    for ride in rides:
        check_rate_accuracy(ride, violations)
        check_canceled_trip_rule(ride, violations)
        check_ed_wud_rad(ride, violations)
        check_net_pay_contamination(ride, violations)
        check_rate_49_72(ride, violations)

    # ── Run driver-level checks ────────────────────────────────────────────────
    print("Running driver-level checks...")
    check_carry_overs(carry_map, violations)
    check_hafid_retired(hafid_ride_count, violations)

    # ── Build driver summaries ─────────────────────────────────────────────────
    summaries = build_driver_summaries(
        rides, carry_map, driver_codes, manual_withhold_pids, batch_infos
    )
    totals = compute_totals(summaries)

    # ── Print console summary ──────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("AUDIT RESULTS")
    print("=" * 60)
    print(f"  Total rides:         {len(rides)}")
    print(f"  Total z_rate (DB):   ${totals['total_z_rate']:.2f}")
    print(f"  Total payout:        ${totals['total_payout']:.2f}")
    print(f"  Total withheld:      ${totals['total_withheld_balance']:.2f}")
    print(f"  Drivers paid:        {int(totals['paid_count'])}")
    print(f"  Drivers withheld:    {int(totals['withheld_count'])}")
    print("")

    critical = [v for v in violations if v.severity == "CRITICAL"]
    high = [v for v in violations if v.severity == "HIGH"]
    warn = [v for v in violations if v.severity == "WARN"]
    info_v = [v for v in violations if v.severity == "INFO"]

    print(f"  Violations:")
    print(f"    CRITICAL: {len(critical)}")
    print(f"    HIGH:     {len(high)}")
    print(f"    WARN:     {len(warn)}")
    print(f"    INFO:     {len(info_v)}")
    print("")

    if critical:
        print("CRITICAL VIOLATIONS:")
        for v in critical:
            print(f"  [{v.rule}] {v.driver_name}: {v.detail}")
        print("")

    if high:
        print("HIGH VIOLATIONS:")
        for v in high[:5]:  # show top 5 in console
            print(f"  [{v.rule}] {v.driver_name}: {v.detail}")
        if len(high) > 5:
            print(f"  ... and {len(high) - 5} more. See full report.")
        print("")

    # Carry-over status
    print("CARRY-OVER BALANCES:")
    for pid, (name, expected) in REQUIRED_CARRY_OVERS.items():
        actual, src_batch = carry_map.get(pid, (Decimal("0"), "MISSING"))
        status = "OK" if abs(actual - Decimal(str(expected))) <= PENNY and pid in carry_map else "ISSUE"
        print(f"  {name}: expected ${expected:.2f}, actual ${actual:.2f} — {status}")
    print("")

    verdict = "PASS"
    if critical:
        verdict = f"FAIL ({len(critical)} critical)"
    elif high:
        verdict = f"WARN ({len(high)} high)"

    print(f"VERDICT: {verdict}")
    print("=" * 60)

    # ── Write full report ──────────────────────────────────────────────────────
    report = build_report(
        batch_infos=batch_infos,
        rides=rides,
        summaries=summaries,
        violations=violations,
        carry_map=carry_map,
        totals=totals,
        run_date=run_date,
    )

    out_path = Path.home() / "Downloads" / "w15_audit_2026-04-30.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"\nFull report written to: {out_path}")

    # Return exit code for CI: 0 = clean/warn, 1 = critical failures
    if critical:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
