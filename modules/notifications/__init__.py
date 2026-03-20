"""
Notifications module.

Strategy-based notification dispatching (IN_APP, EMAIL, SMS).
API routes for listing and marking notifications read.
"""

from .services import NotificationDispatcher, InAppStrategy, EmailStrategy, SmsStrategy
from .routes import notifications_bp

__all__ = [
    "notifications_bp",
    "NotificationDispatcher",
    "InAppStrategy",
    "EmailStrategy",
    "SmsStrategy",
]
