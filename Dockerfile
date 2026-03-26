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


# Optional: copy backend if you also want a build without bind mounts
#COPY backend /app

# Add entrypoint to run Alembic then start API
#COPY scripts/entrypoint.sh /app/entrypoint.sh
#RUN chmod +x /app/entrypoint.sh

# Default workdir is /app; compose sets the command to /app/entrypoint.sh
