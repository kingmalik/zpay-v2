# UX Audit Report — Z-Pay
**Audited:** All 27 templates + app.py routes + base navigation
**Users:** Malik (business owner, power user) and mom (non-technical payroll operator)

---

## Pages to Remove or Merge

### 1. `/analytics`, `/pareto`, `/insights` — DEAD STANDALONE PAGES
All three are registered as live routes (`/analytics/`, `/pareto/`, `/insights/`) and have their own full templates (`analytics.html`, `pareto.html`, `insights.html`), but they do not appear in the nav at all. The nav only links to `/intelligence`, which is a unified tab wrapper that re-renders all three. These standalone pages are orphaned — no user can navigate to them without typing the URL directly.

**Fix:** Remove the three standalone `@router.get("/")` handlers and their templates. Keep only `/intelligence`. The route files (`analytics.py`, `pareto.py`, `insights.py`) contain shared helper functions (`_build_analytics`, `_build_pareto`, `_build_snapshot`) that should stay.

---

### 2. `/rides` (`rides.html`) — UNSTYLED DEAD PAGE
`rides.html` does not extend `base.html` (missing all styling classes, uses raw `<h1>` and `<table class="table">`). It renders outside the nav shell entirely. The link from `people_list.html` ("View Rides") may be pointing here, but `people_person_rides.html` serves the same purpose with a fully styled implementation. Two templates serve "view a driver's rides for a week."

**Fix:** Confirm which route `people_list.html` links to, then consolidate to `people_person_rides.html` only. Delete `rides.html`.

---

### 3. `uploading.html` — ORPHANED LEGACY FORM
`uploading.html` is a raw HTML file (no `{% extends "base.html" %}`), styled with inline CSS from an earlier era. It duplicates the upload form that `upload.html` already handles with a modern UI. It has no navigation, no branding, and references a button label "Upload to AcumenYY" (a typo/placeholder left from development). No nav link or app route points to it.

**Fix:** Delete `uploading.html`. It is unreachable from the UI and fully superseded by `upload.html`.

---

### 4. `people_companies.html` — REDUNDANT INTERMEDIATE STEP
With only 2 companies (Acumen/Maz), an entire page just to pick a company is unnecessary friction. The company selector page adds a click with no value.

**Fix:** Fold company selection into the main `/people` page as pill-tabs (the same pattern used on Dashboard, Analytics, and Insights). Eliminate `people_companies.html` as a standalone page.

---

### 5. `admin/rate_overrides.html` — UNSTYLED SKELETON
`rate_overrides.html` is a raw HTML page — no base template, no navigation, plain `<table border="1">`, unstyled form. It is reachable via the "Manage" link on the Rates page (which is in the main nav). Any user who clicks "Manage" on a rate override lands on a completely unstyled, broken-looking page.

**Fix:** Either style it properly using base.html, or remove the "Manage" button from the Rates list if override management is not a supported workflow yet.

---

## Info Overload Issues

### 1. Analytics tab — 7 major sections stacked with no breathing room
The Analytics tab (and the orphaned `/analytics` page) has: 6 KPI cards, Profit by Company cards, Route Profitability table (all routes, can be 100+ rows), Most Profitable Rides (top 10), Least Profitable Rides (bottom 10), Profit by Pay Period table, and Driver Profitability table. That is 7 distinct data tables/sections in one scroll. Most Profitable Rides and Least Profitable Rides are near-identical tables (same 9 columns, same layout) placed back to back. Malik said "minimal, not too much info displayed."

**Fix:** Analytics tab should show only: KPI cards + Route Profitability + Driver Profitability. Move Most/Least Profitable Rides into a collapsible section or into the Pareto tab. Move Profit by Pay Period to Payroll History.

---

### 2. Intelligence page — 3 filters that don't apply to all tabs
The Intelligence page has: Company pill tabs, a Period batch dropdown, AND start/end date inputs — but these apply only to the Analytics tab. When you switch to Pareto or Insights, those tabs only respond to company filter; the date/period controls do nothing. The filter bar appears global but is not.

**Fix:** Either make filters apply to all tabs (pass all params to pareto/insights builders), or move the date/period filter controls inside the Analytics tab panel div — not in the shared page header.

---

### 3. Insights tab — AI narrative is null on every page load
The Intelligence route passes `"narrative": None` on GET. The Insights tab renders an empty narrative card on every load. The POST endpoint to generate it exists, but there is no trigger button visible in the Intelligence template. Users see an empty AI analysis box with no way to fill it.

**Fix:** Add a "Generate Analysis" button inside the Insights tab panel. Or auto-generate on load with a loading spinner.

---

### 4. Pareto tab — Explanation callout wastes space
The Pareto section has a large purple callout box explaining what the Pareto Principle is. Malik knows — he named the tab. The section headers already say "by profit generated."

**Fix:** Remove the explanation callout box.

---

### 5. Insights tab — Duplicate KPIs already shown in Analytics tab
The Insights tab shows 7 KPI cards (Revenue, Driver Cost, Profit, Margin, Total Rides, Active Drivers, Avg Profit/Ride). These are the exact same metrics shown in the Analytics tab one click away. Every page load re-fetches and re-renders the same numbers.

**Fix:** In the Insights tab, show only the 2 KPIs not already in Analytics: Active Drivers and Avg Profit/Ride. Remove Revenue, Cost, Profit, Margin, Rides — they live in Analytics.

---

### 6. People — 6-level drill-down to see one driver's rides
To view a driver's rides: People page (pick week) → company page → batch page → week-in-batch page → driver list → View Rides. Six templates deep for one drill-down. The flow involves selecting the date range twice (once to enter People, once again inside the batch).

**Fix:** People page should be a flat, searchable driver list with company/period filter pills at the top. One click opens a driver profile. Maximum two levels: list → detail.

---

## Navigation Problems

### 1. "Payroll" nav link → 404
The nav has `<a href="/payroll">Payroll</a>`. The `payroll_history.py` router defines `prefix="/payroll"` with only `/history` and `/history/{batch_id}` endpoints — `/payroll` alone returns 404. This is a broken primary nav link.

**Fix:** Change the nav href to `/payroll/history`. Or add a redirect from `/payroll` → `/payroll/history` in `app.py`.

---

### 2. Payroll History is hidden behind a broken link
Payroll History is one of the most important pages for the mom operator. It is only reachable via the broken `/payroll` nav link or by knowing the direct URL. It is not linked from Dashboard, not from Batches, not surfaced with any working shortcut.

**Fix:** Fix the nav link (#1 above). Also add a "View History" button on the Dashboard and Batches pages.

---

### 3. "Validation" in main nav is a developer-only tool
`/validate` is in the primary nav. It requires files to be placed manually in `~/Downloads/Acumen/` or `~/Downloads/Maz/` before it works. For mom, this page is confusing (technical language: "variance," "dry-run rate validator," "DB Stored") and impossible to use without terminal access.

**Fix:** Remove Validation from the primary nav. Expose it only via a footer link, a Settings page, or directly accessible to Malik at a known URL. Label it clearly for developers/auditors only.

---

### 4. "Rates" nav label is vague and routes to `/admin/rates`
The nav shows "Rates" but the URL prefix is `/admin/rates`. For mom, "Rates" without context is meaningless. The page itself is legitimately useful (view driver cost per service), but the label and the admin URL prefix together send mixed signals.

**Fix:** Rename nav item to "Rate Table" or move it to a secondary settings area, separate from the primary action items (Dashboard, Payroll, Upload, Dispatch, Intelligence).

---

### 5. Nav has 9 items — breaks on any screen under 1200px
Current nav: Dashboard, Payroll, Upload, Batches, People, Dispatch, Intelligence, Validation, Rates — plus a bell and avatar. `base.html` has no mobile breakpoint. On a laptop at 1024px this will overflow or compress unpredictably.

**Fix:** Group secondary items (Validation, Rates, Batches) into a "..." overflow/settings dropdown. Keep 5-6 primary items: Dashboard, Payroll, Upload, People, Dispatch, Intelligence.

---

### 6. Dispatch is one nav link but hides two separate systems + auth
Clicking "Dispatch" goes to `/dispatch` (unified view). But EverDriven has its own sub-page at `/dispatch/everdriven`, and Smart Assign is at `/dispatch/assign`. When EverDriven is offline, the error banner has a link — but it is easy to miss. There is no sub-navigation within Dispatch.

**Fix:** Add sub-nav tabs inside the Dispatch page: "Live View | Assign Driver | EverDriven Setup." The auth page (`dispatch_everdriven_auth.html`) should be reachable from a clearly visible tab, not just an error banner link.

---

## Missing Pages / Flows

### 1. No "Run Payroll" page — the core mom workflow has no front door
The system has Upload, Summary (payroll table), People (drill-down), and History. But there is no single page that says: "Here is the current open batch, here are the drivers, click to send pay stubs." The "Send All Pay Stubs" button is buried 4+ clicks deep inside the People drill-down. For mom, running payroll is the primary weekly task.

**Recommendation:** Build `/payroll/run` — shows the current batch, lists drivers with their calculated pay, and has one "Send All Pay Stubs" button. This is the page mom would bookmark.

---

### 2. No persistent driver profile page
There is no `/people/{driver_id}` profile. Driver info is scattered: pay in Summary, rides in People drill-down, email in the week_people table. `people_person_rides.html` is the closest, but it requires batch+week context and is not linkable without those params.

**Recommendation:** Build `/people/{driver_id}` with: contact info, email (editable inline), all-time earnings total, last 5 batches, and link to full ride history.

---

### 3. No pre-send confirmation before pay stubs go out
"Send All Pay Stubs" is a form POST with only a JS `confirm()` popup. For mom, accidentally emailing 80 drivers is a serious and unrecoverable mistake. No preview of who will receive email, no "dry run."

**Recommendation:** Add a confirmation page before sending: "Sending X pay stubs to Y drivers. Z have no email on file. [names listed]. Confirm or Cancel."

---

### 4. No global driver search
No search exists anywhere. Finding a specific driver requires knowing their batch week. With 80+ drivers across 11+ batches, this is slow.

**Recommendation:** Add a search input on the People page that filters the driver list by name in real time (client-side JS filter on the rendered table).

---

## Quick Wins (easy fix, high impact)

1. **Fix `/payroll` nav link** → `href="/payroll/history"` in `base.html`. One-line fix.
2. **Delete `uploading.html`** — unreachable, unstyled, has a "AcumenYY" typo. Zero-risk delete.
3. **Remove Validation from main nav** — move to footer. Reduces nav clutter and protects mom.
4. **Add redirect in `app.py`**: `RedirectResponse("/payroll/history")` for `/payroll`. Two lines.
5. **Remove Pareto explainer callout** — delete 10 lines from intelligence.html Pareto tab panel.
6. **Add "Generate Analysis" button to Insights tab** — currently the AI narrative box is permanently empty.
7. **Style `rate_overrides.html`** — extend `base.html`, copy the glass-card pattern. Prevents landing on an unstyled page from a main-nav-accessible link.
8. **Remove duplicate KPI cards from Insights tab** — keep only Active Drivers and Avg Profit/Ride.

---

## Recommendations (prioritized)

### Tier 1 — Fix broken things (before mom uses the system)
1. Fix `/payroll` nav link → `/payroll/history`
2. Fix `/payroll` 404 with redirect in app.py
3. Add "Generate Analysis" button to Insights tab (narrative is permanently null on load)
4. Style `rate_overrides.html` with base.html
5. Remove Validation from primary nav

### Tier 2 — Reduce overload and confusion
6. Analytics tab: remove Most/Least Profitable Rides and Profit by Pay Period (too many sections)
7. Insights tab: remove duplicate KPI cards already in Analytics tab
8. Intelligence filter bar: scope date/period controls to Analytics tab only
9. Remove Pareto explainer callout
10. Delete `uploading.html`, `rides.html` dead templates

### Tier 3 — Navigation cleanup
11. Reduce nav from 9 to 5-6 items with settings overflow
12. Fold company selector into People page as pill-tabs (kill `people_companies.html`)
13. Add Dispatch sub-navigation (Live | Assign | EverDriven Setup)
14. Remove orphan `/analytics`, `/pareto`, `/insights` standalone routes

### Tier 4 — Build missing flows
15. Flatten People from 6-level drill-down to 2-level (list + profile)
16. Build `/payroll/run` page for mom: current batch, driver list, one send button
17. Build pre-send confirmation flow before pay stubs are emailed
18. Add driver name search on People page

---

## Summary Table

| Issue | Severity | Effort |
|---|---|---|
| `/payroll` nav link 404 | Critical | Trivial |
| `uploading.html` dead page | High | Trivial |
| Validation in main nav | High | Trivial |
| AI narrative null on load (no button) | High | Low |
| 9-item nav overflow on mobile | High | Medium |
| `rate_overrides.html` unstyled | Medium | Low |
| Analytics 7-section info overload | Medium | Low |
| Intelligence filter scope mismatch | Medium | Medium |
| People 6-level drill-down | High | High |
| No payroll run page for mom | High | High |
| No pre-send confirmation | High | Medium |
| Duplicate KPIs across tabs | Low | Trivial |
| Pareto explainer callout | Low | Trivial |
| Orphan `/analytics`, `/pareto`, `/insights` routes | Medium | Low |
| `rides.html` unstyled duplicate | Medium | Low |
| No driver search | Medium | Medium |
