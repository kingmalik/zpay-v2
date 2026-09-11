# Driver course corrections — Malik, 2026-09-10 (voice)

Applies to backend/services/certification.py (COURSE_VERSION 2026-07) and docs/binder/05-driver-rules-certification.md. Bump COURSE_VERSION when applied.

1. **Accept window.** Rides can only be accepted about ONE HOUR before start (partner app limit) — "right away" is wrong. Rule + quiz Q1 must change to: accept as soon as the app lets you, roughly an hour before pickup. ⚠️ exact window unconfirmed ("something like that") — confirm with Z / partner app.
2. **911.** Call 911 only for a real 911 emergency (injury, danger). Anything else → dispatch first. Module 5 "accident: 911 then dispatch" is wrong as written; quiz Q7 (nobody hurt → dispatch) is right. Make them match.
3. **No Z-Pay in the course.** Drivers never see or use Z-Pay and don't know the name. Remove "Z-Pay reminds you 30 days before expiry", the Z-Pay branding/logo, any system references. Course speaks as Maz Services only; reminders come "from dispatch/Z".
4. **Camera is not universal.** Not every driver/partner has a camera. Drop the blanket "camera working" rule and quiz Q3, or scope it to "if your vehicle has a partner camera".

Still open from the 9/10 audit (need Z): dispatch number/hours, pickup wait rule, top-10 driver questions.

## Round 2 — Malik, 2026-09-10 ~2:1xp (voice)
5. **Drinks OK, food no.** Water/coffee in the car is fine. No eating. The real rule is NO DISTRACTED DRIVING — teach that as the idea, food is one example.
6. **Deposit day = FRIDAY** (not Thursday).
7. **Fifth-grade reading level** for every sentence in the course, all three languages.
8. **Don't explain how partners pay Maz.** Not their business. Say only: your first pay lands about a week or two after your first ride, then weekly.
9. **No-load wait = 5–10 minutes, depends on the school district.**
10. **No-load pay = FULL pay.**
11. **Late cancellation (1–2 hours before ride) = FULL pay to the driver.**
12. **Vest + placard still required.**
13. **Camera = situational**, depends on partner and driver. Teach as "if your partner gave you a camera, it stays on."
14. **Dispatch number: not built yet.** Leave a placeholder line; course ships with "call Z" until the line exists.

## Round 3 — Malik, 2026-09-10 ~2:2xp
15. **Pay lag, exact:** rides you drive Mon–Fri are paid on the FRIDAY TWO WEEKS LATER. (Verified prod batches 116–127: payroll runs 10–12 days after week_end, deposit that Friday.) Course says exactly that, not "about a week or two".
16. **No guardian confirmation on first pickup.** There is no such step. Drop it from the course (April spec line was wrong). No parent contact by drivers or Maz dispatch.

## Round 4 — Malik, 2026-09-10 ~7:50p (reviewing v2026-09 live)
17. **IB/OB, ride numbers, (W) variants = internal dispatch vocabulary, NOT driver knowledge.** Delete the "Reading your ride" module and its quiz question. Keep only "read the ride notes before you accept" (moved into Accepting a ride).
18. **No wheelchair content for drivers.** Remove wheelchair pay, the wheelchair-swap rule, and the wheelchair quiz question. Z assigns wheelchair rides only to approved drivers; drivers don't need the rule.
19. **Explain the delayed pay fully.** One block "paid the Friday two weeks later" is not enough. Walk it: a dated example week → the Friday it lands; what the first three Fridays look like for a new driver (nothing, nothing, first check); why there is a delay (each ride is checked and counted before it's paid — no partner details); stub by email a few days before the deposit; after the first check, every Friday.

## Round 5 — Malik, 2026-09-10 ~8:10p
20. **No extra stuff.** "No pay between rides" and anything like it that Malik/Z never said comes out. Rule for the course: only (a) what Malik or Z stated, (b) what is verified in code/docs. No "why it matters" filler, no invented examples, no inferred rules (no-smoking, no-passengers, accident photo steps, cancel-the-night-before, app screen definitions, seat-belt law, save-for-taxes advice, send-docs-same-day).
