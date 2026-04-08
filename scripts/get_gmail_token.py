#!/usr/bin/env python3
"""
One-time script to get Gmail OAuth2 refresh tokens for Z-Pay email sending.
Run this on your Mac for each Gmail account (acumen or maz).

Usage:
    pip install google-auth-oauthlib
    python3 scripts/get_gmail_token.py

This will open a browser window — sign in with the correct Gmail account
(the script will tell you which one).
"""

import os
from google_auth_oauthlib.flow import InstalledAppFlow

# ---------------------------------------------------------------------------
# Default OAuth client credentials (Z-Pay Google Cloud project)
# ---------------------------------------------------------------------------
DEFAULT_CLIENT_ID = os.environ.get("GMAIL_CLIENT_ID", "")
DEFAULT_CLIENT_SECRET = os.environ.get("GMAIL_CLIENT_SECRET", "")

# ---------------------------------------------------------------------------
# Gmail accounts
# ---------------------------------------------------------------------------
ACCOUNTS = {
    "acumen": {
        "email": "noreply.acumenpay@gmail.com",
        "env_user": "GMAIL_USER_ACUMEN",
        "env_token": "GMAIL_REFRESH_TOKEN_ACUMEN",
    },
    "maz": {
        "email": "noreply.mazpay@gmail.com",
        "env_user": "GMAIL_USER_MAZ",
        "env_token": "GMAIL_REFRESH_TOKEN_MAZ",
    },
}

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

# ---------------------------------------------------------------------------
# Step 1 — pick the account
# ---------------------------------------------------------------------------
print()
print("=" * 60)
print("  Z-Pay Gmail OAuth Token Generator")
print("=" * 60)
print()
print("Available accounts:")
print("  acumen  ->  noreply.acumenpay@gmail.com")
print("  maz     ->  noreply.mazpay@gmail.com")
print()

ACCOUNT = input("Which account? (acumen / maz): ").strip().lower()

if ACCOUNT not in ACCOUNTS:
    print(f"\nError: unknown account '{ACCOUNT}'. Must be 'acumen' or 'maz'.")
    exit(1)

acct = ACCOUNTS[ACCOUNT]

# ---------------------------------------------------------------------------
# Step 2 — client credentials (just press Enter to use defaults)
# ---------------------------------------------------------------------------
print()
raw_id = input(f"Client ID [{DEFAULT_CLIENT_ID[:20]}...]: ").strip()
CLIENT_ID = raw_id if raw_id else DEFAULT_CLIENT_ID

raw_secret = input(f"Client Secret [{DEFAULT_CLIENT_SECRET[:12]}...]: ").strip()
CLIENT_SECRET = raw_secret if raw_secret else DEFAULT_CLIENT_SECRET

# ---------------------------------------------------------------------------
# Step 3 — run the OAuth flow
# ---------------------------------------------------------------------------
print()
print("=" * 60)
print(f"  IMPORTANT: Sign in with  -->  {acct['email']}")
print("=" * 60)
print()
print("A browser window will open. Make sure you sign in with the")
print(f"account listed above ({acct['email']}).")
print("If you're already signed into a different Google account,")
print("use the account-switcher or an incognito window.")
print()
input("Press Enter to open the browser...")

client_config = {
    "installed": {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}

flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
creds = flow.run_local_server(port=0)

# ---------------------------------------------------------------------------
# Step 4 — print the env vars to set
# ---------------------------------------------------------------------------
print()
print("=" * 60)
print("  SUCCESS — add these env vars to Railway:")
print("=" * 60)
print()
print(f"GMAIL_CLIENT_ID={CLIENT_ID}")
print(f"GMAIL_CLIENT_SECRET={CLIENT_SECRET}")
print(f"{acct['env_user']}={acct['email']}")
print(f"{acct['env_token']}={creds.refresh_token}")
print()
print("=" * 60)
print("  Copy-paste command for Railway CLI:")
print("=" * 60)
print()
print(
    f'railway variables set'
    f' GMAIL_CLIENT_ID="{CLIENT_ID}"'
    f' GMAIL_CLIENT_SECRET="{CLIENT_SECRET}"'
    f' {acct["env_user"]}="{acct["email"]}"'
    f' {acct["env_token"]}="{creds.refresh_token}"'
)
print()
