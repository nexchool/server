"""
Push notification strategy — always async via Celery.

Failures here must not break other channels; never raises.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from backend.modules.devices.device_service import sanitize_push_data

from .base import NotificationStrategy

logger = logging.getLogger(__name__)


class PushStrategy(NotificationStrategy):
    """Enqueue send_push_task; returns True if queued or gracefully skipped."""

    def send(
        self,
        user_id: str,
        tenant_id: str,
        notification_type: str,
        title: str,
        body: Optional[str] = None,
        extra_data: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> bool:
        try:
            parent_notification_id = kwargs.get("parent_notification_id")
            extra = dict(extra_data or {})
            notification_id = parent_notification_id or extra.get("_push_notification_id")

            base_data = {
                "type": str(notification_type)[:64],
                "notification_id": str(notification_id or "")[:64],
                "entity_id": str(extra.get("entity_id") or "")[:128],
                "screen": str(extra.get("screen") or "notifications")[:64],
            }
            for k, v in extra.items():
                if k in (
                    "_push_notification_id",
                    "_prefetch_user_email",
                    "_prefetch_user_name",
                    "_dispatch_channels",
                    "_async_support",
                ):
                    continue
                if isinstance(k, str) and not k.startswith("_") and k not in base_data:
                    if len(base_data) >= 20:
                        break
                    base_data[k] = v

            data = sanitize_push_data(base_data)
            payload = json.dumps(data)

            from backend.celery_app import get_celery

            celery_app = get_celery()
            if not celery_app:
                logger.warning("PushStrategy: Celery not initialized; push skipped for user=%s", user_id)
                return True

            celery_app.send_task(
                "send_push_task",
                args=[
                    user_id,
                    tenant_id,
                    notification_id,
                    notification_type,
                    title,
                    body or "",
                    payload,
                ],
            )
            return True
        except Exception as e:
            logger.exception("PushStrategy: enqueue failed (non-fatal): %s", e)
            return True
