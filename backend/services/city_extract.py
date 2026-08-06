"""
City extraction — S10 Season Assignment Board.

Pure function, no I/O: pulls a canonical Washington city name out of a free-
text address or city-only string. Used by season_pool (mapping intake/sheet
origin+destination text into season_ride.pickup_city/dropoff_city) and
school_service (deriving city from a mom-entered school address).

Strategy (docs/SEASON-BOARD-PLAN.md §Services):
  1. Regex the segment right before ", WA" / " WA " (the shape US addresses
     use — "... Kirkland, WA 98033") and validate it against the whitelist.
  2. Fallback: scan the whitelist for word-boundary membership anywhere in
     the string, preferring the LAST match — city names sit near the end of
     US addresses ("123 Main St, Renton" beats a street named after a city).
  3. No match anywhere → None. Never raises.

The whitelist covers King, Snohomish, and Pierce county cities/towns —
Maz's operating footprint. Multi-word names are matched as whole phrases
before any shorter name that could be a substring of them (e.g. "Lake
Forest Park" must win over "Forest"/"Park"; "Mountlake Terrace" must not
be shredded into "Mount" + "Lake" + "Terrace").
"""
from __future__ import annotations

import re
from typing import Optional

# Canonical Title Case. Order doesn't matter for lookup (we index by a
# normalized key below) but longer/multi-word names are tried first so they
# win over substrings that are themselves valid single-word cities.
WA_CITIES: tuple[str, ...] = (
    # King County
    "Seattle", "Bellevue", "Redmond", "Kirkland", "Sammamish", "Issaquah",
    "Renton", "Kent", "Auburn", "Federal Way", "Bothell", "Woodinville",
    "Kenmore", "Shoreline", "Lake Forest Park", "Mercer Island", "Newcastle",
    "Tukwila", "SeaTac", "Burien", "Des Moines", "Normandy Park", "Covington",
    "Maple Valley", "Black Diamond", "Enumclaw", "Pacific", "Algona",
    "Clyde Hill", "Medina", "Yarrow Point", "Hunts Point",
    "Beaux Arts Village", "Redmond Ridge", "Cottage Lake", "White Center",
    "Vashon", "Snoqualmie", "North Bend", "Fall City", "Preston", "Duvall",
    "Carnation",
    # Snohomish County
    "Everett", "Mukilteo", "Monroe", "Lake Stevens", "Marysville",
    "Snohomish", "Arlington", "Stanwood", "Granite Falls", "Sultan",
    "Gold Bar", "Index", "Darrington", "Mill Creek", "Edmonds", "Lynnwood",
    "Mountlake Terrace", "Brier",
    # Pierce County
    "Tacoma", "Milton", "Fife", "Edgewood", "Sumner", "Puyallup",
    "Bonney Lake", "Lakewood", "University Place",
)

# Sort longest-name-first so multi-word cities are tried before any shorter
# name that could collide as a substring/word within them.
_WHITELIST_BY_LENGTH = sorted(WA_CITIES, key=len, reverse=True)

# name -> canonical Title Case, keyed by a lower/single-spaced normal form.
_CANONICAL_BY_KEY: dict[str, str] = {
    re.sub(r"\s+", " ", city).strip().lower(): city for city in WA_CITIES
}

# "... <city>, WA[ 98033]" or "... <city> WA[ 98033]" — the segment between
# the last comma (or start of string) and the WA token.
_STATE_SUFFIX_RE = re.compile(
    r"(?:^|,)\s*([A-Za-z][A-Za-z .'\-]*?)\s*,?\s+WA\b",
    re.IGNORECASE,
)

# Word-boundary match for a specific city name (allow internal whitespace to
# be one-or-more, in case of double spaces).
def _city_pattern(city: str) -> re.Pattern:
    escaped = re.escape(city).replace(r"\ ", r"\s+")
    return re.compile(rf"\b{escaped}\b", re.IGNORECASE)


_CITY_PATTERNS: tuple[tuple[str, re.Pattern], ...] = tuple(
    (city, _city_pattern(city)) for city in _WHITELIST_BY_LENGTH
)


def _lookup(candidate: str) -> Optional[str]:
    key = re.sub(r"\s+", " ", candidate).strip().lower()
    return _CANONICAL_BY_KEY.get(key)


def extract_city(address: Optional[str]) -> Optional[str]:
    """Best-effort extraction of a canonical WA city name from free text.

    Returns None for None/blank input or when nothing in the whitelist
    matches. Never raises.
    """
    if not address:
        return None
    text = str(address).strip()
    if not text:
        return None

    try:
        m = _STATE_SUFFIX_RE.search(text)
        if m:
            segment = m.group(1)
            # The segment may itself carry a street address before the city
            # ("123 Main St Kirkland" -> WA) — try the whole segment first
            # (handles plain "Kirkland, WA"), then fall back to scanning it.
            direct = _lookup(segment)
            if direct:
                return direct
            last_match: Optional[str] = None
            for city, pattern in _CITY_PATTERNS:
                if pattern.search(segment):
                    last_match = city
                    break  # longest-name-first list; first hit is the best.
            if last_match:
                return last_match
    except Exception:
        pass

    # Fallback: scan the whole string, preferring the LAST match position
    # (city sits near the end of US addresses) among longest-name-first
    # candidates so multi-word cities still win over substrings.
    best_city: Optional[str] = None
    best_pos = -1
    for city, pattern in _CITY_PATTERNS:
        last: Optional[re.Match] = None
        for match in pattern.finditer(text):
            last = match
        if last is not None and last.start() > best_pos:
            best_pos = last.start()
            best_city = city

    return best_city
