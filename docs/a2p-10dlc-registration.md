# A2P 10DLC Registration — Maz Services SMS Recovery

**Problem:** Twilio error 30034 (carrier filter) and 63007 (no messaging service) are silently
dropping driver SMS. Root cause: no A2P 10DLC brand or campaign registered, no Messaging Service
wired to the sending number +1 (206) 752-5347.

**Fix:** Complete the Twilio A2P 10DLC wizard at console.twilio.com. This document gives you
everything needed to finish in one sitting.

---

## Costs (no surprises)

| Item | Cost |
|---|---|
| Standard Brand vetting | $44 one-time |
| Campaign fee | $10/month |
| Number linking | Free |

Total upfront: **$44**. Monthly add: **$10**.

---

## Step 1 — Register a Standard Brand

Navigate to: **Messaging > Senders > A2P 10DLC > Brands > Create Brand**

Fill in every field below. Fields marked **NEED FROM MALIK** are not in any stored context —
collect these before opening the console.

| Field | Value |
|---|---|
| Legal business name | Maz Services LLC |
| Business type | Private For-Profit |
| Entity type | Limited Liability Company (LLC) |
| EIN (Tax ID) | **NEED FROM MALIK** |
| Industry | Transportation |
| Business registration country | United States |
| State of incorporation | Washington |
| Business address | Bellevue, WA (**NEED full street address from Malik**) |
| Business website | **NEED FROM MALIK** (use zpay or maz public URL if live, else explain below) |
| Support email | **NEED FROM MALIK** (e.g. dispatch@mazservices.com or the contact.activate inbox) |
| Support phone | +14254696353 |

**Website note:** If Maz Services does not have a public-facing website yet, use the Z-Pay
frontend URL (https://frontend-ruddy-ten-82.vercel.app) and note in the form that this is
the internal operations platform. Carrier vetting teams accept internal tools — the important
thing is that the URL loads and is professionally presented.

---

## Step 2 — Register a Campaign

Navigate to: **Messaging > Senders > A2P 10DLC > Campaigns > Create Campaign**

**Use case:** Select **"Account Notification"**

This is the correct category for transactional operational messages (trip alerts, reminders)
sent to your own contractors. Do NOT select "Marketing" or "Mixed."

### Campaign description (copy-paste this into the wizard)

> Maz Services LLC operates a school transportation network with approximately 126 independent
> contractor drivers across the greater Seattle area. This campaign sends transactional trip
> reminders to drivers via SMS — never promotional content. Messages are sent only when a
> driver has an unaccepted or unstarted trip assignment and are triggered by the Z-Pay
> dispatch monitoring system. All message recipients are active contractors who have
> acknowledged and agreed to receive operational SMS communications as part of their
> onboarding agreement with Maz Services. Drivers may reply STOP at any time to opt out.
> Typical message volume is 10–50 messages per day, Monday through Friday, during school
> operating hours (roughly 6 AM to 4 PM Pacific).

### Sample messages (use exactly as shown — these match the live SMS templates in call_scripts.py)

**Sample 1 — Unaccepted trip:**
> MAZ Services: You have an unaccepted trip at 7:45 AM. Please accept it in your driver app now.

**Sample 2 — Trip start reminder:**
> MAZ Services: Your FirstAlt trip starts at 8:00 AM — time to head out!

**Sample 3 — Admin escalation alert (sent to +14254696353 only):**
> Z-PAY ALERT: Driver has not accepted trip 7421454 — escalation required.

### Other campaign fields

| Field | Value |
|---|---|
| Message flow | Contractor receives SMS when their trip is unaccepted or unstarted per dispatch system |
| Opt-in mechanism | Written consent in driver onboarding agreement (see opt-in language below) |
| Opt-out | Reply STOP — **see STOP handling note below** |
| Help keyword | Reply HELP to receive: "MAZ Services dispatch alerts. Reply STOP to unsubscribe. Help: +14254696353" |
| Contains embedded links | No |
| Contains phone numbers | No |
| Contains age-gated content | No |

---

## Step 3 — Link the Number to the Messaging Service

After creating the campaign and messaging service:

1. Go to **Messaging > Services > [your new service] > Sender Pool**
2. Click **Add Senders**
3. Select **Phone Number**
4. Add: **+1 (206) 752-5347**

The number must be in the sender pool before any A2P traffic flows through it.

---

## Step 4 — Set the Inbound SMS Webhook

**Current state:** There is no inbound SMS route in the Z-Pay backend. The only Twilio webhook
that exists handles WhatsApp (`/webhooks/whatsapp`). There is no `/webhooks/sms` or equivalent.

**Action required now (before setting webhook URL):** An inbound SMS route needs to be built
before this field can be populated with a real Z-Pay endpoint. For registration to proceed,
Twilio requires a webhook URL to be set on the number but it does not need to be functional
at registration time.

**Temporary webhook URL (use for now):** Set the inbound SMS webhook on the number to:
```
https://zpay-production-[your-railway-domain].up.railway.app/webhooks/sms
```

Or use Twilio's built-in null webhook: leave it as the default Twilio demo URL during
registration only — change it after STOP handling is built.

**What to build (next session):** A `POST /webhooks/sms` route in `backend/routes/` that:
- Reads `Body` and `From` from the Twilio form-encoded payload
- If `Body.strip().upper() == "STOP"`: mark the driver's `Person` record as sms_opted_out=True
  (column does not exist yet — migration needed)
- Returns a TwiML `<Response/>` (empty 200) so Twilio doesn't retry

**This is not blocking registration but must be built before going live post-approval.**

---

## Step 5 — Wait for Approval

- Standard Brand vetting: typically **1–7 business days** (often 24–48 hours)
- Campaign approval: typically **1–3 business days** after brand approval
- Twilio sends email when each stage clears
- Check status at: Messaging > A2P 10DLC > Brands / Campaigns

---

## Step 6 — Verify Post-Approval

After campaign status shows **VERIFIED**:

1. Send a test SMS from the Twilio console to your own phone using +1 (206) 752-5347 as sender
2. Confirm it arrives (no 30034 or 63007 errors in the Twilio logs)
3. Trigger a real dispatch cycle and watch Railway logs for successful Twilio API responses
4. Check Twilio error log at console.twilio.com/us1/monitor/errors — should be clean

---

## STOP Handling — Current Status

The Z-Pay backend does NOT have STOP handling implemented. Twilio automatically processes
STOP replies at the carrier level (the number will be opted out on Twilio's side), but Z-Pay
has no corresponding database record of the opt-out. This means:

- Twilio will honor the STOP and block future messages to that number
- Z-Pay will attempt to send and silently fail (Twilio blocks it server-side)
- No alert or driver record update will occur

This is acceptable for initial launch but must be resolved in the next build sprint.
See Step 4 above for what to build.

---

## Opt-In Consent Language

Add this clause to the Maz Services driver onboarding agreement or the Z-Pay /contract page:

> By signing this agreement, I consent to receive transactional SMS messages from Maz Services
> LLC at the mobile number I have provided. These messages include trip reminders, dispatch
> notifications, and operational alerts. Message frequency varies based on your schedule,
> typically 1–5 messages per shift day. Standard message and data rates may apply. You may
> opt out at any time by replying STOP to any message.

This is required evidence of opt-in consent if Twilio or a carrier requests it during vetting.
Keep a copy in the driver file (Z-Pay onboarding record is sufficient documentation).

---

## Alternative: Toll-Free Verification

If Standard Brand registration is denied or takes too long, the faster alternative is:

1. Purchase a US toll-free number (e.g. +1 888 XXX XXXX) from Twilio — ~$2/month
2. Submit **Toll-Free Verification** (separate flow from A2P 10DLC) — approval typically
   1–3 business days, no $44 brand fee, no monthly campaign fee
3. Update `TWILIO_FROM_NUMBER` in Railway to the new toll-free number

**Trade-off:** Toll-free numbers have per-message carrier filtering that is slightly stricter
than A2P 10DLC for high-volume senders, but at Maz's volume (10–50 msgs/day) the deliverability
is equivalent. Standard Brand is the better long-term choice if you plan to scale or add more
numbers. For getting unblocked fast, toll-free verification is the lower-friction path.

---

## Quick Reference — What to Gather Before Opening the Console

- [ ] EIN (Federal Tax ID for Maz Services LLC)
- [ ] Full business street address in Bellevue, WA
- [ ] Business website URL (or confirm using frontend-ruddy-ten-82.vercel.app)
- [ ] Support email address (the contact.activate inbox or a dedicated dispatch@ address)

Everything else in this document is already known and ready to paste.

---

## Account Reference

| Item | Value |
|---|---|
| Twilio Account SID | See Twilio console (do not commit) |
| Sending number | +1 (206) 752-5347 |
| Admin alert phone | +14254696353 |
| Railway env var | `TWILIO_FROM_NUMBER` |
| Backend SMS function | `backend/services/notification_service.py` → `send_sms()` |
| SMS templates | `backend/services/call_scripts.py` → `SMS_SCRIPTS` |
