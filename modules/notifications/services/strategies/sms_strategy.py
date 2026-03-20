"""
SMS notification strategy (stub only).

Do NOT implement SMS provider. Stub returns False.
"""

from typing import Any, Dict, Optional

from .base import NotificationStrategy


class SmsStrategy(NotificationStrategy):
    """
    SMS delivery stub. Does not implement actual SMS provider.
    Returns False - caller can handle as "not delivered".
    """

    def send(
        self,
        user_id: str,
        tenant_id: str,
        notification_type: str,
        title: str,
        body: Optional[str] = None,
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        # Stub: no SMS implementation
        return False
