# Dockerfile (at repo root)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (minimal; psycopg[binary] doesn't need libpq-dev)
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps first for better build caching
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

# Install Playwright system dependencies and bake the Chromium binary into the image
RUN playwright install-deps chromium
RUN playwright install chromium


# Bake entrypoint scripts into the image to avoid virtiofs exec issues on macOS
COPY scripts/entrypoint.sh /entrypoint.sh
COPY scripts/wait-for.sh /wait-for.sh
RUN chmod +x /entrypoint.sh /wait-for.sh

# Bake all backend code and scripts into the image (virtiofs can't exec .py files from mounts on macOS)
COPY backend /app/backend
COPY scripts /app/scripts

# Bake rate CSVs into the image (virtiofs blocks file reads from mounted volumes on macOS)
COPY data/in/acumen.rates.csv /app/data/acumen.rates.csv
COPY data/in/maz.rates.csv /app/data/maz.rates.csv

# Default workdir is /app; compose sets the command to /entrypoint.sh
