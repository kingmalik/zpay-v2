# Payroll Runbook — Monday, Step by Step

> Franchise Binder §2 · drafted 2026-07-22 from W20–W25 history (W25 = the clean reference cycle: 12/12 stubs, Paychex matched to the penny). Reader: the operator. Plain words on purpose.

## Before you start
- It's Monday. The partner file (FirstAlt/Acumen Excel, EverDriven PDF when active) has landed by email.
- Deploy freeze is on — nobody touches the system's code from Sunday noon until Tuesday 9am. If something looks broken, call Malik; do not wait it out.

## Step 1 — Upload
1. Log into Z-Pay → Payroll → Upload.
2. Upload the partner file. The system ingests rides and matches each one to a driver rate automatically.

## Step 2 — Resolve unpriced rides
1. Open **Rates Review**. Anything the engine refused to price is here, with its evidence ("matches spring ride #17, 28mi @ $62 × 92 rides").
2. If the evidence looks right, accept it. If a ride is genuinely new (new school, changed deal), set the rate by hand.
3. **Wheelchair (HCV) rides always land here on purpose** — default is full pass-through to the driver; confirm and move on.
4. The page must say every ride is priced before you continue. If it claims "All priced" but the batch totals look thin, refresh — then call Malik.

## Step 3 — Review the payroll
1. Open the batch review. Check driver count and total against what the week should look like (school year ≈ $17–24k; summer ≈ $2–3k).
2. Withheld amounts under $100 carry forward automatically. Loans/advances appear as negative lines.
3. Check the **active manual withholds panel** — anything listed there is money deliberately held; confirm it still should be.
4. Double-pay check: if a ride looks paid twice (partner re-sent a ride already advance-paid), flag it — the stub gets a reversing line, like Amanuel in W25.

## Step 4 — Approve and send stubs
1. Approve the batch.
2. Send stubs. Every driver with pay gets a PDF by email. The screen must show all stubs sent (e.g. 12/12) — a partial send is a stop-and-call.

## Step 5 — Paychex
1. Run the Paychex bot (it types the amounts into Paychex Flex Pay Entry). You'll capture the Paychex session cookie when asked — that's normal.
2. **TENANT CHECK:** Paychex is one login with TWO companies — *Acumen International* (FirstAlt drivers) and *Maz Services* (EverDriven drivers). Read the company name on screen before anything else. Tenant mix-ups have caused real incidents.
3. When the bot finishes, compare **Paychex Quick Totals against the Z-Pay batch total — number of checks AND dollar amount must match exactly** (W25: $2,298.00 / 11 checks, penny-exact). Not close — exact.
4. Match → click Review & Submit. No match → STOP, do not submit, call Malik.
5. Drivers see direct deposit around Thursday.

## Step 6 — Reconciliation (when the partner pays US)
This is a legal clock, not bookkeeping.
1. A FirstAlt/EverDriven deposit hits the bank → same day, open **/reconciliation** and record it on the batch row, using the **real bank posting date** (the 14-day dispute clock runs from it).
2. Deposit short of what the batch says we're owed → send the **written dispute email FIRST**, then click Mark Disputed and cite the email subject + date.
3. Under the FirstAlt contract (§6b), a shortfall not disputed **in writing within 14 days is waived — the money is gone**. The page shows countdown badges; red means days are running out.

## If anything goes wrong
- Numbers don't match, stubs half-sent, bot errors: stop where you are, don't retry blindly, call Malik.
- System down: hourly encrypted backups exist and restores are proven (docs/disaster-recovery.md). Nothing is ever lost; don't improvise.
