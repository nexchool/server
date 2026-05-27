"""Service-level tests for announcement CRUD + state transitions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.database import db
from modules.announcements.services import (
    create_draft,
    update_announcement,
    publish,
    schedule,
    unschedule,
    recall,
    ValidationError,
    StateError,
)
from modules.announcements.models import AnnouncementRevision


def _audience():
    return {"scope": "all"}


def test_create_draft_minimal(tenant_ctx, author_user):
    a = create_draft(
        title="Welcome", body_markdown="Hello school!",
        audience_json=_audience(), actor_user_id=author_user.id,
    )
    assert a.status == "draft"
    assert a.revision_count == 1
    assert a.published_at is None
    assert a.author_user_id == author_user.id


def test_create_draft_rejects_invalid_audience_scope(tenant_ctx, author_user):
    with pytest.raises(ValidationError):
        create_draft(
            title="x", body_markdown="y",
            audience_json={"scope": "invalid"}, actor_user_id=author_user.id,
        )


def test_create_draft_rejects_empty_title(tenant_ctx, author_user):
    with pytest.raises(ValidationError):
        create_draft(
            title="", body_markdown="y",
            audience_json=_audience(), actor_user_id=author_user.id,
        )


def test_update_draft_overwrites_in_place(tenant_ctx, author_user):
    a = create_draft(
        title="A", body_markdown="b",
        audience_json=_audience(), actor_user_id=author_user.id,
    )
    updated = update_announcement(
        a.id, actor_user_id=author_user.id,
        title="A new", body_markdown="b new",
    )
    assert updated.title == "A new"
    assert updated.revision_count == 1
    assert db.session.query(AnnouncementRevision).filter_by(announcement_id=a.id).count() == 0


def test_publish_writes_revision_1(tenant_ctx, author_user, monkeypatch):
    from modules.announcements import services as svc
    monkeypatch.setattr(svc, "_enqueue_fan_out", lambda announcement_id: None)
    a = create_draft(
        title="A", body_markdown="b",
        audience_json=_audience(), actor_user_id=author_user.id,
    )
    published = publish(a.id, actor_user_id=author_user.id)
    assert published.status == "published"
    assert published.published_at is not None
    rev = db.session.query(AnnouncementRevision).filter_by(announcement_id=a.id).one()
    assert rev.revision_number == 1
    assert rev.title == "A"


def test_update_published_appends_revision(tenant_ctx, author_user, monkeypatch):
    from modules.announcements import services as svc
    monkeypatch.setattr(svc, "_enqueue_fan_out", lambda announcement_id: None)
    a = create_draft(
        title="A", body_markdown="b",
        audience_json=_audience(), actor_user_id=author_user.id,
    )
    publish(a.id, actor_user_id=author_user.id)
    updated = update_announcement(
        a.id, actor_user_id=author_user.id,
        title="A v2", body_markdown="b v2", edit_note="typo",
    )
    assert updated.revision_count == 2
    revisions = (
        db.session.query(AnnouncementRevision)
        .filter_by(announcement_id=a.id)
        .order_by(AnnouncementRevision.revision_number)
        .all()
    )
    assert [r.title for r in revisions] == ["A", "A v2"]
    assert revisions[1].edit_note == "typo"


def test_schedule_and_unschedule(tenant_ctx, author_user):
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    a = create_draft(
        title="A", body_markdown="b",
        audience_json=_audience(), actor_user_id=author_user.id,
    )
    scheduled = schedule(a.id, actor_user_id=author_user.id, scheduled_at=future.isoformat())
    assert scheduled.status == "scheduled"
    assert scheduled.scheduled_at is not None
    back_to_draft = unschedule(a.id, actor_user_id=author_user.id)
    assert back_to_draft.status == "draft"
    assert back_to_draft.scheduled_at is None


def test_schedule_rejects_past_time(tenant_ctx, author_user):
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    a = create_draft(
        title="A", body_markdown="b",
        audience_json=_audience(), actor_user_id=author_user.id,
    )
    with pytest.raises(ValidationError):
        schedule(a.id, actor_user_id=author_user.id, scheduled_at=past.isoformat())


def test_recall_published(tenant_ctx, author_user, monkeypatch):
    from modules.announcements import services as svc
    monkeypatch.setattr(svc, "_enqueue_fan_out", lambda announcement_id: None)
    monkeypatch.setattr(svc, "_enqueue_recall_fan_out", lambda announcement_id, reason: None)
    a = create_draft(
        title="A", body_markdown="b",
        audience_json=_audience(), actor_user_id=author_user.id,
    )
    publish(a.id, actor_user_id=author_user.id)
    recalled = recall(a.id, actor_user_id=author_user.id, reason="Sent in error")
    assert recalled.status == "recalled"
    assert recalled.recalled_at is not None
    assert recalled.recalled_reason == "Sent in error"


def test_recall_rejects_draft(tenant_ctx, author_user):
    a = create_draft(
        title="A", body_markdown="b",
        audience_json=_audience(), actor_user_id=author_user.id,
    )
    with pytest.raises(StateError):
        recall(a.id, actor_user_id=author_user.id, reason="nope")


def test_revision_pruning_at_10_cap(tenant_ctx, author_user, monkeypatch):
    from modules.announcements import services as svc
    monkeypatch.setattr(svc, "_enqueue_fan_out", lambda announcement_id: None)
    a = create_draft(
        title="A", body_markdown="b",
        audience_json=_audience(), actor_user_id=author_user.id,
    )
    publish(a.id, actor_user_id=author_user.id)
    for i in range(11):
        update_announcement(
            a.id, actor_user_id=author_user.id,
            title=f"A v{i + 2}", body_markdown="x",
        )
    # 12 revisions appended (1 from publish + 11 updates), capped at 10.
    assert db.session.query(AnnouncementRevision).filter_by(announcement_id=a.id).count() <= 10
