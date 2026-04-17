"""
FirstAlt driver creation via Playwright automation.

Creates a new driver in the spguardian.firstalt.com portal because
FirstAlt has no public API for driver creation.

Usage:
    from backend.services.firstalt_playwright import create_driver_playwright
    result = create_driver_playwright(name="John Doe", email="john@example.com", phone="2065551234")

Environment variables required:
    FIRSTALT_USERNAME — portal login email
    FIRSTALT_PASSWORD — portal login password

Returns:
    {"success": True, "driver_id": "..."}  on success
    {"success": False, "error": "..."}     on failure
"""
import logging
import os
import re

logger = logging.getLogger("zpay.firstalt.playwright")

_PORTAL_URL = "https://spguardian.firstalt.com"
_LOGIN_URL = f"{_PORTAL_URL}/login"
_DRIVERS_URL = f"{_PORTAL_URL}/drivers"
_ADD_DRIVER_URL = f"{_PORTAL_URL}/drivers/add"


def _normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 11 and digits[0] == "1":
        digits = digits[1:]
    return digits  # 10-digit string


def create_driver_playwright(name: str, email: str, phone: str) -> dict:
    """
    Automate driver creation in the FirstAlt SP Guardian portal.

    Steps performed:
      1. Launch headless Chromium
      2. Log in with FIRSTALT_USERNAME / FIRSTALT_PASSWORD
      3. Navigate to Add Driver form
      4. Fill name, email, phone
      5. Submit and capture the new driver ID from the redirect URL

    Returns dict with success/error keys.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
    except ImportError:
        return {"success": False, "error": "playwright not installed — run: pip install playwright && playwright install chromium"}

    username = os.environ.get("FIRSTALT_USERNAME")
    password = os.environ.get("FIRSTALT_PASSWORD")
    if not username or not password:
        return {"success": False, "error": "FIRSTALT_USERNAME / FIRSTALT_PASSWORD not set"}

    phone_digits = _normalize_phone(phone)
    if len(phone_digits) != 10:
        return {"success": False, "error": f"Invalid phone number: {phone!r}"}

    name_parts = name.strip().split()
    first_name = name_parts[0] if name_parts else name
    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.set_default_timeout(30_000)

        try:
            # ── Step 1: Log in ────────────────────────────────────────
            logger.info("Navigating to FirstAlt login")
            page.goto(_LOGIN_URL)
            page.wait_for_load_state("networkidle")

            # Fill credentials — selectors may need adjustment after portal updates
            page.fill('input[type="email"], input[name="email"], input[placeholder*="email" i]', username)
            page.fill('input[type="password"], input[name="password"]', password)
            page.click('button[type="submit"], input[type="submit"]')
            page.wait_for_load_state("networkidle")

            if "login" in page.url.lower():
                return {"success": False, "error": "Login failed — check FIRSTALT_USERNAME/PASSWORD"}

            logger.info("Login successful, navigating to add driver form")

            # ── Step 2: Navigate to Add Driver ────────────────────────
            page.goto(_ADD_DRIVER_URL)
            page.wait_for_load_state("networkidle")

            if "login" in page.url.lower():
                return {"success": False, "error": "Redirected to login after navigation — session not established"}

            # ── Step 3: Fill driver form ──────────────────────────────
            # Try first/last name fields first; fall back to full-name field
            try:
                page.fill('input[name*="firstName" i], input[placeholder*="first" i]', first_name)
                page.fill('input[name*="lastName" i], input[placeholder*="last" i]', last_name)
            except Exception:
                page.fill('input[name*="name" i]:first-of-type', name)

            page.fill('input[type="email"], input[name*="email" i]', email)

            # Phone — try formatted (555) 555-1234 first, fallback to digits
            phone_formatted = f"({phone_digits[:3]}) {phone_digits[3:6]}-{phone_digits[6:]}"
            try:
                page.fill('input[name*="phone" i], input[type="tel"]', phone_formatted)
            except Exception:
                page.fill('input[name*="phone" i], input[type="tel"]', phone_digits)

            # ── Step 4: Submit ────────────────────────────────────────
            page.click('button[type="submit"], input[type="submit"]')
            page.wait_for_load_state("networkidle")

            # ── Step 5: Extract new driver ID from URL or page ───────
            final_url = page.url
            match = re.search(r"/drivers/([A-Za-z0-9_-]+)", final_url)
            driver_id = match.group(1) if match else None

            if driver_id and driver_id != "add":
                logger.info("Driver created: id=%s", driver_id)
                return {"success": True, "driver_id": driver_id, "name": name, "email": email}

            # Check for error message on page
            error_el = page.query_selector(".error, .alert-danger, [role='alert']")
            error_text = error_el.inner_text() if error_el else "Unknown error after submit"
            return {"success": False, "error": error_text}

        except PwTimeout as e:
            return {"success": False, "error": f"Timeout: {e}"}
        except Exception as e:
            logger.exception("Playwright error during driver creation")
            return {"success": False, "error": str(e)}
        finally:
            ctx.close()
            browser.close()
