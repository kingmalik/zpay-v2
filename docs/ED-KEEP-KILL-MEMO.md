# EverDriven (Maz Services) — Keep / Kill Memo
**For the family meeting, weekend of 2026-07-25/26. Decision is Malik's — this is the case file, not the verdict.**

---

## The one-line version

ED is small, roughly break-even-to-slightly-profitable on actual rides, currently dormant (summer/ESY), carries a real legal question (noncompete tied to the two-LLC structure), and Z-Pay has no visibility into whether ED's mandatory $2/trip insurance deduction is even landing correctly. **Recommendation: keep-idle through summer, force a renegotiation conversation before the September restart, with exit-at-season-boundary as the fallback if ED won't move.**

---

## Revenue trend (queried live from prod DB, 2026-07-23, read-only)

`ride` table, `source = 'maz'`, Jan 1 – Jul 10 2026 (most recent ED ride on file: 2026-07-10 — ED is currently inactive).

**Clean per-ride numbers (excludes batch-level reconciliation-adjustment entries — see note below):**

| Month | Rides | Revenue (net_pay) | Driver cost (z_rate) | Margin | Active drivers |
|---|---|---|---|---|---|
| Jan 2026 | 627 | $30,696.54 | $28,480.34 | **+$2,216.20** | 23 |
| Feb 2026 | 626 | $29,453.84 | $28,269.03 | **+$1,184.81** | 23 |
| Mar 2026 | 778 | $32,817.00 | $35,345.49 | **-$2,528.49** | 20 |
| Apr 2026 | 431 | $17,268.87 | $18,946.00 | **-$1,677.13** | 21 |
| May 2026 | 617 | $31,497.56 | $27,661.00 | **+$3,836.56** | 17 |
| Jun 2026 | 386 | $20,145.19 | $17,269.00 | **+$2,876.19** | 15 |
| Jul 2026 (partial, thru 7/10) | 33 | $1,558.77 | $1,421.00 | **+$137.77** | 4 |
| **YTD total (clean)** | **3,498** | **$163,437.77** | **$157,392.86** | **+$6,044.91** | — |

**Trend read:** ride volume and driver count are both declining — 627→33 rides, 23→4 drivers, Jan to July. That's the summer dormancy pattern the business already expects (ESY winds down, mom travels), not a new problem. On a per-ride basis, ED has run modestly PROFITABLE this year (+$6k YTD margin), with two rough months (Mar, Apr) that self-corrected. This is a small, thin-margin side business, not a money pit — but it's also not a growth engine.

**Data-quality caveat (be aware of this before quoting numbers Saturday):** The raw `ride` table also contains 291 batch-level "gap-fill"/"reconciliation adjustment" entries (`RECONCILE_ADJ`, `W14_RECONSTRUCTED` service names) inserted when individual-ride data was missing for a batch. Most of these are zero-margin placeholders (net_pay set equal to z_rate — i.e., "we know what we paid drivers, we don't know what ED actually revenued, so assume break-even"). **One batch is not a placeholder: 276 adjustment rows dated May 2026 show driver cost ($31,340.67) exceeding recorded revenue ($11,315.57) by -$20,025.10.** That's either (a) a real, unresolved ED shortfall from May that never got reconciled, or (b) a data-entry/matching artifact from that period. Either way it's a $20k question mark sitting in the books, separate from the keep/kill call. **Action item: before the meeting, pull the May ED remittance and confirm whether that $20k gap is real money owed or a bookkeeping ghost.** No `partner_payment` (deposit-reconciliation) records exist for ED at all in Z-Pay — unlike FirstAlt, where every deposit is logged and disputed within 14 days per contract, ED deposits aren't being tracked the same way today.

---

## WUD ($2/trip) deduction verification

**Contract requirement:** EverDriven's WUD ("While Under Dispatch") program deducts $2.00 per trip from provider pay for group commercial auto liability coverage (GW Purchasing Group), covering arrival-at-pickup through last dropoff only — no physical damage, no coverage outside that window.

**What the data shows:** The `ride.deduction` field — the column built specifically to capture this — is **$0.00 on all 3,789 ED rides in the database, with zero exceptions.** The ingest code (`backend/services/pdf_reader.py`) does have logic to pull separate RAD/WUD columns from the source PDF and sum them into `deduction`, but that logic is producing zero every single time, meaning either the real ED PDFs Malik/mom upload don't actually contain a broken-out RAD/WUD column (only Gross and Net), or the columns are present but not being read correctly.

**What we can infer instead:** `gross_pay` and `net_pay` DO differ per ride — typical gap is $3.58–$4.62/ride (median $3.64), which is larger than a flat $2.00 and not a constant percentage either. So SOME deduction is clearly baked into ED's reported net_pay before it ever reaches Z-Pay — but we cannot isolate how much of that gap is the $2/trip WUD specifically versus other ED-side fees, because the itemized breakdown isn't in our data.

**Bottom line: WUD is very likely being charged (the gross/net gap is consistent with that), but it is NOT independently verifiable from Z-Pay's records today, and Z-Pay currently has no way to confirm ED is charging the correct amount.** This is a blind spot worth fixing regardless of the keep/kill decision — cheap to fix (confirm the PDF has RAD/WUD columns, wire the existing code to actually read them), and it directly supports the reconciliation muscle FirstAlt's contract already forced you to build.

---

## The noncompete / two-LLC constraint

The EverDriven relationship requires a noncompete, which is why Maz Services (ED's LLC) and Acumen International (FirstAlt's LLC) are structurally separate — FA knows about ED and doesn't care, but the separation exists specifically to satisfy ED's terms. **Open legal question, never resolved:** does common family ownership of both LLCs actually satisfy or violate that noncompete's affiliate/ownership language? Nobody has had a lawyer read the actual noncompete clause against the LLC structure. This matters for the decision because:
- **If you exit ED:** the noncompete question becomes moot — no more constraint to worry about, and Acumen/FirstAlt work (the growth engine, per §0 of the master plan) is unaffected either way, since the separation was defensive, not something FA required.
- **If you keep ED:** the unresolved noncompete is a standing risk that should get a real answer, ideally on the same call as the insurance questions (`docs/INSURANCE-QUESTIONS.md`) — a transportation/contracts attorney can likely answer both in one sitting.

---

## Seasonality

ED work is EverDriven/ESY (Extended School Year) — summer-dormant by design, restarts with the regular school year in September. Right now (late July) is exactly the low point: 4 active drivers, $137 margin so far this month, last ride 7/10. This is normal, not a warning sign on its own. The real test of "is ED worth it" is what September–June actually nets — and the clean 6-month trend above (+$6k YTD, two soft months that self-corrected) says: modest, positive, small.

---

## Options

### Option A — Keep-idle
Do nothing differently. Let ED stay dormant through summer, resume normally in September on the existing terms.
- **Pro:** Zero effort, zero risk of losing the relationship, preserves optionality.
- **Con:** Doesn't fix the WUD blind spot, doesn't resolve the noncompete question, doesn't address that ED work eats real dispatcher/mom attention (calls, portal-checking, onboarding) for a business line that nets low four figures a month at peak.

### Option B — Renegotiate before September
Use the natural season-boundary pause to go back to ED/GW Purchasing Group with two asks: (1) confirm/clarify the WUD deduction amount and get it itemized on remittance so Z-Pay can verify it automatically, (2) push on rate terms given Mar/Apr ran at a loss on thin volume — even a small per-ride rate bump changes the margin picture meaningfully at this scale.
- **Pro:** Directly fixes the two concrete problems this memo surfaced (deduction opacity, thin/negative-margin months). Costs only a conversation — no relationship risk if handled as "tightening up," not "threatening to leave."
- **Con:** Takes Malik or mom's time to actually make the ask; ED may not be able to move much (WUD is a fixed insurer-side program, not ED's to negotiate).

### Option C — Exit at season boundary
Formally wind down ED before the September restart — stop taking new ED rides, let current commitments finish, dissolve or repurpose Maz Services LLC.
- **Pro:** Removes the noncompete question entirely, frees dispatcher/mom time (family-hours is the stated north-star metric per the master plan) to go toward FirstAlt/Acumen, the actual growth engine. Clean books — no more $20k mystery adjustments to chase down.
- **Con:** Gives up a real, if small, profit source (+$6k over 6 months, ~$1k/month at full-season run rate). Drivers currently doing ED work lose that income stream — a people cost, not just a numbers one. Not reversible without re-signing.

---

## Recommendation

**Keep-idle through the summer (nothing to decide right now — ED is already dormant on its own), but treat September as a hard decision checkpoint, not an autopilot restart.** Before ED resumes in September:
1. Resolve the $20k May reconciliation gap — real or bookkeeping ghost (cheap, do this first, changes the read on whether ED has actually been profitable).
2. Fix WUD visibility so Z-Pay can verify the deduction going forward (cheap, one-time code fix).
3. Get the noncompete question answered on the same call as the insurance broker/lawyer conversation (`docs/INSURANCE-QUESTIONS.md`) — bundle it, don't spend a second call on it.
4. THEN decide keep vs. renegotiate vs. exit, with real numbers instead of "pretty sure it's fine."

Given the actual trend line — small, positive, declining in effort-to-value as FirstAlt scales — **Option B (renegotiate) is the default lean if the May gap turns out to be a bookkeeping artifact and the noncompete is confirmed harmless. If the May gap is real money ED shorted you, or the noncompete turns out to be a genuine risk to the FirstAlt side, that tips straight to Option C (exit).** Either way, ED should not consume more of mom's dispatcher time than its ~$1k/month run-rate justifies once FirstAlt's 44-48 driver season ramps back up.

---

*Data sourced via read-only query against the production Postgres DB (Railway, `appdb`), 2026-07-23. No writes were made. Query basis: `ride` table, `source='maz'`, `removed_at IS NULL`, grouped by `date_trunc('month', ride_start_ts)`. Deduction check against `ride.deduction` column and `gross_pay`/`net_pay` gap analysis, same table. `partner_payment` table checked for ED-side deposit records (none found).*
