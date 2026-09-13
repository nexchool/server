"""
Celery application with Flask context support.

Uses ContextTask pattern so tasks run with Flask app context (db, config, etc).

Worker: celery -A celery_app:celery worker -l info
Beat:   celery -A celery_app:celery beat -l info
"""

import os

from celery import Celery
from celery.schedules import crontab

from core.school_time import DEFAULT_SCHOOL_TIMEZONE

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
            "tasks.subscription",
            "modules.school_setup.retention_tasks",
            "modules.announcements.tasks",
        ],
    )
    # Crontab hours below are read in this timezone. Every school on the
    # platform is in India (see core.school_time), and a UTC reading would put
    # every one of them 5h30m out — which is how a fee reminder scheduled for
    # "daily" reached parents at 23:01 local.
    celery.conf.timezone = DEFAULT_SCHOOL_TIMEZONE

    # Use new lowercase config keys; avoid celery.conf.update(app.config) to prevent old-key conflicts
    #
    # Anything rarer than hourly is a `crontab`, never an interval. An interval
    # counts from when beat last started, and beat's state file lives in /tmp
    # inside a container that every deploy replaces — so `86400.0` meant "a day
    # after the last deploy", and `604800` meant "never" on any repo that
    # deploys more than weekly. Production had not run either weekly job.
    celery.conf.beat_schedule = {
        "process-overdue-fees-daily": {
            "task": "process_overdue_fees_task",
            "schedule": crontab(hour=9, minute=0),
        },
        "retention-purge-notification-logs": {
            "task": "retention.purge_notification_logs",
            "schedule": crontab(hour=1, minute=15),
        },
        "retention-purge-expired-sessions": {
            "task": "retention.purge_expired_sessions",
            "schedule": crontab(hour=1, minute=30),
        },
        "retention-purge-audit-logs": {
            "task": "retention.purge_audit_logs",
            "schedule": crontab(hour=2, minute=0, day_of_week=0),
        },
        "retention-advance-offboarding": {
            "task": "retention.advance_offboarding_stage",
            "schedule": crontab(hour=2, minute=30, day_of_week=0),
        },
        # Hostel: detect gatepasses past expected return + grace period.
        # Every 5 minutes is responsive enough for warden alerts without
        # hammering the DB.
        "hostel-mark-overdue-gatepasses": {
            "task": "hostel.mark_overdue_gatepasses",
            "schedule": 300.0,  # 5 minutes
        },
        # Subscription: suspend schools whose payment grace period has run out.
        # Overnight — a school should not lose access mid-working-day.
        "subscription-suspend-after-grace": {
            "task": "subscription.suspend_after_grace",
            "schedule": crontab(hour=3, minute=0),
        },
        # Subscription: remind schools with an outstanding payment, once a day,
        # at an hour when somebody is at the desk to act on it.
        "subscription-send-payment-reminders": {
            "task": "subscription.send_payment_reminders",
            "schedule": crontab(hour=9, minute=30),
        },
        "announcements-process-scheduled": {
            "task": "announcements.process_scheduled",
            "schedule": 60.0,  # every minute
        },
        "announcements-sweep-orphan-attachments": {
            "task": "announcements.sweep_orphan_attachments",
            "schedule": crontab(hour=2, minute=45),
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

    # Safety: a stuck task (hung SMTP / WeasyPrint render / slow external call) must not hold a
    # worker slot forever — with concurrency 2, two stuck tasks would freeze all async work.
    # soft limit raises SoftTimeLimitExceeded (task can clean up); hard limit force-kills.
    celery.conf.task_soft_time_limit = int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "600"))
    celery.conf.task_time_limit = int(os.getenv("CELERY_TASK_TIME_LIMIT", "660"))
    # Long tasks + low concurrency: prefetch one at a time so work spreads evenly across workers.
    celery.conf.worker_prefetch_multiplier = 1

    # Nothing reads a task result. There is no `AsyncResult` in the codebase, no
    # blocking `.get(timeout=)`, and not one of the dispatch sites assigns what
    # `.delay()` returns — every task here is fire-and-forget: an email, a
    # notification fan-out, a PDF. Celery still stored a result for each of them
    # and kept it for a day, in the same 100 MB Redis the broker depends on.
    #
    # That is the largest avoidable pressure on a store where pressure used to
    # mean a queued message being evicted and the email simply never happening.
    celery.conf.task_ignore_result = True
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
