#!/usr/bin/env python3
"""
Paychex Employee Data Export
Logs into Paychex Flex (real browser, handles MFA), then scrapes the
employee directory for home address, phone, email, and DOB.

Exports to /tmp/paychex_employees_{company}.json

Usage:
  python3 scripts/paychex_employee_export.py acumen
  python3 scripts/paychex_employee_export.py maz
  python3 scripts/paychex_employee_export.py both
"""
import asyncio
import sys
import os
import json
import re
import time
from playwright.async_api import async_playwright, Page, BrowserContext

PAYCHEX_URL = "https://myapps.paychex.com"
FLEX_URL = "https://flex.paychex.com"
OUTPUT_DIR = "/tmp"


def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    return digits if len(digits) >= 10 else ""


async def login_and_get_context(p, company: str) -> tuple:
    """Open a visible Chrome window, let the user log in, return (browser, context, page)."""
    browser = await p.chromium.launch(
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
    )
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 900},
    )
    await context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    page = await context.new_page()
    await page.goto(PAYCHEX_URL)

    print(f"\n  [ACTION REQUIRED] Log into Paychex Flex for {company.upper()}")
    print(f"  Complete MFA if asked, then wait for the dashboard to load.")
    print(f"  (Waiting up to 3 minutes...)\n")

    try:
        await page.wait_for_url(
            lambda url: "login" not in url.lower() and "paychex.com" in url.lower(),
            timeout=180000,
        )
    except Exception:
        print("  Timed out — continuing with whatever session exists...")

    await page.wait_for_timeout(3000)
    print("  Logged in. Starting employee data extraction...\n")
    return browser, context, page


async def navigate_to_employee_list(page: Page, company: str) -> bool:
    """Navigate to the People / Employee Directory section of Paychex Flex."""
    # Paychex Flex navigation: try multiple paths
    nav_attempts = [
        ("People & Culture nav", 'a:has-text("People"), a[href*="people"], nav a:has-text("People")'),
        ("HR tab", 'a:has-text("HR"), a[href*="hr"]'),
        ("Employees menu", 'a:has-text("Employees"), a[href*="employee"]'),
        ("Workers menu", 'a:has-text("Workers"), a[href*="workers"]'),
    ]

    for label, selector in nav_attempts:
        try:
            await page.wait_for_selector(selector, timeout=5000)
            await page.click(selector)
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(2000)
            print(f"  Clicked: {label}")
            return True
        except Exception:
            pass

    # Try direct URL patterns
    url_patterns = [
        f"{FLEX_URL}/#/workers",
        f"{FLEX_URL}/#/people",
        f"{FLEX_URL}/#/employees",
        f"{FLEX_URL}/app/hr/workers",
    ]
    for url in url_patterns:
        try:
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)
            title = await page.title()
            curr = page.url
            print(f"  Tried URL {url} → {curr}")
            if "login" not in curr.lower():
                return True
        except Exception:
            pass

    return False


async def intercept_employee_api(page: Page, context: BrowserContext, company: str) -> list:
    """
    Intercept XHR/fetch calls Paychex makes when loading the employee list.
    Captures structured employee data directly from the API responses.
    """
    captured_responses = []

    async def handle_response(response):
        url = response.url
        if not ("flex.paychex.com" in url or "api.paychex.com" in url):
            return
        if response.status != 200:
            return
        try:
            ct = response.headers.get("content-type", "")
            if "json" not in ct:
                return
            body = await response.json()
            # Look for responses that look like employee lists
            if isinstance(body, dict):
                for key in ["content", "data", "employees", "workers", "results"]:
                    items = body.get(key)
                    if isinstance(items, list) and len(items) > 0:
                        first = items[0]
                        if isinstance(first, dict) and any(
                            k in first for k in ["firstName", "lastName", "workerId", "employeeId"]
                        ):
                            print(f"  [API] Captured {len(items)} employees from {url[:80]}")
                            captured_responses.extend(items)
            elif isinstance(body, list) and len(body) > 0:
                first = body[0]
                if isinstance(first, dict) and any(
                    k in first for k in ["firstName", "lastName", "workerId", "employeeId"]
                ):
                    print(f"  [API] Captured {len(body)} employees from {url[:80]}")
                    captured_responses.extend(body)
        except Exception:
            pass

    page.on("response", handle_response)
    return captured_responses


async def extract_employees_from_ui(page: Page) -> list:
    """
    Parse employee data directly from the Paychex Flex UI.
    Falls back to DOM scraping if API intercept didn't work.
    """
    employees = []

    # Wait for any list to appear
    row_selectors = [
        'tr[class*="worker"], tr[class*="employee"]',
        '[data-testid*="worker-row"], [data-testid*="employee-row"]',
        'table tbody tr',
        '[class*="worker-list"] [class*="item"]',
        '[class*="employee-list"] [class*="item"]',
    ]

    for selector in row_selectors:
        try:
            await page.wait_for_selector(selector, timeout=5000)
            rows = await page.query_selector_all(selector)
            if rows:
                print(f"  Found {len(rows)} rows with selector: {selector}")
                for row in rows:
                    text = await row.inner_text()
                    if text.strip():
                        employees.append({"raw_text": text.strip()})
                break
        except Exception:
            pass

    return employees


async def get_employee_details_via_api(page: Page, company: str) -> list:
    """
    Use the Paychex API (intercepted auth tokens) to pull detailed
    employee data including home address.
    """
    employees = []

    # Get auth token from the page's session
    token_data = await page.evaluate("""
        () => {
            // Try various storage locations Paychex uses
            const keys = Object.keys(localStorage);
            const result = {};
            keys.forEach(k => {
                const v = localStorage.getItem(k);
                if (v && (v.includes('token') || v.includes('Bearer') || k.includes('token') || k.includes('auth'))) {
                    result[k] = v.substring(0, 200);
                }
            });
            // Also check sessionStorage
            const skeys = Object.keys(sessionStorage);
            skeys.forEach(k => {
                const v = sessionStorage.getItem(k);
                if (v && (v.includes('token') || k.includes('token') || k.includes('auth'))) {
                    result['session_' + k] = v.substring(0, 200);
                }
            });
            return result;
        }
    """)

    print(f"  Auth token keys found: {list(token_data.keys())[:10]}")

    # Get all cookies for use with requests
    cookies = await page.context.cookies()
    cookie_dict = {c["name"]: c["value"] for c in cookies}

    # Try Paychex API directly
    import aiohttp
    import urllib.request

    bearer = None
    for k, v in token_data.items():
        if "Bearer" in str(v):
            bearer = v.split("Bearer ")[-1].strip()[:500]
            break

    if bearer:
        print(f"  Found Bearer token: {bearer[:30]}...")

    # Use page.evaluate to make API calls in browser context (bypasses CORS)
    companies_resp = await page.evaluate("""
        async () => {
            try {
                const resp = await fetch('https://api.paychex.com/companies', {
                    credentials: 'include',
                    headers: {'Accept': 'application/json'}
                });
                return {status: resp.status, body: await resp.text()};
            } catch(e) {
                return {error: e.message};
            }
        }
    """)
    print(f"  /companies API response: {str(companies_resp)[:200]}")

    return employees


async def scrape_paychex_employees(company: str) -> list:
    """Main function to scrape all employee data for a company."""
    print(f"\n{'='*55}")
    print(f"  Paychex Employee Export — {company.upper()}")
    print(f"{'='*55}")

    async with async_playwright() as p:
        browser, context, page = await login_and_get_context(p, company)

        # Set up API interception
        api_responses = await intercept_employee_api(page, context, company)

        # Navigate to employee section
        nav_success = await navigate_to_employee_list(page, company)
        if not nav_success:
            print("  WARNING: Could not navigate to employee list — trying API directly")

        # Wait for page to settle and APIs to fire
        await page.wait_for_timeout(5000)

        # Try getting employee data via in-page API calls
        await get_employee_details_via_api(page, company)

        # Take a screenshot for debugging
        screenshot_path = f"/tmp/paychex_{company}_employees.png"
        await page.screenshot(path=screenshot_path)
        print(f"  Screenshot: {screenshot_path}")

        # Save page HTML
        html = await page.content()
        with open(f"/tmp/paychex_{company}_page.html", "w") as f:
            f.write(html)
        print(f"  HTML saved: /tmp/paychex_{company}_page.html")

        # Check what API calls were made
        print(f"\n  API responses captured: {len(api_responses)}")

        # If we got API data, use it
        if api_responses:
            employees = api_responses
        else:
            # Fall back to UI scraping
            employees = await extract_employees_from_ui(page)

        # Print body text to understand the page structure
        body_text = await page.evaluate("() => document.body.innerText")
        print(f"\n  Page text (first 2000 chars):\n{body_text[:2000]}")

        await browser.close()

        output_path = f"{OUTPUT_DIR}/paychex_employees_{company}.json"
        with open(output_path, "w") as f:
            json.dump(employees, f, indent=2, default=str)
        print(f"\n  Saved {len(employees)} employees to {output_path}")

        return employees


def main():
    if len(sys.argv) < 2 or sys.argv[1].lower() not in ("acumen", "maz", "both"):
        print("Usage:")
        print("  python3 scripts/paychex_employee_export.py acumen")
        print("  python3 scripts/paychex_employee_export.py maz")
        print("  python3 scripts/paychex_employee_export.py both")
        sys.exit(1)

    company = sys.argv[1].lower()

    if company == "both":
        asyncio.run(scrape_paychex_employees("maz"))
        asyncio.run(scrape_paychex_employees("acumen"))
    else:
        asyncio.run(scrape_paychex_employees(company))


if __name__ == "__main__":
    main()
