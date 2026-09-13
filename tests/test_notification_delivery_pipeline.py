"""The bulk fan-out contract: creating recipients is not delivering them.

`notification_service.create_notification()` + `create_recipients()` only write
rows. Nothing leaves the server until `send_notification()` enqueues
`dispatch_notification_task`, and that task runs in a *different process* — so
the rows must be committed before it is enqueued, or the worker looks for a
notification that its own transaction never saw.

Three producers wrote the rows and stopped there. Their recipients sat at
`pending` forever: no push, no email, no realtime inbox event. Production had
30 such rows from a single August afternoon.

Every test here asserts the same two things about a producer — dispatch was
enqueued, and nothing was still uncommitted when it was.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from core.database import db
from modules.notifications.models import Notification, NotificationRecipient


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@pytest.fixture
def recipients(db_session, tenant):
    """Two users in the tenant, eligible to receive a notification."""
    from modules.auth.models import User

    users = []
    for i in range(2):
        u = User(
            id=_uid("u"),
            tenant_id=tenant.id,
            email=f"{_uid('r')}@test.school",
            password_hash="x" * 60,
            name=f"Recipient {i}",
        )
        db_session.add(u)
        users.append(u)
    db_session.flush()
    return users


class _DispatchSpy:
    """Records calls to send_notification and the session state at call time.

    `pending_at_call` is the point of the exercise: the Celery worker runs in
    another process and can only see committed rows, so anything still sitting
    in `session.new` when dispatch is enqueued is a row the worker will not
    find.
    """

    def __init__(self):
        self.notification_ids = []
        self.pending_at_call = []

    def __call__(self, notification_id):
        self.notification_ids.append(notification_id)
        self.pending_at_call.append(
            [obj for obj in db.session.new if isinstance(obj, (Notification, NotificationRecipient))]
        )
        return True

    def assert_dispatched_cleanly(self):
        assert self.notification_ids, "producer never enqueued dispatch_notification_task"
        assert self.pending_at_call[0] == [], (
            "dispatch was enqueued while notification rows were still uncommitted — "
            "the worker process cannot see them"
        )


# ---------------------------------------------------------------------------
# Announcements
# ---------------------------------------------------------------------------

def test_announcement_fan_out_dispatches_and_commits(db_session, tenant, recipients, monkeypatch):
    """Publishing an announcement must actually deliver it, not just record it."""
    from modules.announcements.models import Announcement
    import modules.announcements.services as svc
    import modules.notifications.notification_service as ns
    import modules.announcements.tasks as tasks

    announcement = Announcement(
        id=_uid("a"),
        tenant_id=tenant.id,
        title="Sports day moved to Friday",
        body_markdown="The ground is waterlogged.",
        audience_json={"all": True},
        status="published",
        published_at=datetime.now(timezone.utc),
    )
    db_session.add(announcement)
    db_session.flush()

    monkeypatch.setattr(svc, "_resolve_audience", lambda _t, _a: [u.id for u in recipients])
    spy = _DispatchSpy()
    monkeypatch.setattr(ns, "send_notification", spy)

    tasks.announcement_fan_out(announcement.id)

    spy.assert_dispatched_cleanly()

    created = Notification.query.filter_by(
        tenant_id=tenant.id, type="announcement.published"
    ).one()
    assert created.id == spy.notification_ids[0]
    assert NotificationRecipient.query.filter_by(notification_id=created.id).count() == 2


def test_announcement_recall_fan_out_dispatches_and_commits(
    db_session, tenant, recipients, monkeypatch
):
    """A recall is the message people most need to actually receive."""
    from modules.announcements.models import Announcement
    import modules.announcements.services as svc
    import modules.notifications.notification_service as ns
    import modules.announcements.tasks as tasks

    announcement = Announcement(
        id=_uid("a"),
        tenant_id=tenant.id,
        title="Sports day moved to Friday",
        body_markdown="The ground is waterlogged.",
        audience_json={"all": True},
        status="recalled",
        recalled_at=datetime.now(timezone.utc),
        recalled_reason="Posted to the wrong campus",
    )
    db_session.add(announcement)
    db_session.flush()

    monkeypatch.setattr(svc, "_resolve_audience", lambda _t, _a: [u.id for u in recipients])
    spy = _DispatchSpy()
    monkeypatch.setattr(ns, "send_notification", spy)

    tasks.announcement_recall_fan_out(announcement.id, "Posted to the wrong campus")

    spy.assert_dispatched_cleanly()


# ---------------------------------------------------------------------------
# Academic calendar
# ---------------------------------------------------------------------------

def test_calendar_change_dispatches(db_session, tenant, recipients, monkeypatch):
    """A holiday nobody is told about is not a holiday anyone can plan around."""
    import modules.academics.calendar.activity as activity
    import modules.notifications.notification_service as ns
    import modules.notifications.notification_targeting_service as targeting

    monkeypatch.setattr(
        targeting,
        "get_users_by_role",
        lambda role, _tenant: recipients if role == "Admin" else [],
    )
    spy = _DispatchSpy()
    monkeypatch.setattr(ns, "send_notification", spy)

    activity.notify_calendar_change(
        title="Diwali break added",
        body="School closed 20-26 October.",
        tenant_id=tenant.id,
    )

    spy.assert_dispatched_cleanly()


# ---------------------------------------------------------------------------
# Student leaves
# ---------------------------------------------------------------------------

def test_student_leave_notification_dispatches_to_many(
    db_session, tenant, recipients, monkeypatch
):
    """Multi-recipient leave notifications go through the bulk fan-out path."""
    import modules.student_leaves.services as leaves
    import modules.notifications.notification_service as ns

    spy = _DispatchSpy()
    monkeypatch.setattr(ns, "send_notification", spy)

    leaves._notify(
        tenant_id=tenant.id,
        notification_type="STUDENT_LEAVE_REQUESTED",
        title="Leave request from Aarav Shah",
        body="2 days, medical.",
        recipient_user_ids=[u.id for u in recipients],
    )

    spy.assert_dispatched_cleanly()


def test_student_leave_notification_dispatches_to_one(
    db_session, tenant, recipients, monkeypatch
):
    """The single-recipient path takes a different branch and must dispatch too."""
    import modules.student_leaves.services as leaves
    import modules.notifications.notification_service as ns

    spy = _DispatchSpy()
    monkeypatch.setattr(ns, "send_notification", spy)

    leaves._notify(
        tenant_id=tenant.id,
        notification_type="STUDENT_LEAVE_APPROVED",
        title="Your leave was approved",
        body="20-21 October.",
        recipient_user_ids=[recipients[0].id],
    )

    spy.assert_dispatched_cleanly()


# ---------------------------------------------------------------------------
# Push delivery
# ---------------------------------------------------------------------------

def test_push_survives_a_user_who_was_once_locked_out(db_session, tenant, recipients):
    """`login_locked_until` is TIMESTAMPTZ, so it comes back timezone-aware.

    Comparing it to a naive `datetime.utcnow()` raises TypeError, which
    `autoretry_for=(Exception,)` turns into three retries and then silence —
    permanently, because a lockout timestamp is never cleared once set. Any
    user who has ever fat-fingered their password five times stops receiving
    push forever.
    """
    from modules.devices.models import DeviceToken
    from tasks.push_notifications import send_push_task

    user = recipients[0]
    user.login_locked_until = datetime.now(timezone.utc) - timedelta(days=30)
    db_session.add(
        DeviceToken(
            id=_uid("dt"),
            tenant_id=tenant.id,
            user_id=user.id,
            device_token="ExponentPushToken[test-token-value]",
            platform="android",
            provider="expo",
            is_active=True,
        )
    )
    db_session.flush()

    result = send_push_task.apply(
        args=[user.id, tenant.id, None, "ANNOUNCEMENT", "Title", "Body", "{}"]
    )

    assert result.successful(), f"send_push_task raised: {result.traceback}"


def test_push_still_skips_a_currently_locked_user(db_session, tenant, recipients):
    """The lock check itself must keep working — an active lock still skips."""
    from tasks.push_notifications import send_push_task

    user = recipients[0]
    user.login_locked_until = datetime.now(timezone.utc) + timedelta(hours=1)
    db_session.flush()

    result = send_push_task.apply(
        args=[user.id, tenant.id, None, "ANNOUNCEMENT", "Title", "Body", "{}"]
    )

    assert result.successful()
    assert result.result == {"skipped": True, "reason": "user_locked"}
def test_scheduled_announcement_commits_before_enqueueing_fan_out(
    db_session, tenant, monkeypatch
):
    """The beat task must not hand the worker a row it has not committed yet.

    `process_scheduled_announcements` flipped status to "published", called
    `.delay()`, and only committed after the loop. The worker is a separate
    process with its own connection, and its first act is
    `if a.status != "published": return`. Until that commit lands the worker
    reads "scheduled" — so winning the race means the announcement is
    published in the database, delivered to nobody, and logged as a routine
    "fan_out skipped".

    Ordering is the invariant, so ordering is what this asserts.
    """
    from sqlalchemy import event

    from modules.announcements.models import Announcement
    import modules.announcements.tasks as tasks

    announcement = Announcement(
        id=_uid("a"),
        tenant_id=tenant.id,
        title="Parent-teacher meeting Saturday",
        body_markdown="10am in the main hall.",
        audience_json={"all": True},
        status="scheduled",
        scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db_session.add(announcement)
    # Committed, not flushed, so the only commit the event log below records is
    # the one the task itself makes — this test is about ordering, and setup
    # must not appear in the ordering.
    db_session.commit()

    log = []

    def _on_commit(_session):
        log.append("commit")

    monkeypatch.setattr(tasks.announcement_fan_out, "delay", lambda _id: log.append("enqueue"))
    event.listen(db.session, "after_commit", _on_commit)
    try:
        fired = tasks.process_scheduled_announcements()
    finally:
        event.remove(db.session, "after_commit", _on_commit)

    assert fired == 1
    assert "enqueue" in log, "scheduled announcement never enqueued fan-out"
    assert log.index("commit") < log.index("enqueue"), (
        f"fan-out enqueued before the status flip was committed (order: {log}) — "
        "the worker can read status='scheduled' and skip delivery"
    )
