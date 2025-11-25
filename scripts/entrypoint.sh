#!/usr/bin/env sh
set -euo pipefail

echo "[entrypoint] waiting for db..."
/wait-for.sh db:5432

export PYTHONPATH=/app
ALEMBIC_INI="/app/backend/alembic/alembic.ini"

echo "[entrypoint] Running Alembic migrations..."
# run from the backend folder so relative paths in alembic.ini work
cd /app/backend
alembic -c alembic/alembic.ini upgrade head

echo "[entrypoint] Starting Uvicorn..."
# CHANGE THIS to where your FastAPI() app lives:
exec uvicorn backend.app:app --host 0.0.0.0 --port 8000

