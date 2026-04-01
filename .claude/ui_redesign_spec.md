# Z-Pay UI Redesign Spec — Light Mode
## Design Direction: Apple-clean, Futuristic Minimal, Animated

---

## Core Aesthetic
- **Mode:** Light (white/near-white base)
- **Feel:** Apple.com × Linear.app × Vercel Dashboard
- **Principle:** One thing per page, done beautifully. Drill down for details.
- **Animations:** Subtle fade-ins on load, number counters, smooth hover states, page transitions

---

## Color System
```
Background:       #F5F5F7   (Apple off-white)
Surface:          #FFFFFF   (cards, panels)
Surface elevated: #FAFAFA   (hover states)
Border:           #E5E5EA   (subtle dividers)
Text primary:     #1D1D1F   (Apple dark)
Text secondary:   #6E6E73   (Apple gray)
Text tertiary:    #AEAEB2   (labels, hints)
Accent:           #0071E3   (Apple blue)
Accent hover:     #0077ED
Success:          #34C759   (Apple green)
Warning:          #FF9F0A   (Apple orange)
Danger:           #FF3B30   (Apple red)
```

---

## Typography
```
Font: -apple-system, "SF Pro Display", BlinkMacSystemFont, sans-serif
Page title:    28px, weight 700, #1D1D1F
Section head:  18px, weight 600, #1D1D1F
Card label:    11px, weight 500, uppercase, letter-spacing 0.06em, #6E6E73
Body:          14px, weight 400, #1D1D1F
Number (KPI):  36px, weight 700, #1D1D1F
```

---

## Layout
- **Navigation:** Fixed top nav bar (64px tall), white, 1px bottom border #E5E5EA
  - Left: Z-Pay logo (wordmark, bold, #1D1D1F)
  - Center: Nav links (Dashboard, Payroll, Upload, People, Dispatch, Intelligence)
  - Right: Alerts badge + avatar/initials
- **No sidebar** — removed entirely
- **Content:** Max-width 1200px, centered, padding 32px horizontal
- **Page header:** Page title + subtitle, 40px top padding

---

## Component Patterns

### KPI Cards
- White background, 16px border-radius, subtle shadow (0 1px 3px rgba(0,0,0,0.08))
- Large number top, label below, trend indicator (arrow + %)
- Animate number from 0 on load (300ms ease-out)

### Tables
- White surface, clean rows, 1px #E5E5EA dividers
- Sticky header, alternating row hover (#F5F5F7)
- No zebra striping — hover only
- Pill badges for status (green/orange/red/blue)

### Buttons
- Primary: #0071E3 bg, white text, 8px radius, 36px height
- Secondary: White bg, #E5E5EA border, #1D1D1F text
- Ghost: Transparent, #0071E3 text
- All: 200ms transition on hover

### Page Transitions
- Fade in + slight upward slide (translateY 8px → 0, opacity 0 → 1, 250ms)
- On tab switch: instant fade (150ms)

---

## Pages to Redesign (All)

### 1. Dashboard (index)
- 4 KPI cards top row: Total Revenue, Total Profit, Active Drivers, Rides This Period
- Charts section: Revenue over time (line), Profit by source (bar)
- Recent activity feed (last 5 payroll runs)
- Clean, spacious, animated on load

### 2. Payroll
- Batch selector as segmented control (pill style)
- Driver table: Name, Rides, Gross, Rate, Net — clean rows
- "Run Payroll" CTA button top right
- Summary bar above table (totals)

### 3. Upload
- Two large upload zones side by side (Acumen left, Maz right)
- Drag-and-drop with dashed border, icon, label
- Progress state, success state with green checkmark animation

### 4. People
- Grid of driver cards (not table) — name, photo placeholder, ID, status badge
- Search bar top
- Click → detail page

### 5. Intelligence
- Tab strip: Analytics / Insights / Pareto
- Charts and tables per tab, minimal, no info overload
- AI insight box styled as a clean card with subtle blue left border

### 6. Dispatch
- Full-width live ride table
- Status pills, auto-refresh badge

### 7. Alerts
- Simple list, severity icons, dismiss button per alert

### 8. Rates / Validation
- Table-based, clean, same system

---

## Animation Spec
```css
/* Page load */
@keyframes fadeSlideIn {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}
.page-content { animation: fadeSlideIn 250ms ease-out; }

/* KPI number counter — JS */
/* Count from 0 to final value over 400ms on DOMContentLoaded */

/* Hover on cards */
.card { transition: box-shadow 200ms, transform 200ms; }
.card:hover { box-shadow: 0 4px 16px rgba(0,0,0,0.10); transform: translateY(-1px); }
```

---

## Agent Task Breakdown

### Agent 1 — CSS Architect
Build `/backend/static/css/zpay-light.css`
- Full design system: variables, reset, base, nav, cards, tables, buttons, badges, forms, animations
- ~600-800 lines

### Agent 2 — Base Template Builder
Rewrite `base.html`:
- Remove sidebar
- Add top nav with all links, alerts badge
- Include new CSS, remove old
- Add page transition JS

### Agent 3 — Dashboard + Payroll Pages
Rewrite `index.html` and `payroll.html` using new system

### Agent 4 — Upload + People Pages
Rewrite `upload.html`, `upload_success.html`, `people.html`, `people_person.html`

### Agent 5 — Intelligence + Other Pages
Rewrite `intelligence.html`, `dispatch_everdriven.html`, `alerts.html`, `rates_unmatched.html`, `validate.html`, `payroll_history.html`, `payroll_history_detail.html`

### Agent 6 — QA
- Hit every route, check for 200 status
- Check for broken template blocks, missing variables
- Report issues in `/tmp/qa_report.txt`

---

## Handoff Protocol
- Agent 1 writes CSS first, signals DONE by creating `/tmp/css_done.flag`
- Agent 2 reads CSS, rewrites base.html, signals `/tmp/base_done.flag`
- Agents 3/4/5 run in parallel after base is done
- Agent 6 runs last
