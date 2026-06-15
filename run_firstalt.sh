#!/usr/bin/env bash
# FirstAlt one-shot: capture fresh Acumen session, then auto-run the bot
# on the given batch and poll to completion. Run from your Mac.
#
#   ./run_w21_firstalt.sh <BATCH_ID>
#
# What happens:
#   1. A Chrome window opens -> log into Paychex (Acumen) -> enter the MFA text.
#   2. The moment the dashboard loads, the session is captured + uploaded.
#   3. The bot fires automatically against <BATCH_ID> and fills every driver.
#   4. You watch live status here. Bot NEVER submits — you Review & Submit
#      in Paychex yourself at the end.

set -euo pipefail
cd "$(dirname "$0")"

if [ $# -lt 1 ]; then
  echo "usage: $0 <BATCH_ID>"
  echo "  find the batch number on the Z-Pay dashboard after Mom uploads the FA Excel"
  exit 2
fi

BASE="https://zpay-v2-production.up.railway.app"
BATCH="$1"
PY=.botvenv/bin/python

echo "==> Loading secrets from Railway..."
export ZPAY_INTERNAL_SECRET="$(railway variables --kv 2>/dev/null | awk -F= '/^ZPAY_INTERNAL_SECRET=/{sub(/^[^=]*=/,""); print; exit}')"
SK="$(railway variables --kv 2>/dev/null | awk -F= '/^ZPAY_SERVICE_KEY_RUNNER=/{sub(/^[^=]*=/,""); print; exit}')"
[ -n "$ZPAY_INTERNAL_SECRET" ] || { echo "!! ZPAY_INTERNAL_SECRET missing"; exit 1; }
[ -n "$SK" ] || { echo "!! ZPAY_SERVICE_KEY_RUNNER missing"; exit 1; }

echo "==> Opening Chrome for Acumen login (complete MFA when prompted)..."
$PY scripts/capture_paychex_session.py acumen

echo "==> Session captured. Triggering bot on batch $BATCH..."
RESP=$(curl -sS -m 20 -X POST -H "X-Service-Key: $SK" -H "Accept: application/json" \
  -H "Content-Type: application/json" "$BASE/api/data/paychex-bot/push/$BATCH")
echo "    push: $RESP"
JOB=$(echo "$RESP" | $PY -c "import json,sys; print(json.load(sys.stdin).get('job_id',''))")
[ -n "$JOB" ] || { echo "!! push failed — no job_id"; exit 1; }

echo "==> job=$JOB — polling every 20s (run takes ~20 min for 44 drivers)..."
for i in $(seq 1 90); do
  sleep 20
  curl -sS -m 15 -H "X-Service-Key: $SK" -H "Accept: application/json" \
    "$BASE/api/data/paychex-bot/status/$JOB" > /tmp/zpay_w21_status.json
  LINE=$($PY - <<'PYEOF'
import json
d=json.load(open('/tmp/zpay_w21_status.json'))
msg=(d.get('message') or '').replace('\n',' ')[:90]
err=(d.get('error') or '').replace('\n',' ')[:160]
print(f"{d.get('status')} {d.get('progress')}/{d.get('total')} {d.get('current_driver','')} | {msg}" + (f" | ERR={err}" if err else ""))
PYEOF
)
  echo "    [$(date +%H:%M:%S)] $LINE"
  case "$LINE" in
    done*)   echo "==> ✅ FILL COMPLETE. Log into Paychex, verify amounts, then Review & Submit."; break;;
    failed*) echo "==> ❌ Bot failed — see ERR above. Debug snaps in the job's R2 folder."; exit 1;;
  esac
done
