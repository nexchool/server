"""
Email notification strategy.

Sends notification via email using templates from notification_templates.
Uses Celery for async sending when available.
"""

import logging
from typing import Any, Dict, Optional

from .base import NotificationStrategy
from backend.modules.notifications.template_service import (
    get_and_render_notification_template,
    TemplateNotFoundError,
)

logger = logging.getLogger(__name__)


class EmailStrategy(NotificationStrategy):
    """Sends notification via email using templates (async via Celery when available)."""

    def send(
        self,
        user_id: str,
        tenant_id: str,
        notification_type: str,
        title: str,
        body: Optional[str] = None,
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        try:
            from backend.modules.auth.models import User
            user = User.query.get(user_id)
            if not user or not user.email:
                logger.warning("EmailStrategy: No user or email for user_id=%s", user_id)
                return False

            # Build context: extra_data + standard vars (user_email, user_name, etc.)
            context = dict(extra_data or {})
            context.setdefault("user_email", user.email)
            context.setdefault("user_name", user.name or user.email)
            context.setdefault("title", title)
            context.setdefault("body", body)

            # Look up and render template (no hardcoded body)
            subject, body_html = get_and_render_notification_template(
                tenant_id=tenant_id,
                notification_type=notification_type,
                channel="EMAIL",
                context=context,
            )

            # Prefer async via Celery
            try:
                from backend.celery_app import get_celery
                celery_app = get_celery()
                if celery_app:
                    celery_app.send_task(
                        "send_email_task",
                        args=[user.email, subject, body_html or ""],
                        kwargs={"is_html": True},
                    )
                    return True
            except Exception:
                pass

            # Fallback: synchronous Flask-Mail
            from flask import current_app
            mail = getattr(current_app, "mail", None)
            if mail:
                from flask_mail import Message
                msg = Message(subject=subject, body=body_html or "", recipients=[user.email])
                if body_html:
                    msg.html = body_html
                mail.send(msg)
                return True

            logger.info(
                "EmailStrategy (no mail/Celery): would send to %s: %s",
                user.email, subject,
            )
            return True
        except TemplateNotFoundError as e:
            logger.warning("EmailStrategy: %s", e)
            return False
        except Exception as e:
            logger.exception("EmailStrategy failed: %s", e)
            return False
