# NOTE: Paychex selectors may need updating — use browser devtools to verify

import asyncio
import json
import os
from typing import Callable
from playwright.async_api import async_playwright, Page, BrowserContext

PAYCHEX_URL = "https://myapps.paychex.com"


async def run_paychex_entry(
    company: str,                            # "acumen" or "maz"
    username: str,
    password: str,
    drivers: list[dict],                     # [{"worker_id": str, "name": str, "amount": float}]
    on_status: Callable[[dict], None],       # callback for progress updates
    session_cookies: list[dict] | None = None,  # pre-captured browser cookies (skips login)
) -> None:
    """
    Automates Paychex Flex payroll entry for 1099-NEC workers.

    Steps:
      1. Launch browser
      1a. If session_cookies provided: inject them and navigate directly to Paychex Flex
          (skips login + MFA entirely). Falls back to normal login if session is expired.
      2. Enter username (only if no valid session)
      3. Enter password (only if no valid session)
      4. Handle MFA if required (only if no valid session)
      5. Navigate to the payroll entry / pay grid
      6. For each driver, find their row and fill in the 1099-NEC amount
      7. Never submit — leave entries in draft for manual review and submission
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
            # STEP 1: Session cookie fast-path (skip login entirely)
            # If we have pre-captured cookies from a real browser login,
            # inject them and navigate straight to Paychex Flex.
            # ----------------------------------------------------------------
            session_valid = False

            if session_cookies:
                on_status({"status": "running", "message": "Loading saved session cookies..."})
                await context.add_cookies(session_cookies)
                # Navigate directly to Paychex Flex (bypass login page)
                await page.goto("https://flex.paychex.com", wait_until="domcontentloaded")
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass  # proceed — some SPAs stay "loading" forever

                # Element-based session check — far more reliable than URL pattern matching.
                # If the login form is present anywhere, we are NOT logged in.
                # If it's absent after a brief wait, cookies worked and we are on the dashboard
                # (or being routed through Paychex's post-login OIDC chain).
                current_url = page.url
                try:
                    await page.wait_for_selector('#login-username', timeout=5000)
                    # Login form rendered → cookies didn't authenticate us
                    on_status({"status": "running", "message": f"Session expired (url={current_url[:80]}) — falling back to username/password login..."})
                    session_cookies = None  # force normal login flow below
                except Exception:
                    # No login form found → session is good
                    session_valid = True
                    on_status({"status": "running", "message": f"Session loaded (url={current_url[:80]}) — navigating to payroll..."})

            if not session_valid:
                # ----------------------------------------------------------------
                # STEP 1 (fallback): Navigate to Paychex Flex login page
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

                # If still on the login/auth page, login failed.
                # myapps.paychex.com is the post-login portal (success), not a login URL.
                login_indicators = ["login.flex.paychex.com", "signin", "/login", "/auth"]
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

            # Real navigation flow (verified against live Paychex Flex 2026-05-20):
            # The portal landing page shows a "Current payroll" card with a Begin button.
            # Clicking it navigates to the actual Pay Entry app at
            # myapps.paychex.com/landing_remote/login.do?... where rows can actually be filled.
            on_status({"status": "running", "message": "Looking for Current Payroll → Begin button..."})

            begin_selector = (
                'button:has-text("Begin"), '
                'a:has-text("Begin"), '
                'button:has-text("Start payroll"), '
                'a:has-text("Start payroll"), '
                'button:has-text("Continue"), '
                'a:has-text("Continue")'
            )
            try:
                await page.wait_for_selector(begin_selector, timeout=15000)
                await page.click(begin_selector)
                await page.wait_for_load_state("domcontentloaded")
                try:
                    await page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    pass
            except Exception as nav_err:
                # Diagnostic: dump what's visible on the portal so we can see why "Begin" isn't there
                try:
                    diag = await page.evaluate("""
                        () => {
                            const txt = document.body.innerText || '';
                            return {
                                url: location.href,
                                title: document.title,
                                button_texts: Array.from(document.querySelectorAll('button')).slice(0, 20).map(b => (b.innerText || '').slice(0, 40)),
                                link_texts: Array.from(document.querySelectorAll('a')).slice(0, 20).map(a => (a.innerText || '').slice(0, 40)),
                                body_text_sample: txt.slice(0, 500),
                            };
                        }
                    """)
                except Exception as e:
                    diag = {"diagnostic_error": str(e)[:200]}
                raise Exception(
                    f"Could not find 'Begin' / 'Start payroll' button on Paychex portal. "
                    f"Diagnostic: {json.dumps(diag, default=str)[:800]}"
                ) from nav_err

            # After clicking Begin, Paychex shows a "Start Payroll" intermediate modal
            # with two radio options:
            #   (•) Automatically create checks  [default]
            #   ( ) I'll enter checks myself
            # We need "I'll enter checks myself" + Continue to land in actual Pay Entry.
            #
            # NOTE: only treat the modal as ABSENT if we cannot find the literal text.
            # If we find the text but can't click the radio, that's a real failure → raise.
            on_status({"status": "running", "message": "Handling Start Payroll modal..."})

            # Detect modal presence by body text rather than a brittle element selector
            modal_text_present = False
            try:
                modal_text_present = await page.evaluate(
                    "() => (document.body.innerText || '').includes(\"I'll enter checks myself\")"
                )
            except Exception:
                pass

            if modal_text_present:
                # Use Playwright's text-based locator — works regardless of <label>/<span>/<div>
                try:
                    # Click the text label first (often this toggles the associated radio)
                    await page.get_by_text("I'll enter checks myself").first.click(timeout=8000)
                    await page.wait_for_timeout(400)  # let radio state settle
                except Exception as radio_err:
                    # Fall back to finding any radio whose parent/ancestor contains the text
                    try:
                        await page.locator('input[type="radio"]').nth(1).click(timeout=5000)
                        await page.wait_for_timeout(400)
                    except Exception:
                        raise Exception(
                            f"Modal visible but could not click 'I'll enter checks myself' radio. "
                            f"Underlying error: {str(radio_err)[:200]}"
                        ) from radio_err

                # Click Continue
                try:
                    await page.get_by_role("button", name="Continue").click(timeout=8000)
                except Exception:
                    # Fall back to broad button text match
                    await page.click('button:has-text("Continue"), a:has-text("Continue")', timeout=8000)

                await page.wait_for_load_state("domcontentloaded")
                try:
                    await page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    pass
            else:
                on_status({"status": "running", "message": "No Start Payroll modal — proceeding to Pay Entry check..."})

            # HARD GATE — we must verify we're actually on the Pay Entry page before
            # touching anything that looks like a row. Pay Entry has a distinctive
            # "Search by Name or ID" box and a "Review & Submit" button. If neither
            # is present, we're on the wrong page and must NOT type anything.
            on_status({"status": "running", "message": "Verifying we reached Pay Entry..."})

            pay_entry_indicator = (
                'input[placeholder*="Search by Name"], '
                'button:has-text("Review & Submit"), '
                'button:has-text("Review and Submit"), '
                'text="Review & Submit"'
            )
            try:
                await page.wait_for_selector(pay_entry_indicator, timeout=20000)
            except Exception as pe_err:
                try:
                    diag = await page.evaluate("""
                        () => {
                            const txt = document.body.innerText || '';
                            return {
                                url: location.href,
                                title: document.title,
                                has_search_box: !!document.querySelector('input[placeholder*="Search"]'),
                                has_review_submit: txt.includes('Review') && txt.includes('Submit'),
                                body_text_sample: txt.slice(0, 600),
                            };
                        }
                    """)
                except Exception as e:
                    diag = {"diagnostic_error": str(e)[:200]}
                raise Exception(
                    f"Begin button clicked but Pay Entry page never loaded. "
                    f"Refusing to type into unknown UI. Diagnostic: {json.dumps(diag, default=str)[:800]}"
                ) from pe_err

            on_status({"status": "running", "message": "Reached Pay Entry. Starting driver entries..."})

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
                    # Paychex Flex is a modern SPA — rows can be <tr>, div[role=row],
                    # or other custom grid containers. Try a broad set.
                    row_selector = (
                        f'tr:has-text("{worker_id}"), '
                        f'tr:has-text("{name}"), '
                        f'[data-worker-id="{worker_id}"], '
                        f'[data-employee-id="{worker_id}"], '
                        f'[role="row"]:has-text("{worker_id}"), '
                        f'[role="row"]:has-text("{name}"), '
                        f'div[class*="row"]:has-text("{worker_id}"), '
                        f'div[class*="Row"]:has-text("{worker_id}"), '
                        f'li:has-text("{worker_id}")'
                    )
                    try:
                        row = await page.wait_for_selector(row_selector, timeout=15000)
                    except Exception as row_err:
                        # Capture diagnostic info so the next iteration knows what we're up against
                        try:
                            diag = await page.evaluate(f"""
                                () => {{
                                    const txt = document.body.innerText || '';
                                    return {{
                                        url: location.href,
                                        title: document.title,
                                        tr_count: document.querySelectorAll('tr').length,
                                        role_row_count: document.querySelectorAll('[role="row"]').length,
                                        div_row_count: document.querySelectorAll('div[class*="row"], div[class*="Row"]').length,
                                        input_count: document.querySelectorAll('input').length,
                                        body_text_sample: txt.slice(0, 400),
                                        worker_id_in_dom: txt.includes('{worker_id}'),
                                        name_in_dom: txt.includes('{name.split()[0]}'),
                                    }};
                                }}
                            """)
                        except Exception as e:
                            diag = {"diagnostic_error": str(e)[:200]}
                        raise Exception(
                            f"Row not found for {name} (worker_id {worker_id}). "
                            f"Diagnostic: {json.dumps(diag, default=str)[:800]}"
                        ) from row_err

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
                    await page.wait_for_timeout(400)               # let any onChange settle

                    # Verify the value was actually accepted
                    entered_value = await nec_input.input_value()
                    entered_normalized = entered_value.replace(",", "").strip()
                    expected_normalized = formatted_amount.lstrip("0") or "0"
                    # Paychex may render "1250.00" or "1,250.00" — normalize both
                    try:
                        entered_float = float(entered_normalized) if entered_normalized else 0.0
                        expected_float = float(formatted_amount)
                        verified = abs(entered_float - expected_float) < 0.01
                    except ValueError:
                        verified = False

                    if not verified:
                        raise Exception(
                            f"Verification failed for {name}: entered {formatted_amount}, "
                            f"field shows '{entered_value}'. The value may not have been accepted."
                        )

                    on_status({
                        "status": "running",
                        "progress": i + 1,
                        "total": len(drivers),
                        "current_driver": name,
                        "message": f"✓ Verified ${formatted_amount} for {name}"
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
