# Platform (Super Admin) API

This document describes the Platform Admin API used by the NextJS Super Admin panel. All routes live under `/api/platform` and require JWT auth plus `is_platform_admin=True`.

## Authentication

- Use the **existing** login endpoint (e.g. `POST /api/auth/login`) with a user that has `is_platform_admin=True`.
- Send `Authorization: Bearer <access_token>` on every platform request.
- Platform routes **bypass** tenant resolution (no `X-Tenant-ID` or subdomain required).

## Response format

All responses use the same JSON shape:

**Success**

```json
{
  "success": true,
  "data": { ... },
  "message": "Optional message"
}
```

**Error**

```json
{
  "success": false,
  "error": "ErrorType",
  "message": "Human-readable message",
  "details": { ... }
}
```

**Status codes**

- `200` – Success (GET, PATCH)
- `201` – Created (POST tenant)
- `400` – Bad request / validation
- `401` – Missing or invalid token
- `403` – Forbidden (not platform admin, or plan limit exceeded)
- `404` – Resource not found

---

## Endpoints

### GET /api/platform/dashboard

Returns aggregate stats for the platform.

**Response 200**

```json
{
  "success": true,
  "data": {
    "total_tenants": 10,
    "active_tenants": 8,
    "suspended_tenants": 2,
    "total_students": 1250,
    "total_teachers": 180,
    "revenue_monthly": 4999.00,
    "tenant_growth_by_month": [
      { "month": "2025-01-01T00:00:00", "count": 3 },
      { "month": "2025-02-01T00:00:00", "count": 5 }
    ]
  }
}
```

---

### GET /api/platform/plans

List all plans (for tenant creation form).

**Response 200**

```json
{
  "success": true,
  "data": [
    {
      "id": "uuid",
      "name": "Starter",
      "price_monthly": 0,
      "max_students": 100,
      "max_teachers": 20,
      "features_json": {}
    }
  ]
}
```

---

### POST /api/platform/tenants

Create a new tenant and its school admin user.

**Body**

```json
{
  "name": "Acme School",
  "subdomain": "acme",
  "contact_email": "contact@acme.edu",
  "phone": "+1234567890",
  "address": "Optional address",
  "plan_id": "uuid-of-plan",
  "admin_email": "admin@acme.edu",
  "admin_name": "School Admin",
  "login_url": "https://acme.school-erp.example.com/login"
}
```

Required: `name`, `subdomain`, `plan_id`, `admin_email`.

**Response 201**

```json
{
  "success": true,
  "message": "Tenant created",
  "data": {
    "tenant": {
      "id": "uuid",
      "name": "Acme School",
      "subdomain": "acme",
      "status": "active",
      "plan_id": "uuid"
    },
    "admin_user_id": "uuid"
  }
}
```

**Errors:** `400` if subdomain exists or plan not found.

---

### GET /api/platform/tenants

Paginated list of tenants.

**Query:** `page`, `per_page`, `status` (optional: `active` | `suspended`).

**Response 200**

```json
{
  "success": true,
  "data": {
    "items": [
      {
        "id": "uuid",
        "name": "Acme School",
        "subdomain": "acme",
        "contact_email": "contact@acme.edu",
        "status": "active",
        "plan_id": "uuid",
        "plan_name": "Starter",
        "student_count": 50,
        "teacher_count": 10,
        "created_at": "2025-02-18T12:00:00"
      }
    ],
    "pagination": {
      "page": 1,
      "per_page": 20,
      "total": 10,
      "pages": 1
    }
  }
}
```

---

### PATCH /api/platform/tenants/:id/suspend

Set tenant status to `suspended`.

**Response 200**

```json
{
  "success": true,
  "message": "Tenant suspended",
  "data": { "id": "uuid", "status": "suspended" }
}
```

---

### PATCH /api/platform/tenants/:id/activate

Set tenant status to `active`.

**Response 200**

```json
{
  "success": true,
  "message": "Tenant activated",
  "data": { "id": "uuid", "status": "active" }
}
```

---

### PATCH /api/platform/tenants/:id/change-plan

**Body:** `{ "plan_id": "uuid" }`

**Response 200**

```json
{
  "success": true,
  "message": "Plan updated",
  "data": { "id": "tenant-uuid", "plan_id": "new-plan-uuid" }
}
```

---

### POST /api/platform/tenants/:id/reset-admin

Generate new password for school admin, set `force_password_reset=true`, send email.

**Response 200**

```json
{
  "success": true,
  "message": "Password reset and email sent"
}
```

**Errors:** `404` if tenant or school admin not found.

---

## Refactoring notes

- **Tenant middleware:** Unchanged. Only addition: paths under `/api/platform/` skip tenant resolution in `app.py` so platform routes never set `g.tenant_id`.
- **Platform routes** never use `@tenant_required`; they use `@auth_required` and `@platform_admin_required` only. Any tenant-scoped operation (e.g. list students for a tenant) must pass `tenant_id` explicitly in the URL or body.
- **Plan enforcement** is implemented in `modules/students/services.py` and `modules/teachers/services.py`. Creating a student/teacher checks the tenant’s plan `max_students` / `max_teachers`; if exceeded, the service returns an error and the route returns **403** with a message. Enforcement cannot be bypassed because it lives in the service layer.
- **Audit logs** are written only for: tenant created, tenant suspended, tenant activated, plan changed, school admin reset. Implemented in `modules/platform/audit.py` and called from platform services.
- **First platform admin:** After migration, set `is_platform_admin = true` for a user (e.g. via SQL or a one-off script). That user can then use the existing login and call platform APIs.
- **Plans:** Migration `003_platform_admin_plans_audit` creates the `plans` table and inserts one default plan (“Starter”). Add more plans via SQL or a future plan management API.
