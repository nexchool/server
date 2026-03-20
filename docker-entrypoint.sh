#!/bin/sh
set -e
cd /app

if [ "${SKIP_DB_MIGRATE:-0}" != "1" ]; then
  echo "Running database migrations..."
  flask db upgrade
fi

# Single-container / local shell convenience: worker + beat + gunicorn in one process tree.
# Do NOT set this when using docker-compose with separate celery-worker / celery-beat services.
if [ "${RUN_EMBEDDED_CELERY:-0}" = "1" ]; then
  echo "Starting API with embedded Celery (run_gunicorn.sh)..."
  exec ./run_gunicorn.sh
fi

echo "Starting gunicorn..."
exec gunicorn -c gunicorn_conf.py "backend.app:app"
