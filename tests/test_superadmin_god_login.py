"""Tests for platform super-admin god-login + role/setup flags.

Covers:
- Platform admin logs into any tenant with their own creds (god-login) -> 200.
- Normal tenant user still logs in unchanged; email collision keeps tenant user.
- Wrong password for the platform admin -> InvalidCredentials.
- has_permission god-mode for platform admins.
- require_setup_complete bypass for platform admins.
- login + profile expose is_platform_admin / is_subadmin / is_setup_complete.
- Freshly-seeded Admin lacks school_setup.manage (gets 403) while platform admin passes.

These run against the localhost Postgres bound to the savepoint connection in
conftest (changes rolled back per test).
"""

from __future__ import annotations

import uuid

import pytest
from flask import g

from core.database import db
from core.decorators.rbac import require_permission
from core.decorators.setup import require_setup_complete
from core.models import Tenant, TENANT_STATUS_ACTIVE, BILLING_CYCLE_YEARLY
from modules.auth.models import User
from modules.rbac.models import Role, UserRole
from modules.rbac.role_seeder import seed_roles_for_tenant
from modules.rbac.services import has_permission, is_subadmin_user


PASSWORD = "Sup3rSecret1"
ADMIN_PASSWORD = "Adm1nPass99"


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
def _disable_rate_limit(flask_app):
    """5/min login limiter would 429 multiple logins in one test run."""
    from core.extensions import limiter

    previous = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = previous


@pytest.fixture
def setup_tenant(db_session):
    """An active tenant whose school setup is NOT complete."""
    t = Tenant(
        id=_new_id("t-"),
        name="Test School",
        subdomain=f"god-{uuid.uuid4().hex[:6]}",
        status=TENANT_STATUS_ACTIVE,
        billing_cycle=BILLING_CYCLE_YEARLY,
        is_setup_complete=False,
    )
    db_session.add(t)
    db_session.flush()
    return t


@pytest.fixture
def platform_home_tenant(db_session):
    """The platform admin's own home tenant (distinct from the entered tenant)."""
    t = Tenant(
        id=_new_id("t-"),
        name="Platform HQ",
        subdomain=f"hq-{uuid.uuid4().hex[:6]}",
        status=TENANT_STATUS_ACTIVE,
        billing_cycle=BILLING_CYCLE_YEARLY,
        is_setup_complete=True,
    )
    db_session.add(t)
    db_session.flush()
    return t


@pytest.fixture
def platform_admin(db_session, platform_home_tenant):
    """A platform super-admin user whose home tenant is NOT the entered tenant."""
    u = User(
        id=_new_id("pa-"),
        tenant_id=platform_home_tenant.id,
        email=f"super-{uuid.uuid4().hex[:6]}@platform.test",
        name="Super Admin",
        is_platform_admin=True,
        email_verified=True,
    )
    u.set_password(PASSWORD)
    db_session.add(u)
    db_session.flush()
    return u


def _seed_admin_role(db_session, tenant):
    seed_roles_for_tenant(tenant.id)
    return Role.query.filter_by(name="Admin", tenant_id=tenant.id).first()


@pytest.fixture
def tenant_admin(db_session, setup_tenant):
    """A normal Admin user inside setup_tenant with the seeded Admin role."""
    admin_role = _seed_admin_role(db_session, setup_tenant)
    u = User(
        id=_new_id("ta-"),
        tenant_id=setup_tenant.id,
        email=f"admin-{uuid.uuid4().hex[:6]}@school.test",
        name="School Admin",
        email_verified=True,
    )
    u.set_password(ADMIN_PASSWORD)
    db_session.add(u)
    db_session.flush()
    db_session.add(
        UserRole(tenant_id=setup_tenant.id, user_id=u.id, role_id=admin_role.id)
    )
    db_session.flush()
    return u


@pytest.fixture
def sub_admin(db_session, setup_tenant):
    """A sub-admin user attached to an is_subadmin role in setup_tenant."""
    role = Role(
        id=_new_id("r-"),
        tenant_id=setup_tenant.id,
        name=f"subadmin:{uuid.uuid4().hex[:8]}",
        description="Private sub-admin role",
        is_subadmin=True,
    )
    db_session.add(role)
    db_session.flush()
    u = User(
        id=_new_id("sa-"),
        tenant_id=setup_tenant.id,
        email=f"sub-{uuid.uuid4().hex[:6]}@school.test",
        name="Sub Admin",
        email_verified=True,
    )
    u.set_password(ADMIN_PASSWORD)
    db_session.add(u)
    db_session.flush()
    db_session.add(
        UserRole(tenant_id=setup_tenant.id, user_id=u.id, role_id=role.id)
    )
    db_session.flush()
    return u


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _login(client, email, password, tenant_id):
    return client.post(
        "/api/auth/login",
        json={"email": email, "password": password, "tenant_id": tenant_id},
    )


# ---------------------------------------------------------------------------
# God-login
# ---------------------------------------------------------------------------

def test_platform_admin_god_login_into_tenant(client, db_session, setup_tenant, platform_admin):
    resp = _login(client, platform_admin.email, PASSWORD, setup_tenant.id)
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()["data"]
    assert body["is_platform_admin"] is True
    assert body["permissions"] == ["system.manage"]
    assert body["tenant_id"] == str(setup_tenant.id)
    assert body["subdomain"] == setup_tenant.subdomain
    assert body["enabled_features"] == []
    assert body["is_subadmin"] is False
    assert body["is_setup_complete"] is False
    assert body.get("access_token")
    assert body.get("refresh_token")


def test_god_login_is_audited(client, db_session, setup_tenant, platform_admin):
    from core.models import AuditLog

    _login(client, platform_admin.email, PASSWORD, setup_tenant.id)
    entry = (
        AuditLog.query.filter_by(
            action="tenant.admin_web_entered",
            platform_admin_id=platform_admin.id,
            tenant_id=setup_tenant.id,
        ).first()
    )
    assert entry is not None
    assert entry.extra_data == {"subdomain": setup_tenant.subdomain}


def test_platform_admin_wrong_password_no_god_access(client, db_session, setup_tenant, platform_admin):
    resp = _login(client, platform_admin.email, "wrong-password", setup_tenant.id)
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "InvalidCredentials"


# ---------------------------------------------------------------------------
# Precedence: normal user is not shadowed by god-login
# ---------------------------------------------------------------------------

def test_normal_admin_login_unchanged(client, db_session, setup_tenant, tenant_admin):
    resp = _login(client, tenant_admin.email, ADMIN_PASSWORD, setup_tenant.id)
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()["data"]
    assert body["is_platform_admin"] is False
    assert "system.manage" not in body["permissions"]
    assert body["permissions"]  # non-empty real permissions
    assert body["tenant_id"] == str(setup_tenant.id)


def test_email_collision_tenant_user_wins(client, db_session, setup_tenant, platform_admin):
    """A tenant user sharing the platform admin's email authenticates as
    themselves (god-login does not shadow them)."""
    admin_role = _seed_admin_role(db_session, setup_tenant)
    collision = User(
        id=_new_id("col-"),
        tenant_id=setup_tenant.id,
        email=platform_admin.email,  # same email, different tenant row
        name="Real Tenant User",
        email_verified=True,
    )
    collision.set_password(ADMIN_PASSWORD)
    db_session.add(collision)
    db_session.flush()
    db_session.add(
        UserRole(tenant_id=setup_tenant.id, user_id=collision.id, role_id=admin_role.id)
    )
    db_session.flush()

    # Logging in with the TENANT user's password authenticates the tenant user.
    resp = _login(client, platform_admin.email, ADMIN_PASSWORD, setup_tenant.id)
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()["data"]
    assert body["is_platform_admin"] is False
    assert body["user"]["id"] == collision.id


# ---------------------------------------------------------------------------
# Authorization god-mode
# ---------------------------------------------------------------------------

def test_has_permission_god_mode(db_session, setup_tenant, platform_admin, tenant_admin):
    assert has_permission(platform_admin.id, "anything.manage") is True
    assert has_permission(platform_admin.id, "school_setup.manage") is True
    # Normal admin lacks school_setup.manage after the seeder change.
    assert has_permission(tenant_admin.id, "school_setup.manage") is False
    # but has a real granted permission.
    assert has_permission(tenant_admin.id, "student.manage") is True


def test_is_subadmin_user(db_session, setup_tenant, sub_admin, tenant_admin):
    assert is_subadmin_user(sub_admin.id, setup_tenant.id) is True
    assert is_subadmin_user(tenant_admin.id, setup_tenant.id) is False


# ---------------------------------------------------------------------------
# require_setup_complete bypass
# ---------------------------------------------------------------------------

def _wrap_setup_route():
    @require_setup_complete
    def _view():
        return ("ok", 200)

    return _view


def test_require_setup_complete_bypassed_for_platform_admin(flask_app, db_session, setup_tenant, platform_admin):
    view = _wrap_setup_route()
    with flask_app.test_request_context("/"):
        g.tenant_id = setup_tenant.id
        g.current_user = platform_admin
        result = view()
    assert result == ("ok", 200)


def test_require_setup_complete_blocks_normal_user_when_incomplete(flask_app, db_session, setup_tenant, tenant_admin):
    view = _wrap_setup_route()
    with flask_app.test_request_context("/"):
        g.tenant_id = setup_tenant.id
        g.current_user = tenant_admin
        body, status = view()
    assert status == 403
    assert body.get_json()["error"] == "SetupIncomplete"


# ---------------------------------------------------------------------------
# require_permission('school_setup.manage') route-level
# ---------------------------------------------------------------------------

def _wrap_permission_route():
    @require_permission("school_setup.manage")
    def _view():
        return ("granted", 200)

    return _view


def test_seeded_admin_denied_school_setup_manage(flask_app, db_session, setup_tenant, tenant_admin):
    view = _wrap_permission_route()
    with flask_app.test_request_context("/"):
        g.current_user = tenant_admin
        body, status = view()
    assert status == 403


def test_platform_admin_passes_school_setup_manage(flask_app, db_session, setup_tenant, platform_admin):
    view = _wrap_permission_route()
    with flask_app.test_request_context("/"):
        g.current_user = platform_admin
        result = view()
    assert result == ("granted", 200)


# ---------------------------------------------------------------------------
# Profile flags
# ---------------------------------------------------------------------------

def _profile(client, user, tenant_id):
    """Hit GET /profile with a freshly minted access token for `user`."""
    from modules.auth.services import generate_access_token

    token = generate_access_token(user)
    return client.get(
        "/api/auth/profile",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Tenant-ID": str(tenant_id),
        },
    )


def test_profile_flags_platform_admin(client, db_session, setup_tenant, platform_admin):
    resp = _profile(client, platform_admin, setup_tenant.id)
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()["data"]
    assert body["is_platform_admin"] is True
    assert body["permissions"] == ["system.manage"]
    assert body["is_subadmin"] is False
    assert body["is_setup_complete"] is False


def test_profile_flags_normal_admin(client, db_session, setup_tenant, tenant_admin):
    resp = _profile(client, tenant_admin, setup_tenant.id)
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()["data"]
    assert body["is_platform_admin"] is False
    assert body["is_subadmin"] is False
    assert body["is_setup_complete"] is False


def test_profile_flags_sub_admin(client, db_session, setup_tenant, sub_admin):
    resp = _profile(client, sub_admin, setup_tenant.id)
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()["data"]
    assert body["is_platform_admin"] is False
    assert body["is_subadmin"] is True
