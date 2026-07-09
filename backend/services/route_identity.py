"""
FA route-name parsing — the identity layer under Pricing Engine v2.

Ground truth (Malik, 2026-07-08, reference_zpay_route_naming_semantics):
FA route numbers are per-STUDENT pairings — "Kent Meridian HS IB 17" is one
kid's ride, stable within a school season, renumbered at season boundaries.
The PRICE follows the DISTANCE, not the number. In-season, FA churns the
NAME without changing the ride: variant letters, day markers, wheelchair
markers, extra-run blocks. All of that is noise around a stable identity:

    (school, direction, number)

Observed grammar (prod, 9.6k acumen rides):

    <School Name> <IB|OB> [ODT ]<NN>[ (<marker>)][_<variant>][ ER<mmddyy> <NN>]

    - direction: IB (inbound / to school) or OB (outbound / home)
    - ODT: on-demand-trip prefix on the number — same pairing, strip it
    - markers: (W) (M) (F) day-of-week, (HCV) wheelchair vehicle
    - variant: _A/_B/_D... — FA re-issues of the same route
    - ER block: extra run, ER + date + sequence — an add-on trip re-using
      the base route's name

Unparseable names (e.g. "[RECONCILE_ADJ]") return None — they are
adjustments, not routes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# Trailing add-on blocks: " ER012726 01" (extra run), " LS022626 01" (late
# start) — two letters + 6-digit date + sequence. Strip iteratively; FA keeps
# inventing prefixes, the shape is what's stable.
_ER_BLOCK_RE = re.compile(r"\s+[A-Z]{2}\s?\d{6}\s+\d{1,2}$")
# Trailing variant letter: "_A" — FA sometimes typos a space ("OB 04_ F").
_VARIANT_RE = re.compile(r"_\s?([A-Z])$")
# Markers after the direction: (W) (M) (F) (HCV) (M/T) (T/H) and bracket
# forms like [Wt].
_MARKER_RE = re.compile(r"\s*[(\[]([A-Za-z/]{1,5})[)\]]")
# Core shape after stripping: school + direction + optional ODT + number.
_CORE_RE = re.compile(r"^(?P<school>.+?)\s+(?P<direction>IB|OB)\s+(?:(?P<odt>ODT)\s+)?(?P<number>\d{1,2})$")
# Day-of-week schedule markers (single or slash-combined): W, M, F, T, TH, M/T…
_DAY_MARKER_RE = re.compile(r"^(?:M|T|W|TH|H|F)(?:/(?:M|T|W|TH|H|F))*$", re.IGNORECASE)


@dataclass(frozen=True)
class RouteIdentity:
    """The stable student-pairing identity parsed from an FA route name."""
    school: str          # normalized school text (single-spaced)
    direction: str       # "IB" | "OB"
    number: str          # zero-padded two digits, e.g. "02"
    is_odt: bool
    markers: tuple[str, ...]   # e.g. ("W",) or ("HCV",)
    variant: Optional[str]     # "A" / "B" / ... or None
    raw: str

    @property
    def key(self) -> tuple[str, str, str]:
        """Tier-1 identity: same key = same student pairing = same rate."""
        return (self.school.lower(), self.direction, self.number)

    @property
    def day_markers(self) -> frozenset[str]:
        """Schedule-modifier markers — (W)/(M)/(F)/(M/T)... — which the
        2026-07-09 replay proved are SOMETIMES price-affecting (early-release
        runs get repriced). Equipment markers like (HCV)/[Wt] are excluded —
        they proved price-neutral."""
        return frozenset(
            m.upper() for m in self.markers if _DAY_MARKER_RE.match(m)
        )

    @property
    def school_direction_key(self) -> tuple[str, str]:
        """Tier-2 scope: candidates for price inheritance by distance."""
        return (self.school.lower(), self.direction)


def parse_route_identity(service_name: Optional[str]) -> Optional[RouteIdentity]:
    """Parse an FA route name into its identity, or None if not a route."""
    if not service_name:
        return None
    name = re.sub(r"\s+", " ", str(service_name)).strip()
    if not name or name.startswith("["):
        return None

    raw = name

    # 1. Strip extra-run blocks (may stack in principle — strip until stable).
    while True:
        stripped = _ER_BLOCK_RE.sub("", name)
        if stripped == name:
            break
        name = stripped

    # 2. Strip trailing variant letter.
    variant: Optional[str] = None
    m = _VARIANT_RE.search(name)
    if m:
        variant = m.group(1)
        name = name[: m.start()]

    # 3. Collect + strip parenthesised markers.
    markers = tuple(_MARKER_RE.findall(name))
    if markers:
        name = _MARKER_RE.sub("", name).strip()

    # 4. A variant letter can also sit before a marker/ER block
    #    ("OB 03 (W)_A ER061726 01" strips ER, then _A, then (W) — but
    #    "OB 03_A (W)" would leave _A inside; strip once more).
    m = _VARIANT_RE.search(name)
    if m and variant is None:
        variant = m.group(1)
        name = name[: m.start()]

    name = re.sub(r"\s+", " ", name).strip()

    core = _CORE_RE.match(name)
    if not core:
        return None

    school = re.sub(r"\s+", " ", core.group("school")).strip()
    if not school:
        return None

    return RouteIdentity(
        school=school,
        direction=core.group("direction"),
        number=core.group("number").zfill(2),
        is_odt=core.group("odt") is not None,
        markers=markers,
        variant=variant,
        raw=raw,
    )
