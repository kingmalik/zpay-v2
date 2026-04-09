#!/usr/bin/env python3
"""
Paychex Session Capture
Run this script to capture your logged-in Paychex session.
The bot will reuse your session cookies to skip login entirely.

Usage:
  python3 scripts/capture_paychex_session.py acumen
  python3 scripts/capture_paychex_session.py maz
"""
import asyncio
import sys
import os
import json
import requests
from playwright.async_api import async_playwright

RAILWAY_URL = "https://zpay-v2-production.up.railway.app"
PAYCHEX_URL = "https://myapps.paychex.com"

# The internal secret must match ZPAY_INTERNAL_SECRET env var on Railway
INTERNAL_SECRET = os.environ.get("ZPAY_INTERNAL_SECRET", "zpay-internal-2026")

async def capture_session(company: str):
    print(f"\n{'='*55}")
    print(f"  Paychex Session Capture — {company.upper()}")
    print(f"{'='*55}")
    print(f"\n  1. A Chrome window will open")
    print(f"  2. Log into Paychex Flex ({company})")
    print(f"  3. Once you see the dashboard, come back here")
    print(f"  4. The script captures your session automatically\n")
    input("  Press Enter to open Chrome...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,  # REAL browser — no bot detection
            args=['--disable-blink-features=AutomationControlled'],
        )
        context = await browser.new_context(
            user_agent=(
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/122.0.0.0 Safari/537.36'
            ),
            viewport={'width': 1280, 'height': 800},
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = await context.new_page()
        await page.goto(PAYCHEX_URL)

        print(f"\n  Waiting for you to log in...")
        print(f"  (Watching for Paychex dashboard — up to 3 minutes)\n")

        # Wait until user is past the login pages (URL no longer contains "login")
        try:
            await page.wait_for_url(
                lambda url: "login" not in url.lower() and "paychex.com" in url.lower(),
                timeout=180000
            )
        except Exception:
            print("  Timed out waiting for login. Capturing whatever cookies exist...")

        # Small extra wait for all cookies to be set
        await page.wait_for_timeout(2000)

        # Capture all cookies for paychex domains
        cookies = await context.cookies(["https://myapps.paychex.com", "https://flex.paychex.com", "https://login.flex.paychex.com", "https://oidc.flex.paychex.com"])

        await browser.close()

        if not cookies:
            print("  No cookies captured. Make sure you logged in successfully.")
            return

        print(f"\n  Captured {len(cookies)} cookies")
        print(f"  Uploading to Railway...")

        # Upload to Railway
        try:
            resp = requests.post(
                f"{RAILWAY_URL}/health/upload-session/{company}",
                json={"cookies": cookies},
                headers={"X-Internal-Secret": INTERNAL_SECRET, "Accept": "application/json"},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                print(f"\n  Session saved! ({data.get('cookie_count', len(cookies))} cookies)")
                print(f"  The bot will now skip login for {company.upper()}.\n")
            else:
                print(f"\n  Upload failed: {resp.status_code} — {resp.text[:200]}")
        except Exception as e:
            # Fallback: save to file
            path = os.path.expanduser(f"~/.zpay_session_{company}.json")
            with open(path, "w") as f:
                json.dump(cookies, f)
            print(f"\n  Could not reach Railway ({e})")
            print(f"  Session saved locally to: {path}")

def main():
    if len(sys.argv) < 2 or sys.argv[1].lower() not in ("acumen", "maz"):
        print("Usage: python3 scripts/capture_paychex_session.py acumen")
        print("       python3 scripts/capture_paychex_session.py maz")
        sys.exit(1)

    company = sys.argv[1].lower()
    asyncio.run(capture_session(company))

if __name__ == "__main__":
    main()
