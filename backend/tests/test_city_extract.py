"""
Tests for backend/services/city_extract.py — WA city extraction from
free-text addresses. Pure function, no DB.

Run with:
    PYTHONPATH=. pytest backend/tests/test_city_extract.py -x -v
"""
from __future__ import annotations

import os
import sys

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.services.city_extract import extract_city


def test_none_input_returns_none():
    assert extract_city(None) is None


def test_empty_string_returns_none():
    assert extract_city("") is None


def test_whitespace_only_returns_none():
    assert extract_city("   ") is None


def test_garbage_text_with_no_city_returns_none():
    assert extract_city("this is not an address at all") is None


def test_full_address_with_state_and_zip():
    assert extract_city("1620 116th Ave NE, Bellevue, WA 98008") == "Bellevue"


def test_full_address_without_zip():
    assert extract_city("400 Broad St, Seattle, WA") == "Seattle"


def test_full_address_no_commas():
    assert extract_city("1620 116th Ave NE Bellevue WA 98008") == "Bellevue"


def test_city_only_string():
    assert extract_city("Kirkland") == "Kirkland"


def test_city_only_string_is_case_insensitive_and_returns_canonical_case():
    assert extract_city("kirkland") == "Kirkland"
    assert extract_city("SEATAC") == "SeaTac"


def test_multi_city_string_prefers_last_match():
    assert extract_city("Kirkland Ave, Renton, WA") == "Renton"


def test_multi_word_city_matches_whole_phrase_not_substring():
    assert extract_city("Lake Forest Park") == "Lake Forest Park"


def test_multi_word_city_not_shredded_into_smaller_words():
    # "Mountlake Terrace" must not resolve to some other whitelist entry via
    # a stray substring match on "Lake" or "Terrace" (neither is its own
    # whitelist entry, but this guards the multi-word-first strategy).
    assert extract_city("Mountlake Terrace, WA 98043") == "Mountlake Terrace"


def test_redmond_ridge_wins_over_plain_redmond_substring():
    assert extract_city("Redmond Ridge area") == "Redmond Ridge"


def test_plain_redmond_still_resolves_without_ridge():
    assert extract_city("15720 NE 85th St, Redmond, WA 98052") == "Redmond"


def test_snohomish_county_city():
    assert extract_city("Lake Stevens, WA") == "Lake Stevens"


def test_pierce_county_city():
    assert extract_city("Bonney Lake, WA 98391") == "Bonney Lake"


def test_street_named_after_a_non_matching_word_returns_none():
    assert extract_city("123 Random Ave") is None


def test_word_boundary_prevents_partial_word_match():
    # "Kentucky" must not resolve to "Kent".
    assert extract_city("123 Kentucky Ln") is None


def test_last_city_wins_when_multiple_valid_cities_present_no_state_suffix():
    assert extract_city("Auburn area near Kent District") == "Kent"


def test_seatac_mixed_case_full_address():
    assert extract_city("18000 Pacific Hwy S, SeaTac, WA 98188") == "SeaTac"
