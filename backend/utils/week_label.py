"""
Week labeling utility for payroll batches.

Both FirstAlt and EverDriven cover the same 5 workdays but start their
weeks on different days. We derive the canonical week number from the
period_start date using FirstAlt's school-year calendar (Week 1 = Jan 3, 2026,
which is the Saturday starting the first full school week). This ensures FA
and ED batches for the same payroll cycle always display the same "Week N".

If a batch_ref embeds an explicit week via the OY2026W<N> pattern (common in
older ED batch refs) we use that in preference to the date derivation.
"""
import re
from datetime import date, timedelta

# Anchor: FirstAlt W1 period starts 2026-01-03 (Saturday).
# Every subsequent week starts 7 days later, so week N starts
# on anchor + (N-1) * 7 days.
_ANCHOR = date(2026, 1, 3)
_OY_WEEK_RE = re.compile(r'OY\d{4}W(\d+)', re.IGNORECASE)


def canonical_week_num(
    period_start: date | None,
    batch_ref: str | None = None,
) -> int | None:
    """
    Return the canonical payroll week number (1-based integer) for a batch.

    Priority:
    1. OY<year>W<N> embedded in batch_ref  (e.g. "WASO291-OY2026W14-20260412")
    2. Date arithmetic from period_start relative to _ANCHOR
    3. None if neither is available
    """
    if batch_ref:
        m = _OY_WEEK_RE.search(batch_ref)
        if m:
            return int(m.group(1))

    if period_start is None:
        return None

    delta = (period_start - _ANCHOR).days
    if delta < 0:
        # Pre-anchor date — fall back to ISO week to avoid negative numbers.
        return period_start.isocalendar()[1]
    return delta // 7 + 1


def canonical_week_label(
    period_start: date | None,
    batch_ref: str | None = None,
) -> str:
    """Return 'Week N' using canonical week numbering, or '' if undetermined."""
    n = canonical_week_num(period_start, batch_ref)
    return f"Week {n}" if n is not None else ""


def week_label(period_start: date | None, period_end: date | None) -> str:
    """Return 'Week X' label from batch period dates (legacy — uses period midpoint ISO week)."""
    if not period_start:
        return ""
    mid = period_start
    if period_end:
        mid = period_start + (period_end - period_start) / 2
    iso_week = mid.isocalendar()[1]
    return f"Week {iso_week}"


def week_label_full(period_start: date | None, period_end: date | None) -> str:
    """Return 'Week X · m/d – m/d' with dates as secondary context."""
    label = week_label(period_start, period_end)
    if not label or not period_start:
        return label
    s = f"{period_start.month}/{period_start.day}"
    e = f"{period_end.month}/{period_end.day}" if period_end else ""
    return f"{label} · {s} – {e}" if e else f"{label} · {s}"
