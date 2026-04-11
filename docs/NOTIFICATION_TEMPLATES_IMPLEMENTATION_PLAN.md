# Notification Templates — Implementation Plan

Unified email + notification template management. Additive architecture; mailer module and auth/student flows unchanged.

---

## 1. Updated Schema

### `notification_templates` table (migration 008)

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| id | String(36) | No | PK, UUID |
| tenant_id | String(36) | **Yes** | FK tenants; NULL = global default |
| type | String(50) | No | e.g. FEE_OVERDUE, EMAIL_VERIFICATION |
| channel | String(20) | No | EMAIL, SMS, IN_APP |
| category | String(20) | No | AUTH, STUDENT, PLATFORM, FINANCE, SYSTEM |
| is_system | Boolean | No | Default false |
| subject_template | String(500) | No | Jinja2 template |
| body_template | Text | No | Jinja2 template |
| created_at | DateTime | No | |
| updated_at | DateTime | No | |

**Unique constraints (partial indexes):**
- `uq_notification_templates_global`: (type, channel) WHERE tenant_id IS NULL
- `uq_notification_templates_tenant`: (tenant_id, type, channel) WHERE tenant_id IS NOT NULL

---

## 2. Migration Files

- **008_notification_templates.py** — Creates `notification_templates` with category, is_system, partial unique indexes.

```bash
flask db upgrade
```

---

## 3. Template Service Code

**File:** `server/modules/notifications/template_service.py`

- `get_notification_template(tenant_id, type, channel)` — tenant → global fallback; raises `TemplateNotFoundError`
- `render_notification_template(subject_template, body_template, context)` — Jinja2 safe env
- `get_and_render_notification_template(...)` — lookup + render
- Constants: `NOTIFICATION_CATEGORY_*`, `NOTIFICATION_CATEGORIES`

---

## 4. Dispatcher Updates

**EmailStrategy** (`notifications/services/strategies/email_strategy.py`):

- No longer uses raw title/body from dispatcher for EMAIL channel
- Calls `get_and_render_notification_template(tenant_id, notification_type, channel="EMAIL", context)`
- Context = `extra_data` + `user_email`, `user_name`, `title`, `body` (fallback keys)
- Renders subject and body from templates, then enqueues Celery `send_email_task`
- On `TemplateNotFoundError` → returns False (no hardcoded fallback body)

**Dispatcher** — Unchanged; still passes title, body, extra_data. EmailStrategy ignores title/body for template lookup.

---

## 5. API Route Definitions

### Tenant notification settings

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/platform/tenants/<id>/notification-settings` | Tenant override templates |
| PATCH | `/api/platform/tenants/<id>/notification-settings` | Body: `{ templates: [...] }` |

### Notification templates CRUD

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/platform/notification-templates` | List with filters |
| POST | `/api/platform/notification-templates` | Create template |
| PATCH | `/api/platform/notification-templates/<id>` | Update template |
| DELETE | `/api/platform/notification-templates/<id>` | Delete template |

**GET query params:** `tenant_id`, `category`, `type`, `channel`, `page`, `per_page`  
**POST body:** `type`, `channel`, `category`, `subject_template`, `body_template`, `tenant_id?`, `is_system?`

---

## 6. Panel Change Requirements (High-Level)

### Tenant detail page

1. **Notification settings section** — New card/section "Notification settings"
   - GET `/api/platform/tenants/<id>/notification-settings`
   - Display table of tenant override templates (type, channel, category)
   - Edit modal: subject_template, body_template (textarea or code editor)
   - PATCH on save

### Platform → Notification templates

2. **New page: Notification templates** — `/dashboard/notification-templates`
   - GET `/api/platform/notification-templates` with filters
   - Filters: tenant (dropdown; "Global" for null), category, type, channel
   - Table: id, tenant, type, channel, category, is_system, subject preview
   - Actions: Create, Edit, Delete
   - Create/Edit form: type, channel, category (dropdown), subject_template, body_template, tenant_id (optional)

### Categories dropdown

- Use `NOTIFICATION_CATEGORIES`: AUTH, STUDENT, PLATFORM, FINANCE, SYSTEM

### Types

- Known types: FEE_OVERDUE, FEE_DUE, PAYMENT_RECEIVED, PAYMENT_FAILED, EMAIL_VERIFICATION, PASSWORD_RESET, WELCOME, STUDENT_CREDENTIALS, ADMIN_CREDENTIALS
- Allow free-text for custom types

---

## 7. Post-Migration Steps

1. Run migration: `flask db upgrade`
2. Seed templates: `python -m scripts.seed_notification_templates`
3. Verify FEE_OVERDUE email: trigger overdue fee or inspect Celery task

---

## 8. Non-Breaking Guarantees

- Mailer module: untouched; auth, student, platform emails still use `send_template_email`
- Auth flows: unchanged
- Student creation email: unchanged
- Existing notification dispatcher callers: continue to pass title, body, extra_data; EmailStrategy resolves from templates
