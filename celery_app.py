"""
Celery application with Flask context support.

Uses ContextTask pattern so tasks run with Flask app context (db, config, etc).

Worker: celery -A celery_app:celery worker -l info
Beat:   celery -A celery_app:celery beat -l info
"""

import os

from celery import Celery

_celery = None


def make_celery(app):
    """Create Celery app bound to Flask app. Use ContextTask for db access."""
    broker = app.config.get("CELERY_BROKER_URL") or app.config.get("REDIS_URL") or "redis://localhost:6379/0"
    backend = app.config.get("CELERY_RESULT_BACKEND") or app.config.get("REDIS_URL") or "redis://localhost:6379/0"
    # Default fallback for local Docker Compose (can be overridden via REDIS_URL env var).
    # Keep it Docker-friendly to avoid accidental "localhost" failures inside containers.
    broker = broker.replace("redis://localhost:6379/0", "redis://redis:6379/0")
    backend = backend.replace("redis://localhost:6379/0", "redis://redis:6379/0")
    celery = Celery(
        app.import_name,
        broker=broker,
        backend=backend,
        include=[
            "tasks.notifications",
            "tasks.finance",
            "tasks.notification_dispatch",
            "tasks.push_notifications",
            "tasks.hostel",
            "modules.school_setup.retention_tasks",
        ],
    )
    # Use new lowercase config keys; avoid celery.conf.update(app.config) to prevent old-key conflicts
    celery.conf.beat_schedule = {
        "process-overdue-fees-daily": {
            "task": "process_overdue_fees_task",
            "schedule": 86400.0,  # 24 hours
        },
        "retention-purge-notification-logs": {
            "task": "retention.purge_notification_logs",
            "schedule": 86400,
        },
        "retention-purge-audit-logs": {
            "task": "retention.purge_audit_logs",
            "schedule": 604800,
        },
        "retention-advance-offboarding": {
            "task": "retention.advance_offboarding_stage",
            "schedule": 604800,
        },
        # Hostel: detect gatepasses past expected return + grace period.
        # Every 5 minutes is responsive enough for warden alerts without
        # hammering the DB.
        "hostel-mark-overdue-gatepasses": {
            "task": "hostel.mark_overdue_gatepasses",
            "schedule": 300.0,  # 5 minutes
        },
    }
    # Default cwd is /app (owned by app) but a root-owned celerybeat-schedule from an old run breaks beat.
    # /tmp is always writable for the container user. Override with CELERY_BEAT_SCHEDULE_FILENAME if needed.
    celery.conf.beat_schedule_filename = os.environ.get(
        "CELERY_BEAT_SCHEDULE_FILENAME", "/tmp/celerybeat-schedule"
    )

    class ContextTask(celery.Task):
        """Run task with Flask application context."""

        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    # Celery 6: startup retries no longer follow broker_connection_retry; keep current behavior.
    celery.conf.broker_connection_retry_on_startup = True
    return celery


def init_celery(app):
    """Initialize Celery with Flask app. Call from create_app."""
    global _celery
    _celery = make_celery(app)
    return _celery


def get_celery():
    """Get Celery instance. Returns None if not initialized."""
    return _celery


# Worker entry: celery -A celery_worker:celery worker -l info
# (celery_worker imports create_app, calls init_celery, exports celery - no circular import)
