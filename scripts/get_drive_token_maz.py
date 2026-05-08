#!/usr/bin/env python3
"""
One-time script to get a combined Gmail+Drive OAuth2 refresh token for
the noreply.mazpay@gmail.com account.

This token covers ALL three scopes:
  - https://www.googleapis.com/auth/gmail.send   (existing)
  - https://www.googleapis.com/auth/drive.file   (new — for payroll xlsx archive)
  - https://www.googleapis.com/auth/drive.metadata.readonly  (new — folder search)

The resulting refresh token goes in Railway as:
  GOOGLE_DRIVE_REFRESH_TOKEN_MAZ

This does NOT replace GMAIL_REFRESH_TOKEN_MAZ (the old Gmail-only token).
Both can coexist. The drive_archive.py service reads GOOGLE_DRIVE_REFRESH_TOKEN_MAZ.

Usage:
    pip install google-auth-oauthlib
    GMAIL_CLIENT_ID=xxx GMAIL_CLIENT_SECRET=yyy python3 scripts/get_drive_token_maz.py
"""

import os
from google_auth_oauthlib.flow import InstalledAppFlow

CLIENT_ID = os.environ.get("GMAIL_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("GMAIL_CLIENT_SECRET", "")

if not CLIENT_ID or not CLIENT_SECRET:
    print("ERROR: set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET env vars first.")
    exit(1)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
]

client_config = {
    "installed": {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}

print()
print("=" * 60)
print("  IMPORTANT: Sign in with  -->  noreply.mazpay@gmail.com")
print("=" * 60)
print()
print("A browser window will open. Sign in with noreply.mazpay@gmail.com.")
print("You will be asked to grant Gmail send AND Drive file AND Drive metadata access.")
print()
input("Press Enter to open the browser...")

flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
creds = flow.run_local_server(port=0)

print()
print("=" * 60)
print("  SUCCESS — add this env var to Railway:")
print("=" * 60)
print()
print(f"GOOGLE_DRIVE_REFRESH_TOKEN_MAZ={creds.refresh_token}")
print()
print("Railway CLI one-liner:")
print(f'railway variables set GOOGLE_DRIVE_REFRESH_TOKEN_MAZ="{creds.refresh_token}"')
print()
print("Also verify GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET are set in Railway.")
print("The existing GMAIL_REFRESH_TOKEN_MAZ (Gmail-only) is NOT replaced.")
print()
print("\n👉 Next: railway variables --set GOOGLE_DRIVE_REFRESH_TOKEN_MAZ=<the_token_above> --service zpay-v2\n")
