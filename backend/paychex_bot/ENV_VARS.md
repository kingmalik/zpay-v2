# Paychex Bot — Required Environment Variables

Add these to Railway environment variables (Settings → Variables):

| Variable | Description | Example |
|----------|-------------|---------|
| PAYCHEX_ACUMEN_USER | Paychex Flex username for Acumen account | john@acumen.com |
| PAYCHEX_ACUMEN_PASS | Paychex Flex password for Acumen account | ••••••••• |
| PAYCHEX_MAZ_USER | Paychex Flex username for Maz account | john@mazservices.com |
| PAYCHEX_MAZ_PASS | Paychex Flex password for Maz account | ••••••••• |

## Setup Steps
1. Go to Railway → zpay-v2 service → Variables
2. Add the four variables above
3. Redeploy (Railway auto-redeploys on variable changes)

## Notes
- These credentials are used by the headless Playwright bot to log into Paychex Flex
- The bot fills pay entries but NEVER submits payroll — Malik manually reviews and submits
- If Paychex has 2FA enabled, the bot will pause and notify you to check your phone
