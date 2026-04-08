#!/usr/bin/env python3
"""
One-time script to get Gmail OAuth2 refresh tokens.
Run this on your Mac for each Gmail account you want to use.

Usage:
    pip install google-auth-oauthlib
    python3 scripts/get_gmail_token.py

You'll need:
  - GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET from Google Cloud Console
    (see instructions below)

Google Cloud Console setup (one-time):
  1. Go to https://console.cloud.google.com
  2. Create a new project (or select existing)
  3. Enable "Gmail API" (APIs & Services > Enable APIs)
  4. Go to APIs & Services > Credentials > Create Credentials > OAuth client ID
  5. Application type: Desktop app
  6. Download the JSON — copy client_id and client_secret from it
"""

import json

CLIENT_ID = input("Paste GMAIL_CLIENT_ID: ").strip()
CLIENT_SECRET = input("Paste GMAIL_CLIENT_SECRET: ").strip()
ACCOUNT = input("Which account? (acumen / maz): ").strip().lower()

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

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

suffix = "ACUMEN" if "acumen" in ACCOUNT else "MAZ"

print("\n" + "="*60)
print("Add these to Railway environment variables:")
print("="*60)
print(f"GMAIL_CLIENT_ID={CLIENT_ID}")
print(f"GMAIL_CLIENT_SECRET={CLIENT_SECRET}")
print(f"GMAIL_REFRESH_TOKEN_{suffix}={creds.refresh_token}")
print("="*60)
print("\nCopy and run:")
print(f'railway variables set GMAIL_CLIENT_ID="{CLIENT_ID}" GMAIL_CLIENT_SECRET="{CLIENT_SECRET}" GMAIL_REFRESH_TOKEN_{suffix}="{creds.refresh_token}"')
