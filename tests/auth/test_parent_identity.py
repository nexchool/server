"""Phase 6 — a parent signs in as themselves.

The identity model this rests on already existed:

    Person ── FamilyMember ── Family ── FamilyMember(child) ── Student
              (father)                       × many

A parent is **one Person and one membership**; their children are the other
members of the same household. So one parent with three children needs no new
table, no new column, and — this is the assertion that matters most — no
second account.

The ones worth reading first:

  * `test_one_parent_with_three_children_is_one_person_and_one_account` —
    PARENT-1, and the failure mode the whole phase exists to avoid.
  * `test_a_teacher_who_becomes_a_parent_keeps_one_account` — PARENT-11 and
    A1: the account is reused, never duplicated.
  * `test_nothing_changes_for_a_school_that_shares_one_login` — PARENT-7 and
    NFR-1, the regression that must hold on deployment.
  * `test_a_parent_cannot_reach_a_child_who_is_not_theirs` — PARENT-10.
"""

from __future__ import annotations

import uuid

import pytest

from core.database import db
from modules.auth.models import AccountIdentifier, User
from modules.auth.parents import (
    ParentProvisioningError,
    children_of,
    children_of_account,
    is_a_parent,
    may_access_student,
    provision_parent_login,
)
from modules.auth.person_link import AccountAlreadyExists
from modules.auth.policy import ensure_default_policy, subject_kinds
from modules.auth.policy_models import (
    FAMILY_ACCESS_SEPARATE,
    FAMILY_ACCESS_SHARED,
    SUBJECT_PARENT,
    SUBJECT_STAFF,
    SUBJECT_STUDENT,
)
from modules.people.models import FamilyMember, Person
from modules.people.service import record_family_member
from modules.students.models import Student
from tests.auth._characterization import (
    grant_permissions,
    make_tenant,
    make_user,
    new_id,
    sessions_for,
)


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _fresh_request(flask_app):
    from flask import g as flask_g

    for attribute in ("tenant_id", "tenant", "current_user"):
        if hasattr(flask_g, attribute):
            delattr(flask_g, attribute)


def _school(db_session, *, separate=True):
    """A school, sharing one login or issuing separate parent ones."""
    from modules.auth.policy_models import TenantAuthPolicy

    tenant = make_tenant(db_session)
    ensure_default_policy(tenant.id)
    if separate:
        policy = TenantAuthPolicy.query.filter_by(tenant_id=tenant.id).first()
        policy.family_access_mode = FAMILY_ACCESS_SEPARATE
        db_session.flush()
    return tenant


def _child(db_session, tenant, *, name="A Child"):
    """A student with a Person of their own, and no account."""
    person = Person(id=new_id("p-"), tenant_id=tenant.id, full_name=name)
    db_session.add(person)
    db_session.flush()
    student = Student(
        id=new_id("s-"),
        tenant_id=tenant.id,
        person_id=person.id,
        admission_number=f"ADM-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(student)
    db_session.flush()
    return student, person


def provision_parent_login_forcing_mode(db_session, tenant, parent):
    """An account for a parent at a school that shares one login.

    Provisioning refuses that, correctly — so the mode is turned on, the
    account is made, and the mode is put back. The tests that use this are
    about what happens *to an existing account* when the mode changes, which
    is a state a school reaches by switching back.
    """
    from modules.auth.policy_models import TenantAuthPolicy

    policy = TenantAuthPolicy.query.filter_by(tenant_id=tenant.id).first()
    was = policy.family_access_mode
    policy.family_access_mode = FAMILY_ACCESS_SEPARATE
    db_session.flush()

    account = provision_parent_login(parent, email=f"{uuid.uuid4().hex[:8]}@example.test").account

    policy.family_access_mode = was
    db_session.flush()
    db_session.refresh(account)
    return account


def _parent_of(db_session, tenant, child_person, *, name="A Parent", email=None, phone=None):
    """Record a responsible adult for this child, the way admission does."""
    record_family_member(
        tenant.id,
        child_person.id,
        name=name,
        relationship="father",
        email=email,
        phone=phone or f"98{uuid.uuid4().int % 100000000:08d}",
    )
    db_session.flush()
    return (
        Person.query.filter_by(tenant_id=tenant.id, full_name=name)
        .order_by(Person.created_at.desc())
        .first()
    )


# ---------------------------------------------------------------------------
# One parent, many children
# ---------------------------------------------------------------------------

def test_one_parent_with_three_children_is_one_person_and_one_account(db_session):
    """PARENT-1. The failure this phase exists to avoid is three accounts."""
    tenant = _school(db_session)
    first, first_person = _child(db_session, tenant, name="Child One")
    parent = _parent_of(
        db_session, tenant, first_person, name="Ravi Sharma", phone="9876500001"
    )

    for label in ("Child Two", "Child Three"):
        student, person = _child(db_session, tenant, name=label)
        record_family_member(
            tenant.id,
            person.id,
            name="Ravi Sharma",
            relationship="father",
            phone="9876500001",
        )
    db_session.flush()

    assert (
        Person.query.filter_by(tenant_id=tenant.id, full_name="Ravi Sharma").count() == 1
    )
    assert len(children_of(parent)) == 3

    provision_parent_login(parent, email="ravi@example.test")
    db_session.flush()

    assert User.query.filter_by(tenant_id=tenant.id, person_id=parent.id).count() == 1


def test_one_child_may_have_two_parents(db_session):
    """PARENT-2."""
    tenant = _school(db_session)
    student, child_person = _child(db_session, tenant)
    father = _parent_of(db_session, tenant, child_person, name="A Father")
    record_family_member(
        tenant.id, child_person.id, name="A Mother", relationship="mother",
        phone="9876511111",
    )
    db_session.flush()

    mother = Person.query.filter_by(tenant_id=tenant.id, full_name="A Mother").first()

    assert children_of(father)[0].id == student.id
    assert children_of(mother)[0].id == student.id
    assert father.id != mother.id


def test_a_family_relationship_is_not_an_account(db_session):
    """PARENT-3. Recording a father creates a father, not a login."""
    tenant = _school(db_session)
    student, child_person = _child(db_session, tenant)

    parent = _parent_of(db_session, tenant, child_person)

    assert User.query.filter_by(tenant_id=tenant.id, person_id=parent.id).count() == 0


def test_removing_one_child_leaves_the_parent_and_the_others(db_session):
    """The account hangs off the Person, not off any child."""
    tenant = _school(db_session)
    first, first_person = _child(db_session, tenant, name="Child One")
    parent = _parent_of(
        db_session, tenant, first_person, name="Meera Shah", phone="9876522222"
    )
    second, second_person = _child(db_session, tenant, name="Child Two")
    record_family_member(
        # The same role as the first membership: the person matcher keys on
        # (role, contact, name), so "father Meera" and "mother Meera" are two
        # different people — correctly, and not what this test is about.
        tenant.id, second_person.id, name="Meera Shah", relationship="father",
        phone="9876522222",
    )
    db_session.flush()
    provision_parent_login(parent, email="meera@example.test")
    db_session.flush()

    # The school removes the first child's membership.
    membership = FamilyMember.query.filter_by(
        tenant_id=tenant.id, person_id=first_person.id
    ).first()
    db.session.delete(membership)
    db_session.flush()

    assert Person.query.filter_by(id=parent.id).first() is not None
    assert User.query.filter_by(tenant_id=tenant.id, person_id=parent.id).count() == 1
    remaining = [s.id for s in children_of(parent)]
    assert remaining == [second.id]


# ---------------------------------------------------------------------------
# The account is reused, never duplicated
# ---------------------------------------------------------------------------

def test_a_teacher_who_becomes_a_parent_keeps_one_account(db_session):
    """PARENT-11 and A1. Two accounts would mean two contexts for one human."""
    tenant = _school(db_session)
    teacher = make_user(db_session, tenant, password="Password123", email="ms.rao@school.test")
    grant_permissions(db_session, tenant, teacher, ("student.read.all",))
    student, child_person = _child(db_session, tenant)

    # The same Person is later recorded as a parent.
    from modules.people.models import FAMILY_ROLE_MOTHER, Family, FamilyMember as FM

    family = FamilyMember.query.filter_by(
        tenant_id=tenant.id, person_id=child_person.id
    ).first()
    if family is None:
        household = Family(id=new_id("f-"), tenant_id=tenant.id)
        db_session.add(household)
        db_session.flush()
        db_session.add(
            FM(
                id=new_id("fm-"),
                tenant_id=tenant.id,
                family_id=household.id,
                person_id=child_person.id,
                relationship="child",
            )
        )
        family_id = household.id
    else:
        family_id = family.family_id
    db_session.add(
        FM(
            id=new_id("fm-"),
            tenant_id=tenant.id,
            family_id=family_id,
            person_id=teacher.person_id,
            relationship=FAMILY_ROLE_MOTHER,
        )
    )
    db_session.flush()

    result = provision_parent_login(teacher.person, email="ms.rao@school.test")
    db_session.flush()

    assert result.reused_existing_account is True
    assert result.created_account is False
    assert result.password is None  # their existing one still works
    assert User.query.filter_by(tenant_id=tenant.id, person_id=teacher.person_id).count() == 1
    assert {SUBJECT_STAFF, SUBJECT_PARENT} <= subject_kinds(teacher)


def test_the_one_account_per_person_invariant_still_bites(db_session):
    """A1 is enforced by the database and the flush guard, not by politeness."""
    tenant = _school(db_session)
    student, child_person = _child(db_session, tenant)
    parent = _parent_of(db_session, tenant, child_person)
    provision_parent_login(parent, email="one@example.test")
    db_session.flush()

    with pytest.raises(AccountAlreadyExists):
        db_session.add(
            User(
                id=new_id("u-"),
                tenant_id=tenant.id,
                person_id=parent.id,
                email="second@example.test",
                name="A Second Account",
            )
        )
        db_session.flush()


# ---------------------------------------------------------------------------
# Provisioning
# ---------------------------------------------------------------------------

def test_provisioning_issues_a_password_once(db_session):
    tenant = _school(db_session)
    student, child_person = _child(db_session, tenant)
    parent = _parent_of(db_session, tenant, child_person)

    result = provision_parent_login(parent, email="parent@example.test")
    db_session.flush()

    assert result.created_account is True
    assert result.password
    assert result.account.check_password(result.password)
    # And the email identifier exists, through the existing A2 machinery.
    assert AccountIdentifier.query.filter_by(
        account_id=result.account.id, identifier_type="email"
    ).count() == 1


def test_a_school_sharing_one_login_cannot_provision_a_parent(db_session):
    """PARENT-8 read the other way: the mode is what makes this possible."""
    tenant = _school(db_session, separate=False)
    student, child_person = _child(db_session, tenant)
    parent = _parent_of(db_session, tenant, child_person)

    with pytest.raises(ParentProvisioningError):
        provision_parent_login(parent, email="parent@example.test")


def test_somebody_who_is_not_a_parent_cannot_be_given_a_parent_login(db_session):
    tenant = _school(db_session)
    stranger = Person(id=new_id("p-"), tenant_id=tenant.id, full_name="A Stranger")
    db_session.add(stranger)
    db_session.flush()

    with pytest.raises(ParentProvisioningError):
        provision_parent_login(stranger, email="stranger@example.test")


def test_a_parent_with_no_email_gets_no_login_and_no_invented_one(db_session):
    """NFR-3. A synthesized address is a fake identity that would then receive
    password resets and audit attribution for a real person."""
    tenant = _school(db_session)
    student, child_person = _child(db_session, tenant)
    parent = _parent_of(db_session, tenant, child_person)

    with pytest.raises(ParentProvisioningError):
        provision_parent_login(parent, email="")

    assert User.query.filter_by(tenant_id=tenant.id, person_id=parent.id).count() == 0
    # The relationship survives untouched — authentication is optional.
    assert is_a_parent(parent) is True
    assert len(children_of(parent)) == 1


def test_a_child_s_address_is_not_borrowed_for_their_parent(db_session):
    tenant = _school(db_session)
    student, child_person = _child(db_session, tenant)
    child_account = make_user(db_session, tenant, password="Password123", email="pupil@example.test")
    student.user_id = child_account.id
    db_session.flush()
    parent = _parent_of(db_session, tenant, child_person)

    with pytest.raises(ParentProvisioningError):
        provision_parent_login(parent, email="pupil@example.test")


def test_provisioning_twice_does_not_make_a_second_account(db_session):
    tenant = _school(db_session)
    student, child_person = _child(db_session, tenant)
    parent = _parent_of(db_session, tenant, child_person)

    first = provision_parent_login(parent, email="again@example.test")
    db_session.flush()
    second = provision_parent_login(parent, email="again@example.test")
    db_session.flush()

    assert first.account.id == second.account.id
    assert second.password is None
    assert User.query.filter_by(tenant_id=tenant.id, person_id=parent.id).count() == 1


def test_a_parent_password_says_nothing_about_the_family(db_session):
    """A5 — the existing generator, not a new one built from the child."""
    tenant = _school(db_session)
    student, child_person = _child(db_session, tenant, name="Aarav Patel")
    parent = _parent_of(db_session, tenant, child_person, name="Nikhil Patel")

    password = provision_parent_login(parent, email="nikhil@example.test").password

    for leaked in ("Patel", "Aarav", "Nikhil", student.admission_number):
        assert leaked.lower() not in password.lower()


# ---------------------------------------------------------------------------
# Subject kinds
# ---------------------------------------------------------------------------

def test_a_parent_is_a_subject_kind_only_under_separate_logins(db_session):
    """PARENT-4. Relationship-derived, and gated on the school's choice."""
    from modules.auth.policy_models import TenantAuthPolicy

    tenant = _school(db_session, separate=False)
    student, child_person = _child(db_session, tenant)
    parent = _parent_of(db_session, tenant, child_person)
    account = provision_parent_login_forcing_mode(db_session, tenant, parent)

    assert SUBJECT_PARENT not in subject_kinds(account)

    policy = TenantAuthPolicy.query.filter_by(tenant_id=tenant.id).first()
    policy.family_access_mode = FAMILY_ACCESS_SEPARATE
    db_session.flush()
    db_session.refresh(account)

    assert SUBJECT_PARENT in subject_kinds(account)


def test_the_parent_role_is_now_reachable_and_only_under_separate_logins(db_session):
    """It was seeded into every school and could be held by nobody: the
    catalogue declared no relationship for it to be implied from."""
    from modules.auth.policy_models import TenantAuthPolicy
    from modules.rbac.authority_service import authority_profiles_for_person
    from modules.rbac.role_seeder import seed_roles_for_tenant

    tenant = _school(db_session, separate=False)
    seed_roles_for_tenant(tenant.id)
    db_session.flush()
    student, child_person = _child(db_session, tenant)
    parent = _parent_of(db_session, tenant, child_person)

    shared = {r.name for r in authority_profiles_for_person(parent.id)}
    assert "Parent" not in shared

    policy = TenantAuthPolicy.query.filter_by(tenant_id=tenant.id).first()
    policy.family_access_mode = FAMILY_ACCESS_SEPARATE
    db_session.flush()

    separate = {r.name for r in authority_profiles_for_person(parent.id)}
    assert "Parent" in separate


# ---------------------------------------------------------------------------
# The default school is untouched
# ---------------------------------------------------------------------------

def test_nothing_changes_for_a_school_that_shares_one_login(db_session):
    """PARENT-7 and NFR-1 — the regression that must hold on deployment."""
    from modules.rbac.authority_service import authority_profiles_for_person

    tenant = _school(db_session, separate=False)
    student, child_person = _child(db_session, tenant)
    parent = _parent_of(db_session, tenant, child_person)
    account = provision_parent_login_forcing_mode(db_session, tenant, parent)

    assert SUBJECT_PARENT not in subject_kinds(account)
    assert "Parent" not in {r.name for r in authority_profiles_for_person(parent.id)}
    with pytest.raises(ParentProvisioningError):
        provision_parent_login(parent, email="nope@example.test")


def test_a_school_defaults_to_sharing_one_login(db_session):
    from modules.auth.policy import family_access_mode

    tenant = make_tenant(db_session)
    ensure_default_policy(tenant.id)

    assert family_access_mode(tenant.id) == FAMILY_ACCESS_SHARED


# ---------------------------------------------------------------------------
# Switching modes destroys nothing
# ---------------------------------------------------------------------------

def test_turning_separate_logins_on_provisions_nobody(db_session):
    """PARENT-8. The mode makes provisioning *possible*, never automatic."""
    from modules.auth.policy_models import TenantAuthPolicy

    tenant = _school(db_session, separate=False)
    for label in ("One", "Two"):
        student, person = _child(db_session, tenant, name=label)
        _parent_of(db_session, tenant, person, name=f"Parent {label}")
    db_session.flush()
    before = User.query.filter_by(tenant_id=tenant.id).count()

    policy = TenantAuthPolicy.query.filter_by(tenant_id=tenant.id).first()
    policy.family_access_mode = FAMILY_ACCESS_SEPARATE
    db_session.flush()

    assert User.query.filter_by(tenant_id=tenant.id).count() == before


def test_turning_separate_logins_off_destroys_nothing(db_session):
    """PARENT-9. Expand before contract: a policy change must not delete
    identity."""
    from modules.auth.policy_models import TenantAuthPolicy
    from modules.auth.models import Session

    tenant = _school(db_session)
    student, child_person = _child(db_session, tenant)
    parent = _parent_of(db_session, tenant, child_person)
    result = provision_parent_login(parent, email="stays@example.test")
    db_session.add(
        Session(
            id=new_id("sess-"),
            tenant_id=tenant.id,
            user_id=result.account.id,
            refresh_token=new_id("rt-"),
        )
    )
    db_session.flush()
    account_id = result.account.id

    policy = TenantAuthPolicy.query.filter_by(tenant_id=tenant.id).first()
    policy.family_access_mode = FAMILY_ACCESS_SHARED
    db_session.flush()

    account = User.query.filter_by(id=account_id).first()
    assert account is not None
    assert account.deleted_at is None
    assert AccountIdentifier.query.filter_by(account_id=account_id).count() >= 1
    assert Session.query.filter_by(user_id=account_id, revoked=False).count() == 1
    assert is_a_parent(parent) is True
    # But they are no longer a parent authentication subject.
    assert SUBJECT_PARENT not in subject_kinds(account)


# ---------------------------------------------------------------------------
# Whose child is this?
# ---------------------------------------------------------------------------

def test_a_parent_reaches_both_of_their_children(db_session):
    tenant = _school(db_session)
    first, first_person = _child(db_session, tenant, name="First")
    parent = _parent_of(
        db_session, tenant, first_person, name="Anita Rao", phone="9876533333"
    )
    second, second_person = _child(db_session, tenant, name="Second")
    record_family_member(
        tenant.id, second_person.id, name="Anita Rao", relationship="father",
        phone="9876533333",
    )
    db_session.flush()
    account = provision_parent_login(parent, email="anita@example.test").account
    db_session.flush()

    assert may_access_student(account, first.id) is True
    assert may_access_student(account, second.id) is True


def test_a_parent_cannot_reach_a_child_who_is_not_theirs(db_session):
    """PARENT-10."""
    tenant = _school(db_session)
    mine, my_person = _child(db_session, tenant, name="Mine")
    parent = _parent_of(db_session, tenant, my_person)
    stranger, _ = _child(db_session, tenant, name="Somebody Else's")
    account = provision_parent_login(parent, email="p@example.test").account
    db_session.flush()

    assert may_access_student(account, mine.id) is True
    assert may_access_student(account, stranger.id) is False


def test_a_parent_cannot_reach_a_child_at_another_school(db_session):
    """PARENT-5. The join runs through a family, and a family belongs to a
    school — there is no path that could return somebody else's roll."""
    ours = _school(db_session)
    theirs = _school(db_session)
    mine, my_person = _child(db_session, ours, name="Mine")
    parent = _parent_of(db_session, ours, my_person)
    elsewhere, _ = _child(db_session, theirs, name="Elsewhere")
    account = provision_parent_login(parent, email="p2@example.test").account
    db_session.flush()

    assert may_access_student(account, elsewhere.id) is False
    assert [s.id for s in children_of_account(account)] == [mine.id]


def test_a_parent_whose_last_relationship_went_reaches_nobody(db_session):
    tenant = _school(db_session)
    student, child_person = _child(db_session, tenant)
    parent = _parent_of(db_session, tenant, child_person)
    account = provision_parent_login(parent, email="p3@example.test").account
    db_session.flush()

    for membership in FamilyMember.query.filter_by(
        tenant_id=tenant.id, person_id=parent.id
    ).all():
        db.session.delete(membership)
    db_session.flush()
    db_session.refresh(parent)

    assert children_of_account(account) == []
    assert may_access_student(account, student.id) is False


def test_somebody_who_is_not_a_parent_has_no_children(db_session):
    tenant = _school(db_session)
    teacher = make_user(db_session, tenant, password="Password123")
    grant_permissions(db_session, tenant, teacher, ("student.read.all",))

    assert children_of_account(teacher) == []
