"""Revision-numbering invariants."""

from __future__ import annotations

from core.database import db
from modules.announcements.services import create_draft, publish, update_announcement
from modules.announcements.models import AnnouncementRevision


def test_revision_numbers_monotonic(tenant_ctx, author_user, monkeypatch):
    from modules.announcements import services as svc
    monkeypatch.setattr(svc, "_enqueue_fan_out", lambda announcement_id: None)
    a = create_draft(
        title="A", body_markdown="b",
        audience_json={"scope": "all"}, actor_user_id=author_user.id,
    )
    publish(a.id, actor_user_id=author_user.id)
    for i in range(3):
        update_announcement(
            a.id, actor_user_id=author_user.id,
            title=f"A v{i + 2}", body_markdown="x",
        )
    nums = [
        r.revision_number
        for r in db.session.query(AnnouncementRevision)
        .filter_by(announcement_id=a.id)
        .order_by(AnnouncementRevision.revision_number)
        .all()
    ]
    assert nums == [1, 2, 3, 4]


def test_revision_count_matches_max_revision_number(tenant_ctx, author_user, monkeypatch):
    from modules.announcements import services as svc
    monkeypatch.setattr(svc, "_enqueue_fan_out", lambda announcement_id: None)
    a = create_draft(
        title="A", body_markdown="b",
        audience_json={"scope": "all"}, actor_user_id=author_user.id,
    )
    publish(a.id, actor_user_id=author_user.id)
    update_announcement(
        a.id, actor_user_id=author_user.id,
        title="A v2", body_markdown="x",
    )
    db.session.refresh(a)
    assert a.revision_count == 2
