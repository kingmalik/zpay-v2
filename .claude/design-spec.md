# Z-Pay Design System Spec — Command Center Aesthetic

**Version:** 2.0
**Status:** Source of truth for all UI rebuild agents
**Replaces:** Apple Glass (dark navy, frosted glass, top pill nav)
**New Direction:** Modern ops command center — Linear / Vercel / Planetscale aesthetic

---

## 0. Summary of Changes

| Before | After |
|---|---|
| Top pill navigation bar | Fixed left sidebar 240px |
| `max-width` centered column | Full-width main content area |
| `backdrop-filter: blur(...)` frosted glass | Solid subtle backgrounds, no blur |
| Blue accent (`#6c63ff` or similar) | Indigo accent (`#6366f1`) |
| Deep navy background | Near-black with subtle indigo radial gradient |
| Single full-page `.glass-card` wrapper | Section-level glass cards only, direct main area render |

---

## 1. Layout Architecture

### Structure

Every page uses a two-column layout: fixed sidebar on the left, scrollable main content on the right.

```
+------------------+-----------------------------------------------+
|   .zpay-sidebar  |              .zpay-main                       |
|   (240px fixed)  |   (margin-left: 240px, full remaining width)  |
|                  |                                               |
|   Logo           |   .zpay-page-header                          |
|   Nav groups     |     h1 + subtitle p                          |
|   Footer         |                                               |
|                  |   .stat-grid (optional KPI row)              |
|                  |                                               |
|                  |   .glass-card sections                        |
|                  |   .glass-card sections                        |
+------------------+-----------------------------------------------+
```

### Key Rules

- Sidebar: `position: fixed; top: 0; left: 0; width: 240px; height: 100vh; overflow-y: auto; z-index: 100`
- Main content: `margin-left: 240px; padding: 32px 36px 60px; min-height: 100vh`
- **No** top nav bar (`<nav>` or `.nav-pill` or `.top-nav` style elements must be removed from `base.html`)
- **No** single wrapping `.glass-card` around the entire page content — `{% block content %}` renders directly into `.zpay-main`
- Individual page templates keep their own `.glass-card` sections as sub-components
- Body must have `margin: 0; padding: 0` — no top padding reserved for old nav

---

## 2. Color System

All values are CSS custom properties defined on `:root` in `base.html`'s `<style>` block (or a shared stylesheet).

```css
:root {
  /* Backgrounds */
  --bg-base:          #07070e;
  --bg-sidebar:       #0c0c17;
  --bg-card:          rgba(255, 255, 255, 0.03);
  --bg-card-hover:    rgba(255, 255, 255, 0.05);

  /* Borders */
  --border-subtle:    rgba(255, 255, 255, 0.07);
  --border-strong:    rgba(255, 255, 255, 0.14);

  /* Accent (Indigo) */
  --accent:           #6366f1;
  --accent-glow:      rgba(99, 102, 241, 0.30);
  --accent-soft:      rgba(99, 102, 241, 0.10);
  --accent-hover:     #5254cc;

  /* Status Colors */
  --green:            #10b981;
  --green-glow:       rgba(16, 185, 129, 0.25);
  --green-soft:       rgba(16, 185, 129, 0.10);
  --red:              #ef4444;
  --red-soft:         rgba(239, 68, 68, 0.10);
  --yellow:           #f59e0b;
  --yellow-soft:      rgba(245, 158, 11, 0.10);

  /* Text */
  --text-primary:     rgba(255, 255, 255, 0.90);
  --text-secondary:   rgba(255, 255, 255, 0.48);
  --text-muted:       rgba(255, 255, 255, 0.24);

  /* Border Radius */
  --radius-sm:        8px;
  --radius-md:        12px;
  --radius-lg:        16px;
  --radius-xl:        24px;
  --radius-pill:      999px;
}
```

### Body Background

Replace whatever background the `<body>` previously had with:

```css
body {
  margin: 0;
  padding: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', sans-serif;
  color: var(--text-primary);
  background:
    radial-gradient(ellipse at 15% 25%, rgba(99, 102, 241, 0.12) 0%, transparent 50%),
    radial-gradient(ellipse at 85% 75%, rgba(99, 102, 241, 0.07) 0%, transparent 50%),
    linear-gradient(160deg, #07070e 0%, #09091a 50%, #07070e 100%);
  background-attachment: fixed;
  min-height: 100vh;
}
```

---

## 3. Sidebar Component

### HTML Structure

```html
<aside class="zpay-sidebar">
  <div class="zpay-logo">
    <a href="/summary">Z-Pay</a>
    <span class="zpay-logo-sub">Ops Dashboard</span>
  </div>

  <nav class="zpay-nav">
    <div class="nav-section-label">Main</div>
    <a href="/summary">
      <!-- SVG icon --> Summary
    </a>
    <!-- more links -->
  </nav>

  <div class="zpay-sidebar-footer">
    Z-Pay v2 &bull; jarvis-dev
  </div>
</aside>
```

### CSS

```css
.zpay-sidebar {
  position: fixed;
  top: 0;
  left: 0;
  width: 240px;
  height: 100vh;
  overflow-y: auto;
  background: var(--bg-sidebar);
  border-right: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  z-index: 100;
  scrollbar-width: thin;
  scrollbar-color: var(--border-subtle) transparent;
}

/* Logo area */
.zpay-logo {
  height: 64px;
  padding: 0 20px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  border-bottom: 1px solid var(--border-subtle);
  flex-shrink: 0;
}

.zpay-logo a {
  font-size: 17px;
  font-weight: 700;
  color: var(--text-primary);
  text-decoration: none;
  letter-spacing: -0.3px;
}

.zpay-logo-sub {
  font-size: 10px;
  color: var(--text-muted);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-top: 2px;
}

/* Navigation */
.zpay-nav {
  flex: 1;
  padding: 8px 8px;
  overflow-y: auto;
}

.nav-section-label {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.10em;
  color: var(--text-muted);
  font-weight: 600;
  padding: 16px 8px 6px;
  user-select: none;
}

.zpay-nav a {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
  text-decoration: none;
  transition: background 0.15s, color 0.15s;
  margin: 1px 0;
  position: relative;
}

.zpay-nav a svg {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  stroke: currentColor;
  fill: none;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
  opacity: 0.6;
  transition: opacity 0.15s;
}

.zpay-nav a:hover {
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-primary);
}

.zpay-nav a:hover svg {
  opacity: 1;
}

.zpay-nav a.active {
  background: var(--accent-soft);
  color: var(--accent);
  border-left: 2px solid var(--accent);
  padding-left: 10px; /* compensates for the 2px border */
}

.zpay-nav a.active svg {
  opacity: 1;
}

/* Sidebar footer */
.zpay-sidebar-footer {
  padding: 16px 20px;
  font-size: 11px;
  color: var(--text-muted);
  border-top: 1px solid var(--border-subtle);
  flex-shrink: 0;
}
```

---

## 4. Main Content Area

### HTML Structure

```html
<main class="zpay-main">
  <div class="zpay-page-header">
    <h1>Page Title</h1>
    <p>Optional subtitle or context</p>
  </div>

  <!-- Optional KPI row -->
  <div class="stat-grid">...</div>

  <!-- Page-specific content sections -->
  <div class="glass-card">...</div>
</main>
```

### CSS

```css
.zpay-main {
  margin-left: 240px;
  padding: 32px 36px 60px;
  min-height: 100vh;
}

.zpay-page-header {
  margin-bottom: 24px;
}

.zpay-page-header h1 {
  font-size: 24px;
  font-weight: 700;
  letter-spacing: -0.4px;
  color: var(--text-primary);
  margin: 0 0 4px 0;
}

.zpay-page-header p {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0;
}
```

---

## 5. Glass Card (Updated)

Still used within page templates as section containers. The key change is removing `backdrop-filter`.

```css
.glass-card {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  overflow: hidden;
  box-shadow:
    0 1px 3px rgba(0, 0, 0, 0.30),
    0 20px 60px rgba(0, 0, 0, 0.20);
  /* NO backdrop-filter — removed intentionally */
  margin-bottom: 20px;
}

.glass-card-header {
  padding: 20px 24px 16px;
  border-bottom: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.glass-card-header h2,
.glass-card-header h3 {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
  letter-spacing: -0.2px;
}

.glass-card-body {
  padding: 20px 24px;
}
```

---

## 6. Stat Cards (KPI Row)

Used for top-line metrics like "Avg Profit / Ride", "Total Revenue", etc.

### HTML

```html
<div class="stat-grid">
  <div class="stat-card">
    <div class="stat-card-label">Avg Profit / Ride</div>
    <div class="stat-card-value">$8.42</div>
    <div class="stat-card-sub">
      <span class="stat-card-trend up">+12%</span> vs last period
    </div>
  </div>
  <!-- repeat -->
</div>
```

### CSS

```css
.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
  margin-bottom: 28px;
}

.stat-card {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  padding: 20px;
  position: relative;
  overflow: hidden;
  transition: border-color 0.15s;
}

.stat-card:hover {
  border-color: var(--border-strong);
}

/* Optional accent glow bar on top */
.stat-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: linear-gradient(90deg, var(--accent), transparent);
  opacity: 0;
  transition: opacity 0.15s;
}

.stat-card:hover::before {
  opacity: 1;
}

.stat-card-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-muted);
  font-weight: 600;
  margin-bottom: 8px;
}

.stat-card-value {
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.5px;
  color: var(--text-primary);
  margin-bottom: 4px;
  line-height: 1;
}

.stat-card-sub {
  font-size: 12px;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.stat-card-trend {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: var(--radius-pill);
}

.stat-card-trend.up {
  color: var(--green);
  background: var(--green-soft);
}

.stat-card-trend.down {
  color: var(--red);
  background: var(--red-soft);
}

.stat-card-trend.neutral {
  color: var(--text-secondary);
  background: rgba(255, 255, 255, 0.05);
}
```

---

## 7. Tables

`.glass-table` class stays. Updated to match command center density.

```css
.glass-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.glass-table thead {
  background: rgba(255, 255, 255, 0.025);
  border-bottom: 1px solid var(--border-subtle);
}

.glass-table th {
  padding: 12px 16px;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: var(--text-muted);
  font-weight: 600;
  text-align: left;
  white-space: nowrap;
}

.glass-table td {
  padding: 13px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  color: var(--text-primary);
  vertical-align: middle;
}

.glass-table tr:last-child td {
  border-bottom: none;
}

.glass-table tbody tr:hover td {
  background: rgba(255, 255, 255, 0.025);
}

.glass-table tfoot {
  background: rgba(99, 102, 241, 0.06);
  border-top: 1px solid rgba(99, 102, 241, 0.20);
}

.glass-table tfoot td {
  padding: 13px 16px;
  font-weight: 600;
  color: var(--text-secondary);
  border-bottom: none;
}

.glass-table tfoot .total-value {
  color: var(--green);
  font-weight: 700;
}
```

---

## 8. Buttons

Accent color updated from blue to indigo. All other button classes remain structurally identical.

```css
.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: var(--radius-sm);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border: 1px solid transparent;
  transition: all 0.15s;
  text-decoration: none;
  white-space: nowrap;
}

.btn-primary {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
  box-shadow: 0 4px 16px var(--accent-glow);
}

.btn-primary:hover {
  background: var(--accent-hover);
  border-color: var(--accent-hover);
  box-shadow: 0 6px 20px var(--accent-glow);
}

.btn-secondary {
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-secondary);
  border-color: var(--border-subtle);
}

.btn-secondary:hover {
  background: rgba(255, 255, 255, 0.10);
  color: var(--text-primary);
  border-color: var(--border-strong);
}

.btn-danger {
  background: rgba(239, 68, 68, 0.12);
  color: var(--red);
  border-color: rgba(239, 68, 68, 0.25);
}

.btn-danger:hover {
  background: rgba(239, 68, 68, 0.20);
  border-color: rgba(239, 68, 68, 0.40);
}

.btn-sm {
  padding: 5px 10px;
  font-size: 12px;
}

.btn-lg {
  padding: 11px 22px;
  font-size: 14px;
}
```

---

## 9. Badges, Pills, Alerts

### Alert Badge (nav indicator)

```css
/* Alert count badge on sidebar nav link */
.nav-badge {
  margin-left: auto;
  background: var(--red);
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: var(--radius-pill);
  min-width: 18px;
  text-align: center;
  animation: pulse-badge 2s infinite;
}

@keyframes pulse-badge {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}
```

### General Badge

```css
.badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  font-size: 11px;
  font-weight: 600;
  background: var(--accent-soft);
  color: var(--accent);
  white-space: nowrap;
}

.badge-green {
  background: var(--green-soft);
  color: var(--green);
}

.badge-red {
  background: var(--red-soft);
  color: var(--red);
}

.badge-yellow {
  background: var(--yellow-soft);
  color: var(--yellow);
}

.badge-muted {
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-secondary);
}
```

### Status Pills

Reuse `.badge` with color variants above. No change to behavior.

---

## 10. Utility Classes

```css
/* Text */
.text-primary   { color: var(--text-primary); }
.text-secondary { color: var(--text-secondary); }
.muted          { color: var(--text-secondary); }
.text-muted     { color: var(--text-muted); }
.text-right     { text-align: right; }
.text-center    { text-align: center; }
.text-accent    { color: var(--accent); }
.text-green     { color: var(--green); }
.text-red       { color: var(--red); }
.text-yellow    { color: var(--yellow); }

/* Payroll-specific */
.net-pay-cell {
  color: var(--green);
  font-weight: 600;
}

.total-label {
  text-transform: uppercase;
  color: var(--text-secondary);
  font-size: 11px;
  letter-spacing: 0.06em;
}

.total-value {
  color: var(--green);
  font-size: 15px;
  font-weight: 700;
}

/* Links */
.row-link {
  color: var(--accent);
  text-decoration: none;
  font-weight: 500;
}

.row-link:hover {
  color: #818cf8; /* lighter indigo */
  text-decoration: underline;
}

.back-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 13px;
  margin-bottom: 16px;
  transition: color 0.15s;
}

.back-link:hover {
  color: var(--text-primary);
}

/* Empty state */
.empty-state {
  padding: 48px 24px;
  text-align: center;
  color: var(--text-secondary);
  font-size: 14px;
}

.empty-state-icon {
  font-size: 32px;
  margin-bottom: 12px;
  opacity: 0.4;
}

/* Layout helpers */
.flex          { display: flex; }
.flex-center   { display: flex; align-items: center; }
.flex-between  { display: flex; align-items: center; justify-content: space-between; }
.gap-8         { gap: 8px; }
.gap-12        { gap: 12px; }
.gap-16        { gap: 16px; }
.mt-4          { margin-top: 4px; }
.mt-8          { margin-top: 8px; }
.mt-16         { margin-top: 16px; }
.mt-24         { margin-top: 24px; }
.mb-16         { margin-bottom: 16px; }
.mb-24         { margin-bottom: 24px; }
```

---

## 11. Active Nav Detection (JavaScript)

Because Jinja2 templates don't have access to `request.url` in the base layout by default, use client-side JS to set the active nav link. This snippet goes at the **bottom of `<body>`** in `base.html`.

```html
<script>
(function() {
  var path = window.location.pathname;
  var links = document.querySelectorAll('.zpay-nav a');
  var best = null;
  var bestLen = 0;

  links.forEach(function(link) {
    var href = link.getAttribute('href');
    if (!href) return;
    // Exact match always wins; otherwise longest prefix match
    if (path === href || (path.startsWith(href) && href !== '/' && href.length > bestLen)) {
      best = link;
      bestLen = href.length;
    }
  });

  if (best) {
    best.classList.add('active');
  }
})();
</script>
```

**Edge cases handled:**
- `/payroll/history` correctly matches `/payroll/history` rather than a shorter `/payroll` prefix
- `/summary` won't accidentally match `/summary/detail` unless that's intended
- Multiple matches: longest href wins

---

## 12. Nav Structure (base.html)

Exact nav items, section groupings, hrefs, and icon descriptions for `base.html`. Use Feather Icons inline SVG or equivalent.

```html
<nav class="zpay-nav">

  <!-- MAIN -->
  <div class="nav-section-label">Main</div>

  <a href="/summary">
    <svg viewBox="0 0 24 24"><!-- house / home icon -->
      <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
      <polyline points="9 22 9 12 15 12 15 22"/>
    </svg>
    Summary
  </a>

  <a href="/people">
    <svg viewBox="0 0 24 24"><!-- users icon -->
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
      <circle cx="9" cy="7" r="4"/>
      <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
      <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
    </svg>
    People
  </a>

  <a href="/payroll/history">
    <svg viewBox="0 0 24 24"><!-- calendar icon -->
      <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
      <line x1="16" y1="2" x2="16" y2="6"/>
      <line x1="8" y1="2" x2="8" y2="6"/>
      <line x1="3" y1="10" x2="21" y2="10"/>
    </svg>
    Payroll History
  </a>

  <!-- INTELLIGENCE -->
  <div class="nav-section-label">Intelligence</div>

  <a href="/intelligence">
    <svg viewBox="0 0 24 24"><!-- activity / pulse icon -->
      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
    </svg>
    Intelligence
  </a>

  <!-- OPS -->
  <div class="nav-section-label">Ops</div>

  <a href="/dispatch">
    <svg viewBox="0 0 24 24"><!-- send icon -->
      <line x1="22" y1="2" x2="11" y2="13"/>
      <polygon points="22 2 15 22 11 13 2 9 22 2"/>
    </svg>
    Dispatch
  </a>

  <a href="/dispatch/assign">
    <svg viewBox="0 0 24 24"><!-- plus-circle icon -->
      <circle cx="12" cy="12" r="10"/>
      <line x1="12" y1="8" x2="12" y2="16"/>
      <line x1="8" y1="12" x2="16" y2="12"/>
    </svg>
    Smart Assign
  </a>

  <a href="/upload">
    <svg viewBox="0 0 24 24"><!-- upload-cloud icon -->
      <polyline points="16 16 12 12 8 16"/>
      <line x1="12" y1="12" x2="12" y2="21"/>
      <path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/>
    </svg>
    Upload
  </a>

  <a href="/batches">
    <svg viewBox="0 0 24 24"><!-- list icon -->
      <line x1="8" y1="6" x2="21" y2="6"/>
      <line x1="8" y1="12" x2="21" y2="12"/>
      <line x1="8" y1="18" x2="21" y2="18"/>
      <line x1="3" y1="6" x2="3.01" y2="6"/>
      <line x1="3" y1="12" x2="3.01" y2="12"/>
      <line x1="3" y1="18" x2="3.01" y2="18"/>
    </svg>
    Batches
  </a>

  <!-- ADMIN -->
  <div class="nav-section-label">Admin</div>

  <a href="/rates">
    <svg viewBox="0 0 24 24"><!-- dollar-sign icon -->
      <line x1="12" y1="1" x2="12" y2="23"/>
      <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>
    </svg>
    Rates
  </a>

  <a href="/alerts">
    <svg viewBox="0 0 24 24"><!-- bell icon -->
      <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
      <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
    </svg>
    Alerts
    <!-- Alert badge injected by Jinja2 if count > 0: -->
    {% if alert_count and alert_count > 0 %}
    <span class="nav-badge">{{ alert_count }}</span>
    {% endif %}
  </a>

  <a href="/validate">
    <svg viewBox="0 0 24 24"><!-- check-circle icon -->
      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
      <polyline points="22 4 12 14.01 9 11.01"/>
    </svg>
    Validate
  </a>

  <a href="/docs" target="_blank">
    <svg viewBox="0 0 24 24"><!-- file-text icon -->
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
      <polyline points="14 2 14 8 20 8"/>
      <line x1="16" y1="13" x2="8" y2="13"/>
      <line x1="16" y1="17" x2="8" y2="17"/>
      <polyline points="10 9 9 9 8 9"/>
    </svg>
    Docs
  </a>

</nav>
```

---

## 13. Page-Specific Notes for Agents

Each page uses `{% extends "base.html" %}` and `{% block content %}`. No structural change is needed in the templates themselves — all changes are in `base.html` (nav → sidebar, body padding, color vars).

| Template | Notes |
|---|---|
| `summary.html` | Top-level payroll page. Company tabs, batch filter, summary table. Works as-is. |
| `intelligence.html` | Tab system (Analytics / Pareto / Insights), company filter, date range. Keep all JS tab logic intact — do not refactor. |
| `upload.html` | Has `.upload-grid` and `.upload-card` classes. Keep those, they are self-contained. |
| `batches.html` | Standard `.glass-table` list page. |
| `payroll_history.html` | History list. Uses `.glass-card` sections. |
| `payroll_history_detail.html` | Detail view. Uses back-link pattern. |
| `people_list.html` | People directory table. |
| `dispatch.html`, `dispatch_assign.html` | Operational live pages — keep JS/polling intact. |
| `validate.html` | Validation results. May use progress indicators. |
| `admin/rates_list.html` | Rate management table. |

**What agents must NOT change:**
- Any page's `{% block content %}` structure
- Tab switching JS in `intelligence.html`
- Upload form handlers
- Table column definitions (only visual styling updates)
- Database-bound variable names in templates

**What agents MUST change:**
- Remove any `backdrop-filter: blur(...)` from `.glass-card` in base styles
- Remove the top `<nav>` / pill nav from `base.html`
- Add `.zpay-sidebar` + `.zpay-main` layout to `base.html`
- Update accent color references from old blue to `var(--accent)`
- Add all CSS custom properties to `:root`
- Add active nav detection JS snippet at bottom of `<body>`

---

## 14. Full base.html Shell (Reference)

Agents building `base.html` should follow this shell exactly:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{% block title %}Z-Pay{% endblock %}</title>
  <style>
    /* === RESET === */
    *, *::before, *::after { box-sizing: border-box; }

    /* === DESIGN TOKENS === */
    :root {
      --bg-base:          #07070e;
      --bg-sidebar:       #0c0c17;
      --bg-card:          rgba(255,255,255,0.03);
      --bg-card-hover:    rgba(255,255,255,0.05);
      --border-subtle:    rgba(255,255,255,0.07);
      --border-strong:    rgba(255,255,255,0.14);
      --accent:           #6366f1;
      --accent-glow:      rgba(99,102,241,0.30);
      --accent-soft:      rgba(99,102,241,0.10);
      --accent-hover:     #5254cc;
      --green:            #10b981;
      --green-glow:       rgba(16,185,129,0.25);
      --green-soft:       rgba(16,185,129,0.10);
      --red:              #ef4444;
      --red-soft:         rgba(239,68,68,0.10);
      --yellow:           #f59e0b;
      --yellow-soft:      rgba(245,158,11,0.10);
      --text-primary:     rgba(255,255,255,0.90);
      --text-secondary:   rgba(255,255,255,0.48);
      --text-muted:       rgba(255,255,255,0.24);
      --radius-sm:        8px;
      --radius-md:        12px;
      --radius-lg:        16px;
      --radius-xl:        24px;
      --radius-pill:      999px;
    }

    /* === BODY === */
    body {
      margin: 0;
      padding: 0;
      font-family: -apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', sans-serif;
      color: var(--text-primary);
      background:
        radial-gradient(ellipse at 15% 25%, rgba(99,102,241,0.12) 0%, transparent 50%),
        radial-gradient(ellipse at 85% 75%, rgba(99,102,241,0.07) 0%, transparent 50%),
        linear-gradient(160deg, #07070e 0%, #09091a 50%, #07070e 100%);
      background-attachment: fixed;
      min-height: 100vh;
    }

    /* === ALL CSS FROM SECTIONS 3-10 ABOVE === */
    /* Insert: sidebar, main, glass-card, stat-grid, glass-table, buttons, badges, utilities */

    /* === PAGE-SPECIFIC BLOCK === */
    {% block styles %}{% endblock %}
  </style>
</head>
<body>

  <!-- SIDEBAR -->
  <aside class="zpay-sidebar">
    <div class="zpay-logo">
      <a href="/summary">Z-Pay</a>
      <span class="zpay-logo-sub">Ops Dashboard</span>
    </div>
    <nav class="zpay-nav">
      <!-- Nav from Section 12 -->
    </nav>
    <div class="zpay-sidebar-footer">
      Z-Pay v2 &bull; jarvis-dev
    </div>
  </aside>

  <!-- MAIN CONTENT -->
  <main class="zpay-main">
    {% block content %}{% endblock %}
  </main>

  <!-- Active nav detection -->
  <script>
  (function() {
    var path = window.location.pathname;
    var links = document.querySelectorAll('.zpay-nav a');
    var best = null;
    var bestLen = 0;
    links.forEach(function(link) {
      var href = link.getAttribute('href');
      if (!href || href === '#') return;
      if (path === href || (path.startsWith(href) && href !== '/' && href.length > bestLen)) {
        best = link;
        bestLen = href.length;
      }
    });
    if (best) best.classList.add('active');
  })();
  </script>

  {% block scripts %}{% endblock %}
</body>
</html>
```

---

## 15. Migration Checklist for Each Agent

When an agent is assigned to update `base.html` or a page template, verify:

- [ ] `:root` CSS vars are defined with exact values from Section 2
- [ ] Body background is the 3-layer radial + linear gradient (Section 2)
- [ ] Old top `<nav>` / pill nav is removed
- [ ] `.zpay-sidebar` is present with correct structure (Section 3)
- [ ] `.zpay-main` wraps `{% block content %}` (Section 4)
- [ ] `.glass-card` has NO `backdrop-filter` (Section 5)
- [ ] All old `#6c63ff` / `#5b57e0` / old blue accent references replaced with `var(--accent)`
- [ ] Active nav JS snippet is at the bottom of `<body>` (Section 11)
- [ ] Nav items match exactly the hrefs + sections in Section 13
- [ ] Alert badge slot is present on the `/alerts` nav link
- [ ] No page-level `{% block content %}` was structurally changed

---

*End of Z-Pay Design System Spec v2.0*
