"""
Dispatch Agent — natural-language ride reassignment + payroll review.

Uses Anthropic Haiku with tool-use to:
  1. Understand requests like "move Rahim's 8am Tuesday ride to Dawit"
  2. Search rides + drivers via read-only DB tools
  3. Propose a reassignment (preview card) for user confirmation

Reviewer mode uses a separate, read-only tool set (reviewer_tools.py) for
pre-paystub batch sanity checks.  Dispatcher tools are never exposed when
mode == "reviewer", and reviewer tools are never exposed to the dispatcher.

Write operations are NEVER performed by the agent — the frontend
renders a preview and calls /rides/{id}/assign after confirm.
"""
from __future__ import annotations

import os
from datetime import date
from typing import Any

from sqlalchemy import Date, cast, text
from sqlalchemy.orm import Session

from backend.db.models import Person, Ride

MODEL = "claude-haiku-4-5-20251001"
MAX_TURNS = 6
UNASSIGNED_PERSON_ID = 227

# Legacy constant kept for any external code that imports SYSTEM_PROMPT directly.
# The canonical source of truth is now agent_modes/dispatcher.md.
def _load_default_system_prompt() -> str:
    from backend.services.agent_modes import get_system_prompt
    return get_system_prompt("dispatcher")

SYSTEM_PROMPT = _load_default_system_prompt()


# ─── Tool implementations ──────────────────────────────────────────────────

def _tool_search_rides(db: Session, args: dict) -> list[dict]:
    q = args.get("query", "")
    date_from = args.get("date_from")
    date_to = args.get("date_to")
    driver_name = args.get("driver_name")

    query = db.query(Ride, Person).join(Person, Ride.person_id == Person.person_id)
    if q:
        query = query.filter(Ride.service_name.ilike(f"%{q}%"))
    if driver_name:
        query = query.filter(Person.full_name.ilike(f"%{driver_name}%"))
    if date_from:
        query = query.filter(cast(Ride.ride_start_ts, Date) >= date_from)
    if date_to:
        query = query.filter(cast(Ride.ride_start_ts, Date) <= date_to)

    rows = query.order_by(Ride.ride_start_ts.desc()).limit(20).all()
    return [
        {
            "ride_id": ride.ride_id,
            "service_name": ride.service_name or "",
            "date": ride.ride_start_ts.date().isoformat() if ride.ride_start_ts else "",
            "driver": person.full_name,
            "driver_person_id": person.person_id,
            "source": ride.source,
        }
        for ride, person in rows
    ]


def _tool_list_drivers(db: Session, args: dict) -> list[dict]:
    q = args.get("query", "")
    rows = (
        db.query(Person)
        .filter(Person.active == True, Person.full_name.ilike(f"%{q}%"))  # noqa: E712
        .order_by(Person.full_name)
        .limit(15)
        .all()
    )
    return [
        {"person_id": p.person_id, "name": p.full_name, "phone": p.phone or ""}
        for p in rows
    ]


def _tool_find_route_drivers(db: Session, args: dict) -> list[dict]:
    service_name = args.get("service_name", "")
    if not service_name:
        return []
    rows = db.execute(
        text(
            """
            SELECT p.person_id, p.full_name, COUNT(*) as rides,
                   MAX(r.ride_start_ts)::date as last_driven
            FROM ride r
            JOIN person p ON r.person_id = p.person_id
            WHERE r.service_name = :service_name
              AND p.active = true
              AND p.full_name != 'Unassigned'
            GROUP BY p.person_id, p.full_name
            ORDER BY rides DESC, last_driven DESC
            LIMIT 10
            """
        ),
        {"service_name": service_name},
    ).fetchall()
    return [
        {
            "person_id": r.person_id,
            "name": r.full_name,
            "past_rides": r.rides,
            "last_driven": str(r.last_driven) if r.last_driven else "",
        }
        for r in rows
    ]


TOOLS = [
    {
        "name": "search_rides",
        "description": "Search rides by service name, driver name, and/or date range. Returns up to 20 matches.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Partial service name (e.g. 'Rose Hill', 'Mark Twain AM')"},
                "driver_name": {"type": "string", "description": "Partial driver name to filter by"},
                "date_from": {"type": "string", "description": "ISO date (YYYY-MM-DD), inclusive lower bound"},
                "date_to": {"type": "string", "description": "ISO date, inclusive upper bound"},
            },
        },
    },
    {
        "name": "list_drivers",
        "description": "Find active drivers by partial name match.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Partial driver name"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "find_route_drivers",
        "description": "For a given route (service_name), return active drivers who have driven it before, ranked by experience.",
        "input_schema": {
            "type": "object",
            "properties": {
                "service_name": {"type": "string", "description": "Exact service_name (e.g. 'Rose Hill ES IB 02_A')"},
            },
            "required": ["service_name"],
        },
    },
    {
        "name": "propose_reassignment",
        "description": "Propose moving a ride to a new driver. This does NOT execute the move — it shows the user a preview for confirmation. Only call this when you have verified both the ride_id and the target_person_id exist.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ride_id": {"type": "integer"},
                "target_person_id": {"type": "integer"},
                "summary": {"type": "string", "description": "One-line human-readable summary"},
                "notes": {"type": "string", "description": "Optional conflict warnings or context"},
            },
            "required": ["ride_id", "target_person_id", "summary"],
        },
    },
]


def _dispatch_tool(db: Session, name: str, args: dict) -> Any:
    if name == "search_rides":
        return _tool_search_rides(db, args)
    if name == "list_drivers":
        return _tool_list_drivers(db, args)
    if name == "find_route_drivers":
        return _tool_find_route_drivers(db, args)
    return {"error": f"Unknown tool: {name}"}


def _reviewer_tool(db: Session, name: str, args: dict) -> Any:
    """Dispatch reviewer-mode tool calls.  All functions here are read-only."""
    from backend.services.reviewer_tools import (
        find_anomalous_drivers,
        find_missing_paycheck_codes,
        find_zero_rides_with_pay,
        review_batch_totals,
    )

    batch_id = int(args.get("batch_id", 0))
    if name == "review_batch_totals":
        return review_batch_totals(db, batch_id)
    if name == "find_anomalous_drivers":
        return find_anomalous_drivers(db, batch_id)
    if name == "find_missing_paycheck_codes":
        return find_missing_paycheck_codes(db, batch_id)
    if name == "find_zero_rides_with_pay":
        return find_zero_rides_with_pay(db, batch_id)
    return {"error": f"Unknown reviewer tool: {name}"}


def run_agent(
    db: Session,
    message: str,
    history: list[dict] | None = None,
    system_prompt: str | None = None,
    mode: str = "dispatcher",
) -> dict:
    """
    Run a single conversational turn.

    Args:
      db: SQLAlchemy session.
      message: The user's latest message.
      history: Accumulated message history from previous turns.
      system_prompt: Override the system prompt. When omitted (None) the
                     dispatcher prompt is used — preserving existing behavior.
      mode: Agent mode string.  "reviewer" activates the read-only reviewer
            tool set.  All other values use the dispatcher tool set.

    Returns:
      {
        "reply": str,                        # agent's text response
        "proposed_action": dict | None,      # if agent called propose_reassignment
        "history": list[dict],               # updated message history for next turn
      }
    """
    from anthropic import Anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"reply": "ANTHROPIC_API_KEY not configured.", "proposed_action": None, "history": history or []}

    client = Anthropic(api_key=api_key)
    today = date.today().isoformat()
    mode_lower = mode.strip().lower() if mode else "dispatcher"
    is_reviewer = mode_lower == "reviewer"
    is_onboarder = mode_lower == "onboarder"

    if system_prompt is not None:
        active_prompt = system_prompt
    elif mode_lower not in ("dispatcher", ""):
        from backend.services.agent_modes import get_system_prompt as _get_mode_prompt
        active_prompt = _get_mode_prompt(mode_lower)
    else:
        active_prompt = SYSTEM_PROMPT
    system = f"{active_prompt}\n\nToday's date: {today}"

    # Select the correct tool schema for this mode.
    if is_reviewer:
        from backend.services.reviewer_tools import REVIEWER_TOOLS
        active_tools: list[dict] = REVIEWER_TOOLS
    elif is_onboarder:
        from backend.services.onboarder_tools import ONBOARDER_TOOLS
        active_tools = ONBOARDER_TOOLS
    else:
        active_tools = TOOLS

    messages: list[dict] = list(history or [])
    messages.append({"role": "user", "content": message})

    proposed_action: dict | None = None

    for _ in range(MAX_TURNS):
        resp = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=system,
            tools=active_tools,
            messages=messages,
        )

        assistant_content = resp.content
        messages.append({"role": "assistant", "content": [b.model_dump() for b in assistant_content]})

        if resp.stop_reason != "tool_use":
            text_parts = [b.text for b in assistant_content if getattr(b, "type", None) == "text"]
            return {
                "reply": "\n".join(text_parts).strip() or "(no response)",
                "proposed_action": proposed_action,
                "history": messages,
            }

        tool_results = []
        for block in assistant_content:
            if getattr(block, "type", None) != "tool_use":
                continue

            # ── Onboarder mode — all tools are read-only helpers ──────────
            if is_onboarder:
                try:
                    from backend.services.onboarder_tools import (
                        get_bgc_status,
                        get_cc_status,
                        get_onboarding_status,
                        list_pending_onboarding,
                    )
                    _onboarder_map = {
                        "get_onboarding_status": lambda args: get_onboarding_status(db, int(args["person_id"])),
                        "list_pending_onboarding": lambda args: list_pending_onboarding(db, int(args.get("limit", 20))),
                        "get_bgc_status": lambda args: get_bgc_status(db, int(args["person_id"])),
                        "get_cc_status": lambda args: get_cc_status(db, int(args["person_id"])),
                    }
                    fn = _onboarder_map.get(block.name)
                    if fn:
                        result = fn(block.input)
                    else:
                        result = {"error": f"Unknown onboarder tool: {block.name}"}
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(result),
                    })
                except Exception as exc:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"Error: {exc}",
                        "is_error": True,
                    })
                continue

            # ── Reviewer mode — all tools are read-only helpers ────────────
            if is_reviewer:
                try:
                    result = _reviewer_tool(db, block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(result),
                    })
                except Exception as exc:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"Error: {exc}",
                        "is_error": True,
                    })
                continue

            # ── Dispatcher mode ────────────────────────────────────────────
            if block.name == "propose_reassignment":
                ride = db.query(Ride).filter(Ride.ride_id == block.input["ride_id"]).first()
                target = db.query(Person).filter(
                    Person.person_id == block.input["target_person_id"]
                ).first()
                current_driver = None
                if ride:
                    cur = db.query(Person).filter(Person.person_id == ride.person_id).first()
                    current_driver = cur.full_name if cur else None

                if ride and target:
                    proposed_action = {
                        "ride_id": ride.ride_id,
                        "service_name": ride.service_name,
                        "ride_date": ride.ride_start_ts.date().isoformat() if ride.ride_start_ts else "",
                        "current_driver": current_driver,
                        "target_person_id": target.person_id,
                        "target_driver": target.full_name,
                        "summary": block.input.get("summary", ""),
                        "notes": block.input.get("notes", ""),
                    }
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "Preview shown to user. Await confirmation.",
                    })
                else:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"Invalid: ride={bool(ride)}, driver={bool(target)}",
                        "is_error": True,
                    })
            else:
                try:
                    result = _dispatch_tool(db, block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(result),
                    })
                except Exception as exc:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"Error: {exc}",
                        "is_error": True,
                    })

        messages.append({"role": "user", "content": tool_results})

        if proposed_action is not None:
            return {
                "reply": proposed_action["summary"],
                "proposed_action": proposed_action,
                "history": messages,
            }

    return {
        "reply": "(agent exceeded max turns)",
        "proposed_action": proposed_action,
        "history": messages,
    }
