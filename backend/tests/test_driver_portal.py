"""
backend/tests/test_driver_portal.py
=====================================
Tests for GET /api/public/driver/{person_id}/portal

Run with:
    PYTHONPATH=. pytest backend/tests/test_driver_portal.py -x -v

Strategy: patch compute_driver_scorecard + individual DB calls — no real
Postgres needed. All tests call _portal_response() directly (no HTTP layer).

Test matrix
-----------
 1. 200 with valid driver and rides — verifies response shape
 2. 404 with missing driver (no Person row)
 3. Response NEVER contains: last name, paycheck_code, paycheck_code_maz, internal IDs
 4. held_balance reflects the scalar returned by the held-total query
 5. current_week.withheld = True when driver has a carried_over balance > 0
 6. recent_weeks max 3 entries (prior batches, not the current one)
 7. Portal route is registered on the router exactly once
"""

from __future__ import annotations

import json
import os
import sys
from decimal import Decimal
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.routes.public import _portal_response
from backend.services.driver_scorecard import (
    AxisScore,
    DriverScorecard,
    AXIS_WEIGHTS,
)


# ── Fixture helpers ───────────────────────────────────────────────────────────

def _make_person(
    person_id: int = 1,
    full_name: str = "Ahmed Abdi",
    paycheck_code: str = "1099",
    paycheck_code_maz: Optional[str] = "2055",
) -> MagicMock:
    p = MagicMock()
    p.person_id = person_id
    p.full_name = full_name
    p.paycheck_code = paycheck_code
    p.paycheck_code_maz = paycheck_code_maz
    return p


def _make_scorecard(
    person_id: int = 1,
    tier: str = "silver",
    composite: Optional[float] = 82.0,
) -> DriverScorecard:
    from datetime import date
    ws = date(2026, 4, 28)
    week_iso = f"{ws.isocalendar().year}-W{ws.isocalendar().week:02d}"
    axes = {
        k: AxisScore(
            name=k,
            raw_value=0.85,
            normalized_value=0.85,
            weight=AXIS_WEIGHTS.get(k, 0.0),
            weighted_score=0.85 * AXIS_WEIGHTS.get(k, 0.0) * 100,
            sample_size=5,
            available=True,
            low_confidence=False,
        )
        for k in AXIS_WEIGHTS
    }
    return DriverScorecard(
        person_id=person_id,
        driver_name="Ahmed Abdi",
        week_start=ws,
        week_iso=week_iso,
        total_trips=8,
        axes=axes,
        composite_score=composite,
        tier=tier,
        tier_label="Tier 2",
        low_sample=False,
        week_over_week_delta=None,
        headline_metric="",
        focus_area="",
        revenue_impact=0.0,
        revenue_impact_per_trip=0.0,
        revenue_rank=None,
    )


def _make_batch(
    batch_id: int = 10,
    source: str = "acumen",
) -> MagicMock:
    from datetime import date
    b = MagicMock()
    b.payroll_batch_id = batch_id
    b.source = source
    b.week_start = date(2026, 4, 21)
    b.period_start = date(2026, 4, 21)
    b.period_end = date(2026, 4, 25)
    return b


def _make_balance(carried_over: float) -> MagicMock:
    bm = MagicMock()
    bm.carried_over = Decimal(str(carried_over))
    return bm


def _build_mock_db(
    person: Optional[MagicMock],
    batches: list,
    latest_ride_result: tuple,       # (count, z_rate_sum) for latest batch
    latest_balance: Optional[float], # carried_over for latest batch (None = no row)
    held_total: float,               # scalar for total held query
    history_rides: list,             # [(count, z_rate_sum)] for history batches
    history_balances: list,          # [float | None] for history batches
) -> MagicMock:
    """
    Build a mock DB that returns the right results in order.

    Query order in _portal_response:
      0: Person lookup          → .first() = person
      1: recent batches list    → .all() = batches
      2: latest ride count/sum  → .first() = (count, z_rate)
      3: latest balance row     → .first() = balance row | None
      4: held total             → .scalar() = held_total
      5+: per-history-batch pairs of (ride count/sum, balance row)
          for each history batch: ride .first(), balance .first()
          also week-label scalar per batch
    """
    db = MagicMock()
    call_idx = [0]

    def _make_q():
        q = MagicMock()
        q.filter.return_value = q
        q.join.return_value = q
        q.group_by.return_value = q
        q.order_by.return_value = q
        q.limit.return_value = q
        return q

    def query_side(*args):
        idx = call_idx[0]
        call_idx[0] += 1
        q = _make_q()

        if idx == 0:
            # Person lookup
            q.first.return_value = person

        elif idx == 1:
            # Batch list
            q.all.return_value = batches

        elif idx == 2:
            # Ride count/sum for latest batch
            c, s = latest_ride_result
            q.first.return_value = (c, Decimal(str(s)))

        elif idx == 3:
            # Balance row for latest batch
            if latest_balance is not None:
                q.first.return_value = _make_balance(latest_balance)
            else:
                q.first.return_value = None

        elif idx == 4:
            # Held total scalar
            q.scalar.return_value = Decimal(str(held_total))

        else:
            # History batches: pairs of (ride, balance) then optional week-label scalar
            # idx 5 = history[0] ride, 6 = history[0] balance
            # idx 7 = history[1] ride, 8 = history[1] balance  ... etc.
            history_idx = idx - 5
            batch_i = history_idx // 2
            sub_i = history_idx % 2

            if batch_i < len(history_rides):
                if sub_i == 0:
                    c, s = history_rides[batch_i]
                    q.first.return_value = (c, Decimal(str(s)))
                else:
                    hbal = history_balances[batch_i] if batch_i < len(history_balances) else None
                    if hbal is not None:
                        q.first.return_value = _make_balance(hbal)
                    else:
                        q.first.return_value = None
            else:
                q.first.return_value = None
                q.scalar.return_value = 1

        return q

    db.query.side_effect = query_side
    return db


def _run(
    person_id: int,
    person: Optional[MagicMock],
    batches: list,
    latest_ride: tuple = (8, 640.00),
    latest_balance: Optional[float] = None,
    held_total: float = 0.0,
    history_rides: Optional[list] = None,
    history_balances: Optional[list] = None,
    scorecard_tier: str = "silver",
) -> tuple:
    sc = _make_scorecard(person_id=person_id, tier=scorecard_tier)

    # Patch _batch_week_label so it doesn't need real DB queries for week numbers
    with patch("backend.routes.public.compute_driver_scorecard", return_value=sc), \
         patch("backend.routes.public._batch_week_label", return_value="Week 16"):

        db = _build_mock_db(
            person=person,
            batches=batches,
            latest_ride_result=latest_ride,
            latest_balance=latest_balance,
            held_total=held_total,
            history_rides=history_rides or [],
            history_balances=history_balances or [],
        )
        response = _portal_response(person_id, db)

    return response, json.loads(response.body)


# ── Test 1: 200 with valid driver ─────────────────────────────────────────────

def test_portal_200_valid_driver():
    person = _make_person(person_id=10, full_name="Ahmed Abdi")
    batches = [_make_batch(batch_id=50)]

    resp, body = _run(
        person_id=10,
        person=person,
        batches=batches,
        latest_ride=(8, 640.00),
    )

    assert resp.status_code == 200
    assert "driver" in body
    assert "current_week" in body
    assert "held_balance" in body
    assert "recent_weeks" in body
    assert "scorecard_url" in body
    assert body["driver"]["name"] == "Ahmed"
    assert body["driver"]["tier"] == "silver"
    assert body["scorecard_url"] == f"/driver/10/scorecard"


# ── Test 2: 404 with missing driver ──────────────────────────────────────────

def test_portal_404_missing_driver():
    db = MagicMock()
    q = MagicMock()
    db.query.return_value = q
    q.filter.return_value = q
    q.first.return_value = None

    with patch("backend.routes.public.compute_driver_scorecard"):
        response = _portal_response(9999, db)

    assert response.status_code == 404
    body = json.loads(response.body)
    assert "error" in body


# ── Test 3: Response never exposes private fields ─────────────────────────────

def test_portal_no_private_fields():
    """Last name, paycheck_code, paycheck_code_maz must not appear anywhere in the body."""
    person = _make_person(
        person_id=7,
        full_name="Fatuma Hassan",
        paycheck_code="1042",
        paycheck_code_maz="2033",
    )
    batches = [_make_batch(batch_id=99)]

    resp, body = _run(
        person_id=7,
        person=person,
        batches=batches,
        latest_ride=(6, 480.00),
    )

    raw = resp.body.decode()

    assert "paycheck_code" not in raw, "paycheck_code must never appear in portal response"
    assert "1042" not in raw, "paycheck_code value must never appear"
    assert "2033" not in raw, "paycheck_code_maz value must never appear"
    assert "Hassan" not in raw, "last name must not appear — first name only"
    assert "person_id" not in raw, "internal person_id must not appear as a response key"
    assert body["driver"]["name"] == "Fatuma"


# ── Test 4: held_balance reflects the total from DB ──────────────────────────

def test_portal_held_balance_matches_db_scalar():
    """held_balance must equal whatever the DB scalar returns for the sum query."""
    person = _make_person(person_id=20, full_name="Nuraynie Mohammed")
    batches = [_make_batch(batch_id=101)]

    # held_total = $348 (representing cumulative unpaid balance across prior batches)
    resp, body = _run(
        person_id=20,
        person=person,
        batches=batches,
        latest_ride=(5, 255.00),
        latest_balance=255.00,
        held_total=348.00,
    )

    assert resp.status_code == 200
    assert body["held_balance"] == 348.00


# ── Test 5: withheld = True when driver has carried_over balance ──────────────

def test_portal_withheld_true_when_carried_over():
    """current_week.withheld is True when the latest batch balance row has carried_over > 0."""
    person = _make_person(person_id=30, full_name="Seude Ahmed")
    batches = [_make_batch(batch_id=200)]

    resp, body = _run(
        person_id=30,
        person=person,
        batches=batches,
        latest_ride=(3, 76.00),
        latest_balance=76.00,
        held_total=76.00,
    )

    assert resp.status_code == 200
    assert body["current_week"]["withheld"] is True
    assert body["current_week"]["withheld_amount"] == 76.00
    assert body["current_week"]["paid_this_period"] == 0.00


# ── Test 6: recent_weeks max 3, only prior batches ────────────────────────────

def test_portal_recent_weeks_max_3():
    """recent_weeks must contain at most 3 entries (prior batches, not the latest)."""
    person = _make_person(person_id=40, full_name="Omar Farah")

    # 4 batches returned: latest + 3 prior
    batches = [_make_batch(batch_id=300 + i) for i in range(4)]
    history_rides = [(5 + i, 400.00 + i * 50) for i in range(3)]

    resp, body = _run(
        person_id=40,
        person=person,
        batches=batches,
        latest_ride=(8, 640.00),
        history_rides=history_rides,
        history_balances=[None, None, None],
    )

    assert resp.status_code == 200
    # Must not exceed 3 prior weeks
    assert len(body["recent_weeks"]) <= 3


# ── Test 7: Route is registered on the public router ─────────────────────────

def test_portal_route_registered():
    """Portal route must be registered exactly once on the public router."""
    from backend.routes.public import router

    portal_routes = [
        r for r in router.routes
        if hasattr(r, "path") and r.path == "/api/public/driver/{person_id}/portal"
    ]
    assert len(portal_routes) == 1, "Portal route must be registered exactly once"
    assert portal_routes[0].endpoint.__name__ == "public_driver_portal"
