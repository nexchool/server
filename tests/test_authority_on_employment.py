"""Authority belongs to the employment, not the account (ADR-013).

The case worth protecting: when someone stops working here their authority
stops, because it was never anything but an aspect of that employment.
"""

from __future__ import annotations

import uuid

import pytest

from modules.people.employment import (
    EMPLOYMENT_STATUS_ON_LEAVE,
    EMPLOYMENT_STATUS_RESIGNED,
    EMPLOYMENT_STATUS_SUSPENDED,
)
from modules.people.service import employ
from modules.rbac.authority_service import (
    AuthorityRefused,
    authorities_held_by,
    grant_authority,
    permission_keys_for_person,
    withdraw_authority,
)


def _account(db_session, tenant, name="Rohit Mehta"):
    from modules.auth.models import User

    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=f"u-{suffix}",
        tenant_id=tenant.id,
        email=f"{suffix}@test.school",
        password_hash="x" * 60,
        name=name,
    )
    db_session.add(user)
    db_session.flush()
    return user


def _authority_profile(db_session, tenant, *, permissions=("student.read",)):
    """An Authority Profile — a Role, in the schema's vocabulary."""
    from modules.rbac.models import Permission, Role, RolePermission

    role = Role(
        id=f"r-{uuid.uuid4().hex[:8]}",
        tenant_id=tenant.id,
        name=f"Coordinator-{uuid.uuid4().hex[:6]}",
    )
    db_session.add(role)
    db_session.flush()

    for name in permissions:
        permission = Permission.query.filter_by(name=name).first()
        if permission is None:
            permission = Permission(id=f"p-{uuid.uuid4().hex[:8]}", name=name)
            db_session.add(permission)
            db_session.flush()
        db_session.add(
            RolePermission(
                id=f"rp-{uuid.uuid4().hex[:8]}",
                tenant_id=tenant.id,
                role_id=role.id,
                permission_id=permission.id,
            )
        )
    db_session.flush()
    return role


# ---------------------------------------------------------------------------
# Holding authority
# ---------------------------------------------------------------------------

def test_an_employed_person_holds_the_authority_they_are_granted(db_session, tenant):
    user = _account(db_session, tenant)
    staff = employ(tenant.id, user.person_id)
    role = _authority_profile(db_session, tenant, permissions=("student.read",))

    grant_authority(staff.id, role.id)

    assert [r.id for r in authorities_held_by(staff.id)] == [role.id]
    assert permission_keys_for_person(user.person_id) == ["student.read"]


def test_granting_the_same_authority_twice_holds_it_once(db_session, tenant):
    user = _account(db_session, tenant)
    staff = employ(tenant.id, user.person_id)
    role = _authority_profile(db_session, tenant)

    grant_authority(staff.id, role.id)
    grant_authority(staff.id, role.id)

    assert len(authorities_held_by(staff.id)) == 1


def test_withdrawing_authority_takes_it_away(db_session, tenant):
    user = _account(db_session, tenant)
    staff = employ(tenant.id, user.person_id)
    role = _authority_profile(db_session, tenant)
    grant_authority(staff.id, role.id)

    assert withdraw_authority(staff.id, role.id) is True
    assert permission_keys_for_person(user.person_id) == []


# ---------------------------------------------------------------------------
# The point of ADR-013
# ---------------------------------------------------------------------------

def test_authority_ends_when_the_employment_ends(db_session, tenant):
    """Nobody has to remember. The employment ended, so the authority did."""
    user = _account(db_session, tenant)
    staff = employ(tenant.id, user.person_id)
    role = _authority_profile(db_session, tenant, permissions=("student.read",))
    grant_authority(staff.id, role.id)

    assert permission_keys_for_person(user.person_id) == ["student.read"]

    staff.employment_status = EMPLOYMENT_STATUS_RESIGNED
    db_session.flush()

    assert permission_keys_for_person(user.person_id) == []


def test_a_suspended_employee_holds_nothing_while_suspended(db_session, tenant):
    user = _account(db_session, tenant)
    staff = employ(tenant.id, user.person_id)
    role = _authority_profile(db_session, tenant)
    grant_authority(staff.id, role.id)

    staff.employment_status = EMPLOYMENT_STATUS_SUSPENDED
    db_session.flush()

    assert permission_keys_for_person(user.person_id) == []

    # Suspension is not departure: the grant survives it.
    staff.employment_status = EMPLOYMENT_STATUS_ON_LEAVE
    db_session.flush()
    assert permission_keys_for_person(user.person_id) != []


def test_authority_cannot_be_granted_to_someone_who_has_left(db_session, tenant):
    user = _account(db_session, tenant)
    staff = employ(
        tenant.id, user.person_id, employment_status=EMPLOYMENT_STATUS_RESIGNED
    )
    role = _authority_profile(db_session, tenant)

    with pytest.raises(AuthorityRefused, match="no longer works here"):
        grant_authority(staff.id, role.id)


def test_authority_from_another_organization_is_refused(db_session, tenant):
    from core.models import BILLING_CYCLE_YEARLY, TENANT_STATUS_ACTIVE, Tenant

    other = Tenant(
        id=f"t-{uuid.uuid4().hex[:12]}",
        name="Other School",
        subdomain=f"other-{uuid.uuid4().hex[:6]}",
        status=TENANT_STATUS_ACTIVE,
        billing_cycle=BILLING_CYCLE_YEARLY,
    )
    db_session.add(other)
    db_session.flush()

    user = _account(db_session, tenant)
    staff = employ(tenant.id, user.person_id)
    elsewhere = _authority_profile(db_session, other)

    with pytest.raises(AuthorityRefused, match="does not exist here"):
        grant_authority(staff.id, elsewhere.id)


# ---------------------------------------------------------------------------
# Resolution reads both sources during the migration
# ---------------------------------------------------------------------------

def test_permission_resolution_reads_authority_held_through_employment(
    db_session, tenant
):
    from modules.rbac.services import _load_user_permissions_from_db

    user = _account(db_session, tenant)
    staff = employ(tenant.id, user.person_id)
    role = _authority_profile(db_session, tenant, permissions=("fee.collect",))
    grant_authority(staff.id, role.id)

    assert "fee.collect" in _load_user_permissions_from_db(user.id)


def test_an_account_with_no_employment_still_resolves_its_own_roles(
    db_session, tenant
):
    """The account-held path is untouched while both sources coexist."""
    from modules.rbac.models import UserRole
    from modules.rbac.services import _load_user_permissions_from_db

    user = _account(db_session, tenant)
    role = _authority_profile(db_session, tenant, permissions=("student.read",))
    db_session.add(
        UserRole(
            id=f"ur-{uuid.uuid4().hex[:8]}",
            tenant_id=tenant.id,
            user_id=user.id,
            role_id=role.id,
        )
    )
    db_session.flush()

    assert "student.read" in _load_user_permissions_from_db(user.id)
