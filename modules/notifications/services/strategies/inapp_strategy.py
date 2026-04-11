"""
In-App notification strategy.

Creates a Notification record in the database for in-app display.
Bulk sends use a parent Notification + notification_recipients (no duplicate row).
"""

from typing import Any, Dict, Optional

from core.database import db
from modules.notifications.models import Notification
from modules.notifications.enums import NotificationChannel

from .base import NotificationStrategy


class InAppStrategy(NotificationStrategy):
    """Creates Notification record with channel=IN_APP, or defers to parent bulk row."""

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
        parent_notification_id = kwargs.get("parent_notification_id")
        if parent_notification_id:
            # Inbox lists via NotificationRecipient join parent Notification
            return True

        try:
            clean_extra = dict(extra_data or {})
            clean_extra.pop("_prefetch_user_email", None)
            clean_extra.pop("_prefetch_user_name", None)
            clean_extra.pop("_dispatch_channels", None)
            clean_extra.pop("_async_support", None)

            notification = Notification(
                tenant_id=tenant_id,
                user_id=user_id,
                type=notification_type,
                channel=NotificationChannel.IN_APP.value,
                title=title,
                body=body,
                extra_data=clean_extra if clean_extra else None,
            )
            db.session.add(notification)
            db.session.commit()
            if extra_data is not None:
                extra_data["_push_notification_id"] = notification.id
            return True
        except Exception:
            db.session.rollback()
            return False
