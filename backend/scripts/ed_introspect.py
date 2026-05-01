"""
One-shot ED GraphQL schema introspection.

Usage:
    python -m backend.scripts.ed_introspect

Writes full schema to data/ed_schema_dump.json (relative to repo root).
On 400/403 or disabled introspection, logs clearly and exits 0.

This script is informational — it does NOT modify any service code.
If timestamp fields are found, update _RUNS_QUERY in everdriven_service.py
manually per the Phase 4 spec.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Module-level imports from service — allows tests to patch these directly
from backend.services.everdriven_service import _get_token, _API_URL

# ---------------------------------------------------------------------------
# Resolve repo root (two levels up from this file: backend/scripts → root)
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_OUT_FILE = _REPO_ROOT / "data" / "ed_schema_dump.json"

# ---------------------------------------------------------------------------
# Introspection query — standard GraphQL introspection
# ---------------------------------------------------------------------------
_INTROSPECTION_QUERY = """
query IntrospectionQuery {
  __schema {
    types {
      name
      kind
      fields {
        name
        type {
          kind
          name
          ofType {
            kind
            name
          }
        }
      }
    }
  }
}
"""

# Fields we care about on Trip/Run/Job-like types
_TARGET_FIELDS = {
    "acceptedAt", "arrivedAt", "pickedUpAt", "completedAt",
    "startedAt", "lastUpdatedAt", "statusHistory", "events",
    "transitions", "timestamps",
}

# Type names that likely carry timestamp or event fields
_TRIP_TYPE_KEYWORDS = {"run", "trip", "job", "ride", "dispatch"}


def _log(msg: str) -> None:
    print(f"[ed_introspect] {msg}", flush=True)


def run_introspection() -> None:
    _log("Acquiring ED access token...")
    try:
        token = _get_token()
    except Exception as exc:
        _log(f"FATAL: Token acquisition failed: {exc}")
        _log(
            "Ensure EVERDRIVEN_USERNAME and EVERDRIVEN_PASSWORD are set, "
            "or a valid cached token exists at data/out/.everdriven_token.json"
        )
        sys.exit(1)

    _log(f"Token acquired. Sending introspection query to {_API_URL} ...")

    payload = json.dumps({"query": _INTROSPECTION_QUERY}).encode()
    req = urllib.request.Request(
        _API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode()
            status = resp.status
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read().decode() if exc.fp else ""
        if status in (400, 403):
            _log(
                f"HTTP {status} — introspection likely disabled in prod "
                f"(this is expected; Phase 2 polling remains the fallback). "
                f"Response snippet: {raw[:300]}"
            )
            _write_note(
                f"Introspection returned HTTP {status}. "
                "No native timestamp fields available from ED GraphQL. "
                "Phase 2 polling-based inference is the source of truth."
            )
            sys.exit(0)
        _log(f"HTTP {exc.code} — unexpected error. Body: {raw[:300]}")
        sys.exit(1)
    except Exception as exc:
        _log(f"Request failed: {exc}")
        sys.exit(1)

    _log(f"HTTP {status} — response received ({len(raw)} bytes)")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        _log(f"Could not parse JSON response: {exc}. Raw: {raw[:300]}")
        _write_note(
            "Introspection returned non-JSON response. "
            "ED endpoint may not support introspection. "
            "Phase 2 polling-based inference is the source of truth."
        )
        sys.exit(0)

    # Check for GraphQL-level introspection-disabled error
    errors = data.get("errors") or []
    if errors:
        messages = [e.get("message", "") for e in errors]
        _log(f"GraphQL errors: {messages}")
        introspection_blocked = any(
            "introspection" in m.lower() or "not allowed" in m.lower()
            for m in messages
        )
        if introspection_blocked:
            _log(
                "Introspection is explicitly disabled on this endpoint. "
                "Phase 2 polling-based inference is the source of truth."
            )
            _write_note(
                f"Introspection disabled by server. GraphQL errors: {messages}. "
                "Phase 2 polling-based inference is the source of truth."
            )
        else:
            _log("Unexpected GraphQL errors — writing raw response for inspection.")
            _write_dump(data)
        sys.exit(0)

    schema = (data.get("data") or {}).get("__schema")
    if not schema:
        _log("Response has no __schema field — introspection may not be supported.")
        _write_note(
            "Response contained no __schema. "
            "Phase 2 polling-based inference is the source of truth."
        )
        sys.exit(0)

    # Write full dump
    _write_dump(data)
    types = schema.get("types") or []
    _log(f"Schema dump written. Total types: {len(types)}")

    # Scan for relevant types and fields
    _log("\n--- Scanning for timestamp/event fields on Trip/Run/Job types ---")
    hits: dict[str, list[str]] = {}  # type_name -> list of matching field names

    for t in types:
        type_name: str = (t.get("name") or "").lower()
        if not any(kw in type_name for kw in _TRIP_TYPE_KEYWORDS):
            continue
        fields = t.get("fields") or []
        if not fields:
            continue
        matching = [
            f["name"] for f in fields
            if f.get("name") in _TARGET_FIELDS
        ]
        if matching:
            hits[t["name"]] = matching

    if hits:
        _log("TIMESTAMP FIELDS FOUND — extend _RUNS_QUERY in everdriven_service.py:")
        for type_name, fields in hits.items():
            _log(f"  {type_name}: {fields}")
        _log(
            "\nAction required: add these fields to _RUNS_QUERY and update "
            "_normalise_run() + trip_monitor.py to prefer them over poll-inferred timestamps."
        )
    else:
        _log(
            "No native timestamp/event fields found on Trip/Run/Job types. "
            "Phase 2 polling-based inference is the source of truth. No _RUNS_QUERY changes needed."
        )
        # List all trip/run/job type names and their fields for the record
        for t in types:
            type_name = (t.get("name") or "").lower()
            if any(kw in type_name for kw in _TRIP_TYPE_KEYWORDS):
                fields = [f["name"] for f in (t.get("fields") or [])]
                _log(f"  Type '{t['name']}' fields: {fields}")

    _log(f"\nFull schema written to: {_OUT_FILE}")


def _write_dump(data: dict) -> None:
    _OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _OUT_FILE.write_text(json.dumps(data, indent=2))


def _write_note(message: str) -> None:
    note_file = _REPO_ROOT / "data" / "ed_schema_dump_NOTE.md"
    note_file.parent.mkdir(parents=True, exist_ok=True)
    note_file.write_text(
        f"# ED GraphQL Introspection Result\n\n{message}\n\n"
        "_Generated by `backend/scripts/ed_introspect.py`_\n"
    )
    _log(f"Note written to {note_file}")


if __name__ == "__main__":
    run_introspection()
