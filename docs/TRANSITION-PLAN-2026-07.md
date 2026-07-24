# Z-PAY TRANSITION PLAN — July 2026
**Written 2026-07-23 (evening) by Fable from the "what would you have built greenfield" sit-down with Malik. This document is EXECUTABLE: a cold session reads §0, then works §2 top-to-bottom without new sit-downs. Companion to MASTER-PLAN-2026-07.md (S1–S9, all code-complete as of 2026-07-23 except S9's human test).**

---

## §0 — STATE AS OF 2026-07-23 EVENING (do not re-derive)

**Live in prod** (main branch, Railway + Vercel, migrations through s7/s8b): S1–S8 complete — assignment/coverage `/dispatch/assign` (288 rosters seeded), onboarding repair, trilingual certification course, owner KPI endpoint + `~/.claude/bin/zpay-kpis.sh` wired into the 6am brief, franchise binder `docs/binder/`, full test suite green under per-file isolation (`run_tests.sh`, red = real).

**Business inbox access:** read-only Gmail token (scope `gmail.readonly` — cannot send/delete) for contact.acumenintl@gmail.com as Railway env `GMAIL_REFRESH_TOKEN_BIZ_RO` + `GMAIL_USER_BIZ_RO`. 1,100 FirstStudent emails cached in this session's scratchpad (re-fetchable any time via API). Intake parser calibrated on the real corpus: 87% pay / 95% district extraction across all 110 real offers.

**Paychex:** TOTP auto-MFA is CODED + DEPLOYED (`backend/paychex_bot/totp.py`, wired into `paychex_entry.py`) but DORMANT until Malik enrolls an authenticator app in Paychex Flex and provides the secret → set `PAYCHEX_TOTP_SECRET_ACUMEN` (and `_MAZ` if separate login) in Railway. Both stored sessions are currently expired; keepalive pings can't resurrect them (hard expiry).

**THE AUDIT FINDING (2026-07-23, dry-run — no rows written):** all 27 First Student EFT remittance PDFs (Jan 22 → Jul 23, $580,587 total) parsed and matched against Z-Pay expected revenue per batch:
- **Since May 2026: FirstAlt pays penny-exact.** 9 straight exact weeks + one self-corrected pair (−$350.75 on 04/23 repaid +$350.75 on 04/30). FA is NOT shorting; their payment-review loop works.
- **Jan–mid-April: deposits EXCEED Z-Pay expected by ~$2–6k/week, ~$51k cumulative.** Interpretation: NOT FA generosity — early-2026 Z-Pay ride data is incomplete (pre-identity-spine ingest era). Z-Pay's early batches under-represent what was actually driven/billed. Treat pre-May Z-Pay revenue history as a floor, not truth.
- Unmatched: deposit 07/23 $4,871.00 (service week ~07/11–17 — batch not yet uploaded; expect it Monday 07/27, verify then). Batch 43 (week end 01/09) has no EFT email — the advice series only starts 01/22; fine.
- Data: `remit_rows.json` + per-PDF files in session scratchpad; expected-side query in this plan's history. Re-derivable from Gmail + DB at any time.

**Deploy freeze standing rule: Sunday noon → Tuesday 9am PT, every week (Monday payroll).** Nothing ships in that window, no exceptions.

**Contacts ground truth:** `~/.claude/reference/contacts.md` — Brandon (direct SP, LWSD+Kent, all deal flow), Desmond Poulson (his boss, ALL WA; mostly sees our complaints; blessed other-state expansion), third SP (name TBD from Malik) self-deals the other big district = WA near ceiling. Market map in `~/.claude/context/zpay.md`.

---

## §1 — DECISIONS ALREADY MADE (don't reopen)
1. Money rails come off browser robots. Path A = Paychex 1099-NEC import/API (if their rep confirms it exists). Path B = API-native contractor-payout provider (Check/Gusto class). Either way: **two full parallel payroll cycles, penny-exact both times, before any cutover.** Migration window = summer (batches ~$3–5k, 12 drivers) — NOT September (48 drivers, $20k+).
2. Inbox is the front door: auto-intake watcher creates draft ride cards + pings Malik. It NEVER auto-replies, never messages anyone external. A human always sends the yes.
3. Complaint pattern gets managed like revenue risk (it is — FA §1b + the Desmond file).
4. Family-hours (≤30 min/day) is the north-star metric; it ships in the weekly text.
5. Expansion (other states) is gated on S9 passing. The binder is the expansion kit. Post-lock only.

## §2 — EXECUTION QUEUE (work top-to-bottom; each task: spec → gate → rollback)

### T1 — Inbox auto-intake watcher ✅ SHIPPED 2026-07-23 ~8pm (merge 6c87ad9, migration s8b applied to prod, Railway deployed, /api/data/assignment/inbox-status returns enabled:true on all replicas)
`backend/services/inbox_intake.py` polling job (APScheduler, INBOX_POLL_MINUTES=10, flag INBOX_AUTOINTAKE=1), migration s8b (ride_intake.source_msg_id unique-partial), status endpoint `/api/data/assignment/inbox-status`. If merged+deployed: verify with a real offer or by checking inbox-status after a cycle. If branch exists unmerged: review, merge, gate (isolated tests + `npm run build` + import), deploy before Sunday freeze.
**Gate:** next real Brandon offer produces a draft intake + ntfy ping without human touch. **Rollback:** INBOX_AUTOINTAKE=0.

### T2 — Remittance backfill ✅ SHIPPED 2026-07-23 eve (write phase + auto-ingest). Backfill: 26 rows committed to prod ($575,716.27), batches 107/109/110 verify "match"; rollback = delete memo tag 'backfill-2026-07'; script backend/scripts/backfill_partner_payments_2026_07.py. Auto-ingest: backend/services/remit_ingest.py rides the inbox watcher (flag EFT_AUTOINGEST), records the ACTUAL paid amount, dedupes on business key eft:<payment#>:<invoice-ref> under unique index (migration s8c) — replica-race-proof, re-sent-email-proof; aligned SPF/DKIM/DMARC + supplier-id gates; adversarially reviewed twice (ship-gate workflow + focused re-review), all confirmed findings fixed. The 7/23 $4,871 deposit auto-records once its batch uploads (~Mon 7/27) — verify then.
Write `partner_payment` rows for the 26 matched deposits (mapping table = §0 audit: deposit_date+amount → payroll_batch_id). Respect existing rows (mom may have entered Jul deposits — upsert by batch, don't duplicate). Statuses will show match/overpaid per S1.5 semantics; RECON_ENFORCE_SINCE=2026-07-01 keeps old weeks from red-alerting.
**Gate:** /reconciliation shows the deposit history; batch 107 row = $3,050.50 match. **Rollback:** delete rows where notes tag = 'backfill-2026-07'. Tag every written row with that note.
**Also:** wire a small `remit_ingest` into the inbox watcher: EFT Remittance email → parse PDF → auto-create partner_payment row (same dedupe pattern, note tag 'auto-eft'). Mom stops hand-entering deposits forever. Flag EFT_AUTOINGEST default 1, internal only.

### T3 — Complaint ledger
Parse complaint threads from the corpus (search subjects containing "complaint"; 45 msgs incl. Kedir Ali ×11, Eliyas Surur) → `docs/binder/08-complaint-ledger.md`: per-driver complaint history (dates, district, resolution if visible) + coach-or-cut shortlist. Cross-ref reliability tiers (`GET /api/data/reliability/tiers`). No driver-facing anything; deliverable is the doc + a one-screen summary for Malik. (DB table + UI integration = later, only if Malik wants it.)

### T4 — Paychex rep call script + provider decision memo
(a) Write `docs/PAYCHEX-CALL-SCRIPT.md`: 20-min script — "do you support 1099-NEC payment import via file or API for Flex? What's the enrollment path?" + fallback questions (SFTP? scheduled imports? API program?). Malik makes the call.
(b) Research memo `docs/PAYROLL-RAILS-MEMO.md`: API-native contractor payout options (Check, Gusto Embedded/Contractor, Square Contractors, others current as of research date) — criteria: API-triggered payouts, 1099-NEC filing included, per-contractor monthly cost at 12 vs 48 drivers, WA compliance, stub generation, migration effort from Z-Pay's existing payout data. One recommendation. Use web research; verify pricing on vendor sites, not memory.
**Decision gate (Malik):** rep call result + memo → pick path A or B. Then build the integration behind a flag, run the two parallel cycles.

### T5 — Insurance verification pack
`docs/INSURANCE-QUESTIONS.md` from the contract facts in MASTER-PLAN §0 (FA TPA: Acumen = PRIMARY insurer-responsible, FA auto policy EXCESS only $100k/300k/50k passenger-window; ED WUD $2/trip group cover, no physical damage; open Q: WA L&I for 1099 drivers; §4c annual mechanic certs — verify current fleet has them). Malik books one call with a commercial insurance broker/lawyer and reads the list. This is the existential item — schedule it, don't let it rot.

### T6 — Family-hours metric
Add operator-hours estimate to weekly KPI text: proxy = (calls_made × 4 min) + (payroll session duration from paychex_job timestamps) + (onboarding assisted-steps × 60 min). Crude is fine; direction over precision. Lands in `owner_kpis.py` weekly block + zpay-kpis.sh line.

### T7 — ED keep/kill memo
One page: ED revenue trend from DB (rides by month, source='maz'), the $2/trip WUD deduction (verify it shows in remittance/ingest), the noncompete constraint on the two-LLC structure, summer dormancy. Options: keep-idle / renegotiate / exit-at-season-boundary. Malik decides at/after the fam meeting.

### T8 — Meeting one-pager (BEFORE the weekend)
Single doc for the fam meeting: what the machine now does (one paragraph), the audit headline ("FA verified penny-exact since May; we now auto-audit every deposit"), the KPI snapshot, the binder TOC, next-school-year plan (max Brandon's book, bench recruiting in LWSD/Kent zips, mom's ≤30-min/day target, S9 week), and the decision list. Source: binder README + zpay-kpis output + this plan.

### T9 — Paychex TOTP activation (blocked on Malik, 5 min)
Malik enrolls authenticator in Paychex Flex → pastes secret key → set `PAYCHEX_TOTP_SECRET_ACUMEN` (+`_MAZ`) in Railway → next bot run logs in alone. Test OUTSIDE the freeze window with a no-op run (login + navigate, no entry): `mfa auto` status expected. Until then weekly cookie capture continues.

### T10 — Autosend approval (blocked on Malik)
Show him the exact email/SMS wording in `backend/services/onboarding_autosend.py` → he approves/edits copy → `ONBOARDING_AUTOSEND=1`. Law 7: no flip without explicit approval recorded.

### T11 — September readiness rail (August)
Bench recruiting task with dates (target LWSD/Kent zips; use home-area data as it fills); verify annual compliance items for existing fleet BEFORE Sep 1 (mechanic certs esp.); mom walkthroughs (assign screen, backups, languages); Arabic QA for the course; then S9 solo week once school rhythm settles.

## §3 — STANDING SAFETY (unchanged, non-negotiable)
Deploy freeze Sun noon→Tue 9am · pg_dump before any migration (B2 hourly + `pre-s5s6s8` tag + local snapshots exist) · driver-facing comms approval-gated · money-path changes always shadow/parallel first · production build green before "done".

## §4 — OPEN ITEMS ON MALIK (rolled up)
Meeting day/time · Paychex TOTP secret · Paychex rep call · insurance call booking · autosend copy approval · ED decision · Arabic QA speaker · third SP's name (contacts.md) · Acumen-vs-Maz contract-column contradiction ruling (S6 finding).
