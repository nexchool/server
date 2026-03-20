"""
Base notification strategy (abstract interface).
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class NotificationStrategy(ABC):
    """
    Abstract base for notification delivery strategies.
    """

    @abstractmethod
    def send(
        self,
        user_id: str,
        tenant_id: str,
        notification_type: str,
        title: str,
        body: Optional[str] = None,
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Deliver the notification.

        Returns:
            True if delivery succeeded (or was queued), False otherwise.
        """
        pass
