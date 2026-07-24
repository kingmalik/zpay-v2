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

# ── Calibrated against the real corpus (1,100 FirstStudent emails, 2026-07-23) ──
# Brandon's offers are conversational: district in the SUBJECT
# ("LWSD - New Trip", "Fife SD - New Route"), prose body with one pay
# ("the pay is $73") or split directional pays ("The IB pay is $54.75 while
# the OB pay is $49.75"), a start date ("set to start on Monday the 12th"),
# sometimes a city pair ("from Kirkland to Kent") and equipment notes
# ("requires two booster seats"). Signature + legal footer must be stripped.
_SIGNATURE_MARKERS = (
    "\nThanks,", "\nThank you,", "\nBest,",
    "BRANDEN SEEBERGER", "Seeberger, Branden",
    "[Icon", "This email (and any attachment)",
)
_SUBJECT_RE = re.compile(
    r"(?:^|\n)\s*(?:subj(?:ect)?\s*:\s*)?([A-Za-z][A-Za-z .&/]{1,40}?)\s*[-–]\s*new\s+(trip|route)s?\b",
    re.IGNORECASE,
)
_PAY_IB_RE = re.compile(r"(?:\bIB\b|inbound)[^$\n]{0,30}\$\s?(\d{1,5}(?:\.\d{1,2})?)", re.IGNORECASE)
_PAY_OB_RE = re.compile(r"(?:\bOB\b|outbound)[^$\n]{0,30}\$\s?(\d{1,5}(?:\.\d{1,2})?)", re.IGNORECASE)
_START_DATE_RE = re.compile(
    r"start(?:ing|s)?\s+(?:on\s+)?((?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day)?\s*(?:the\s+)?(\d{1,2}(?:st|nd|rd|th))\b",
    re.IGNORECASE,
)
_CITY_PAIR_RE = re.compile(
    r"\bfrom\s+([A-Z][A-Za-z .'\-]{2,25}?)\s+to\s+([A-Z][A-Za-z .'\-]{2,25}?)(?=[\s.,;]|$)",
)
_REQUIREMENT_RES = (
    (re.compile(r"\b(two|2|three|3)?\s*booster seats?\b", re.IGNORECASE), "booster seat"),
    (re.compile(r"\bcar seats?\b", re.IGNORECASE), "car seat"),
    (re.compile(r"\bharness\b", re.IGNORECASE), "harness"),
    (re.compile(r"\bmonitor\b", re.IGNORECASE), "monitor required"),
)

REQUIRED_FOR_ACCEPT = ("school", "direction", "net_pay")


def _strip_boilerplate(text: str) -> str:
    """Cut the body at the first signature/legal-footer marker so signature
    phone numbers and disclaimer text can't pollute pay/date extraction."""
    cut = len(text)
    for marker in _SIGNATURE_MARKERS:
        idx = text.find(marker)
        if idx != -1:
            cut = min(cut, idx)
    return text[:cut]


def _extract_subject_fields(text: str) -> tuple[Optional[str], Optional[bool]]:
    """(district, is_recurring) from a 'District - New Trip/Route' line."""
    m = _SUBJECT_RE.search(text)
    if not m:
        return None, None
    district = m.group(1).strip()
    is_recurring = m.group(2).lower() == "route"
    return district, is_recurring


def _extract_directional_pays(text: str) -> tuple[Optional[float], Optional[float]]:
    ib = _PAY_IB_RE.search(text)
    ob = _PAY_OB_RE.search(text)
    try:
        return (float(ib.group(1)) if ib else None, float(ob.group(1)) if ob else None)
    except ValueError:
        return None, None


def _extract_start_date(text: str) -> Optional[str]:
    m = _START_DATE_RE.search(text)
    if not m:
        return None
    weekday, day = m.group(1), m.group(2)
    return f"{weekday} the {day}" if weekday else f"the {day}"


def _extract_city_pair(text: str) -> tuple[Optional[str], Optional[str]]:
    m = _CITY_PAIR_RE.search(text)
    if not m:
        return None, None
    return m.group(1).strip(), m.group(2).strip()


def _extract_requirements(text: str) -> Optional[list[str]]:
    found = []
    for pattern, label in _REQUIREMENT_RES:
        m = pattern.search(text)
        if m:
            qty = (m.group(1) or "").lower() if pattern.groups else ""
            found.append(f"{qty} {label}".strip() if qty else label)
    return found or None


def _build_notes(district, is_recurring, net_pay_ib, net_pay_ob, start_date, origin, destination, requirements) -> Optional[str]:
    """Human-readable summary of everything the contract's core fields can't
    carry — surfaces in the intake UI's notes without frontend changes."""
    bits = []
    if district:
        bits.append(f"District: {district}")
    if is_recurring is not None:
        bits.append("recurring route" if is_recurring else "single trip")
    if net_pay_ib is not None or net_pay_ob is not None:
        ib = f"IB ${net_pay_ib:g}" if net_pay_ib is not None else None
        ob = f"OB ${net_pay_ob:g}" if net_pay_ob is not None else None
        bits.append(" / ".join(b for b in (ib, ob) if b))
    if start_date:
        bits.append(f"starts {start_date}")
    if origin and destination:
        bits.append(f"{origin} → {destination}")
    if requirements:
        bits.append("needs: " + ", ".join(requirements))
    return " · ".join(bits) or None


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
    full_text = raw_text or ""
    try:
        text = _strip_boilerplate(full_text)
    except Exception:
        text = full_text

    try:
        district, is_recurring = _extract_subject_fields(full_text)
    except Exception:
        district, is_recurring = None, None

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
        net_pay_ib, net_pay_ob = _extract_directional_pays(text)
    except Exception:
        net_pay_ib, net_pay_ob = None, None

    try:
        net_pay = net_pay_ib if net_pay_ib is not None else _extract_net_pay(text)
    except Exception:
        net_pay = net_pay_ib

    try:
        start_date = _extract_start_date(text)
    except Exception:
        start_date = None

    try:
        origin, destination = _extract_city_pair(text)
    except Exception:
        origin, destination = None, None

    try:
        requirements = _extract_requirements(text)
    except Exception:
        requirements = None

    try:
        days = _extract_days(text)
    except Exception:
        days = None

    try:
        start_time = _extract_start_time(text)
    except Exception:
        start_time = None

    # IB-only match means the email is directional even without an IB/OB token
    # elsewhere; don't override an explicit direction hit though.
    if direction is None and net_pay_ib is not None and net_pay_ob is None:
        direction = "IB"

    try:
        notes = _build_notes(district, is_recurring, net_pay_ib, net_pay_ob,
                             start_date, origin, destination, requirements)
    except Exception:
        notes = None

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
        "notes": notes,
        # Extended fields (additive to the S5 contract — UI shows them via notes):
        "district": district,
        "is_recurring": is_recurring,
        "net_pay_ib": net_pay_ib,
        "net_pay_ob": net_pay_ob,
        "start_date": start_date,
        "origin": origin,
        "destination": destination,
        "requirements": requirements,
    }


def _missing_fields(parsed: dict) -> list[str]:
    return [f for f in REQUIRED_FOR_ACCEPT if not parsed.get(f)]


def build_reply_draft(parsed: dict, decision_hint: Optional[str] = None) -> str:
    """Short professional reply text for Brandon. Never raises."""
    parsed = parsed or {}
    fallback = f"the {parsed['district']} route" if parsed.get("district") else "the route"
    school = parsed.get("school") or fallback
    direction = parsed.get("direction") or ""
    number = parsed.get("number") or ""
    route_label = " ".join(p for p in (school, direction, number) if p).strip() or fallback

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
