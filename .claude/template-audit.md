# Template Audit — Z-Pay UI Rebuild

**Audited:** 2026-03-28
**Scope:** All active templates + main.css + inline-edit.js
**Purpose:** Complete reference for agents building the new CSS and templates

---

## CSS Variables Reference (from main.css)

All templates depend on these CSS custom properties:

```
--bg-base:       #07070e
--sidebar-bg:    #0d0d18
--glass-bg:      rgba(255,255,255,0.035)
--glass-bg-hover:rgba(255,255,255,0.065)
--glass-border:  rgba(255,255,255,0.08)
--glass-border-strong: rgba(255,255,255,0.18)
--glass-shadow:  0 8px 32px rgba(0,0,0,0.55), inset 0 1px 0 rgba(255,255,255,0.05)
--glass-blur:    blur(20px) saturate(160%)
--text-primary:  rgba(255,255,255,0.92)
--text-secondary:rgba(255,255,255,0.50)
--text-muted:    rgba(255,255,255,0.25)
--accent:        #6366f1  (indigo)
--accent-glow:   rgba(99,102,241,0.35)
--accent-soft:   rgba(99,102,241,0.12)
--accent-hover:  #818cf8
--green:         #10b981
--green-glow:    rgba(16,185,129,0.30)
--green-soft:    rgba(16,185,129,0.12)
--red:           #ef4444
--red-soft:      rgba(239,68,68,0.12)
--yellow:        #f59e0b
--yellow-soft:   rgba(245,158,11,0.12)
--radius-sm:     8px
--radius-md:     12px
--radius-lg:     16px
--radius-xl:     22px
--radius-pill:   999px
--sidebar-width: 240px
```

## Hardcoded Color Tokens (used inline, NOT in CSS vars)

The templates make heavy use of hardcoded hex/rgba colors inline rather than CSS variables. New build should either tokenize these or map them to variable equivalents:

| Inline value | Semantic meaning | CSS var equivalent |
|---|---|---|
| `#93c5fd` | Revenue / blue | — (not in vars) |
| `#f87171` | Driver cost / red | close to `--red` |
| `#34d399` | Profit / green | close to `--green` |
| `#a5b4fc` | Margin / violet | — (not in vars) |
| `#a78bfa` | Profit alt / purple | — (not in vars) |
| `#fbbf24` | Warning / withheld / gold | — (not in vars) |
| `#6ee7b7` | EverDriven green | — (not in vars) |
| `rgba(59,130,246,...)` | Blue accent (pill tabs active) | — (not in vars, different from --accent indigo) |

---

## base.html

**Classes used:** `zpay-layout`, `zpay-sidebar`, `zpay-logo`, `zpay-logo-sub`, `zpay-nav`, `nav-section-label`, `zpay-sidebar-footer`, `zpay-main`, `zpay-page-header`, `glass-card`, `active` (on nav `<a>`)

**Key inline styles:**
- Alert badge on Alerts nav link: `display:none; margin-left:auto; min-width:18px; height:18px; padding:0 5px; border-radius:999px; background:#ef4444; color:#fff; font-size:10px; font-weight:700; line-height:18px; text-align:center; flex-shrink:0;`
  - Injected dynamically via JS: `animation: alert-pulse 2s ease-in-out infinite` + `box-shadow: 0 0 8px rgba(239,68,68,0.7)`

**JavaScript:**
1. Alert badge fetch — polls `/alerts/data`, shows badge count with pulse animation if `d.total > 0`
2. Active nav highlight — matches `window.location.pathname` to `data-path` attributes on nav links, adds `active` class to best/longest match (exact match wins)

**Jinja2 blocks defined:** `title`, `page_title`, `subtitle`, `content`

**Variables:** None (layout-only). `self.page_title()|trim` check controls whether `.zpay-page-header` renders.

**Notes:**
- Every page gets wrapped in `.glass-card` automatically via base. Some pages add extra wrapper divs with padding inside.
- The `active` class on nav links is added by JS client-side, not server-side.
- `inline-edit.js` is loaded globally via `<script defer>` in `<head>`.

---

## summary.html

**Classes used:** `btn`, `btn-ghost`, `btn-primary`, `glass-table`, `text-right`, `muted`, `net-pay-cell`, `empty-state`, `total-label`, `total-value`

**Key inline styles:**
- Company tab pills — fully inline, no CSS class. Active state: `background:rgba(59,130,246,0.18); border:1px solid rgba(59,130,246,0.4); color:#93c5fd`. Inactive: `background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.1); color:rgba(255,255,255,0.5)`
- Batch period pills — same pattern as company pills but smaller (`padding:5px 12px; font-size:12px`)
- Warning banner when no batch selected: `background:rgba(251,191,36,0.1); border:1px solid rgba(251,191,36,0.25); border-radius:8px; color:rgba(251,191,36,0.85)`
- Withheld row tint: `background:rgba(248,113,113,0.04)` on `<tr>`
- "From last period" yellow amount: `color:rgba(251,191,36,0.8)`
- Withheld cell text: `color:#f87171; font-size:12px; font-weight:500`
- Pay this period green: `color:#34d399`
- Table wrapper: `overflow-x:auto; margin-top:12px`

**JavaScript:** None page-specific

**Jinja2 variables:** `companies` (list), `selected_company` (str), `selected_batch_id` (int|None), `batches` (list with `.payroll_batch_id`, `.period_start`, `.period_end`), `rows` (list with `.person`, `.code`, `.active_between`, `.days`, `.net_pay`, `.withheld`, `.withheld_amount`, `.from_last_period`, `.pay_this_period`), `totals` (obj with `.days`, `.net_pay`, `.pay_this_period`), `start` (str|None), `end` (str|None)

**Notes:**
- Company tab and batch period filters use URL params (full page reload), not JS
- `net-pay-cell` class makes net_pay column green
- `total-value` in tfoot makes totals green (overridden inline for color variants)
- The pill tab pattern (active/inactive inline style) is repeated verbatim across many templates — keep consistent

---

## intelligence.html

**Classes used:** `btn`, `btn-ghost`, `glass-table`, `text-right`, `muted`, `empty-state`, `total-label`, `total-value`

**Key inline styles (structural):**
- Tab bar container: `display:flex; gap:6px; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08); border-radius:14px; padding:5px; width:fit-content`
- Tab buttons: `padding:8px 22px; border-radius:10px; border:none; cursor:pointer; font-size:13px; font-weight:600`
- Tab active style (injected by JS): `background:rgba(59,130,246,0.2); border:1px solid rgba(59,130,246,0.4); color:#93c5fd; box-shadow:0 0 12px rgba(59,130,246,0.25)`
- Tab inactive (injected by JS): `background:transparent; border:1px solid transparent; color:rgba(255,255,255,0.4); box-shadow:none`
- Company pill tabs and date range form: same inline pill pattern as summary.html
- Batch dropdown select: `background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.15); border-radius:6px; color:rgba(255,255,255,0.8); padding:5px 10px; font-size:12px; cursor:pointer; max-width:380px`
- Summary KPI cards: each has unique color tint (blue/red/green/violet/neutral/gold), inline background + border + border-radius:12px
- Unmatched rates warning banner: `background:rgba(251,191,36,0.07); border:1px solid rgba(251,191,36,0.2); border-radius:10px`
- Progress bars (Pareto): `background:rgba(255,255,255,0.06); border-radius:999px; height:6px` wrapping `height:100%; width:{{pct}}%; background:linear-gradient(...); border-radius:999px`
- 80% cutoff rows: `background:rgba(251,191,36,0.08); border-bottom:2px solid rgba(251,191,36,0.35)` on `<tr>`
- 80% LINE badge: `margin-left:8px; font-size:10px; padding:2px 7px; border-radius:999px; background:rgba(251,191,36,0.15); border:1px solid rgba(251,191,36,0.35); color:#fbbf24`
- Pareto intro callout: `background:rgba(165,180,252,0.06); border:1px solid rgba(165,180,252,0.2); border-radius:12px; padding:16px 20px`
- Pareto summary callouts (green/blue): `background:rgba(52,211,153,0.07); border:1px solid rgba(52,211,153,0.25); border-radius:10px`
- 2-column grids for Pareto services: `display:grid; grid-template-columns:1fr 1fr; gap:20px`
- Claude analysis container: `background:rgba(165,180,252,0.05); border:1px solid rgba(165,180,252,0.18); border-radius:14px; padding:22px 24px`
- Claude avatar circle: `width:32px; height:32px; border-radius:50%; background:rgba(165,180,252,0.15); border:1px solid rgba(165,180,252,0.3); font-size:15px`
- Narrative area: `font-size:14px; color:rgba(255,255,255,0.75); line-height:1.75; white-space:pre-wrap; min-height:40px`
- Generate button: `padding:8px 20px; border-radius:9px; border:1px solid rgba(165,180,252,0.35); background:rgba(165,180,252,0.1); color:#a5b4fc; font-size:13px; font-weight:600`

**JavaScript:**
1. `switchTab(name)` — shows/hides `#tab-analytics`, `#tab-pareto`, `#tab-insights` divs; applies active/inactive styles to tab buttons; shows/hides date range form and batch filter row (analytics only); updates URL hash
2. On-load: reads `{{ active_tab }}` from Jinja and `location.hash`, activates appropriate tab
3. `generateInsights()` — POSTs to `/intelligence/generate-insights?company=...`, updates `#narrative-area` text and button state; handles loading/error states

**Jinja2 variables:**
- `zero_rate_count` (int), `companies` (list), `selected_company` (str|None), `selected_batch_id` (int|None), `batches`, `start`, `end`, `active_tab` (str, default 'analytics')
- Analytics tab: `summary` (obj: `.total_revenue`, `.total_cost`, `.total_profit`, `.margin_pct`, `.total_rides`, `.avg_profit_per_ride`), `company_rows` (list), `top_rides`, `bottom_rides`, `period_rows`, `route_stats` (list with `.rank`, `.service_name`, `.total_rides`, `.revenue`, `.cost`, `.profit`, `.avg_profit_per_ride`, `.margin_pct`), `driver_stats` (list with `.rank`, `.driver`, `.total_rides`, `.total_profit`, `.avg_profit_per_ride`, `.profit_margin`, `.total_earnings`, `.active_weeks`)
- Pareto tab: `pareto_driver_rows` (list with `.rank`, `.driver`, `.rides`, `.profit`, `.individual_pct`, `.cumulative_pct`, `.is_cutoff`), `pareto_driver_summary` (`.drivers_at_80`, `.driver_pct_of_fleet`, `.total_drivers`), `pareto_least_profitable_rows`, `pareto_service_by_volume`, `pareto_service_by_profit`, `pareto_service_summary`, `pareto_period_rows`, `pareto_period_summary`
- Insights tab: `snapshot` (obj with `.total_revenue`, `.total_cost`, `.total_profit`, `.margin_pct`, `.total_rides`, `.active_drivers`, `.company_filter`, `.top_drivers`, `.recent_periods`, `.top_routes`, `.bottom_routes`, `.top_services`)

**Notes:**
- `#shared-filters` div contains company pills + date range form + batch dropdown, visible for all tabs but date/batch elements hidden for pareto/insights via JS
- Tab state lives in URL hash, not server; `active_tab` from server is only the initial default
- `style="display:none"` on `#tab-pareto` and `#tab-insights` at render time; JS shows on click
- Loss rows: `background:rgba(248,113,113,0.04)` when `r.profit < 0` — preserve this pattern

---

## payroll_history.html

**Classes used:** `glass-table`, `text-right`, `muted`, `empty-state`

**Key inline styles:**
- Table wrapper: `padding:20px 20px 0; overflow-x:auto`
- Colored column headers: `color:#93c5fd` (Partner Paid), `color:#f87171` (Driver Cost), `color:#a78bfa` (Profit), `color:#fbbf24` (Withheld), `color:#34d399` (Driver Payout)
- Company name cell: `font-weight:600; color:rgba(255,255,255,0.85)`
- Batch ref cell: `font-size:12px; font-family:monospace`
- Period cell: `white-space:nowrap`; separator: `color:rgba(255,255,255,0.2)`
- Uploaded at: `font-size:12px`
- Revenue value: `color:#93c5fd; font-weight:600`
- Driver cost value: `color:#f87171`
- Profit value: `color:#a78bfa; font-weight:700`
- Withheld amount: `color:#fbbf24; font-weight:600` + sub-label `font-size:10px; color:rgba(251,191,36,0.45)`
- Driver payout: `color:#34d399; font-weight:700`
- View button (inline, not .btn class): `padding:4px 12px; border-radius:6px; font-size:12px; font-weight:600; background:rgba(59,130,246,0.12); border:1px solid rgba(59,130,246,0.3); color:#93c5fd` with JS `onmouseover`/`onmouseout` hover swap
- Totals footer row: `display:flex; gap:14px; flex-wrap:wrap; align-items:center; justify-content:flex-end; border-top:1px solid rgba(255,255,255,0.06)`

**JavaScript:** None (onmouseover/onmouseout inline hover only)

**Jinja2 variables:** `batch_rows` (list with `.batch_id`, `.company_name`, `.batch_ref`, `.batch_ref_display`, `.period_start`, `.period_end`, `.uploaded_at`, `.ride_count`, `.total_net_pay`, `.total_z_rate`, `.total_profit`, `.has_withholding_data`, `.total_withheld`, `.withheld_drivers`, `.total_paid_out`)

**Notes:**
- Uses Jinja2 `sum` filter on batch_rows for the totals footer
- `batch_ref_display` is a truncated version of `batch_ref` for display
- "ⓘ" tooltip character is used for the Withheld column header help text
- The "View" button is NOT using the `.btn` class — it's fully inline

---

## payroll_history_detail.html

**Classes used:** `glass-table`, `text-right`, `muted`, `empty-state`, `total-label`, `total-value`

**Key inline styles:**
- Back link: fully inline flex, `color:rgba(255,255,255,0.4)` + `onmouseover`/`onmouseout` color swap
- Batch ref badge: `font-size:12px; font-family:monospace; background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.1); border-radius:6px; padding:3px 10px`
- Source badge: same style as batch ref badge
- "Open in Summary" link (not .btn): `background:rgba(59,130,246,0.1); border:1px solid rgba(59,130,246,0.25); color:#93c5fd` with hover swap
- Warning notice (historical import): `background:rgba(251,191,36,0.07); border:1px solid rgba(251,191,36,0.2); border-radius:8px`
- KPI summary cards: 6 cards, each with color tint (neutral/blue/red/gold/green/purple), inline background + border + border-radius:12px + padding:16px 18px
- KPI label: `font-size:10px; text-transform:uppercase; letter-spacing:0.08em; color:...; margin-bottom:6px`
- KPI value: `font-size:24px; font-weight:700; color:...; letter-spacing:-0.5px`
- KPI sub-label: `font-size:11px; color:rgba(255,255,255,0.25); margin-top:3px`
- Section heading: `font-size:13px; font-weight:600; color:rgba(255,255,255,0.4); text-transform:uppercase; letter-spacing:0.08em`
- Withheld row tint: `background:rgba(251,191,36,0.03)` on `<tr>` when `d.is_withheld`
- Driver name link: `color:inherit; text-decoration:none` with `onmouseover`/`onmouseout` to `#93c5fd`
- Code cell: `font-size:12px; font-family:monospace`
- Withheld badge cell: `display:inline-block; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:700; background:rgba(251,191,36,0.12); border:1px solid rgba(251,191,36,0.25); color:#fbbf24`

**JavaScript:** None (inline onmouseover/onmouseout only)

**Jinja2 variables:** `batch` (obj with `.company_name`, `.batch_ref`, `.source`), `batch_id`, `batch_ref_display`, `period_start`, `period_end`, `uploaded_at`, `has_withholding_data`, `totals` (obj with `.rides`, `.net_pay`, `.z_rate`, `.withheld`, `.paid_out`, `.gross_pay`, `.profit`), `driver_rows` (list with `.person_id`, `.driver`, `.code`, `.ride_count`, `.gross_pay`, `.net_pay`, `.z_rate`, `.profit`, `.withheld`, `.paid_out`, `.is_withheld`)

**Notes:**
- Driver names link to `/people/{{ d.person_id }}`
- `total-value muted` combo is used for gross_pay total (dimmed, not green)
- `total-value` with inline color override is used for per-column coloring in tfoot

---

## people_list.html

**Classes used:** `table` (NOT `glass-table` — legacy class, not defined in main.css)

**Key inline styles:** None

**JavaScript:** None

**Jinja2 variables:** `week_start`, `week_end`, `source`, `company`, `people` (list with `.full_name`, `.ride_count`, `.net_total`, `.person_id`), Jinja filters: `mmddyyyy`, `currency`

**Notes:**
- LEGACY template. Uses `class="table"` which has no definition in main.css. Does NOT extend base.html with standard layout — it extends base.html but uses legacy CSS classes. The H1 and P tags are bare unstyled elements.
- This template is mostly obsolete — the active people UX flows through the main dashboard. Needs complete rebuild to match glass aesthetic.

---

## people.html

**Classes used:** `table` (legacy, not in main.css)

**Key inline styles:** None

**JavaScript:** None

**Jinja2 variables:** `weeks` (list with `.week_start`, `.week_end`), Jinja filter: `mmddyyyy`

**Notes:**
- LEGACY template. Same issues as people_list.html. No navigation back to base layout. Shows a list of weeks, not the current people directory concept.

---

## upload.html

**Classes used:** `upload-grid`, `upload-card`, `btn`, `btn-primary`, `btn-green`

**Key inline styles:**
- Submit button wrapper div: `margin-top:16px` (inside upload-card)

**JavaScript:** None page-specific

**Jinja2 variables:** None (static form)

**Notes:**
- Clean and minimal. upload-card and upload-grid are fully defined in main.css.
- Two forms: Acumen (`.xlsx`) and MAZ (`.pdf`), different button colors (`btn-primary` vs `btn-green`)
- No flash messages shown — success redirects to a different page

---

## batches.html

**Classes used:** `glass-table`, `text-right`, `muted`, `empty-state`, `total-label`, `total-value`

**Key inline styles:**
- Top bar: `display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px; padding:20px 20px 0`
- Count label: `font-size:13px; color:rgba(255,255,255,0.35)`
- Upload button (not .btn class): `padding:7px 18px; border-radius:999px; font-size:13px; font-weight:600; background:rgba(59,130,246,0.15); border:1px solid rgba(59,130,246,0.35); color:#93c5fd`
- Table wrapper: `padding:16px 20px 32px; overflow-x:auto`
- Colored column headers: `color:#93c5fd` (Revenue), `color:#f87171` (Driver Cost)
- Revenue cell: `color:#93c5fd; font-weight:600`
- Driver cost cell: `color:#f87171`
- Actions cell: `text-align:center; white-space:nowrap`
- Delete button (inline, not .btn): `padding:5px 14px; border-radius:7px; font-size:12px; font-weight:600; background:rgba(248,113,113,0.08); border:1px solid rgba(248,113,113,0.25); color:#f87171` with `onmouseover`/`onmouseout` swaps
- tfoot total-value for revenue: `color:#93c5fd` override (conflicts with CSS default green)

**JavaScript:** `onsubmit="return confirm(...)"` for delete confirmation (inline, not in script tag)

**Jinja2 variables:** `batches` (list with `.payroll_batch_id`, `.company_name`, `.source`, `.period_start`, `.period_end`, `.uploaded_at`, `.ride_count`, `.total_revenue`, `.total_cost`)

**Notes:**
- Upload button and Delete button are NOT using `.btn` class — all inline
- `total-value` class is green by default; revenue/cost totals use inline color overrides to make them blue/red

---

## dispatch.html

**Classes used:** None from main.css (entirely inline styles)

**Key inline styles (structural):**
- Top bar layout: flex, space-between, gap:12px, padding:16px 20px 0
- Date input: `background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.12); border-radius:8px; color:rgba(255,255,255,0.85); font-size:13px; padding:5px 10px`; auto-submits on `onchange`
- Source filter tabs container: `display:flex; gap:4px; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08); border-radius:10px; padding:3px`
- Source tab items: `padding:4px 12px; border-radius:7px; font-size:12px`
  - All: active `background:rgba(255,255,255,0.1); color:rgba(255,255,255,0.9)`
  - FirstAlt: active `background:rgba(99,102,241,0.25); color:#a5b4fc`
  - EverDriven: active `background:rgba(52,211,153,0.18); color:#6ee7b7`
- Dashboard stat pills (Total/Done/Active/Scheduled/Cancelled): each uniquely colored pill with background+border
- FA/ED breakdown pill: `background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.07); font-size:11px`
- Error banners: `background:rgba(248,113,113,0.08); border:1px solid rgba(248,113,113,0.2); border-radius:10px`
- Driver grid: `display:grid; grid-template-columns:repeat(auto-fill, minmax(340px,1fr)); gap:12px; padding:16px 20px`
- Driver card: `background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08); border-radius:14px; padding:16px`
- FA source badge pill: `background:rgba(99,102,241,0.18); border:1px solid rgba(99,102,241,0.3); color:#a5b4fc`
- ED source badge pill: `background:rgba(52,211,153,0.15); border:1px solid rgba(52,211,153,0.28); color:#6ee7b7`
- Trip status color logic: Completed=#34d399, Cancelled=#f87171, InProgress=#fbbf24, default=#93c5fd
- Source dot (absolute positioned): `position:absolute; top:7px; right:8px; width:6px; height:6px; border-radius:50%`; FirstAlt=#818cf8, EverDriven=#34d399
- Unassigned section: `background:rgba(251,191,36,0.05); border:1px solid rgba(251,191,36,0.18); border-radius:12px`

**JavaScript:**
- Date input `onchange="this.form.submit()"` only

**Jinja2 variables:** `target_date` (str), `source_filter` (str|None), `dashboard` (obj: `.total`, `.completed`, `.active`, `.scheduled`, `.cancelled`, `.fa_total`, `.ed_total`), `fa_ok`, `ed_ok`, `fa_error`, `ed_auth_needed`, `ed_error`, `drivers` (list with `.name`, `.phone`, `.email`, `.sources`, `.trip_count`, `.trips`), `unassigned` (list of trips)

**Notes:**
- This is the most inline-heavy template — zero CSS classes from main.css used
- Trip cards use Jinja set blocks to determine status color: `{% set sc = '#34d399' %}{% set sb = 'rgba(...)' %}`
- Source dot is absolutely positioned within relative trip card
- EverDriven color is #6ee7b7 (teal-green), different from the global --green (#10b981)

---

## validate.html

**Classes used:** `glass-table`, `text-right`, `muted`, `empty-state`, `total-label`, `total-value`

**Key inline styles:**
- Source tab pills: same inline active/inactive pill pattern as other pages
- Legend row: `display:flex; gap:20px; flex-wrap:wrap; padding:14px 20px 0`
- Grand summary cards: 4 cards, color dynamically chosen per-card based on variance value
- Variance card color logic: green if `variance==0`, yellow if `variance|abs < 1`, red otherwise
- Week cards: `background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); border-radius:14px; overflow:hidden; margin-bottom:16px`
- Week header (clickable): `cursor:pointer; display:flex; align-items:center; justify-content:space-between; padding:16px 20px`
- Week header KPI group: `text-align:right` with three value blocks (Z-Pay Calc, DB Stored, Variance)
- Chevron indicator: `id="chevron-{id}"`, text content `▶` collapsed / `▼` expanded
- Collapsed driver table: `display:none` by default on `id="week-{id}"`
- Inline table inside week card: `margin:0; border-radius:0` overrides on `.glass-table`
- "Not in DB" badge: `background:rgba(251,191,36,0.12); border:1px solid rgba(251,191,36,0.25); border-radius:6px; color:#fbbf24; font-size:11px`
- Match cell: ✓ in `#34d399`, ✗ in `#f87171`
- Error week card: `background:rgba(248,113,113,0.07); border:1px solid rgba(248,113,113,0.2); border-radius:12px`

**JavaScript:**
- `toggleWeek(id)` — toggles `display` on week panel div and swaps chevron character ▶/▼

**Jinja2 variables:** `source` (str: 'acumen'|'maz'), `acumen_count` (int), `maz_count` (int), `grand` (obj: `.file_rides`, `.file_net_pay`, `.file_z_rate`, `.db_z_rate`, `.db_rides`, `.variance`), `weeks` (list of either error objects `{week, error}` or full objects `{week, period_start, period_end, db_found, file_z_rate, file_rides, file_net_pay, db_z_rate, db_rides, variance, drivers}`)

**Notes:**
- Week IDs for JS are generated with `w.week|replace(' ','_')` — spaces become underscores
- The `.glass-table` inside collapsed panels gets `margin:0; border-radius:0` via inline override to merge with the card
- `total-value` class is used in tfoot but with inline color overrides per column

---

## insights.html

**Status:** Superseded by `intelligence.html` (Insights tab). Still exists as standalone page at `/insights`.

**Classes used:** `glass-table`, `text-right`, `muted`, `empty-state`

**Key inline styles:**
- Company pills: same inline active/inactive pattern
- KPI cards: 7 cards, same inline color-tinted card pattern (22px value, 11px label)
- Claude analysis container: `background:rgba(165,180,252,0.05); border:1px solid rgba(165,180,252,0.18); border-radius:14px; padding:22px 24px`
- Claude avatar circle: `width:32px; height:32px; border-radius:50%`
- Narrative text: `font-size:14px; color:rgba(255,255,255,0.75); line-height:1.75; white-space:pre-wrap`
- 2-column table grid: `display:grid; grid-template-columns:1fr 1fr; gap:20px`
- Loss row tint: `background:rgba(248,113,113,0.04)` on negative profit route rows
- Route cell: `font-size:12px; max-width:200px; white-space:normal` (allows word wrap)

**JavaScript:** None page-specific (narrative is server-rendered, not fetched)

**Jinja2 variables:** `companies`, `selected_company`, `snapshot` (same shape as intelligence.html's snapshot), `narrative` (str, pre-rendered server-side)

**Notes:**
- This page's `narrative` is pre-rendered (string from server), unlike `intelligence.html` where it's fetched via POST
- The 2-column grid layout of driver/period tables is the same as intelligence.html's Insights tab
- `white-space:normal` on route cells allows service names to wrap — important for long names

---

## analytics.html

**Status:** Superseded by `intelligence.html` (Analytics tab). Still exists as standalone page at `/analytics`.

**Classes used:** `glass-table`, `text-right`, `muted`, `empty-state`, `total-label`, `total-value`, `btn`, `btn-ghost`

**Key inline styles:**
- Identical to intelligence.html Analytics tab (same unmatched banner, same company pills, same date form, same batch dropdown, same KPI cards, same tables)
- Route cell: `font-size:12px; max-width:300px; white-space:normal`

**JavaScript:** Batch dropdown uses `onchange="window.location=this.value"`

**Jinja2 variables:** `zero_rate_count`, `companies`, `selected_company`, `selected_batch_id`, `batches`, `start`, `end`, `summary`, `company_rows`, `route_stats`, `top_rides`, `bottom_rides`, `period_rows`, `driver_stats`

**Notes:**
- Nearly identical to the Analytics tab inside intelligence.html
- The standalone analytics.html and insights.html pages are legacy; all features are now in intelligence.html

---

## admin/rates_list.html

**Status:** LEGACY — does NOT extend base.html, has its own `<html>` document. Uses an old plain table style, not the glass design system.

**Classes used:** `table` (inline CSS, not main.css)

**Key inline styles:** All table styling is in a `<style>` tag inside `<head>`: `table { border-collapse: collapse; width: 100%; }` and `th, td { border: 1px solid #ddd; padding: 8px; }`

**JavaScript:** None

**Jinja2 variables:** `source`, `company_name`, `services` (list with `.service_name`, `.default_rate`, `.z_rate_service_id`)

**Notes:**
- This page is a complete redesign candidate — it's raw HTML from the early project, no glass aesthetic
- Navigation links use emoji icons (⬆, 📊, 💲)
- Form action `/admin/rates/{{ s.z_rate_service_id }}/set-default` for per-row rate editing
- NOT accessible from the main sidebar nav (sidebar links to `/rates` which likely goes elsewhere)

---

## inline-edit.js

**Purpose:** Enables click-to-edit on table cells marked with `class="editable"` in the summary/payroll pages.

**Classes it reads:**
- `td.editable` — cell must have this class to be editable
- `.inline-label` — the display span; hidden when editing
- `.inline-input` — the input shown when editing
- `td.editable.is-editing` — toggled by JS to show input, hide label
- `.gross-value[data-ride-id]` — for live recalc
- `.net-value[data-ride-id]` — for live recalc

**Data attributes it reads:** `data-ride-id` on `.inline-input`, `data-original` (set by JS on `input.dataset.original`)

**Behavior:**
- Click `.inline-label` → adds `is-editing` to parent `td.editable`, focuses `.inline-input`
- Enter → updates label text to input value, calls `recalcRow(rideId)` if present, removes `is-editing`
- Escape → restores original value, removes `is-editing`
- Blur → same as Enter (save + recalc)
- Input event → live recalc while typing (calls `recalcRow()`)
- `recalcRow(rideId)` → reads `#rate-{id}` and `#ded-{id}` inputs, updates `.gross-value` and `.net-value` spans; gross = rate, net = gross - deduction

**Notes:** This JS runs globally on every page (loaded in base.html). It only activates when `.editable` cells exist. No side effects on pages without editable cells.

---

## Global Patterns to Preserve

### 1. Pill Tab Filter Pattern
Used in summary, intelligence, insights, analytics, validate — always fully inline, never a CSS class. Active state uses blue tint (`rgba(59,130,246,...)`). Keep this exact pattern:
```html
<a href="..."
   style="padding:7px 16px; border-radius:999px; font-size:13px; font-weight:600; text-decoration:none; transition:all 0.15s;
          {# active #} background:rgba(59,130,246,0.18); border:1px solid rgba(59,130,246,0.4); color:#93c5fd;
          {# inactive #} background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.1); color:rgba(255,255,255,0.5);">
```

### 2. KPI Card Pattern
Used in intelligence, payroll_history_detail, validate, insights, analytics. Each card has a unique color tint. Standard structure:
```html
<div style="background:rgba({R},{G},{B},0.07); border:1px solid rgba({R},{G},{B},0.2); border-radius:12px; padding:18px 20px;">
  <div style="font-size:11px; text-transform:uppercase; letter-spacing:0.08em; color:rgba({R},{G},{B},0.6); margin-bottom:8px;">LABEL</div>
  <div style="font-size:26px; font-weight:700; color:#{hex}; letter-spacing:-0.5px;">VALUE</div>
  <div style="font-size:11px; color:rgba(255,255,255,0.3); margin-top:4px;">sub-label</div>
</div>
```

### 3. Loss Row Highlighting
Negative profit rows get: `background:rgba(248,113,113,0.04)` on `<tr>`. Used in analytics, intelligence, insights, validate. This must survive the rebuild.

### 4. 80% Cutoff Line (Pareto)
Cutoff row: `background:rgba(251,191,36,0.08); border-bottom:2px solid rgba(251,191,36,0.35)` on `<tr>`. Badge: inline pill `color:#fbbf24`. The double border-bottom is intentional — it creates a visible "line" effect.

### 5. Column Color Coding
Financial columns always use the same colors:
- Revenue / Partner Paid → `#93c5fd` (blue)
- Driver Cost → `#f87171` (red)
- Profit → `#34d399` (green) or `#a78bfa` (purple-ish in payroll history)
- Margin → `#a5b4fc` (violet)
- Withheld → `#fbbf24` (gold)
- Paid Out → `#34d399` (green)

These are set on both `<th>` (header) and `<td>` (cell), consistently. They are NOT in CSS variables — they must be defined as new CSS tokens in the rebuild.

### 6. Progress Bar Pattern (Pareto)
```html
<div style="background:rgba(255,255,255,0.06); border-radius:999px; height:6px; overflow:hidden;">
  <div style="height:100%; width:{{ pct }}%; background:linear-gradient(90deg,...); border-radius:999px;"></div>
</div>
```
Bar color depends on cumulative_pct: ≤80% = green gradient, at cutoff = yellow, over 80% = faint white.

### 7. Section Label Pattern
Repeated across intelligence, analytics, insights for subsection headers inside the glass-card:
```html
<h2 style="font-size:14px; font-weight:600; color:rgba(255,255,255,0.5); text-transform:uppercase; letter-spacing:0.08em; margin:0 0 12px;">
  Section Title <span style="font-weight:400; font-size:12px; color:rgba(52,211,153,0.4);">sub-note</span>
</h2>
```

### 8. Warning/Info Banner Pattern
Yellow warning: `background:rgba(251,191,36,0.07); border:1px solid rgba(251,191,36,0.2); border-radius:10px; padding:11px 16px`
Red error: `background:rgba(248,113,113,0.08); border:1px solid rgba(248,113,113,0.2); border-radius:10px`
Blue info/Claude: `background:rgba(165,180,252,0.05); border:1px solid rgba(165,180,252,0.18); border-radius:14px`

---

## Templates Needing Full Redesign (Not Audited)

These templates exist but are legacy / not currently in active use via the main nav:

- `people_list.html` — legacy, uses `class="table"`, no glass design
- `people.html` — legacy, same issue
- `admin/rates_list.html` — legacy standalone HTML, no glass design
- `rides.html` — not audited (legacy)
- `uploading.html` — not audited
- `people_companies.html`, `people_batches.html`, `people_weeks.html`, `people_week_people.html`, `people_person_rides.html` — legacy people sub-pages not audited
- `upload_success.html` — not audited
- `dispatch_everdriven.html`, `dispatch_everdriven_auth.html`, `dispatch_assign.html` — not audited
- `rates_unmatched.html` — not audited
- `pareto.html` — likely superseded by intelligence.html Pareto tab, not audited
- `admin/rate_overrides.html` — not audited

---

## CSS Classes Inventory (from main.css — complete list)

Layout: `zpay-layout`, `zpay-sidebar`, `zpay-sidebar-footer`, `zpay-main`, `zpay-page-header`, `zpay-logo`, `zpay-logo-sub`, `zpay-nav`, `nav-section-label`

Glass: `glass-card`, `stat-grid`, `stat-card`, `stat-card-label`, `stat-card-value`, `stat-card-trend` (+ `.up`, `.down`, `.neutral`)

Tables: `glass-table`, `net-pay-cell`, `total-label`, `total-value`, `loss-row`

Navigation: `.zpay-nav a`, `.zpay-nav a.active`, `.zpay-nav a svg`

Buttons: `btn`, `btn-ghost`, `btn-primary`, `btn-green`, `btn-secondary`, `btn-danger`

Links: `row-link`, `back-link`

Upload: `upload-grid`, `upload-card`

Inline edit: `editable`, `is-editing`, `inline-label`, `inline-input`

Empty: `empty-state`

Badges: `badge`, `badge-green`, `badge-red`, `badge-yellow`

Forms: `form-actions`, `.form-actions .hint`

Meta bar: `meta-bar`, `meta-bar-info`, `meta-bar-title`, `meta-bar-detail`, `meta-bar-actions`

Section: `section-header`

Filter tabs: `filter-tabs`, `filter-tab`, `filter-tab.active`

Utility: `text-green`, `text-red`, `text-yellow`, `text-accent`, `text-muted`, `text-secondary`, `text-right`, `text-center`, `font-mono`, `divider`

Profit helpers: `profit-positive`, `profit-negative`, `profit-neutral`

Animations: `alert-pulse` (keyframes)

Responsive: `.zpay-sidebar.open` (mobile toggle)

---

## Classes Defined in main.css but NOT Used in Audited Templates

`stat-grid`, `stat-card`, `stat-card-label`, `stat-card-value`, `stat-card-trend` (all .up/.down/.neutral), `meta-bar`, `meta-bar-info`, `meta-bar-title`, `meta-bar-detail`, `meta-bar-actions`, `section-header`, `filter-tabs`, `filter-tab`, `row-link`, `back-link`, `btn-secondary`, `btn-danger`, `badge`, `badge-green`, `badge-red`, `badge-yellow`, `loss-row`, `profit-positive`, `profit-negative`, `profit-neutral`, `form-actions`, `divider`, `text-green`, `text-red`, `text-yellow`, `text-accent`, `text-secondary`, `font-mono`

These are all defined and ready for use but the current templates bypass them with inline styles. The rebuild should migrate inline patterns into these (and new) classes.
