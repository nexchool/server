"""
Seed default notification templates.

Inserts current mailer HTML templates and finance notification types into
notification_templates table as GLOBAL templates (tenant_id = NULL).
Does NOT delete filesystem templates.

Run: flask shell
    >>> from scripts.seed_notification_templates import seed_default_notification_templates
    >>> seed_default_notification_templates()
"""

import os
import uuid

from core.database import db
from modules.notifications.models import NotificationTemplate
from modules.notifications.template_service import (
    NOTIFICATION_CATEGORY_AUTH,
    NOTIFICATION_CATEGORY_STUDENT,
    NOTIFICATION_CATEGORY_PLATFORM,
    NOTIFICATION_CATEGORY_FINANCE,
    NOTIFICATION_CATEGORY_SYSTEM,
)
from modules.notifications.teacher_leave_email_defaults import (
    teacher_leave_email_template_rows,
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


def seed_default_notification_templates(force_update: bool = False) -> dict:
    """
    Insert default notification templates as GLOBAL (tenant_id = NULL).
    Idempotent by default: skips existing (type, channel) global templates.

    Args:
        force_update: When True, overwrites subject_template and body_template
                      for templates that already exist in the database.

    Returns:
        Dict with inserted_count, skipped_count, updated_count, errors.
    """
    inserted = 0
    skipped = 0
    updated = 0
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
        {
            "type": "ADMIN_PASSWORD_RESET",
            "channel": "EMAIL",
            "category": NOTIFICATION_CATEGORY_PLATFORM,
            "subject_template": "Your admin password for {{ tenant_name }} has been reset",
            "body_template": _read_mailer_template("school_admin_password_reset.html")
            or '<html><body><p>Hello {{ admin_name }}, your password for {{ tenant_name }} has been reset. Email: {{ admin_email }}, Temporary password: {{ password }}</p></body></html>',
            "is_system": True,
        },
        # FINANCE - for notification dispatcher
        {
            "type": "FEE_OVERDUE",
            "channel": "EMAIL",
            "category": NOTIFICATION_CATEGORY_FINANCE,
            "subject_template": "Overdue fee notice — action required",
            "body_template": """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0"/><meta http-equiv="X-UA-Compatible" content="IE=edge"/><title>Overdue Fee Notice</title></head>
<body style="margin:0;padding:0;background-color:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;">
  <div style="display:none;max-height:0;overflow:hidden;mso-hide:all;font-size:1px;color:#f1f5f9;line-height:1px;">Your fee payment is overdue. Please settle your dues at the earliest. &#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;</div>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#f1f5f9"><tr><td align="center" style="padding:48px 16px;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:600px;">
    <tr><td align="center" style="background-color:#0f172a;border-radius:12px 12px 0 0;padding:28px 40px 24px;">
      <p style="margin:0;font-size:20px;font-weight:700;color:#ffffff;letter-spacing:-0.5px;line-height:1;">Nexchool</p>
      <p style="margin:4px 0 0;font-size:11px;font-weight:500;color:#64748b;letter-spacing:1.5px;text-transform:uppercase;">School Management Platform</p>
    </td></tr>
    <tr><td style="background-color:#dc2626;padding:14px 48px;border-left:1px solid #b91c1c;border-right:1px solid #b91c1c;">
      <p style="margin:0;font-size:13px;font-weight:600;color:#ffffff;letter-spacing:0.5px;text-transform:uppercase;">Overdue Payment &mdash; Immediate Attention Required</p>
    </td></tr>
    <tr><td style="background-color:#ffffff;padding:36px 48px 32px;border-left:1px solid #e2e8f0;border-right:1px solid #e2e8f0;">
      <h1 style="margin:0 0 12px;font-size:24px;font-weight:700;color:#0f172a;line-height:1.3;letter-spacing:-0.3px;">Fee payment overdue</h1>
      <p style="margin:0 0 24px;font-size:15px;color:#475569;line-height:1.65;">Your fee payment was due on <strong>{{ due_date }}</strong> and has not yet been received. Please settle the outstanding amount as soon as possible to avoid any disruption.</p>
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin:0 0 28px;border:1px solid #e2e8f0;border-radius:10px;overflow:hidden;">
        <tr><td style="padding:12px 20px;background-color:#0f172a;"><p style="margin:0;font-size:11px;font-weight:600;color:#64748b;letter-spacing:1.5px;text-transform:uppercase;">Payment Summary</p></td></tr>
        <tr><td style="padding:0;background-color:#f8fafc;">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
            <tr><td style="padding:13px 20px;border-bottom:1px solid #e2e8f0;width:50%;"><p style="margin:0;font-size:11px;font-weight:600;color:#94a3b8;letter-spacing:0.8px;text-transform:uppercase;">Due Date</p></td><td style="padding:13px 20px;border-bottom:1px solid #e2e8f0;"><p style="margin:0;font-size:14px;font-weight:600;color:#dc2626;">{{ due_date }}</p></td></tr>
            <tr><td style="padding:13px 20px;"><p style="margin:0;font-size:11px;font-weight:600;color:#94a3b8;letter-spacing:0.8px;text-transform:uppercase;">Outstanding Amount</p></td><td style="padding:13px 20px;"><p style="margin:0;font-size:18px;font-weight:700;color:#0f172a;">{{ total_amount }}</p></td></tr>
          </table>
        </td></tr>
      </table>
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
        <tr><td style="background-color:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:14px 18px;">
          <p style="margin:0;font-size:13px;color:#991b1b;line-height:1.6;">Please contact your school's accounts office to make the payment or discuss a payment arrangement.</p>
        </td></tr>
      </table>
    </td></tr>
    <tr><td style="background-color:#f8fafc;border:1px solid #e2e8f0;border-top:none;border-radius:0 0 12px 12px;padding:24px 48px;">
      <p style="margin:0 0 6px;font-size:12px;color:#94a3b8;text-align:center;line-height:1.6;">This is an automated reminder from Nexchool. Please do not reply to this email.</p>
      <p style="margin:0;font-size:12px;color:#cbd5e1;text-align:center;">&copy; Nexchool &mdash; School Management Platform</p>
    </td></tr>
  </table></td></tr></table>
</body></html>""",
            "is_system": True,
        },
        {
            "type": "FEE_DUE",
            "channel": "EMAIL",
            "category": NOTIFICATION_CATEGORY_FINANCE,
            "subject_template": "Fee payment due on {{ due_date }}",
            "body_template": """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0"/><meta http-equiv="X-UA-Compatible" content="IE=edge"/><title>Fee Due Reminder</title></head>
<body style="margin:0;padding:0;background-color:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;">
  <div style="display:none;max-height:0;overflow:hidden;mso-hide:all;font-size:1px;color:#f1f5f9;line-height:1px;">A friendly reminder that your fee payment is due on {{ due_date }}. &#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;</div>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#f1f5f9"><tr><td align="center" style="padding:48px 16px;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:600px;">
    <tr><td align="center" style="background-color:#0f172a;border-radius:12px 12px 0 0;padding:28px 40px 24px;">
      <p style="margin:0;font-size:20px;font-weight:700;color:#ffffff;letter-spacing:-0.5px;line-height:1;">Nexchool</p>
      <p style="margin:4px 0 0;font-size:11px;font-weight:500;color:#64748b;letter-spacing:1.5px;text-transform:uppercase;">School Management Platform</p>
    </td></tr>
    <tr><td style="background-color:#f59e0b;padding:14px 48px;border-left:1px solid #d97706;border-right:1px solid #d97706;">
      <p style="margin:0;font-size:13px;font-weight:600;color:#ffffff;letter-spacing:0.5px;text-transform:uppercase;">Fee Payment Reminder</p>
    </td></tr>
    <tr><td style="background-color:#ffffff;padding:36px 48px 32px;border-left:1px solid #e2e8f0;border-right:1px solid #e2e8f0;">
      <h1 style="margin:0 0 12px;font-size:24px;font-weight:700;color:#0f172a;line-height:1.3;letter-spacing:-0.3px;">Fee payment due soon</h1>
      <p style="margin:0 0 24px;font-size:15px;color:#475569;line-height:1.65;">This is a friendly reminder that a fee payment is due on <strong>{{ due_date }}</strong>. Please ensure payment is made on time to avoid a late fee.</p>
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin:0 0 28px;border:1px solid #e2e8f0;border-radius:10px;overflow:hidden;">
        <tr><td style="padding:12px 20px;background-color:#0f172a;"><p style="margin:0;font-size:11px;font-weight:600;color:#64748b;letter-spacing:1.5px;text-transform:uppercase;">Payment Summary</p></td></tr>
        <tr><td style="padding:0;background-color:#f8fafc;">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
            <tr><td style="padding:13px 20px;border-bottom:1px solid #e2e8f0;width:50%;"><p style="margin:0;font-size:11px;font-weight:600;color:#94a3b8;letter-spacing:0.8px;text-transform:uppercase;">Due Date</p></td><td style="padding:13px 20px;border-bottom:1px solid #e2e8f0;"><p style="margin:0;font-size:14px;font-weight:600;color:#0f172a;">{{ due_date }}</p></td></tr>
            <tr><td style="padding:13px 20px;"><p style="margin:0;font-size:11px;font-weight:600;color:#94a3b8;letter-spacing:0.8px;text-transform:uppercase;">Amount Due</p></td><td style="padding:13px 20px;"><p style="margin:0;font-size:18px;font-weight:700;color:#0f172a;">{{ total_amount }}</p></td></tr>
          </table>
        </td></tr>
      </table>
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
        <tr><td style="background-color:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:14px 18px;">
          <p style="margin:0;font-size:13px;color:#92400e;line-height:1.6;">Please contact your school's accounts office if you need assistance with payment options.</p>
        </td></tr>
      </table>
    </td></tr>
    <tr><td style="background-color:#f8fafc;border:1px solid #e2e8f0;border-top:none;border-radius:0 0 12px 12px;padding:24px 48px;">
      <p style="margin:0 0 6px;font-size:12px;color:#94a3b8;text-align:center;line-height:1.6;">This is an automated reminder from Nexchool. Please do not reply to this email.</p>
      <p style="margin:0;font-size:12px;color:#cbd5e1;text-align:center;">&copy; Nexchool &mdash; School Management Platform</p>
    </td></tr>
  </table></td></tr></table>
</body></html>""",
            "is_system": True,
        },
        {
            "type": "PAYMENT_RECEIVED",
            "channel": "EMAIL",
            "category": NOTIFICATION_CATEGORY_FINANCE,
            "subject_template": "Payment confirmed — receipt for {{ amount }}",
            "body_template": """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0"/><meta http-equiv="X-UA-Compatible" content="IE=edge"/><title>Payment Confirmed</title></head>
<body style="margin:0;padding:0;background-color:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;">
  <div style="display:none;max-height:0;overflow:hidden;mso-hide:all;font-size:1px;color:#f1f5f9;line-height:1px;">Your payment of {{ amount }} has been received and confirmed. &#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;</div>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#f1f5f9"><tr><td align="center" style="padding:48px 16px;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:600px;">
    <tr><td align="center" style="background-color:#0f172a;border-radius:12px 12px 0 0;padding:28px 40px 24px;">
      <p style="margin:0;font-size:20px;font-weight:700;color:#ffffff;letter-spacing:-0.5px;line-height:1;">Nexchool</p>
      <p style="margin:4px 0 0;font-size:11px;font-weight:500;color:#64748b;letter-spacing:1.5px;text-transform:uppercase;">School Management Platform</p>
    </td></tr>
    <tr><td style="background-color:#16a34a;padding:14px 48px;border-left:1px solid #15803d;border-right:1px solid #15803d;">
      <p style="margin:0;font-size:13px;font-weight:600;color:#ffffff;letter-spacing:0.5px;text-transform:uppercase;">Payment Confirmed</p>
    </td></tr>
    <tr><td style="background-color:#ffffff;padding:36px 48px 32px;border-left:1px solid #e2e8f0;border-right:1px solid #e2e8f0;">
      <h1 style="margin:0 0 12px;font-size:24px;font-weight:700;color:#0f172a;line-height:1.3;letter-spacing:-0.3px;">Payment received</h1>
      <p style="margin:0 0 24px;font-size:15px;color:#475569;line-height:1.65;">Thank you — your payment has been successfully received and recorded. Please retain this email as your payment confirmation.</p>
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin:0 0 28px;border:1px solid #e2e8f0;border-radius:10px;overflow:hidden;">
        <tr><td style="padding:12px 20px;background-color:#0f172a;"><p style="margin:0;font-size:11px;font-weight:600;color:#64748b;letter-spacing:1.5px;text-transform:uppercase;">Payment Confirmation</p></td></tr>
        <tr><td style="padding:0;background-color:#f8fafc;">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
            <tr><td style="padding:13px 20px;"><p style="margin:0;font-size:11px;font-weight:600;color:#94a3b8;letter-spacing:0.8px;text-transform:uppercase;">Amount Paid</p></td><td style="padding:13px 20px;"><p style="margin:0;font-size:22px;font-weight:700;color:#16a34a;">{{ amount }}</p></td></tr>
          </table>
        </td></tr>
      </table>
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
        <tr><td style="background-color:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:14px 18px;">
          <p style="margin:0;font-size:13px;color:#166534;line-height:1.6;">A detailed receipt is available from your school's accounts office. Keep this email for your records.</p>
        </td></tr>
      </table>
    </td></tr>
    <tr><td style="background-color:#f8fafc;border:1px solid #e2e8f0;border-top:none;border-radius:0 0 12px 12px;padding:24px 48px;">
      <p style="margin:0 0 6px;font-size:12px;color:#94a3b8;text-align:center;line-height:1.6;">This is an automated message from Nexchool. Please do not reply to this email.</p>
      <p style="margin:0;font-size:12px;color:#cbd5e1;text-align:center;">&copy; Nexchool &mdash; School Management Platform</p>
    </td></tr>
  </table></td></tr></table>
</body></html>""",
            "is_system": True,
        },
        {
            "type": "PAYMENT_FAILED",
            "channel": "EMAIL",
            "category": NOTIFICATION_CATEGORY_FINANCE,
            "subject_template": "Payment could not be processed — action required",
            "body_template": """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0"/><meta http-equiv="X-UA-Compatible" content="IE=edge"/><title>Payment Failed</title></head>
<body style="margin:0;padding:0;background-color:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;">
  <div style="display:none;max-height:0;overflow:hidden;mso-hide:all;font-size:1px;color:#f1f5f9;line-height:1px;">Your recent payment could not be processed. Please try again or contact your school. &#8203;&#8203;&#8203;&#8203;&#8203;&#8203;</div>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#f1f5f9"><tr><td align="center" style="padding:48px 16px;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:600px;">
    <tr><td align="center" style="background-color:#0f172a;border-radius:12px 12px 0 0;padding:28px 40px 24px;">
      <p style="margin:0;font-size:20px;font-weight:700;color:#ffffff;letter-spacing:-0.5px;line-height:1;">Nexchool</p>
      <p style="margin:4px 0 0;font-size:11px;font-weight:500;color:#64748b;letter-spacing:1.5px;text-transform:uppercase;">School Management Platform</p>
    </td></tr>
    <tr><td style="background-color:#dc2626;padding:14px 48px;border-left:1px solid #b91c1c;border-right:1px solid #b91c1c;">
      <p style="margin:0;font-size:13px;font-weight:600;color:#ffffff;letter-spacing:0.5px;text-transform:uppercase;">Payment Failed &mdash; Action Required</p>
    </td></tr>
    <tr><td style="background-color:#ffffff;padding:36px 48px 32px;border-left:1px solid #e2e8f0;border-right:1px solid #e2e8f0;">
      <h1 style="margin:0 0 12px;font-size:24px;font-weight:700;color:#0f172a;line-height:1.3;letter-spacing:-0.3px;">Payment could not be processed</h1>
      <p style="margin:0 0 24px;font-size:15px;color:#475569;line-height:1.65;">We were unable to process your recent fee payment. This may be due to insufficient funds, an expired card, or a temporary issue. Please try again or contact your school's accounts office.</p>
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
        <tr><td style="background-color:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:16px 18px;">
          <p style="margin:0 0 8px;font-size:13px;font-weight:600;color:#991b1b;">What to do next</p>
          <table role="presentation" cellspacing="0" cellpadding="0" border="0">
            <tr><td style="padding:4px 0;vertical-align:top;padding-right:8px;font-size:13px;color:#b91c1c;">1.</td><td style="padding:4px 0;font-size:13px;color:#b91c1c;line-height:1.5;">Verify your payment details are correct and up to date.</td></tr>
            <tr><td style="padding:4px 0;vertical-align:top;padding-right:8px;font-size:13px;color:#b91c1c;">2.</td><td style="padding:4px 0;font-size:13px;color:#b91c1c;line-height:1.5;">Retry the payment through the Nexchool app or portal.</td></tr>
            <tr><td style="padding:4px 0;vertical-align:top;padding-right:8px;font-size:13px;color:#b91c1c;">3.</td><td style="padding:4px 0;font-size:13px;color:#b91c1c;line-height:1.5;">Contact your school's accounts office if the issue persists.</td></tr>
          </table>
        </td></tr>
      </table>
    </td></tr>
    <tr><td style="background-color:#f8fafc;border:1px solid #e2e8f0;border-top:none;border-radius:0 0 12px 12px;padding:24px 48px;">
      <p style="margin:0 0 6px;font-size:12px;color:#94a3b8;text-align:center;line-height:1.6;">This is an automated message from Nexchool. Please do not reply to this email.</p>
      <p style="margin:0;font-size:12px;color:#cbd5e1;text-align:center;">&copy; Nexchool &mdash; School Management Platform</p>
    </td></tr>
  </table></td></tr></table>
</body></html>""",
            "is_system": True,
        },
    ]

    for row in teacher_leave_email_template_rows():
        templates_to_seed.append(
            {
                "type": row["type"],
                "channel": row["channel"],
                "category": row.get("category") or NOTIFICATION_CATEGORY_SYSTEM,
                "subject_template": row["subject_template"],
                "body_template": row["body_template"],
                "is_system": bool(row.get("is_system", True)),
            }
        )

    for t in templates_to_seed:
        try:
            existing = NotificationTemplate.query.filter(
                NotificationTemplate.tenant_id.is_(None),
                NotificationTemplate.type == t["type"],
                NotificationTemplate.channel == t["channel"],
            ).first()
            if existing:
                if force_update:
                    existing.subject_template = t["subject_template"]
                    existing.body_template = t["body_template"]
                    updated += 1
                else:
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

    if inserted > 0 or updated > 0:
        db.session.commit()

    return {
        "inserted_count": inserted,
        "updated_count": updated,
        "skipped_count": skipped,
        "errors": errors,
    }


if __name__ == "__main__":
    from app import create_app
    app = create_app()
    import sys
    force = "--force" in sys.argv or "--update" in sys.argv
    with app.app_context():
        result = seed_default_notification_templates(force_update=force)
        print(
            f"Inserted: {result['inserted_count']}, "
            f"Updated: {result['updated_count']}, "
            f"Skipped: {result['skipped_count']}"
        )
        if result["errors"]:
            print("Errors:", result["errors"])
