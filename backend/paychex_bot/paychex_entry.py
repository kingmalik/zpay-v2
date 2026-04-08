# NOTE: Paychex selectors may need updating — use browser devtools to verify

import asyncio
import os
from typing import Callable
from playwright.async_api import async_playwright, Page, BrowserContext

PAYCHEX_URL = "https://myapps.paychex.com"


async def run_paychex_entry(
    company: str,           # "acumen" or "maz"
    username: str,
    password: str,
    drivers: list[dict],    # [{"worker_id": str, "name": str, "amount": float}]
    on_status: Callable[[dict], None],  # callback for progress updates
) -> None:
    """
    Automates Paychex Flex payroll entry for 1099-NEC workers.

    Steps:
      1. Launch browser and log in to myapps.paychex.com
      2. Handle MFA if required
      3. Navigate to the payroll entry / pay grid
      4. For each driver, find their row and fill in the 1099-NEC amount
      5. Never submit — leave entries in draft for manual review and submission
    """

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            slow_mo=150,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage',
            ],
        )
        context: BrowserContext = await browser.new_context(
            user_agent=(
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/122.0.0.0 Safari/537.36'
            ),
            viewport={'width': 1280, 'height': 800},
            locale='en-US',
        )
        # Hide webdriver fingerprint from Paychex bot detection
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page: Page = await context.new_page()

        try:
            # ----------------------------------------------------------------
            # STEP 1: Navigate to Paychex Flex login
            # ----------------------------------------------------------------
            on_status({"status": "running", "message": "Navigating to Paychex Flex..."})
            await page.goto(PAYCHEX_URL, wait_until="domcontentloaded")

            # ----------------------------------------------------------------
            # STEP 2: Enter username
            # Paychex uses a two-step login: username first, then password
            # ----------------------------------------------------------------
            on_status({"status": "running", "message": "Entering username..."})

            # Confirmed selectors from live Paychex Flex page inspection
            await page.wait_for_selector('#login-username', timeout=15000)
            await page.fill('#login-username', username)
            await page.click('#login-button')  # "Continue" button

            on_status({"status": "running", "message": "Waiting for password field..."})

            # ----------------------------------------------------------------
            # STEP 3: Enter password (same SPA page, password field appears)
            # ----------------------------------------------------------------
            await page.wait_for_selector('#login-password', timeout=15000)
            on_status({"status": "running", "message": "Entering password..."})
            await page.fill('#login-password', password)
            await page.click('#login-button')  # same button ID, now says "Log in"

            on_status({"status": "running", "message": "Sign-in submitted, checking for MFA..."})

            # ----------------------------------------------------------------
            # STEP 4: Handle MFA / OTP prompt
            # Paychex OTP flow: delivery method selection → OTP code entry
            # ----------------------------------------------------------------
            try:
                # Step 4a: OTP delivery method (text vs call)
                await page.wait_for_selector('#otp-delivery-method-next-button', timeout=8000)
                on_status({"status": "mfa_required", "message": "MFA required — selecting text delivery..."})
                # Select text delivery and request the code
                try:
                    await page.click('#otp-text')  # text message radio
                except Exception:
                    pass
                await page.click('#otp-delivery-method-next-button')

                # Step 4b: Wait for OTP code input to appear
                await page.wait_for_selector('#one-time-password', timeout=15000)
                on_status({
                    "status": "mfa_required",
                    "message": "MFA code sent to your phone — enter it in Z-Pay to continue"
                })
                # Wait up to 120s for user to complete MFA
                await page.wait_for_selector('[id*="home"], [class*="dashboard"], nav[class*="nav"]', timeout=120000)
            except Exception:
                pass  # No MFA prompt or already past it — proceed to dashboard check

            # ----------------------------------------------------------------
            # STEP 5: Verify login succeeded
            # Wait for the URL to leave the login domain, or for any app shell element.
            # ----------------------------------------------------------------
            try:
                # Wait for network to settle after sign-in click
                await page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass  # proceed regardless — some SPAs never go fully idle

            current_url = page.url
            current_title = await page.title()

            # If still on the login/auth page, login failed
            login_indicators = ["myapps.paychex.com", "login", "signin", "auth"]
            still_on_login = any(ind in current_url.lower() for ind in login_indicators)

            if still_on_login:
                # Try one more selector check in case it's a post-login interstitial
                try:
                    post_login_selector = (
                        '[class*="dashboard"], [class*="home"], '
                        'a[href*="payroll"], [data-testid*="nav"]'
                    )
                    await page.wait_for_selector(post_login_selector, timeout=5000)
                except Exception:
                    raise Exception(
                        f"Login failed — still on login page after sign-in. "
                        f"URL: {current_url} | Title: {current_title} | "
                        f"Possible causes: wrong password, MFA required, or Paychex blocked the login."
                    )

            on_status({"status": "running", "message": "Login successful. Navigating to payroll entry..."})

            # ----------------------------------------------------------------
            # STEP 6: Navigate to Payroll section
            # Paychex Flex keeps payroll under a "Payroll" nav item.
            # We try clicking it in the nav, then look for "Pay Entry" or
            # similar sub-items.
            # ----------------------------------------------------------------

            # Try clicking the Payroll nav link
            payroll_nav_selector = (
                'a:has-text("Payroll"), '
                'button:has-text("Payroll"), '
                '[aria-label="Payroll"], '
                'li:has-text("Payroll")'
            )
            try:
                await page.click(payroll_nav_selector, timeout=10000)
                await page.wait_for_load_state("domcontentloaded")
            except Exception:
                # Fallback: navigate directly to a known payroll URL pattern
                on_status({"status": "running", "message": "Trying direct payroll URL..."})
                await page.goto(f"{PAYCHEX_URL}/payroll", wait_until="domcontentloaded")

            # Look for the "Pay Entry" or "Payroll Entry" sub-item
            # Paychex Flex typically labels this as "Pay Entry" in the sidebar
            pay_entry_selector = (
                'a:has-text("Pay Entry"), '
                'a:has-text("Payroll Entry"), '
                'a:has-text("Enter Pay"), '
                'a[href*="payentry"], '
                'a[href*="pay-entry"], '
                'li:has-text("Pay Entry")'
            )
            try:
                await page.wait_for_selector(pay_entry_selector, timeout=10000)
                await page.click(pay_entry_selector)
                await page.wait_for_load_state("domcontentloaded")
            except Exception:
                # Fallback: try navigating directly to the payentry URL
                on_status({"status": "running", "message": "Trying direct pay entry URL..."})
                await page.goto(f"{PAYCHEX_URL}/payroll/payentry", wait_until="domcontentloaded")

            on_status({"status": "running", "message": "Reached payroll entry. Starting driver entries..."})

            # ----------------------------------------------------------------
            # STEP 7: Select the correct company if Paychex shows multiple
            # Paychex sometimes shows a company picker when an account has
            # multiple companies (e.g. Acumen + Maz Services).
            # ----------------------------------------------------------------
            company_map = {
                "acumen": "Acumen",
                "maz": "Maz Services",
            }
            company_display = company_map.get(company.lower(), company)

            company_selector = f'[data-company="{company_display}"], option:has-text("{company_display}"), li:has-text("{company_display}")'
            try:
                await page.wait_for_selector(company_selector, timeout=5000)
                await page.click(company_selector)
                await page.wait_for_load_state("domcontentloaded")
            except Exception:
                # No company picker — assume already in the right company context
                pass

            # ----------------------------------------------------------------
            # STEP 8: Enter pay for each driver
            # Paychex pay grids typically show a table of workers. We search
            # by worker_id (the Paychex employee/worker number) and fill in
            # the 1099-NEC earnings column.
            # ----------------------------------------------------------------
            for i, driver in enumerate(drivers):
                worker_id = driver["worker_id"]
                name = driver["name"]
                amount = driver["amount"]
                formatted_amount = f"{amount:.2f}"

                try:
                    # -- Find the driver row --
                    # Paychex pay entry tables usually have a search/filter box
                    # at the top, or rows identified by employee ID.

                    # Try using a search box to filter to this worker
                    search_selector = (
                        'input[placeholder*="search"], '
                        'input[aria-label*="search"], '
                        'input[type="search"], '
                        '#employee-search, '
                        'input[name*="search"]'
                    )
                    try:
                        search_box = await page.wait_for_selector(search_selector, timeout=5000)
                        await search_box.triple_click()        # select all existing text
                        await search_box.fill(worker_id)       # type the worker ID
                        await page.keyboard.press("Enter")
                        await page.wait_for_timeout(800)       # brief pause for results to load
                    except Exception:
                        # No search box — assume the full grid is visible
                        pass

                    # Locate the row that contains this worker's ID.
                    # Paychex renders rows as <tr> with the worker ID in a cell,
                    # or as divs with data attributes.
                    row_selector = (
                        f'tr:has-text("{worker_id}"), '
                        f'tr:has-text("{name}"), '
                        f'[data-worker-id="{worker_id}"], '
                        f'[data-employee-id="{worker_id}"]'
                    )
                    row = await page.wait_for_selector(row_selector, timeout=15000)

                    # -- Find the 1099-NEC amount cell within that row --
                    # The column header is usually "1099-NEC", "NEC", "Nonemployee Comp",
                    # or "NEC Amount". The input inside the row matches one of these.
                    nec_input_selector = (
                        'input[aria-label*="1099"], '
                        'input[aria-label*="NEC"], '
                        'input[data-pay-type*="1099"], '
                        'input[data-pay-type*="NEC"], '
                        'input[placeholder*="NEC"], '
                        'td[class*="nec"] input, '
                        'td[class*="1099"] input'
                    )
                    nec_input = await row.query_selector(nec_input_selector)

                    if nec_input is None:
                        # Fallback: grab all inputs in the row and use the first
                        # numeric-type one that isn't already labeled for something else
                        inputs = await row.query_selector_all('input[type="number"], input[type="text"]')
                        if inputs:
                            nec_input = inputs[0]
                        else:
                            raise Exception(f"Could not find 1099-NEC input field in row for worker {worker_id}")

                    # Clear the field and enter the amount
                    await nec_input.triple_click()                 # select all
                    await nec_input.fill("")                       # clear
                    await nec_input.fill(formatted_amount)         # type amount
                    await nec_input.press("Tab")                   # tab away to trigger validation

                    on_status({
                        "status": "running",
                        "progress": i + 1,
                        "total": len(drivers),
                        "current_driver": name,
                        "message": f"Entered ${formatted_amount} for {name}"
                    })

                except Exception as e:
                    on_status({
                        "status": "driver_error",
                        "driver": name,
                        "error": str(e),
                        "message": f"Failed to enter pay for {name}: {e}"
                    })
                    # Continue with the next driver
                    continue

            # ----------------------------------------------------------------
            # STEP 9: Done — DO NOT submit or finalize
            # Leave all entries as drafts. The user will log in and review
            # before manually clicking Submit/Finalize.
            # ----------------------------------------------------------------
            on_status({
                "status": "done",
                "message": "All entries complete. Log into Paychex to review and submit."
            })

        finally:
            # Close the browser (headless mode — no UI to leave open)
            await browser.close()


# ----------------------------------------------------------------------------
# Manual test entrypoint
# Run with:
#   PAYCHEX_USERNAME=you@example.com PAYCHEX_PASSWORD=secret python paychex_entry.py
# ----------------------------------------------------------------------------

def main():
    """Test runner — reads credentials from environment variables."""

    username = os.environ.get("PAYCHEX_USERNAME", "")
    password = os.environ.get("PAYCHEX_PASSWORD", "")
    company  = os.environ.get("PAYCHEX_COMPANY", "maz")   # "acumen" or "maz"

    if not username or not password:
        print("Set PAYCHEX_USERNAME and PAYCHEX_PASSWORD env vars to run the test.")
        return

    # Sample drivers for manual testing
    test_drivers = [
        {"worker_id": "W001", "name": "John Smith",    "amount": 1250.00},
        {"worker_id": "W002", "name": "Maria Garcia",  "amount":  875.50},
        {"worker_id": "W003", "name": "James Williams", "amount": 2100.75},
    ]

    def status_handler(event: dict) -> None:
        status = event.get("status", "")
        message = event.get("message", "")
        progress = event.get("progress")
        total = event.get("total")

        if progress is not None and total is not None:
            print(f"[{status.upper()}] ({progress}/{total}) {message}")
        else:
            print(f"[{status.upper()}] {message}")

    asyncio.run(
        run_paychex_entry(
            company=company,
            username=username,
            password=password,
            drivers=test_drivers,
            on_status=status_handler,
        )
    )


if __name__ == "__main__":
    main()
