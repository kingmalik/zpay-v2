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


# Cache bust
ARG CACHEBUST=20260405v2

# Copy application code
COPY . .

# Bake entrypoint scripts into the image to avoid virtiofs exec issues on macOS
COPY scripts/entrypoint.sh /entrypoint.sh
COPY scripts/wait-for.sh /wait-for.sh
COPY scripts/sync_drivers.py /app/scripts/sync_drivers.py
RUN chmod +x /entrypoint.sh /wait-for.sh

EXPOSE 8000
CMD ["sh", "/entrypoint.sh"]
