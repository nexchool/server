# Multi-Tenant SaaS Implementation

## Summary

The School ERP has been converted from single-tenant to multi-tenant. All business data is scoped by `tenant_id`. Tenant is resolved per request via subdomain or `X-Tenant-ID` header.

## 1. Tenant Model (`server/core/models.py`)

- **Tenant** table: `id` (UUID), `name`, `subdomain` (unique), `contact_email`, `phone`, `address`, `plan_id` (nullable), `status` (active/suspended), `created_at`, `updated_at`.
- **TenantBaseModel**: Abstract base with `tenant_id` (FK → `tenants.id`, NOT NULL, indexed). All tenant-scoped models inherit from it.

## 2. Models Updated with `tenant_id`

All of these inherit `TenantBaseModel` and have `tenant_id`:

- `users`, `sessions`, `roles`, `user_roles`, `role_permissions`
- `students`, `teachers`, `classes`, `class_teachers`, `attendance`

**Note:** `permissions` table is global (no `tenant_id`); only role–permission assignments are per-tenant.

## 3. Tenant-Scoped Unique Constraints

| Table        | Old unique              | New unique                          |
|-------------|--------------------------|-------------------------------------|
| users       | `email`                  | `(email, tenant_id)`                |
| roles       | `name`                   | `(name, tenant_id)`                 |
| students    | `admission_number`, `user_id` | `(admission_number, tenant_id)`, `(user_id, tenant_id)` |
| teachers    | `employee_id`, `user_id` | `(employee_id, tenant_id)`, `(user_id, tenant_id)` |
| classes     | `(name, section, academic_year)` | `(name, section, academic_year, tenant_id)` |
| class_teachers | `(class_id, teacher_id)` | `(class_id, teacher_id, tenant_id)` |
| attendance  | `(date, class_id, student_id)` | `(date, class_id, student_id, tenant_id)` |
| user_roles  | `(user_id, role_id)`     | `(user_id, role_id, tenant_id)`      |
| role_permissions | `(role_id, permission_id)` | `(role_id, permission_id, tenant_id)` |

## 4. Tenant Resolution Middleware (`server/core/tenant.py`)

- **Resolution order:** Header `X-Tenant-ID` (UUID) → then subdomain from `Host` (e.g. `acme.school-erp.example.com` → subdomain `acme`).
- For single-part host (e.g. `localhost`), a tenant with `subdomain='default'` is used if present.
- Sets `g.tenant_id` and `g.tenant`; returns **404** if tenant not found, **403** if tenant is suspended.
- Registered in `app.py` as `before_request` for all `/api/*` except `/api/health` and `/api`.

## 5. Automatic Tenant Filtering (No Cross-Tenant Leakage)

- In `server/core/database.py`, a SQLAlchemy `before_compile` event is registered on `Query`.
- For models with `__tenant_scoped__ = True` (i.e. inheriting `TenantBaseModel`), every query automatically adds `tenant_id == g.tenant_id` when inside a request that has set `g.tenant_id`.
- Reads are always tenant-scoped; writes must set `tenant_id` when creating rows (e.g. from `get_tenant_id()`).

## 6. Decorator `@tenant_required`

- In `server/core/tenant.py` and re-exported from `server/core/decorators`.
- Ensures `g.tenant_id` is set (calls `resolve_tenant()` if not). Use on routes that must run in a tenant context.

Example:

```python
from core.decorators import tenant_required, auth_required

@bp.route('/students')
@tenant_required
@auth_required
def list_students():
    ...
```

## 7. Migration

- **File:** `server/migrations/versions/002_multi_tenant.py`
- **Steps:** Creates `tenants` table → inserts default tenant (`subdomain='default'`) → adds `tenant_id` to all business tables (nullable, then backfill, then NOT NULL + FK) → drops old uniques and creates tenant-scoped uniques.

**Run migrations:**

```bash
export FLASK_APP=app:app
flask db upgrade
```

## 8. Example: Students Module

- **Create student:** Uses `get_tenant_id()`; validates tenant; sets `user.tenant_id` and `student.tenant_id`; uses `User.get_user_by_email(email, tenant_id=tenant_id)` for uniqueness.
- **List/get students:** Uses `Student.query` and `Class.query`; both are automatically filtered by `g.tenant_id` via the query event, so no explicit `filter_by(tenant_id=...)` is needed in read paths.
- **Writes:** Every create (User, Student, Class, etc.) sets `tenant_id` from `get_tenant_id()` or from a related entity (e.g. `ClassTeacher.tenant_id` from `Class.tenant_id`).

## 9. Module-by-module tenant support

All API modules enforce tenant context and scope data by tenant:

| Module      | Tenant usage |
|------------|--------------|
| **Auth**   | Register/login/validate/forgot/reset use `get_tenant_id()`; `User.get_user_by_email(email, tenant_id=...)`; new users and sessions get `tenant_id`. All auth routes use `@tenant_required`. |
| **Users**  | `list_users(tenant_id=...)` and `get_user_by_email(email, tenant_id=...)`; all user routes use `@tenant_required`. Reads are auto-scoped via query filter. |
| **RBAC**   | `create_role` sets `tenant_id`; `UserRole` and `RolePermission` created with `tenant_id` (from user/role). All RBAC routes use `@tenant_required`. Role/permission lookups are auto-scoped. |
| **Classes**| `create_class` and `assign_teacher_to_class` set `tenant_id`. All class routes use `@tenant_required`. Queries auto-scoped. |
| **Students** | Create/update use `get_tenant_id()` and set `tenant_id` on User/Student. All student routes use `@tenant_required`. Queries auto-scoped. |
| **Teachers** | Create sets `tenant_id` on User/Teacher; `User.get_user_by_email(..., tenant_id=...)`. All teacher routes use `@tenant_required`. Queries auto-scoped. |
| **Attendance** | Mark attendance sets `tenant_id` on `Attendance` via `get_tenant_id()`. All attendance routes use `@tenant_required`. Queries auto-scoped. |

## 10. Scripts and Default Tenant

- After migration, all existing rows are backfilled with the default tenant ID (`00000000-0000-0000-0000-000000000001`), subdomain `default`.
- Scripts that create users/roles (e.g. `create_admin`, `seed_rbac`) run outside a request. They should either:
  - Run inside a request context with `g.tenant_id` set (e.g. to the default tenant), or
  - Be updated to resolve the default tenant and pass `tenant_id` explicitly when creating User/Role/UserRole.

## 11. API Usage

- **By subdomain:** e.g. `https://acme.school-erp.example.com/api/auth/login`
- **By header:** e.g. `X-Tenant-ID: <tenant-uuid>` for any host (useful for mobile or non-subdomain setups).

Health and API root do not require a tenant: `/api/health`, `/api`.
