"""Backend tests for the tenant-scoped Sub-Admins module (T3).

Exercises the service layer against the real localhost Postgres (via the
``db_session`` + ``tenant`` conftest fixtures) so RBAC joins, unique
constraints and the ``has_permission`` hierarchy behave exactly as in prod.
The notification dispatcher is mocked everywhere so no real email is sent.

Covered:
- create happy path (user + private is_subadmin role + correct perms + email)
- permission expansion correctness via rbac.has_permission (students delete
  toggle, finance operate excludes manage/refund)
- list scoping (only sub-admins, excludes soft-deleted, includes status)
- edit re-syncs permissions (add + remove)
- suspend/restore + session revocation
- reset-password (old fails / new works) + session revocation + email
- soft delete hides the user from lookup + list
- duplicate email (incl. soft-deleted) -> 409
- password < 8 -> 422
- self-action guards -> 400
- authorization: the seeded Admin role carries subadmin.manage; a bare
  sub-admin does not (service-level proxy for the route guard)
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def seeded_tenant(db_session, tenant):
    """Tenant with default roles (Admin/Teacher/...) seeded for RBAC joins.

    Ensures the global ``subadmin.manage`` permission row exists first so the
    seeder can attach it to the Admin role regardless of whether ``seed_rbac``
    has been re-run against this local database.
    """
    from modules.rbac.models import Permission
    from modules.rbac.role_seeder import seed_roles_for_tenant

    if not Permission.query.filter_by(name="subadmin.manage").first():
        db_session.add(
            Permission(name="subadmin.manage", description="Manage sub-admins")
        )
        db_session.flush()

    seed_roles_for_tenant(tenant.id)
    return tenant


@pytest.fixture
def mock_dispatch():
    """Patch the notification dispatcher used inside the service module."""
    with patch("modules.notifications.services.notification_dispatcher") as md:
        md.dispatch.return_value = {"email": True}
        yield md


def _email() -> str:
    return f"sa-{uuid.uuid4().hex[:10]}@test.school"


def _create(tenant, **overrides):
    """Call create_sub_admin with sensible defaults."""
    from modules.sub_admins.services import create_sub_admin

    payload = {
        "tenant_id": tenant.id,
        "tenant_name": tenant.name,
        "name": "Finance Admin",
        "email": _email(),
        "password": "password123",
        "modules": [{"key": "finance", "level": "operate"}],
    }
    payload.update(overrides)
    return create_sub_admin(**payload)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def test_create_happy_path(db_session, seeded_tenant, mock_dispatch):
    from modules.auth.models import User
    from modules.rbac.models import Role, UserRole

    email = _email()
    result = _create(seeded_tenant, email=email)
    assert result["success"], result

    user = User.get_user_by_email(email, tenant_id=seeded_tenant.id)
    assert user is not None
    assert user.email_verified is True
    assert user.force_password_reset is False  # no forced first-login change

    # Private is_subadmin role linked via UserRole
    ur = UserRole.query.filter_by(user_id=user.id, tenant_id=seeded_tenant.id).first()
    assert ur is not None
    role = Role.query.get(ur.role_id)
    assert role.is_subadmin is True
    assert role.name == f"subadmin:{user.id}"

    # Email dispatch attempted with ADMIN_CREDENTIALS
    assert mock_dispatch.dispatch.called
    kwargs = mock_dispatch.dispatch.call_args.kwargs
    assert kwargs["notification_type"] == "ADMIN_CREDENTIALS"


def test_create_password_too_short_rejected(db_session, seeded_tenant, mock_dispatch):
    result = _create(seeded_tenant, password="short")
    assert result["success"] is False
    assert result["status_code"] == 422


def test_create_requires_at_least_one_module(db_session, seeded_tenant, mock_dispatch):
    result = _create(seeded_tenant, modules=[{"key": "finance", "level": "none"}])
    assert result["success"] is False
    assert result["status_code"] == 422


def test_create_duplicate_email_active_returns_409(db_session, seeded_tenant, mock_dispatch):
    email = _email()
    assert _create(seeded_tenant, email=email)["success"]
    dup = _create(seeded_tenant, email=email)
    assert dup["success"] is False
    assert dup["status_code"] == 409


def test_create_duplicate_email_soft_deleted_returns_409(db_session, seeded_tenant, mock_dispatch):
    from modules.auth.models import User

    email = _email()
    created = _create(seeded_tenant, email=email)
    assert created["success"]

    user = User.get_user_by_email(email, tenant_id=seeded_tenant.id)
    user.deleted_at = datetime.utcnow()
    db_session.flush()

    dup = _create(seeded_tenant, email=email)
    assert dup["success"] is False
    assert dup["status_code"] == 409


# ---------------------------------------------------------------------------
# Permission expansion correctness (via rbac.has_permission)
# ---------------------------------------------------------------------------

def test_students_edit_excludes_delete_toggle_on_grants_it(db_session, seeded_tenant, mock_dispatch):
    from modules.auth.models import User
    from modules.rbac.services import has_permission

    # Edit only: create + update, NOT delete
    email = _email()
    _create(
        seeded_tenant,
        email=email,
        modules=[{"key": "students", "level": "edit"}],
    )
    user = User.get_user_by_email(email, tenant_id=seeded_tenant.id)
    assert has_permission(user.id, "student.create") is True
    assert has_permission(user.id, "student.update") is True
    assert has_permission(user.id, "student.delete") is False

    # With delete toggle on
    email2 = _email()
    _create(
        seeded_tenant,
        email=email2,
        modules=[{"key": "students", "level": "edit", "delete": True}],
    )
    user2 = User.get_user_by_email(email2, tenant_id=seeded_tenant.id)
    assert has_permission(user2.id, "student.delete") is True


def test_finance_operate_excludes_manage_and_refund(db_session, seeded_tenant, mock_dispatch):
    from modules.auth.models import User
    from modules.rbac.services import has_permission

    email = _email()
    _create(seeded_tenant, email=email, modules=[{"key": "finance", "level": "operate"}])
    user = User.get_user_by_email(email, tenant_id=seeded_tenant.id)

    assert has_permission(user.id, "finance.collect") is True
    assert has_permission(user.id, "fees.payment.record") is True
    # refund not granted, and no finance.manage means delete-equivalent is off
    assert has_permission(user.id, "finance.refund") is False
    assert has_permission(user.id, "finance.manage") is False


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

def test_list_returns_only_sub_admins_excludes_deleted(db_session, seeded_tenant, mock_dispatch):
    from modules.auth.models import User
    from modules.sub_admins.services import list_sub_admins

    # A sub-admin
    sa_email = _email()
    _create(seeded_tenant, email=sa_email)

    # A plain (non-sub-admin) user — must NOT appear
    plain = User(
        id=f"u-{uuid.uuid4().hex[:12]}",
        tenant_id=seeded_tenant.id,
        email=_email(),
        password_hash="x" * 60,
        name="Plain User",
    )
    db_session.add(plain)
    db_session.flush()

    listed = list_sub_admins(seeded_tenant.id)
    emails = {item["email"] for item in listed["items"]}
    assert sa_email in emails
    assert plain.email not in emails
    # status present
    sa_item = next(i for i in listed["items"] if i["email"] == sa_email)
    assert sa_item["status"] == "active"
    assert sa_item["modules"]  # module summary populated

    # Soft-delete the sub-admin -> excluded
    user = User.get_user_by_email(sa_email, tenant_id=seeded_tenant.id)
    user.deleted_at = datetime.utcnow()
    db_session.flush()
    listed2 = list_sub_admins(seeded_tenant.id)
    assert sa_email not in {i["email"] for i in listed2["items"]}


# ---------------------------------------------------------------------------
# Edit
# ---------------------------------------------------------------------------

def test_edit_resyncs_permissions(db_session, seeded_tenant, mock_dispatch):
    from modules.auth.models import User
    from modules.rbac.services import has_permission
    from modules.sub_admins.services import update_sub_admin

    email = _email()
    _create(seeded_tenant, email=email, modules=[{"key": "finance", "level": "operate"}])
    user = User.get_user_by_email(email, tenant_id=seeded_tenant.id)
    assert has_permission(user.id, "finance.collect") is True
    assert has_permission(user.id, "class.read") is False

    # Switch to classes manage, drop finance
    res = update_sub_admin(
        seeded_tenant.id,
        user.id,
        modules=[{"key": "classes", "level": "manage"}],
    )
    assert res["success"], res
    assert has_permission(user.id, "class.manage") is True
    # finance perms removed
    assert has_permission(user.id, "finance.collect") is False


# ---------------------------------------------------------------------------
# Suspend / restore
# ---------------------------------------------------------------------------

def test_suspend_then_restore_revokes_sessions(db_session, seeded_tenant, mock_dispatch):
    from modules.auth.models import Session, User
    from modules.sub_admins.services import restore_sub_admin, suspend_sub_admin

    email = _email()
    _create(seeded_tenant, email=email)
    user = User.get_user_by_email(email, tenant_id=seeded_tenant.id)

    sess = Session(
        id=f"s-{uuid.uuid4().hex[:12]}",
        tenant_id=seeded_tenant.id,
        user_id=user.id,
        refresh_token="tok",
    )
    db_session.add(sess)
    db_session.flush()

    res = suspend_sub_admin(seeded_tenant.id, user.id, actor_id="someone-else")
    assert res["success"], res
    db_session.refresh(user)
    db_session.refresh(sess)
    assert user.is_suspended is True
    assert sess.revoked is True

    res2 = restore_sub_admin(seeded_tenant.id, user.id)
    assert res2["success"]
    db_session.refresh(user)
    assert user.is_suspended is False


def test_suspend_self_is_blocked(db_session, seeded_tenant, mock_dispatch):
    from modules.auth.models import User
    from modules.sub_admins.services import suspend_sub_admin

    email = _email()
    _create(seeded_tenant, email=email)
    user = User.get_user_by_email(email, tenant_id=seeded_tenant.id)

    res = suspend_sub_admin(seeded_tenant.id, user.id, actor_id=user.id)
    assert res["success"] is False
    assert res["status_code"] == 400


# ---------------------------------------------------------------------------
# Reset password
# ---------------------------------------------------------------------------

def test_reset_password_changes_and_revokes(db_session, seeded_tenant, mock_dispatch):
    from modules.auth.models import Session, User
    from modules.auth.services import authenticate_user
    from modules.sub_admins.services import reset_sub_admin_password

    email = _email()
    _create(seeded_tenant, email=email, password="oldpassword1")
    user = User.get_user_by_email(email, tenant_id=seeded_tenant.id)

    sess = Session(
        id=f"s-{uuid.uuid4().hex[:12]}",
        tenant_id=seeded_tenant.id,
        user_id=user.id,
        refresh_token="tok",
    )
    db_session.add(sess)
    db_session.flush()

    res = reset_sub_admin_password(
        tenant_id=seeded_tenant.id,
        tenant_name=seeded_tenant.name,
        user_id=user.id,
        actor_id="someone-else",
        password="newpassword2",
    )
    assert res["success"], res

    db_session.refresh(sess)
    assert sess.revoked is True
    # Old password fails, new works
    assert authenticate_user(email, "oldpassword1", tenant_id=seeded_tenant.id) is None
    assert authenticate_user(email, "newpassword2", tenant_id=seeded_tenant.id) is not None

    # Email dispatch attempted with ADMIN_PASSWORD_RESET
    types = [c.kwargs.get("notification_type") for c in mock_dispatch.dispatch.call_args_list]
    assert "ADMIN_PASSWORD_RESET" in types


def test_reset_password_too_short_rejected(db_session, seeded_tenant, mock_dispatch):
    from modules.auth.models import User
    from modules.sub_admins.services import reset_sub_admin_password

    email = _email()
    _create(seeded_tenant, email=email)
    user = User.get_user_by_email(email, tenant_id=seeded_tenant.id)

    res = reset_sub_admin_password(
        tenant_id=seeded_tenant.id,
        tenant_name=seeded_tenant.name,
        user_id=user.id,
        actor_id="someone-else",
        password="short",
    )
    assert res["success"] is False
    assert res["status_code"] == 422


# ---------------------------------------------------------------------------
# Soft delete
# ---------------------------------------------------------------------------

def test_soft_delete_hides_user(db_session, seeded_tenant, mock_dispatch):
    from modules.auth.models import User
    from modules.sub_admins.services import delete_sub_admin, list_sub_admins

    email = _email()
    _create(seeded_tenant, email=email)
    user = User.get_user_by_email(email, tenant_id=seeded_tenant.id)

    res = delete_sub_admin(seeded_tenant.id, user.id, actor_id="someone-else")
    assert res["success"], res

    # Default lookup (login path) now returns None
    assert User.get_user_by_email(email, tenant_id=seeded_tenant.id) is None
    # Excluded from list
    assert email not in {i["email"] for i in list_sub_admins(seeded_tenant.id)["items"]}


def test_delete_self_is_blocked(db_session, seeded_tenant, mock_dispatch):
    from modules.auth.models import User
    from modules.sub_admins.services import delete_sub_admin

    email = _email()
    _create(seeded_tenant, email=email)
    user = User.get_user_by_email(email, tenant_id=seeded_tenant.id)

    res = delete_sub_admin(seeded_tenant.id, user.id, actor_id=user.id)
    assert res["success"] is False
    assert res["status_code"] == 400


# ---------------------------------------------------------------------------
# Guardrails: target must be a sub-admin in this tenant
# ---------------------------------------------------------------------------

def test_cannot_act_on_non_subadmin_user(db_session, seeded_tenant, mock_dispatch):
    from modules.auth.models import User
    from modules.sub_admins.services import get_sub_admin, suspend_sub_admin

    plain = User(
        id=f"u-{uuid.uuid4().hex[:12]}",
        tenant_id=seeded_tenant.id,
        email=_email(),
        password_hash="x" * 60,
        name="Plain User",
    )
    db_session.add(plain)
    db_session.flush()

    assert get_sub_admin(seeded_tenant.id, plain.id)["status_code"] == 404
    assert suspend_sub_admin(seeded_tenant.id, plain.id, "actor")["status_code"] == 404


# ---------------------------------------------------------------------------
# Authorization: subadmin.manage gating
# ---------------------------------------------------------------------------

def test_subadmin_lacks_subadmin_manage_permission(db_session, seeded_tenant, mock_dispatch):
    """A created sub-admin must NOT receive subadmin.manage (route guard basis)."""
    from modules.auth.models import User
    from modules.rbac.services import has_permission

    email = _email()
    _create(seeded_tenant, email=email, modules=[{"key": "finance", "level": "operate"}])
    user = User.get_user_by_email(email, tenant_id=seeded_tenant.id)
    assert has_permission(user.id, "subadmin.manage") is False


def test_seeded_admin_has_subadmin_manage(db_session, seeded_tenant, mock_dispatch):
    """The seeded Admin role carries subadmin.manage so the School Admin passes the guard."""
    from modules.auth.models import User
    from modules.rbac.models import Role, UserRole
    from modules.rbac.services import has_permission

    admin_role = Role.query.filter_by(name="Admin", tenant_id=seeded_tenant.id).first()
    assert admin_role is not None

    admin_user = User(
        id=f"u-{uuid.uuid4().hex[:12]}",
        tenant_id=seeded_tenant.id,
        email=_email(),
        password_hash="x" * 60,
        name="School Admin",
    )
    db_session.add(admin_user)
    db_session.flush()
    db_session.add(
        UserRole(tenant_id=seeded_tenant.id, user_id=admin_user.id, role_id=admin_role.id)
    )
    db_session.flush()

    assert has_permission(admin_user.id, "subadmin.manage") is True


# ---------------------------------------------------------------------------
# Credential / reset emails carry a non-empty, tenant-correct login_url
# ---------------------------------------------------------------------------

def _dispatched_login_url(mock_dispatch, notification_type):
    """Return extra_data['login_url'] from the matching dispatch call, or None."""
    for call in mock_dispatch.dispatch.call_args_list:
        if call.kwargs.get("notification_type") == notification_type:
            return (call.kwargs.get("extra_data") or {}).get("login_url")
    return None


def test_build_tenant_login_url_is_subdomain_specific():
    """The builder produces a tenant-subdomain admin-web login URL (dev/prod)."""
    from modules.sub_admins.services import build_tenant_login_url

    with patch("config.settings.is_production", return_value=False):
        assert build_tenant_login_url("mts") == "http://mts.localhost:3000/login"
    with patch("config.settings.is_production", return_value=True):
        assert build_tenant_login_url("mts") == "https://mts.nexchool.in/login"
    # No subdomain -> empty (email omits the link rather than rendering broken).
    assert build_tenant_login_url("") == ""


def test_create_email_carries_tenant_login_url(db_session, seeded_tenant, mock_dispatch):
    """ADMIN_CREDENTIALS dispatch carries a non-empty, tenant-correct login_url."""
    from modules.sub_admins.services import build_tenant_login_url

    expected = build_tenant_login_url(seeded_tenant.subdomain)
    assert expected  # sanity: tenant has a subdomain, so URL is non-empty

    result = _create(seeded_tenant, email=_email(), login_url=expected)
    assert result["success"], result

    login_url = _dispatched_login_url(mock_dispatch, "ADMIN_CREDENTIALS")
    assert login_url == expected
    assert seeded_tenant.subdomain in login_url


def test_reset_email_carries_tenant_login_url(db_session, seeded_tenant, mock_dispatch):
    """ADMIN_PASSWORD_RESET dispatch carries a non-empty, tenant-correct login_url."""
    from modules.auth.models import User
    from modules.sub_admins.services import (
        build_tenant_login_url,
        reset_sub_admin_password,
    )

    email = _email()
    _create(seeded_tenant, email=email)
    user = User.get_user_by_email(email, tenant_id=seeded_tenant.id)

    expected = build_tenant_login_url(seeded_tenant.subdomain)
    res = reset_sub_admin_password(
        tenant_id=seeded_tenant.id,
        tenant_name=seeded_tenant.name,
        user_id=user.id,
        actor_id="someone-else",
        password="newpassword2",
        login_url=expected,
    )
    assert res["success"], res

    login_url = _dispatched_login_url(mock_dispatch, "ADMIN_PASSWORD_RESET")
    assert login_url == expected
    assert seeded_tenant.subdomain in login_url
