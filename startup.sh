#!/bin/sh
set -eu

cd /app

log() {
  echo "[startup] $*"
}

wait_for_db() {
  : "${DATABASE_URL:?DATABASE_URL is required}"

  log "Waiting for Postgres to be ready..."
  # Use psycopg2 (already installed in requirements) to avoid extra client deps.
  python - <<'PY'
import os, time
import psycopg2

url = os.environ["DATABASE_URL"]
max_attempts = int(os.getenv("DB_WAIT_ATTEMPTS", "60"))
sleep_s = float(os.getenv("DB_WAIT_SLEEP_SECONDS", "2"))

last_err = None
for i in range(max_attempts):
    try:
        conn = psycopg2.connect(url)
        conn.close()
        print(f"[startup] Postgres ready (attempt {i+1}/{max_attempts})")
        break
    except Exception as e:
        last_err = e
        print(f"[startup] Postgres not ready (attempt {i+1}/{max_attempts}): {e}")
        time.sleep(sleep_s)
else:
    raise SystemExit(f"[startup] Postgres failed to become ready: {last_err}")
PY
}

run_migrations() {
  if [ "${SKIP_DB_MIGRATE:-0}" = "1" ]; then
    log "Skipping migrations (SKIP_DB_MIGRATE=1)"
    return 0
  fi
  log "Running database migrations..."
  flask db upgrade
}

start_api() {
  log "Starting Gunicorn..."
  exec gunicorn -c gunicorn_conf.py "backend.app:app"
}

start_api_with_embedded_celery() {
  log "Starting embedded Celery + Gunicorn..."
  exec ./run_gunicorn.sh
}

wait_for_db
run_migrations

if [ "${RUN_EMBEDDED_CELERY:-0}" = "1" ]; then
  start_api_with_embedded_celery
fi

start_api

