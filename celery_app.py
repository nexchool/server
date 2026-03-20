"""
Celery application with Flask context support.

Uses ContextTask pattern so tasks run with Flask app context (db, config, etc).

Worker: celery -A backend.celery_app:celery worker -l info
Beat:   celery -A backend.celery_app:celery beat -l info
"""

from celery import Celery

_celery = None


def make_celery(app):
    """Create Celery app bound to Flask app. Use ContextTask for db access."""
    broker = app.config.get("CELERY_BROKER_URL") or app.config.get("REDIS_URL") or "redis://localhost:6379/0"
    backend = app.config.get("CELERY_RESULT_BACKEND") or app.config.get("REDIS_URL") or "redis://localhost:6379/0"
    celery = Celery(
        app.import_name,
        broker=broker,
        backend=backend,
        include=[
            "backend.tasks.notifications",
            "backend.tasks.finance",
        ],
    )
    # Use new lowercase config keys; avoid celery.conf.update(app.config) to prevent old-key conflicts
    celery.conf.beat_schedule = {
        "process-overdue-fees-daily": {
            "task": "process_overdue_fees_task",
            "schedule": 86400.0,  # 24 hours
        },
    }

    class ContextTask(celery.Task):
        """Run task with Flask application context."""

        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    return celery


def init_celery(app):
    """Initialize Celery with Flask app. Call from create_app."""
    global _celery
    _celery = make_celery(app)
    return _celery


def get_celery():
    """Get Celery instance. Returns None if not initialized."""
    return _celery


# Worker entry: celery -A backend.celery_worker:celery worker -l info
# (celery_worker imports create_app, calls init_celery, exports celery - no circular import)
