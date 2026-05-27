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
    headless: bool = True,                   # set False to watch the browser locally
    screenshot_dir: str | None = None,       # if set, save screenshot + DOM dump at each step
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
            headless=headless,
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

        _snap_n = [0]

        async def snap(label: str) -> None:
            """Save a full-page screenshot + DOM dump when screenshot_dir is set. No-op otherwise."""
            if not screenshot_dir:
                return
            try:
                os.makedirs(screenshot_dir, exist_ok=True)
                _snap_n[0] += 1
                base = os.path.join(screenshot_dir, f"{_snap_n[0]:02d}_{label}")
                await page.screenshot(path=f"{base}.png", full_page=True)
                html = await page.content()
                with open(f"{base}.html", "w") as fh:
                    fh.write(html)
            except Exception:
                pass

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

            await snap("after_session_load")

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
                await snap("ERROR_begin_not_found")
                raise Exception(
                    f"Could not find 'Begin' / 'Start payroll' button on Paychex portal. "
                    f"Diagnostic: {json.dumps(diag, default=str)[:800]}"
                ) from nav_err

            await snap("after_begin_click")

            # After clicking Begin, Paychex shows the "Start Payroll" card. It loads
            # pay-entry preferences asynchronously, THEN reveals two radio options:
            #   ( ) Automatically create checks
            #   ( ) I'll enter checks myself   <- we need this
            # plus a Continue button. The radio group lives inside a div that starts
            # hidden (Angular ng-hide) until payEntryPreferences finishes loading, so
            # we must WAIT for the radio to become visible — a one-shot check fires
            # too early and misses it entirely.
            on_status({"status": "running", "message": "Handling Start Payroll card..."})

            START_CARD     = '[data-payxautoid="paychex.app.payroll.quickPayroll.startPayroll.startPayrollLabel"]'
            MANUAL_CAPTION = '[data-payxautoid="paychex.app.payroll.quickPayroll.startPayroll.manualChecksRadioButton.caption"]'
            MANUAL_RADIO   = '[data-payxautoid="paychex.app.payroll.quickPayroll.startPayroll.manualChecksRadioButton"]'
            CONTINUE_BTN   = '[data-payxautoid="paychex.app.payroll.quickPayroll.startPayroll.continueButton"]'

            start_card_present = await page.locator(START_CARD).count() > 0

            if start_card_present:
                caption = page.locator(MANUAL_CAPTION)
                # Wait for the radio option to render (preferences load async).
                try:
                    await caption.wait_for(state="visible", timeout=20000)
                except Exception:
                    # Radios still hidden — click the card header to activate it, retry.
                    try:
                        await page.locator(START_CARD).click(timeout=5000)
                    except Exception:
                        pass
                    try:
                        await caption.wait_for(state="visible", timeout=15000)
                    except Exception as radio_err:
                        await snap("ERROR_start_payroll_radio_hidden")
                        raise Exception(
                            "Start Payroll card present but 'I'll enter checks myself' "
                            f"radio never became visible. Underlying error: {str(radio_err)[:200]}"
                        ) from radio_err

                # Select "I'll enter checks myself" — click the caption (label-wrapped radio).
                await caption.click()
                await page.wait_for_timeout(400)
                try:
                    if not await page.locator(MANUAL_RADIO).is_checked():
                        await page.locator(MANUAL_RADIO).check(force=True)
                except Exception:
                    pass

                # Click Continue
                await page.locator(CONTINUE_BTN).click(timeout=10000)
                await page.wait_for_load_state("domcontentloaded")
                try:
                    await page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    pass
            else:
                on_status({"status": "running", "message": "No Start Payroll card — proceeding to Pay Entry check..."})

            await snap("after_modal")

            # HARD GATE — we must verify we're actually on the Pay Entry page before
            # touching anything that looks like a row. Pay Entry has a distinctive
            # "Search by Name or ID" box and a "Review & Submit" button. If neither
            # is present, we're on the wrong page and must NOT type anything.
            on_status({"status": "running", "message": "Verifying we reached Pay Entry..."})

            # The Pay Entry search bar is the most reliable "we made it" signal:
            # a single stable data-payxautoid present only on the real Pay Entry grid.
            pay_entry_indicator = (
                '[data-payxautoid="paychex.app.payroll.payrollEntry.search.searchBar.input"]'
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
                await snap("ERROR_pay_entry_not_found")
                raise Exception(
                    f"Begin button clicked but Pay Entry page never loaded. "
                    f"Refusing to type into unknown UI. Diagnostic: {json.dumps(diag, default=str)[:800]}"
                ) from pe_err

            on_status({"status": "running", "message": "Reached Pay Entry. Starting driver entries..."})
            await snap("pay_entry_reached")

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
            # STEP 8: Enter pay for each driver — COMPANY-AWARE
            # Maz and Acumen use different Paychex Flex layouts:
            #
            #   Maz (flex.paychex.com → Pay Entry view)
            #     Cell autoId: paychex.app.payroll.payrollEntry.grid.{wid}.1.amount.1099-NEC
            #     The cell becomes editable on click; input lives inside the cell.
            #
            #   Acumen (myapps.paychex.com → Payroll Center → Basic - All Employees)
            #     Uses Kendo UI grid framework. No cell-level autoId in non-edit state.
            #     Must locate the row, click the 1099-NEC Amount column cell, then
            #     wait for the input with worker-specific autoId to appear:
            #     paychex.app.payroll.payrollEntry.worker.{wid}.check.1.row.0.1099NecAmount.edit
            # ----------------------------------------------------------------
            is_acumen = (company or "").lower() == "acumen"

            for i, driver in enumerate(drivers):
                worker_id = driver["worker_id"]
                name = driver["name"]
                amount = driver["amount"]
                formatted_amount = f"{amount:.2f}"

                # Maz-only locators (Acumen uses different locators below)
                amount_auto = f"paychex.app.payroll.payrollEntry.grid.{worker_id}.1.amount.1099-NEC"
                amount_cell = page.locator(f'[data-payxautoid="{amount_auto}"]')

                try:
                    # -- Search to bring this worker's row into the virtualized grid --
                    # The Pay Entry grid only renders ~9 of N rows at a time, so we
                    # must search per worker (by worker_id / Paychex code) to force
                    # the row into the DOM. We MUST filter by worker_id, not name —
                    # some workers are paid to LLCs whose registered name in Paychex
                    # doesn't match the driver's name in Z-Pay. Worker code is the
                    # only stable identifier.
                    #
                    # Previous .fill() approach failed because it set the input value
                    # without triggering Angular's ng-change. The Search button stayed
                    # disabled, the click silently failed, and the grid never filtered.
                    # We now type() with per-char delay so real keystroke events fire.
                    search_box = page.locator(
                        '[data-payxautoid="paychex.app.payroll.payrollEntry.search.searchBar.input"]'
                    )
                    await search_box.wait_for(state="visible", timeout=10000)

                    # Clear the field reliably (fill("") on Angular inputs is flaky)
                    await search_box.click()
                    await page.keyboard.press("Control+a")
                    await page.keyboard.press("Delete")
                    # Type real keystrokes so Angular's ng-change fires + enables Search
                    await search_box.type(str(worker_id), delay=35)
                    await page.wait_for_timeout(600)  # let Angular digest

                    # Submit the search — try button click, then Enter, then JS event
                    submitted = False
                    try:
                        search_btn = page.locator(
                            '[data-payxautoid="paychex.app.payroll.payrollEntry.search.searchButton"]'
                        )
                        await search_btn.wait_for(state="visible", timeout=4000)
                        await search_btn.click(timeout=3000)
                        submitted = True
                    except Exception:
                        try:
                            await search_box.press("Enter")
                            submitted = True
                        except Exception:
                            pass

                    if not submitted:
                        # Last resort: dispatch input + Enter via JS so Angular's
                        # ng-model and the keydown handler both fire.
                        await page.evaluate(
                            """(wid) => {
                                const el = document.querySelector(
                                    '[data-payxautoid="paychex.app.payroll.payrollEntry.search.searchBar.input"]'
                                );
                                if (el) {
                                    el.value = wid;
                                    el.dispatchEvent(new Event('input', {bubbles: true}));
                                    el.dispatchEvent(new Event('change', {bubbles: true}));
                                    el.dispatchEvent(new KeyboardEvent('keydown', {
                                        key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true
                                    }));
                                }
                            }""",
                            str(worker_id),
                        )

                    # Let the grid re-render after the filter
                    await page.wait_for_timeout(1500)

                    # =========================================================
                    # COMPANY-AWARE row location + cell click + input fill
                    # =========================================================
                    filled = False

                    if is_acumen:
                        # ----- ACUMEN (Kendo UI grid) ------------------------
                        # 1. Search filters to one row (verified manually).
                        # 2. Find the 1099-NEC Amount column index from headers.
                        # 3. Click that TD in the filtered row -> cell enters
                        #    edit mode -> input with the worker-specific autoId
                        #    appears.
                        editor_autoid = (
                            f"paychex.app.payroll.payrollEntry.worker.{worker_id}"
                            f".check.1.row.0.1099NecAmount.edit"
                        )

                        # JS: locate + click the 1099-NEC Amount cell in the
                        # row containing this worker_id. Returns True on click.
                        clicked = await page.evaluate(
                            """({wid}) => {
                                // Find the column index whose header is "1099-NEC Amount"
                                const headers = Array.from(document.querySelectorAll('table thead th'));
                                let colIdx = -1;
                                for (let i = 0; i < headers.length; i++) {
                                    const t = (headers[i].textContent || '').trim();
                                    if (t.includes('1099-NEC') && t.toLowerCase().includes('amount')) {
                                        colIdx = i;
                                        break;
                                    }
                                }
                                // Find the worker's row by ID text content
                                const rows = Array.from(document.querySelectorAll('tr.k-master-row'));
                                for (const r of rows) {
                                    if ((r.textContent || '').includes(wid)) {
                                        const cells = r.querySelectorAll('td');
                                        // Prefer header index match; fall back to last cell
                                        let target = (colIdx >= 0 && colIdx < cells.length)
                                            ? cells[colIdx]
                                            : cells[cells.length - 1];
                                        if (!target) return false;
                                        target.scrollIntoView({block: 'center', behavior: 'instant'});
                                        target.click();
                                        return true;
                                    }
                                }
                                return false;
                            }""",
                            {"wid": str(worker_id)},
                        )

                        if not clicked:
                            await snap(f"ERROR_acumen_row_not_found_{worker_id}")
                            raise Exception(
                                f"Acumen row not found for {name} (worker_id {worker_id}) "
                                f"after search. Header lookup or row-by-text failed."
                            )

                        await page.wait_for_timeout(500)

                        # The TD click should activate edit mode. The input
                        # with the worker-specific autoId now appears.
                        editor = page.locator(f'[data-payxautoid="{editor_autoid}"]')
                        try:
                            await editor.wait_for(state="visible", timeout=6000)
                        except Exception as edit_err:
                            # Sometimes the first click selects the row instead
                            # of entering edit mode. Click the same cell again.
                            await snap(f"WARN_acumen_first_click_no_editor_{worker_id}")
                            await page.evaluate(
                                """({wid}) => {
                                    const headers = Array.from(document.querySelectorAll('table thead th'));
                                    let colIdx = -1;
                                    for (let i = 0; i < headers.length; i++) {
                                        const t = (headers[i].textContent || '').trim();
                                        if (t.includes('1099-NEC') && t.toLowerCase().includes('amount')) {
                                            colIdx = i; break;
                                        }
                                    }
                                    const rows = Array.from(document.querySelectorAll('tr.k-master-row'));
                                    for (const r of rows) {
                                        if ((r.textContent || '').includes(wid)) {
                                            const cells = r.querySelectorAll('td');
                                            const target = (colIdx >= 0 && colIdx < cells.length)
                                                ? cells[colIdx] : cells[cells.length - 1];
                                            if (target) {
                                                target.click();
                                                // Some Kendo grids need a double-click to enter edit
                                                target.dispatchEvent(new MouseEvent('dblclick', {bubbles: true}));
                                            }
                                            return;
                                        }
                                    }
                                }""",
                                {"wid": str(worker_id)},
                            )
                            await page.wait_for_timeout(600)
                            try:
                                await editor.wait_for(state="visible", timeout=4000)
                            except Exception:
                                await snap(f"ERROR_acumen_editor_never_appeared_{worker_id}")
                                raise Exception(
                                    f"Acumen editor input never appeared for {name} "
                                    f"(worker_id {worker_id}). Underlying: {str(edit_err)[:200]}"
                                )

                        if i == 0:
                            await snap(f"acumen_editor_open_{worker_id}")

                        # Fill the input. Kendo inputs respond to fill() reliably.
                        try:
                            await editor.fill(formatted_amount)
                            filled = True
                        except Exception:
                            try:
                                await editor.click()
                                await page.keyboard.press("Control+a")
                                await page.keyboard.type(formatted_amount, delay=40)
                                filled = True
                            except Exception:
                                pass

                    else:
                        # ----- MAZ (existing flex.paychex.com Pay Entry view) ----
                        # JS query first so we know whether the row is in DOM at all
                        # (Playwright's wait_for(visible) can't distinguish "in DOM
                        # but not visible" from "not in DOM").
                        found_in_dom = await page.evaluate(
                            """(sel) => !!document.querySelector(sel)""",
                            f'[data-payxautoid="{amount_auto}"]',
                        )

                        if found_in_dom:
                            await page.evaluate(
                                """(sel) => {
                                    const el = document.querySelector(sel);
                                    if (el) el.scrollIntoView({block: 'center', behavior: 'instant'});
                                }""",
                                f'[data-payxautoid="{amount_auto}"]',
                            )
                            await page.wait_for_timeout(400)

                        try:
                            await amount_cell.wait_for(state="visible", timeout=10000)
                        except Exception:
                            await snap(f"WARN_row_not_visible_after_search_{worker_id}")
                            scroll_found = False
                            for _scroll_i in range(20):
                                await page.keyboard.press("PageDown")
                                await page.wait_for_timeout(250)
                                found_in_dom = await page.evaluate(
                                    """(sel) => !!document.querySelector(sel)""",
                                    f'[data-payxautoid="{amount_auto}"]',
                                )
                                if found_in_dom:
                                    await page.evaluate(
                                        """(sel) => {
                                            const el = document.querySelector(sel);
                                            if (el) el.scrollIntoView({block: 'center', behavior: 'instant'});
                                        }""",
                                        f'[data-payxautoid="{amount_auto}"]',
                                    )
                                    await page.wait_for_timeout(400)
                                    try:
                                        await amount_cell.wait_for(state="visible", timeout=4000)
                                        scroll_found = True
                                        break
                                    except Exception:
                                        continue
                            if not scroll_found:
                                await snap(f"ERROR_amount_cell_never_found_{worker_id}")
                                raise Exception(
                                    f"1099-NEC amount cell not found for {name} (worker_id {worker_id}) "
                                    f"after typed-search + JS-scroll + PageDown scan. "
                                    f"Verification pass will catch this driver."
                                )

                        await amount_cell.scroll_into_view_if_needed()
                        await amount_cell.click()
                        await page.wait_for_timeout(500)
                        if i == 0:
                            await snap(f"editor_open_{worker_id}")

                        editor = page.locator(f'[data-payxautoid="{amount_auto}"] input').first
                        try:
                            await editor.wait_for(state="visible", timeout=3000)
                            await editor.fill(formatted_amount)
                            filled = True
                        except Exception:
                            try:
                                await page.keyboard.press("Control+a")
                                await page.keyboard.type(formatted_amount, delay=40)
                                filled = True
                            except Exception:
                                pass

                    if not filled:
                        await snap(f"ERROR_amount_fill_failed_{worker_id}")
                        raise Exception(
                            f"Could not enter amount for {name} (worker_id {worker_id})."
                        )

                    await page.keyboard.press("Tab")  # commit + trigger validation
                    # Paychex autosaves each entry async (debounced). Wait for the
                    # save POST to fire and settle before moving on — otherwise the
                    # final driver's save can be cut off when the browser closes.
                    await page.wait_for_timeout(1200)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass

                    # -- Verify the entry persisted (company-aware) ---------
                    verified = False
                    try:
                        if is_acumen:
                            # Read the 1099-NEC Amount cell text content via JS
                            actual = await page.evaluate(
                                """({wid}) => {
                                    const headers = Array.from(document.querySelectorAll('table thead th'));
                                    let colIdx = -1;
                                    for (let i = 0; i < headers.length; i++) {
                                        const t = (headers[i].textContent || '').trim();
                                        if (t.includes('1099-NEC') && t.toLowerCase().includes('amount')) {
                                            colIdx = i; break;
                                        }
                                    }
                                    const rows = Array.from(document.querySelectorAll('tr.k-master-row'));
                                    for (const r of rows) {
                                        if ((r.textContent || '').includes(wid)) {
                                            const cells = r.querySelectorAll('td');
                                            const cell = (colIdx >= 0 && colIdx < cells.length)
                                                ? cells[colIdx] : cells[cells.length - 1];
                                            if (!cell) return null;
                                            return (cell.textContent || '').trim();
                                        }
                                    }
                                    return null;
                                }""",
                                {"wid": str(worker_id)},
                            )
                            if actual:
                                cleaned = actual.replace(",", "").replace("$", "").strip()
                                try:
                                    verified = abs(float(cleaned) - amount) < 0.01
                                except Exception:
                                    verified = False
                        else:
                            total_text = await page.locator(
                                f'[data-payxautoid="paychex.app.payroll.payrollEntry.grid.{worker_id}.1.total"]'
                            ).inner_text()
                            cleaned = total_text.replace(",", "").replace("$", "").strip()
                            verified = abs(float(cleaned) - amount) < 0.01
                    except Exception:
                        verified = False

                    if not verified:
                        await snap(f"WARN_unverified_{worker_id}")

                    on_status({
                        "status": "running",
                        "progress": i + 1,
                        "total": len(drivers),
                        "current_driver": name,
                        "message": (
                            f"✓ Entered ${formatted_amount} for {name}"
                            if verified else
                            f"⚠ Entered ${formatted_amount} for {name} — review (total not auto-verified)"
                        ),
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

            # Final flush — the last entry's autosave is async. Wait for it to
            # reach Paychex's server before we close the browser, or the final
            # driver silently won't persist (the UI shows it locally regardless).
            on_status({"status": "running", "message": "Waiting for Paychex to save the final entry..."})
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            await page.wait_for_timeout(8000)

            # ----------------------------------------------------------------
            # STEP 8b: Verification pass — re-check every driver, re-fill $0s
            # ----------------------------------------------------------------
            # This catches two recurring bugs:
            #   1. Last-driver autosave race: Paychex's debounced save POST for
            #      the final driver got cut off when the browser was about to
            #      close. We see the local UI showed the amount but server has
            #      it at $0.
            #   2. Mid-batch skips: the search-and-fill loop occasionally bails
            #      on a driver (search timing flake) but we continue. The
            #      verification pass picks them up at the end.
            #
            # For each driver, we re-locate the row by worker_id, read the row's
            # 1099-NEC total, and if it's not the expected amount, we re-fill.
            on_status({
                "status": "running",
                "message": "Verifying all entries persisted...",
            })
            missing: list[dict] = []
            for driver in drivers:
                worker_id_v = driver["worker_id"]
                name_v = driver["name"]
                expected = float(driver["amount"])

                # Bring the row into the viewport so we can read its total.
                try:
                    search_box_v = page.locator(
                        '[data-payxautoid="paychex.app.payroll.payrollEntry.search.searchBar.input"]'
                    )
                    await search_box_v.click()
                    await page.keyboard.press("Control+a")
                    await page.keyboard.press("Delete")
                    await search_box_v.type(str(worker_id_v), delay=35)
                    await page.wait_for_timeout(500)
                    try:
                        await page.locator(
                            '[data-payxautoid="paychex.app.payroll.payrollEntry.search.searchButton"]'
                        ).click(timeout=3000)
                    except Exception:
                        await search_box_v.press("Enter")
                    await page.wait_for_timeout(1200)

                    if is_acumen:
                        # Read the 1099-NEC Amount cell text from the Kendo row
                        actual_text = await page.evaluate(
                            """({wid}) => {
                                const headers = Array.from(document.querySelectorAll('table thead th'));
                                let colIdx = -1;
                                for (let i = 0; i < headers.length; i++) {
                                    const t = (headers[i].textContent || '').trim();
                                    if (t.includes('1099-NEC') && t.toLowerCase().includes('amount')) {
                                        colIdx = i; break;
                                    }
                                }
                                const rows = Array.from(document.querySelectorAll('tr.k-master-row'));
                                for (const r of rows) {
                                    if ((r.textContent || '').includes(wid)) {
                                        const cells = r.querySelectorAll('td');
                                        const cell = (colIdx >= 0 && colIdx < cells.length)
                                            ? cells[colIdx] : cells[cells.length - 1];
                                        if (!cell) return null;
                                        return (cell.textContent || '').trim();
                                    }
                                }
                                return null;
                            }""",
                            {"wid": str(worker_id_v)},
                        )
                        cleaned = (actual_text or "").replace(",", "").replace("$", "").strip()
                        try:
                            actual = float(cleaned or 0)
                        except Exception:
                            actual = 0.0
                    else:
                        total_auto = f"paychex.app.payroll.payrollEntry.grid.{worker_id_v}.1.total"
                        total_text = await page.locator(
                            f'[data-payxautoid="{total_auto}"]'
                        ).inner_text(timeout=6000)
                        cleaned = total_text.replace(",", "").replace("$", "").strip()
                        actual = float(cleaned or 0)

                    if abs(actual - expected) >= 0.01:
                        missing.append({
                            "worker_id": worker_id_v,
                            "name": name_v,
                            "amount": expected,
                            "actual": actual,
                        })
                except Exception:
                    # If we can't read the total, treat as needs-refill
                    missing.append({
                        "worker_id": worker_id_v,
                        "name": name_v,
                        "amount": expected,
                        "actual": None,
                    })

            if missing:
                on_status({
                    "status": "running",
                    "message": f"Refilling {len(missing)} driver(s) whose entries didn't persist...",
                })
                await snap("verification_found_missing")

                for m in missing:
                    worker_id_r = m["worker_id"]
                    name_r = m["name"]
                    amount_r = m["amount"]
                    formatted_r = f"{amount_r:.2f}"

                    try:
                        # Search again (it's possible the previous search was stale)
                        search_box_r = page.locator(
                            '[data-payxautoid="paychex.app.payroll.payrollEntry.search.searchBar.input"]'
                        )
                        await search_box_r.click()
                        await page.keyboard.press("Control+a")
                        await page.keyboard.press("Delete")
                        await search_box_r.type(str(worker_id_r), delay=35)
                        await page.wait_for_timeout(600)
                        try:
                            await page.locator(
                                '[data-payxautoid="paychex.app.payroll.payrollEntry.search.searchButton"]'
                            ).click(timeout=3000)
                        except Exception:
                            await search_box_r.press("Enter")
                        await page.wait_for_timeout(1500)

                        if is_acumen:
                            editor_autoid_r = (
                                f"paychex.app.payroll.payrollEntry.worker.{worker_id_r}"
                                f".check.1.row.0.1099NecAmount.edit"
                            )
                            # Click the 1099-NEC Amount cell in the row
                            await page.evaluate(
                                """({wid}) => {
                                    const headers = Array.from(document.querySelectorAll('table thead th'));
                                    let colIdx = -1;
                                    for (let i = 0; i < headers.length; i++) {
                                        const t = (headers[i].textContent || '').trim();
                                        if (t.includes('1099-NEC') && t.toLowerCase().includes('amount')) {
                                            colIdx = i; break;
                                        }
                                    }
                                    const rows = Array.from(document.querySelectorAll('tr.k-master-row'));
                                    for (const r of rows) {
                                        if ((r.textContent || '').includes(wid)) {
                                            const cells = r.querySelectorAll('td');
                                            const target = (colIdx >= 0 && colIdx < cells.length)
                                                ? cells[colIdx] : cells[cells.length - 1];
                                            if (target) {
                                                target.scrollIntoView({block: 'center', behavior: 'instant'});
                                                target.click();
                                            }
                                            return;
                                        }
                                    }
                                }""",
                                {"wid": str(worker_id_r)},
                            )
                            await page.wait_for_timeout(500)
                            editor_r = page.locator(f'[data-payxautoid="{editor_autoid_r}"]')
                            try:
                                await editor_r.wait_for(state="visible", timeout=6000)
                                await editor_r.fill(formatted_r)
                            except Exception:
                                await page.keyboard.press("Control+a")
                                await page.keyboard.type(formatted_r, delay=40)
                        else:
                            amount_auto_r = f"paychex.app.payroll.payrollEntry.grid.{worker_id_r}.1.amount.1099-NEC"
                            cell_r = page.locator(f'[data-payxautoid="{amount_auto_r}"]')
                            await page.evaluate(
                                """(sel) => {
                                    const el = document.querySelector(sel);
                                    if (el) el.scrollIntoView({block: 'center', behavior: 'instant'});
                                }""",
                                f'[data-payxautoid="{amount_auto_r}"]',
                            )
                            await page.wait_for_timeout(400)
                            await cell_r.wait_for(state="visible", timeout=8000)
                            await cell_r.click()
                            await page.wait_for_timeout(400)
                            editor_r = page.locator(f'[data-payxautoid="{amount_auto_r}"] input').first
                            try:
                                await editor_r.wait_for(state="visible", timeout=3000)
                                await editor_r.fill(formatted_r)
                            except Exception:
                                await page.keyboard.press("Control+a")
                                await page.keyboard.type(formatted_r, delay=40)

                        await page.keyboard.press("Tab")
                        await page.wait_for_timeout(1500)
                        try:
                            await page.wait_for_load_state("networkidle", timeout=8000)
                        except Exception:
                            pass

                        on_status({
                            "status": "running",
                            "message": f"♻ Refilled ${formatted_r} for {name_r}",
                        })
                    except Exception as e:
                        await snap(f"ERROR_refill_failed_{worker_id_r}")
                        on_status({
                            "status": "driver_error",
                            "driver": name_r,
                            "error": str(e),
                            "message": f"Could not refill {name_r} during verification: {e}",
                        })
                        continue

                # Hard flush after refills — same race as the original loop end
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                await page.wait_for_timeout(8000)

            await snap("all_drivers_done")

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
