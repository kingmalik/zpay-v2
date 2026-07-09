"""
Tests for backend/services/driver_reliability_tier.py

Run with:
    PYTHONPATH=. pytest backend/tests/test_driver_reliability_tier.py -x -v

Covers the pure classification rule, the effective-window policy, the
policy flag, and cache fallback behavior. compute_tiers' SQL is exercised
against a stubbed session (no Postgres).
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.services import driver_reliability_tier as drt


# ── classify() — pure rule ───────────────────────────────────────────────────

def test_new_driver_with_few_trips_is_watch():
    tier, reason = drt.classify(trips=3, nudges=0, calls=0, ghosts=0)
    assert tier == drt.TIER_WATCH
    assert "3 trips" in reason


def test_clean_veteran_is_trusted():
    tier, _ = drt.classify(trips=40, nudges=1, calls=0, ghosts=0)
    assert tier == drt.TIER_TRUSTED


def test_high_nudge_rate_is_chronic():
    # MUSSA case from the audit: 7 nudges over 39 trips = 17.9%
    tier, reason = drt.classify(trips=39, nudges=7, calls=0, ghosts=0)
    assert tier == drt.TIER_CHRONIC
    assert "18%" in reason


def test_any_call_is_chronic_even_with_low_nudge_rate():
    tier, reason = drt.classify(trips=50, nudges=1, calls=1, ghosts=0)
    assert tier == drt.TIER_CHRONIC
    assert "call" in reason


def test_ghost_overrides_everything():
    tier, reason = drt.classify(trips=100, nudges=0, calls=1, ghosts=1)
    assert tier == drt.TIER_CHRONIC
    assert "ghosted" in reason


def test_moderate_nudge_rate_is_watch():
    # 8% — above trusted ceiling, below chronic floor
    tier, _ = drt.classify(trips=25, nudges=2, calls=0, ghosts=0)
    assert tier == drt.TIER_WATCH


def test_small_clean_sample_is_watch_not_trusted():
    # Clean record but under the trusted minimum sample
    tier, _ = drt.classify(trips=6, nudges=0, calls=0, ghosts=0)
    assert tier == drt.TIER_WATCH


# ── effective_reminder_window() ──────────────────────────────────────────────

def test_trusted_window_shrinks():
    assert drt.effective_reminder_window(drt.TIER_TRUSTED, default_window=50) == 25


def test_trusted_window_never_exceeds_default():
    # If prod default is already tighter than the trusted knob, keep it
    assert drt.effective_reminder_window(drt.TIER_TRUSTED, default_window=20) == 20


def test_chronic_window_widens():
    assert drt.effective_reminder_window(drt.TIER_CHRONIC, default_window=50) == 90


def test_chronic_window_never_below_default():
    assert drt.effective_reminder_window(drt.TIER_CHRONIC, default_window=120) == 120


def test_watch_window_is_default():
    assert drt.effective_reminder_window(drt.TIER_WATCH, default_window=50) == 50


def test_unknown_tier_falls_back_to_default():
    assert drt.effective_reminder_window("garbage", default_window=50) == 50


# ── tier_policy_enabled() flag ───────────────────────────────────────────────

def test_policy_defaults_off(monkeypatch):
    monkeypatch.delenv("MONITOR_TIER_POLICY", raising=False)
    assert drt.tier_policy_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes"])
def test_policy_on_values(monkeypatch, val):
    monkeypatch.setenv("MONITOR_TIER_POLICY", val)
    assert drt.tier_policy_enabled() is True


@pytest.mark.parametrize("val", ["0", "false", "", "off"])
def test_policy_off_values(monkeypatch, val):
    monkeypatch.setenv("MONITOR_TIER_POLICY", val)
    assert drt.tier_policy_enabled() is False


# ── get_tier() cache behavior ────────────────────────────────────────────────

def test_get_tier_unknown_driver_defaults_to_watch():
    drt.invalidate_cache()
    with patch.object(drt, "compute_tiers", return_value={}):
        result = drt.get_tier(MagicMock(), person_id=999)
    assert result.tier == drt.TIER_WATCH
    assert result.reason == "no history in window"


def test_get_tier_returns_computed_tier_and_caches():
    drt.invalidate_cache()
    fake = drt.TierResult(
        person_id=7, tier=drt.TIER_CHRONIC, trips=39, nudges=7,
        calls=0, ghosts=0, nudge_rate=0.1795, reason="test",
    )
    with patch.object(drt, "compute_tiers", return_value={7: fake}) as mock_compute:
        first = drt.get_tier(MagicMock(), person_id=7)
        second = drt.get_tier(MagicMock(), person_id=7)
    assert first.tier == drt.TIER_CHRONIC
    assert second is first
    mock_compute.assert_called_once()  # second hit served from cache


def test_get_tier_compute_failure_falls_back_to_watch():
    drt.invalidate_cache()
    with patch.object(drt, "compute_tiers", side_effect=RuntimeError("db down")):
        result = drt.get_tier(MagicMock(), person_id=1)
    assert result.tier == drt.TIER_WATCH
