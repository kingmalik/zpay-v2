#!/usr/bin/env sh
set -euo pipefail

# Only wait for local DB container — skip when using external DB (Supabase, Railway Postgres, etc.)
DB_HOST=$(echo "${DATABASE_URL:-}" | sed -E 's|.*@([^/:]+).*|\1|')
if [ "${DB_HOST}" = "db" ] || [ "${WAIT_FOR_DB:-1}" = "1" ]; then
  echo "[entrypoint] waiting for db..."
  /wait-for.sh "${DB_HOST:-db}:5432"
else
  echo "[entrypoint] external DB detected (${DB_HOST}) — skipping wait-for."
fi

export PYTHONPATH=/app
ALEMBIC_INI="/app/backend/alembic/alembic.ini"

echo "[entrypoint] Running Alembic migrations..."
cd /app/backend
alembic -c alembic/alembic.ini upgrade head

# Auto-sync drivers from FirstAlt and EverDriven into Person table
echo "[entrypoint] Syncing drivers from FirstAlt and EverDriven..."
python /app/scripts/sync_drivers.py || echo "[entrypoint] WARNING: driver sync failed — continuing anyway."

# --------------------------------------------
# Auto-seed: if the ride table is empty and a seed file exists, restore it.
# This fires on first boot (fresh DB) when mom copies zpay_backup.sql to
# data/out/ before running docker compose up.
# --------------------------------------------
# psql needs plain postgresql:// scheme; strip any SQLAlchemy driver suffix
PSQL_URL=$(echo "${DATABASE_URL}" | sed 's|postgresql+[^:]*://|postgresql://|')
RIDE_COUNT=$(psql "${PSQL_URL}" -tAc "SELECT COUNT(*) FROM ride;" 2>/dev/null || echo "0")
SEED_FILE="/data/out/zpay_backup.sql"
if [ "${RIDE_COUNT}" -eq 0 ] && [ -f "${SEED_FILE}" ]; then
  echo "[entrypoint] Empty database detected — restoring from seed file ${SEED_FILE} ..."
  psql "${PSQL_URL}" < "${SEED_FILE}" \
    && echo "[entrypoint] Seed restore complete." \
    || echo "[entrypoint] WARNING: seed restore failed — continuing anyway."
else
  echo "[entrypoint] DB already has data (or no seed file) — skipping auto-seed."
fi

# --------------------------------------------
# Optional: seed/update z_rate_service defaults
# --------------------------------------------
# Enable by setting:
#   RUN_Z_RATE_UPSERT=1
#   Z_RATE_CSV_PATH=/data/in/accumen.rates.csv
#   Z_RATE_SOURCE=acumen
#   Z_RATE_COMPANY_NAME="Acumen International"
#
# Script expected at:
#   /app/scripts/upsert_z_rate_service_from_csv.py
#
if [ "${RUN_Z_RATE_UPSERT:-0}" = "1" ]; then
  CSV_PATH="${Z_RATE_ACCUMEN_CSV_PATH:-/data/in/accument.rates.csv}"
  SCRIPT_PATH="${Z_RATE_UPSERT_SCRIPT:-/app/scripts/upsert_z_rate_service_from_csv.py}"
  echo "accument.rates.csv"
  echo "[entrypoint] RUN_Z_RATE_UPSERT=1 → attempting z_rate_service upsert"
  echo "[entrypoint] CSV: ${CSV_PATH}"
  echo "[entrypoint] Script: ${SCRIPT_PATH}"

  if [ ! -f "${SCRIPT_PATH}" ]; then
    echo "[entrypoint] ERROR: upsert script not found at ${SCRIPT_PATH}" >&2
    exit 1
  fi

  if [ ! -f "${CSV_PATH}" ]; then
    echo "[entrypoint] ERROR: rates CSV not found at ${CSV_PATH}" >&2
    exit 1
  fi

  if [ -z "${DATABASE_URL:-}" ]; then
    echo "[entrypoint] ERROR: DATABASE_URL is not set (needed for upsert)" >&2
    exit 1
  fi

  python "${SCRIPT_PATH}" \
    --csv "${CSV_PATH}" \
    --source "${Z_RATE_ACUMMEN_SOURCE:-acumen}" \
    --company-name "${Z_RATE_COMPANY_NAME_ACCUMEN:-Acumen International}" \
    --db-url "${DATABASE_URL}"
  
  echo "[entrypoint] z_rate_service upsert completed"
else
  echo "[entrypoint] RUN_Z_RATE_UPSERT not enabled → skipping z_rate_service upsert"
fi

if [ "${RUN_Z_RATE_UPSERT:-0}" = "1" ]; then
  CSV_PATH="${Z_RATE_MAZ_CSV_PATH:-/data/in/maz.rates.csv}"
  SCRIPT_PATH="${Z_RATE_UPSERT_SCRIPT:-/app/scripts/upsert_z_rate_service_from_csv.py}"
  echo "maz.rates.csv"
  echo "[entrypoint] RUN_Z_RATE_UPSERT=1 → attempting z_rate_service upsert"
  echo "[entrypoint] CSV: ${CSV_PATH}"
  echo "[entrypoint] Script: ${SCRIPT_PATH}"

  if [ ! -f "${SCRIPT_PATH}" ]; then
    echo "[entrypoint] ERROR: upsert script not found at ${SCRIPT_PATH}" >&2
    exit 1
  fi

  if [ ! -f "${CSV_PATH}" ]; then
    echo "[entrypoint] ERROR: rates CSV not found at ${CSV_PATH}" >&2
    exit 1
  fi

  if [ -z "${DATABASE_URL:-}" ]; then
    echo "[entrypoint] ERROR: DATABASE_URL is not set (needed for upsert)" >&2
    exit 1
  fi

  python "${SCRIPT_PATH}" \
    --csv "${CSV_PATH}" \
    --source "${Z_RATE_MAZ_SOURCE:-maz}" \
    --company-name "${Z_RATE_COMPANY_NAME_MAZ:-everDriven}" \
    --db-url "${DATABASE_URL}"

  echo "[entrypoint] z_rate_service upsert completed"

  # After seeding rates, bulk-fix any rides that still have z_rate=0
  echo "[entrypoint] Running fix_unmatched_rates to back-fill any zero-rate rides..."
  python /app/scripts/fix_unmatched_rates.py || echo "[entrypoint] fix_unmatched_rates finished (non-zero exit means some rides may still be unmatched)"

else
  echo "[entrypoint] RUN_Z_RATE_UPSERT not enabled → skipping z_rate_service upsert"
fi

# --------------------------------------------
# Ensure Playwright Chromium binary is present.
# The binary is stored in the named Docker volume mounted at
# $PLAYWRIGHT_BROWSERS_PATH (default /app/.playwright-cache), so it survives container recreates.
# System deps (libglib, libnss, etc.) are baked into the image via
# `playwright install-deps chromium` in the Dockerfile.
# --------------------------------------------
CHROMIUM_BINARY=$(find "${PLAYWRIGHT_BROWSERS_PATH:-/app/.playwright-cache}" -name "chrome" -type f 2>/dev/null | head -1)
if [ -n "${CHROMIUM_BINARY}" ]; then
  echo "[entrypoint] Playwright Chromium already installed at ${CHROMIUM_BINARY}, skipping."
else
  echo "[entrypoint] Playwright Chromium not found in cache — installing..."
  playwright install chromium
  echo "[entrypoint] Playwright Chromium install complete."
fi

echo "[entrypoint] Starting Uvicorn on port ${PORT:-8000}..."
exec uvicorn backend.app:app --host 0.0.0.0 --port "${PORT:-8000}"
