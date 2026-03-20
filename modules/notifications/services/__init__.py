"""
Notification services.

Dispatcher and delivery strategies.
"""

from .dispatcher import NotificationDispatcher
from .strategies import InAppStrategy, EmailStrategy, SmsStrategy

notification_dispatcher = NotificationDispatcher()

__all__ = [
    "NotificationDispatcher",
    "notification_dispatcher",
    "InAppStrategy",
    "EmailStrategy",
    "SmsStrategy",
]
