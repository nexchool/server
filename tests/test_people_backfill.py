"""Building the People model from v1 data (ADR-010)."""

from __future__ import annotations

import uuid

import pytest

from modules.people.backfill import backfill_tenant
from modules.people.models import (
    FAMILY_ROLE_CHILD,
    FAMILY_ROLE_FATHER,
    FAMILY_ROLE_MOTHER,
    Family,
    FamilyMember,
    Person,
)

HOUSEHOLD_PHONE = "9876543210"
FATHER_PHONE = "9811111111"
MOTHER_PHONE = "9822222222"


def _add_student(db_session, tenant, *, name, **parent_columns):
    """Create the v1 (User, Student) pair a backfill would find."""
    from modules.auth.models import User
    from modules.students.models import Student

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

    # Identity lives on the Person now (migration 090); the family columns are
    # still on the student row, which is what the family backfill reads.
    identity = {
        "date_of_birth": parent_columns.pop("date_of_birth", None),
        "gender": parent_columns.pop("gender", None),
        "phone_number": parent_columns.pop("phone", None),
        "address": parent_columns.pop("address", None),
        "aadhaar_number": parent_columns.pop("aadhar_number", None),
    }

    student = Student(
        id=f"s-{suffix}",
        tenant_id=tenant.id,
        user_id=user.id,
        admission_number=f"ADM-{suffix}",
        **parent_columns,
    )
    db_session.add(student)
    db_session.flush()

    for field, value in identity.items():
        if value is not None:
            setattr(student.person, field, value)
    db_session.flush()
    return student


def _people(tenant):
    return Person.query.filter(Person.tenant_id == tenant.id).all()


def _members(tenant, relationship):
    return FamilyMember.query.filter(
        FamilyMember.tenant_id == tenant.id,
        FamilyMember.relationship == relationship,
    ).all()


# ---------------------------------------------------------------------------
# Accounts become people
# ---------------------------------------------------------------------------

def test_every_account_gets_a_person(db_session, tenant):
    from modules.auth.models import User

    user = User(
        id=f"u-{uuid.uuid4().hex[:8]}",
        tenant_id=tenant.id,
        email="principal@test.school",
        password_hash="x" * 60,
        name="Meera Shah",
    )
    db_session.add(user)
    db_session.flush()

    backfill_tenant(tenant.id)

    assert user.person_id is not None
    assert Person.query.get(user.person_id).full_name == "Meera Shah"


def test_a_person_takes_the_identity_the_student_row_was_holding(db_session, tenant):
    from datetime import date

    student = _add_student(
        db_session,
        tenant,
        name="Aarav Patel",
        date_of_birth=date(2014, 5, 2),
        gender="male",
        phone="9800000000",
        address="12 Ring Road",
    )

    backfill_tenant(tenant.id)

    from modules.auth.models import User

    person = Person.query.get(User.query.get(student.user_id).person_id)
    assert person.date_of_birth == date(2014, 5, 2)
    assert person.gender == "male"
    assert person.phone_number == "9800000000"
    assert person.address == "12 Ring Road"


def test_an_account_without_a_name_still_produces_a_named_person(db_session, tenant):
    from modules.auth.models import User

    user = User(
        id=f"u-{uuid.uuid4().hex[:8]}",
        tenant_id=tenant.id,
        email="nameless@test.school",
        password_hash="x" * 60,
        name=None,
    )
    db_session.add(user)
    db_session.flush()

    backfill_tenant(tenant.id)

    assert Person.query.get(user.person_id).full_name == "nameless"


# ---------------------------------------------------------------------------
# Siblings
# ---------------------------------------------------------------------------

def test_siblings_share_one_family_and_one_set_of_parents(db_session, tenant):
    parents = {
        "father_name": "Rajesh Patel",
        "father_phone": FATHER_PHONE,
        "mother_name": "Nita Patel",
        "mother_phone": MOTHER_PHONE,
    }
    _add_student(db_session, tenant, name="Aarav Patel", **parents)
    _add_student(db_session, tenant, name="Isha Patel", **parents)

    backfill_tenant(tenant.id)

    families = Family.query.filter(Family.tenant_id == tenant.id).all()
    assert len(families) == 1

    fathers = _members(tenant, FAMILY_ROLE_FATHER)
    mothers = _members(tenant, FAMILY_ROLE_MOTHER)
    children = _members(tenant, FAMILY_ROLE_CHILD)

    assert len(fathers) == 1
    assert len(mothers) == 1
    assert len(children) == 2
    assert {child.family_id for child in children} == {families[0].id}


def test_a_parent_recorded_differently_for_each_child_is_not_merged(db_session, tenant):
    _add_student(
        db_session,
        tenant,
        name="Aarav Patel",
        father_name="Rajesh Patel",
        father_phone=FATHER_PHONE,
    )
    _add_student(
        db_session,
        tenant,
        name="Isha Patel",
        father_name="R Patel",
        father_phone=FATHER_PHONE,
    )

    report = backfill_tenant(tenant.id)

    assert len(_members(tenant, FAMILY_ROLE_FATHER)) == 2
    assert any(
        suggestion["reason"] == "same_phone_different_name"
        for suggestion in report.suggestions
    )


def test_children_of_different_families_do_not_share_a_family(db_session, tenant):
    _add_student(
        db_session,
        tenant,
        name="Aarav Patel",
        father_name="Rajesh Patel",
        father_phone=FATHER_PHONE,
    )
    _add_student(
        db_session,
        tenant,
        name="Vivaan Shah",
        father_name="Amit Shah",
        father_phone="9833333333",
    )

    backfill_tenant(tenant.id)

    assert len(Family.query.filter(Family.tenant_id == tenant.id).all()) == 2


# ---------------------------------------------------------------------------
# The guard, end to end
# ---------------------------------------------------------------------------

def test_parents_sharing_the_household_phone_remain_two_people(db_session, tenant):
    _add_student(
        db_session,
        tenant,
        name="Aarav Patel",
        father_name="Rajesh Patel",
        father_phone=HOUSEHOLD_PHONE,
        mother_name="Nita Patel",
        mother_phone=HOUSEHOLD_PHONE,
    )

    backfill_tenant(tenant.id)

    father = _members(tenant, FAMILY_ROLE_FATHER)
    mother = _members(tenant, FAMILY_ROLE_MOTHER)

    assert len(father) == 1
    assert len(mother) == 1
    assert father[0].person_id != mother[0].person_id

    names = {Person.query.get(m.person_id).full_name for m in father + mother}
    assert names == {"Rajesh Patel", "Nita Patel"}


# ---------------------------------------------------------------------------
# Repeatability
# ---------------------------------------------------------------------------

def test_running_the_backfill_twice_changes_nothing(db_session, tenant):
    parents = {
        "father_name": "Rajesh Patel",
        "father_phone": FATHER_PHONE,
        "mother_name": "Nita Patel",
        "mother_phone": MOTHER_PHONE,
    }
    _add_student(db_session, tenant, name="Aarav Patel", **parents)
    _add_student(db_session, tenant, name="Isha Patel", **parents)

    backfill_tenant(tenant.id)
    people_after_first = len(_people(tenant))
    families_after_first = len(Family.query.filter(Family.tenant_id == tenant.id).all())
    members_after_first = len(
        FamilyMember.query.filter(FamilyMember.tenant_id == tenant.id).all()
    )

    second = backfill_tenant(tenant.id)

    assert len(_people(tenant)) == people_after_first
    assert len(Family.query.filter(Family.tenant_id == tenant.id).all()) == families_after_first
    assert (
        len(FamilyMember.query.filter(FamilyMember.tenant_id == tenant.id).all())
        == members_after_first
    )
    assert second.people_created == 0
    assert second.families_created == 0


def test_a_student_without_parent_details_gets_no_empty_family(db_session, tenant):
    _add_student(db_session, tenant, name="Aarav Patel")

    backfill_tenant(tenant.id)

    assert Family.query.filter(Family.tenant_id == tenant.id).all() == []
