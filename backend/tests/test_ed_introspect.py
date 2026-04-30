"""
Tests for backend/scripts/ed_introspect.py

Covers:
    - Successful introspection response with timestamp fields present
    - Successful introspection response with no timestamp fields
    - HTTP 400/403 (introspection disabled)
    - GraphQL-level introspection-disabled error
    - Non-JSON response
    - Token acquisition failure (missing credentials)

Run with:
    PYTHONPATH=. pytest backend/tests/test_ed_introspect.py -v
"""

from __future__ import annotations

import json
import sys
import urllib.error
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers to build mock introspection responses
# ---------------------------------------------------------------------------

def _make_schema_response(types: list[dict]) -> dict:
    return {"data": {"__schema": {"types": types}}}


def _make_run_type(fields: list[str]) -> dict:
    return {
        "name": "RunType",
        "kind": "OBJECT",
        "fields": [{"name": f, "type": {"kind": "SCALAR", "name": "String", "ofType": None}} for f in fields],
    }


def _make_trip_type(fields: list[str]) -> dict:
    return {
        "name": "TripInfo",
        "kind": "OBJECT",
        "fields": [{"name": f, "type": {"kind": "SCALAR", "name": "DateTime", "ofType": None}} for f in fields],
    }


def _make_unrelated_type() -> dict:
    return {
        "name": "UserType",
        "kind": "OBJECT",
        "fields": [{"name": "email", "type": {"kind": "SCALAR", "name": "String", "ofType": None}}],
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_data_dir(tmp_path: Path, monkeypatch):
    """
    Redirect _OUT_FILE and note path inside the script module to tmp_path
    so tests don't write into the real data/ directory.
    """
    import importlib
    import backend.scripts.ed_introspect as mod
    monkeypatch.setattr(mod, "_OUT_FILE", tmp_path / "ed_schema_dump.json")
    # Also patch the _write_note helper to use tmp_path
    original_write_note = mod._write_note

    def _patched_write_note(message: str) -> None:
        note = tmp_path / "ed_schema_dump_NOTE.md"
        note.write_text(f"# ED GraphQL Introspection Result\n\n{message}\n")
        mod._log(f"Note written to {note}")

    monkeypatch.setattr(mod, "_write_note", _patched_write_note)
    return tmp_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestIntrospectionWithTimestampFields:
    """Introspection succeeds and Run/Trip types expose timestamp fields."""

    def test_hits_found_on_run_type(self, tmp_data_dir, capsys):
        schema = _make_schema_response([
            _make_run_type(["keyValue", "runState", "acceptedAt", "arrivedAt", "completedAt"]),
            _make_unrelated_type(),
        ])
        raw_bytes = json.dumps(schema).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = raw_bytes
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with (
            patch("backend.scripts.ed_introspect._get_token", return_value="tok"),
            patch("backend.scripts.ed_introspect._API_URL", "https://fake-ed-api/Graphql"),
            patch("urllib.request.urlopen", return_value=mock_resp),
        ):
            from backend.scripts import ed_introspect
            ed_introspect.run_introspection()

        out = capsys.readouterr().out
        assert "TIMESTAMP FIELDS FOUND" in out
        assert "acceptedAt" in out
        assert "arrivedAt" in out
        assert "completedAt" in out
        # Dump file written
        dump_path = tmp_data_dir / "ed_schema_dump.json"
        assert dump_path.exists()
        dumped = json.loads(dump_path.read_text())
        assert dumped["data"]["__schema"]["types"]

    def test_hits_found_on_trip_type(self, tmp_data_dir, capsys):
        schema = _make_schema_response([
            _make_trip_type(["tripState", "startedAt", "lastUpdatedAt", "events"]),
        ])
        raw_bytes = json.dumps(schema).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = raw_bytes
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with (
            patch("backend.scripts.ed_introspect._get_token", return_value="tok"),
            patch("backend.scripts.ed_introspect._API_URL", "https://fake-ed-api/Graphql"),
            patch("urllib.request.urlopen", return_value=mock_resp),
        ):
            from backend.scripts import ed_introspect
            ed_introspect.run_introspection()

        out = capsys.readouterr().out
        assert "TIMESTAMP FIELDS FOUND" in out
        assert "startedAt" in out or "lastUpdatedAt" in out or "events" in out


class TestIntrospectionNoTimestampFields:
    """Introspection succeeds but no relevant timestamp fields are exposed."""

    def test_no_hits_reported(self, tmp_data_dir, capsys):
        schema = _make_schema_response([
            _make_run_type(["keyValue", "runState", "miles"]),
            _make_unrelated_type(),
        ])
        raw_bytes = json.dumps(schema).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = raw_bytes
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with (
            patch("backend.scripts.ed_introspect._get_token", return_value="tok"),
            patch("backend.scripts.ed_introspect._API_URL", "https://fake-ed-api/Graphql"),
            patch("urllib.request.urlopen", return_value=mock_resp),
        ):
            from backend.scripts import ed_introspect
            ed_introspect.run_introspection()

        out = capsys.readouterr().out
        assert "No native timestamp/event fields found" in out
        assert "Phase 2 polling-based inference is the source of truth" in out
        # Dump still written — useful reference
        assert (tmp_data_dir / "ed_schema_dump.json").exists()


class TestIntrospectionDisabled:
    """HTTP 400 or 403 from the endpoint."""

    @pytest.mark.parametrize("http_status", [400, 403])
    def test_http_error_exits_cleanly(self, http_status, tmp_data_dir, capsys, monkeypatch):
        error_body = b'{"errors":[{"message":"Introspection not allowed"}]}'
        http_err = urllib.error.HTTPError(
            url="https://fake-ed-api/Graphql",
            code=http_status,
            msg="Forbidden",
            hdrs={},
            fp=BytesIO(error_body),
        )

        with (
            patch("backend.scripts.ed_introspect._get_token", return_value="tok"),
            patch("backend.scripts.ed_introspect._API_URL", "https://fake-ed-api/Graphql"),
            patch("urllib.request.urlopen", side_effect=http_err),
            pytest.raises(SystemExit) as exc_info,
        ):
            from backend.scripts import ed_introspect
            ed_introspect.run_introspection()

        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert str(http_status) in out
        assert "Phase 2 polling" in out or "introspection likely disabled" in out.lower()

    def test_graphql_level_disabled(self, tmp_data_dir, capsys):
        schema = {"errors": [{"message": "Introspection is not allowed"}], "data": None}
        raw_bytes = json.dumps(schema).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = raw_bytes
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with (
            patch("backend.scripts.ed_introspect._get_token", return_value="tok"),
            patch("backend.scripts.ed_introspect._API_URL", "https://fake-ed-api/Graphql"),
            patch("urllib.request.urlopen", return_value=mock_resp),
            pytest.raises(SystemExit) as exc_info,
        ):
            from backend.scripts import ed_introspect
            ed_introspect.run_introspection()

        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "disabled" in out.lower() or "introspection" in out.lower()


class TestIntrospectionNonJson:
    """Endpoint returns non-JSON (e.g. HTML error page)."""

    def test_non_json_exits_cleanly(self, tmp_data_dir, capsys):
        raw_bytes = b"<html><body>Service Unavailable</body></html>"

        mock_resp = MagicMock()
        mock_resp.read.return_value = raw_bytes
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with (
            patch("backend.scripts.ed_introspect._get_token", return_value="tok"),
            patch("backend.scripts.ed_introspect._API_URL", "https://fake-ed-api/Graphql"),
            patch("urllib.request.urlopen", return_value=mock_resp),
            pytest.raises(SystemExit) as exc_info,
        ):
            from backend.scripts import ed_introspect
            ed_introspect.run_introspection()

        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "non-JSON" in out or "Could not parse" in out


class TestTokenAcquisitionFailure:
    """Token acquisition fails (missing credentials)."""

    def test_token_failure_exits_nonzero(self, tmp_data_dir, capsys):
        from backend.services.everdriven_service import EverDrivenAuthError

        with (
            patch(
                "backend.scripts.ed_introspect._get_token",
                side_effect=EverDrivenAuthError("No credentials"),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            from backend.scripts import ed_introspect
            ed_introspect.run_introspection()

        assert exc_info.value.code == 1
        out = capsys.readouterr().out
        assert "FATAL" in out
