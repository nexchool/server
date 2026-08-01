"""School unit routes — gr_number_scheme write coverage.

Runs against the real localhost Postgres via the ``db_session`` + ``tenant``
conftest fixtures (savepoint rollback per test). The ``auth_headers`` fixture
mirrors tests/test_departments_routes.py: a real Flask test client with a JWT
for a user holding the tenant's seeded Admin role, which carries
school_unit.manage (and manage implies read).
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
    """Bearer token + tenant header for a user holding school_unit.read/manage."""
    from modules.auth.models import User
    from modules.auth.services import generate_access_token
    from modules.rbac.models import Permission, Role, UserRole
    from modules.rbac.role_seeder import seed_roles_for_tenant

    for name, description in (
        ("school_unit.read", "View school units (campuses)"),
        ("school_unit.manage", "Manage school units (campuses)"),
    ):
        if not Permission.query.filter_by(name=name).first():
            db_session.add(Permission(name=name, description=description))
    db_session.flush()

    seed_roles_for_tenant(tenant.id)
    admin_role = Role.query.filter_by(name="Admin", tenant_id=tenant.id).first()

    user = User(
        id=f"u-{uuid.uuid4().hex[:12]}",
        tenant_id=tenant.id,
        email=f"unit-admin-{uuid.uuid4().hex[:8]}@test.school",
        name="Branch Admin",
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


def _unique_code() -> str:
    return f"BR{uuid.uuid4().hex[:6].upper()}"


def test_create_persists_gr_number_scheme(client, auth_headers):
    response = client.post(
        "/api/school-units/",
        json={
            "name": "North Campus",
            "code": _unique_code(),
            "gr_number_scheme": "NC-{SEQ}",
        },
        headers=auth_headers,
    )

    assert response.status_code == 201
    assert response.get_json()["data"]["gr_number_scheme"] == "NC-{SEQ}"


def test_update_persists_gr_number_scheme(client, auth_headers):
    created = client.post(
        "/api/school-units/",
        json={"name": "South Campus", "code": _unique_code()},
        headers=auth_headers,
    )
    unit_id = created.get_json()["data"]["id"]

    response = client.patch(
        f"/api/school-units/{unit_id}",
        json={"gr_number_scheme": "SC-{SEQ}"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["gr_number_scheme"] == "SC-{SEQ}"


def test_update_clears_gr_number_scheme_when_blank(client, auth_headers):
    created = client.post(
        "/api/school-units/",
        json={
            "name": "East Campus",
            "code": _unique_code(),
            "gr_number_scheme": "EC-{SEQ}",
        },
        headers=auth_headers,
    )
    unit_id = created.get_json()["data"]["id"]

    response = client.patch(
        f"/api/school-units/{unit_id}",
        json={"gr_number_scheme": ""},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["gr_number_scheme"] is None
