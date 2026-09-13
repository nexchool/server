"""Notification fan-out and inbox reads must not scale queries with rows.

The scale contract is 15,000 students in one tenant. A per-recipient query in
the dispatch loop is 15,000 round trips for one announcement; a per-row query
in the inbox serializer is one per notification on every page load. Both were
present, and both are invisible on a seeded dev tenant of twenty users.

These tests measure the *slope*, not an absolute count: the same work is done
twice at two sizes and the query counts must match. A fixed budget would be a
constant to renegotiate every time an unrelated lookup moves, and would pass or
fail depending on what ran before it — the property worth protecting is that
the cost does not grow with the number of rows.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest
from sqlalchemy import event

from core.database import db
from modules.notifications.enums import NotificationRecipientStatus
from modules.notifications.models import Notification, NotificationRecipient

SMALL = 3
LARGE = 12


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@contextmanager
def count_queries():
    """Count statements issued on the test connection."""
    counter = {"n": 0}
    bind = db.session.get_bind()

    def _before(conn, cursor, statement, params, context, executemany):
        counter["n"] += 1

    event.listen(bind, "before_cursor_execute", _before)
    try:
        yield counter
    finally:
        event.remove(bind, "before_cursor_execute", _before)


def _make_users(db_session, tenant, count):
    from modules.auth.models import User

    users = []
    for _ in range(count):
        u = User(
            id=_uid("u"),
            tenant_id=tenant.id,
            email=f"{_uid('c')}@test.school",
            password_hash="x" * 60,
            name="Member",
        )
        db_session.add(u)
        users.append(u)
    db_session.flush()
    return users


def _make_fanout(db_session, tenant, users):
    notification = Notification(
        id=_uid("n"),
        tenant_id=tenant.id,
        user_id=None,
        type="ANNOUNCEMENT",
        channel="IN_APP",
        title="Fee deadline extended",
        body="Now the 30th.",
        extra_data={"_dispatch_channels": ["IN_APP"]},
    )
    db_session.add(notification)
    for u in users:
        db_session.add(
            NotificationRecipient(
                id=_uid("nr"),
                notification_id=notification.id,
                user_id=u.id,
                status=NotificationRecipientStatus.PENDING.value,
            )
        )
    db_session.flush()
    return notification


@pytest.fixture
def _flat_dispatch(monkeypatch):
    """The dispatcher is exercised elsewhere; it must not add queries here."""
    import modules.notifications.services as services

    monkeypatch.setattr(
        services.notification_dispatcher, "dispatch", lambda **kwargs: {"IN_APP": True}
    )


def test_dispatch_chunk_cost_does_not_grow_with_recipients(
    db_session, tenant, _flat_dispatch
):
    """A fan-out chunk costs the same for 12 recipients as for 3."""
    from tasks.notification_dispatch import process_notification_chunk

    counts = {}
    for size in (SMALL, LARGE):
        users = _make_users(db_session, tenant, size)
        notification = _make_fanout(db_session, tenant, users)

        # Read every attribute the measurement needs before opening the
        # counter, so no setup work is metered. (If this setup ever commits,
        # the session expires these objects and the first touch of `.id` emits
        # a refresh SELECT per row — indistinguishable from the N+1 under test.)
        user_ids = [u.id for u in users]
        notification_id = notification.id

        with count_queries() as counted:
            process_notification_chunk(notification_id, user_ids)
        counts[size] = counted["n"]

        marked = NotificationRecipient.query.filter_by(
            notification_id=notification.id
        ).all()
        assert {r.status for r in marked} == {NotificationRecipientStatus.SENT.value}

    assert counts[SMALL] == counts[LARGE], (
        f"{counts[SMALL]} queries for {SMALL} recipients but {counts[LARGE]} for "
        f"{LARGE} — dispatch is querying per recipient"
    )


def test_inbox_serialization_cost_does_not_grow_with_page_size(db_session, tenant):
    """Serializing 12 notifications costs the same as serializing 3."""
    from modules.notifications.routes import _serialize_page

    reader = _make_users(db_session, tenant, 1)[0]
    reader_id = reader.id
    counts = {}
    made = []

    for size in (SMALL, LARGE):
        while len(made) < size:
            n = Notification(
                id=_uid("n"),
                tenant_id=tenant.id,
                user_id=None,
                type="ANNOUNCEMENT",
                channel="IN_APP",
                title="Notice",
                body="Body",
            )
            db_session.add(n)
            db_session.add(
                NotificationRecipient(
                    id=_uid("nr"),
                    notification_id=n.id,
                    user_id=reader.id,
                    status=NotificationRecipientStatus.SENT.value,
                )
            )
            made.append(n)
        db_session.flush()

        # Materialize the page before opening the counter, for the same reason.
        page = made[:size]
        [n.id for n in page]

        with count_queries() as counted:
            data = _serialize_page(page, reader_id)
        counts[size] = counted["n"]

        assert len(data) == size
        assert all(item["recipient_id"] for item in data)

    assert counts[SMALL] == counts[LARGE], (
        f"{counts[SMALL]} queries for {SMALL} notifications but {counts[LARGE]} for "
        f"{LARGE} — the serializer is querying per row"
    )
