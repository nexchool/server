"""
Notification Dispatcher (Strategy Pattern).

Dispatches notifications to IN_APP, EMAIL, SMS based on channel.
"""

from typing import Any, Dict, List, Optional

from backend.modules.notifications.enums import NotificationChannel

from .strategies import InAppStrategy, EmailStrategy, PushStrategy, SmsStrategy


class NotificationDispatcher:
    """
    Dispatches notifications to the appropriate strategy per channel.
    """

    def __init__(self):
        self._strategies = {
            NotificationChannel.IN_APP.value: InAppStrategy(),
            NotificationChannel.EMAIL.value: EmailStrategy(),
            NotificationChannel.SMS.value: SmsStrategy(),
            NotificationChannel.PUSH.value: PushStrategy(),
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
        *,
        async_support: Optional[bool] = None,
        parent_notification_id: Optional[str] = None,
    ) -> Dict[str, bool]:
        """
        Dispatch notification to specified channels.

        Args:
            user_id: Target user ID.
            tenant_id: Tenant ID.
            notification_type: Notification type string (see NotificationType enum).
            channels: List of channel names (IN_APP, EMAIL, SMS).
            title: Notification title.
            body: Optional body text.
            extra_data: Optional JSON-serializable data (keys starting with '_' are not
                passed to template context for strategies; some are used internally).
            async_support: None = preserve existing email behavior (prefer Celery when
                available). False = force synchronous email. True = prefer Celery queue.
            parent_notification_id: When set, IN_APP strategy does not insert a duplicate
                notification row (bulk inbox uses notification_recipients + parent row).

        Returns:
            Dict mapping channel -> success (True/False).
        """
        results = {}
        strategy_extra = dict(extra_data) if extra_data else {}
        push_ch = NotificationChannel.PUSH.value
        ordered = [c for c in channels if c != push_ch] + [c for c in channels if c == push_ch]
        for ch in ordered:
            strategy = self._strategies.get(ch)
            if strategy:
                try:
                    results[ch] = strategy.send(
                        user_id=user_id,
                        tenant_id=tenant_id,
                        notification_type=notification_type,
                        title=title,
                        body=body,
                        extra_data=strategy_extra,
                        async_support=async_support,
                        parent_notification_id=parent_notification_id,
                    )
                except Exception:
                    # Never let a strategy exception break other channels
                    results[ch] = False
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
        *,
        async_support: Optional[bool] = None,
        parent_notification_id: Optional[str] = None,
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
            async_support=async_support,
            parent_notification_id=parent_notification_id,
        )
        return results.get(channel, False)
