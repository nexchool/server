"""
Notification module Enums.

Defines type and channel enumerations for notifications.
"""

import enum


class NotificationType(str, enum.Enum):
    """All notification types used by templates, dispatcher, and APIs."""

    # Finance
    FEE_DUE = "FEE_DUE"
    FEE_OVERDUE = "FEE_OVERDUE"
    PAYMENT_RECEIVED = "PAYMENT_RECEIVED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    # Auth / onboarding
    EMAIL_VERIFICATION = "EMAIL_VERIFICATION"
    PASSWORD_RESET = "PASSWORD_RESET"
    WELCOME = "WELCOME"
    # Student / platform admin
    STUDENT_CREDENTIALS = "STUDENT_CREDENTIALS"
    ADMIN_CREDENTIALS = "ADMIN_CREDENTIALS"
    ADMIN_PASSWORD_RESET = "ADMIN_PASSWORD_RESET"
    # Bulk / school announcements (templates optional per tenant)
    ANNOUNCEMENT = "ANNOUNCEMENT"
    # Teacher leave management
    TEACHER_LEAVE_REQUEST = "TEACHER_LEAVE_REQUEST"
    TEACHER_LEAVE_APPROVED = "TEACHER_LEAVE_APPROVED"
    TEACHER_LEAVE_REJECTED = "TEACHER_LEAVE_REJECTED"
    TEACHER_UNAVAILABILITY_ADDED = "TEACHER_UNAVAILABILITY_ADDED"


class NotificationChannel(str, enum.Enum):
    IN_APP = "IN_APP"
    EMAIL = "EMAIL"
    SMS = "SMS"
    PUSH = "PUSH"


class NotificationRecipientStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    READ = "read"
