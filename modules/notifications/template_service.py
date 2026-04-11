"""
Notification Template Service.

Lookup and render notification templates with tenant fallback logic.
Uses Jinja2 with safe environment (no dangerous constructs).
"""

from typing import Any, Dict, Optional

from jinja2 import Environment, BaseLoader, select_autoescape
from jinja2.exceptions import TemplateError

from core.database import db
from modules.notifications.models import NotificationTemplate


# Category constants (single source of truth)
NOTIFICATION_CATEGORY_AUTH = "AUTH"
NOTIFICATION_CATEGORY_STUDENT = "STUDENT"
NOTIFICATION_CATEGORY_PLATFORM = "PLATFORM"
NOTIFICATION_CATEGORY_FINANCE = "FINANCE"
NOTIFICATION_CATEGORY_SYSTEM = "SYSTEM"

NOTIFICATION_CATEGORIES = [
    NOTIFICATION_CATEGORY_AUTH,
    NOTIFICATION_CATEGORY_STUDENT,
    NOTIFICATION_CATEGORY_PLATFORM,
    NOTIFICATION_CATEGORY_FINANCE,
    NOTIFICATION_CATEGORY_SYSTEM,
]


class TemplateNotFoundError(Exception):
    """Raised when no template exists for (tenant_id, type, channel)."""
    pass


def _safe_jinja_env() -> Environment:
    """Create Jinja2 environment with safe defaults (no arbitrary code execution)."""
    return Environment(
        loader=BaseLoader(),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def get_notification_template(
    tenant_id: Optional[str],
    notification_type: str,
    channel: str,
) -> NotificationTemplate:
    """
    Get notification template with fallback logic.

    1. Try tenant-specific template (tenant_id IS NOT NULL)
    2. Else fallback to global template (tenant_id IS NULL)
    3. If none found → raise TemplateNotFoundError

    Args:
        tenant_id: Tenant ID or None for global-only lookup.
        notification_type: Notification type (e.g. FEE_OVERDUE, EMAIL_VERIFICATION).
        channel: Channel (EMAIL, SMS, IN_APP).

    Returns:
        NotificationTemplate instance.

    Raises:
        TemplateNotFoundError: No template found.
    """
    # 1. Try tenant-specific
    if tenant_id:
        tpl = NotificationTemplate.query.filter_by(
            tenant_id=tenant_id,
            type=notification_type,
            channel=channel,
        ).first()
        if tpl:
            return tpl

    # 2. Fallback to global (tenant_id IS NULL)
    tpl = NotificationTemplate.query.filter(
        NotificationTemplate.tenant_id.is_(None),
        NotificationTemplate.type == notification_type,
        NotificationTemplate.channel == channel,
    ).first()

    if tpl:
        return tpl

    raise TemplateNotFoundError(
        f"No notification template found for type={notification_type}, channel={channel}"
        + (f", tenant_id={tenant_id}" if tenant_id else " (global)")
    )


def render_notification_template(
    subject_template: str,
    body_template: str,
    context: Dict[str, Any],
) -> tuple[str, str]:
    """
    Render subject and body templates with Jinja2 (safe environment).

    Args:
        subject_template: Subject string (may contain {{ vars }}).
        body_template: Body string (may contain Jinja2 syntax).
        context: Dict of variables for template rendering.

    Returns:
        (rendered_subject, rendered_body)

    Raises:
        TemplateError: If rendering fails.
    """
    env = _safe_jinja_env()

    subj_tpl = env.from_string(subject_template)
    body_tpl = env.from_string(body_template)

    rendered_subject = subj_tpl.render(**context)
    rendered_body = body_tpl.render(**context)

    return rendered_subject, rendered_body


# Dummy context for preview and test-send
PREVIEW_CONTEXT = {
    "student_name": "John Doe",
    "user_name": "Admin User",
    "user_email": "admin@example.com",
    "amount": "₹5,000",
    "due_date": "31 March 2026",
    "school_name": "Demo School",
    "verify_url": "https://example.com/verify",
    "reset_url": "https://example.com/reset",
    "expires_in": "60",
    "admission_number": "ADM001",
    "username": "johndoe",
    "password": "••••••••",
    "admin_name": "School Admin",
    "tenant_name": "Demo School",
    "login_url": "https://demo.example.com",
    "admin_email": "admin@school.com",
    "total_amount": "₹5,000",
    "message": "This is a preview.",
}


def validate_notification_template(
    subject_template: str,
    body_template: str,
) -> tuple[bool, Optional[str]]:
    """
    Validate Jinja2 syntax of subject and body templates.

    Returns:
        (True, None) if valid.
        (False, error_message) if invalid.
    """
    env = _safe_jinja_env()
    try:
        env.from_string(subject_template or "")
        env.from_string(body_template or "")
        return True, None
    except TemplateError as e:
        return False, str(e)


def get_and_render_notification_template(
    tenant_id: Optional[str],
    notification_type: str,
    channel: str,
    context: Dict[str, Any],
) -> tuple[str, str]:
    """
    Get template, render with context, return (subject, body).

    Convenience combining get_notification_template and render_notification_template.
    """
    tpl = get_notification_template(tenant_id, notification_type, channel)
    return render_notification_template(
        tpl.subject_template,
        tpl.body_template,
        context,
    )
