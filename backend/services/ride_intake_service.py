"""
Ride intake parsing — best-effort extraction from Brandon/FirstStudent emails.

S5 (Assignment Helper + Coverage). New-ride emails land in the
contact.activate inbox with a school, direction, pay, miles, and schedule
buried in free text (format drifts constantly — Brandon doesn't template
these). parse_intake() NEVER raises on weird input: every field defaults to
None/empty and gets filled in by a human in the intake UI. It is a best-effort
extraction helper, not a validator.

build_reply_draft() turns the parsed result into a short professional email
reply — either an acceptance ("we can cover...") or a clarifying-questions
draft when key fields are still missing.
"""
from __future__ import annotations

import re
from typing import Optional

from backend.services.route_identity import parse_route_identity

# Wheelchair / equipment markers seen in the wild: "(HCV)", "[Wt]", the word
# "wheelchair", or "w/c". Bracket/paren forms aren't \b-bounded on their own
# (a leading "[" or "(" is a non-word char, so \b never matches there) —
# they're split out as their own alternatives instead.
_WHEELCHAIR_RE = re.compile(r"\b(?:wheelchair|w/c|HCV)\b|\[Wt\]|\(Wt\)", re.IGNORECASE)

# Dollar amounts — captures "$45.00", "$45", "45.00 dollars".
_MONEY_RE = re.compile(r"\$\s?(\d{1,5}(?:\.\d{1,2})?)")
# Pay-context keywords near a dollar amount raise our confidence it's the
# rate, not e.g. a fuel surcharge or a fee mentioned elsewhere in the email.
_PAY_KEYWORD_RE = re.compile(r"(pay|rate|net|price)\D{0,25}\$\s?(\d{1,5}(?:\.\d{1,2})?)", re.IGNORECASE)

# Mileage — "12 miles", "12.5 mi", "12mi".
_MILES_RE = re.compile(r"(\d{1,3}(?:\.\d{1,2})?)\s?(?:miles|mi)\b", re.IGNORECASE)

# Direction tokens anywhere in the text (route-identity parse handles the
# stricter "School IB/OB NN" shape; this is a looser fallback).
_DIRECTION_RE = re.compile(r"\b(inbound|IB|outbound|OB)\b", re.IGNORECASE)

# Start time — "7:45 AM", "07:45am", "3:15 PM".
_TIME_RE = re.compile(r"\b(\d{1,2}:\d{2}\s?(?:AM|PM|am|pm)?)\b")

# Day-of-week tokens, longest-first so "Thursday" doesn't get eaten by "Th".
_DAY_TOKENS = [
    ("Monday", "M"), ("Mon", "M"),
    ("Tuesday", "T"), ("Tue", "T"), ("Tues", "T"),
    ("Wednesday", "W"), ("Wed", "W"),
    ("Thursday", "Th"), ("Thu", "Th"), ("Thurs", "Th"),
    ("Friday", "F"), ("Fri", "F"),
]

# Route-name-shaped substring: "<School> IB|OB [ODT] NN" possibly with
# trailing markers — used to hand off to the route_identity parser.
_ROUTE_SHAPE_RE = re.compile(
    r"[A-Za-z][A-Za-z .'\-]+?\s+(?:IB|OB)\s+(?:ODT\s+)?\d{1,2}(?:\s*[(\[][A-Za-z/]{1,5}[)\]])?",
)

REQUIRED_FOR_ACCEPT = ("school", "direction", "net_pay")


def _extract_wheelchair(text: str) -> bool:
    return bool(_WHEELCHAIR_RE.search(text))


def _extract_net_pay(text: str) -> Optional[float]:
    keyworded = _PAY_KEYWORD_RE.search(text)
    if keyworded:
        try:
            return float(keyworded.group(2))
        except ValueError:
            return None
    generic = _MONEY_RE.search(text)
    if generic:
        try:
            return float(generic.group(1))
        except ValueError:
            return None
    return None


def _extract_miles(text: str) -> Optional[float]:
    m = _MILES_RE.search(text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _extract_days(text: str) -> Optional[list[str]]:
    found: list[str] = []
    for token, code in _DAY_TOKENS:
        if re.search(rf"\b{token}\b", text, re.IGNORECASE) and code not in found:
            found.append(code)
    return found or None


def _extract_start_time(text: str) -> Optional[str]:
    m = _TIME_RE.search(text)
    return m.group(1) if m else None


def _extract_school_direction_number(text: str) -> tuple[Optional[str], Optional[str], Optional[str], bool]:
    """Try the strict route_identity grammar first; fall back to loose tokens."""
    for candidate in _ROUTE_SHAPE_RE.findall(text):
        identity = parse_route_identity(candidate.strip())
        if identity is not None:
            return identity.school, identity.direction, identity.number, identity.is_odt

    dir_match = _DIRECTION_RE.search(text)
    direction = None
    if dir_match:
        token = dir_match.group(1).upper()
        direction = "IB" if token in ("IB", "INBOUND") else "OB"
    return None, direction, None, False


def parse_intake(raw_text: str) -> dict:
    """Best-effort parse of a new-ride email. Never raises.

    Returns a dict shaped exactly like the API contract's `parsed` object;
    any field we can't confidently extract stays None so a human can fill it
    in via the intake UI.
    """
    text = raw_text or ""

    try:
        school, direction, number, is_odt = _extract_school_direction_number(text)
    except Exception:
        school, direction, number, is_odt = None, None, None, False

    try:
        wheelchair = _extract_wheelchair(text)
    except Exception:
        wheelchair = False

    try:
        miles = _extract_miles(text)
    except Exception:
        miles = None

    try:
        net_pay = _extract_net_pay(text)
    except Exception:
        net_pay = None

    try:
        days = _extract_days(text)
    except Exception:
        days = None

    try:
        start_time = _extract_start_time(text)
    except Exception:
        start_time = None

    return {
        "school": school,
        "direction": direction,
        "number": number,
        "is_odt": bool(is_odt),
        "wheelchair": wheelchair,
        "miles": miles,
        "net_pay": net_pay,
        "days": days,
        "start_time": start_time,
        "notes": None,
    }


def _missing_fields(parsed: dict) -> list[str]:
    return [f for f in REQUIRED_FOR_ACCEPT if not parsed.get(f)]


def build_reply_draft(parsed: dict, decision_hint: Optional[str] = None) -> str:
    """Short professional reply text for Brandon. Never raises."""
    parsed = parsed or {}
    school = parsed.get("school") or "the route"
    direction = parsed.get("direction") or ""
    number = parsed.get("number") or ""
    route_label = " ".join(p for p in (school, direction, number) if p).strip() or "the route"

    if decision_hint == "pass":
        return (
            f"Hi Brandon,\n\nThanks for the offer on {route_label} — we're not able to "
            f"cover this one right now. Appreciate you thinking of us for the next one.\n\n"
            f"Best,\nMaz Services"
        )

    missing = _missing_fields(parsed)
    if missing:
        asks = []
        if "school" in missing:
            asks.append("the school name")
        if "direction" in missing:
            asks.append("inbound or outbound")
        if "net_pay" in missing:
            asks.append("the rate for this route")
        ask_text = ", ".join(asks)
        return (
            f"Hi Brandon,\n\nThanks for sending this over. Before we confirm coverage on "
            f"{route_label}, could you send over {ask_text}? Want to make sure we get the "
            f"right driver lined up.\n\nBest,\nMaz Services"
        )

    wheelchair_note = " (WC-equipped vehicle)" if parsed.get("wheelchair") else ""
    return (
        f"Hi Brandon,\n\nWe can cover {route_label}{wheelchair_note}. We'll get a driver "
        f"assigned and confirm before the start date.\n\nBest,\nMaz Services"
    )
