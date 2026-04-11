#!/bin/bash
# All-in-one: Gunicorn + Celery worker with embedded beat in a single container.
# Intended for small setups; set RUN_EMBEDDED_CELERY=1 on the API container.
# When using docker-compose.yml with separate celery-worker / celery-beat services,
# keep RUN_EMBEDDED_CELERY unset so only Gunicorn runs in the API container.

cd "$(dirname "$0")"

# Fix for macOS + Conda/Anaconda: prevents "objc initialize fork" crash
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES

echo "Starting Celery worker + beat..."

# Run only ONE celery worker to keep memory low
celery -A celery_worker:celery worker -B --concurrency=1 -l info &

echo "Starting Flask API with Gunicorn..."

# Run only one gunicorn worker
exec gunicorn -c gunicorn_conf.py app:app --workers 1 --threads 2