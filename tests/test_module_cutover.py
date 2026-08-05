"""Students and teachers created today belong to the People model.

Records created before the migration were linked by the backfill. These are the
paths that must produce correct records without it.
"""

from __future__ import annotations

import uuid

import pytest
from flask import g

from modules.people.employment import Staff, StaffEmploymentPeriod
from modules.people.models import FAMILY_ROLE_GUARDIAN, FAMILY_ROLE_UNCLE, FamilyMember
from modules.people.service import family_role_for


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    """The services take their tenant from the request, as the routes do."""
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


@pytest.fixture
def academic_year(db_session, tenant):
    """A student is admitted into a year; creation refuses without one."""
    from datetime import date

    from modules.academics.academic_year.models import AcademicYear

    year = AcademicYear(
        tenant_id=tenant.id,
        name=f"AY-{uuid.uuid4().hex[:6]}",
        start_date=date(2026, 6, 1),
        end_date=date(2027, 3, 31),
    )
    db_session.add(year)
    db_session.flush()
    return year


# ---------------------------------------------------------------------------
# Creating a teacher
# ---------------------------------------------------------------------------

def test_a_new_teacher_is_employed_before_they_teach(ctx, tenant):
    from modules.teachers.services import create_teacher

    result = create_teacher(
        name="Rohit Mehta",
        email=f"{_unique('rohit')}@test.school",
        designation="Senior Teacher",
        date_of_joining="2021-06-01",
    )
    assert result["success"], result

    from modules.teachers.models import Teacher

    teacher = Teacher.query.get(result["teacher"]["id"])
    assert teacher.staff_id is not None

    staff = Staff.query.get(teacher.staff_id)
    assert staff.person_id == teacher.user.person_id
    assert staff.employee_number == teacher.employee_id
    assert staff.designation == "Senior Teacher"


def test_a_new_teacher_gets_an_open_employment_period(ctx, tenant):
    from modules.teachers.services import create_teacher

    result = create_teacher(
        name="Rohit Mehta",
        email=f"{_unique('rohit')}@test.school",
        date_of_joining="2021-06-01",
    )

    from modules.teachers.models import Teacher

    teacher = Teacher.query.get(result["teacher"]["id"])
    period = StaffEmploymentPeriod.query.filter_by(staff_id=teacher.staff_id).one()

    assert str(period.joined_on) == "2021-06-01"
    assert period.is_open


# ---------------------------------------------------------------------------
# Creating a student
# ---------------------------------------------------------------------------

def test_a_new_student_belongs_to_a_person(ctx, tenant, academic_year):
    from modules.students.models import Student
    from modules.students.services import create_student

    result = create_student(
        name="Aarav Patel",
        academic_year_id=academic_year.id,
        guardian_name="Rajesh Patel",
        guardian_relationship="Father",
        guardian_phone="9811111111",
        date_of_birth="2014-05-02",
        gender="male",
        phone="9800000000",
    )
    assert result["success"], result

    student = Student.query.get(result["student"]["id"])
    assert student.person_id == student.user.person_id


def test_the_admission_form_records_identity_on_the_person(ctx, tenant, academic_year):
    from modules.students.models import Student
    from modules.students.services import create_student

    result = create_student(
        name="Aarav Patel",
        academic_year_id=academic_year.id,
        guardian_name="Rajesh Patel",
        guardian_relationship="Father",
        guardian_phone="9811111111",
        date_of_birth="2014-05-02",
        gender="male",
        phone="9800000000",
        address="12 Ring Road",
    )
    assert result["success"], result

    person = Student.query.get(result["student"]["id"]).user.person
    assert str(person.date_of_birth) == "2014-05-02"
    assert person.gender == "male"
    assert person.phone_number == "9800000000"
    assert person.address == "12 Ring Road"


# ---------------------------------------------------------------------------
# Guardians, which is how v1 actually recorded families
# ---------------------------------------------------------------------------

def test_a_guardian_recorded_as_a_father_is_treated_as_one(db_session, tenant):
    from modules.people.models import FAMILY_ROLE_FATHER

    assert family_role_for("Father") == FAMILY_ROLE_FATHER
    assert family_role_for("mother") != FAMILY_ROLE_FATHER


def test_an_unfamiliar_relationship_is_still_a_guardian(db_session, tenant):
    assert family_role_for("family friend") == FAMILY_ROLE_GUARDIAN
    assert family_role_for(None) == FAMILY_ROLE_GUARDIAN
    assert family_role_for("Uncle") == FAMILY_ROLE_UNCLE


def _admit(academic_year, name, **guardian):
    from modules.students.services import create_student

    fields = {
        "guardian_name": "Rajesh Patel",
        "guardian_relationship": "Father",
        "guardian_phone": "9811111111",
    }
    fields.update(guardian)
    result = create_student(name=name, academic_year_id=academic_year.id, **fields)
    assert result["success"], result
    return result["student"]


def test_admission_records_the_family_without_waiting_for_a_migration(
    ctx, tenant, academic_year
):
    from modules.people.models import Person
    from modules.students.models import Student

    student = _admit(academic_year, "Aarav Patel")

    guardian = Person.query.filter_by(
        tenant_id=tenant.id, full_name="Rajesh Patel"
    ).one()
    membership = FamilyMember.query.filter_by(person_id=guardian.id).one()
    assert membership.relationship == "father"

    child_person_id = Student.query.get(student["id"]).person_id
    child = FamilyMember.query.filter_by(person_id=child_person_id).one()
    assert child.family_id == membership.family_id
    assert child.relationship == "child"


def test_a_sibling_admitted_later_joins_the_same_family(ctx, tenant, academic_year):
    from modules.people.models import Family, Person
    from modules.students.models import Student

    first = _admit(academic_year, "Aarav Patel")
    second = _admit(academic_year, "Isha Patel")

    guardians = Person.query.filter_by(
        tenant_id=tenant.id, full_name="Rajesh Patel"
    ).all()
    assert len(guardians) == 1
    assert Family.query.filter_by(tenant_id=tenant.id).count() == 1

    families = {
        FamilyMember.query.filter_by(
            person_id=Student.query.get(child["id"]).person_id
        ).one().family_id
        for child in (first, second)
    }
    assert len(families) == 1


def test_an_unrelated_student_gets_their_own_family(ctx, tenant, academic_year):
    from modules.people.models import Family

    _admit(academic_year, "Aarav Patel")
    _admit(
        academic_year,
        "Vivaan Shah",
        guardian_name="Amit Shah",
        guardian_phone="9833333333",
    )

    assert Family.query.filter_by(tenant_id=tenant.id).count() == 2


def test_a_guardian_written_differently_is_not_assumed_to_be_the_same_person(
    ctx, tenant, academic_year
):
    """The admission path uses the migration's recognition rules, which refuse
    to merge on a shared phone alone."""
    from modules.people.models import Person

    _admit(academic_year, "Aarav Patel")
    _admit(
        academic_year,
        "Isha Patel",
        guardian_name="Nita Patel",
        guardian_relationship="Mother",
        guardian_phone="9811111111",
    )

    assert (
        Person.query.filter_by(tenant_id=tenant.id, full_name="Rajesh Patel").count()
        == 1
    )
    assert (
        Person.query.filter_by(tenant_id=tenant.id, full_name="Nita Patel").count() == 1
    )


def test_the_backfill_records_a_guardian_as_a_person(db_session, tenant):
    from modules.auth.models import User
    from modules.people.backfill import backfill_tenant
    from modules.people.models import Person
    from modules.students.models import Student

    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=f"u-{suffix}",
        tenant_id=tenant.id,
        email=f"{suffix}@test.school",
        password_hash="x" * 60,
        name="Aarav Patel",
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(
        Student(
            id=f"s-{suffix}",
            tenant_id=tenant.id,
            user_id=user.id,
            admission_number=f"ADM-{suffix}",
            guardian_name="Ramesh Joshi",
            guardian_relationship="Grandfather",
            guardian_phone="9876500000",
        )
    )
    db_session.flush()

    backfill_tenant(tenant.id)

    guardian = Person.query.filter_by(
        tenant_id=tenant.id, full_name="Ramesh Joshi"
    ).one()
    membership = FamilyMember.query.filter_by(person_id=guardian.id).one()
    assert membership.relationship == "grandfather"


def test_siblings_with_one_guardian_share_that_guardian(db_session, tenant):
    from modules.auth.models import User
    from modules.people.backfill import backfill_tenant
    from modules.people.models import Person
    from modules.students.models import Student

    guardian = {
        "guardian_name": "Ramesh Joshi",
        "guardian_relationship": "Guardian",
        "guardian_phone": "9876500001",
    }
    for name in ("Aarav Patel", "Isha Patel"):
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
        db_session.add(
            Student(
                id=f"s-{suffix}",
                tenant_id=tenant.id,
                user_id=user.id,
                admission_number=f"ADM-{suffix}",
                **guardian,
            )
        )
    db_session.flush()

    backfill_tenant(tenant.id)

    people = Person.query.filter_by(
        tenant_id=tenant.id, full_name="Ramesh Joshi"
    ).all()
    assert len(people) == 1

    memberships = FamilyMember.query.filter_by(person_id=people[0].id).all()
    assert len(memberships) == 1
