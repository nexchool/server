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
    # Subscription (platform → school administrators)
    SUBSCRIPTION_PAYMENT_DUE = "SUBSCRIPTION_PAYMENT_DUE"
    # Teacher leave management
    TEACHER_LEAVE_REQUEST = "TEACHER_LEAVE_REQUEST"
    TEACHER_LEAVE_APPROVED = "TEACHER_LEAVE_APPROVED"
    TEACHER_LEAVE_REJECTED = "TEACHER_LEAVE_REJECTED"
    TEACHER_UNAVAILABILITY_ADDED = "TEACHER_UNAVAILABILITY_ADDED"


#: Notices from Nexchool to a school about its own account, as opposed to
#: messages a school module sends its people. A school may switch its
#: `notifications` feature off — that is its business for announcements and
#: fee alerts, and none at all for the notice saying its subscription payment
#: is due. These types therefore bypass the tenant feature gate, and the email
#: strategy delivers them on their own wording when no template row exists:
#: they carry the whole message in the body, and a school being suspended
#: without ever being told is not an acceptable failure.
PLATFORM_ACCOUNT_NOTIFICATIONS = frozenset(
    {
        NotificationType.SUBSCRIPTION_PAYMENT_DUE.value,
    }
)


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
