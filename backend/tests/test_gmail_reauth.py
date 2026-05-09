"""
Tests for backend/routes/gmail_reauth.py

Run with:
    PYTHONPATH=. pytest backend/tests/test_gmail_reauth.py -v

Covered cases
-------------
 1. start_reauth: unknown account returns 400
 2. start_reauth: acumen (no include_drive) redirects with Gmail-only scope, state="acumen"
 3. start_reauth: maz without include_drive redirects with Gmail-only scope, state="maz"
 4. start_reauth: maz + include_drive=1 redirects with Gmail+Drive scopes, state="maz|drive"
 5. start_reauth: acumen + include_drive=1 ignored — still Gmail-only, state="acumen" (not "acumen|drive")
 6. callback: state round-trip "maz|drive" → include_drive=True, writes two Railway vars
 7. callback: state "acumen" → include_drive=False, writes only GMAIL_REFRESH_TOKEN_ACUMEN
 8. callback: state "maz" (no drive flag) → writes only GMAIL_REFRESH_TOKEN_MAZ
 9. callback: error param returns 400
10. callback: missing code returns 400
11. callback: no refresh_token in exchange response returns 500
12. callback: partial Railway failure renders warn status
"""

from __future__ import annotations

import json
import sys
import os
from unittest.mock import patch, MagicMock
import urllib.parse

import pytest

# Ensure backend package root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from fastapi.testclient import TestClient
from fastapi import FastAPI


# ---------------------------------------------------------------------------
# Minimal app fixture — mount only the reauth router, no DB needed
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    from backend.routes.gmail_reauth import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_token_exchange(refresh_token: str = "rt_test_abc123"):
    """Return a mock urlopen context manager that yields a token exchange response."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({
        "access_token": "at_test",
        "refresh_token": refresh_token,
        "token_type": "Bearer",
    }).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def _parse_redirect_params(location: str) -> dict[str, str]:
    parsed = urllib.parse.urlparse(location)
    return dict(urllib.parse.parse_qsl(parsed.query))


# ---------------------------------------------------------------------------
# start_reauth tests
# ---------------------------------------------------------------------------

class TestStartReauth:
    def test_unknown_account_returns_400(self, client):
        resp = client.get("/admin/gmail-reauth?account=unknown", follow_redirects=False)
        assert resp.status_code == 400
        assert "Unknown account" in resp.text

    def test_acumen_no_drive_gmail_only_scope(self, client):
        with patch.dict(os.environ, {"GMAIL_CLIENT_ID": "client_id_test", "GMAIL_CLIENT_SECRET": "secret_test"}):
            resp = client.get("/admin/gmail-reauth?account=acumen", follow_redirects=False)
        assert resp.status_code in (302, 307)
        params = _parse_redirect_params(resp.headers["location"])
        assert params["state"] == "acumen"
        scopes = params["scope"].split()
        assert "https://mail.google.com/" in scopes
        assert "https://www.googleapis.com/auth/drive.file" not in scopes
        assert "https://www.googleapis.com/auth/drive.metadata.readonly" not in scopes

    def test_maz_no_include_drive_gmail_only_scope(self, client):
        with patch.dict(os.environ, {"GMAIL_CLIENT_ID": "client_id_test", "GMAIL_CLIENT_SECRET": "secret_test"}):
            resp = client.get("/admin/gmail-reauth?account=maz", follow_redirects=False)
        assert resp.status_code in (302, 307)
        params = _parse_redirect_params(resp.headers["location"])
        assert params["state"] == "maz"
        scopes = params["scope"].split()
        assert "https://mail.google.com/" in scopes
        assert "https://www.googleapis.com/auth/drive.file" not in scopes

    def test_maz_include_drive_1_gmail_plus_drive_scopes(self, client):
        with patch.dict(os.environ, {"GMAIL_CLIENT_ID": "client_id_test", "GMAIL_CLIENT_SECRET": "secret_test"}):
            resp = client.get("/admin/gmail-reauth?account=maz&include_drive=1", follow_redirects=False)
        assert resp.status_code in (302, 307)
        params = _parse_redirect_params(resp.headers["location"])
        assert params["state"] == "maz|drive"
        scopes = params["scope"].split()
        assert "https://mail.google.com/" in scopes
        assert "https://www.googleapis.com/auth/drive.file" in scopes
        assert "https://www.googleapis.com/auth/drive.metadata.readonly" in scopes

    def test_acumen_include_drive_ignored(self, client):
        """include_drive=1 on acumen account must NOT add Drive scopes or change state."""
        with patch.dict(os.environ, {"GMAIL_CLIENT_ID": "client_id_test", "GMAIL_CLIENT_SECRET": "secret_test"}):
            resp = client.get("/admin/gmail-reauth?account=acumen&include_drive=1", follow_redirects=False)
        assert resp.status_code in (302, 307)
        params = _parse_redirect_params(resp.headers["location"])
        # State must not carry the drive flag for acumen
        assert params["state"] == "acumen"
        scopes = params["scope"].split()
        assert "https://www.googleapis.com/auth/drive.file" not in scopes


# ---------------------------------------------------------------------------
# callback tests
# ---------------------------------------------------------------------------

class TestReauthCallback:
    def test_error_param_returns_400(self, client):
        resp = client.get("/admin/gmail-reauth/callback?error=access_denied")
        assert resp.status_code == 400
        assert "OAuth error" in resp.text

    def test_missing_code_returns_400(self, client):
        resp = client.get("/admin/gmail-reauth/callback")
        assert resp.status_code == 400
        assert "No code received" in resp.text

    def test_no_refresh_token_in_response_returns_500(self, client):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"access_token": "at_test"}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with (
            patch.dict(os.environ, {"GMAIL_CLIENT_ID": "cid", "GMAIL_CLIENT_SECRET": "csec"}),
            patch("urllib.request.urlopen", return_value=mock_resp),
        ):
            resp = client.get("/admin/gmail-reauth/callback?code=authcode&state=acumen")
        assert resp.status_code == 500
        assert "No refresh token" in resp.text

    def test_acumen_state_writes_only_gmail_acumen_var(self, client):
        mock_resp = _fake_token_exchange("rt_acumen_token")
        updated_vars: list[str] = []

        def fake_update(name: str, value: str) -> bool:
            updated_vars.append(name)
            return True

        with (
            patch.dict(os.environ, {"GMAIL_CLIENT_ID": "cid", "GMAIL_CLIENT_SECRET": "csec"}),
            patch("urllib.request.urlopen", return_value=mock_resp),
            patch("backend.routes.gmail_reauth._update_railway_var", side_effect=fake_update),
        ):
            resp = client.get("/admin/gmail-reauth/callback?code=authcode&state=acumen")

        assert resp.status_code == 200
        assert updated_vars == ["GMAIL_REFRESH_TOKEN_ACUMEN"]
        assert "GOOGLE_DRIVE_REFRESH_TOKEN_MAZ" not in updated_vars

    def test_maz_state_no_drive_writes_only_gmail_maz_var(self, client):
        mock_resp = _fake_token_exchange("rt_maz_token")
        updated_vars: list[str] = []

        def fake_update(name: str, value: str) -> bool:
            updated_vars.append(name)
            return True

        with (
            patch.dict(os.environ, {"GMAIL_CLIENT_ID": "cid", "GMAIL_CLIENT_SECRET": "csec"}),
            patch("urllib.request.urlopen", return_value=mock_resp),
            patch("backend.routes.gmail_reauth._update_railway_var", side_effect=fake_update),
        ):
            resp = client.get("/admin/gmail-reauth/callback?code=authcode&state=maz")

        assert resp.status_code == 200
        assert updated_vars == ["GMAIL_REFRESH_TOKEN_MAZ"]
        assert "GOOGLE_DRIVE_REFRESH_TOKEN_MAZ" not in updated_vars

    def test_maz_drive_state_writes_both_vars(self, client):
        """state='maz|drive' → Option A: write same token to GMAIL_REFRESH_TOKEN_MAZ and GOOGLE_DRIVE_REFRESH_TOKEN_MAZ."""
        mock_resp = _fake_token_exchange("rt_combined_token")
        updated: dict[str, str] = {}

        def fake_update(name: str, value: str) -> bool:
            updated[name] = value
            return True

        with (
            patch.dict(os.environ, {"GMAIL_CLIENT_ID": "cid", "GMAIL_CLIENT_SECRET": "csec"}),
            patch("urllib.request.urlopen", return_value=mock_resp),
            patch("backend.routes.gmail_reauth._update_railway_var", side_effect=fake_update),
        ):
            resp = client.get("/admin/gmail-reauth/callback?code=authcode&state=maz%7Cdrive")

        assert resp.status_code == 200
        assert "GMAIL_REFRESH_TOKEN_MAZ" in updated
        assert "GOOGLE_DRIVE_REFRESH_TOKEN_MAZ" in updated
        # Both vars must receive the same token (Option A)
        assert updated["GMAIL_REFRESH_TOKEN_MAZ"] == updated["GOOGLE_DRIVE_REFRESH_TOKEN_MAZ"] == "rt_combined_token"

    def test_maz_drive_state_drive_note_in_html(self, client):
        """Success page for drive flow must mention the Drive scopes granted."""
        mock_resp = _fake_token_exchange("rt_combined")
        with (
            patch.dict(os.environ, {"GMAIL_CLIENT_ID": "cid", "GMAIL_CLIENT_SECRET": "csec"}),
            patch("urllib.request.urlopen", return_value=mock_resp),
            patch("backend.routes.gmail_reauth._update_railway_var", return_value=True),
        ):
            resp = client.get("/admin/gmail-reauth/callback?code=authcode&state=maz%7Cdrive")

        assert resp.status_code == 200
        assert "GOOGLE_DRIVE_REFRESH_TOKEN_MAZ" in resp.text
        assert "drive.file" in resp.text

    def test_partial_railway_failure_renders_warn(self, client):
        """If one Railway update fails, page renders warn class, not ok."""
        mock_resp = _fake_token_exchange("rt_token")
        call_count = {"n": 0}

        def fake_update(name: str, value: str) -> bool:
            call_count["n"] += 1
            # First call (GMAIL_REFRESH_TOKEN_MAZ) succeeds, second (GOOGLE_DRIVE) fails
            return call_count["n"] == 1

        with (
            patch.dict(os.environ, {"GMAIL_CLIENT_ID": "cid", "GMAIL_CLIENT_SECRET": "csec"}),
            patch("urllib.request.urlopen", return_value=mock_resp),
            patch("backend.routes.gmail_reauth._update_railway_var", side_effect=fake_update),
        ):
            resp = client.get("/admin/gmail-reauth/callback?code=authcode&state=maz%7Cdrive")

        assert resp.status_code == 200
        assert 'class="warn"' in resp.text
