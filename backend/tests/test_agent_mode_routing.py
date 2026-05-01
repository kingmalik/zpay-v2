"""
Tests for agent mode routing scaffold.

These are pure unit tests against get_system_prompt — no DB, no HTTP, no
Anthropic calls needed.  Three cases per the spec:

  1. Default (no mode / empty string) → dispatcher prompt
  2. Explicit "dispatcher" → same dispatcher prompt
  3. "onboarder" → onboarder stub prompt
"""
from __future__ import annotations

import pytest

from backend.services.agent_modes import MODES, get_system_prompt


# ── Helpers ────────────────────────────────────────────────────────────────────

DISPATCHER_SENTINEL = "Z-Pay's dispatch agent"
ONBOARDER_SENTINEL = "Onboarder mode is in development"
PENDING_SENTINEL = "This mode is in development"


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_default_mode_returns_dispatcher_prompt():
    """Omitted / empty mode must produce the dispatcher system prompt."""
    prompt = get_system_prompt("")
    assert DISPATCHER_SENTINEL in prompt, (
        f"Expected dispatcher sentinel in prompt, got:\n{prompt[:200]}"
    )


def test_explicit_dispatcher_returns_dispatcher_prompt():
    """Explicit mode='dispatcher' must produce the same dispatcher system prompt."""
    prompt = get_system_prompt("dispatcher")
    assert DISPATCHER_SENTINEL in prompt, (
        f"Expected dispatcher sentinel in prompt, got:\n{prompt[:200]}"
    )


def test_onboarder_returns_stub_prompt():
    """mode='onboarder' must return the onboarder stub, not the dispatcher prompt."""
    prompt = get_system_prompt("onboarder")
    assert ONBOARDER_SENTINEL in prompt, (
        f"Expected onboarder sentinel in prompt, got:\n{prompt[:200]}"
    )
    assert DISPATCHER_SENTINEL not in prompt, (
        "Onboarder prompt must not contain the dispatcher sentinel"
    )


def test_unknown_mode_falls_back_to_dispatcher():
    """Any mode not in MODES must silently fall back to dispatcher."""
    prompt = get_system_prompt("not_a_real_mode")
    assert DISPATCHER_SENTINEL in prompt


def test_pending_modes_return_pending_stub():
    """triage / reconciler / investigator share the _pending.md stub."""
    for mode in ("triage", "reconciler", "investigator"):
        prompt = get_system_prompt(mode)
        assert PENDING_SENTINEL in prompt, (
            f"Expected pending sentinel for mode={mode!r}, got:\n{prompt[:200]}"
        )


def test_modes_constant_contains_all_six():
    """MODES list must declare exactly the six canonical modes."""
    expected = {"dispatcher", "onboarder", "reviewer", "triage", "reconciler", "investigator"}
    assert set(MODES) == expected


def test_reviewer_returns_stub():
    """mode='reviewer' returns a stub (not the dispatcher prompt)."""
    prompt = get_system_prompt("reviewer")
    assert DISPATCHER_SENTINEL not in prompt
    assert len(prompt) > 0


def test_mode_case_insensitive():
    """Mode lookup must be case-insensitive."""
    lower = get_system_prompt("dispatcher")
    upper = get_system_prompt("DISPATCHER")
    mixed = get_system_prompt("Dispatcher")
    assert lower == upper == mixed
