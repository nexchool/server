#!/bin/sh
set -eu

cd /app

# Flask CLI (migrations): app module is server/app.py on PYTHONPATH=/app.
# Host env_file must not override with a stale package path.
export FLASK_APP="app:create_app"

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

widen_alembic_version() {
  # Alembic ships `alembic_version.version_num` as VARCHAR(32). Some of our
  # revision IDs are >32 chars and Postgres rejects the post-upgrade UPDATE
  # with StringDataRightTruncation. Widening to VARCHAR(255) is the standard
  # fix and is idempotent (no-op if already wider). Skipped on a fresh DB
  # where the table doesn't exist yet — `flask db upgrade` will create it.
  python - <<'PY'
import os
import psycopg2

conn = psycopg2.connect(os.environ["DATABASE_URL"])
try:
    cur = conn.cursor()
    cur.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'alembic_version'
            ) THEN
                ALTER TABLE alembic_version
                    ALTER COLUMN version_num TYPE VARCHAR(255);
            END IF;
        END $$;
    """)
    conn.commit()
    print("[startup] alembic_version.version_num ensured >= VARCHAR(255)")
finally:
    conn.close()
PY
}

run_migrations() {
  if [ "${SKIP_DB_MIGRATE:-0}" = "1" ]; then
    log "Skipping migrations (SKIP_DB_MIGRATE=1)"
    return 0
  fi
  widen_alembic_version
  log "Running database migrations..."
  flask db upgrade
}

start_api() {
  log "Starting Gunicorn..."
  exec gunicorn -c gunicorn_conf.py "app:app"
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

