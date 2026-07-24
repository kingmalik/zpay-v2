# Payroll Rails Memo — API-Native Contractor Payout Providers (Path B)

**Date:** 2026-07-23
**Context:** Z-Pay pays 1099-NEC contractor drivers weekly across 2 company accounts (Acumen International, Maz). Current rail is a Playwright browser bot hand-entering payments into Paychex Flex — fragile, being replaced. All payout data lives in Z-Pay's own Postgres. Volume: ~12 drivers / $3–5k weekly batches now (summer), scaling to ~48 drivers / $20k+ weekly batches by September.

**Method:** live web research + direct vendor-site verification (checkhq.com, docs.checkhq.com, gusto.com/pricing + cross-verified via 4 independent 2026 pricing aggregators after gusto.com blocked automated fetch, squareup.com/payroll/pricing, wingspan.app/pricing, routable.com). Not pulled from model memory. Researched 2026-07-23 — reverify before acting; vendor pricing and program terms change.

---

## Headline finding before the table

The evaluation criteria call for "API-triggered payouts." Digging into that specifically surfaced the real constraint on this whole category:

**Genuine self-serve API-triggered contractor payouts, for a single company paying its own roster, are rare.** The two providers that actually expose a payroll-execution API — **Check** and **Gusto Embedded** — are both built and sold as *embedded payroll infrastructure for software platforms*, i.e. for a SaaS company that wants to offer payroll as a feature to hundreds of its own end-customer businesses. Check's own marketing says it plainly: "Payroll-as-a-Service APIs like Check sell to platforms, not businesses." Onboarding is sales-led, pricing is negotiated/usage-based and undisclosed, and it's built for a many-tenant use case Z-Pay doesn't have today (2 company accounts, not 200).

Standard **Gusto** (the $35+$6/contractor consumer product) confirms directly that it does **not** offer API access for a customer to connect their own systems — that's explicitly Embedded-only. **Square Payroll** has developer APIs for reading Square data, but no evidence of an endpoint to programmatically run/trigger contractor payroll — that's still a dashboard action.

So the realistic choice isn't "API automation vs. Paychex automation" — it's "dashboard-driven SaaS built for exactly this job vs. a browser bot faking clicks through Paychex Flex's UI, which wasn't built for automation and breaks on every UI change." That's still a large reliability win even without an API, and it's the honest frame for the recommendation below.

---

## Comparison table

| Provider | API-triggered payouts | 1099-NEC filing included | Cost @ 12 drivers/mo | Cost @ 48 drivers/mo | WA compliance | Pay-stub generation | Migration effort from Postgres |
|---|---|---|---|---|---|---|---|
| **Gusto — Contractor Only** | **No.** Standard Gusto has no public API for customer-triggered payroll runs (confirmed directly — Embedded-only). Dashboard/CSV bulk-add of contractors, manual "run payroll" click. | **Yes** — ACH direct deposit + 1099-NEC prep/e-file to IRS included. | **$107** ($35 base + 12×$6) per company account | **$323** ($35 + 48×$6) per company account | Low complexity — WA has no state income tax; L&I/worker-classification risk is a legal question independent of the rail (already tracked separately in transition plan). | Yes, contractor payment history/receipts via self-serve portal. | Low. CSV import of contractor roster + bank info; drivers self-onboard via portal (W-9, direct deposit). No API to sync Postgres directly — payout amounts entered/uploaded weekly. |
| **Square Payroll — Contractors** | **No.** No confirmed API to run contractor payroll programmatically; dashboard action ("Run payroll → Pay Contractors"). Read-only Square APIs exist (Labor, Payments) but not a payroll-trigger endpoint. | **Yes** — 1099 filings covered; note "automated tax filings" (state/federal deposits) explicitly excluded on this tier, though largely N/A for pure 1099 contractors. | **$72** (12×$6, $0 base) | **$288** (48×$6, $0 base) | Same low-complexity profile as Gusto. | Yes, digital delivery of 1099s/payment records. | Low-moderate. No per-account base fee, so cheapest if Acumen + Maz run as 2 separate Square accounts. Manual weekly entry same as Gusto; slightly less polished contractor-management UX per reviews. |
| **Check (checkhq.com)** | **Yes** — genuine payroll-execution API, up to 1,500 async contractor payments/run. | Yes, as part of the embedded product. | **Not publicly priced.** Usage-based + negotiated platform fees; requires becoming a Check platform partner (sales-led). | Same — undisclosed, negotiated. | Handled by Check's engine, but irrelevant if the onboarding barrier isn't cleared. | Yes, as part of the embedded product. | **High.** Not a self-serve product for a 2-entity company — it's infrastructure for building a payroll *product*. Would require dev integration + a partner sales cycle, disproportionate to current scale. |
| **Gusto Embedded** | **Yes** — full payroll API (create/execute payments, contractor + employee). | Yes. | **Not publicly priced.** Same platform-partner model as Check. | Same. | Same caveat as above. | Yes. | **High.** Same structural mismatch as Check — built for a SaaS company serving many end-customer businesses, not one operator's own 2 accounts. |
| **Wingspan** (contractor-payment specialist, API + embed) | Partial — "Custom" tier offers modular API-first architecture, but as of this check **all pricing is sales-gated** (no self-serve tier shown on their own pricing page; earlier third-party estimates of a $500/mo Teams self-serve tier could not be confirmed on wingspan.app today). | Yes — tax automation + 1099 compliance built in. | **Unknown** — contact-sales only at check time. | Unknown. | Handled by platform. | Yes (Wingspan Wallet + payment records). | Moderate if API tier is real and affordable; unverifiable claim otherwise — do not plan around it without a sales call. |
| **Trolley / Routable** (mass-payout infra) | **Yes** — API-first disbursement + 1099-NEC filing tied to payment records. | Yes. | Not a fit at this scale — Trolley typically requires $10–25k/mo payout volume and $500–1,000/mo contract minimums to access full features; Z-Pay's summer batches ($3–5k) fall well under. | Marginal fit — $20k+/mo weekly batches by September start to approach minimums, but still adds a $500–1,000+/mo contract floor for a use case (2 companies, 48 people) these tools are overbuilt for. | Strong (built for high-volume disbursement compliance). | Yes. | High relative to payoff — built for marketplaces paying thousands of payees, not a 48-driver roster. |

---

## Recommendation: **Gusto — Contractor Only plan**

Not because it has an API — it doesn't — but because it's the only option in this set that is simultaneously **self-serve today, fully priced, includes 1099-NEC filing, and is materially more reliable than the current Playwright bot** without requiring a partner sales cycle Z-Pay's current scale doesn't justify.

- **Cost is small and predictable relative to payroll volume.** Worst case (Acumen + Maz run as two separate Gusto accounts, each carrying its own $35 base): ~$214/mo total at 12 drivers, ~$646/mo at 48 drivers — against $3–5k and $20k+ weekly payout volumes respectively. This is noise-level cost either way.
- **It kills the actual failure mode.** The Paychex bot is fragile because it automates a UI that was never designed to be automated and has no idempotency or error surfacing built for that. Replacing it with a human doing one clean weekly review-and-submit in a contractor-native dashboard (vs. reverse-engineering Paychex Flex's DOM) removes the fragility even without an API.
- **1099-NEC filing is handled**, which removes a year-end compliance task entirely — currently presumably manual or Paychex-side.
- **WA-specific exposure is low regardless of vendor** — no state income tax, and the L&I/worker-classification question is a legal determination independent of which payroll tool executes the payment (track that separately, per the transition plan's existing insurance-broker action item).

**Path A (Paychex file/API import) still wins if the call confirms it** — it would avoid a rail switch entirely. This memo's job was to have a real fallback priced and vetted the moment that call comes back negative, and Gusto Contractor Only is that fallback.

**Revisit Check / Gusto Embedded later, not now** — if Z-Pay's own dispatch/payroll platform is ever sold or licensed to *other* transportation companies (i.e., Z-Pay itself becomes the multi-tenant platform), embedded payroll infrastructure becomes directly relevant and the sales-led onboarding pays for itself. At 2 company accounts paying their own drivers, it's the wrong shape of tool.

---

## Migration outline

**Rule, per the transition plan: two full parallel payroll cycles, penny-exact both times, before any cutover. Migration window = summer (12 drivers, $3–5k batches) — not September (48 drivers, $20k+).**

1. **Setup (week 1):** Create Gusto Contractor Only account(s) for Acumen (and Maz, if kept — pending the ED keep-idle/renegotiate/exit decision noted in the transition plan). Bulk-import current 12-driver roster from Postgres: name, TIN/W-9 status, bank/direct-deposit info. Drivers complete self-onboarding (W-9, direct deposit) via Gusto's portal — this is new work for them, budget a week of nudging.
2. **Shadow cycle 1:** Run payroll for real in Paychex as usual (source of truth, actual money moves there). In parallel, manually build the same week's payment batch in Gusto from the same Postgres numbers but **do not submit** — or submit to a $0-funded test if Gusto supports it. Diff every driver, every cent, against the Paychex run. Any mismatch → find and fix root cause (data pull, rounding, fee handling) before cycle 2.
3. **Shadow cycle 2:** Repeat with a second week's batch. Must be penny-exact against Paychex with zero manual corrections. This is the actual go/no-go gate — not cycle 1.
4. **Cutover:** Once two consecutive cycles are penny-exact, run the next live week's payroll through Gusto for real and stop Paychex entry for that account. Keep Paychex account active (don't cancel) through at least one more cycle as a rollback path.
5. **Scale check before September:** With 4 extra weeks of summer runway after cutover, deliberately test roster growth (add 5–10 test/placeholder contractor records, remove them) to confirm the $6/contractor line item and bulk-add flow hold up before the real 12→48 driver ramp hits in September. Don't let the first time Gusto sees 48 drivers be the same week volume also jumps to $20k+.

---

## Sources consulted

- [Check — Requirements API / Usage & Billing docs](https://docs.checkhq.com/docs/usage) — usage-based/negotiated billing, no public per-unit pricing
- [Check — Embedded Payroll for Platforms](https://www.checkhq.com/) — "platforms, not businesses" positioning, sales-led onboarding
- [Gusto Embedded — Payroll API](https://embedded.gusto.com/product/payroll-api) — confirms Embedded-only API access, standard Gusto has no customer-facing payroll API
- Gusto Contractor Only pricing ($35 + $6/contractor) — cross-verified via [gustopricing.com](https://gustopricing.com/contractor-plan), [SpotSaaS](https://www.spotsaas.com/blog/gusto-pricing), [Workstream](https://www.workstream.us/blog/gusto-pricing), [CostBench](https://costbench.com/software/hr/gusto/) (gusto.com/product/pricing blocked automated fetch — 403; figure is consistent across 4 independent current sources, not from model memory)
- [Square Payroll Pricing](https://squareup.com/us/en/payroll/pricing) — $6/contractor, $0 base, 1099 filings included, automated tax filings excluded, no confirmed payroll-trigger API
- [Wingspan Pricing](https://www.wingspan.app/pricing) — fully sales-gated as of check date, MAP-based billing, no public self-serve tier
- [Routable — Best 1099 Automation / Payouts APIs guides](https://www.routable.com/resources/best-payouts-apis-high-volume-disbursements/) — Trolley/Routable volume minimums and positioning
