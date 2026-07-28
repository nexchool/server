"""Department routes — status codes, envelope shape, delete guard.

Runs against the real localhost Postgres via the ``db_session`` + ``tenant``
conftest fixtures (savepoint rollback per test). ``client``/``auth_headers``
mirror the pattern in tests/test_superadmin_god_login.py: a real Flask test
client hitting a JWT-bearing Authorization header, built via
modules.auth.services.generate_access_token for a user holding the seeded
Admin role (which after this task's role_seeder.py change carries
department.manage, and manage implies read).
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def auth_headers(db_session, tenant):
    """Bearer token + tenant header for a user holding department.read/manage.

    Grants via the tenant's seeded Admin role. Inserts the global Permission
    rows if this DB hasn't had scripts/seed_rbac.py run against it yet —
    same guard test_sub_admin_branches.py uses for a freshly-added permission
    — then lets seed_roles_for_tenant wire them onto the Admin role.
    """
    from modules.auth.models import User
    from modules.auth.services import generate_access_token
    from modules.rbac.models import Permission, Role, UserRole
    from modules.rbac.role_seeder import seed_roles_for_tenant

    for name, description in (
        ("department.read", "View department information"),
        ("department.manage", "Full department management access"),
    ):
        if not Permission.query.filter_by(name=name).first():
            db_session.add(Permission(name=name, description=description))
    db_session.flush()

    seed_roles_for_tenant(tenant.id)
    admin_role = Role.query.filter_by(name="Admin", tenant_id=tenant.id).first()

    user = User(
        id=f"u-{uuid.uuid4().hex[:12]}",
        tenant_id=tenant.id,
        email=f"dept-admin-{uuid.uuid4().hex[:8]}@test.school",
        name="Department Admin",
        email_verified=True,
    )
    user.set_password("Password123")
    db_session.add(user)
    db_session.flush()
    db_session.add(
        UserRole(tenant_id=tenant.id, user_id=user.id, role_id=admin_role.id)
    )
    db_session.flush()

    token = generate_access_token(user)
    return {"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant.id}


@pytest.fixture
def read_only_headers(db_session, tenant):
    """Bearer token + tenant header for a user holding ONLY department.read.

    Built directly against a private Role rather than through
    seed_roles_for_tenant, so this fixture can't accidentally also grant
    department.manage via some other seeded role's permission list — the
    whole point is proving PERM_READ alone is refused on the mutating routes.
    """
    from modules.auth.models import User
    from modules.auth.services import generate_access_token
    from modules.rbac.models import Permission, Role, RolePermission, UserRole

    perm = Permission.query.filter_by(name="department.read").first()
    if not perm:
        perm = Permission(name="department.read", description="View department information")
        db_session.add(perm)
        db_session.flush()

    role = Role(
        tenant_id=tenant.id,
        name=f"DeptReadOnly-{uuid.uuid4().hex[:6]}",
        description="test read-only role",
    )
    db_session.add(role)
    db_session.flush()
    db_session.add(
        RolePermission(tenant_id=tenant.id, role_id=role.id, permission_id=perm.id)
    )
    db_session.flush()

    user = User(
        id=f"u-{uuid.uuid4().hex[:12]}",
        tenant_id=tenant.id,
        email=f"dept-reader-{uuid.uuid4().hex[:8]}@test.school",
        name="Department Reader",
        email_verified=True,
    )
    user.set_password("Password123")
    db_session.add(user)
    db_session.flush()
    db_session.add(UserRole(tenant_id=tenant.id, user_id=user.id, role_id=role.id))
    db_session.flush()

    token = generate_access_token(user)
    return {"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant.id}


def test_create_returns_201(client, auth_headers, tenant):
    response = client.post(
        "/api/departments", json={"name": "Primary"}, headers=auth_headers
    )

    assert response.status_code == 201
    assert response.get_json()["data"]["name"] == "Primary"


def test_create_duplicate_returns_409(client, auth_headers, tenant):
    client.post("/api/departments", json={"name": "Science"}, headers=auth_headers)
    response = client.post(
        "/api/departments", json={"name": "science"}, headers=auth_headers
    )

    assert response.status_code == 409
    assert response.get_json()["error"] == "DuplicateError"


def test_create_without_name_returns_400(client, auth_headers, tenant):
    response = client.post("/api/departments", json={}, headers=auth_headers)

    assert response.status_code == 400


def test_list_returns_the_paginated_envelope(client, auth_headers, tenant):
    client.post("/api/departments", json={"name": "Primary"}, headers=auth_headers)

    payload = client.get("/api/departments", headers=auth_headers).get_json()["data"]

    assert payload["total"] == 1
    assert payload["page"] == 1
    assert payload["per_page"] == 20
    assert payload["total_pages"] == 1
    assert payload["items"][0]["name"] == "Primary"
    assert payload["items"][0]["teacher_count"] == 0
    assert payload["items"][0]["class_count"] == 0


def test_get_unknown_id_returns_404(client, auth_headers, tenant):
    response = client.get("/api/departments/does-not-exist", headers=auth_headers)

    assert response.status_code == 404


def test_patch_updates_the_department(client, auth_headers, tenant):
    created = client.post(
        "/api/departments", json={"name": "Primary"}, headers=auth_headers
    ).get_json()["data"]

    response = client.patch(
        f"/api/departments/{created['id']}",
        json={"status": "inactive"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["status"] == "inactive"


def test_delete_unreferenced_returns_204(client, auth_headers, tenant):
    created = client.post(
        "/api/departments", json={"name": "Primary"}, headers=auth_headers
    ).get_json()["data"]

    response = client.delete(f"/api/departments/{created['id']}", headers=auth_headers)

    assert response.status_code == 204


def test_delete_blocked_while_teacher_assigned_returns_409(client, db_session, auth_headers, tenant):
    from modules.auth.models import User
    from modules.teachers.models import Teacher

    created = client.post(
        "/api/departments", json={"name": "Science"}, headers=auth_headers
    ).get_json()["data"]

    teacher_user = User(
        id=f"u-{uuid.uuid4().hex[:12]}",
        tenant_id=tenant.id,
        email=f"teacher-{uuid.uuid4().hex[:8]}@test.school",
        name="Assigned Teacher",
    )
    teacher_user.set_password("Password123")
    db_session.add(teacher_user)
    db_session.flush()
    teacher = Teacher(
        tenant_id=tenant.id,
        user_id=teacher_user.id,
        employee_id=f"T-{uuid.uuid4().hex[:6]}",
        department_id=created["id"],
    )
    db_session.add(teacher)
    db_session.flush()

    response = client.delete(f"/api/departments/{created['id']}", headers=auth_headers)

    assert response.status_code == 409
    body = response.get_json()
    assert body["error"] == "DEPARTMENT_IN_USE"
    assert body["details"] == {"teachers": 1, "classes": 0}


def test_stats_returns_the_four_card_values(client, auth_headers, tenant):
    client.post("/api/departments", json={"name": "Primary"}, headers=auth_headers)

    payload = client.get("/api/departments/stats", headers=auth_headers).get_json()["data"]

    assert payload["total"] == 1
    assert payload["active"] == 1
    assert payload["teachers_assigned"] == 0
    assert payload["classes_assigned"] == 0


def test_list_requires_authentication(client, tenant):
    # Deliberately no Authorization header, but WITH X-Tenant-ID: app.py's
    # _ensure_tenant runs on every /api/* request and, with no tenant header
    # at all, falls back to whatever tenant has subdomain "default" (see
    # core/tenant.py resolve_tenant). On a dev DB that row exists, so a
    # headerless request 404s on tenant resolution before auth is ever
    # consulted — passing for the wrong reason. Pinning X-Tenant-ID to a real
    # tenant isolates the assertion to auth_required's own 401.
    response = client.get("/api/departments", headers={"X-Tenant-ID": tenant.id})
    assert response.status_code == 401


def test_create_with_read_only_permission_returns_403(client, read_only_headers, tenant):
    response = client.post(
        "/api/departments", json={"name": "Primary"}, headers=read_only_headers
    )

    assert response.status_code == 403


def test_update_with_read_only_permission_returns_403(client, auth_headers, read_only_headers, tenant):
    created = client.post(
        "/api/departments", json={"name": "Primary"}, headers=auth_headers
    ).get_json()["data"]

    response = client.patch(
        f"/api/departments/{created['id']}",
        json={"status": "inactive"},
        headers=read_only_headers,
    )

    assert response.status_code == 403


def test_delete_with_read_only_permission_returns_403(client, auth_headers, read_only_headers, tenant):
    created = client.post(
        "/api/departments", json={"name": "Primary"}, headers=auth_headers
    ).get_json()["data"]

    response = client.delete(f"/api/departments/{created['id']}", headers=read_only_headers)

    assert response.status_code == 403


def test_list_returns_403_when_class_management_feature_disabled(client, auth_headers, tenant):
    # No existing route test in this codebase exercises require_feature at
    # the HTTP layer (checked: no sibling module's route tests assert a
    # feature-disabled 403), so this test goes straight to the fixture the
    # decorator itself reads — Tenant.feature_flags — rather than inventing
    # a borrowed pattern. See core/feature_flags.py: missing keys default to
    # enabled, so flipping the key explicitly is the only way to disable it.
    tenant.feature_flags = {"class_management": False}

    response = client.get("/api/departments", headers=auth_headers)

    assert response.status_code == 403
    assert response.get_json()["error"] == "FeatureDisabled"


# ---------------------------------------------------------------------------
# _error_status — the message it maps to 500 must come FROM services.py, not
# a copy of its text living in routes.py, or a reworded message in services.py
# would silently fall through to the 400 branch (the bug a previous review
# round closed). This guards the import, not just today's string value.
# ---------------------------------------------------------------------------

def test_error_status_maps_the_services_integrity_fallback_to_500():
    from modules.departments import routes, services

    assert routes._error_status(services.INTEGRITY_FALLBACK_ERROR) == 500


def test_error_status_maps_an_unrelated_duplicate_message_to_409():
    from modules.departments import routes

    assert routes._error_status("A department with this name or code already exists") == 409


def test_error_status_maps_anything_else_to_400():
    from modules.departments import routes

    assert routes._error_status("name is required") == 400
