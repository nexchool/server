"""Login sessions do not accumulate forever.

A row is written per login and nothing pruned them. Notification logs and audit
logs each had a retention job; sessions — the table guaranteed to grow fastest,
one row per sign-in per device — had none. `auth/services.py` carried a
`cleanup_expired_sessions` whose docstring said it "should be run periodically
(e.g., via cron job)", and nothing ever did.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from core.school_time import utc_now


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def user(db_session, tenant):
    from modules.auth.models import User

    suffix = uuid.uuid4().hex[:8]
    row = User(
        id=f"u-{suffix}", tenant_id=tenant.id, email=f"{suffix}@test.school",
        password_hash="x" * 60, name="Somebody",
    )
    db_session.add(row)
    db_session.flush()
    return row


def _session(db_session, tenant, user, *, expires_in_days: int):
    from modules.auth.models import Session

    row = Session(
        id=_new_id("s-"),
        user_id=user.id,
        tenant_id=tenant.id,
        refresh_token=f"tok-{uuid.uuid4().hex}",
        refresh_token_expires_at=utc_now() + timedelta(days=expires_in_days),
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_the_job_is_on_the_schedule(flask_app):
    """A task nothing runs is what this replaced — so assert it is scheduled.

    Uses the session's app rather than building one: `make_celery` rebinds the
    SQLAlchemy instance to whatever app it is given, so a throwaway app here
    leaves every later test in this file talking to an engine that no longer
    exists.
    """
    from celery_app import make_celery

    celery = make_celery(flask_app)
    tasks = {entry["task"] for entry in celery.conf.beat_schedule.values()}
    assert "retention.purge_expired_sessions" in tasks


def test_an_expired_session_is_deleted(flask_app, db_session, tenant, user):
    from modules.auth.models import Session
    from modules.school_setup.retention_tasks import purge_expired_sessions

    stale = _session(db_session, tenant, user, expires_in_days=-1)
    stale_id = stale.id

    purge_expired_sessions()

    assert Session.query.filter_by(id=stale_id).first() is None


def test_a_live_session_survives(flask_app, db_session, tenant, user):
    """The obvious way to get this wrong is to empty the table."""
    from modules.auth.models import Session
    from modules.school_setup.retention_tasks import purge_expired_sessions

    live = _session(db_session, tenant, user, expires_in_days=7)
    live_id = live.id

    purge_expired_sessions()

    assert Session.query.filter_by(id=live_id).first() is not None
