import os, urllib.parse, secrets, hashlib, base64
os.environ.setdefault("EVERDRIVEN_USERNAME", "mazservices3@gmail.com")
os.environ.setdefault("EVERDRIVEN_PASSWORD", "MalaayaMaz3")
from playwright.sync_api import sync_playwright

_CLIENT_ID = "63cca938-16e4-4d66-8860-e2395b3e8a11"
_SCOPE = "https://alcproviderportal.onmicrosoft.com/providerportal/user_impersonation"
_AUTH_URL = "https://alcproviderportal.b2clogin.com/alcproviderportal.onmicrosoft.com/b2c_1_signin/oauth2/v2.0/authorize"
redirect_uri = "https://sp.everdriven.com/"

code_verifier = secrets.token_urlsafe(64)
code_challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode()
state = secrets.token_urlsafe(16)
params = urllib.parse.urlencode({
    "response_type": "code", "client_id": _CLIENT_ID,
    "redirect_uri": redirect_uri,
    "scope": f"openid offline_access {_SCOPE}",
    "state": state, "code_challenge": code_challenge,
    "code_challenge_method": "S256", "prompt": "login"
})
authorize_url = f"{_AUTH_URL}?{params}"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(authorize_url, timeout=30000)
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(2000)
    page.wait_for_selector("#email", timeout=30000)
    page.click("#email")
    page.type("#email", os.environ["EVERDRIVEN_USERNAME"], delay=50)
    page.click("#password")
    page.type("#password", os.environ["EVERDRIVEN_PASSWORD"], delay=50)
    page.click("#next")
    page.wait_for_timeout(10000)
    print("Final URL:", page.url[:300])
    print("Title:", page.title())
    # Check for errors
    err_text = page.inner_text("body")
    if "error" in err_text.lower() or "invalid" in err_text.lower():
        print("Body snippet:", err_text[:500])
    browser.close()
