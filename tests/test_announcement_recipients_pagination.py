"""A read-receipt roster is one row per person the announcement reached.

`list_recipients` selected all of them with `.all()` and returned a bare list.
A notice to the whole school is one row per parent, so at 15,000 students that
is a single response holding the entire roster — and both clients then derive
their "read / total" counter from `array.length`, which is what makes a naive
server-side cap *worse* than no cap: the numbers would silently become wrong
rather than visibly truncate.

So the counts have to move to the server before the list can be bounded. This
pins the envelope both screens need — the page, plus totals computed in SQL
over the whole roster — and the ordering that makes paging coherent at all.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from flask import g

from modules.announcements import services


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


def _roster(db_session, tenant, *, size: int, read: int = 0):
    """An announcement fanned out to `size` people, `read` of whom opened it.

    Everyone is deliberately given the *same* display name. Ordering by name
    alone leaves the order of ties unspecified, and unspecified order across
    two pages means a person can appear twice or not at all.
    """
    from modules.announcements.models import Announcement
    from modules.auth.models import User
    from modules.notifications.models import Notification, NotificationRecipient

    suffix = uuid.uuid4().hex[:8]
    announcement = Announcement(
        id=f"an-{suffix}",
        tenant_id=tenant.id,
        title="School reopens Monday",
        body_markdown="Please note the revised timings.",
        audience_json={"scope": "all"},
        status="published",
        published_at=datetime.now(timezone.utc),
    )
    db_session.add(announcement)
    db_session.flush()

    notification = Notification(
        id=f"no-{suffix}",
        tenant_id=tenant.id,
        type="announcement.published",
        channel="in_app",
        title=announcement.title,
        extra_data={"announcement_id": announcement.id},
    )
    db_session.add(notification)
    db_session.flush()

    user_ids = []
    for i in range(size):
        user = User(
            id=f"u-{suffix}-{i:04d}",
            tenant_id=tenant.id,
            email=f"{suffix}-{i}@test.school",
            password_hash="x" * 60,
            name="Parent",  # identical on purpose — see docstring
        )
        db_session.add(user)
        db_session.add(
            NotificationRecipient(
                id=f"nr-{suffix}-{i:04d}",
                notification_id=notification.id,
                user_id=user.id,
                status="delivered",
                read_at=datetime.now(timezone.utc) if i < read else None,
            )
        )
        user_ids.append(user.id)
    db_session.flush()
    return announcement, user_ids


# ---------------------------------------------------------------------------
# The page is bounded; the counts are not
# ---------------------------------------------------------------------------

def test_the_roster_comes_back_a_page_at_a_time(ctx, db_session, tenant):
    announcement, _ = _roster(db_session, tenant, size=120)

    result = services.list_recipients(announcement.id)

    assert len(result["items"]) <= services.RECIPIENTS_PAGE_SIZE
    assert len(result["items"]) < 120, "the whole roster must not arrive at once"


def test_the_total_describes_the_roster_not_the_page(ctx, db_session, tenant):
    """This is the number the counter shows, so it cannot be `len(items)`."""
    announcement, _ = _roster(db_session, tenant, size=120)

    result = services.list_recipients(announcement.id)

    assert result["total"] == 120


def test_the_read_count_is_counted_across_the_whole_roster(ctx, db_session, tenant):
    """Both screens render "read / total", and read people are not all on page 1."""
    announcement, _ = _roster(db_session, tenant, size=120, read=75)

    result = services.list_recipients(announcement.id)

    assert result["read_count"] == 75, (
        "counting only the rows on this page would report 20-odd of 120"
    )


def test_a_small_roster_still_returns_everybody(ctx, db_session, tenant):
    announcement, user_ids = _roster(db_session, tenant, size=3, read=1)

    result = services.list_recipients(announcement.id)

    assert {r["user_id"] for r in result["items"]} == set(user_ids)
    assert result["total"] == 3
    assert result["read_count"] == 1
    assert result["total_pages"] == 1


# ---------------------------------------------------------------------------
# Paging is only coherent if the order is total
# ---------------------------------------------------------------------------

def test_paging_the_whole_roster_sees_each_person_exactly_once(
    ctx, db_session, tenant
):
    """With every name identical, ordering by name alone loses rows.

    Postgres may return tied rows in any order, and a different order between
    two LIMIT/OFFSET queries means someone is served twice and someone else
    never appears.
    """
    announcement, user_ids = _roster(db_session, tenant, size=120)

    seen: list[str] = []
    page = 1
    while True:
        result = services.list_recipients(announcement.id, page=page)
        seen.extend(r["user_id"] for r in result["items"])
        if page >= result["total_pages"]:
            break
        page += 1

    assert len(seen) == len(set(seen)), "a row was served on two pages"
    assert set(seen) == set(user_ids), "a row was never served at all"


def test_a_page_past_the_end_is_empty_rather_than_an_error(ctx, db_session, tenant):
    announcement, _ = _roster(db_session, tenant, size=3)

    result = services.list_recipients(announcement.id, page=99)

    assert result["items"] == []
    assert result["total"] == 3, "the counter must survive an overshoot"


# ---------------------------------------------------------------------------
# The caller does not get to ask for the whole school back
# ---------------------------------------------------------------------------

def test_an_enormous_page_size_is_capped(ctx, db_session, tenant):
    announcement, _ = _roster(db_session, tenant, size=120)

    result = services.list_recipients(announcement.id, per_page=100_000)

    assert len(result["items"]) <= services.RECIPIENTS_MAX_PAGE_SIZE


@pytest.mark.parametrize("bad", [0, -1, "abc", None])
def test_a_nonsense_page_is_treated_as_the_first(ctx, db_session, tenant, bad):
    """These arrive from a query string, so they must not raise."""
    announcement, _ = _roster(db_session, tenant, size=3)

    result = services.list_recipients(announcement.id, page=bad)

    assert result["page"] == 1
    assert result["total"] == 3
