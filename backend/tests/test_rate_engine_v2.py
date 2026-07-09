"""
Tests for backend/services/rate_engine_v2.py — two-tier resolution.

Run with:
    PYTHONPATH=. pytest backend/tests/test_rate_engine_v2.py -x -v

Pure resolver tests against synthetic ServiceProfile pools, seeded with the
master plan's named regression cases (Risalah suffix churn, Kent-Meridian
season-boundary 17→02, ER/ODT).
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.services.rate_engine_v2 import (
    MODE_LIVE,
    MODE_OFF,
    MODE_SHADOW,
    TIER_DISTANCE,
    TIER_IDENTITY,
    TIER_NONE,
    ServiceProfile,
    resolve_rate_v2,
    v2_mode,
)
from backend.services.route_identity import parse_route_identity


def _profile(name: str, rate: str, rides: int = 50, miles: float | None = 10.0) -> ServiceProfile:
    ident = parse_route_identity(name)
    assert ident is not None, name
    return ServiceProfile(
        service_name=name,
        identity=ident,
        rate=Decimal(rate),
        z_rate_service_id=hash(name) % 10_000,
        ride_count=rides,
        median_miles=miles,
    )


# ── Tier 1: in-season identity ────────────────────────────────────────────────

def test_risalah_suffix_churn_resolves_tier1():
    pool = [_profile("Risalah ES IB 05", "45.00", rides=83, miles=12.0)]
    r = resolve_rate_v2("Risalah ES IB 05 (HCV)_A LS022626 01", 12.0, pool)
    assert r.tier == TIER_IDENTITY
    assert r.rate == Decimal("45.00")
    assert "Risalah ES IB 05" in r.evidence


def test_er_block_resolves_to_base_route_tier1():
    pool = [_profile("Albert Einstein ES OB 03", "38.00", rides=90)]
    r = resolve_rate_v2("Albert Einstein ES OB 03_A ER061726 01", 8.0, pool)
    assert r.tier == TIER_IDENTITY
    assert r.rate == Decimal("38.00")


def test_day_marker_never_crosses_to_unmarked_base():
    # Replay lesson (Cedar Heights OB 16): the (W) run was $40 against the
    # base's $62. Day-marked names only Tier-1 match same-day-marked names.
    pool = [_profile("Cedar Heights MS OB 16", "62.00", rides=14)]
    r = resolve_rate_v2("Cedar Heights MS OB 16 (W)_A", None, pool)
    assert r.tier == TIER_NONE


def test_unmarked_never_inherits_from_day_marked():
    pool = [_profile("Westgate ES OB 01 (F)", "44.00", rides=2, miles=16.0)]
    r = resolve_rate_v2("Westgate ES OB 01", None, pool)
    assert r.tier == TIER_NONE


def test_same_day_marker_crosses_fine():
    pool = [_profile("Cedar Heights MS OB 16 (W)", "40.00", rides=8)]
    r = resolve_rate_v2("Cedar Heights MS OB 16 (W)_A", None, pool)
    assert r.tier == TIER_IDENTITY
    assert r.rate == Decimal("40.00")


def test_equipment_marker_hcv_still_crosses():
    pool = [_profile("Risalah ES IB 05", "45.00", rides=83)]
    r = resolve_rate_v2("Risalah ES IB 05 (HCV)_A", 12.0, pool)
    assert r.tier == TIER_IDENTITY
    assert r.rate == Decimal("45.00")


def test_tier2_day_marker_guard():
    pool = [_profile("Alderwood MS OB 02 (F)", "42.00", rides=10, miles=12.0)]
    r = resolve_rate_v2("Alderwood MS OB 09", 12.0, pool)
    assert r.tier == TIER_NONE


def test_odt_is_its_own_pricing_class_never_tier1_to_base():
    # Replay lesson (Alderwood): ODT runs are priced separately from the
    # base pairing. "OB ODT 03" must not inherit "OB 03"'s rate via Tier 1.
    pool = [_profile("Alderwood MS OB 03", "70.00", rides=22, miles=None)]
    r = resolve_rate_v2("Alderwood MS OB ODT 03", None, pool)
    assert r.tier == TIER_NONE


def test_odt_matches_odt_tier1():
    pool = [_profile("Cedar Heights MS IB ODT 05", "42.00")]
    r = resolve_rate_v2("Cedar Heights MS IB ODT 05_A", 9.0, pool)
    assert r.tier == TIER_IDENTITY
    assert r.rate == Decimal("42.00")


def test_odt_tier2_inherits_only_from_odt():
    # ODT distance-inheritance stays inside the ODT class (Scenic Hill family).
    pool = [
        _profile("Alderwood MS OB ODT 01", "54.00", rides=10, miles=12.0),
        _profile("Alderwood MS OB 03", "70.00", rides=22, miles=12.0),
    ]
    r = resolve_rate_v2("Alderwood MS OB ODT 07", 12.0, pool)
    assert r.tier == TIER_DISTANCE
    assert r.rate == Decimal("54.00")


def test_exact_name_match_beats_better_evidenced_variant():
    pool = [
        _profile("Bell ES IB 01_A", "58.00", rides=500),
        _profile("Bell ES IB 01 (W)", "40.00", rides=3),
    ]
    r = resolve_rate_v2("Bell ES IB 01 (W)", 7.0, pool)
    assert r.rate == Decimal("40.00")
    assert r.matched_service_name == "Bell ES IB 01 (W)"


def test_split_priced_family_refuses():
    # Replay lesson (Meeker/Westgate/Cedar Heights): day-marker variants are
    # sometimes genuinely repriced. A family that disagrees is a human call.
    pool = [
        _profile("Cedarhome ES IB 01_A", "75.00", rides=2),
        _profile("Cedarhome ES IB 01_B", "85.00", rides=2),
    ]
    r = resolve_rate_v2("Cedarhome ES IB 01_C", 26.0, pool)
    assert r.tier == TIER_NONE
    assert "split-priced" in r.evidence


def test_uniform_family_resolves_despite_markers():
    pool = [
        _profile("Risalah ES IB 05", "45.00", rides=83),
        _profile("Risalah ES IB 05 (HCV)", "45.00", rides=12),
    ]
    r = resolve_rate_v2("Risalah ES IB 05_B", 12.0, pool)
    assert r.tier == TIER_IDENTITY
    assert r.rate == Decimal("45.00")


def test_exact_name_match_wins_even_in_split_family():
    pool = [
        _profile("Meeker MS OB 19", "60.00", rides=18),
        _profile("Meeker MS OB 19 (W)", "54.00", rides=6),
    ]
    r = resolve_rate_v2("Meeker MS OB 19 (W)", 26.0, pool)
    assert r.tier == TIER_IDENTITY
    assert r.rate == Decimal("54.00")


def test_neighbor_number_is_NOT_matched_tier1():
    # v1's fatal flaw: 02 must never match 01/03 by number adjacency.
    pool = [_profile("Rosa Parks ES IB 01", "38.00"), _profile("Rosa Parks ES IB 03", "38.00")]
    r = resolve_rate_v2("Rosa Parks ES IB 02", None, pool)
    assert r.tier == TIER_NONE   # no miles → no tier2 either


# ── Tier 2: season-boundary price inheritance ────────────────────────────────

def test_kent_meridian_17_to_02_season_boundary():
    # THE case from the plan: spring IB 17 (28mi, $62 × 92 rides) → fall IB 02 at 27mi.
    pool = [_profile("Kent Meridian HS IB 17", "62.00", rides=92, miles=28.0)]
    r = resolve_rate_v2("Kent Meridian HS IB 02", 27.0, pool)
    assert r.tier == TIER_DISTANCE
    assert r.rate == Decimal("62.00")
    assert "28mi @ $62.00" in r.evidence
    assert "92 rides" in r.evidence


def test_tier2_respects_miles_tolerance():
    pool = [_profile("Kent Meridian HS IB 17", "62.00", rides=92, miles=28.0)]
    r = resolve_rate_v2("Kent Meridian HS IB 02", 25.0, pool)   # 3mi off
    assert r.tier == TIER_NONE


def test_tier2_never_crosses_direction():
    pool = [_profile("Kent Meridian HS OB 17", "62.00", rides=92, miles=28.0)]
    r = resolve_rate_v2("Kent Meridian HS IB 02", 28.0, pool)
    assert r.tier == TIER_NONE


def test_tier2_never_crosses_school():
    pool = [_profile("Lake Washington HS IB 01", "58.00", rides=87, miles=28.0)]
    r = resolve_rate_v2("Kent Meridian HS IB 02", 28.0, pool)
    assert r.tier == TIER_NONE


def test_tier2_ambiguous_prices_refuses():
    pool = [
        _profile("Kent Meridian HS IB 17", "62.00", rides=92, miles=28.0),
        _profile("Kent Meridian HS IB 09", "48.00", rides=40, miles=28.1),
    ]
    r = resolve_rate_v2("Kent Meridian HS IB 02", 28.0, pool)
    assert r.tier == TIER_NONE
    assert "refusing to guess" in r.evidence


def test_tier2_equal_prices_at_tie_is_fine():
    pool = [
        _profile("Kent Meridian HS IB 17", "62.00", rides=92, miles=28.0),
        _profile("Kent Meridian HS IB 09", "62.00", rides=40, miles=28.1),
    ]
    r = resolve_rate_v2("Kent Meridian HS IB 02", 28.0, pool)
    assert r.tier == TIER_DISTANCE
    assert r.rate == Decimal("62.00")


def test_tier2_clear_nearest_wins_over_farther_different_price():
    pool = [
        _profile("Kent Meridian HS IB 17", "62.00", rides=92, miles=28.0),
        _profile("Kent Meridian HS IB 09", "48.00", rides=40, miles=29.0),  # 1mi farther
    ]
    r = resolve_rate_v2("Kent Meridian HS IB 02", 28.0, pool)
    assert r.tier == TIER_DISTANCE
    assert r.rate == Decimal("62.00")


def test_tier1_wins_over_tier2():
    pool = [
        _profile("Kent Meridian HS IB 02", "50.00", rides=10, miles=27.0),
        _profile("Kent Meridian HS IB 17", "62.00", rides=92, miles=27.0),
    ]
    r = resolve_rate_v2("Kent Meridian HS IB 02_A", 27.0, pool)
    assert r.tier == TIER_IDENTITY
    assert r.rate == Decimal("50.00")


# ── Refusals ──────────────────────────────────────────────────────────────────

def test_unparseable_name_refuses():
    r = resolve_rate_v2("[RECONCILE_ADJ]", 10.0, [])
    assert r.tier == TIER_NONE
    assert not r.resolved


def test_empty_pool_refuses():
    r = resolve_rate_v2("Kent Meridian HS IB 02", 27.0, [])
    assert r.tier == TIER_NONE


# ── Mode flag ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("val,expected", [
    (None, MODE_OFF), ("0", MODE_OFF), ("shadow", MODE_SHADOW),
    ("SHADOW", MODE_SHADOW), ("1", MODE_LIVE), ("garbage", MODE_OFF),
])
def test_v2_mode(monkeypatch, val, expected):
    if val is None:
        monkeypatch.delenv("RATE_ENGINE_V2", raising=False)
    else:
        monkeypatch.setenv("RATE_ENGINE_V2", val)
    assert v2_mode() == expected
