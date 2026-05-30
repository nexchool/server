"""Celery tasks for the announcements module."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from celery import shared_task
from flask import current_app

from core.database import db
from modules.announcements.models import Announcement, AnnouncementAttachment, AnnouncementRevision
from modules.notifications import notification_service
from modules.notifications.enums import NotificationChannel


# ---------------------------------------------------------------------------
# Fan-out on publish
# ---------------------------------------------------------------------------

@shared_task(name="announcements.fan_out")
def announcement_fan_out(announcement_id: str) -> None:
    """Resolve audience + create Notification + recipients.

    Idempotent: re-runs are guarded by the published status check.
    """
    a = db.session.query(Announcement).filter(Announcement.id == announcement_id).first()
    if not a or a.status != "published":
        current_app.logger.info("fan_out skipped for %s (not published)", announcement_id)
        return

    from modules.announcements.services import _resolve_audience
    user_ids = _resolve_audience(a.tenant_id, a.audience_json)
    if not user_ids:
        current_app.logger.info("fan_out: empty audience for %s", announcement_id)
        return

    push_body = (a.body_markdown or "")[:100]

    n = notification_service.create_notification(
        tenant_id=a.tenant_id,
        notification_type="announcement.published",
        title=a.title,
        body=push_body,
        extra_data={"announcement_id": a.id, "revision_count": a.revision_count},
        channels=[NotificationChannel.IN_APP.value, NotificationChannel.PUSH.value],
        user_id=None,
    )
    notification_service.create_recipients(n.id, list(user_ids))


@shared_task(name="announcements.recall_fan_out")
def announcement_recall_fan_out(announcement_id: str, reason: str) -> None:
    a = db.session.query(Announcement).filter(Announcement.id == announcement_id).first()
    if not a or a.status != "recalled":
        return

    from modules.announcements.services import _resolve_audience
    user_ids = _resolve_audience(a.tenant_id, a.audience_json)
    if not user_ids:
        return

    n = notification_service.create_notification(
        tenant_id=a.tenant_id,
        notification_type="announcement.recalled",
        title=f"Recalled: {a.title}",
        body=reason or "This announcement was recalled by the admin.",
        extra_data={"announcement_id": a.id, "reason": reason},
        channels=[NotificationChannel.IN_APP.value, NotificationChannel.PUSH.value],
        user_id=None,
    )
    notification_service.create_recipients(n.id, list(user_ids))


# ---------------------------------------------------------------------------
# Scheduled-send beat task
# ---------------------------------------------------------------------------

@shared_task(name="announcements.process_scheduled")
def process_scheduled_announcements() -> int:
    """Beat task — runs every minute. Promotes due scheduled announcements to published
    and enqueues fan-out. Uses SELECT FOR UPDATE SKIP LOCKED for multi-worker safety."""
    now = datetime.now(timezone.utc)
    rows = (
        db.session.query(Announcement)
        .filter(
            Announcement.status == "scheduled",
            Announcement.scheduled_at <= now,
        )
        .with_for_update(skip_locked=True)
        .limit(100)
        .all()
    )
    fired = 0
    for a in rows:
        a.status = "published"
        a.published_at = now
        a.scheduled_at = None
        # Write initial revision if none yet.
        existing = db.session.query(AnnouncementRevision).filter_by(announcement_id=a.id).count()
        if existing == 0:
            db.session.add(AnnouncementRevision(
                tenant_id=a.tenant_id,
                announcement_id=a.id,
                revision_number=1,
                title=a.title,
                body_markdown=a.body_markdown,
                edited_by_user_id=a.author_user_id,
            ))
            a.revision_count = 1
        db.session.flush()
        announcement_fan_out.delay(a.id)
        fired += 1
    db.session.commit()
    if fired:
        current_app.logger.info("process_scheduled_announcements fired %d", fired)
    return fired


# ---------------------------------------------------------------------------
# Orphan attachment sweep
# ---------------------------------------------------------------------------

@shared_task(name="announcements.sweep_orphan_attachments")
def sweep_orphan_attachments() -> int:
    """Daily beat task. Deletes AnnouncementAttachment rows where announcement_id IS NULL
    and created_at < now - 24h, plus their S3 objects."""
    from shared.s3_utils import delete_file
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    orphans = (
        db.session.query(AnnouncementAttachment)
        .filter(
            AnnouncementAttachment.announcement_id.is_(None),
            AnnouncementAttachment.created_at < cutoff,
        )
        .all()
    )
    deleted = 0
    for o in orphans:
        try:
            delete_file(o.s3_key)
        except Exception as exc:
            current_app.logger.warning("Failed to delete S3 object %s: %s", o.s3_key, exc)
        db.session.delete(o)
        deleted += 1
    db.session.commit()
    if deleted:
        current_app.logger.info("sweep_orphan_attachments deleted %d", deleted)
    return deleted
