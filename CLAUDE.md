# Z-Pay — Claude Context

## The Business

Malik runs a transportation company with a large driver pool, partnered with two ride sources:

| Partner | Entity | Notes |
|---|---|---|
| FirstAlt | Acumen | AWS Cognito auth, trips via FirstAlt API |
| EverDriven | Maz | Playwright-based auth, EverDriven API |

The two partners operate under separate business entities (Acumen / Maz) to maintain a noncompete — they are not aware of each other. Same driver pool services both.

## What Z-Pay Is

Started as payroll tooling, now the **full business dashboard** running the entire operation. Built by Malik and his uncle.

## Current Features

- **Upload** — ingest ride data (PDF/Excel) from Acumen (FirstAlt) and Maz (EverDriven)
- **Payroll** — per-driver pay calculation with rates, overrides, batch/company filtering
- **Pay stubs** — PDF/Excel export + automated email delivery
- **Driver balance withholding** — hold pay <$100, carry forward to next batch
- **People directory** — driver profiles linked to FirstAlt + EverDriven IDs
- **Dispatch dashboard** — unified real-time ride view from both partners
- **Smart assign** — score/assign drivers to rides by location and time

### Intelligence Hub (`/intelligence`)
Unified dashboard with three tabs showing profitability-focused metrics:

**Analytics Tab** — Business metrics ranked by profit
- Avg Profit / Ride KPI card
- Route Profitability table (all routes ranked by total profit, margin %)
- Driver Profitability table (drivers ranked by profit, margin % added)
- Most Profitable Rides (top 10 by profit)

**Insights Tab** — AI-powered analysis + business patterns
- Most Profitable Drivers (sorted by profit, margin %)
- Most Profitable Routes (top 5)
- Least Profitable Routes (bottom 5, loss leaders highlighted in red)
- Highest Volume Routes (by ride count, includes profit column)
- Avg Profit / Ride KPI card
- Claude AI analysis (profit-centric, calls out specific drivers/routes, flags loss routes, compares Acumen vs Maz)

**Pareto Tab** — 80/20 profitability analysis
- Drivers ranked by profit (most/least profitable drivers)
- Routes ranked by profit (service types)
- Historical data snapshots

### Other Pages
- **Payroll History** — locked historical view of every payroll run, per driver with profit columns
- **Batch Management** — upload, delete, review rides with profit metrics
- **Rate Management** — outlier detection, smart variant resolver, auto-fix on startup
- **Alerts** — nav badge showing issues needing attention
- **Validation (`/validate`)** — Dry-run rate validator comparing Z-Pay calculations to partner files (non-destructive)

## Stack

- FastAPI + PostgreSQL + Alembic (migrations)
- Jinja2 templates (currently undergoing UI redesign — see UI Status below)
- Docker Compose for local dev (`docker compose up -d`)
- App runs at `http://localhost:8000`
- Claude API integrated for AI insights

## Branches

- `main` — stable
- `jarvis-dev` — active development branch

## Important Rules

- Acumen = FirstAlt rides. Maz = EverDriven rides. Never mix them.
- Always verify code state before assuming a feature is complete or missing.
- There is always more to build — ask Malik what's next.
- Profitability = `net_pay - z_rate` (driver payout minus driver cost)
- **Validation-first approach:** Build validators before loading data; use non-destructive testing
- **Design decisions before builds:** In visual/UI work, confirm direction with user before building the entire system

## Recent Updates (Session a6b14c01 — Final Phase)

### Data Validation & Fixes (2026-03-28)

**Acumen Rate Gap Resolution**
- Issue: 5.4% of rides had zero rates due to service name mismatches
- Root causes:
  1. Company name aliases ("Acumen" vs "Acumen International")
  2. Missing service variant registrations (148 services with suffixes like "(W)", "(F)", "(M/F)")
  3. Duplicate zero-rate rows
- Solution: Smart rate resolver with alias mapping + suffix stripping + all variants inserted
- Result: Variance reduced from -$5,559 to +$38 (one legitimate data gap)

**Maz Data Resolution**
- Issue: Validator reported weeks 4, 8, 11 missing
- Findings:
  - Weeks 4 & 8: Present in DB, false negative from date sensitivity (period_start off by 1 day)
  - Week 11: Genuinely missing, now imported (173 rides)
- Result: All 11 Maz batches complete with perfect rate matching

### New: Validation Route (`/validate`)
Dry-run rate validator for comparing Z-Pay calculations against partner data.

**Purpose:** Prove system calculates rates correctly by comparing file-provided amounts vs. DB-stored amounts (non-destructive)

**How it works:**
- User places files in ~/Downloads/Acumen/ or ~/Downloads/Maz/ subfolders
- Route parses files (Excel for Acumen, PDF for Maz)
- Runs rate resolver per ride without writing to database
- Aggregates by driver and week
- Reports variance between file-calculated and DB-stored amounts

**Files:**
- `backend/routes/validate.py` — Dry-run validator logic
- `backend/templates/validate.html` — Validation UI
- `scripts/validate_run.py` — Standalone validation script
- Registered in `backend/app.py`

### Key Discoveries

**System Accuracy (Current)**
- Total rides: 5,976 (Acumen 4,060 + Maz 1,916)
- Rides with rates: 5,976 (0 unmatched)
- System accuracy: 99.98% (1 legitimate gap)

**File Source Stability**
- Acumen: Original DB import files are identical to Google Drive files. Use validator instead of re-uploading (prevents duplicates).
- Maz: Original DB was imported from PDFs (same as Google Drive downloads), not Excel. Different formats but consistent source.

**Date Matching Sensitivity**
- Validator's "missing weeks" revealed hypersensitivity to date matching
- Recommendation: Future validators should use date ranges, not exact matches

**Validation as User-Facing Feature**
- Validation endpoint is not just internal QA—it's a proof mechanism
- Proves to Malik that Z-Pay calculations are mathematically sound
- Enables confidence before production deployment

### MCP Integration (2026-03-28)
**Status:** Registered and configured
- **Stitch MCP** — Google Material Design system (API key placeholder, Node 21.7+ required for init wizard)
- **Nano Banana 2 MCP** — Gemini image generation (active and tested)
- **21st.dev** — Design system research initiated (component library integration pending decision)

## Current UI Status (Session df75909b — 2026-03-28)

### UI Redesign Attempt: REJECTED
**Status:** ⏸️ Awaiting user decision on design direction

**What Was Built:**
- 7-agent swarm executed a complete ground-up UI redesign
- New design system: Indigo accent (`#6366f1`), sidebar navigation, modern component architecture
- 1,187-line CSS system with component-based patterns
- All 14+ templates migrated from inline styles to CSS classes
- Dispatch page: Successfully migrated from 100% inline styles
- All tested routes returning 200 status

**User Feedback:**
- Malik reviewed the redesigned UI and rejected it
- Feedback: "i dont like it" / "everything"
- Indicates comprehensive dissatisfaction with the aesthetic/UX direction, not implementation quality

**Current State:**
- New design is live in Docker container
- All changes are uncommitted in `jarvis-dev` branch
- Can be rolled back with `git checkout .`
- Awaiting Malik's choice: Roll back to old Apple Glass design OR start over with new direction

**Next Steps When Malik Returns:**
1. Get explicit decision: rollback or redesign?
2. If redesign: Ask design questions FIRST (layout, colors, aesthetic) before building
3. If rollback: `git checkout .`, restart Docker, return to status quo

**Key Learning:**
- Multi-agent coordination via file-based specs worked exceptionally well
- BUT: Autonomous design decision without user input was a mistake
- Pattern: Design approval → THEN build system (not the reverse)

## Non-Obvious Patterns (For Future Sessions)

### Malik's Development Model
1. **Validation-first:** Builds validators before trusting data
2. **Parallel execution:** Works on multiple concerns simultaneously (data validation + UI design system research)
3. **Autonomous delegation:** Launches agents, lets them work independently
4. **Mathematical proof:** Variance tables convince more than anecdotes
5. **Non-destructive testing:** Always validate before modifying DB
6. **Design vision matters:** Won't compromise on aesthetic; rejects systems that don't match vision
7. **Direct feedback:** Clear about what doesn't work; expects efficient course correction

### Code Patterns That Work
- Two-phase rate lookups (preference + fallback) are more robust than single-phase
- Alias logic should be permanent in resolvers, not one-time fixes
- Zero rates need special handling (skip in preference, fall back if needed)
- Suffix-stripping with normalized comparisons scales better than exact matches
- File-based agent communication (shared specs) enables true parallel multi-agent work

### What to Build Next
- Ask Malik directly ("What should we build next?")
- Follow same cycle: understand → launch agents → validate → polish
- Include validation layer in every new feature
- For visual/design work: Get approval on direction BEFORE building the full system
