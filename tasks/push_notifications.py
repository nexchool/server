"""Async push delivery (FCM v1 + Expo)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

from celery_app import get_celery

logger = logging.getLogger(__name__)

celery_app = get_celery()


@celery_app.task(
    bind=True,
    name="send_push_task",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_kwargs={"max_retries": 3},
)
def send_push_task(
    self,
    user_id: str,
    tenant_id: str,
    notification_id: Optional[str],
    notification_type: str,
    title: str,
    body: str,
    data_json: str,
) -> dict:
    """
    Deliver push to all active device tokens for user+tenant.

    Idempotent enough for Celery retries: deactivates bad tokens; skips missing user/notification.
    """
    from core.database import db
    from modules.auth.models import User
    from modules.notifications.models import Notification
    from modules.devices.device_service import list_active_tokens_for_user
    from modules.notifications.push_delivery import deliver_to_tokens, strip_html_for_push

    user = User.query.filter_by(id=user_id, tenant_id=tenant_id).first()
    if not user:
        logger.info("send_push_task: user not found user=%s tenant=%s", user_id, tenant_id)
        return {"skipped": True, "reason": "no_user"}

    if user.login_locked_until and user.login_locked_until > datetime.utcnow():
        logger.info("send_push_task: user locked user=%s", user_id)
        return {"skipped": True, "reason": "user_locked"}

    if notification_id:
        n = Notification.query.filter_by(id=notification_id, tenant_id=tenant_id).first()
        if not n:
            logger.info(
                "send_push_task: notification gone id=%s (skip)", notification_id
            )
            return {"skipped": True, "reason": "notification_deleted"}

    try:
        data = json.loads(data_json) if data_json else {}
        if not isinstance(data, dict):
            data = {}
    except json.JSONDecodeError:
        data = {}

    tokens = list_active_tokens_for_user(tenant_id, user_id)
    if not tokens:
        logger.info(
            "send_push_task: no_tokens user_id=%s tenant_id=%s — "
            "push only after POST /api/devices/register from that user (web or mobile)",
            user_id,
            tenant_id,
        )
        return {"ok": 0, "failed": 0, "deactivated": 0, "skipped": True, "reason": "no_tokens"}

    plain_body = strip_html_for_push(body)
    counts = deliver_to_tokens(
        tokens,
        title=title[:200],
        body=plain_body,
        data=data,
    )
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    logger.info(
        "send_push_task user=%s tenant=%s ok=%s failed=%s deactivated=%s",
        user_id,
        tenant_id,
        counts.get("ok"),
        counts.get("failed"),
        counts.get("deactivated"),
    )
    return counts
