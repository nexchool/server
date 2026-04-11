# Database Migrations

## Before Running Migrations

**IMPORTANT:** For migrations that modify core schema (e.g. `007_academic_year_id`), take a full database backup first:

```bash
# PostgreSQL
pg_dump -U <user> -d <database> -F c -f backup_pre_migration_$(date +%Y%m%d).dump
```

Or use your hosting provider's backup feature.

## Running Migrations

```bash
cd app
flask db upgrade
```

## Celery (Async Jobs)

After migration, for async email and overdue fee processing:

```bash
# Start Redis (if not running)
# macOS: brew services start redis

# Celery worker
celery -A celery_worker:celery worker -l info

# Celery beat (scheduled tasks, e.g. overdue fees daily)
celery -A celery_worker:celery beat -l info
```

Configure `REDIS_URL` in `.env` (default: `redis://localhost:6379/0`).