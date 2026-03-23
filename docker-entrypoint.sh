#!/bin/sh
set -e

# Production-like startup:
# - wait for DB
# - run migrations
# - start Gunicorn (or embedded Celery+Gunicorn when requested)
exec /app/startup.sh
