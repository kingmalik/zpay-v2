"""
Onboarder mode tools — read-only driver onboarding status checks.

ALL functions here are strictly read-only.  No db.commit(), no db.add(),
no db.delete().  The agent advises; the human acts.

FA/Acumen 8-step flow:
  1  Application received
  2  BGC order placed (FADV)
  3  BGC cleared
  4  Contract sent (Adobe Sign)
  5  Contract signed
  6  CC invite sent (Contractor Compliance)
  7  CC profile active
  8  FirstAlt portal access granted
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

# OnboardingRecord and Person are imported lazily inside each function body
# to avoid module-level stub collisions in tests (test_fa_onboarding.py stubs
# backend.db.models as an empty module at collection time).


# ─── Step mapping ──────────────────────────────────────────────────────────────

# Each tuple: (step_number, step_name, status_field_or_None, completion_value)
# We derive the current step by walking the list and finding the first one that
# is NOT "complete" / "signed" / "active" / "granted".
_FA_STEPS: list[tuple[int, str, str | None]] = [
    (1, "Application received",          "intake_submitted_at"),      # datetime field
    (2, "BGC order placed",              "fadv_status"),               # text: pending|initiated|clear|consider|suspended
    (3, "BGC cleared",                   "bgc_status"),                # text: pending|complete
    (4, "Contract sent",                 "contract_status"),           # text: pending|sent|signed|complete
    (5, "Contract signed",               "contract_status"),           # same field — "signed"/"complete" = done
    (6, "CC invite sent",                "cc_invite_sent_at"),         # datetime field
    (7, "CC profile active",             "cc_id"),                     # populated = active
    (8, "FirstAlt portal access",        "priority_email_status"),     # text: pending|sent|complete
]

_STEP_DONE_VALUES: dict[str, set[str]] = {
    "fadv_status":           {"clear", "consider", "suspended"},  # any result = order placed & processed
    "bgc_status":            {"complete", "clear"},
    "contract_status_sent":  {"sent", "signed", "complete", "manual"},
    "contract_status_signed":{"signed", "complete"},
    "priority_email_status": {"sent", "complete", "manual"},
}

_NEXT_ACTIONS: dict[int, str] = {
    1: "Driver or Malik submits the intake application",
    2: "Malik orders the BGC through First Advantage (FADV portal)",
    3: "Wait for FADV to return a result — usually 1–3 business days",
    4: "Malik sends the Acumen contract via Adobe Sign",
    5: "Driver signs the contract (Adobe Sign email to driver)",
    6: "Malik sends the Contractor Compliance invite to the driver",
    7: "Driver completes their CC profile (on their end)",
    8: "Malik grants the driver access on the FirstAlt partner portal",
}


def _derive_step(rec) -> tuple[int, str, str]:
    """
    Walk the 8 FA steps and return (current_step, step_name, next_action).
    Returns step 8 + "complete" if everything is done.
    """
    # Step 1 — application
    if not rec.intake_submitted_at:
        return 1, _FA_STEPS[0][1], _NEXT_ACTIONS[1]

    # Step 2 — BGC order placed
    fadv = (rec.fadv_status or "").lower()
    if fadv not in {"initiated", "clear", "consider", "suspended", "complete"}:
        return 2, _FA_STEPS[1][1], _NEXT_ACTIONS[2]

    # Step 3 — BGC cleared
    bgc = (rec.bgc_status or "").lower()
    if bgc not in {"complete", "clear"}:
        return 3, _FA_STEPS[2][1], _NEXT_ACTIONS[3]

    # Step 4 — Contract sent
    contract = (rec.contract_status or "").lower()
    if contract not in {"sent", "signed", "complete", "manual"}:
        return 4, _FA_STEPS[3][1], _NEXT_ACTIONS[4]

    # Step 5 — Contract signed
    if contract not in {"signed", "complete"}:
        return 5, _FA_STEPS[4][1], _NEXT_ACTIONS[5]

    # Step 6 — CC invite sent
    if not rec.cc_invite_sent_at:
        return 6, _FA_STEPS[5][1], _NEXT_ACTIONS[6]

    # Step 7 — CC profile active
    if not rec.cc_id:
        return 7, _FA_STEPS[6][1], _NEXT_ACTIONS[7]

    # Step 8 — Portal access
    portal = (rec.priority_email_status or "").lower()
    if portal not in {"sent", "complete", "manual"}:
        return 8, _FA_STEPS[7][1], _NEXT_ACTIONS[8]

    # Fully complete
    return 8, "Portal access granted — onboarding complete", "Nothing — driver is fully onboarded"


def _days_since(dt: datetime | None) -> int | None:
    """Return days since a UTC datetime, or None if dt is None."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(tz=timezone.utc) - dt
    return max(0, delta.days)


# ─── Public tool functions ─────────────────────────────────────────────────────

def get_onboarding_status(db: Session, person_id: int) -> dict[str, Any]:
    """
    Return the onboarding state for a single driver.

    READ-ONLY — no commits.
    """
    from backend.db.models import OnboardingRecord, Person  # lazy — avoids test stub collision
    person = db.query(Person).filter(Person.person_id == person_id).first()
    if person is None:
        return {"error": f"No driver found with person_id={person_id}"}

    rec = (
        db.query(OnboardingRecord)
        .filter(OnboardingRecord.person_id == person_id)
        .first()
    )

    if rec is None:
        return {
            "person_id": person_id,
            "name": person.full_name,
            "status": "not_started",
            "step": 0,
            "step_name": "Not started",
            "next_action": _NEXT_ACTIONS[1],
            "days_at_current_step": None,
            "notes": None,
            "partner": "firstalt",
        }

    step_num, step_name, next_action = _derive_step(rec)
    is_complete = step_num == 8 and step_name.startswith("Portal access granted")

    return {
        "person_id": person_id,
        "name": person.full_name,
        "status": "complete" if is_complete else "in_progress",
        "step": step_num,
        "step_name": step_name,
        "step_of_total": f"Step {step_num} of 8",
        "next_action": next_action,
        "days_since_started": _days_since(rec.started_at),
        "notes": rec.notes,
        "partner": rec.partner or "firstalt",
        "fadv_status": rec.fadv_status,
        "bgc_status": rec.bgc_status,
        "contract_status": rec.contract_status,
        "cc_invite_sent": rec.cc_invite_sent_at is not None,
        "cc_id": rec.cc_id,
    }


def list_pending_onboarding(db: Session, limit: int = 20) -> dict[str, Any]:
    """
    Return all drivers currently mid-onboarding (not yet fully done),
    sorted by days stuck at current step (longest first).

    READ-ONLY — no commits.
    """
    rows = db.execute(
        text(
            """
            SELECT
                o.id            AS onboarding_id,
                o.person_id,
                p.full_name,
                o.started_at,
                o.intake_submitted_at,
                o.fadv_status,
                o.bgc_status,
                o.contract_status,
                o.cc_invite_sent_at,
                o.cc_id,
                o.priority_email_status,
                o.notes,
                o.partner
            FROM onboarding_record o
            JOIN person p ON o.person_id = p.person_id
            WHERE o.completed_at IS NULL
            ORDER BY o.started_at ASC
            LIMIT :limit
            """
        ),
        {"limit": limit},
    ).fetchall()

    drivers: list[dict[str, Any]] = []
    for r in rows:
        # Build a minimal record-like object to reuse _derive_step
        class _Stub:
            intake_submitted_at = r.intake_submitted_at
            fadv_status = r.fadv_status
            bgc_status = r.bgc_status
            contract_status = r.contract_status
            cc_invite_sent_at = r.cc_invite_sent_at
            cc_id = r.cc_id
            priority_email_status = r.priority_email_status

        step_num, step_name, next_action = _derive_step(_Stub())
        days_since_started = _days_since(r.started_at)

        drivers.append({
            "person_id": r.person_id,
            "name": r.full_name,
            "step": step_num,
            "step_name": step_name,
            "step_of_total": f"Step {step_num} of 8",
            "next_action": next_action,
            "days_since_started": days_since_started,
            "partner": r.partner or "firstalt",
            "notes": r.notes,
        })

    # Sort by days_since_started descending (stuck longest first)
    drivers.sort(key=lambda d: d["days_since_started"] or 0, reverse=True)

    return {
        "count": len(drivers),
        "drivers": drivers,
    }


def get_bgc_status(db: Session, person_id: int) -> dict[str, Any]:
    """
    Return the BGC (background check) status for a driver.

    Uses the fadv_report_id and fadv_status fields from onboarding_record.
    The actual FADV API call is a TODO — right now this returns stored state.

    READ-ONLY — no commits.
    """
    from backend.db.models import OnboardingRecord, Person  # lazy — avoids test stub collision
    # TODO: plug in FADV API when credentials available — for now return stored state
    person = db.query(Person).filter(Person.person_id == person_id).first()
    if person is None:
        return {"error": f"No driver found with person_id={person_id}"}

    rec = (
        db.query(OnboardingRecord)
        .filter(OnboardingRecord.person_id == person_id)
        .first()
    )

    if rec is None:
        return {
            "person_id": person_id,
            "name": person.full_name,
            "bgc_submitted": False,
            "fadv_report_id": None,
            "fadv_status": "Not submitted yet",
            "initiated_at": None,
            "result_at": None,
        }

    return {
        "person_id": person_id,
        "name": person.full_name,
        "bgc_submitted": rec.fadv_report_id is not None,
        "fadv_report_id": rec.fadv_report_id,
        "fadv_status": rec.fadv_status or "Not submitted yet",
        "initiated_at": rec.fadv_initiated_at.isoformat() if rec.fadv_initiated_at else None,
        "result_at": rec.fadv_result_at.isoformat() if rec.fadv_result_at else None,
        "bgc_status_field": rec.bgc_status,
    }


def get_cc_status(db: Session, person_id: int) -> dict[str, Any]:
    """
    Return the Contractor Compliance invite/profile status for a driver.

    NOTE: CC API not yet connected — returns stored fields only.

    READ-ONLY — no commits.
    """
    from backend.db.models import OnboardingRecord, Person  # lazy — avoids test stub collision
    person = db.query(Person).filter(Person.person_id == person_id).first()
    if person is None:
        return {"error": f"No driver found with person_id={person_id}"}

    rec = (
        db.query(OnboardingRecord)
        .filter(OnboardingRecord.person_id == person_id)
        .first()
    )

    if rec is None:
        return {
            "person_id": person_id,
            "name": person.full_name,
            "invite_sent": False,
            "invite_sent_at": None,
            "cc_id": None,
            "cc_profile_active": False,
            "note": "No onboarding record found",
        }

    return {
        "person_id": person_id,
        "name": person.full_name,
        "invite_sent": rec.cc_invite_sent_at is not None,
        "invite_sent_at": rec.cc_invite_sent_at.isoformat() if rec.cc_invite_sent_at else None,
        "cc_id": rec.cc_id,
        "cc_profile_active": rec.cc_id is not None,
        # NOTE: cc_status JSON field holds raw CC API payload when available
        "cc_status_raw": rec.cc_status,
        "note": "CC API not yet connected — profile_active is inferred from cc_id presence",
    }


# ─── Anthropic tool schema ─────────────────────────────────────────────────────

ONBOARDER_TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_onboarding_status",
        "description": (
            "Get the full onboarding status for a single driver. "
            "Returns their current step (1-8), step name, how long they've been "
            "at this step, the next required action, and any blocker notes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "person_id": {
                    "type": "integer",
                    "description": "The person_id of the driver to check",
                },
            },
            "required": ["person_id"],
        },
    },
    {
        "name": "list_pending_onboarding",
        "description": (
            "List all drivers currently mid-onboarding (not yet fully done), "
            "sorted by how long they've been stuck (longest first). "
            "Use this to answer 'who needs attention today?'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of drivers to return (default 20)",
                },
            },
        },
    },
    {
        "name": "get_bgc_status",
        "description": (
            "Get the background check (BGC) status for a driver. "
            "Returns the FADV report ID, status (pending/initiated/clear/consider/suspended), "
            "and when it was initiated and completed. "
            "Note: live FADV API not yet connected — returns stored state."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "person_id": {
                    "type": "integer",
                    "description": "The person_id of the driver to check",
                },
            },
            "required": ["person_id"],
        },
    },
    {
        "name": "get_cc_status",
        "description": (
            "Get the Contractor Compliance invite and profile status for a driver. "
            "Returns whether the invite was sent, when, the CC ID if the driver "
            "completed their profile, and whether their profile is active. "
            "Note: CC API not yet connected — profile_active is inferred from cc_id presence."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "person_id": {
                    "type": "integer",
                    "description": "The person_id of the driver to check",
                },
            },
            "required": ["person_id"],
        },
    },
]
