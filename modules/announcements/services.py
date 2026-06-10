"""Announcement business logic — CRUD, audience resolution, revision append.

Celery fan-out + recall fan-out are routed through `_enqueue_fan_out` /
`_enqueue_recall_fan_out` so tests can monkeypatch them without real workers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

from sqlalchemy import func

from core.database import db
from core.tenant import get_tenant_id
from modules.announcements.models import (
    Announcement,
    AnnouncementRevision,
    AUDIENCE_SCOPES,
    KNOWN_AUDIENCE_ROLES,
)


REVISION_CAP = 10


class ValidationError(Exception):
    """400 — invalid request data."""


class StateError(Exception):
    """409 — illegal state transition."""


class AuthorizationError(Exception):
    """403 — actor not allowed."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_draft(
    *,
    title: str,
    body_markdown: str,
    audience_json: Dict[str, Any],
    actor_user_id: str,
) -> Announcement:
    tenant_id = get_tenant_id()
    if not tenant_id:
        raise AuthorizationError("Tenant context required")
    _validate_title(title)
    _validate_body(body_markdown)
    _validate_audience(audience_json)

    a = Announcement(
        tenant_id=tenant_id,
        title=title.strip(),
        body_markdown=body_markdown,
        audience_json=audience_json,
        status="draft",
        author_user_id=actor_user_id,
        revision_count=1,
    )
    db.session.add(a)
    db.session.commit()
    return a


def update_announcement(
    announcement_id: str,
    *,
    actor_user_id: str,
    title: Optional[str] = None,
    body_markdown: Optional[str] = None,
    audience_json: Optional[Dict[str, Any]] = None,
    edit_note: Optional[str] = None,
) -> Announcement:
    a = _get_or_404(announcement_id)
    if a.status == "recalled":
        raise StateError("Cannot edit a recalled announcement")

    if title is not None:
        _validate_title(title)
    if body_markdown is not None:
        _validate_body(body_markdown)
    if audience_json is not None:
        _validate_audience(audience_json)

    new_title = title if title is not None else a.title
    new_body = body_markdown if body_markdown is not None else a.body_markdown
    new_audience = audience_json if audience_json is not None else a.audience_json

    if a.status == "published":
        a.title = new_title.strip() if isinstance(new_title, str) else new_title
        a.body_markdown = new_body
        a.audience_json = new_audience
        _append_revision(a, editor_user_id=actor_user_id, edit_note=edit_note)
    else:
        # draft or scheduled — overwrite in place, no revision row
        a.title = new_title.strip() if isinstance(new_title, str) else new_title
        a.body_markdown = new_body
        a.audience_json = new_audience

    db.session.commit()
    return a


def publish(announcement_id: str, *, actor_user_id: str) -> Announcement:
    a = _get_or_404(announcement_id)
    if a.status not in ("draft", "scheduled"):
        raise StateError(f"Cannot publish from status {a.status}")

    a.status = "published"
    a.published_at = datetime.now(timezone.utc)
    a.scheduled_at = None
    db.session.add(AnnouncementRevision(
        tenant_id=a.tenant_id,
        announcement_id=a.id,
        revision_number=1,
        title=a.title,
        body_markdown=a.body_markdown,
        edited_by_user_id=actor_user_id,
    ))
    a.revision_count = 1
    db.session.commit()

    _enqueue_fan_out(a.id)
    return a


def schedule(announcement_id: str, *, actor_user_id: str, scheduled_at: str) -> Announcement:
    a = _get_or_404(announcement_id)
    if a.status != "draft":
        raise StateError(f"Cannot schedule from status {a.status}")
    try:
        when = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("scheduled_at must be ISO-8601")
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    if when <= datetime.now(timezone.utc):
        raise ValidationError("scheduled_at must be in the future")

    a.status = "scheduled"
    a.scheduled_at = when
    db.session.commit()
    return a


def unschedule(announcement_id: str, *, actor_user_id: str) -> Announcement:
    a = _get_or_404(announcement_id)
    if a.status != "scheduled":
        raise StateError(f"Cannot unschedule from status {a.status}")
    a.status = "draft"
    a.scheduled_at = None
    db.session.commit()
    return a


def recall(announcement_id: str, *, actor_user_id: str, reason: str) -> Announcement:
    a = _get_or_404(announcement_id)
    if a.status != "published":
        raise StateError(f"Can only recall published announcements (current: {a.status})")
    a.status = "recalled"
    a.recalled_at = datetime.now(timezone.utc)
    a.recalled_reason = (reason or "").strip() or None
    db.session.commit()

    _enqueue_recall_fan_out(a.id, reason=a.recalled_reason or "")
    return a


# ---------------------------------------------------------------------------
# Audience resolution
# ---------------------------------------------------------------------------

def _resolve_audience(tenant_id: str, audience_json: Dict[str, Any]) -> Set[str]:
    """Resolve audience_json into a deduped set of user_ids in this tenant."""
    _validate_audience(audience_json)
    scope = audience_json["scope"]

    from modules.auth.models import User
    if scope == "all":
        rows = db.session.query(User.id).filter(
            User.tenant_id == tenant_id,
        ).all()
        return {r[0] for r in rows}

    if scope == "roles":
        role_names = [r for r in audience_json.get("roles", []) if r in KNOWN_AUDIENCE_ROLES]
        if not role_names:
            return set()
        from modules.rbac.models import UserRole, Role
        from sqlalchemy import func as sfunc
        normalized = [n.lower() for n in role_names]
        rows = (
            db.session.query(User.id)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .filter(
                User.tenant_id == tenant_id,
                sfunc.lower(Role.name).in_(normalized),
            )
            .all()
        )
        return {r[0] for r in rows}

    if scope == "classes":
        class_ids = audience_json.get("class_ids", []) or []
        if not class_ids:
            return set()
        from modules.students.models import Student
        from modules.classes.models import Class
        student_user_ids = {
            r[0] for r in db.session.query(Student.user_id).filter(
                Student.tenant_id == tenant_id,
                Student.class_id.in_(class_ids),
                Student.user_id.isnot(None),
            ).all()
        }
        teacher_user_ids = {
            r[0] for r in db.session.query(Class.teacher_id).filter(
                Class.tenant_id == tenant_id,
                Class.id.in_(class_ids),
                Class.teacher_id.isnot(None),
            ).all()
        }
        return student_user_ids | teacher_user_ids

    if scope == "students":
        student_ids = audience_json.get("student_ids", []) or []
        if not student_ids:
            return set()
        from modules.students.models import Student
        rows = db.session.query(Student.user_id).filter(
            Student.tenant_id == tenant_id,
            Student.id.in_(student_ids),
            Student.user_id.isnot(None),
        ).all()
        return {r[0] for r in rows}

    raise ValidationError(f"Unknown audience scope: {scope}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_or_404(announcement_id: str) -> Announcement:
    tenant_id = get_tenant_id()
    a = db.session.query(Announcement).filter(
        Announcement.id == announcement_id,
        Announcement.tenant_id == tenant_id,
    ).first()
    if not a:
        raise ValidationError("Announcement not found")
    return a


def _validate_title(title: Optional[str]) -> None:
    if not title or not title.strip():
        raise ValidationError("title is required")
    if len(title) > 255:
        raise ValidationError("title too long (max 255)")


def _validate_body(body: Optional[str]) -> None:
    if body is None or body.strip() == "":
        raise ValidationError("body_markdown is required")


def _validate_audience(audience: Optional[Dict[str, Any]]) -> None:
    if not isinstance(audience, dict):
        raise ValidationError("audience_json must be an object")
    scope = audience.get("scope")
    if scope not in AUDIENCE_SCOPES:
        raise ValidationError(f"audience scope must be one of {AUDIENCE_SCOPES}")
    if scope == "roles":
        roles = audience.get("roles") or []
        if not isinstance(roles, list) or not roles:
            raise ValidationError("audience roles[] required for scope=roles")
    if scope == "classes":
        cids = audience.get("class_ids") or []
        if not isinstance(cids, list) or not cids:
            raise ValidationError("audience class_ids[] required for scope=classes")
    if scope == "students":
        sids = audience.get("student_ids") or []
        if not isinstance(sids, list) or not sids:
            raise ValidationError("audience student_ids[] required for scope=students")


def _append_revision(announcement: Announcement, *, editor_user_id: str, edit_note: Optional[str]) -> None:
    next_num = (
        db.session.query(func.max(AnnouncementRevision.revision_number))
        .filter(AnnouncementRevision.announcement_id == announcement.id)
        .scalar() or 0
    ) + 1

    db.session.add(AnnouncementRevision(
        tenant_id=announcement.tenant_id,
        announcement_id=announcement.id,
        revision_number=next_num,
        title=announcement.title,
        body_markdown=announcement.body_markdown,
        edited_by_user_id=editor_user_id,
        edit_note=edit_note,
    ))
    announcement.revision_count = next_num

    if next_num > REVISION_CAP:
        prune_threshold = next_num - REVISION_CAP
        deleted = db.session.query(AnnouncementRevision).filter(
            AnnouncementRevision.announcement_id == announcement.id,
            AnnouncementRevision.revision_number <= prune_threshold,
        ).delete(synchronize_session=False)
        from flask import current_app
        current_app.logger.warning(
            "Pruned %d old revisions for announcement %s (cap=%d)",
            deleted, announcement.id, REVISION_CAP,
        )


# ---------------------------------------------------------------------------
# Celery indirection (Task 5 wires real tasks)
# ---------------------------------------------------------------------------

def _enqueue_fan_out(announcement_id: str) -> None:
    try:
        from modules.announcements.tasks import announcement_fan_out
        announcement_fan_out.delay(announcement_id)
    except Exception as exc:
        from flask import current_app
        current_app.logger.warning("Failed to enqueue fan_out for %s: %s", announcement_id, exc)


def _enqueue_recall_fan_out(announcement_id: str, reason: str) -> None:
    try:
        from modules.announcements.tasks import announcement_recall_fan_out
        announcement_recall_fan_out.delay(announcement_id, reason)
    except Exception as exc:
        from flask import current_app
        current_app.logger.warning("Failed to enqueue recall_fan_out for %s: %s", announcement_id, exc)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def list_for_admin(*, status: Optional[str] = None, search: Optional[str] = None) -> list:
    tenant_id = get_tenant_id()
    q = db.session.query(Announcement).filter(Announcement.tenant_id == tenant_id)
    if status:
        q = q.filter(Announcement.status == status)
    if search:
        like = f"%{search.lower()}%"
        q = q.filter(func.lower(Announcement.title).like(like))
    return q.order_by(Announcement.created_at.desc()).all()


def inbox_for_user(user_id: str) -> list:
    """Return published/recalled announcements where this user is in the resolved audience,
    read through the notification_recipients fan-out."""
    tenant_id = get_tenant_id()
    from modules.notifications.models import Notification, NotificationRecipient
    rows = (
        db.session.query(Announcement)
        .join(Notification, Notification.extra_data["announcement_id"].as_string() == Announcement.id)
        .join(NotificationRecipient, NotificationRecipient.notification_id == Notification.id)
        .filter(
            Announcement.tenant_id == tenant_id,
            NotificationRecipient.user_id == user_id,
            Notification.type.in_(("announcement.published", "announcement.recalled")),
        )
        .order_by(Announcement.published_at.desc())
        .all()
    )
    seen = set()
    out = []
    for a in rows:
        if a.id in seen:
            continue
        seen.add(a.id)
        out.append(a)
    return out


def get_for_user(announcement_id: str, user) -> Announcement:
    a = _get_or_404(announcement_id)
    from modules.rbac.services import has_permission
    if has_permission(user.id, "announcement.read.all"):
        return a
    if a.status in ("draft", "scheduled"):
        if a.author_user_id == user.id:
            return a
        raise AuthorizationError("Not allowed")
    # Published or recalled — check recipient membership via notification_recipients.
    from modules.notifications.models import Notification, NotificationRecipient
    is_recipient = (
        db.session.query(NotificationRecipient.id)
        .join(Notification, NotificationRecipient.notification_id == Notification.id)
        .filter(
            NotificationRecipient.user_id == user.id,
            Notification.extra_data["announcement_id"].as_string() == a.id,
        )
        .first()
        is not None
    )
    if not is_recipient:
        raise AuthorizationError("Not allowed")
    return a


def list_recipients(announcement_id: str) -> list:
    """NotificationRecipient rows joined to User for the read-receipt roster."""
    tenant_id = get_tenant_id()
    a = _get_or_404(announcement_id)
    from modules.notifications.models import Notification, NotificationRecipient
    from modules.auth.models import User
    rows = (
        db.session.query(NotificationRecipient, User)
        .join(User, User.id == NotificationRecipient.user_id)
        .join(Notification, Notification.id == NotificationRecipient.notification_id)
        .filter(
            Notification.type == "announcement.published",
            Notification.extra_data["announcement_id"].as_string() == a.id,
            Notification.tenant_id == tenant_id,
        )
        .all()
    )
    return [
        {
            "user_id": user.id,
            "name": user.name,
            "read_at": recipient.read_at.isoformat() if recipient.read_at else None,
            "status": recipient.status,
        }
        for recipient, user in rows
    ]


def list_revisions(announcement_id: str) -> list:
    a = _get_or_404(announcement_id)
    return [r.to_dict() for r in a.revisions]


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------

def create_attachment(
    *,
    actor_user_id: str,
    file_stream,
    filename: str,
    content_type: str,
    size_bytes: int,
    announcement_id: Optional[str] = None,
):
    from shared.s3_utils import upload_file, sanitize_folder
    from modules.announcements.models import AnnouncementAttachment

    tenant_id = get_tenant_id()
    if not tenant_id:
        raise AuthorizationError("Tenant context required")

    if announcement_id:
        a = _get_or_404(announcement_id)
        target_announcement_id = a.id
    else:
        target_announcement_id = None

    folder = sanitize_folder(f"tenants/{tenant_id}/announcements")

    # upload_file returns (presigned_url, object_key) — we persist object_key only.
    _url, stored_key = upload_file(file_stream, folder, filename, content_type)

    att = AnnouncementAttachment(
        tenant_id=tenant_id,
        announcement_id=target_announcement_id,
        s3_key=stored_key,
        original_filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
        uploaded_by_user_id=actor_user_id,
    )
    db.session.add(att)
    db.session.commit()
    return att


def delete_attachment(attachment_id: str, *, actor_user_id: str) -> None:
    from shared.s3_utils import delete_file
    from modules.announcements.models import AnnouncementAttachment

    tenant_id = get_tenant_id()
    att = db.session.query(AnnouncementAttachment).filter(
        AnnouncementAttachment.id == attachment_id,
        AnnouncementAttachment.tenant_id == tenant_id,
    ).first()
    if not att:
        raise ValidationError("Attachment not found")
    if att.uploaded_by_user_id != actor_user_id:
        from modules.rbac.services import has_permission
        if not has_permission(actor_user_id, "announcement.update"):
            raise AuthorizationError("Not allowed")
    try:
        delete_file(att.s3_key)
    except Exception as exc:
        from flask import current_app
        current_app.logger.warning("Failed to delete S3 object %s: %s", att.s3_key, exc)
    db.session.delete(att)
    db.session.commit()


def attachment_download_url(attachment_id: str, user) -> str:
    """Return a short-lived presigned URL for the attachment."""
    from modules.announcements.models import AnnouncementAttachment
    from shared.s3_utils import _get_s3_client, _bucket_name, key_for_download_url

    tenant_id = get_tenant_id()
    att = db.session.query(AnnouncementAttachment).filter(
        AnnouncementAttachment.id == attachment_id,
        AnnouncementAttachment.tenant_id == tenant_id,
    ).first()
    if not att:
        raise ValidationError("Attachment not found")

    if att.announcement_id:
        get_for_user(att.announcement_id, user)  # raises if not authorized
    else:
        # Orphan/draft attachment — must be either the uploader or an admin
        # with the update permission. Otherwise any tenant user could fetch
        # un-attached uploads by guessing IDs.
        if att.uploaded_by_user_id != user.id:
            from modules.rbac.services import has_permission
            if not has_permission(user.id, "announcement.update"):
                raise AuthorizationError("Not allowed")

    s3 = _get_s3_client()
    bucket = _bucket_name()
    key = key_for_download_url(att.s3_key) or att.s3_key
    url = s3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": bucket,
            "Key": key,
            "ResponseContentDisposition": f'attachment; filename="{att.original_filename or "file"}"',
        },
        ExpiresIn=600,
    )
    return url


def list_templates() -> list:
    from modules.announcements.templates_data import SYSTEM_TEMPLATES
    return list(SYSTEM_TEMPLATES)
