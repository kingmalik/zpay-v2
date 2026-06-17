"""
Gmail OAuth2 token renewal endpoint.

GET  /admin/gmail-reauth?account=acumen              → redirects to Google OAuth consent (Gmail only)
GET  /admin/gmail-reauth?account=maz&include_drive=1 → same flow but requests Gmail + Drive scopes
GET  /admin/gmail-reauth/callback                    → exchanges code, updates Railway env var(s) automatically

include_drive=1 (maz account only):
  Requests scopes: https://mail.google.com/ + drive.file + drive.metadata.readonly
  Writes the resulting refresh token to BOTH:
    • GMAIL_REFRESH_TOKEN_MAZ   (replaces the existing Gmail token — token still has Gmail scope)
    • GOOGLE_DRIVE_REFRESH_TOKEN_MAZ (new, used by scripts/backfill_maz_drive_archive.py)
  This is Option A (single combined token, single source of truth).

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

GMAIL_SCOPE = "https://mail.google.com/"
DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
]

SCOPES_GMAIL_ONLY = " ".join([
    # Full Gmail access — needed to read Sent folder (messages.list with label filters).
    # gmail.readonly alone does NOT permit label-based queries against SENT.
    # gmail.send is a subset of this scope, so sending still works after this upgrade.
    GMAIL_SCOPE,
])

SCOPES_GMAIL_AND_DRIVE = " ".join([GMAIL_SCOPE] + DRIVE_SCOPES)
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


def _reauth_url(account: str) -> str:
    """Absolute reauth link to ship in /status responses.

    Returning a relative path here made the Vercel frontend resolve it to
    `frontend-ruddy-ten-82.vercel.app/admin/gmail-reauth?...` and 404, since
    the reauth route only exists on the Railway backend. Pin to the same
    public base used for the OAuth redirect URI so both stay consistent.
    """
    base = os.environ.get(
        "PUBLIC_BASE_URL", "https://zpay-v2-production.up.railway.app"
    ).rstrip("/")
    suffix = "&include_drive=1" if account == "maz" else ""
    return f"{base}/admin/gmail-reauth?account={account}{suffix}"


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


@router.get("/status")
def gmail_status(request: Request):
    """
    Pre-flight check: attempt creds.refresh() for each Gmail account.
    Returns JSON indicating whether each account is healthy.

    Response shape:
    {
      "accounts": [
        {"account": "acumen", "ok": true, "error": null, "scopes": [...],
         "from_email": "noreply.acumenpay@gmail.com"},
        {"account": "maz", "ok": false, "error": "invalid_grant", "scopes": [...],
         "from_email": "noreply.mazpay@gmail.com",
         "reauth_url": "/admin/gmail-reauth?account=maz&include_drive=1"}
      ]
    }
    """
    from fastapi.responses import JSONResponse
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request as GRequest

    client_id     = _client_id()
    client_secret = _client_secret()

    results = []
    for account, acct in ACCOUNTS.items():
        token_var  = acct["token_var"]
        user_var   = acct["user_var"]
        from_email = os.environ.get(user_var, acct["email"]).strip()
        refresh_token = os.environ.get(token_var, "").strip()

        entry: dict = {
            "account":    account,
            "ok":         False,
            "error":      None,
            "scopes":     [GMAIL_SCOPE],
            "from_email": from_email,
        }

        if not all([client_id, client_secret, refresh_token, from_email]):
            missing = [
                k for k, v in {
                    "GMAIL_CLIENT_ID":    client_id,
                    "GMAIL_CLIENT_SECRET": client_secret,
                    token_var:             refresh_token,
                    user_var:              from_email,
                }.items() if not v
            ]
            entry["error"] = f"Missing env vars: {', '.join(missing)}"
            entry["reauth_url"] = _reauth_url(account)
            results.append(entry)
            continue

        try:
            creds = Credentials(
                token=None,
                refresh_token=refresh_token,
                client_id=client_id,
                client_secret=client_secret,
                token_uri="https://oauth2.googleapis.com/token",
                scopes=[GMAIL_SCOPE],
            )
            creds.refresh(GRequest())
            entry["ok"] = True
            _logger.info("gmail-status: %s OK", account)
        except Exception as exc:
            err_str = str(exc)
            entry["error"] = err_str
            entry["reauth_url"] = _reauth_url(account)
            _logger.warning("gmail-status: %s FAILED — %s", account, err_str)

        results.append(entry)

    return JSONResponse({"accounts": results})


@router.get("", response_class=RedirectResponse)
def start_reauth(request: Request, account: str = "acumen", include_drive: int = 0):
    """Kick off the Google OAuth2 consent flow for the given account.

    Optional query params:
      account=acumen|maz   (default: acumen)
      include_drive=1      (default: 0) — only meaningful for account=maz.
                           When set, requests Gmail + Drive scopes and writes
                           the token to both GMAIL_REFRESH_TOKEN_MAZ and
                           GOOGLE_DRIVE_REFRESH_TOKEN_MAZ (Option A).
    """
    if account not in ACCOUNTS:
        return HTMLResponse(f"Unknown account '{account}'. Use ?account=acumen or ?account=maz", status_code=400)

    acct = ACCOUNTS[account]
    want_drive = bool(include_drive) and account == "maz"
    scopes = SCOPES_GMAIL_AND_DRIVE if want_drive else SCOPES_GMAIL_ONLY

    # Encode include_drive flag into state so the callback knows what to do.
    # Format: "<account>|drive" or "<account>"
    state = f"{account}|drive" if want_drive else account

    params = urllib.parse.urlencode({
        "client_id":     _client_id(),
        "redirect_uri":  _redirect_uri(request),
        "response_type": "code",
        "scope":         scopes,
        "access_type":   "offline",
        "prompt":        "consent",          # force new refresh token
        "login_hint":    acct["email"],
        "state":         state,
    })
    return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{params}")


@router.get("/callback", response_class=HTMLResponse)
def reauth_callback(request: Request, code: str = "", state: str = "acumen", error: str = ""):
    """Handle Google's OAuth2 callback, exchange code for tokens, update Railway.

    State format (set by start_reauth):
      "<account>"        — Gmail-only flow
      "<account>|drive"  — Gmail+Drive flow (maz only)
    """
    if error:
        return HTMLResponse(f"<h2>OAuth error: {error}</h2>", status_code=400)
    if not code:
        return HTMLResponse("<h2>No code received from Google.</h2>", status_code=400)

    # Parse state: "maz|drive" → account="maz", include_drive=True
    state_parts = state.split("|", 1)
    account = state_parts[0] if state_parts[0] in ACCOUNTS else "acumen"
    include_drive = len(state_parts) > 1 and state_parts[1] == "drive"
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

    # Determine which Railway vars to update.
    # Option A: when include_drive, write the combined token to BOTH the Gmail var
    # AND GOOGLE_DRIVE_REFRESH_TOKEN_MAZ so both email and Drive code share one token.
    vars_to_update = {acct["token_var"]: refresh_token}
    if include_drive and account == "maz":
        vars_to_update["GOOGLE_DRIVE_REFRESH_TOKEN_MAZ"] = refresh_token

    results: dict[str, bool] = {}
    for var_name, var_value in vars_to_update.items():
        results[var_name] = _update_railway_var(var_name, var_value)

    all_ok = all(results.values())
    some_ok = any(results.values())

    if all_ok:
        status_class = "ok"
        status_msg = "Railway env var(s) updated automatically!"
    elif some_ok:
        failed = [k for k, v in results.items() if not v]
        status_class = "warn"
        status_msg = f"Partial update — failed vars: {', '.join(failed)}. Copy the token below for those."
    else:
        status_class = "warn"
        status_msg = "Could not update Railway automatically — copy the token below manually."

    vars_html = "".join(
        f"<li><code>{var}</code> — {'updated' if ok else 'FAILED'}</li>"
        for var, ok in results.items()
    )

    drive_note = ""
    if include_drive:
        drive_note = (
            "<p><strong>Scopes granted:</strong> gmail (full) + drive.file + drive.metadata.readonly<br>"
            "Token written to both <code>GMAIL_REFRESH_TOKEN_MAZ</code> and "
            "<code>GOOGLE_DRIVE_REFRESH_TOKEN_MAZ</code> (Option A — shared token).</p>"
        )

    return HTMLResponse(f"""
<!DOCTYPE html><html><head><title>Gmail Token Renewed</title>
<style>body{{font-family:system-ui;max-width:700px;margin:40px auto;padding:20px;}}
pre{{background:#f0f0f0;padding:16px;border-radius:8px;word-break:break-all;white-space:pre-wrap;}}
.ok{{color:green;}} .warn{{color:orange;}}</style></head><body>
<h2>Gmail Token Renewed — {acct['email']}</h2>
<p class="{status_class}">{status_msg}</p>
<p><strong>Account:</strong> {account} ({acct['email']})</p>
<strong>Env vars updated:</strong><ul>{vars_html}</ul>
{drive_note}
<p><strong>New refresh token:</strong></p>
<pre>{refresh_token}</pre>
<p><a href="/admin/gmail-reauth?account={'maz' if account == 'acumen' else 'acumen'}">
  → Renew the other account ({'maz' if account == 'acumen' else 'acumen'}) too
</a></p>
</body></html>
""")
