"""The admin dashboard answers to a permission, not merely to a login.

`GET /api/dashboard` aggregates the whole school in one payload — headcounts,
today's attendance, alerts, **the finance position** (expected, collected,
outstanding, overdue) and transport. It carried `@tenant_required` and
`@auth_required` and nothing else, so every account that could log in could
read the school's money: a pupil's account, or a household sharing one
(ADR-011).

`build_dashboard()` contains no authorization of its own — only tenant and
feature gates — so the route decorator is the only place this can be said.
"""

from __future__ import annotations

import uuid

import pytest

DASHBOARD_PATH = "/api/dashboard/"


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _account_with(db_session, tenant, *permission_keys, name="Staff"):
    """An employed account holding exactly the permissions named."""
    from modules.auth.models import User
    from modules.auth.services import generate_access_token
    from modules.rbac.models import Permission, Role, RolePermission
    from tests.conftest import grant_profile_to

    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=f"u-{suffix}", tenant_id=tenant.id, email=f"{suffix}@test.school",
        password_hash="x" * 60, name=name,
    )
    db_session.add(user)
    db_session.flush()

    role = Role(id=f"r-{suffix}", tenant_id=tenant.id, name=f"Role-{suffix}")
    db_session.add(role)
    db_session.flush()
    for key in permission_keys:
        permission = Permission.query.filter_by(name=key).first()
        if permission is None:
            permission = Permission(id=_new_id("perm-"), name=key)
            db_session.add(permission)
            db_session.flush()
        db_session.add(RolePermission(
            tenant_id=tenant.id, role_id=role.id, permission_id=permission.id
        ))
    db_session.flush()
    grant_profile_to(user, role.id, employee_number=f"EMP-{suffix}")
    return user, generate_access_token(user)


def _get_dashboard(client, tenant, token):
    return client.get(DASHBOARD_PATH, headers={
        "X-Tenant-Subdomain": tenant.subdomain,
        "Authorization": f"Bearer {token}",
    })


@pytest.fixture(autouse=True)
def _cheap_dashboard(monkeypatch):
    """These tests are about who may ask, not about what the answer contains."""
    from modules.dashboard import service

    monkeypatch.setattr(
        service, "build_dashboard",
        lambda: {"overview": {"students": 1}, "finance": {"outstanding": 42}},
    )


def test_an_account_without_the_permission_is_refused(client, db_session, tenant):
    """A pupil's login must not return the school's finance position."""
    _user, token = _account_with(
        db_session, tenant, "student.read.self", name="A Pupil"
    )

    response = _get_dashboard(client, tenant, token)

    assert response.status_code == 403, response.get_json()
    assert b"outstanding" not in response.data


def test_the_permission_grants_access(client, db_session, tenant):
    _user, token = _account_with(db_session, tenant, "dashboard.read", name="Principal")

    response = _get_dashboard(client, tenant, token)

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["data"]["finance"]["outstanding"] == 42


def test_manage_implies_read(client, db_session, tenant):
    """`<resource>.manage` covers every key under it — the rule used everywhere."""
    _user, token = _account_with(db_session, tenant, "dashboard.manage")

    assert _get_dashboard(client, tenant, token).status_code == 200


def test_an_anonymous_request_is_refused(client, tenant):
    response = client.get(
        DASHBOARD_PATH, headers={"X-Tenant-Subdomain": tenant.subdomain}
    )
    assert response.status_code in (401, 403)


def test_the_school_admin_role_ships_with_the_permission():
    """A school's own Admin must not lose its dashboard when this lands.

    The seed is additions-only and runs on boot, so the grant reaches every
    existing tenant — but only if the catalogue actually carries it.
    """
    from modules.rbac.catalog import DEFAULT_ROLES, PERMISSIONS

    assert any(name == "dashboard.read" for name, _desc in PERMISSIONS)
    assert "dashboard.read" in DEFAULT_ROLES["Admin"]["permissions"]
    for role in ("Teacher", "Student", "Parent"):
        assert "dashboard.read" not in DEFAULT_ROLES[role]["permissions"], (
            f"{role} must not read the school-wide dashboard"
        )
