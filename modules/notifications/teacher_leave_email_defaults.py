"""
Default HTML email templates for teacher leave notifications (global EMAIL channel).

Used by:
- Alembic migration `038_leave_email_tpl`
- `scripts.seed_notification_templates` (manual re-seed)

Context keys available at render time include those passed in `extra_data` plus
`user_name`, `user_email`, `title`, `body`, and (for previews) `school_name`.
"""

from __future__ import annotations

from typing import Any, List

_REQUEST_BODY = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/></head>
<body style="margin:0;padding:24px;background:#f4f6f8;font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#111827;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:640px;margin:0 auto;background:#ffffff;border-radius:12px;overflow:hidden;border:1px solid #e5e7eb;">
    <tr><td style="padding:20px 24px;background:#111827;color:#ffffff;font-size:18px;font-weight:600;">New teacher leave request</td></tr>
    <tr><td style="padding:24px;font-size:15px;line-height:1.55;">
      <p style="margin:0 0 12px;">Hello {{ user_name }},</p>
      <p style="margin:0 0 16px;">{{ teacher_name }} has submitted a leave request that needs your attention.</p>
      <table role="presentation" cellspacing="0" cellpadding="0" style="width:100%;border-collapse:collapse;font-size:14px;">
        <tr><td style="padding:8px 0;color:#6b7280;width:38%;">Teacher</td><td style="padding:8px 0;font-weight:600;">{{ teacher_name }}</td></tr>
        <tr><td style="padding:8px 0;color:#6b7280;">Leave type</td><td style="padding:8px 0;font-weight:600;">{{ leave_type }}</td></tr>
        <tr><td style="padding:8px 0;color:#6b7280;">Dates</td><td style="padding:8px 0;font-weight:600;">{{ start_date }} → {{ end_date }}</td></tr>
        <tr><td style="padding:8px 0;color:#6b7280;vertical-align:top;">Summary</td><td style="padding:8px 0;">{{ body }}</td></tr>
        <tr><td style="padding:8px 0;color:#6b7280;">Leave ID</td><td style="padding:8px 0;font-family:ui-monospace,Menlo,monospace;font-size:13px;">{{ leave_id }}</td></tr>
      </table>
      <p style="margin:20px 0 0;font-size:13px;color:#6b7280;">Open the school admin panel to review pending leave requests.</p>
    </td></tr>
  </table>
  <p style="max-width:640px;margin:16px auto 0;font-size:12px;color:#9ca3af;text-align:center;">This message was sent by {{ school_name }}.</p>
</body>
</html>"""

_DECISION_BODY = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/></head>
<body style="margin:0;padding:24px;background:#f4f6f8;font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#111827;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:640px;margin:0 auto;background:#ffffff;border-radius:12px;overflow:hidden;border:1px solid #e5e7eb;">
    <tr><td style="padding:20px 24px;background:#111827;color:#ffffff;font-size:18px;font-weight:600;">{{ title }}</td></tr>
    <tr><td style="padding:24px;font-size:15px;line-height:1.55;">
      <p style="margin:0 0 12px;">Hello {{ user_name }},</p>
      <p style="margin:0 0 16px;">{{ body }}</p>
      <table role="presentation" cellspacing="0" cellpadding="0" style="width:100%;border-collapse:collapse;font-size:14px;">
        <tr><td style="padding:8px 0;color:#6b7280;width:38%;">Leave type</td><td style="padding:8px 0;font-weight:600;">{{ leave_type }}</td></tr>
        <tr><td style="padding:8px 0;color:#6b7280;">Dates</td><td style="padding:8px 0;font-weight:600;">{{ start_date }} → {{ end_date }}</td></tr>
        <tr><td style="padding:8px 0;color:#6b7280;">Leave ID</td><td style="padding:8px 0;font-family:ui-monospace,Menlo,monospace;font-size:13px;">{{ leave_id }}</td></tr>
      </table>
      <p style="margin:20px 0 0;font-size:13px;color:#6b7280;">You can view details in the Nexchool app under <strong>My leaves</strong>.</p>
    </td></tr>
  </table>
  <p style="max-width:640px;margin:16px auto 0;font-size:12px;color:#9ca3af;text-align:center;">This message was sent by {{ school_name }}.</p>
</body>
</html>"""


def teacher_leave_email_template_rows() -> List[dict[str, Any]]:
    """Rows compatible with `NotificationTemplate` insert / seed dicts (global EMAIL)."""
    return [
        {
            "type": "TEACHER_LEAVE_REQUEST",
            "channel": "EMAIL",
            "category": "SYSTEM",
            "subject_template": "New teacher leave request — {{ teacher_name }}",
            "body_template": _REQUEST_BODY,
            "is_system": True,
        },
        {
            "type": "TEACHER_LEAVE_APPROVED",
            "channel": "EMAIL",
            "category": "SYSTEM",
            "subject_template": "Leave approved — {{ leave_type }} ({{ start_date }} to {{ end_date }})",
            "body_template": _DECISION_BODY,
            "is_system": True,
        },
        {
            "type": "TEACHER_LEAVE_REJECTED",
            "channel": "EMAIL",
            "category": "SYSTEM",
            "subject_template": "Leave request update — {{ leave_type }} ({{ start_date }} to {{ end_date }})",
            "body_template": _DECISION_BODY,
            "is_system": True,
        },
    ]
