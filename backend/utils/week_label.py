"""
Week labeling utility for payroll batches.

Both FirstAlt and EverDriven cover the same 5 workdays but start their
weeks on different days. We use the ISO week number of the period midpoint
so both companies' batches for the same work week get the same "Week X" label.
"""
from datetime import date, timedelta


def week_label(period_start: date | None, period_end: date | None) -> str:
    """Return 'Week X' label from batch period dates."""
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
