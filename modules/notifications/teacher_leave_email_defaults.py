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

_SHARED_STYLES = """
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;
  -webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;
""".strip()

_REQUEST_BODY = """<!DOCTYPE html>
<html lang="en" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <meta http-equiv="X-UA-Compatible" content="IE=edge"/>
  <meta name="x-apple-disable-message-reformatting"/>
  <title>New Teacher Leave Request</title>
</head>
<body style="margin:0;padding:0;background-color:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;">

  <div style="display:none;max-height:0;overflow:hidden;mso-hide:all;font-size:1px;color:#f1f5f9;line-height:1px;">{{ teacher_name }} has submitted a leave request that needs your review. &#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;</div>

  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#f1f5f9">
    <tr>
      <td align="center" style="padding:48px 16px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:600px;">

          <!-- Brand Header -->
          <tr>
            <td align="center" style="background-color:#0f172a;border-radius:12px 12px 0 0;padding:28px 40px 24px;">
              <p style="margin:0;font-size:20px;font-weight:700;color:#ffffff;letter-spacing:-0.5px;line-height:1;">Nexchool</p>
              <p style="margin:4px 0 0;font-size:11px;font-weight:500;color:#64748b;letter-spacing:1.5px;text-transform:uppercase;">School Management Platform</p>
            </td>
          </tr>

          <!-- Status band -->
          <tr>
            <td style="background-color:#f59e0b;padding:14px 48px;border-left:1px solid #d97706;border-right:1px solid #d97706;">
              <table role="presentation" cellspacing="0" cellpadding="0" border="0">
                <tr>
                  <td style="padding-right:10px;vertical-align:middle;">
                    <div style="width:8px;height:8px;background-color:#ffffff;border-radius:50%;opacity:0.9;"></div>
                  </td>
                  <td style="font-size:13px;font-weight:600;color:#ffffff;letter-spacing:0.5px;text-transform:uppercase;">Action Required &mdash; Pending Review</td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Main Card -->
          <tr>
            <td style="background-color:#ffffff;padding:36px 48px 32px;border-left:1px solid #e2e8f0;border-right:1px solid #e2e8f0;">

              <h1 style="margin:0 0 8px;font-size:24px;font-weight:700;color:#0f172a;line-height:1.3;letter-spacing:-0.3px;">New leave request</h1>
              <p style="margin:0 0 24px;font-size:15px;color:#475569;line-height:1.65;">
                Hello <strong>{{ user_name }}</strong>,<br/>
                <strong>{{ teacher_name }}</strong> has submitted a leave request that requires your attention.
              </p>

              <!-- Leave details table -->
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin:0 0 28px;border:1px solid #e2e8f0;border-radius:10px;overflow:hidden;">
                <tr>
                  <td style="padding:12px 20px;background-color:#0f172a;">
                    <p style="margin:0;font-size:11px;font-weight:600;color:#64748b;letter-spacing:1.5px;text-transform:uppercase;">Leave Details</p>
                  </td>
                </tr>
                <tr>
                  <td style="padding:0;background-color:#f8fafc;">
                    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                      <tr>
                        <td style="padding:13px 20px;border-bottom:1px solid #e2e8f0;width:38%;vertical-align:top;">
                          <p style="margin:0;font-size:11px;font-weight:600;color:#94a3b8;letter-spacing:0.8px;text-transform:uppercase;">Teacher</p>
                        </td>
                        <td style="padding:13px 20px;border-bottom:1px solid #e2e8f0;vertical-align:top;">
                          <p style="margin:0;font-size:14px;font-weight:600;color:#0f172a;">{{ teacher_name }}</p>
                        </td>
                      </tr>
                      <tr>
                        <td style="padding:13px 20px;border-bottom:1px solid #e2e8f0;vertical-align:top;">
                          <p style="margin:0;font-size:11px;font-weight:600;color:#94a3b8;letter-spacing:0.8px;text-transform:uppercase;">Leave Type</p>
                        </td>
                        <td style="padding:13px 20px;border-bottom:1px solid #e2e8f0;vertical-align:top;">
                          <p style="margin:0;font-size:14px;font-weight:600;color:#0f172a;">{{ leave_type }}</p>
                        </td>
                      </tr>
                      <tr>
                        <td style="padding:13px 20px;border-bottom:1px solid #e2e8f0;vertical-align:top;">
                          <p style="margin:0;font-size:11px;font-weight:600;color:#94a3b8;letter-spacing:0.8px;text-transform:uppercase;">Period</p>
                        </td>
                        <td style="padding:13px 20px;border-bottom:1px solid #e2e8f0;vertical-align:top;">
                          <p style="margin:0;font-size:14px;font-weight:600;color:#0f172a;">{{ start_date }} &mdash; {{ end_date }}</p>
                        </td>
                      </tr>
                      {% if body %}
                      <tr>
                        <td style="padding:13px 20px;border-bottom:1px solid #e2e8f0;vertical-align:top;">
                          <p style="margin:0;font-size:11px;font-weight:600;color:#94a3b8;letter-spacing:0.8px;text-transform:uppercase;">Notes</p>
                        </td>
                        <td style="padding:13px 20px;border-bottom:1px solid #e2e8f0;vertical-align:top;">
                          <p style="margin:0;font-size:14px;color:#374151;line-height:1.5;">{{ body }}</p>
                        </td>
                      </tr>
                      {% endif %}
                      <tr>
                        <td style="padding:13px 20px;vertical-align:top;">
                          <p style="margin:0;font-size:11px;font-weight:600;color:#94a3b8;letter-spacing:0.8px;text-transform:uppercase;">Reference ID</p>
                        </td>
                        <td style="padding:13px 20px;vertical-align:top;">
                          <p style="margin:0;font-size:13px;color:#64748b;font-family:'Courier New',Courier,monospace;letter-spacing:0.5px;">{{ leave_id }}</p>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>

              <!-- Info box -->
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                <tr>
                  <td style="background-color:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:14px 18px;">
                    <p style="margin:0;font-size:13px;color:#92400e;line-height:1.6;">
                      Log in to the admin panel to approve or reject this request. Pending requests are visible under <strong>Staff &rsaquo; Leave Requests</strong>.
                    </p>
                  </td>
                </tr>
              </table>

            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color:#f8fafc;border:1px solid #e2e8f0;border-top:none;border-radius:0 0 12px 12px;padding:24px 48px;">
              {% if school_name %}
              <p style="margin:0 0 6px;font-size:12px;color:#94a3b8;text-align:center;line-height:1.6;">
                This message was sent by {{ school_name }} via Nexchool.
              </p>
              {% endif %}
              <p style="margin:0;font-size:12px;color:#cbd5e1;text-align:center;">
                &copy; Nexchool &mdash; School Management Platform
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>

</body>
</html>"""

_APPROVED_BODY = """<!DOCTYPE html>
<html lang="en" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <meta http-equiv="X-UA-Compatible" content="IE=edge"/>
  <meta name="x-apple-disable-message-reformatting"/>
  <title>Leave Approved</title>
</head>
<body style="margin:0;padding:0;background-color:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;">

  <div style="display:none;max-height:0;overflow:hidden;mso-hide:all;font-size:1px;color:#f1f5f9;line-height:1px;">Your leave request has been approved. &#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;</div>

  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#f1f5f9">
    <tr>
      <td align="center" style="padding:48px 16px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:600px;">

          <!-- Brand Header -->
          <tr>
            <td align="center" style="background-color:#0f172a;border-radius:12px 12px 0 0;padding:28px 40px 24px;">
              <p style="margin:0;font-size:20px;font-weight:700;color:#ffffff;letter-spacing:-0.5px;line-height:1;">Nexchool</p>
              <p style="margin:4px 0 0;font-size:11px;font-weight:500;color:#64748b;letter-spacing:1.5px;text-transform:uppercase;">School Management Platform</p>
            </td>
          </tr>

          <!-- Status band -->
          <tr>
            <td style="background-color:#16a34a;padding:14px 48px;border-left:1px solid #15803d;border-right:1px solid #15803d;">
              <table role="presentation" cellspacing="0" cellpadding="0" border="0">
                <tr>
                  <td style="padding-right:10px;vertical-align:middle;">
                    <div style="width:18px;height:18px;background-color:rgba(255,255,255,0.2);border-radius:50%;text-align:center;line-height:18px;font-size:11px;color:#ffffff;font-weight:700;">&#10003;</div>
                  </td>
                  <td style="font-size:13px;font-weight:600;color:#ffffff;letter-spacing:0.5px;text-transform:uppercase;">Leave Approved</td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Main Card -->
          <tr>
            <td style="background-color:#ffffff;padding:36px 48px 32px;border-left:1px solid #e2e8f0;border-right:1px solid #e2e8f0;">

              <h1 style="margin:0 0 8px;font-size:24px;font-weight:700;color:#0f172a;line-height:1.3;letter-spacing:-0.3px;">Your leave has been approved</h1>
              <p style="margin:0 0 24px;font-size:15px;color:#475569;line-height:1.65;">
                Hello <strong>{{ user_name }}</strong>,<br/>
                Your leave request has been approved. Please refer to the details below.
              </p>

              <!-- Leave details -->
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin:0 0 28px;border:1px solid #e2e8f0;border-radius:10px;overflow:hidden;">
                <tr>
                  <td style="padding:12px 20px;background-color:#0f172a;">
                    <p style="margin:0;font-size:11px;font-weight:600;color:#64748b;letter-spacing:1.5px;text-transform:uppercase;">Approved Leave Details</p>
                  </td>
                </tr>
                <tr>
                  <td style="padding:0;background-color:#f8fafc;">
                    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                      <tr>
                        <td style="padding:13px 20px;border-bottom:1px solid #e2e8f0;width:38%;vertical-align:top;">
                          <p style="margin:0;font-size:11px;font-weight:600;color:#94a3b8;letter-spacing:0.8px;text-transform:uppercase;">Leave Type</p>
                        </td>
                        <td style="padding:13px 20px;border-bottom:1px solid #e2e8f0;vertical-align:top;">
                          <p style="margin:0;font-size:14px;font-weight:600;color:#0f172a;">{{ leave_type }}</p>
                        </td>
                      </tr>
                      <tr>
                        <td style="padding:13px 20px;border-bottom:1px solid #e2e8f0;vertical-align:top;">
                          <p style="margin:0;font-size:11px;font-weight:600;color:#94a3b8;letter-spacing:0.8px;text-transform:uppercase;">Period</p>
                        </td>
                        <td style="padding:13px 20px;border-bottom:1px solid #e2e8f0;vertical-align:top;">
                          <p style="margin:0;font-size:14px;font-weight:600;color:#0f172a;">{{ start_date }} &mdash; {{ end_date }}</p>
                        </td>
                      </tr>
                      <tr>
                        <td style="padding:13px 20px;vertical-align:top;">
                          <p style="margin:0;font-size:11px;font-weight:600;color:#94a3b8;letter-spacing:0.8px;text-transform:uppercase;">Reference ID</p>
                        </td>
                        <td style="padding:13px 20px;vertical-align:top;">
                          <p style="margin:0;font-size:13px;color:#64748b;font-family:'Courier New',Courier,monospace;letter-spacing:0.5px;">{{ leave_id }}</p>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>

              <!-- Info box -->
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                <tr>
                  <td style="background-color:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:14px 18px;">
                    <p style="margin:0;font-size:13px;color:#166534;line-height:1.6;">
                      You can view the details of this leave in the Nexchool app under <strong>My Leaves</strong>.
                    </p>
                  </td>
                </tr>
              </table>

            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color:#f8fafc;border:1px solid #e2e8f0;border-top:none;border-radius:0 0 12px 12px;padding:24px 48px;">
              {% if school_name %}
              <p style="margin:0 0 6px;font-size:12px;color:#94a3b8;text-align:center;line-height:1.6;">
                This message was sent by {{ school_name }} via Nexchool.
              </p>
              {% endif %}
              <p style="margin:0;font-size:12px;color:#cbd5e1;text-align:center;">
                &copy; Nexchool &mdash; School Management Platform
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>

</body>
</html>"""

_REJECTED_BODY = """<!DOCTYPE html>
<html lang="en" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <meta http-equiv="X-UA-Compatible" content="IE=edge"/>
  <meta name="x-apple-disable-message-reformatting"/>
  <title>Leave Request Update</title>
</head>
<body style="margin:0;padding:0;background-color:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;">

  <div style="display:none;max-height:0;overflow:hidden;mso-hide:all;font-size:1px;color:#f1f5f9;line-height:1px;">Your leave request has not been approved. Please see the details below. &#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;</div>

  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#f1f5f9">
    <tr>
      <td align="center" style="padding:48px 16px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:600px;">

          <!-- Brand Header -->
          <tr>
            <td align="center" style="background-color:#0f172a;border-radius:12px 12px 0 0;padding:28px 40px 24px;">
              <p style="margin:0;font-size:20px;font-weight:700;color:#ffffff;letter-spacing:-0.5px;line-height:1;">Nexchool</p>
              <p style="margin:4px 0 0;font-size:11px;font-weight:500;color:#64748b;letter-spacing:1.5px;text-transform:uppercase;">School Management Platform</p>
            </td>
          </tr>

          <!-- Status band -->
          <tr>
            <td style="background-color:#dc2626;padding:14px 48px;border-left:1px solid #b91c1c;border-right:1px solid #b91c1c;">
              <table role="presentation" cellspacing="0" cellpadding="0" border="0">
                <tr>
                  <td style="padding-right:10px;vertical-align:middle;">
                    <div style="width:18px;height:18px;background-color:rgba(255,255,255,0.2);border-radius:50%;text-align:center;line-height:18px;font-size:14px;color:#ffffff;font-weight:700;">&times;</div>
                  </td>
                  <td style="font-size:13px;font-weight:600;color:#ffffff;letter-spacing:0.5px;text-transform:uppercase;">Leave Not Approved</td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Main Card -->
          <tr>
            <td style="background-color:#ffffff;padding:36px 48px 32px;border-left:1px solid #e2e8f0;border-right:1px solid #e2e8f0;">

              <h1 style="margin:0 0 8px;font-size:24px;font-weight:700;color:#0f172a;line-height:1.3;letter-spacing:-0.3px;">Your leave request was not approved</h1>
              <p style="margin:0 0 24px;font-size:15px;color:#475569;line-height:1.65;">
                Hello <strong>{{ user_name }}</strong>,<br/>
                We regret to inform you that your leave request has not been approved. Please refer to the details below and contact your administrator for more information.
              </p>

              <!-- Leave details -->
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin:0 0 28px;border:1px solid #e2e8f0;border-radius:10px;overflow:hidden;">
                <tr>
                  <td style="padding:12px 20px;background-color:#0f172a;">
                    <p style="margin:0;font-size:11px;font-weight:600;color:#64748b;letter-spacing:1.5px;text-transform:uppercase;">Leave Details</p>
                  </td>
                </tr>
                <tr>
                  <td style="padding:0;background-color:#f8fafc;">
                    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                      <tr>
                        <td style="padding:13px 20px;border-bottom:1px solid #e2e8f0;width:38%;vertical-align:top;">
                          <p style="margin:0;font-size:11px;font-weight:600;color:#94a3b8;letter-spacing:0.8px;text-transform:uppercase;">Leave Type</p>
                        </td>
                        <td style="padding:13px 20px;border-bottom:1px solid #e2e8f0;vertical-align:top;">
                          <p style="margin:0;font-size:14px;font-weight:600;color:#0f172a;">{{ leave_type }}</p>
                        </td>
                      </tr>
                      <tr>
                        <td style="padding:13px 20px;border-bottom:1px solid #e2e8f0;vertical-align:top;">
                          <p style="margin:0;font-size:11px;font-weight:600;color:#94a3b8;letter-spacing:0.8px;text-transform:uppercase;">Period</p>
                        </td>
                        <td style="padding:13px 20px;border-bottom:1px solid #e2e8f0;vertical-align:top;">
                          <p style="margin:0;font-size:14px;font-weight:600;color:#0f172a;">{{ start_date }} &mdash; {{ end_date }}</p>
                        </td>
                      </tr>
                      <tr>
                        <td style="padding:13px 20px;vertical-align:top;">
                          <p style="margin:0;font-size:11px;font-weight:600;color:#94a3b8;letter-spacing:0.8px;text-transform:uppercase;">Reference ID</p>
                        </td>
                        <td style="padding:13px 20px;vertical-align:top;">
                          <p style="margin:0;font-size:13px;color:#64748b;font-family:'Courier New',Courier,monospace;letter-spacing:0.5px;">{{ leave_id }}</p>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>

              <!-- Info box -->
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                <tr>
                  <td style="background-color:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:14px 18px;">
                    <p style="margin:0;font-size:13px;color:#991b1b;line-height:1.6;">
                      If you have questions, please contact your school administrator. You can view your leave history in the Nexchool app under <strong>My Leaves</strong>.
                    </p>
                  </td>
                </tr>
              </table>

            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color:#f8fafc;border:1px solid #e2e8f0;border-top:none;border-radius:0 0 12px 12px;padding:24px 48px;">
              {% if school_name %}
              <p style="margin:0 0 6px;font-size:12px;color:#94a3b8;text-align:center;line-height:1.6;">
                This message was sent by {{ school_name }} via Nexchool.
              </p>
              {% endif %}
              <p style="margin:0;font-size:12px;color:#cbd5e1;text-align:center;">
                &copy; Nexchool &mdash; School Management Platform
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>

</body>
</html>"""


def teacher_leave_email_template_rows() -> List[dict[str, Any]]:
    """Rows compatible with `NotificationTemplate` insert / seed dicts (global EMAIL)."""
    return [
        {
            "type": "TEACHER_LEAVE_REQUEST",
            "channel": "EMAIL",
            "category": "SYSTEM",
            "subject_template": "Leave request from {{ teacher_name }} — action required",
            "body_template": _REQUEST_BODY,
            "is_system": True,
        },
        {
            "type": "TEACHER_LEAVE_APPROVED",
            "channel": "EMAIL",
            "category": "SYSTEM",
            "subject_template": "Your leave has been approved ({{ leave_type }}, {{ start_date }} to {{ end_date }})",
            "body_template": _APPROVED_BODY,
            "is_system": True,
        },
        {
            "type": "TEACHER_LEAVE_REJECTED",
            "channel": "EMAIL",
            "category": "SYSTEM",
            "subject_template": "Update on your leave request ({{ leave_type }}, {{ start_date }} to {{ end_date }})",
            "body_template": _REJECTED_BODY,
            "is_system": True,
        },
    ]
