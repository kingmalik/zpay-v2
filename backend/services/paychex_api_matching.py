"""
backend/services/paychex_api_matching.py
==========================================
Pure, I/O-free helpers for the Paychex API rail (backend/services/paychex_api.py,
backend/routes/paychex_api.py). Split out from paychex_api.py to keep both files
under the 400-line house limit — this one holds the row/worker matching logic,
paychex_api.py holds the HTTP client.

Every function here takes plain dicts/lists and returns NEW dicts/lists —
inputs are never mutated (repo immutability rule).
"""

from __future__ import annotations

from backend.services.paychex_api import CONTRACTOR_WORKER_TYPE, _to_iso_date

# ── Pure helpers (no I/O — easy to unit test in isolation) ─────────────────

def _worker_display_name(worker: dict) -> str | None:
    name = worker.get("name")
    if isinstance(name, str):
        return name or None
    if isinstance(name, dict):
        given = name.get("givenName") or name.get("firstName") or ""
        family = name.get("familyName") or name.get("lastName") or ""
        full = f"{given} {family}".strip()
        return full or None
    return None


def build_worker_index(workers: list[dict]) -> dict[str, dict]:
    """{employeeId: {worker_id, worker_type, name, status}} — employeeId is what
    Person.paycheck_code / paycheck_code_maz is expected to match."""
    index: dict[str, dict] = {}
    for worker in workers:
        employee_id = str(worker.get("employeeId") or "").strip()
        if not employee_id:
            continue
        index[employee_id] = {
            "worker_id": worker.get("workerId"),
            "worker_type": worker.get("workerType"),
            "name": _worker_display_name(worker),
            "status": worker.get("currentStatus"),
        }
    return index


def match_rows(rows: list[dict], index: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    """Match summary rows (person_id, person, code, pay_this_period) against the
    worker index. Returns (matched, unmatched) — both new lists of new dicts,
    `rows` is never mutated. Unmatched rows carry a `reason`."""
    matched: list[dict] = []
    unmatched: list[dict] = []
    for row in rows:
        code = str(row.get("code") or "").strip()
        if not code:
            unmatched = unmatched + [{**row, "reason": "no_employee_id"}]
            continue
        worker = index.get(code)
        if worker is None:
            unmatched = unmatched + [{**row, "reason": "not_found_in_paychex"}]
            continue
        if worker.get("worker_type") != CONTRACTOR_WORKER_TYPE:
            unmatched = unmatched + [{**row, "reason": f"wrong_worker_type:{worker.get('worker_type')}"}]
            continue
        matched = matched + [{
            **row,
            "worker_id": worker["worker_id"],
            "worker_name": worker.get("name"),
        }]
    return matched, unmatched


def select_pay_period(periods: list[dict], period_start: object, period_end: object) -> dict | None:
    """Pick the open Paychex pay period a batch should be staged into.

    1. Exact startDate/endDate match wins (Maz EverDriven weeks line up with Paychex).
    2. Otherwise the EARLIEST open period whose endDate is on/after the batch's
       period_start — FirstAlt weeks run Sat–Fri while Paychex runs Mon–Sun, so
       they never match exactly. This mirrors what a human (and the old browser
       bot) does: "Start payroll" on the dashboard = the next open payroll.
       Verified live 2026-09-22: batch 131 (9/5–9/11) → Paychex 9/7–9/13.
    """
    start_iso = _to_iso_date(period_start)
    end_iso = _to_iso_date(period_end)
    if not start_iso or not end_iso:
        return None
    for period in periods:
        if _to_iso_date(period.get("startDate")) == start_iso and _to_iso_date(period.get("endDate")) == end_iso:
            return period
    candidates = [
        p for p in periods
        if (_to_iso_date(p.get("endDate")) or "") >= start_iso
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda p: _to_iso_date(p.get("startDate")) or "9999-12-31")


def count_contractor_workers(workers: list[dict]) -> int:
    return sum(1 for w in workers if w.get("workerType") == CONTRACTOR_WORKER_TYPE)


def filter_contractor_components(components: list[dict]) -> list[dict]:
    """Pay components eligible for INDEPENDENT_CONTRACTOR earnings — candidates
    for PAYCHEX_API_1099_COMPONENT_ID_<CO>."""
    return [c for c in components if CONTRACTOR_WORKER_TYPE in (c.get("appliesToWorkerTypes") or [])]


def component_supports_contractor(components: list[dict], component_id: str) -> bool:
    for component in components:
        if str(component.get("componentId")) == str(component_id):
            return CONTRACTOR_WORKER_TYPE in (component.get("appliesToWorkerTypes") or [])
    return False
