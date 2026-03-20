"""
Seed default notification templates.

Inserts current mailer HTML templates and finance notification types into
notification_templates table as GLOBAL templates (tenant_id = NULL).
Does NOT delete filesystem templates.

Run: flask shell
    >>> from backend.scripts.seed_notification_templates import seed_default_notification_templates
    >>> seed_default_notification_templates()
"""

import os
import uuid

from backend.core.database import db
from backend.modules.notifications.models import NotificationTemplate
from backend.modules.notifications.template_service import (
    NOTIFICATION_CATEGORY_AUTH,
    NOTIFICATION_CATEGORY_STUDENT,
    NOTIFICATION_CATEGORY_PLATFORM,
    NOTIFICATION_CATEGORY_FINANCE,
)

# Base path for mailer templates (for reading content)
MAILER_TEMPLATE_DIR = os.path.join(
    os.path.dirname(__file__),
    "..",
    "modules",
    "mailer",
    "templates",
)


def _read_mailer_template(name: str) -> str:
    """Read mailer template file content."""
    path = os.path.join(MAILER_TEMPLATE_DIR, name)
    if os.path.exists(path):
        with open(path, "r") as f:
            return f.read()
    return ""


def seed_default_notification_templates() -> dict:
    """
    Insert default notification templates as GLOBAL (tenant_id = NULL).
    Idempotent: skips if template already exists for (type, channel) global.

    Returns:
        Dict with inserted_count, skipped_count, errors.
    """
    inserted = 0
    skipped = 0
    errors = []

    templates_to_seed = [
        # AUTH - from mailer
        {
            "type": "EMAIL_VERIFICATION",
            "channel": "EMAIL",
            "category": NOTIFICATION_CATEGORY_AUTH,
            "subject_template": "Verify your email",
            "body_template": _read_mailer_template("email_verification.html")
            or '<html><body><p>Please click <a href="{{ verify_url }}">here</a> to verify your email.</p></body></html>',
            "is_system": True,
        },
        {
            "type": "PASSWORD_RESET",
            "channel": "EMAIL",
            "category": NOTIFICATION_CATEGORY_AUTH,
            "subject_template": "Reset your password",
            "body_template": _read_mailer_template("forgot_password.html")
            or '<html><body><p>Click <a href="{{ reset_url }}">here</a> to reset. Expires in {{ expires_in }} minutes.</p></body></html>',
            "is_system": True,
        },
        {
            "type": "WELCOME",
            "channel": "EMAIL",
            "category": NOTIFICATION_CATEGORY_AUTH,
            "subject_template": "Welcome!",
            "body_template": _read_mailer_template("register.html")
            or '<html><body><p>Thank you for joining. Your features: {% for f in features %}{{ f }}{% endfor %}</p></body></html>',
            "is_system": True,
        },
        # STUDENT - from mailer
        {
            "type": "STUDENT_CREDENTIALS",
            "channel": "EMAIL",
            "category": NOTIFICATION_CATEGORY_STUDENT,
            "subject_template": "Welcome to the school",
            "body_template": _read_mailer_template("student_creation.html")
            or '<html><body><p>Admission: {{ admission_number }}, Username: {{ username }}, Password: {{ password }}</p></body></html>',
            "is_system": True,
        },
        # PLATFORM - from mailer
        {
            "type": "ADMIN_CREDENTIALS",
            "channel": "EMAIL",
            "category": NOTIFICATION_CATEGORY_PLATFORM,
            "subject_template": "Your School Admin Account",
            "body_template": _read_mailer_template("school_admin_credentials.html")
            or '<html><body><p>Hello {{ admin_name }}, School: {{ tenant_name }}, Login: {{ login_url }}, Email: {{ admin_email }}, Password: {{ password }}</p></body></html>',
            "is_system": True,
        },
        # FINANCE - for notification dispatcher
        {
            "type": "FEE_OVERDUE",
            "channel": "EMAIL",
            "category": NOTIFICATION_CATEGORY_FINANCE,
            "subject_template": "Fee Overdue",
            "body_template": "<html><body><p>Your fee (due {{ due_date }}) is now overdue. Total: {{ total_amount }}. Please pay at the earliest.</p></body></html>",
            "is_system": True,
        },
        {
            "type": "FEE_DUE",
            "channel": "EMAIL",
            "category": NOTIFICATION_CATEGORY_FINANCE,
            "subject_template": "Fee Due",
            "body_template": "<html><body><p>Your fee of {{ total_amount }} is due on {{ due_date }}.</p></body></html>",
            "is_system": True,
        },
        {
            "type": "PAYMENT_RECEIVED",
            "channel": "EMAIL",
            "category": NOTIFICATION_CATEGORY_FINANCE,
            "subject_template": "Payment Received",
            "body_template": "<html><body><p>We have received your payment of {{ amount }}. Thank you.</p></body></html>",
            "is_system": True,
        },
        {
            "type": "PAYMENT_FAILED",
            "channel": "EMAIL",
            "category": NOTIFICATION_CATEGORY_FINANCE,
            "subject_template": "Payment Failed",
            "body_template": "<html><body><p>Your payment could not be processed. Please try again or contact support.</p></body></html>",
            "is_system": True,
        },
    ]

    for t in templates_to_seed:
        try:
            existing = NotificationTemplate.query.filter(
                NotificationTemplate.tenant_id.is_(None),
                NotificationTemplate.type == t["type"],
                NotificationTemplate.channel == t["channel"],
            ).first()
            if existing:
                skipped += 1
                continue

            nt = NotificationTemplate(
                id=str(uuid.uuid4()),
                tenant_id=None,
                type=t["type"],
                channel=t["channel"],
                category=t["category"],
                is_system=t["is_system"],
                subject_template=t["subject_template"],
                body_template=t["body_template"],
            )
            db.session.add(nt)
            inserted += 1
        except Exception as e:
            errors.append(f"{t['type']}/{t['channel']}: {e}")

    if inserted > 0:
        db.session.commit()

    return {
        "inserted_count": inserted,
        "skipped_count": skipped,
        "errors": errors,
    }


if __name__ == "__main__":
    from backend.app import create_app
    app = create_app()
    with app.app_context():
        result = seed_default_notification_templates()
        print(f"Inserted: {result['inserted_count']}, Skipped: {result['skipped_count']}")
        if result["errors"]:
            print("Errors:", result["errors"])
