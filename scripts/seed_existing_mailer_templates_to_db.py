"""
Seed existing mailer templates into notification_templates table.

Reads HTML from modules/mailer/templates/ and inserts as GLOBAL templates.
Does NOT delete filesystem templates.

Run: python -m scripts.seed_existing_mailer_templates_to_db

Or: flask shell
    >>> from scripts.seed_existing_mailer_templates_to_db import seed_existing_mailer_templates_to_db
    >>> seed_existing_mailer_templates_to_db()
"""

import os
import uuid

from core.database import db
from modules.notifications.models import NotificationTemplate
from modules.notifications.template_service import (
    NOTIFICATION_CATEGORY_AUTH,
    NOTIFICATION_CATEGORY_STUDENT,
    NOTIFICATION_CATEGORY_PLATFORM,
)

MAILER_TEMPLATE_DIR = os.path.join(
    os.path.dirname(__file__),
    "..",
    "modules",
    "mailer",
    "templates",
)

# Mapping: filename -> (type, category, default_subject)
MAILER_TEMPLATE_MAP = {
    "email_verification.html": ("EMAIL_VERIFICATION", NOTIFICATION_CATEGORY_AUTH, "Verify your email"),
    "forgot_password.html": ("PASSWORD_RESET", NOTIFICATION_CATEGORY_AUTH, "Reset your password"),
    "register.html": ("WELCOME", NOTIFICATION_CATEGORY_AUTH, "Welcome!"),
    "student_creation.html": ("STUDENT_CREDENTIALS", NOTIFICATION_CATEGORY_STUDENT, "Welcome to the school"),
    "school_admin_credentials.html": ("ADMIN_CREDENTIALS", NOTIFICATION_CATEGORY_PLATFORM, "Your School Admin Account"),
}


def _read_mailer_template(name: str) -> str:
    """Read mailer template file content."""
    path = os.path.join(MAILER_TEMPLATE_DIR, name)
    if os.path.exists(path):
        with open(path, "r") as f:
            return f.read()
    return ""


def seed_existing_mailer_templates_to_db() -> dict:
    """
    Read all templates from modules/mailer/templates/
    Insert into notification_templates as GLOBAL (tenant_id=NULL).
    Skip if template already exists for (type, channel) global.

    Returns:
        Dict with inserted_count, skipped_count, errors.
    """
    inserted = 0
    skipped = 0
    errors = []

    for filename, (notification_type, category, default_subject) in MAILER_TEMPLATE_MAP.items():
        try:
            existing = NotificationTemplate.query.filter(
                NotificationTemplate.tenant_id.is_(None),
                NotificationTemplate.type == notification_type,
                NotificationTemplate.channel == "EMAIL",
            ).first()
            if existing:
                skipped += 1
                continue

            body_template = _read_mailer_template(filename)
            if not body_template.strip():
                body_template = f"<html><body><p>Template {filename} - configure in notification_templates.</p></body></html>"

            nt = NotificationTemplate(
                id=str(uuid.uuid4()),
                tenant_id=None,
                type=notification_type,
                channel="EMAIL",
                category=category,
                is_system=True,
                subject_template=default_subject,
                body_template=body_template,
            )
            db.session.add(nt)
            inserted += 1
        except Exception as e:
            errors.append(f"{filename}: {e}")

    # Also seed ADMIN_PASSWORD_RESET with its own dedicated template
    try:
        existing = NotificationTemplate.query.filter(
            NotificationTemplate.tenant_id.is_(None),
            NotificationTemplate.type == "ADMIN_PASSWORD_RESET",
            NotificationTemplate.channel == "EMAIL",
        ).first()
        if not existing:
            body = _read_mailer_template("school_admin_password_reset.html") or (
                "<html><body><p>Hello {{ admin_name }}, "
                "your password for {{ tenant_name }} has been reset. "
                "Email: {{ admin_email }}, Temporary password: {{ password }}</p></body></html>"
            )
            nt = NotificationTemplate(
                id=str(uuid.uuid4()),
                tenant_id=None,
                type="ADMIN_PASSWORD_RESET",
                channel="EMAIL",
                category=NOTIFICATION_CATEGORY_PLATFORM,
                is_system=True,
                subject_template="Your admin password for {{ tenant_name }} has been reset",
                body_template=body,
            )
            db.session.add(nt)
            inserted += 1
    except Exception as e:
        errors.append(f"ADMIN_PASSWORD_RESET: {e}")

    if inserted > 0:
        db.session.commit()

    return {
        "inserted_count": inserted,
        "skipped_count": skipped,
        "errors": errors,
    }


if __name__ == "__main__":
    from app import create_app
    app = create_app()
    with app.app_context():
        result = seed_existing_mailer_templates_to_db()
        print(f"Inserted: {result['inserted_count']}, Skipped: {result['skipped_count']}")
        if result["errors"]:
            print("Errors:", result["errors"])
