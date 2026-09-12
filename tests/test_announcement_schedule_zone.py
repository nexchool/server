"""A scheduled announcement goes out when the school said, not when Greenwich did.

`schedule()` takes an ISO stamp. One with an offset is an instant and is kept
as sent. One without is a wall-clock time somebody typed, and used to be read
as UTC — so "10:00" from an Indian school was stored as 10:00 UTC, five and a
half hours after the assembly it was meant to precede.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from flask import g

from modules.announcements.models import Announcement
from modules.announcements.services import schedule

UTC = timezone.utc


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


@pytest.fixture
def draft(db_session, tenant):
    a = Announcement(
        id=f"an-{uuid.uuid4().hex[:12]}",
        tenant_id=tenant.id,
        title="Assembly at ten",
        body_markdown="Be in the hall by 09:50.",
        audience_json={"scope": "all"},
        status="draft",
    )
    db_session.add(a)
    db_session.flush()
    return a


def test_a_wall_clock_time_is_the_school_s_clock(ctx, db_session, draft):
    a = schedule(draft.id, actor_user_id="u-1", scheduled_at="2099-01-01T10:00:00")
    assert a.status == "scheduled"
    assert a.scheduled_at == datetime(2099, 1, 1, 4, 30, tzinfo=UTC)


def test_an_instant_with_an_offset_is_kept_as_sent(ctx, db_session, draft):
    a = schedule(draft.id, actor_user_id="u-1", scheduled_at="2099-01-01T04:30:00Z")
    assert a.scheduled_at == datetime(2099, 1, 1, 4, 30, tzinfo=UTC)
