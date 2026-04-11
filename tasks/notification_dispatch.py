"""Celery tasks: bulk notification dispatch (chunked)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from celery_app import get_celery

logger = logging.getLogger(__name__)

celery_app = get_celery()

CHUNK_SIZE = 500


def _chunks(items: Sequence[str], size: int) -> List[List[str]]:
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


def _public_extra(extra: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not extra:
        return {}
    return {k: v for k, v in extra.items() if not str(k).startswith("_")}


@celery_app.task(
    bind=True,
    name="dispatch_notification_task",
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3, "countdown": 30},
)
def dispatch_notification_task(self, notification_id: str) -> Dict[str, Any]:
    """
    Load pending recipients for a notification and enqueue process_notification_chunk
    tasks (500 users per chunk).
    """
    from core.database import db
    from modules.notifications.models import NotificationRecipient
    from modules.notifications.enums import NotificationRecipientStatus

    pending_ids = [
        row[0]
        for row in db.session.query(NotificationRecipient.user_id)
        .filter(
            NotificationRecipient.notification_id == notification_id,
            NotificationRecipient.status == NotificationRecipientStatus.PENDING.value,
        )
        .all()
    ]

    if not pending_ids:
        return {"notification_id": notification_id, "chunks_scheduled": 0}

    chunks = _chunks(pending_ids, CHUNK_SIZE)
    for chunk in chunks:
        process_notification_chunk.delay(notification_id, chunk)

    return {
        "notification_id": notification_id,
        "chunks_scheduled": len(chunks),
        "total_recipients": len(pending_ids),
    }


@celery_app.task(
    bind=True,
    name="process_notification_chunk",
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3, "countdown": 20},
)
def process_notification_chunk(self, notification_id: str, user_ids: List[str]) -> Dict[str, Any]:
    """
    For each user in the chunk, run NotificationDispatcher and update recipient status.
    """
    from core.database import db
    from modules.notifications.models import Notification, NotificationRecipient
    from modules.notifications.enums import NotificationRecipientStatus
    from modules.notifications.services import notification_dispatcher
    from modules.notifications.notification_targeting_service import get_users_by_ids

    n = Notification.query.get(notification_id)
    if not n:
        logger.error("process_notification_chunk: notification not found %s", notification_id)
        return {"error": "notification_not_found", "notification_id": notification_id}

    raw_extra = n.extra_data or {}
    channels = raw_extra.get("_dispatch_channels") or ["IN_APP"]
    async_support = raw_extra.get("_async_support")
    if async_support is not None and not isinstance(async_support, bool):
        async_support = None

    public_ctx = _public_extra(raw_extra)
    tenant_id = n.tenant_id

    users = get_users_by_ids(user_ids, tenant_id)
    user_map = {u.id: u for u in users}

    sent_ok = 0
    sent_fail = 0

    for uid in user_ids:
        rec = (
            NotificationRecipient.query.filter_by(
                notification_id=notification_id,
                user_id=uid,
            ).first()
        )
        if not rec:
            continue

        u = user_map.get(uid)
        if not u:
            rec.status = NotificationRecipientStatus.FAILED.value
            sent_fail += 1
            continue

        dispatch_extra = dict(public_ctx)
        dispatch_extra["_prefetch_user_email"] = u.email
        dispatch_extra["_prefetch_user_name"] = u.name or u.email

        results = notification_dispatcher.dispatch(
            user_id=uid,
            tenant_id=tenant_id,
            notification_type=n.type,
            channels=list(channels),
            title=n.title,
            body=n.body,
            extra_data=dispatch_extra,
            async_support=async_support,
            parent_notification_id=notification_id,
        )

        ok = bool(results) and any(results.values())
        if ok:
            rec.status = NotificationRecipientStatus.SENT.value
            sent_ok += 1
        else:
            rec.status = NotificationRecipientStatus.FAILED.value
            sent_fail += 1

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return {
        "notification_id": notification_id,
        "processed": len(user_ids),
        "sent": sent_ok,
        "failed": sent_fail,
    }
