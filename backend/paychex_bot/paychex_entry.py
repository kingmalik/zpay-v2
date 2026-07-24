# NOTE: Paychex selectors may need updating — use browser devtools to verify

import asyncio
import json
import os
from typing import Callable
from playwright.async_api import async_playwright, Page, BrowserContext

from backend.paychex_bot.totp import seconds_remaining, totp_now


def _totp_secret_for(company: str) -> str:
    """Authenticator-app MFA secret for this company's Paychex login, if enrolled."""
    return (
        os.environ.get(f"PAYCHEX_TOTP_SECRET_{company.upper()}", "").strip()
        or os.environ.get("PAYCHEX_TOTP_SECRET", "").strip()
    )

PAYCHEX_URL = "https://myapps.paychex.com"


class PaychexSessionDied(Exception):
    """Raised when Paychex bounces the bot back to the login page mid-run.

    Bot must NOT keep typing values into a login form pretending it's a payroll
    grid. Outer wrapper marks the job 'failed' instead of silently 'done'.
    """


def _is_login_url(url: str) -> bool:
    """True if `url` is any Paychex login / static-login surface — i.e. the
    session is dead and the bot is no longer on Pay Entry.

    Notes
    -----
    `myapps.paychex.com/landing_remote/login.do?...` is the POST-AUTH dashboard
    URL (yes, it literally contains "login.do") so we exclude the landing_remote
    path explicitly. Only the real login forms count as "session died":
      - login.flex.paychex.com
      - /login_static/index.html (the username-only screen)
    """
    u = (url or "").lower()
    if "landing_remote/login.do" in u:
        return False
    if "login.flex.paychex.com" in u:
        return True
    if "/login_static/" in u or u.endswith("/login") or "/login?" in u:
        return True
    return False


async def _assert_session_alive(page: Page, where: str) -> None:
    """Raise PaychexSessionDied if Paychex bounced us back to login.

    Called at cheap checkpoints inside the entry loop. `where` is a short label
    (e.g. "before driver 7") that lands in the error message so we can see
    exactly when the session expired.
    """
    if _is_login_url(page.url):
        raise PaychexSessionDied(
            f"Session expired at {where}: page redirected to {page.url[:140]}. "
            f"Recapture cookies and retry."
        )


async def _kendo_set_amount(
    page: Page,
    editor_locator,
    amount: float,
    formatted: str,
    widget_sel: str,
) -> bool:
    """Write an amount into a Paychex Kendo NumericTextBox cell.

    W21 burned 5 attempts using `editor.fill(formatted)` — Playwright wrote
    the value to the underlying <input> and dispatched synthetic input/change
    events, but Kendo NumericTextBox binds its internal model on real
    keydown/keyup events (for the input mask) OR on its widget API
    (`widget.value(n); widget.trigger("change")`). It ignored both
    synthetic events, the bound model stayed empty, no autosave POST fired,
    and snap 37 of job 594f9b91 caught the bot reaching Review & Submit
    with a $0 contribution (submitted total exactly matched the 16 pre-fill
    manual entries Malik typed before the run).

    Strategy: run both paths back-to-back, every call.
      Path A: focus + clear + `page.keyboard.type(delay=50)`.  Real keystroke
              events the input mask handlers actually fire on.
      Path B: `kendo.widgetInstance($el).value(n); .trigger("change")`.
              Forces the bound model and fires the widget-level change event
              Paychex's save observers listen on, even if focus/mask races
              ate any of the keystrokes.

    `widget_sel` is a CSS selector for an element AT or NEAR the Kendo
    widget root. The JS path tries the element, its parent, and its
    closest `.k-numerictextbox` ancestor — covers Acumen (.edit element
    wraps the widget directly) and Maz (widget wraps the cell).

    Returns True iff at least one path reported success. Caller must still
    DOM-verify the saved value — neither path guarantees the server-save
    POST fired.
    """
    typed_ok = False
    try:
        await editor_locator.click(timeout=4000)
        # `fill("")` is flaky on Kendo masks; Ctrl+A → Delete is reliable.
        await page.keyboard.press("Control+a")
        await page.keyboard.press("Delete")
        await page.keyboard.type(formatted, delay=50)
        typed_ok = True
    except Exception:
        pass

    widget_ok = False
    try:
        widget_ok = await page.evaluate(
            """({sel, val}) => {
                if (!window.kendo || !window.kendo.jQuery) return false;
                const $ = window.kendo.jQuery;
                const root = document.querySelector(sel);
                if (!root) return false;
                const candidates = [
                    root,
                    root.parentElement,
                    root.closest && root.closest('.k-numerictextbox'),
                    root.closest && root.closest('[data-role="numerictextbox"]'),
                ].filter(Boolean);
                for (const el of candidates) {
                    const w = window.kendo.widgetInstance($(el));
                    if (w && typeof w.value === 'function') {
                        w.value(Number(val));
                        if (typeof w.trigger === 'function') {
                            w.trigger('change');
                        }
                        return true;
                    }
                }
                return false;
            }""",
            {"sel": widget_sel, "val": amount},
        )
    except Exception:
        widget_ok = False

    return bool(typed_ok or widget_ok)


async def _read_acumen_total(page: Page, worker_id: str) -> float | None:
    """Read the saved 1099-NEC display cell for an Acumen worker.

    This is the cell Paychex updates ONLY after the server-save POST
    round-trips successfully. Used as the per-driver success signal —
    if the bot typed a value but this cell is still $0, the binding
    never reached the server even though the DOM editor accepted input.
    """
    sel = (
        f'[data-payxautoid="paychex.app.payroll.payrollEntry'
        f'.worker.{worker_id}.check.1.row.0.1099NecAmount"]'
    )
    try:
        text = await page.evaluate(
            """(s) => {
                const el = document.querySelector(s);
                return el ? (el.textContent || '').trim() : null;
            }""",
            sel,
        )
        if not text:
            return None
        cleaned = text.replace(",", "").replace("$", "").strip()
        return float(cleaned) if cleaned else 0.0
    except Exception:
        return None


async def run_paychex_entry(
    company: str,                            # "acumen" or "maz"
    username: str,
    password: str,
    drivers: list[dict],                     # [{"worker_id": str, "name": str, "amount": float}]
    on_status: Callable[[dict], None],       # callback for progress updates
    session_cookies: list[dict] | None = None,  # pre-captured browser cookies (skips login)
    headless: bool = True,                   # set False to watch the browser locally
    screenshot_dir: str | None = None,       # if set, save screenshot + DOM dump at each step
    save_cookies: Callable[[list], None] | None = None,  # called with fresh cookies at run end
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
                # Navigate to the MYAPPS portal — that's where Pay Entry lives
                # and where the long-lived session cookie is scoped. The flex
                # SSO token is short-lived; checking session validity against
                # flex.paychex.com (the old approach) produced false "session
                # expired" when the myapps session was still alive (run
                # 722445a7, W21).
                await page.goto(PAYCHEX_URL, wait_until="domcontentloaded")
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass  # proceed — some SPAs stay "loading" forever

                # Element-based session check: poll for either a login form
                # (any password input / #login-username) or a logged-in signal
                # (Begin button / portal header). URL matching alone is
                # unreliable — landing_remote/login.do appears in BOTH states.
                for _sess_i in range(8):  # up to ~24s
                    state = await page.evaluate(
                        """() => ({
                            loginForm: !!document.querySelector('#login-username')
                                || !!document.querySelector('input[type="password"]'),
                            beginBtn: !!Array.from(document.querySelectorAll('button, a')).find(
                                e => (e.textContent || '').trim().startsWith('Begin')),
                            portalHeader: !!document.querySelector('png-header-icons'),
                        })"""
                    )
                    if state["loginForm"]:
                        break
                    if state["beginBtn"] or state["portalHeader"]:
                        session_valid = True
                        break
                    await page.wait_for_timeout(3000)

                current_url = page.url
                if session_valid:
                    on_status({"status": "running", "message": f"Session loaded (url={current_url[:80]}) — navigating to payroll..."})
                else:
                    on_status({"status": "running", "message": f"Session expired (url={current_url[:80]}) — falling back to username/password login..."})
                    session_cookies = None  # force normal login flow below

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
                # STEP 3: Enter password — OR detect that SSO already let us in.
                # Run 722445a7 (W21): after the username submit, Paychex
                # navigated straight to the myapps portal (the lingering myapps
                # session authenticated us) and no password field ever appeared.
                # The old hard wait for #login-password timed out and killed
                # the run. Poll for either outcome instead.
                # ----------------------------------------------------------------
                password_ready = False
                sso_logged_in = False
                for _pw_i in range(8):  # up to ~24s
                    try:
                        if await page.locator('#login-password').is_visible():
                            password_ready = True
                            break
                    except Exception:
                        pass
                    state = await page.evaluate(
                        """() => ({
                            anyPw: !!document.querySelector('input[type="password"]'),
                            beginBtn: !!Array.from(document.querySelectorAll('button, a')).find(
                                e => (e.textContent || '').trim().startsWith('Begin')),
                            portalHeader: !!document.querySelector('png-header-icons'),
                        })"""
                    )
                    if not state["anyPw"] and (state["beginBtn"] or state["portalHeader"]):
                        sso_logged_in = True
                        break
                    await page.wait_for_timeout(3000)

                if not password_ready and not sso_logged_in:
                    await snap("ERROR_login_password_timeout")
                    raise Exception(
                        f"Login stuck after username submit: no password field and "
                        f"no dashboard detected. URL: {page.url}"
                    )

                if sso_logged_in:
                    on_status({"status": "running", "message": "SSO session still active — password not needed."})

                if password_ready:
                    on_status({"status": "running", "message": "Entering password..."})
                    await page.fill('#login-password', password)
                    await page.click('#login-button')  # same button ID, now says "Log in"

                    # Give the page a beat to render the next state, then capture it.
                    # Diagnosability: this is the first datapoint we get post-submit
                    # and is the difference between "MFA new selector" and
                    # "credentials rejected" debugging next time the bot fails here.
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=8000)
                    except Exception:
                        pass
                    await snap("after_password_submit")

                    on_status({"status": "running", "message": "Sign-in submitted, checking for MFA..."})

                    # ------------------------------------------------------------
                    # STEP 4: Handle MFA / OTP prompt (password path only)
                    #
                    # Paychex used to show a delivery-method picker (text vs
                    # call) before the OTP entry, gated by
                    # `#otp-delivery-method-next-button`. As of W21 (2026-06-16)
                    # they changed the flow: most accounts now skip the picker
                    # and land directly on the OTP entry screen
                    # (`#one-time-password`). The old code waited 8s for the
                    # picker, never saw it, fell through to the still-on-login
                    # check, and silently failed the MFA path.
                    #
                    # New flow: race both selectors. Whichever appears first
                    # wins. If the picker shows up, do the legacy dance. If the
                    # OTP input shows up directly, skip straight to waiting on
                    # the user to type the code.
                    # ------------------------------------------------------------
                    try:
                        # Race: picker vs OTP-direct, up to 15s.
                        try:
                            picker_loc = page.locator('#otp-delivery-method-next-button')
                            otp_loc = page.locator('#one-time-password')
                            # Wait for EITHER selector to become visible. Playwright's
                            # `wait_for(state="visible")` per-locator doesn't race, so
                            # poll with short steps.
                            saw = None
                            for _ in range(30):  # 30 × 500ms = 15s
                                if await otp_loc.is_visible():
                                    saw = "otp_direct"
                                    break
                                if await picker_loc.is_visible():
                                    saw = "picker"
                                    break
                                await page.wait_for_timeout(500)
                            if saw is None:
                                raise Exception("Neither MFA picker nor OTP input appeared within 15s")
                        except Exception:
                            raise

                        if saw == "picker":
                            on_status({"status": "mfa_required", "message": "MFA required — selecting text delivery..."})
                            try:
                                await page.click('#otp-text')  # text message radio
                            except Exception:
                                pass
                            await page.click('#otp-delivery-method-next-button')
                            # Now wait for the OTP input
                            await page.wait_for_selector('#one-time-password', timeout=15000)
                        # else: saw == "otp_direct" — already there, no action needed.

                        # ----------------------------------------------------
                        # TOTP auto-answer (authenticator-app MFA, no human).
                        # Only fires when a secret is enrolled + configured;
                        # otherwise the manual SMS path below is unchanged.
                        # ----------------------------------------------------
                        otp_autofilled = False
                        totp_secret = _totp_secret_for(company)
                        if totp_secret:
                            try:
                                if seconds_remaining() < 4:
                                    # Don't submit a code about to expire mid-flight.
                                    await page.wait_for_timeout(4500)
                                code = totp_now(totp_secret)
                                on_status({"status": "running", "message": "MFA — answering with authenticator code..."})
                                await page.fill('#one-time-password', code)
                                # Best-effort device trust to reduce future prompts.
                                try:
                                    remember = page.locator('input[type="checkbox"]').first
                                    if await remember.is_visible():
                                        await remember.check()
                                except Exception:
                                    pass
                                submitted = False
                                for sel in ('#otp-submit-button', '#login-button', 'button[type="submit"]'):
                                    try:
                                        if await page.locator(sel).is_visible():
                                            await page.click(sel)
                                            submitted = True
                                            break
                                    except Exception:
                                        continue
                                if not submitted:
                                    await page.press('#one-time-password', 'Enter')
                                await page.wait_for_selector('[id*="home"], [class*="dashboard"], nav[class*="nav"]', timeout=20000)
                                otp_autofilled = True
                                on_status({"status": "running", "message": "MFA passed automatically (authenticator)."})
                            except Exception:
                                await snap("totp_autofill_failed")
                                on_status({"status": "running", "message": "Auto-MFA failed — falling back to manual code entry..."})

                        if not otp_autofilled:
                            on_status({
                                "status": "mfa_required",
                                "message": "MFA code sent to your phone — enter it in Z-Pay to continue"
                            })
                            # Wait up to 120s for user to complete MFA
                            await page.wait_for_selector('[id*="home"], [class*="dashboard"], nav[class*="nav"]', timeout=120000)
                    except Exception:
                        pass  # No MFA prompt or already past it — proceed to dashboard check

                    # ------------------------------------------------------------
                    # STEP 5: Verify login succeeded (password path only)
                    # ------------------------------------------------------------
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
                            await snap("ERROR_still_on_login")
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
            # ----------------------------------------------------------------
            # STEP 6a: Dismiss workers' comp coverage popup (Acumen path)
            #
            # W23 (2026-06-21): Paychex added a new modal on the dashboard
            # that asks "Do you have workers' comp coverage?" with three
            # buttons: "Yes", "No", "Ask me later". When present, this modal
            # overlays the Begin button and causes the bot to raise
            # "Could not find 'Begin' / 'Start payroll' button."
            #
            # Strategy: look for the popup before the Begin-button search.
            #   1. Click "Ask me later" if available — safest choice; makes no
            #      workers' comp declaration on the company's behalf, and the
            #      popup will be dismissed again if it reappears next run.
            #   2. Fall back to "No" if "Ask me later" isn't found — Malik
            #      confirmed the company does not have workers' comp (W21).
            #   3. If neither button is found (popup not present), continue
            #      silently — do NOT raise.
            #   4. If popup IS found but dismissal fails, raise — we need a
            #      snap so we can see what changed in the UI.
            #
            # Scope: Acumen-only surface (myapps.paychex.com dashboard).
            # Maz uses flex.paychex.com which does not show this modal.
            # This block runs unconditionally regardless of is_acumen because
            # the company variable is set later — but the modal only lives
            # on the myapps dashboard, so it simply won't match for Maz.
            # ----------------------------------------------------------------
            on_status({"status": "running", "message": "Checking for workers' comp coverage popup..."})
            await snap("workers_comp_popup_before")
            _popup_dismissed = False
            try:
                # Multiple selectors for the popup heading — Paychex may use
                # a <dialog>, a role=dialog region, or just a heading element.
                _popup_heading_selectors = [
                    'text="Do you have workers\' comp coverage?"',
                    ':has-text("Do you have workers\'") :has-text("comp coverage")',
                    '[role="dialog"] :has-text("workers")',
                    'h1:has-text("workers")',
                    'h2:has-text("workers")',
                    'h3:has-text("workers")',
                ]
                _popup_visible = False
                for _sel in _popup_heading_selectors:
                    try:
                        _loc = page.locator(_sel).first
                        if await _loc.is_visible(timeout=800):
                            _popup_visible = True
                            break
                    except Exception:
                        pass

                if _popup_visible:
                    on_status({"status": "running", "message": "Workers' comp popup detected — dismissing..."})
                    # Try "Ask me later" first (link-style button on left)
                    _dismissed = False
                    _ask_later_selectors = [
                        'button:has-text("Ask me later")',
                        'a:has-text("Ask me later")',
                        '[role="button"]:has-text("Ask me later")',
                        ':has-text("Ask me later")',
                    ]
                    for _sel in _ask_later_selectors:
                        try:
                            _btn = page.locator(_sel).first
                            if await _btn.is_visible(timeout=1000):
                                await _btn.click(timeout=3000)
                                _dismissed = True
                                break
                        except Exception:
                            pass

                    if not _dismissed:
                        # Fall back to "No" — truthful (no workers' comp)
                        _no_selectors = [
                            'button:has-text("No")',
                            'a:has-text("No")',
                            '[role="button"]:has-text("No")',
                        ]
                        for _sel in _no_selectors:
                            try:
                                _btn = page.locator(_sel).first
                                if await _btn.is_visible(timeout=1000):
                                    await _btn.click(timeout=3000)
                                    _dismissed = True
                                    break
                            except Exception:
                                pass

                    if not _dismissed:
                        await snap("ERROR_workers_comp_popup_not_dismissed")
                        raise Exception(
                            "Workers' comp coverage popup was detected but neither "
                            "'Ask me later' nor 'No' button could be clicked. "
                            "Paychex may have changed the modal UI — check snap for details."
                        )

                    # Brief settle after dismiss
                    await page.wait_for_timeout(800)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        pass
                    _popup_dismissed = True
                    on_status({"status": "running", "message": "Workers' comp popup dismissed."})
                else:
                    on_status({"status": "running", "message": "No workers' comp popup — continuing."})

            except Exception as _popup_err:
                # Re-raise only if we know the popup was there and we failed to dismiss.
                # If this is a detection failure (popup not present), the error path
                # won't reach here — those are swallowed in the per-selector try/excepts.
                raise _popup_err

            await snap("workers_comp_popup_after")

            on_status({"status": "running", "message": "Looking for Current Payroll → Begin button..."})

            # Accept Resume too: after the first bot run navigated past
            # the Start Payroll modal, Paychex flips the dashboard CTA from
            # "Begin" to "Resume" — same destination (Pay Entry grid), just
            # a different label. Job f33cb7e9: bot failed with diagnostic
            # showing button_texts=["Resume", "View Payroll Center", ...].
            # View Payroll Center is the fallback for that case.
            begin_selector = (
                'button:has-text("Begin"), '
                'a:has-text("Begin"), '
                'button:has-text("Resume"), '
                'a:has-text("Resume"), '
                'button:has-text("Start payroll"), '
                'a:has-text("Start payroll"), '
                'button:has-text("Continue"), '
                'a:has-text("Continue"), '
                'button:has-text("View Payroll Center"), '
                'a:has-text("View Payroll Center")'
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

            # Track per-run failure stats so we can bail loudly if the session
            # silently dies mid-loop. Without this, 40 swallowed driver_errors
            # would still mark the run "done" and look like a clean fill.
            _consecutive_failures = 0
            _total_failures = 0

            for i, driver in enumerate(drivers):
                worker_id = driver["worker_id"]
                name = driver["name"]
                amount = driver["amount"]
                formatted_amount = f"{amount:.2f}"

                # Cheap session-alive checkpoint before every driver. If Paychex
                # bounced us back to login (~30min idle timeout on Acumen), the
                # search/fill operations below would all silently noop and we'd
                # still report progress at 46/46 — the exact bug from W20 FA.
                await _assert_session_alive(page, f"before driver {i+1}/{len(drivers)} ({name})")

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
                    if is_acumen:
                        on_status({
                            "status": "running",
                            "progress": i + 1,
                            "total": len(drivers),
                            "current_driver": name,
                            "message": f"Searching {name}...",
                        })
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

                    # Let the grid re-render after the filter. The old code
                    # used a flat 1500ms wait; if Kendo's loading mask was
                    # still up (slow network) the per-driver `cell_in_dom`
                    # check below would fire one frame too early and raise
                    # `cell_not_in_dom`. W22 (2026-06-17) lost workers 1025
                    # and 1138 to that race — snap evidence had both grids
                    # showing "1 of 1" search result one second later.
                    #
                    # New approach: wait for Kendo's loading mask to clear
                    # if present, then a short settling pause. Bounded so a
                    # broken grid still raises within a few seconds.
                    try:
                        await page.wait_for_function(
                            """() => {
                                const mask = document.querySelector(
                                    '.k-loading-mask, .k-i-loading, [class*="loading-mask"]'
                                );
                                if (!mask) return true;
                                const rect = mask.getBoundingClientRect();
                                return rect.width === 0 && rect.height === 0;
                            }""",
                            timeout=6000,
                        )
                    except Exception:
                        pass
                    await page.wait_for_timeout(600)

                    # =========================================================
                    # COMPANY-AWARE row location + cell click + input fill
                    # =========================================================
                    filled = False

                    if is_acumen:
                        # ----- ACUMEN (Kendo UI grid) ------------------------
                        # Flow (post-W21 iteration 2):
                        # The per-row Actions flyout proved a check ALREADY
                        # exists for every worker (menu shows Edit full check /
                        # Delete check — captured in DIAG_acumen_flyout_open
                        # snaps, job 067ad02b). So no Add Check step is needed.
                        # The W21 run-1 bug was clicking by COLUMN INDEX (wrong
                        # td — 1099-NEC columns sit off-viewport right) and
                        # waiting for a ".edit"-suffixed autoid that never
                        # exists in Paychex's DOM.
                        #
                        # 1. Defensive: close any leftover flyout/overlay from a
                        #    previous driver (a stuck-open menu chain-poisoned
                        #    drivers 2-5 in run 2).
                        # 2. Click the 1099-NEC Amount cell BY AUTOID with
                        #    horizontal scroll-into-view, then wait for an input
                        #    INSIDE the cell (Maz pattern). Single click, then
                        #    dblclick fallback.
                        # 3. Fallback: open the row flyout -> "Edit full check"
                        #    (autoid ...1.0.checkDetails) -> DIAG-snap the
                        #    editor so the next iteration can automate it.

                        cell_auto = (
                            f"paychex.app.payroll.payrollEntry.worker.{worker_id}"
                            f".check.1.row.0.1099NecAmount"
                        )
                        flyout_auto = (
                            f"paychex.app.payroll.payrollEntry.worker.{worker_id}"
                            f".1.0.checkActions-flyout-button"
                        )
                        check_details_auto = (
                            f"paychex.app.payroll.payrollEntry.worker.{worker_id}"
                            f".1.0.checkDetails"
                        )

                        # ── Step 0: clear any leftover overlay state ─────────
                        try:
                            await page.keyboard.press("Escape")
                            stale_close = page.locator(
                                '[data-payxautoid$="powerGridCheckActionsFlyout.header.close"]'
                            ).first
                            if await stale_close.is_visible():
                                await stale_close.click(timeout=2000)
                                await page.wait_for_timeout(300)
                        except Exception:
                            pass

                        # ── Step 1: confirm the cell autoid is in the DOM ────
                        # Retry-with-search-resubmit if the grid hadn't fully
                        # rendered yet. W22 (2026-06-17) lost workers 1025 and
                        # 1138 to a single-shot check here; both rows showed
                        # up in the grid one second later.
                        cell_in_dom = False
                        for _attempt in range(3):
                            cell_in_dom = await page.evaluate(
                                """(sel) => !!document.querySelector(sel)""",
                                f'[data-payxautoid="{cell_auto}"]',
                            )
                            if cell_in_dom:
                                break
                            if _attempt < 2:
                                # Resubmit the search — if Paychex dropped the
                                # filter (rare), this re-applies it. If the
                                # grid was just slow, this gives it another
                                # ~1.5s to render.
                                try:
                                    await search_box.click(timeout=2000)
                                    await page.keyboard.press("Control+a")
                                    await page.keyboard.press("Delete")
                                    await search_box.type(str(worker_id), delay=35)
                                    await page.wait_for_timeout(400)
                                    try:
                                        await search_btn.click(timeout=2000)
                                    except Exception:
                                        await search_box.press("Enter")
                                except Exception:
                                    pass
                                try:
                                    await page.wait_for_function(
                                        """() => {
                                            const mask = document.querySelector(
                                                '.k-loading-mask, .k-i-loading, [class*="loading-mask"]'
                                            );
                                            if (!mask) return true;
                                            const rect = mask.getBoundingClientRect();
                                            return rect.width === 0 && rect.height === 0;
                                        }""",
                                        timeout=4000,
                                    )
                                except Exception:
                                    pass
                                await page.wait_for_timeout(600)

                        if not cell_in_dom:
                            # Last-ditch: JS-walk every k-master-row looking
                            # for one whose textContent contains the worker
                            # id. The verification refill pass uses this same
                            # approach successfully when the autoid path fails.
                            found_via_walk = await page.evaluate(
                                """(wid) => {
                                    const rows = Array.from(document.querySelectorAll('tr.k-master-row'));
                                    for (const r of rows) {
                                        if ((r.textContent || '').includes(wid)) {
                                            r.scrollIntoView({block: 'center', behavior: 'instant'});
                                            return true;
                                        }
                                    }
                                    return false;
                                }""",
                                str(worker_id),
                            )
                            if found_via_walk:
                                await page.wait_for_timeout(400)
                                cell_in_dom = await page.evaluate(
                                    """(sel) => !!document.querySelector(sel)""",
                                    f'[data-payxautoid="{cell_auto}"]',
                                )

                        if not cell_in_dom:
                            await snap(f"ERROR_acumen_cell_not_in_dom_{worker_id}")
                            raise Exception(
                                f"Acumen: cell autoid {cell_auto} not in DOM after search "
                                f"for {name}. Search may not have filtered to this worker."
                            )

                        # ── Step 2: click the amount cell to open its editor ─
                        # PROVEN via live introspection (2026-06-10): clicking
                        # the cell opens an editor input rendered as a SEPARATE
                        # element carrying the autoid suffix ".edit"
                        #   ...1099NecAmount.edit  (class "k-input paychex-incell")
                        # It is NOT a child of the cell div — earlier code waited
                        # for `[cell] input` (no match) or for a ".edit" autoid
                        # while clicking the wrong (column-index) cell, so the
                        # editor never opened. Click the cell div, fall back to
                        # clicking the parent <td> (the key-nav cell that owns
                        # the edit handler), and wait for the ".edit" element.
                        edit_auto = f"{cell_auto}.edit"
                        cell_div = page.locator(f'[data-payxautoid="{cell_auto}"]').first
                        cell_td = page.locator(f'td:has([data-payxautoid="{cell_auto}"])').first
                        editor = page.locator(f'[data-payxautoid="{edit_auto}"]').first

                        on_status({
                            "status": "running",
                            "progress": i + 1,
                            "total": len(drivers),
                            "current_driver": name,
                            "message": f"Clicking 1099-NEC Amount cell for {name}...",
                        })
                        try:
                            await cell_div.scroll_into_view_if_needed(timeout=4000)
                            await page.wait_for_timeout(300)
                        except Exception:
                            pass

                        editor_appeared = False
                        # Escalating open attempts, each followed by a wait for
                        # the ".edit" editor input to become visible.
                        open_attempts = [
                            ("cell_div.click",  lambda: cell_div.click(timeout=4000)),
                            ("cell_td.click",   lambda: cell_td.click(timeout=4000)),
                            ("cell_td.dblclick", lambda: cell_td.dblclick(timeout=4000)),
                        ]
                        for label, action in open_attempts:
                            try:
                                await action()
                            except Exception:
                                pass
                            try:
                                await editor.wait_for(state="visible", timeout=3000)
                                editor_appeared = True
                                break
                            except Exception:
                                if i < 3:
                                    await snap(f"DIAG_acumen_after_{label}_{worker_id}")

                        if not editor_appeared:
                            await snap(f"ERROR_acumen_editor_never_appeared_{worker_id}")
                            try:
                                await page.keyboard.press("Escape")
                            except Exception:
                                pass
                            raise Exception(
                                f"Acumen: '.edit' editor never appeared for {name} "
                                f"(autoid {edit_auto}) after cell click, td click, and "
                                f"td dblclick."
                            )

                        if i == 0:
                            await snap(f"acumen_editor_open_{worker_id}")

                        on_status({
                            "status": "running",
                            "progress": i + 1,
                            "total": len(drivers),
                            "current_driver": name,
                            "message": f"Editor input appeared, filling ${formatted_amount}...",
                        })
                        # Kendo-aware fill: real keystrokes + widget API.
                        # editor.fill() looks successful but never binds the
                        # NumericTextBox model — see _kendo_set_amount docstring.
                        filled = await _kendo_set_amount(
                            page=page,
                            editor_locator=editor,
                            amount=amount,
                            formatted=formatted_amount,
                            widget_sel=f'[data-payxautoid="{edit_auto}"]',
                        )

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

                    # Commit the edit by clicking empty Kendo grid space
                    # BELOW the data row — Malik's actual manual gesture,
                    # captured in screen recording (Jun 16, frames 18→20):
                    # he types the amount, clicks ~100px below the row in
                    # the empty gray grid area, and the Total Amount column
                    # rolls up immediately (proves the server-save fired).
                    #
                    # Why not just click search bar / another element:
                    #   - Search bar click (job 3b73e9a6): cell DOM filled
                    #     but server never saved, batch came back as "Begin"
                    #   - Hardcoded (640, 620) click (job 9da873fc): hit a
                    #     virtualized Kendo row that ate the focus, every
                    #     cell came back empty
                    #   - Enter + synthetic blur (job a9c5a89b): tripped the
                    #     "Unsaved Changes" navigation guard modal
                    #
                    # Dynamic coordinates: locate the just-edited row's
                    # bounding box, click at (row_center_x, row_bottom + 100).
                    # That's "below the data row, in empty grid body" — same
                    # spot Malik clicks. Falls back to a hardcoded reasonable
                    # default if box lookup fails.
                    if is_acumen:
                        click_x, click_y = 640, 540  # bot viewport defaults
                        try:
                            row_loc = page.locator(
                                f'tr.k-master-row:has([data-payxautoid="{cell_auto}"])'
                            ).first
                            row_box = await row_loc.bounding_box(timeout=2000)
                            if row_box:
                                click_x = int(row_box["x"] + row_box["width"] / 2)
                                click_y = int(row_box["y"] + row_box["height"] + 100)
                        except Exception:
                            pass
                        try:
                            await page.mouse.click(click_x, click_y)
                        except Exception:
                            try:
                                await page.keyboard.press("Tab")
                            except Exception:
                                pass
                        # Defensive: dismiss the dirty-state guard if it fires.
                        try:
                            stay_btn = page.locator(
                                'button:has-text("Stay")'
                            ).first
                            if await stay_btn.is_visible(timeout=1000):
                                await stay_btn.click(timeout=2000)
                        except Exception:
                            pass
                        on_status({
                            "status": "running",
                            "progress": i + 1,
                            "total": len(drivers),
                            "current_driver": name,
                            "message": f"Committed entry, waiting for save...",
                        })
                    else:
                        await page.keyboard.press("Tab")  # Maz path — unchanged
                    # Paychex autosaves each entry async (debounced). Wait for the
                    # save POST to fire and settle before moving on — otherwise the
                    # final driver's save can be cut off when the browser closes.
                    await page.wait_for_timeout(1200)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass

                    # -- Verify the entry persisted (company-aware) ---------
                    # Read the display cell — Paychex only updates it after the
                    # server-save POST round-trips. If it doesn't match what we
                    # typed, the Kendo binding silently failed (W21 fail mode:
                    # bot reported success on 44 drivers, server saved 0 of
                    # them, snap 37 of job 594f9b91 caught it at Review &
                    # Submit). Retry once via widget API + click-out, then
                    # raise — the per-driver exception path increments the
                    # consecutive-failure streak guard, which aborts the run
                    # after 5 silent failures instead of mangling 46.
                    async def _read_display() -> float | None:
                        try:
                            if is_acumen:
                                return await _read_acumen_total(page, str(worker_id))
                            total_text = await page.locator(
                                f'[data-payxautoid="paychex.app.payroll.payrollEntry.grid.{worker_id}.1.total"]'
                            ).inner_text()
                            cleaned = total_text.replace(",", "").replace("$", "").strip()
                            return float(cleaned) if cleaned else 0.0
                        except Exception:
                            return None

                    actual_val = await _read_display()
                    verified = (
                        actual_val is not None
                        and abs(actual_val - amount) < 0.01
                    )

                    # Acumen-only hardening: retry-then-raise. The Kendo binding
                    # fix is for Acumen specifically — Maz was shipping working,
                    # so Maz keeps the original soft-warn behavior and lets the
                    # end-of-loop verification pass catch any flake.
                    if is_acumen and not verified:
                        # ONE inline retry — widget API directly, no UI dance.
                        # If the cell display reads $0, neither keystrokes nor
                        # the widget call from the first pass bound the model.
                        # Most common cause: focus race between the cell click
                        # and the editor opening. Force the widget value
                        # without re-clicking the cell, then re-commit.
                        await snap(f"RETRY_unverified_{worker_id}")
                        try:
                            await page.evaluate(
                                """({sel, val}) => {
                                    if (!window.kendo || !window.kendo.jQuery) return false;
                                    const $ = window.kendo.jQuery;
                                    const root = document.querySelector(sel);
                                    if (!root) return false;
                                    const candidates = [
                                        root,
                                        root.parentElement,
                                        root.closest && root.closest('.k-numerictextbox'),
                                        root.closest && root.closest('[data-role="numerictextbox"]'),
                                    ].filter(Boolean);
                                    for (const el of candidates) {
                                        const w = window.kendo.widgetInstance($(el));
                                        if (w && typeof w.value === 'function') {
                                            w.value(Number(val));
                                            if (typeof w.trigger === 'function') w.trigger('change');
                                            // Also dispatch a native change on the underlying
                                            // input so any Angular-side listener picks it up.
                                            const inp = el.querySelector && el.querySelector('input');
                                            if (inp) {
                                                inp.dispatchEvent(new Event('input', {bubbles: true}));
                                                inp.dispatchEvent(new Event('change', {bubbles: true}));
                                                inp.dispatchEvent(new FocusEvent('blur', {bubbles: true}));
                                            }
                                            return true;
                                        }
                                    }
                                    return false;
                                }""",
                                {"sel": f'[data-payxautoid="{edit_auto}"]', "val": amount},
                            )
                        except Exception:
                            pass
                        try:
                            await page.mouse.click(click_x, click_y)
                        except Exception:
                            pass
                        await page.wait_for_timeout(1500)
                        try:
                            await page.wait_for_load_state("networkidle", timeout=8000)
                        except Exception:
                            pass

                        actual_val = await _read_display()
                        verified = (
                            actual_val is not None
                            and abs(actual_val - amount) < 0.01
                        )

                    if is_acumen and not verified:
                        await snap(f"FAIL_unverified_{worker_id}")
                        # Raise — exception path increments the streak guard.
                        # Continuing silently is the failure mode that produced
                        # the $0 Review & Submit screen in W21.
                        raise Exception(
                            f"Save did not persist for {name} (worker_id "
                            f"{worker_id}): typed ${formatted_amount}, "
                            f"display cell reads ${actual_val if actual_val is not None else '?'}. "
                            f"Kendo binding or autosave POST failed."
                        )

                    # Maz path (or any non-acumen path) keeps the original
                    # soft-warn behavior — the end-of-loop verification pass
                    # handles refills there.
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
                    # Successful driver — reset the consecutive-failure streak.
                    _consecutive_failures = 0

                except PaychexSessionDied:
                    # Session bounced us back to login mid-loop. Re-raise so the
                    # outer wrapper marks the job FAILED instead of continuing
                    # to silently noop on the remaining drivers.
                    raise

                except Exception as e:
                    _consecutive_failures += 1
                    _total_failures += 1
                    on_status({
                        "status": "driver_error",
                        "driver": name,
                        "error": str(e),
                        "message": f"Failed to enter pay for {name}: {e}"
                    })

                    # Overlay hygiene: a stuck-open flyout/menu/dialog blocks
                    # every subsequent click (run 067ad02b: one open menu
                    # chain-failed drivers 2-5 on search-box clicks). Close
                    # anything that might be open before the next driver.
                    if is_acumen:
                        try:
                            await page.keyboard.press("Escape")
                            stale_close = page.locator(
                                '[data-payxautoid$="powerGridCheckActionsFlyout.header.close"]'
                            ).first
                            if await stale_close.is_visible():
                                await stale_close.click(timeout=2000)
                        except Exception:
                            pass

                    # If the session died between drivers, the next operations
                    # would all fail too — bail loudly instead of producing a
                    # fake 46/46.
                    try:
                        await _assert_session_alive(page, f"after driver {i+1} error")
                    except PaychexSessionDied:
                        raise

                    # Streak guard: if N drivers in a row fail on a live session,
                    # something structural is broken (selectors stale, modal
                    # overlay blocking clicks, etc). Stop early; better to flag
                    # 5 bad drivers than to silently mangle 46.
                    if _consecutive_failures >= 5:
                        raise Exception(
                            f"5 consecutive drivers failed (last: {name}). "
                            f"Aborting before more entries go bad. "
                            f"Last error: {str(e)[:300]}"
                        )

                    # Otherwise continue with the next driver
                    continue

            # ----------------------------------------------------------------
            # Final autosave confirmation (Maz path only)
            # ----------------------------------------------------------------
            # Paychex debounces autosave POSTs. networkidle is unreliable as a
            # "server received it" signal — it fires when the browser's network
            # stack goes quiet, but the debounce timer may not have fired yet,
            # so the save POST is queued but not sent.
            #
            # Instead, after the loop ends we:
            #   1. Wait for networkidle (catches the common case quickly).
            #   2. Re-locate the last driver's total cell from the DOM and
            #      compare it against the expected value. The total cell is
            #      server-authoritative: Paychex only updates it after the save
            #      POST round-trips. If it matches, we are done. If not, we
            #      wait 5 s and retry up to 3 times.
            #   3. If still mismatched after all retries, we fall through to the
            #      existing verification pass, which will refill the driver.
            #
            # This makes the first try correct in the normal case. The
            # verification pass below remains as a safety net.
            on_status({
                "status": "running",
                "message": "Final autosave confirmation — confirming last entry reached Paychex server...",
            })
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            # Give the debounce timer at least one full cycle before DOM-reading.
            await page.wait_for_timeout(2000)

            # DOM-verify: read the last driver's total cell and confirm the server
            # accepted it. We only do this on the Maz path (is_acumen is False here).
            if drivers and not is_acumen:
                last_driver = drivers[-1]
                last_wid = last_driver["worker_id"]
                last_name = last_driver["name"]
                last_expected = float(last_driver["amount"])
                last_total_auto = (
                    f"paychex.app.payroll.payrollEntry.grid.{last_wid}.1.total"
                )

                _dom_confirmed = False
                for _attempt in range(3):
                    try:
                        # Bring the last driver's row into view via search so the
                        # total cell is rendered in the virtualized grid.
                        _sb = page.locator(
                            '[data-payxautoid="paychex.app.payroll.payrollEntry.search.searchBar.input"]'
                        )
                        await _sb.click()
                        await page.keyboard.press("Control+a")
                        await page.keyboard.press("Delete")
                        await _sb.type(str(last_wid), delay=35)
                        await page.wait_for_timeout(600)
                        try:
                            await page.locator(
                                '[data-payxautoid="paychex.app.payroll.payrollEntry.search.searchButton"]'
                            ).click(timeout=3000)
                        except Exception:
                            await _sb.press("Enter")
                        await page.wait_for_timeout(1200)

                        _total_text = await page.locator(
                            f'[data-payxautoid="{last_total_auto}"]'
                        ).inner_text(timeout=6000)
                        _cleaned = _total_text.replace(",", "").replace("$", "").strip()
                        _actual = float(_cleaned or 0)

                        if abs(_actual - last_expected) < 0.01:
                            _dom_confirmed = True
                            on_status({
                                "status": "running",
                                "message": (
                                    f"Server confirmed final entry for {last_name} "
                                    f"(${last_expected:.2f}) on attempt {_attempt + 1}."
                                ),
                            })
                            break
                        else:
                            on_status({
                                "status": "running",
                                "message": (
                                    f"Final entry not yet confirmed for {last_name} "
                                    f"(expected ${last_expected:.2f}, got ${_actual:.2f}) "
                                    f"— waiting 5 s before retry {_attempt + 2}/3..."
                                ),
                            })
                            await page.wait_for_timeout(5000)
                    except Exception as _dom_err:
                        on_status({
                            "status": "running",
                            "message": (
                                f"DOM-verify attempt {_attempt + 1} failed ({str(_dom_err)[:80]}) "
                                f"— verification pass will cover this."
                            ),
                        })
                        await page.wait_for_timeout(5000)

                if not _dom_confirmed:
                    # Final fallback wait so the verification pass has the best
                    # possible chance of reading stable server state.
                    await page.wait_for_timeout(3000)

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
                                # Kendo-aware fill (same fix as main loop).
                                await _kendo_set_amount(
                                    page=page,
                                    editor_locator=editor_r,
                                    amount=amount_r,
                                    formatted=formatted_r,
                                    widget_sel=f'[data-payxautoid="{editor_autoid_r}"]',
                                )
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

                        # Same commit pattern as the per-driver loop — click
                        # out to empty grid area so Kendo's blur fires without
                        # tripping the dirty-state guard.
                        if is_acumen:
                            try:
                                await page.mouse.click(640, 620)
                            except Exception:
                                pass
                            try:
                                stay_btn = page.locator(
                                    'button:has-text("Stay")'
                                ).first
                                if await stay_btn.is_visible(timeout=1000):
                                    await stay_btn.click(timeout=2000)
                            except Exception:
                                pass
                        else:
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
            # STEP 9: Persist the batch by navigating to Review & Submit
            # ----------------------------------------------------------------
            # W21 FA bug: stopping on Pay Entry left the batch as a discarded
            # draft. Malik returned to the dashboard and saw the "Begin" button
            # again (i.e. no work registered) — Paychex Flex only marks a batch
            # as "in progress" once the user navigates past Pay Entry.
            #
            # Clicking the Review & Submit button (the nextViewButton autoid
            # visible in the Pay Entry header) advances the wizard to step 2
            # of the quick-payroll flow. That transition flushes any pending
            # Kendo edits server-side AND flips the dashboard to show "Resume"
            # instead of "Begin." We do NOT click final submit — we stop at the
            # review screen so Malik can eyeball totals and click Submit himself.
            if is_acumen:
                on_status({
                    "status": "running",
                    "message": "Navigating to Review & Submit to persist the batch...",
                })
                review_btn = page.locator(
                    '[data-payxautoid="paychex.app.payroll.quickPayroll.headerInformation.nextViewButton"]'
                )
                try:
                    await review_btn.wait_for(state="visible", timeout=10000)
                    await review_btn.click(timeout=8000)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=20000)
                    except Exception:
                        pass
                    await page.wait_for_timeout(2000)
                    await snap("review_submit_reached")
                except Exception as rs_err:
                    # Best-effort — if the button moved or the click failed,
                    # surface it as a warning, don't kill the whole run.
                    await snap("WARN_review_submit_click_failed")
                    on_status({
                        "status": "running",
                        "message": (
                            f"Could not click Review & Submit ({str(rs_err)[:120]}); "
                            f"entries may need a manual Resume to persist."
                        ),
                    })

            # ----------------------------------------------------------------
            # STEP 10: Done — DO NOT submit or finalize
            # Leave the batch on the Review & Submit screen. The user reviews
            # totals and clicks Submit themselves.
            # ----------------------------------------------------------------
            on_status({
                "status": "done",
                "message": "All entries complete. Log into Paychex to review and submit."
            })

        finally:
            # Re-save the CURRENT cookies before closing. Paychex rotates
            # session cookies during use — the originally-captured set stops
            # authenticating after a run (run 722445a7: cookies that worked at
            # 13:57 were rejected at 14:08). Harvesting at run end keeps the
            # stored session rolling forward so the next run doesn't need a
            # fresh manual capture.
            if save_cookies is not None:
                try:
                    fresh_cookies = await context.cookies()
                    if fresh_cookies:
                        save_cookies(fresh_cookies)
                except Exception:
                    pass  # cookie refresh is best-effort; never mask the real result
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
