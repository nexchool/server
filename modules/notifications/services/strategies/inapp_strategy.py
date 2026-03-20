"""
In-App notification strategy.

Creates a Notification record in the database for in-app display.
"""

from typing import Any, Dict, Optional

from backend.core.database import db
from backend.modules.notifications.models import Notification
from backend.modules.notifications.enums import NotificationChannel

from .base import NotificationStrategy


class InAppStrategy(NotificationStrategy):
    """Creates Notification record with channel=IN_APP."""

    def send(
        self,
        user_id: str,
        tenant_id: str,
        notification_type: str,
        title: str,
        body: Optional[str] = None,
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        try:
            notification = Notification(
                tenant_id=tenant_id,
                user_id=user_id,
                type=notification_type,
                channel=NotificationChannel.IN_APP.value,
                title=title,
                body=body,
                extra_data=extra_data,
            )
            db.session.add(notification)
            db.session.commit()
            return True
        except Exception:
            db.session.rollback()
            return False
