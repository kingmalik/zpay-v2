"""
Tests for backend/services/route_identity.py — seeded from REAL prod names.

Run with:
    PYTHONPATH=. pytest backend/tests/test_route_identity.py -x -v
"""
from __future__ import annotations

import os
import sys

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.services.route_identity import parse_route_identity


def _key(name: str):
    ident = parse_route_identity(name)
    assert ident is not None, f"failed to parse: {name}"
    return ident.key


# ── Plain shapes ──────────────────────────────────────────────────────────────

def test_plain_route():
    ident = parse_route_identity("Kent Meridian HS IB 17")
    assert ident.school == "Kent Meridian HS"
    assert ident.direction == "IB"
    assert ident.number == "17"
    assert ident.variant is None
    assert ident.markers == ()
    assert not ident.is_odt


def test_school_with_dash_and_multiword():
    ident = parse_route_identity("Canyon Ridge MS - Scenic Hill ES IB 01_A")
    assert ident.school == "Canyon Ridge MS - Scenic Hill ES"
    assert ident.key == ("canyon ridge ms - scenic hill es", "IB", "01")
    assert ident.variant == "A"


def test_single_digit_number_zero_pads():
    assert _key("Rosa Parks ES IB 3") == ("rosa parks es", "IB", "03")


# ── Suffix churn — the Risalah family collapses to one identity ──────────────

@pytest.mark.parametrize("name", [
    "Risalah ES IB 05",
    "Risalah ES IB 05_A",
    "Risalah ES IB 05 (HCV)_A",
    "Risalah ES IB 05 (HCV)",
    "Risalah ES IB 05_B ER013026 01",
])
def test_risalah_suffix_churn_family_is_one_identity(name):
    assert _key(name) == ("risalah es", "IB", "05")


def test_er_block_stripped():
    ident = parse_route_identity("Albert Einstein ES OB 03 ER012726 01")
    assert ident.key == ("albert einstein es", "OB", "03")


def test_marker_variant_er_stack():
    # Real prod name: base + (W) + _A + ER block
    ident = parse_route_identity("Albert Einstein ES OB 03 (W)_A ER061726 01")
    assert ident.key == ("albert einstein es", "OB", "03")
    assert ident.markers == ("W",)
    assert ident.variant == "A"


def test_variant_letters_beyond_a():
    assert _key("Albert Einstein ES OB 04_D") == ("albert einstein es", "OB", "04")


@pytest.mark.parametrize("name,marker", [
    ("Alderwood MS OB 02 (F)", "F"),
    ("Bowman Creek ES IB 03 (M)", "M"),
    ("Bell ES OB 01 (W)", "W"),
])
def test_day_markers(name, marker):
    ident = parse_route_identity(name)
    assert ident.markers == (marker,)


# ── ODT — same pairing, flag recorded ─────────────────────────────────────────

def test_odt_is_same_identity():
    ident = parse_route_identity("Albert Einstein ES IB ODT 02")
    assert ident.key == ("albert einstein es", "IB", "02")
    assert ident.is_odt


def test_odt_and_plain_share_key():
    assert _key("Cedar Heights MS IB ODT 05") == _key("Cedar Heights MS IB 05")


# ── Direction separates identities ────────────────────────────────────────────

def test_ib_and_ob_are_different_identities():
    assert _key("Rosen Family PK IB 02") != _key("Rosen Family PK OB 02")


def test_numbers_are_different_identities():
    # THE ground-truth rule: 17 and 02 are different kids, never neighbors.
    assert _key("Kent Meridian HS IB 17") != _key("Kent Meridian HS IB 02")


# ── Non-routes ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["[RECONCILE_ADJ]", "", None, "no direction here", "IB 02"])
def test_non_routes_return_none(name):
    assert parse_route_identity(name) is None


def test_whitespace_normalized():
    assert _key("Kent  Meridian HS  IB 17") == ("kent meridian hs", "IB", "17")


# ── Long-tail churn found in the prod acid test ───────────────────────────────

def test_ls_late_start_block_stripped():
    assert _key("Risalah ES IB 05 (HCV)_A LS022626 01") == ("risalah es", "IB", "05")


def test_variant_with_typo_space():
    assert _key("Risalah ES OB 04_ F ER030426 01") == ("risalah es", "OB", "04")


def test_slash_day_markers():
    ident = parse_route_identity("HC Achieve PRG OB 01 (M/T)")
    assert ident.key == ("hc achieve prg", "OB", "01")
    assert ident.markers == ("M/T",)


def test_bracket_marker():
    ident = parse_route_identity("ChanceLight Northwater ALT OB 01 (W) [Wt]")
    assert ident.key == ("chancelight northwater alt", "OB", "01")
    assert set(ident.markers) == {"W", "Wt"}


def test_ls_block_on_plain_name():
    assert _key("Sequoia HS IB 01 LS012626 01") == ("sequoia hs", "IB", "01")


def test_er_block_with_space_before_date():
    assert _key("Fife ES OB 06 ER 061726 01") == ("fife es", "OB", "06")


def test_directionless_odt_stays_unparsed():
    # "Wilson Playfields ODT 12" has no IB/OB — not a standard pairing;
    # falls through to v1 behavior / rate review.
    assert parse_route_identity("Wilson Playfields ODT 12") is None
