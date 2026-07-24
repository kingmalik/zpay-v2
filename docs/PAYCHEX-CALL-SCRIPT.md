# Paychex Rep Call Script — 20 Minutes

**Purpose:** find out if Paychex Flex supports file/API import of 1099-NEC contractor payments, so the Playwright entry bot can be retired for a real integration (Path A). If not, Z-Pay moves to an API-native provider (Path B — see `docs/PAYROLL-RAILS-MEMO.md`).

**Who's calling:** Malik Milion, existing Paychex Flex customer, 2 company accounts (Acumen Intl, Maz). Currently entering 1099-NEC contractor payroll by hand in Flex, ~12 drivers/week now scaling to ~48 drivers/week by September.

**How to use this doc live:** read top to bottom. Bold questions are the ones to ask verbatim. Everything else is why-it-matters context for you, not the rep. Write answers directly under each question.

---

## 0. Opening (30 sec)

"Hi, I'm Malik Milion, I have two Paychex Flex accounts under Acumen International and Maz — [account/client IDs]. I run 1099-NEC payroll for contractor drivers weekly and I'm calling to ask about programmatic ways to submit that payroll instead of manual entry. Can you check if my accounts have API or file-import access, or connect me to someone who can?"

**Answer:**

---

## 1. THE PRIMARY ASK (5 min — this is the whole call if the answer is fast)

**"Do you support 1099-NEC contractor payment import via file or API for Paychex Flex? What's the enrollment path to get that turned on for my accounts?"**

**Answer:**

If yes → **"What's the enrollment path — is it self-serve in Flex, does it require a sales/onboarding team, and what's the typical timeline to get it live?"**

**Answer:**

If no / rep doesn't know → move to fallback questions below. Don't let them end the call on "I don't think so" — ask to be routed.

---

## 2. FALLBACK QUESTIONS (if primary ask is unclear or "no")

Ask these in order. Stop as soon as you get a clear yes with a concrete next step.

**a) "Does Paychex Flex support scheduled SFTP file imports for contractor/1099 payments — a batch file I upload or you pull on a schedule?"**

**Answer:**

**b) "Is there a Paychex API partner program or developer program I can apply to that covers contractor payments specifically? Who runs that — is it a separate team from Flex support?"**

**Answer:**

**c) "Does the Paychex Flex API (if one exists) have endpoints for contractor/1099 payments specifically, or is the API limited to W-2 employee payroll and reporting?"**

**Answer:**

**d) "Is this capability different for Paychex Flex Select vs Paychex Flex Pro/Enterprise? Would I need to upgrade my plan tier to get it?"**

**Answer:**

**e) "If none of this exists today, is it on a roadmap? Rough timeline?"**

**Answer:**

---

## 3. PRICING QUESTIONS (5 min — only if Section 1 or 2 gave a real path)

**a) "What does file/API import cost — is it a flat monthly add-on, per-transaction, or included in my current plan?"**

**Answer:**

**b) "Is there a setup/integration fee, and does it apply per company account? I have two accounts — Acumen and Maz — would each need separate enrollment and separate fees?"**

**Answer:**

**c) "Is 1099-NEC filing (year-end forms to IRS + contractors) included in this, or is that priced separately?"**

**Answer:**

**d) "Does pricing change based on contractor count? I'm at ~12 now, scaling to ~48 by September — will cost or capability change at that volume?"**

**Answer:**

---

## 4. WRAP-UP (2 min)

**"Can you send me written documentation on whatever we just discussed — API docs, SFTP spec, or pricing sheet — to the email on file? And can I get your name and a direct line or ticket number in case I need to follow up?"**

Rep name / line / ticket #:

Docs promised, by when:

---

## DECISION CHECKLIST — fill out immediately after the call

Path A (stay on Paychex, replace the bot with a real integration) is **viable** only if ALL of these are true:

- [ ] Confirmed: file or API import for **1099-NEC contractor payments** exists (not just W-2 employee payroll)
- [ ] Enrollment path is concrete — a named program, form, or team, not "I'll have someone call you"
- [ ] Realistic timeline to go live is **weeks, not quarters** (ideally live before the September 48-driver scale-up)
- [ ] Cost is known or at least bounded, and doesn't require jumping to a materially more expensive plan tier
- [ ] Works across **both** company accounts (Acumen + Maz) without a from-scratch enrollment each time being a dealbreaker

If any box is unchecked → default to Path B (see `docs/PAYROLL-RAILS-MEMO.md`) and don't spend more cycles chasing Paychex. Two full parallel payroll cycles, penny-exact, are required before cutover either way — start that clock now regardless of which path wins.
