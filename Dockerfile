# syntax=docker/dockerfile:1
# API — production image (multi-stage, non-root, runtime libs only).
# Local dev with bind mounts: Dockerfile.dev + docker-compose.local.yml
#
#   docker build -t school-erp-api ./app
#   docker build -f Dockerfile.dev -t school-erp-api:dev ./app

FROM python:3.14-slim-bookworm AS base-runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FLASK_APP=backend.app:create_app \
    PYTHONPATH=/app

WORKDIR /app

# Runtime libs only (WeasyPrint / Cairo stack — no *-dev in final image)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libharfbuzz0b \
    libpangoft2-1.0-0 \
    libharfbuzz-subset0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libffi8 \
    libjpeg62-turbo \
    libopenjp2-7 \
    fonts-dejavu-core \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# --- Install Python deps into /venv (build headers isolated in this stage) ---
FROM base-runtime AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libjpeg-dev \
    libopenjp2-7-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m venv /venv
RUN /venv/bin/pip install --upgrade pip && \
    /venv/bin/pip install --no-cache-dir -r requirements.txt

# --- Production: non-root, no compiler toolchain ---
FROM base-runtime AS production

COPY --from=builder /venv /venv
ENV PATH="/venv/bin:$PATH"

RUN useradd --uid 10001 --no-create-home --shell /bin/sh app

COPY --chown=app:app . .

RUN chmod +x docker-entrypoint.sh

USER app

EXPOSE 5001

ENTRYPOINT ["./docker-entrypoint.sh"]
