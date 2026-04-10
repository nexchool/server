"""
Email notification strategy.

Sends notification via email using templates from notification_templates.
Uses Celery for async sending when available (controlled by async_support).
"""

import logging
from typing import Any, Dict, Optional

from .base import NotificationStrategy
from backend.modules.notifications.enums import NotificationType
from backend.modules.notifications.template_service import (
    get_and_render_notification_template,
    TemplateNotFoundError,
)

logger = logging.getLogger(__name__)


class EmailStrategy(NotificationStrategy):
    """Sends notification via email using templates (async via Celery when enabled)."""

    def send(
        self,
        user_id: str,
        tenant_id: str,
        notification_type: str,
        title: str,
        body: Optional[str] = None,
        extra_data: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> bool:
        async_support: Optional[bool] = kwargs.get("async_support")

        try:
            from backend.modules.auth.models import User

            prefetch_email = (extra_data or {}).get("_prefetch_user_email")
            prefetch_name = (extra_data or {}).get("_prefetch_user_name")

            if prefetch_email:
                email = prefetch_email
                display_name = prefetch_name or prefetch_email
            else:
                user = User.query.get(user_id)
                if not user or not user.email:
                    logger.warning("EmailStrategy: No user or email for user_id=%s", user_id)
                    return False
                email = user.email
                display_name = user.name or user.email

            context = dict(extra_data or {})
            context.pop("_prefetch_user_email", None)
            context.pop("_prefetch_user_name", None)
            context.pop("_dispatch_channels", None)
            context.pop("_async_support", None)
            context.setdefault("user_email", email)
            context.setdefault("user_name", display_name)
            context.setdefault("title", title)
            context.setdefault("body", body)

            try:
                subject, body_html = get_and_render_notification_template(
                    tenant_id=tenant_id,
                    notification_type=notification_type,
                    channel="EMAIL",
                    context=context,
                )
            except TemplateNotFoundError:
                if notification_type == NotificationType.ANNOUNCEMENT.value and title:
                    subject = title
                    body_html = body or f"<p>{title}</p>"
                else:
                    logger.warning(
                        "EmailStrategy: no template for type=%s", notification_type
                    )
                    return False

            if async_support is not False:
                try:
                    from backend.celery_app import get_celery

                    celery_app = get_celery()
                    if celery_app:
                        celery_app.send_task(
                            "send_email_task",
                            args=[email, subject, body_html or ""],
                            kwargs={"is_html": True},
                        )
                        return True
                except Exception:
                    pass

            if async_support is True:
                logger.warning("EmailStrategy: Celery unavailable but async_support=True")
                return False

            from backend.core.extensions import mail
            from flask_mail import Message

            msg = Message(subject=subject, body=body_html or "", recipients=[email])
            if body_html:
                msg.html = body_html
            mail.send(msg)
            return True
        except Exception as e:
            logger.exception("EmailStrategy failed: %s", e)
            return False
