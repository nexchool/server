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


# ---------------------------------------------------------------------------
# Temporary delegation — the principal goes on leave, the deputy acts
# ---------------------------------------------------------------------------

def _two_employments(db_session, tenant):
    principal = _account(db_session, tenant, name="Meera Shah")
    deputy = _account(db_session, tenant, name="Rohit Mehta")
    return (
        employ(tenant.id, principal.person_id),
        employ(tenant.id, deputy.person_id),
        principal,
        deputy,
    )


def test_a_deputy_acts_under_delegated_authority(db_session, tenant):
    from datetime import date, timedelta

    from modules.rbac.authority_service import delegate_authority

    principal_staff, deputy_staff, _, deputy = _two_employments(db_session, tenant)
    role = _authority_profile(db_session, tenant, permissions=("fee.refund",))
    grant_authority(principal_staff.id, role.id)

    today = date.today()
    delegate_authority(
        role.id,
        principal_staff.id,
        deputy_staff.id,
        effective_from=today - timedelta(days=1),
        effective_to=today + timedelta(days=7),
        reason="Principal on leave",
    )

    assert permission_keys_for_person(deputy.person_id) == ["fee.refund"]


def test_a_delegation_does_not_apply_before_it_begins(db_session, tenant):
    from datetime import date, timedelta

    from modules.rbac.authority_service import delegate_authority

    principal_staff, deputy_staff, _, deputy = _two_employments(db_session, tenant)
    role = _authority_profile(db_session, tenant, permissions=("fee.refund",))
    grant_authority(principal_staff.id, role.id)

    today = date.today()
    delegate_authority(
        role.id,
        principal_staff.id,
        deputy_staff.id,
        effective_from=today + timedelta(days=3),
        effective_to=today + timedelta(days=10),
    )

    assert permission_keys_for_person(deputy.person_id) == []


def test_a_delegation_expires_without_anything_running(db_session, tenant):
    """No job ends it: it simply stops being read once the window has passed."""
    from datetime import date, timedelta

    from modules.rbac.authority_service import delegate_authority

    principal_staff, deputy_staff, _, deputy = _two_employments(db_session, tenant)
    role = _authority_profile(db_session, tenant, permissions=("fee.refund",))
    grant_authority(principal_staff.id, role.id)

    today = date.today()
    delegate_authority(
        role.id,
        principal_staff.id,
        deputy_staff.id,
        effective_from=today - timedelta(days=10),
        effective_to=today - timedelta(days=1),
    )

    assert permission_keys_for_person(deputy.person_id) == []


def test_a_delegation_can_be_ended_early(db_session, tenant):
    from datetime import date, timedelta

    from modules.rbac.authority_service import delegate_authority, end_delegation

    principal_staff, deputy_staff, _, deputy = _two_employments(db_session, tenant)
    role = _authority_profile(db_session, tenant, permissions=("fee.refund",))
    grant_authority(principal_staff.id, role.id)

    today = date.today()
    delegation = delegate_authority(
        role.id,
        principal_staff.id,
        deputy_staff.id,
        effective_from=today,
        effective_to=today + timedelta(days=30),
    )
    assert permission_keys_for_person(deputy.person_id) == ["fee.refund"]

    assert end_delegation(delegation.id) is True
    assert permission_keys_for_person(deputy.person_id) == []


def test_authority_that_is_not_held_cannot_be_lent(db_session, tenant):
    from datetime import date, timedelta

    from modules.rbac.authority_service import delegate_authority

    principal_staff, deputy_staff, _, _ = _two_employments(db_session, tenant)
    role = _authority_profile(db_session, tenant)

    today = date.today()
    with pytest.raises(AuthorityRefused, match="not held"):
        delegate_authority(
            role.id,
            principal_staff.id,
            deputy_staff.id,
            effective_from=today,
            effective_to=today + timedelta(days=5),
        )


def test_a_delegation_lapses_if_the_person_who_lent_it_leaves(db_session, tenant):
    """Their authority ended, so there is nothing left to lend."""
    from datetime import date, timedelta

    from modules.rbac.authority_service import delegate_authority

    principal_staff, deputy_staff, _, deputy = _two_employments(db_session, tenant)
    role = _authority_profile(db_session, tenant, permissions=("fee.refund",))
    grant_authority(principal_staff.id, role.id)

    today = date.today()
    delegate_authority(
        role.id,
        principal_staff.id,
        deputy_staff.id,
        effective_from=today,
        effective_to=today + timedelta(days=30),
    )
    assert permission_keys_for_person(deputy.person_id) == ["fee.refund"]

    principal_staff.employment_status = EMPLOYMENT_STATUS_RESIGNED
    db_session.flush()

    assert permission_keys_for_person(deputy.person_id) == []


def test_a_delegation_survives_the_absence_that_caused_it(db_session, tenant):
    """Leave is usually the reason for delegating, so it must not cancel it."""
    from datetime import date, timedelta

    from modules.rbac.authority_service import delegate_authority

    principal_staff, deputy_staff, _, deputy = _two_employments(db_session, tenant)
    role = _authority_profile(db_session, tenant, permissions=("fee.refund",))
    grant_authority(principal_staff.id, role.id)

    today = date.today()
    delegate_authority(
        role.id,
        principal_staff.id,
        deputy_staff.id,
        effective_from=today,
        effective_to=today + timedelta(days=30),
    )

    principal_staff.employment_status = EMPLOYMENT_STATUS_ON_LEAVE
    db_session.flush()

    assert permission_keys_for_person(deputy.person_id) == ["fee.refund"]


def test_authority_cannot_be_delegated_to_someone_who_cannot_act(db_session, tenant):
    from datetime import date, timedelta

    from modules.rbac.authority_service import delegate_authority

    principal_staff, deputy_staff, _, _ = _two_employments(db_session, tenant)
    role = _authority_profile(db_session, tenant)
    grant_authority(principal_staff.id, role.id)

    deputy_staff.employment_status = EMPLOYMENT_STATUS_SUSPENDED
    db_session.flush()

    today = date.today()
    with pytest.raises(AuthorityRefused, match="cannot act"):
        delegate_authority(
            role.id,
            principal_staff.id,
            deputy_staff.id,
            effective_from=today,
            effective_to=today + timedelta(days=5),
        )


def test_the_person_who_lent_authority_still_holds_it(db_session, tenant):
    """Delegating is lending, not surrendering."""
    from datetime import date, timedelta

    from modules.rbac.authority_service import delegate_authority

    principal_staff, deputy_staff, principal, _ = _two_employments(db_session, tenant)
    role = _authority_profile(db_session, tenant, permissions=("fee.refund",))
    grant_authority(principal_staff.id, role.id)

    today = date.today()
    delegate_authority(
        role.id,
        principal_staff.id,
        deputy_staff.id,
        effective_from=today,
        effective_to=today + timedelta(days=30),
    )

    assert permission_keys_for_person(principal.person_id) == ["fee.refund"]


# ---------------------------------------------------------------------------
# Moving account-held roles onto employments
# ---------------------------------------------------------------------------

def _assign_account_role(db_session, tenant, user, role):
    from modules.rbac.models import UserRole

    db_session.add(
        UserRole(
            id=f"ur-{uuid.uuid4().hex[:8]}",
            tenant_id=tenant.id,
            user_id=user.id,
            role_id=role.id,
        )
    )
    db_session.flush()


def test_an_employed_holders_authority_moves_onto_their_employment(db_session, tenant):
    from scripts.backfill_authority import _move_tenant_authority

    user = _account(db_session, tenant)
    staff = employ(tenant.id, user.person_id)
    role = _authority_profile(db_session, tenant)
    _assign_account_role(db_session, tenant, user, role)

    report = _move_tenant_authority(tenant.id)

    assert report.moved == 1
    assert [r.id for r in authorities_held_by(staff.id)] == [role.id]


def test_moving_authority_twice_moves_it_once(db_session, tenant):
    from scripts.backfill_authority import _move_tenant_authority

    user = _account(db_session, tenant)
    staff = employ(tenant.id, user.person_id)
    role = _authority_profile(db_session, tenant)
    _assign_account_role(db_session, tenant, user, role)

    _move_tenant_authority(tenant.id)
    second = _move_tenant_authority(tenant.id)

    assert second.moved == 0
    assert second.already_held == 1
    assert len(authorities_held_by(staff.id)) == 1


def test_a_students_assignment_is_redundant_once_the_relationship_implies_it(
    db_session, tenant
):
    """A student holds no organizational authority; their access follows from
    being a student, so the assignment carries nothing the relationship does
    not already give them."""
    from scripts.backfill_authority import _move_tenant_authority

    user = _account(db_session, tenant, name="Aarav Patel")
    _admit_student(db_session, tenant, user)
    role = _student_profile(db_session, tenant)
    _assign_account_role(db_session, tenant, user, role)

    report = _move_tenant_authority(tenant.id)

    assert report.moved == 0
    assert report.students_covered_by_implication == 1
    assert report.students_not_covered == []


def test_a_students_assignment_granting_more_than_implied_is_refused(
    db_session, tenant
):
    """The gate: removing this would quietly take access away, so it is
    reported rather than assumed safe."""
    from scripts.backfill_authority import _move_tenant_authority

    user = _account(db_session, tenant, name="Aarav Patel")
    _admit_student(db_session, tenant, user)
    _student_profile(db_session, tenant, permissions=("attendance.read.self",))

    # Assigned a profile granting something the relationship does not imply.
    extra = _authority_profile(db_session, tenant, permissions=("profile.update.self",))
    _assign_account_role(db_session, tenant, user, extra)

    report = _move_tenant_authority(tenant.id)

    assert [entry["email"] for entry in report.students_not_covered] == [user.email]


def test_a_holder_with_no_employment_is_employed_rather_than_abandoned(
    db_session, tenant
):
    """They work here; the record simply never said so."""
    from modules.people.employment import Staff
    from scripts.backfill_authority import _move_tenant_authority

    user = _account(db_session, tenant, name="Orphaned Admin")
    role = _authority_profile(db_session, tenant)
    _assign_account_role(db_session, tenant, user, role)

    report = _move_tenant_authority(tenant.id)

    assert report.employments_created == 1
    assert report.moved == 1

    employment = Staff.query.filter_by(person_id=user.person_id).one()
    assert [r.id for r in authorities_held_by(employment.id)] == [role.id]


def test_moving_authority_changes_nobodys_permissions(db_session, tenant):
    """The union means this is additive: access before equals access after."""
    from modules.rbac.services import _load_user_permissions_from_db
    from scripts.backfill_authority import _move_tenant_authority

    user = _account(db_session, tenant)
    employ(tenant.id, user.person_id)
    role = _authority_profile(db_session, tenant, permissions=("student.read",))
    _assign_account_role(db_session, tenant, user, role)

    before = _load_user_permissions_from_db(user.id)
    _move_tenant_authority(tenant.id)
    after = _load_user_permissions_from_db(user.id)

    assert before == after == ["student.read"]


# ---------------------------------------------------------------------------
# Access that follows from what someone is, rather than being granted
# ---------------------------------------------------------------------------

def _admit_student(db_session, tenant, user):
    from modules.students.models import Student

    student = Student(
        id=f"s-{uuid.uuid4().hex[:8]}",
        tenant_id=tenant.id,
        user_id=user.id,
        admission_number=f"ADM-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(student)
    db_session.flush()
    return student


def _student_profile(db_session, tenant, *, permissions=("attendance.read.self",)):
    role = _authority_profile(db_session, tenant, permissions=permissions)
    role.implied_by_relationship = "student"
    db_session.flush()
    return role


def test_a_student_holds_their_access_without_anyone_granting_it(db_session, tenant):
    user = _account(db_session, tenant, name="Aarav Patel")
    _admit_student(db_session, tenant, user)
    _student_profile(db_session, tenant)

    # Nothing was assigned to this account.
    assert permission_keys_for_person(user.person_id) == ["attendance.read.self"]


def test_someone_who_is_not_a_student_does_not_get_student_access(db_session, tenant):
    user = _account(db_session, tenant)
    employ(tenant.id, user.person_id)
    _student_profile(db_session, tenant)

    assert permission_keys_for_person(user.person_id) == []


def test_renaming_the_student_profile_does_not_remove_student_access(
    db_session, tenant
):
    """Which is why the profile is marked rather than matched by name."""
    user = _account(db_session, tenant, name="Aarav Patel")
    _admit_student(db_session, tenant, user)
    role = _student_profile(db_session, tenant)

    role.name = "Learner"
    db_session.flush()

    assert permission_keys_for_person(user.person_id) == ["attendance.read.self"]


def test_a_teaching_student_holds_both_kinds_of_access(db_session, tenant):
    """A senior student employed as a lab assistant is both things at once."""
    user = _account(db_session, tenant, name="Aarav Patel")
    _admit_student(db_session, tenant, user)
    _student_profile(db_session, tenant)

    staff = employ(tenant.id, user.person_id)
    employed_role = _authority_profile(db_session, tenant, permissions=("student.read",))
    grant_authority(staff.id, employed_role.id)

    assert permission_keys_for_person(user.person_id) == [
        "attendance.read.self",
        "student.read",
    ]


# ---------------------------------------------------------------------------
# Authority stays inside the organization that granted it
# ---------------------------------------------------------------------------

def _other_tenant(db_session):
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
    return other


def test_a_role_from_another_organization_cannot_be_assigned(db_session, tenant):
    """How the cross-tenant rows were created: an unscoped lookup by name."""
    from modules.rbac.services import assign_role_to_user

    user = _account(db_session, tenant)
    elsewhere = _authority_profile(db_session, _other_tenant(db_session))

    result = assign_role_to_user(user.id, elsewhere.id)

    assert result["success"] is False
    assert "another organization" in result["error"]


def test_assigning_by_name_never_reaches_another_organizations_role(
    db_session, tenant
):
    """Two schools both have a 'Student' profile; a name must not cross over."""
    from modules.rbac.services import assign_role_to_user_by_email

    other = _other_tenant(db_session)
    shared_name = f"Student-{uuid.uuid4().hex[:6]}"
    for owner in (other,):
        role = _authority_profile(db_session, owner)
        role.name = shared_name
    db_session.flush()

    user = _account(db_session, tenant)

    # Only the other organization has a role by this name, so there is nothing
    # here to assign — rather than silently reaching across.
    result = assign_role_to_user_by_email(user.email, shared_name)

    assert result["success"] is False
    assert "not found" in result["error"]


def test_the_database_refuses_a_cross_tenant_assignment(db_session, tenant):
    """The durable guard: no code path can recreate this, however it asks."""
    from sqlalchemy.exc import IntegrityError

    from modules.rbac.models import UserRole

    user = _account(db_session, tenant)
    elsewhere = _authority_profile(db_session, _other_tenant(db_session))

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(
                UserRole(
                    id=f"ur-{uuid.uuid4().hex[:8]}",
                    tenant_id=tenant.id,
                    user_id=user.id,
                    role_id=elsewhere.id,
                )
            )
