"""
Route code parser — extracts structured components from a Z-Pay service_name.

Pattern recognised:
    <school>  <level>  <direction>  [ODT]  <number>[_<letter>]  [(<days>)]

Examples:
    "Ella Baker ES IB 01_B"           → school="Ella Baker", level="ES", dir="IB", num=1, letter="B", odt=False
    "Alderwood MS OB 03"              → school="Alderwood", level="MS", dir="OB", num=3, odt=False
    "Brightmont ACDY OB 01"           → school="Brightmont", level="ACDY", dir="OB", num=1, odt=False
    "Alderwood MS OB 03 (M/W/F)"      → ... days="M/W/F"
    "Albert Einstein ES IB ODT 06"    → school="Albert Einstein", level="ES", dir="IB", num=6, odt=True
    "Loew Hall FT IB ODT 01"          → school="Loew Hall", level="FT", dir="IB", num=1, odt=True
    "Random garbage"                  → None

ODT = On Demand Trip (FA mid-day reinstatement). ODT routes are siblings of
their base routes — same school/level/direction — and pay the same rate.
W21 (2026-06-16) bug: regex omitted ODT marker, so the sibling-route UI
reported "First time this school has appeared in Z-Pay" for ODT codes even
when 4+ rated routes already existed at the same school+level+direction.
"""
import re
from typing import TypedDict


_PATTERN = re.compile(
    r"^(?P<school>.+?)\s+"
    r"(?P<level>ES|MS|HS|ACDY|K8|K-8|PK|FT)\s+"
    r"(?P<direction>IB|OB)\s+"
    r"(?P<odt>ODT\s+)?"
    r"(?P<number>\d+)"
    r"(?:_(?P<letter>[A-Z]))?"
    r"(?:\s+\((?P<days>[A-Z/]+)\))?$"
)


class ParsedRoute(TypedDict, total=False):
    school: str
    level: str
    direction: str
    number: int
    letter: str | None
    days: str | None
    odt: bool


def parse_route_code(name: str) -> ParsedRoute | None:
    """
    Parse a route service_name into its structural components.

    Returns a ParsedRoute dict on success, or None if the name does not
    match the expected format (caller should skip sibling lookup silently).
    """
    if not name:
        return None
    m = _PATTERN.match(name.strip())
    if not m:
        return None
    return {
        "school": m.group("school"),
        "level": m.group("level"),
        "direction": m.group("direction"),
        "number": int(m.group("number")),
        "letter": m.group("letter"),
        "days": m.group("days"),
        "odt": m.group("odt") is not None,
    }
