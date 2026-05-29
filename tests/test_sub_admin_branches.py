"""Backend tests for Phase-2 branch scoping of sub-admins (P2-T3).

Covers:
- create with branch_unit_ids + branch-aware modules -> success, rows created,
  get_allowed_unit_ids returns the set, serialized branch_unit_ids present.
- create with a NON-branch module + branches -> 422.
- create with an invalid / inactive branch id -> 422.
- create with empty branches (unrestricted) + any modules (incl. non-branch)
  -> success, no rows, get_allowed_unit_ids -> None.
- edit add/remove re-syncs rows; edit to empty makes unrestricted; edit a
  restricted sub-admin to include a non-branch module -> 422 (combined check).
- login + profile expose allowed_unit_ids (restricted list / null / null).

Runs against localhost Postgres via conftest savepoint fixtures; the
notification dispatcher is mocked so no real email is sent.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from flask import g

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def seeded_tenant(db_session, tenant):
    """Tenant with default roles seeded (mirrors test_sub_admins.py)."""
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
    with patch("modules.notifications.services.notification_dispatcher") as md:
        md.dispatch.return_value = {"email": True}
        yield md


@pytest.fixture
def units(db_session, seeded_tenant):
    """Two active units + one inactive unit in the tenant."""
    from modules.school_units.models import (
        SCHOOL_UNIT_STATUS_INACTIVE,
        SchoolUnit,
    )

    unit_a = SchoolUnit(
        id=f"su-{uuid.uuid4().hex[:12]}", tenant_id=seeded_tenant.id,
        name="Campus A", code=f"A-{uuid.uuid4().hex[:6]}",
    )
    unit_b = SchoolUnit(
        id=f"su-{uuid.uuid4().hex[:12]}", tenant_id=seeded_tenant.id,
        name="Campus B", code=f"B-{uuid.uuid4().hex[:6]}",
    )
    unit_inactive = SchoolUnit(
        id=f"su-{uuid.uuid4().hex[:12]}", tenant_id=seeded_tenant.id,
        name="Campus C (inactive)", code=f"C-{uuid.uuid4().hex[:6]}",
        status=SCHOOL_UNIT_STATUS_INACTIVE,
    )
    db_session.add_all([unit_a, unit_b, unit_inactive])
    db_session.flush()
    return unit_a, unit_b, unit_inactive


def _email() -> str:
    return f"sa-{uuid.uuid4().hex[:10]}@test.school"


def _create(tenant, **overrides):
    from modules.sub_admins.services import create_sub_admin

    payload = {
        "tenant_id": tenant.id,
        "tenant_name": tenant.name,
        "name": "Branch Admin",
        "email": _email(),
        "password": "password123",
        "modules": [{"key": "students", "level": "view"}],
    }
    payload.update(overrides)
    return create_sub_admin(**payload)


def _allowed_units_for(flask_app, tenant, user):
    """Resolve get_allowed_unit_ids() inside a request context for a user."""
    from core.branch_scope import get_allowed_unit_ids

    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = user
        return get_allowed_unit_ids()


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def test_create_with_branch_and_branch_aware_modules(
    flask_app, db_session, seeded_tenant, units, mock_dispatch
):
    from modules.auth.models import User
    from modules.sub_admins.models import UserSchoolUnit

    unit_a, _unit_b, _inactive = units
    email = _email()
    result = _create(
        seeded_tenant,
        email=email,
        modules=[{"key": "students", "level": "view"}],
        branch_unit_ids=[unit_a.id],
    )
    assert result["success"], result
    assert result["sub_admin"]["branch_unit_ids"] == [unit_a.id]

    user = User.get_user_by_email(email, tenant_id=seeded_tenant.id)
    rows = UserSchoolUnit.query.filter_by(
        user_id=user.id, tenant_id=seeded_tenant.id
    ).all()
    assert {r.school_unit_id for r in rows} == {unit_a.id}

    assert _allowed_units_for(flask_app, seeded_tenant, user) == {unit_a.id}


def test_create_branch_with_non_branch_module_rejected(
    db_session, seeded_tenant, units, mock_dispatch
):
    unit_a, _b, _c = units
    result = _create(
        seeded_tenant,
        modules=[{"key": "teachers", "level": "view"}],
        branch_unit_ids=[unit_a.id],
    )
    assert result["success"] is False
    assert result["status_code"] == 422
    assert "teachers" in result["error"]


def test_create_branch_with_invalid_id_rejected(
    db_session, seeded_tenant, units, mock_dispatch
):
    result = _create(
        seeded_tenant,
        modules=[{"key": "students", "level": "view"}],
        branch_unit_ids=["does-not-exist"],
    )
    assert result["success"] is False
    assert result["status_code"] == 422


def test_create_branch_with_inactive_id_rejected(
    db_session, seeded_tenant, units, mock_dispatch
):
    _a, _b, inactive = units
    result = _create(
        seeded_tenant,
        modules=[{"key": "students", "level": "view"}],
        branch_unit_ids=[inactive.id],
    )
    assert result["success"] is False
    assert result["status_code"] == 422


def test_create_unrestricted_allows_non_branch_modules(
    flask_app, db_session, seeded_tenant, mock_dispatch
):
    from modules.auth.models import User
    from modules.sub_admins.models import UserSchoolUnit

    email = _email()
    result = _create(
        seeded_tenant,
        email=email,
        modules=[
            {"key": "teachers", "level": "view"},
            {"key": "transport", "level": "manage"},
        ],
        branch_unit_ids=[],
    )
    assert result["success"], result
    assert result["sub_admin"]["branch_unit_ids"] == []

    user = User.get_user_by_email(email, tenant_id=seeded_tenant.id)
    assert (
        UserSchoolUnit.query.filter_by(user_id=user.id).count() == 0
    )
    assert _allowed_units_for(flask_app, seeded_tenant, user) is None


# ---------------------------------------------------------------------------
# Edit
# ---------------------------------------------------------------------------

def test_edit_add_and_remove_branches_resyncs(
    flask_app, db_session, seeded_tenant, units, mock_dispatch
):
    from modules.auth.models import User
    from modules.sub_admins.services import update_sub_admin

    unit_a, unit_b, _inactive = units
    email = _email()
    _create(
        seeded_tenant,
        email=email,
        modules=[{"key": "students", "level": "view"}],
        branch_unit_ids=[unit_a.id],
    )
    user = User.get_user_by_email(email, tenant_id=seeded_tenant.id)

    # Add unit_b, drop unit_a
    res = update_sub_admin(
        seeded_tenant.id, user.id, branch_unit_ids=[unit_b.id]
    )
    assert res["success"], res
    assert res["sub_admin"]["branch_unit_ids"] == [unit_b.id]
    assert _allowed_units_for(flask_app, seeded_tenant, user) == {unit_b.id}


def test_edit_to_empty_makes_unrestricted(
    flask_app, db_session, seeded_tenant, units, mock_dispatch
):
    from modules.auth.models import User
    from modules.sub_admins.models import UserSchoolUnit
    from modules.sub_admins.services import update_sub_admin

    unit_a, _b, _c = units
    email = _email()
    _create(
        seeded_tenant,
        email=email,
        modules=[{"key": "students", "level": "view"}],
        branch_unit_ids=[unit_a.id],
    )
    user = User.get_user_by_email(email, tenant_id=seeded_tenant.id)

    res = update_sub_admin(seeded_tenant.id, user.id, branch_unit_ids=[])
    assert res["success"], res
    assert res["sub_admin"]["branch_unit_ids"] == []
    assert UserSchoolUnit.query.filter_by(user_id=user.id).count() == 0
    assert _allowed_units_for(flask_app, seeded_tenant, user) is None


def test_edit_restricted_to_non_branch_module_rejected(
    db_session, seeded_tenant, units, mock_dispatch
):
    """Combined post-edit check: restricted sub-admin + new non-branch module."""
    from modules.auth.models import User
    from modules.sub_admins.services import update_sub_admin

    unit_a, _b, _c = units
    email = _email()
    _create(
        seeded_tenant,
        email=email,
        modules=[{"key": "students", "level": "view"}],
        branch_unit_ids=[unit_a.id],
    )
    user = User.get_user_by_email(email, tenant_id=seeded_tenant.id)

    # branch_unit_ids omitted -> keep existing restricted set; new module is
    # non-branch -> must 422.
    res = update_sub_admin(
        seeded_tenant.id,
        user.id,
        modules=[{"key": "teachers", "level": "view"}],
    )
    assert res["success"] is False
    assert res["status_code"] == 422
    assert "teachers" in res["error"]


def test_edit_add_branch_to_user_with_existing_non_branch_module_rejected(
    db_session, seeded_tenant, units, mock_dispatch
):
    """Restricting an unrestricted sub-admin who holds a non-branch module 422s."""
    from modules.auth.models import User
    from modules.sub_admins.services import update_sub_admin

    unit_a, _b, _c = units
    email = _email()
    _create(
        seeded_tenant,
        email=email,
        modules=[{"key": "teachers", "level": "view"}],
        branch_unit_ids=[],
    )
    user = User.get_user_by_email(email, tenant_id=seeded_tenant.id)

    # modules omitted -> derived from current role (teachers, non-branch);
    # adding a branch must fail the combined check.
    res = update_sub_admin(
        seeded_tenant.id, user.id, branch_unit_ids=[unit_a.id]
    )
    assert res["success"] is False
    assert res["status_code"] == 422


# ---------------------------------------------------------------------------
# login + profile allowed_unit_ids
# ---------------------------------------------------------------------------

def _build_admin_user(db_session, tenant):
    """A verified Admin user (carries permissions) for login/profile tests."""
    from modules.auth.models import User
    from modules.rbac.models import Role, UserRole

    admin_role = Role.query.filter_by(name="Admin", tenant_id=tenant.id).first()
    assert admin_role is not None
    user = User(tenant_id=tenant.id, email=_email(), name="School Admin")
    user.set_password("password123")
    user.email_verified = True
    db_session.add(user)
    db_session.flush()
    db_session.add(UserRole(tenant_id=tenant.id, user_id=user.id, role_id=admin_role.id))
    db_session.flush()
    return user


def test_login_includes_allowed_unit_ids_for_restricted_subadmin(
    flask_app, db_session, seeded_tenant, units, mock_dispatch
):
    from modules.auth.models import User

    unit_a, _b, _c = units
    email = _email()
    _create(
        seeded_tenant,
        email=email,
        password="password123",
        modules=[{"key": "students", "level": "view"}],
        branch_unit_ids=[unit_a.id],
    )
    user = User.get_user_by_email(email, tenant_id=seeded_tenant.id)
    assert user is not None

    client = flask_app.test_client()
    resp = client.post(
        "/api/auth/login",
        json={"email": email, "password": "password123", "tenant_id": seeded_tenant.id},
        headers={"X-Tenant-ID": seeded_tenant.id},
    )
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()["data"]
    assert data["allowed_unit_ids"] == [unit_a.id]


def test_login_and_profile_null_for_unrestricted_admin(
    flask_app, db_session, seeded_tenant, mock_dispatch
):
    user = _build_admin_user(db_session, seeded_tenant)

    client = flask_app.test_client()
    resp = client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "password123", "tenant_id": seeded_tenant.id},
        headers={"X-Tenant-ID": seeded_tenant.id},
    )
    assert resp.status_code == 200, resp.get_json()
    login_data = resp.get_json()["data"]
    assert login_data["allowed_unit_ids"] is None

    token = login_data["access_token"]
    prof = client.get(
        "/api/auth/profile",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Tenant-ID": seeded_tenant.id,
        },
    )
    assert prof.status_code == 200, prof.get_json()
    assert prof.get_json()["data"]["allowed_unit_ids"] is None


def test_profile_includes_allowed_unit_ids_for_restricted_subadmin(
    flask_app, db_session, seeded_tenant, units, mock_dispatch
):
    from modules.auth.models import User

    unit_a, _b, _c = units
    email = _email()
    _create(
        seeded_tenant,
        email=email,
        password="password123",
        modules=[{"key": "students", "level": "view"}],
        branch_unit_ids=[unit_a.id],
    )
    user = User.get_user_by_email(email, tenant_id=seeded_tenant.id)

    client = flask_app.test_client()
    login = client.post(
        "/api/auth/login",
        json={"email": email, "password": "password123", "tenant_id": seeded_tenant.id},
        headers={"X-Tenant-ID": seeded_tenant.id},
    )
    assert login.status_code == 200, login.get_json()
    token = login.get_json()["data"]["access_token"]

    prof = client.get(
        "/api/auth/profile",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Tenant-ID": seeded_tenant.id,
        },
    )
    assert prof.status_code == 200, prof.get_json()
    assert prof.get_json()["data"]["allowed_unit_ids"] == [unit_a.id]
