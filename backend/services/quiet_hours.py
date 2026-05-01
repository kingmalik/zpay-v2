"""
Quiet-hours helper — Phase 3 severity routing.

Returns True when the current wall-clock time in Pacific Time falls inside
the configured quiet window (default 21:00 – 07:00 PT).

Environment variables (optional):
  DISPATCH_QUIET_START  — hour (0-23) quiet window starts  (default 21)
  DISPATCH_QUIET_END    — hour (0-23) quiet window ends    (default 7)
  MONITOR_TIMEZONE      — IANA timezone string              (default America/Los_Angeles)

The window wraps midnight when start > end (e.g. 21 → 7 spans 21:00–07:00).
"""

from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

_QUIET_START: int = int(os.environ.get("DISPATCH_QUIET_START", "21"))
_QUIET_END: int = int(os.environ.get("DISPATCH_QUIET_END", "7"))
_TZ: ZoneInfo = ZoneInfo(os.environ.get("MONITOR_TIMEZONE", "America/Los_Angeles"))


def in_quiet_hours() -> bool:
    """Return True if *now* falls inside the dispatch quiet window (PT by default).

    The window is inclusive of _QUIET_START and exclusive of _QUIET_END so that
    21:00 is quiet and 07:00 is not.

    Wraps midnight when DISPATCH_QUIET_START > DISPATCH_QUIET_END.
    """
    hour = datetime.now(_TZ).hour
    if _QUIET_START > _QUIET_END:
        # Wraps midnight: [21, 24) ∪ [0, 7)
        return hour >= _QUIET_START or hour < _QUIET_END
    else:
        return _QUIET_START <= hour < _QUIET_END
