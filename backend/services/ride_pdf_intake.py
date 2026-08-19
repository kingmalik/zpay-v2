"""
backend/services/ride_pdf_intake.py
====================================
FirstAlt/Acumen "Trip Plan" PDF -> ride_intake_service-shaped dicts.

These are NOT the tabular EverDriven/Maz payroll PDFs backend/services/
pdf_reader.py handles. FirstAlt's "Trip Plan" attachment is a flattened
image -- an HTML card + a Google Maps screenshot rendered straight to a PDF
page, zero extractable text layer. Confirmed against 5 real samples pulled
from the contact.acumenintl@gmail.com inbox (2026-08-19): pdfplumber and
poppler's pdftotext both return nothing (0 chars/page); the only content is
1-6 embedded raster images per page. So this module never touches
pdfplumber -- it renders each page to a PNG (PyMuPDF, pip-only, no system
deps) and reads it back with Claude's vision API, using the same Anthropic
call shape as daily_brief.py / dispatch_agent.py (Anthropic(api_key=...),
ANTHROPIC_API_KEY env var, module-level MODEL constant).

The trip-plan title text ("Bell ES OB 01 (W) - Trip Plan 1") uses the exact
grammar backend/services/route_identity.py already parses for FA route
identity everywhere else in the app. The vision call only has to read that
string verbatim -- route_identity.parse_route_identity() does the actual
school/direction/number/is_odt parsing deterministically, so identity never
depends on the model guessing at structured fields it might get wrong.

Some routes have more than 2 stops (e.g. two pickups at different schools
before one shared dropoff -- see Columbia_JHS_Surprise_Lake_MS_OB_01.pdf).
season_ride only ever has room for ONE pickup + ONE dropoff, so the model is
asked for a `stops` array in printed order; the first stop maps to
pickup_time/origin and the last to dropoff_time/destination exactly like a
normal 2-stop card, and anything in between is never silently dropped -- it
gets written into `notes` as an explicit "unmapped stop" line and the row is
flagged `needs_info=True` (2026-08-19, Malik: "silent data loss is worse
than a loud unknown"). season_pool.upsert_from_intake reads that flag and
skips corridor-city derivation for the row, which surfaces it in the
board's existing "unplaced"/needs-a-look bucket instead of pooling it as if
it were a fully-captured route.

Public API:
    parse_intake_from_pdf(file_bytes: bytes) -> list[dict]
        Zero or one dict (today's samples are always a single trip-plan card
        per PDF; kept list-shaped for any future multi-card PDF), shaped
        exactly like ride_intake_service.parse_intake()'s return value plus
        one additive `needs_info` key (same "extended fields" convention
        parse_intake itself already uses) -- a drop-in match for
        RideIntake.parsed / season_pool.upsert_from_intake. Never raises: a
        PDF that can't be opened/rendered/extracted returns [] and logs why.
        Optional at every layer -- callers with no ANTHROPIC_API_KEY
        configured get [] back, not an exception.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any, Optional

from backend.services.route_identity import RouteIdentity, parse_route_identity

logger = logging.getLogger("zpay.ride_pdf_intake")

# Same model-selection convention as daily_brief.py / dispatch_agent.py --
# one module-level constant, not pinned inline at the call site.
MODEL = "claude-haiku-4-5-20251001"

MAX_PAGES = 2
RENDER_ZOOM = 2.0  # ~144dpi -- readable text without an oversized PNG

_TITLE_SUFFIX_RE = re.compile(r"\s*-\s*Trip Plan\s*\d*\s*$", re.IGNORECASE)

_BAD_STRINGS = {"", "-", "–", "—", "n/a", "na", "none", "null"}

# FirstAlt's day badge sometimes shows "H" for Thursday (visually distinct
# from "T" for Tuesday) instead of the "Th" the rest of the codebase uses
# (ride_intake_service._DAY_TOKENS) -- normalize every spelling into that
# same single convention so days flow into season_ride.days consistently
# regardless of which parser produced them.
_DAY_BADGE_MAP = {
    "M": "M", "MON": "M", "MONDAY": "M",
    "T": "T", "TUE": "T", "TUES": "T", "TUESDAY": "T",
    "W": "W", "WED": "W", "WEDNESDAY": "W",
    "TH": "Th", "H": "Th", "THU": "Th", "THUR": "Th", "THURS": "Th", "THURSDAY": "Th",
    "F": "F", "FRI": "F", "FRIDAY": "F",
}

_EXTRACTION_PROMPT = """You are reading a FirstAlt/Acumen student-transportation "Trip Plan" PDF, rendered here as one or two page images of a SINGLE trip-plan card (a title bar, a small info table, a map, a Schedule section, and a Student Details table).

Extract these fields and return ONLY one JSON object -- no array, no prose, no markdown code fence -- with exactly these keys. Use null for anything not visible or not legible. Never guess or invent a value.

{
  "trip_plan_title": the header text verbatim, e.g. "Bell ES OB 01 (W) - Trip Plan 1",
  "direction": "IB" or "OB" if shown near "Schedule",
  "route_number": the route number as printed in the title, e.g. "01",
  "is_odt": true only if the literal text "ODT" appears in the title, else false,
  "applicable_days": array of the day-badge tokens shown next to "Applicable Days:" (e.g. ["M","T","H","F"] or ["W"]),
  "start_date": the "Start Date:" value as printed,
  "end_date": the "End Date:" value as printed,
  "stops": array of EVERY numbered stop shown under "Schedule", in the order printed (most cards have exactly 2 -- one pickup, one dropoff -- but some have 3+ when the route serves multiple students at different addresses). Each stop is an object:
    {"type": "pickup" or "dropoff", "time": the stop's time, "location": the stop's name + street address, "student": the student name shown at that stop, or null},
  "mileage": the "Mileage" field value as a plain number (no units), or null,
  "driver_assigned": the "Driver" field value (often "Unassigned"),
  "wheelchair_equipment_needed": true if wheelchair/HCV equipment is indicated anywhere on the card, else false,
  "students": array of objects {"name": ..., "equipment": ..., "notes": ...} from the Student Details table -- use null for any "-" cell
}

Return only the JSON object, nothing else."""


def _clean(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in _BAD_STRINGS:
        return None
    return text


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _norm_direction(value: Any) -> Optional[str]:
    text = _clean(value)
    if not text:
        return None
    upper = text.strip().upper()
    if upper in ("IB", "INBOUND"):
        return "IB"
    if upper in ("OB", "OUTBOUND"):
        return "OB"
    return None


def _norm_days(raw_days: Any) -> Optional[list[str]]:
    if not raw_days:
        return None
    if isinstance(raw_days, str):
        tokens = re.split(r"[,\s/]+", raw_days.strip())
    elif isinstance(raw_days, (list, tuple)):
        tokens = [str(t) for t in raw_days]
    else:
        return None

    out: list[str] = []
    for token in tokens:
        key = token.strip().upper()
        if not key:
            continue
        code = _DAY_BADGE_MAP.get(key)
        if code and code not in out:
            out.append(code)
    return out or None


def _extract_wheelchair(card: dict, identity: Optional[RouteIdentity]) -> bool:
    if identity is not None and any(
        marker.upper() in ("HCV", "WT") for marker in identity.markers
    ):
        return True
    if card.get("wheelchair_equipment_needed"):
        return True
    for student in card.get("students") or []:
        equipment = str((student or {}).get("equipment") or "")
        if re.search(r"wheelchair|w/c|hcv", equipment, re.IGNORECASE):
            return True
    return False


def _extract_requirements(card: dict) -> Optional[list[str]]:
    out: list[str] = []
    for student in card.get("students") or []:
        equipment = _clean((student or {}).get("equipment"))
        if equipment:
            out.append(equipment)
    return out or None


def _split_stops(card: dict) -> tuple[Optional[dict], Optional[dict], list[dict]]:
    """(first_stop, last_stop, intermediate_stops) from the card's `stops`
    array, in printed order.

    season_ride only ever has room for ONE pickup + ONE dropoff (schema:
    pickup_time/pickup_address/dropoff_time/dropoff_address), so a normal
    2-stop card maps cleanly -- first stop -> pickup, last stop -> dropoff.
    A route with 3+ stops (e.g. two pickups at different schools before one
    shared dropoff) genuinely doesn't fit that shape; the stops in between
    are returned separately so the caller can surface them instead of
    silently dropping them."""
    stops = card.get("stops")
    if not isinstance(stops, list):
        return None, None, []
    stops = [s for s in stops if isinstance(s, dict)]
    if not stops:
        return None, None, []
    if len(stops) == 1:
        return stops[0], stops[0], []
    return stops[0], stops[-1], stops[1:-1]


def _describe_stop(stop: dict, index: int) -> str:
    stop_type = _clean(stop.get("type")) or "stop"
    time_ = _clean(stop.get("time"))
    location = _clean(stop.get("location"))
    student = _clean(stop.get("student"))
    line = f"unmapped stop {index}: {stop_type} {time_ or '?'} @ {location or '?'}"
    if student:
        line += f" ({student})"
    return line


def _build_notes(
    card: dict, title: Optional[str],
    first_stop: Optional[dict], last_stop: Optional[dict],
    intermediate_stops: list[dict],
) -> Optional[str]:
    """Human-readable summary carrying everything the parse_intake contract
    doesn't have a dedicated field for (student names, exact addresses,
    driver-on-card, end date, and any stop beyond the first pickup/last
    dropoff) -- same "carry the rest in notes" convention
    ride_intake_service._build_notes already uses."""
    bits: list[str] = []
    if title:
        bits.append(title)

    students = card.get("students") or []
    names = [n for n in (_clean((s or {}).get("name")) for s in students) if n]
    if names:
        bits.append("student(s): " + ", ".join(names))

    pickup_time = _clean((first_stop or {}).get("time"))
    pickup_loc = _clean((first_stop or {}).get("location"))
    if pickup_time or pickup_loc:
        bits.append(f"pickup {pickup_time or '?'} @ {pickup_loc or '?'}")

    dropoff_time = _clean((last_stop or {}).get("time"))
    dropoff_loc = _clean((last_stop or {}).get("location"))
    if dropoff_time or dropoff_loc:
        bits.append(f"dropoff {dropoff_time or '?'} @ {dropoff_loc or '?'}")

    start_date = _clean(card.get("start_date"))
    end_date = _clean(card.get("end_date"))
    if start_date or end_date:
        bits.append(f"{start_date or '?'} → {end_date or '?'}")

    driver = _clean(card.get("driver_assigned"))
    if driver and driver.lower() != "unassigned":
        bits.append(f"driver on card: {driver}")

    # Loud, on purpose (Malik, 2026-08-19): silent data loss on a
    # multi-stop route is worse than an obvious unknown -- mom needs to see
    # this ride wasn't fully captured, not trust a quietly-truncated route.
    if intermediate_stops:
        bits.append(
            f"⚠ MULTI-STOP ROUTE — {len(intermediate_stops) + 2} stops total, "
            f"only the first pickup + final dropoff are in the fields above"
        )
        for i, stop in enumerate(intermediate_stops, start=1):
            bits.append(_describe_stop(stop, i))

    for student in students:
        note = _clean((student or {}).get("notes"))
        if note:
            bits.append(f"note: {note}")

    return " · ".join(bits) or None


def _map_card_to_intake(card: dict) -> Optional[dict]:
    """One vision-extracted card -> one parse_intake-shaped dict, or None
    when the card doesn't carry enough identity (school/direction/number)
    to be pooled -- mirrors season_pool.upsert_from_intake's own
    ValueError guard, just checked earlier so a bad card is skipped rather
    than raised."""
    title = _clean(card.get("trip_plan_title"))
    identity_str = _TITLE_SUFFIX_RE.sub("", title).strip() if title else ""
    identity = parse_route_identity(identity_str) if identity_str else None

    if identity is not None:
        school, direction, number, is_odt = (
            identity.school, identity.direction, identity.number, identity.is_odt,
        )
    else:
        school, direction, number, is_odt = (
            None, _norm_direction(card.get("direction")),
            _clean(card.get("route_number")), bool(card.get("is_odt") or False),
        )

    if not school or not direction or not number:
        return None

    start_date = _clean(card.get("start_date"))
    end_date = _clean(card.get("end_date"))
    # FirstAlt Trip Plan cards are standing routes for the school year, not
    # one-off trips -- a distinct start/end date range is a strong recurring
    # signal. Leave None (unknown) rather than guess when dates are missing,
    # same "don't guess" contract as the rest of parse_intake.
    is_recurring = True if (start_date and end_date and start_date != end_date) else None

    first_stop, last_stop, intermediate_stops = _split_stops(card)
    needs_info = bool(intermediate_stops)

    return {
        "school": school,
        "direction": direction,
        "number": number,
        "is_odt": bool(is_odt),
        "wheelchair": _extract_wheelchair(card, identity),
        "miles": _to_float(card.get("mileage")),
        # Trip Plan cards never show a dollar figure -- pay is negotiated
        # separately in the email thread and already captured by
        # ride_intake_service.parse_intake on the body text.
        "net_pay": None,
        "days": _norm_days(card.get("applicable_days")),
        "start_time": _clean((first_stop or {}).get("time")),
        "notes": _build_notes(card, title, first_stop, last_stop, intermediate_stops),
        "district": None,
        "is_recurring": is_recurring,
        "net_pay_ib": None,
        "net_pay_ob": None,
        "start_date": start_date,
        "origin": _clean((first_stop or {}).get("location")),
        "destination": _clean((last_stop or {}).get("location")),
        "requirements": _extract_requirements(card),
        # Additive to the parse_intake contract (same "extended fields"
        # convention ride_intake_service.parse_intake itself uses for
        # net_pay_ib/origin/etc) -- season_pool.upsert_from_intake reads
        # this to skip corridor-city derivation on a truncated route, which
        # surfaces the row in the board's existing "unplaced/needs a look"
        # bucket instead of silently trusting it.
        "needs_info": needs_info,
    }


def _render_pages_to_png(file_bytes: bytes) -> list[bytes]:
    """PDF bytes -> up to MAX_PAGES page images (PNG bytes). [] on any
    failure -- never raises."""
    try:
        import fitz  # PyMuPDF
    except Exception as exc:
        logger.warning("[ride_pdf_intake] PyMuPDF not available: %s", exc)
        return []

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as exc:
        logger.warning("[ride_pdf_intake] could not open PDF: %s", exc)
        return []

    images: list[bytes] = []
    try:
        matrix = fitz.Matrix(RENDER_ZOOM, RENDER_ZOOM)
        for i, page in enumerate(doc):
            if i >= MAX_PAGES:
                break
            try:
                pix = page.get_pixmap(matrix=matrix)
                images.append(pix.tobytes("png"))
            except Exception as exc:
                logger.warning("[ride_pdf_intake] failed to render page %d: %s", i, exc)
    finally:
        doc.close()

    return images


def _parse_json_object(raw: str) -> Optional[dict]:
    """Defensive JSON parse -- strips a stray markdown fence if the model
    added one despite instructions not to. None on any parse failure."""
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except Exception as exc:
        logger.warning(
            "[ride_pdf_intake] model returned non-JSON (%s): %r", exc, text[:200]
        )
        return None
    return data if isinstance(data, dict) else None


def _call_vision_extraction(png_pages: list[bytes]) -> Optional[dict]:
    """One Anthropic vision call over the rendered page(s). None when the
    key is absent, the call fails, or the response isn't parseable JSON --
    callers treat None exactly like "couldn't extract this PDF"."""
    import os

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.info("[ride_pdf_intake] ANTHROPIC_API_KEY not set -- skipping PDF extraction")
        return None

    try:
        from anthropic import Anthropic

        content: list[dict] = []
        for png_bytes in png_pages:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": base64.standard_b64encode(png_bytes).decode("ascii"),
                },
            })
        content.append({"type": "text", "text": _EXTRACTION_PROMPT})

        client = Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=MODEL,
            max_tokens=1200,
            messages=[{"role": "user", "content": content}],
        )
        text_parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
        raw = "\n".join(text_parts).strip()
        return _parse_json_object(raw)
    except Exception as exc:
        logger.warning("[ride_pdf_intake] vision extraction call failed: %s", exc)
        return None


def parse_intake_from_pdf(file_bytes: bytes) -> list[dict]:
    """FirstAlt/Acumen Trip Plan PDF bytes -> list of parse_intake-shaped
    dicts. Never raises -- any failure (bad PDF, no PyMuPDF, no API key,
    a failed/garbled model call, a card with no resolvable route identity)
    logs a reason and returns []."""
    if not file_bytes:
        return []

    try:
        png_pages = _render_pages_to_png(file_bytes)
    except Exception as exc:  # belt-and-suspenders -- _render_pages_to_png already guards
        logger.warning("[ride_pdf_intake] unexpected render failure: %s", exc)
        return []

    if not png_pages:
        logger.info("[ride_pdf_intake] no renderable pages -- returning []")
        return []

    card = _call_vision_extraction(png_pages)
    if not card:
        return []

    try:
        mapped = _map_card_to_intake(card)
    except Exception as exc:
        logger.warning("[ride_pdf_intake] failed to map extracted card: %s", exc)
        return []

    if mapped is None:
        logger.info(
            "[ride_pdf_intake] extraction ran but produced no usable route identity "
            "(title=%r)", card.get("trip_plan_title"),
        )
        return []

    return [mapped]
