"""
Gmail OAuth2 token renewal endpoint.

GET  /admin/gmail-reauth?account=acumen   → redirects to Google OAuth consent
GET  /admin/gmail-reauth/callback          → exchanges code, updates Railway env var automatically

Usage: navigate to /admin/gmail-reauth?account=acumen (or maz) while logged in as admin.
After signing in with the Gmail account, the new refresh token is saved to Railway automatically.
"""

import os
import json
import urllib.parse
import urllib.request
import logging

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, HTMLResponse

router = APIRouter(prefix="/admin/gmail-reauth", tags=["admin"])
_logger = logging.getLogger("zpay.gmail_reauth")

SCOPES = "https://www.googleapis.com/auth/gmail.send"
TOKEN_URI = "https://oauth2.googleapis.com/token"

# company → (user env var, refresh token env var)
ACCOUNTS = {
    "acumen": {
        "email": "noreply.acumenpay@gmail.com",
        "user_var": "GMAIL_USER_ACUMEN",
        "token_var": "GMAIL_REFRESH_TOKEN_ACUMEN",
    },
    "maz": {
        "email": "noreply.mazpay@gmail.com",
        "user_var": "GMAIL_USER_MAZ",
        "token_var": "GMAIL_REFRESH_TOKEN_MAZ",
    },
}

# Railway project/service/env IDs (hardcoded — these don't change)
RAILWAY_PROJECT_ID  = "0022b942-75cc-44b9-be12-fbd7e8ce3961"
RAILWAY_SERVICE_ID  = "4933bd01-7778-4e04-874e-81ce31e985eb"
RAILWAY_ENV_ID      = "5c50192f-142f-41f8-8b9e-507fedebbea2"
RAILWAY_API_TOKEN   = os.environ.get("RAILWAY_API_TOKEN", "")


def _client_id() -> str:
    return os.environ.get("GMAIL_CLIENT_ID", "").strip()


def _client_secret() -> str:
    return os.environ.get("GMAIL_CLIENT_SECRET", "").strip()


def _redirect_uri(request: Request) -> str:
    # Hardcoded to the public Railway URL — request.base_url resolves to an
    # internal host behind the proxy, which Google rejects as a mismatch.
    base = os.environ.get("PUBLIC_BASE_URL", "https://zpay-v2-production.up.railway.app").rstrip("/")
    return f"{base}/admin/gmail-reauth/callback"


def _update_railway_var(name: str, value: str) -> bool:
    """Update a single Railway environment variable via GraphQL API."""
    token = RAILWAY_API_TOKEN
    if not token:
        _logger.warning("RAILWAY_API_TOKEN not set — cannot auto-update Railway vars")
        return False

    mutation = """
    mutation UpsertVariables($input: VariableCollectionUpsertInput!) {
      variableCollectionUpsert(input: $input)
    }
    """
    payload = json.dumps({
        "query": mutation,
        "variables": {
            "input": {
                "projectId":     RAILWAY_PROJECT_ID,
                "serviceId":     RAILWAY_SERVICE_ID,
                "environmentId": RAILWAY_ENV_ID,
                "variables":     {name: value},
            }
        }
    }).encode()

    req = urllib.request.Request(
        "https://backboard.railway.com/graphql/v2",
        data=payload,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            if "errors" in result:
                _logger.error("Railway update error: %s", result["errors"])
                return False
            return True
    except Exception as exc:
        _logger.error("Railway update failed: %s", exc)
        return False


@router.get("", response_class=RedirectResponse)
def start_reauth(request: Request, account: str = "acumen"):
    """Kick off the Google OAuth2 consent flow for the given account."""
    if account not in ACCOUNTS:
        return HTMLResponse(f"Unknown account '{account}'. Use ?account=acumen or ?account=maz", status_code=400)

    acct = ACCOUNTS[account]
    params = urllib.parse.urlencode({
        "client_id":     _client_id(),
        "redirect_uri":  _redirect_uri(request),
        "response_type": "code",
        "scope":         SCOPES,
        "access_type":   "offline",
        "prompt":        "consent",          # force new refresh token
        "login_hint":    acct["email"],
        "state":         account,
    })
    return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{params}")


@router.get("/callback", response_class=HTMLResponse)
def reauth_callback(request: Request, code: str = "", state: str = "acumen", error: str = ""):
    """Handle Google's OAuth2 callback, exchange code for tokens, update Railway."""
    if error:
        return HTMLResponse(f"<h2>OAuth error: {error}</h2>", status_code=400)
    if not code:
        return HTMLResponse("<h2>No code received from Google.</h2>", status_code=400)

    account = state if state in ACCOUNTS else "acumen"
    acct = ACCOUNTS[account]

    # Exchange auth code for tokens
    token_data = urllib.parse.urlencode({
        "code":          code,
        "client_id":     _client_id(),
        "client_secret": _client_secret(),
        "redirect_uri":  _redirect_uri(request),
        "grant_type":    "authorization_code",
    }).encode()

    req = urllib.request.Request(TOKEN_URI, data=token_data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            tokens = json.loads(resp.read())
    except Exception as exc:
        return HTMLResponse(f"<h2>Token exchange failed: {exc}</h2>", status_code=500)

    refresh_token = tokens.get("refresh_token", "")
    if not refresh_token:
        return HTMLResponse(
            f"<h2>No refresh token returned.</h2>"
            f"<p>Google only returns a refresh token on first authorization or when prompted=consent. "
            f"Response: {tokens}</p>",
            status_code=500,
        )

    # Auto-update Railway
    railway_updated = _update_railway_var(acct["token_var"], refresh_token)

    status_msg = (
        "✅ Railway env var updated automatically!"
        if railway_updated
        else "⚠️ Could not update Railway automatically — copy the token below manually."
    )

    return HTMLResponse(f"""
<!DOCTYPE html><html><head><title>Gmail Token Renewed</title>
<style>body{{font-family:system-ui;max-width:700px;margin:40px auto;padding:20px;}}
pre{{background:#f0f0f0;padding:16px;border-radius:8px;word-break:break-all;white-space:pre-wrap;}}
.ok{{color:green;}} .warn{{color:orange;}}</style></head><body>
<h2>Gmail Token Renewed — {acct['email']}</h2>
<p class="{'ok' if railway_updated else 'warn'}">{status_msg}</p>
<p><strong>Account:</strong> {account} ({acct['email']})</p>
<p><strong>Env var:</strong> <code>{acct['token_var']}</code></p>
<p><strong>New refresh token:</strong></p>
<pre>{refresh_token}</pre>
<p><a href="/admin/gmail-reauth?account={'maz' if account == 'acumen' else 'acumen'}">
  → Renew the other account ({'maz' if account == 'acumen' else 'acumen'}) too
</a></p>
</body></html>
""")
