"""
Notification module Enums.

Defines type and channel enumerations for notifications.
"""

import enum


class NotificationType(str, enum.Enum):
    FEE_DUE = "FEE_DUE"
    FEE_OVERDUE = "FEE_OVERDUE"
    PAYMENT_RECEIVED = "PAYMENT_RECEIVED"
    PAYMENT_FAILED = "PAYMENT_FAILED"


class NotificationChannel(str, enum.Enum):
    IN_APP = "IN_APP"
    EMAIL = "EMAIL"
    SMS = "SMS"
