"""
Email Service (DEPRECATED).

DEPRECATED: Use NotificationDispatcher from modules.notifications instead.
This module is retained for backward compatibility only.
All functions internally redirect to NotificationDispatcher.
"""

import logging
import warnings
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Template name -> notification type mapping for redirect
_TEMPLATE_TO_TYPE = {
    "email_verification.html": "EMAIL_VERIFICATION",
    "forgot_password.html": "PASSWORD_RESET",
    "register.html": "WELCOME",
    "student_creation.html": "STUDENT_CREDENTIALS",
    "school_admin_credentials.html": "ADMIN_CREDENTIALS",
}


def _deprecation_warning():
    """Emit deprecation warning."""
    warnings.warn(
        "Mailer module deprecated — use NotificationDispatcher from modules.notifications",
        DeprecationWarning,
        stacklevel=3,
    )
    logger.warning("Mailer module deprecated — use NotificationDispatcher")


def _send_via_dispatcher(
    to_email: str,
    notification_type: str,
    context: Dict,
    subject: str = "",
) -> None:
    """
    Redirect to NotificationDispatcher.
    Resolves user_id from to_email (requires tenant context).
    """
    from flask import has_request_context, g
    from modules.notifications.services import notification_dispatcher
    from modules.notifications.enums import NotificationChannel

    _deprecation_warning()

    tenant_id = None
    if has_request_context():
        tenant_id = getattr(g, "tenant_id", None)

    if not tenant_id:
        logger.warning("Mailer redirect: no tenant_id in context, cannot dispatch")
        return

    from modules.auth.models import User
    user = User.get_user_by_email(to_email, tenant_id=tenant_id)
    if not user:
        logger.warning("Mailer redirect: user not found for email=%s tenant=%s", to_email, tenant_id)
        return

    extra_data = dict(context) if context else {}
    if subject:
        extra_data.setdefault("subject", subject)

    notification_dispatcher.dispatch(
        user_id=user.id,
        tenant_id=tenant_id,
        notification_type=notification_type,
        channels=[NotificationChannel.EMAIL.value],
        title=subject or "Notification",
        body=None,
        extra_data=extra_data,
    )


def send_email(
    to_email: str,
    subject: str,
    body: str,
    is_html: bool = True,
    from_name: Optional[str] = None,
    from_email: Optional[str] = None,
) -> None:
    """
    DEPRECATED: Send a plain email.
    Use NotificationDispatcher with a generic template type.
    For raw body without template, we cannot fully redirect — logs warning and skips.
    """
    _deprecation_warning()
    logger.warning(
        "send_email(raw body) deprecated: cannot redirect to template system. "
        "Use NotificationDispatcher with appropriate template type."
    )
    # Attempt to send via Flask-Mail as last-resort fallback for any legacy callers
    try:
        from flask import current_app
        mail = getattr(current_app, "mail", None)
        if mail:
            from flask_mail import Message
            msg = Message(subject=subject, body=body or "", recipients=[to_email])
            if is_html and body:
                msg.html = body
            mail.send(msg)
    except Exception as e:
        logger.exception("send_email fallback failed: %s", e)


def send_template_email(
    to_email: str,
    template_name: str,
    context: Dict,
    subject: str = "",
    from_name: Optional[str] = None,
    from_email: Optional[str] = None,
) -> None:
    """
    DEPRECATED: Send email using a template.
    Internally redirects to NotificationDispatcher.
    """
    notification_type = _TEMPLATE_TO_TYPE.get(template_name)
    if not notification_type:
        logger.warning("Mailer: unknown template %s, cannot redirect", template_name)
        return
    _send_via_dispatcher(to_email=to_email, notification_type=notification_type, context=context, subject=subject)


