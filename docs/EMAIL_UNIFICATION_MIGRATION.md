# Email Unification — Migration Instructions

All email sending is now routed through the notification template system via `NotificationDispatcher`.

## Pre-Migration Checklist

- [ ] Database backup taken
- [ ] Migration 008 applied (`flask db upgrade`)
- [ ] Celery worker and Redis running (for async email)

## Migration Steps

### 1. Run seed script (idempotent)

```bash
cd app
python -m scripts.seed_existing_mailer_templates_to_db
```

This inserts mailer templates (email_verification, forgot_password, register, student_creation, school_admin_credentials, ADMIN_PASSWORD_RESET) as GLOBAL notification_templates. Skips if already present.

### 2. Verify templates exist

```sql
SELECT type, channel, category FROM notification_templates WHERE tenant_id IS NULL;
```

Expected: EMAIL_VERIFICATION, PASSWORD_RESET, WELCOME, STUDENT_CREDENTIALS, ADMIN_CREDENTIALS, ADMIN_PASSWORD_RESET (all channel=EMAIL).

### 3. Test flows

- **Auth**: Register → verification email; Forgot password → reset email; Email validate → welcome email
- **Students**: Create student with email → credentials email
- **Platform**: Create tenant → admin credentials; Reset admin → password reset email; Add admin → credentials

## Replaced Files

| File | Change |
|------|--------|
| `auth/routes.py` | send_template_email → notification_dispatcher.dispatch (3 calls) |
| `students/routes.py` | send_template_email → notification_dispatcher.dispatch (1 call) |
| `platform/services.py` | send_template_email → notification_dispatcher.dispatch (3 calls) |
| `mailer/service.py` | Deprecated; redirects to NotificationDispatcher |
| `notifications/services/__init__.py` | Added notification_dispatcher singleton |

## Deprecation Notes

- `send_template_email` and `send_email` in mailer module are deprecated
- They log a warning and redirect to NotificationDispatcher when possible
- Filesystem templates in `mailer/templates/` are NOT deleted — kept for reference
- New code should use `notification_dispatcher.dispatch()` directly

## Rollback

If issues occur, the mailer module still contains the original logic in deprecated form. To revert: restore the previous `send_template_email` implementation and revert the auth/students/platform changes. Templates in DB remain harmless.
