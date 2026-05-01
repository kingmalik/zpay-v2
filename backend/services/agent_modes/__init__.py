"""
Agent mode registry for the unified Z-Pay Agent.

Each mode has a corresponding .md file in this directory that contains its
system prompt.  Unknown modes fall back to "dispatcher" (the original
behavior) so existing callers are never broken.
"""
from __future__ import annotations

from pathlib import Path

MODES: list[str] = [
    "dispatcher",
    "onboarder",
    "reviewer",
    "triage",
    "reconciler",
    "investigator",
]

_MODES_DIR = Path(__file__).parent

# Modes without their own .md share the generic pending stub.
_PENDING_MODES = {"triage", "reconciler", "investigator"}


def get_system_prompt(mode: str) -> str:
    """Return the system prompt for *mode*.

    Falls back to the dispatcher prompt for any unknown or empty mode so that
    existing callers that omit the ``mode`` field are unaffected.
    """
    resolved = mode.strip().lower() if mode else "dispatcher"
    if resolved not in MODES:
        resolved = "dispatcher"

    if resolved in _PENDING_MODES:
        prompt_file = _MODES_DIR / "_pending.md"
    else:
        prompt_file = _MODES_DIR / f"{resolved}.md"

    return prompt_file.read_text(encoding="utf-8").strip()
