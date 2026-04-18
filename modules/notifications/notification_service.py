"""
Create bulk notifications, recipients, and enqueue Celery dispatch.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from core.database import db
from modules.notifications.enums import NotificationChannel, NotificationRecipientStatus
from modules.notifications.models import Notification, NotificationRecipient


def _channel_aggregate_label(channels: Sequence[str]) -> str:
    ch = [c for c in channels if c]
    if not ch:
        return NotificationChannel.IN_APP.value
    if len(ch) == 1:
        return ch[0]
    return "MULTI"


def create_notification(
    tenant_id: str,
    notification_type: str,
    title: str,
    body: Optional[str] = None,
    extra_data: Optional[Dict[str, Any]] = None,
    channels: Optional[Sequence[str]] = None,
    user_id: Optional[str] = None,
    async_support: Optional[bool] = None,
) -> Notification:
    """
    Insert a notification row.

    For bulk sends, leave user_id None and persist channels/async flag in extra_data
    for the worker (keys _dispatch_channels, _async_support).
    """
    channels_list = list(channels) if channels else [NotificationChannel.IN_APP.value]
    extra = dict(extra_data or {})
    extra["_dispatch_channels"] = channels_list
    if async_support is not None:
        extra["_async_support"] = async_support

    n = Notification(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        user_id=user_id,
        type=notification_type,
        channel=_channel_aggregate_label(channels_list),
        title=title,
        body=body,
        extra_data=extra,
    )
    db.session.add(n)
    db.session.flush()
    return n


def create_recipients(notification_id: str, user_ids: Sequence[str]) -> int:
    """
    Bulk insert notification_recipients with status pending.

    Returns number of rows inserted (skips duplicates already present).
    """
    uid_list = list(dict.fromkeys(u for u in user_ids if u))
    if not uid_list:
        return 0

    existing_rows = NotificationRecipient.query.filter(
        NotificationRecipient.notification_id == notification_id,
        NotificationRecipient.user_id.in_(uid_list),
    ).all()
    existing = {r.user_id for r in existing_rows}

    to_add = [u for u in uid_list if u not in existing]
    if not to_add:
        return 0

    now = datetime.utcnow()
    mappings = [
        {
            "id": str(uuid.uuid4()),
            "notification_id": notification_id,
            "user_id": uid,
            "status": NotificationRecipientStatus.PENDING.value,
            "read_at": None,
            "created_at": now,
        }
        for uid in to_add
    ]
    db.session.bulk_insert_mappings(NotificationRecipient, mappings)
    return len(mappings)


def ensure_dispatch_recipients(notification: Notification) -> int:
    """
    Ensure a notification has recipient rows before Celery dispatch.

    Bulk notifications already create recipients explicitly. For legacy single-user
    notifications (`user_id` set on the notification row), we create a matching
    recipient row on demand so they can flow through the same durable worker path.
    """
    if not notification or not notification.id or not notification.user_id:
        return 0
    return create_recipients(notification.id, [notification.user_id])


def send_notification(notification_id: str) -> bool:
    """
    Enqueue Celery dispatch_notification_task.

    Returns False only if Celery is unavailable or the notification cannot be loaded.
    """
    from celery_app import get_celery

    notification = Notification.query.get(notification_id)
    if not notification:
        return False

    try:
        created = ensure_dispatch_recipients(notification)
        if created:
            db.session.commit()
    except Exception:
        db.session.rollback()
        return False
    celery_app = get_celery()
    if not celery_app:
        return False
    celery_app.send_task("dispatch_notification_task", args=[notification_id])
    return True
