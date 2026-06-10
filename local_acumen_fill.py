#!/usr/bin/env python3
"""
Local Acumen pay-entry runner — W21 batch 98.
Runs from Malik's Mac (residential IP + on-disk session cookies), bypassing
the Railway container entirely. Uses the PROVEN interaction:
  click cell -> wait for the ".edit" editor input -> fill -> Tab to commit.
NEVER submits. Leaves all entries as drafts for manual Review & Submit.
"""
import asyncio, json, pathlib, sys
from playwright.async_api import async_playwright

COOKIES = json.load(open('/Users/malikmilion/.zpay_session_acumen.json'))
ENTRIES = json.load(open('/tmp/batch98_entry.json'))
GRID = '[data-payxautoid="paychex.app.payroll.payrollEntry.search.searchBar.input"]'
SEARCH_BTN = '[data-payxautoid="paychex.app.payroll.payrollEntry.search.searchButton"]'
LOG = pathlib.Path('/tmp/local_acumen_fill.log')

def log(msg):
    line = msg
    print(line, flush=True)
    with open(LOG, 'a') as f:
        f.write(line + "\n")

async def reach_grid(page):
    async def at_grid():
        try:
            return await page.locator(GRID).count() > 0
        except Exception:
            return False
    for _ in range(6):
        if await at_grid():
            return True
        for label in ["Begin", "Resume", "Continue payroll", "Continue"]:
            try:
                loc = page.locator(f'button:has-text("{label}"), a:has-text("{label}")').first
                if await loc.count() and await loc.is_visible():
                    await loc.click(timeout=4000); await page.wait_for_timeout(2500); break
            except Exception:
                pass
        try:
            cap = page.locator('[data-payxautoid="paychex.app.payroll.quickPayroll.startPayroll.manualChecksRadioButton.caption"]')
            if await cap.count() and await cap.is_visible():
                await cap.click(); await page.wait_for_timeout(300)
                await page.locator('[data-payxautoid="paychex.app.payroll.quickPayroll.startPayroll.continueButton"]').click(timeout=5000)
                await page.wait_for_timeout(2500)
        except Exception:
            pass
        await page.wait_for_timeout(2000)
    return await at_grid()

async def fill_driver(page, code, amount):
    amt = f"{amount:.2f}"
    cell_auto = f"paychex.app.payroll.payrollEntry.worker.{code}.check.1.row.0.1099NecAmount"
    edit_auto = f"{cell_auto}.edit"
    # search
    sb = page.locator(GRID)
    await sb.click(); await page.keyboard.press("Control+a"); await page.keyboard.press("Delete")
    await sb.type(str(code), delay=35); await page.wait_for_timeout(500)
    try:
        await page.locator(SEARCH_BTN).click(timeout=4000)
    except Exception:
        await sb.press("Enter")
    await page.wait_for_timeout(2000)
    # confirm row in DOM
    if not await page.evaluate("(s)=>!!document.querySelector(s)", f'[data-payxautoid="{cell_auto}"]'):
        return False, "row-not-found"
    cell_div = page.locator(f'[data-payxautoid="{cell_auto}"]').first
    cell_td  = page.locator(f'td:has([data-payxautoid="{cell_auto}"])').first
    editor   = page.locator(f'[data-payxautoid="{edit_auto}"]').first
    try:
        await cell_div.scroll_into_view_if_needed(timeout=4000); await page.wait_for_timeout(250)
    except Exception:
        pass
    opened = False
    for action in (lambda: cell_div.click(timeout=4000),
                   lambda: cell_td.click(timeout=4000),
                   lambda: cell_td.dblclick(timeout=4000)):
        try:
            await action()
        except Exception:
            pass
        try:
            await editor.wait_for(state="visible", timeout=3000); opened = True; break
        except Exception:
            continue
    if not opened:
        return False, "editor-never-opened"
    # fill + commit
    try:
        await editor.fill(amt)
    except Exception:
        try:
            await editor.click(); await page.keyboard.press("Control+a"); await page.keyboard.type(amt, delay=35)
        except Exception:
            return False, "fill-failed"
    await page.keyboard.press("Tab")   # commit (click-out)
    await page.wait_for_timeout(900)
    # verify cell now shows the amount
    shown = await page.evaluate("(s)=>{const e=document.querySelector(s);return e?(e.textContent||'').trim():null}",
                                f'[data-payxautoid="{cell_auto}"]')
    ok = False
    if shown:
        try:
            ok = abs(float(shown.replace(',','').replace('$','').strip()) - amount) < 0.01
        except Exception:
            ok = False
    return ok, (shown or "")

async def main():
    LOG.write_text("")
    log(f"== Local Acumen fill — {len(ENTRIES)} codes, ${sum(e['amount'] for e in ENTRIES):,.2f} ==")
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage','--disable-blink-features=AutomationControlled'])
        ctx = await b.new_context(user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36', viewport={'width':1500,'height':900}, locale='en-US')
        await ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        await ctx.add_cookies(COOKIES)
        page = await ctx.new_page()
        await page.goto("https://myapps.paychex.com/landing_remote/login.do?lang=en&landingRedirect=true#?mode=ad", wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)
        if not await reach_grid(page):
            log("!! could not reach Pay Entry grid"); await b.close(); return
        log("reached Pay Entry grid")
        ok_n = fail_n = 0; fails = []
        for idx, e in enumerate(ENTRIES, 1):
            code, amt, name = e["code"], e["amount"], e["name"]
            try:
                ok, detail = await fill_driver(page, code, amt)
            except Exception as ex:
                ok, detail = False, f"exc:{str(ex)[:60]}"
            if ok:
                ok_n += 1; log(f"  [{idx:>2}/{len(ENTRIES)}] OK   {code:<6} ${amt:>9.2f}  {name}")
            else:
                fail_n += 1; fails.append((code, amt, name, detail))
                log(f"  [{idx:>2}/{len(ENTRIES)}] FAIL {code:<6} ${amt:>9.2f}  {name}  ({detail})")
        log(f"== DONE: {ok_n} ok, {fail_n} failed ==")
        if fails:
            log("FAILURES (enter these manually):")
            for c,a,n,d in fails:
                log(f"   {c:<6} ${a:>9.2f}  {n}   [{d}]")
        await b.close()

asyncio.run(main())
