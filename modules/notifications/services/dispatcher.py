"""
Notification Dispatcher (Strategy Pattern).

Dispatches notifications to IN_APP, EMAIL, SMS based on channel.
"""

from typing import Any, Dict, List, Optional

from backend.modules.notifications.enums import NotificationChannel, NotificationType

from .strategies import InAppStrategy, EmailStrategy, SmsStrategy


class NotificationDispatcher:
    """
    Dispatches notifications to the appropriate strategy per channel.
    """

    def __init__(self):
        self._strategies = {
            NotificationChannel.IN_APP.value: InAppStrategy(),
            NotificationChannel.EMAIL.value: EmailStrategy(),
            NotificationChannel.SMS.value: SmsStrategy(),
        }

    def dispatch(
        self,
        user_id: str,
        tenant_id: str,
        notification_type: str,
        channels: List[str],
        title: str,
        body: Optional[str] = None,
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, bool]:
        """
        Dispatch notification to specified channels.

        Args:
            user_id: Target user ID.
            tenant_id: Tenant ID.
            notification_type: One of NotificationType values.
            channels: List of channel names (IN_APP, EMAIL, SMS).
            title: Notification title.
            body: Optional body text.
            extra_data: Optional JSON-serializable data.

        Returns:
            Dict mapping channel -> success (True/False).
        """
        results = {}
        for ch in channels:
            strategy = self._strategies.get(ch)
            if strategy:
                results[ch] = strategy.send(
                    user_id=user_id,
                    tenant_id=tenant_id,
                    notification_type=notification_type,
                    title=title,
                    body=body,
                    extra_data=extra_data,
                )
            else:
                results[ch] = False
        return results

    def dispatch_single(
        self,
        user_id: str,
        tenant_id: str,
        notification_type: str,
        channel: str,
        title: str,
        body: Optional[str] = None,
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Dispatch to a single channel. Returns success."""
        results = self.dispatch(
            user_id=user_id,
            tenant_id=tenant_id,
            notification_type=notification_type,
            channels=[channel],
            title=title,
            body=body,
            extra_data=extra_data,
        )
        return results.get(channel, False)
