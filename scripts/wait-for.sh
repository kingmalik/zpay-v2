#!/usr/bin/env bash
# wait-for HOST:PORT with optional -t/--timeout SECONDS (default 60)
set -Eeuo pipefail

HOSTPORT=""
TIMEOUT=60

# parse args in any order: "-t 60 host:port" or "host:port -t 60"
while (($#)); do
  case "${1:-}" in
    -t|--timeout)
      shift
      TIMEOUT="${1:-}"
      [[ "$TIMEOUT" =~ ^[0-9]+$ ]] || { echo "invalid timeout: $TIMEOUT" >&2; exit 2; }
      ;;
    *)
      HOSTPORT="${1:-}"
      ;;
  esac
  shift || true
done

[[ -n "${HOSTPORT:-}" ]] || { echo "usage: $0 HOST:PORT [-t SECONDS]"; exit 2; }

echo "Waiting for $HOSTPORT up to $TIMEOUT seconds..."
for ((i=1; i<=TIMEOUT; i++)); do
  if exec 3<>"/dev/tcp/${HOSTPORT/:/\/}"; then
    exec 3>&-
    echo "✅ $HOSTPORT is ready"
    exit 0
  fi
  sleep 1
done

echo "❌ Timeout waiting for $HOSTPORT"
exit 1
