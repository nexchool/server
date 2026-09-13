"""Recurring jobs must be anchored to the clock, not to the last deploy.

A `"schedule": 86400.0` entry means "24 hours after beat last started it",
and beat's state lives in `/tmp/celerybeat-schedule` — inside a container that
`docker compose pull && up -d` throws away. So every deploy restarts every
countdown.

For a daily job that means it fires at whatever time of day the last deploy
happened: production was sending FEE_OVERDUE notifications at 17:31 UTC, which
is 23:01 for a parent in India. For a weekly job it means it may never fire at
all — `retention.purge_audit_logs` and `retention.advance_offboarding_stage`
had zero firings across the 5.6 days beat had then been up, and a repo that
deploys weekly or more often never reaches day seven.

A `crontab()` fires at a wall-clock time and a restart cannot shift it.

Note for anyone extending this file: **do not call `create_app()` here.**
`app.py` calls `init_celery(app)`, which rebinds the module-global `_celery` to
whatever app was passed — including its engine registry. A second app built
inside a test therefore points every later Celery task at the real database
instead of the test transaction, and the damage lands on whichever test runs
next, not on this one. Read the live instance through `get_celery()` instead;
it is also the more honest assertion, since it is the object the workers use.
"""

from __future__ import annotations

import pytest
from celery.schedules import crontab

from celery_app import get_celery
from core.school_time import DEFAULT_SCHOOL_TIMEZONE

# Anything rarer than hourly must name its time of day. Sub-hourly polling
# ("has a gatepass gone overdue?", "is a scheduled announcement due?") is
# correctly expressed as an interval — a restart costs at most one cycle.
HOURLY_SECONDS = 3600


@pytest.fixture
def celery_conf(flask_app):
    """The configuration the real workers run with."""
    celery = get_celery()
    assert celery is not None, "celery was never initialized by create_app()"
    return celery.conf


def test_infrequent_jobs_are_wall_clock_anchored(celery_conf):
    offenders = [
        name
        for name, entry in celery_conf.beat_schedule.items()
        if isinstance(entry["schedule"], (int, float))
        and entry["schedule"] > HOURLY_SECONDS
    ]
    assert offenders == [], (
        "these run less often than hourly but are scheduled by interval, so a "
        f"redeploy moves or skips them: {offenders}"
    )


def test_parent_facing_jobs_run_at_a_civil_hour(celery_conf):
    """Fee and payment reminders reach a person's phone. Not at midnight."""
    parent_facing = [
        "process-overdue-fees-daily",
        "subscription-send-payment-reminders",
    ]
    for name in parent_facing:
        entry = celery_conf.beat_schedule[name]["schedule"]
        assert isinstance(entry, crontab), f"{name} is not a crontab"
        hours = entry.hour
        assert all(8 <= h <= 20 for h in hours), (
            f"{name} fires at hour(s) {sorted(hours)} in {celery_conf.timezone} — "
            "outside waking hours for the recipient"
        )


def test_schedule_timezone_is_the_school_timezone(celery_conf):
    """Crontab hours are read in this timezone; UTC would be 5h30m off in India."""
    assert celery_conf.timezone == DEFAULT_SCHOOL_TIMEZONE
