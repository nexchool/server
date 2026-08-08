"""A studentship or an employment does not require a login (migration 094).

ADR-003: authentication is optional. Before this, "no email" minted a
placeholder account nobody could use; now it means no account at all — and
every list, edit and delete path must treat the missing login as normal.
"""

from __future__ import annotations

import uuid

import pytest
from flask import g

from modules.people.employment import Staff, StaffEmploymentPeriod
from modules.people.models import FamilyMember, Person


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


def _admit_without_email(academic_year, **overrides):
    from modules.students.services import create_student

    payload = dict(
        name="Kavya Trivedi",
        academic_year_id=academic_year.id,
        guardian_name="Nilesh Trivedi",
        guardian_relationship="father",
        guardian_phone="9800000001",
        date_of_birth="2015-04-12",
        gender="female",
    )
    payload.update(overrides)
    return create_student(**payload)


def _hire_without_email(**overrides):
    from modules.teachers.services import create_teacher

    payload = dict(
        name="Meera Joshi",
        designation="Assistant Teacher",
        date_of_joining="2024-06-01",
    )
    payload.update(overrides)
    return create_teacher(**payload)


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------

def test_a_student_admitted_without_email_has_no_account(ctx, tenant, academic_year):
    from modules.auth.models import User
    from modules.students.models import Student

    result = _admit_without_email(academic_year)
    assert result["success"], result

    student = Student.query.get(result["student"]["id"])
    assert student.user_id is None
    assert student.user is None

    # The admission itself recorded the human.
    person = Person.query.get(student.person_id)
    assert person.full_name == "Kavya Trivedi"
    assert person.date_of_birth is not None
    assert person.gender == "female"

    # The child belongs to a household, and the guardian named at admission
    # is a member of it and the adult the school calls.
    child_membership = FamilyMember.query.filter_by(
        tenant_id=tenant.id, person_id=person.id
    ).first()
    assert child_membership is not None
    guardians = (
        FamilyMember.query.join(Person, FamilyMember.person_id == Person.id)
        .filter(Person.full_name == "Nilesh Trivedi", Person.tenant_id == tenant.id)
        .all()
    )
    assert any(m.is_primary_contact for m in guardians)

    # No placeholder login was minted.
    assert (
        User.query.filter(
            User.tenant_id == tenant.id, User.email.ilike("%@student.placeholder")
        ).count()
        == 0
    )
    assert "credentials" not in result


def test_an_account_less_student_appears_in_the_list(ctx, tenant, academic_year):
    from modules.students.services import list_students

    result = _admit_without_email(academic_year)
    assert result["success"], result
    admission_number = result["student"]["admission_number"]

    listed = list_students()
    assert admission_number in [i["admission_number"] for i in listed["items"]]

    row = next(
        i for i in listed["items"] if i["admission_number"] == admission_number
    )
    assert row["name"] == "Kavya Trivedi"
    assert row["email"] is None


def test_editing_an_account_less_student_reaches_the_person(
    ctx, tenant, academic_year, db_session
):
    from modules.students.models import Student
    from modules.students.services import update_student

    created = _admit_without_email(academic_year)
    assert created["success"], created
    student_id = created["student"]["id"]

    result = update_student(student_id, name="Kavya T. Trivedi")
    assert result["success"], result

    student = Student.query.get(student_id)
    assert student.person.full_name == "Kavya T. Trivedi"


def test_deleting_an_account_less_student_works(ctx, tenant, academic_year):
    from modules.students.models import Student
    from modules.students.services import delete_student

    created = _admit_without_email(academic_year)
    assert created["success"], created
    student_id = created["student"]["id"]

    result = delete_student(student_id)
    assert result["success"], result
    assert Student.query.get(student_id) is None


def test_a_student_with_email_still_gets_credentials(ctx, tenant, academic_year):
    from modules.students.models import Student

    email = f"{_unique('kavya')}@test.school"
    result = _admit_without_email(academic_year, email=email)
    assert result["success"], result

    assert result["credentials"]["must_reset"] is True
    student = Student.query.get(result["student"]["id"])
    assert student.user is not None
    assert student.user.email == email
    assert student.person_id == student.user.person_id

    # Access is implied by the Student relationship, never granted (migration
    # 087) — the old explicit grant required an employment and failed for
    # every admin-created student login after migration 089.
    from modules.rbac.authority_service import authority_profiles_for_person

    assert "Student" in [
        p.name for p in authority_profiles_for_person(student.person_id)
    ]


# ---------------------------------------------------------------------------
# Teachers
# ---------------------------------------------------------------------------

def test_a_teacher_hired_without_email_has_no_account(ctx, tenant):
    from modules.auth.models import User
    from modules.teachers.models import Teacher

    result = _hire_without_email()
    assert result["success"], result
    assert "credentials" not in result

    teacher = Teacher.query.get(result["teacher"]["id"])
    assert teacher.user_id is None

    # The hire is still a real employment of a real person.
    staff = Staff.query.get(teacher.staff_id)
    assert staff.designation == "Assistant Teacher"
    person = Person.query.get(staff.person_id)
    assert person.full_name == "Meera Joshi"
    periods = StaffEmploymentPeriod.query.filter_by(staff_id=staff.id).all()
    assert any(p.is_open for p in periods)

    # No synthesized login was minted.
    assert (
        User.query.filter(
            User.tenant_id == tenant.id, User.email.ilike("%@teacher.school")
        ).count()
        == 0
    )


def test_an_account_less_teacher_holds_teaching_authority(ctx, tenant):
    from modules.rbac.authority_service import authority_profiles_for_person
    from modules.teachers.models import Teacher

    result = _hire_without_email()
    assert result["success"], result

    teacher = Teacher.query.get(result["teacher"]["id"])
    profiles = authority_profiles_for_person(teacher.staff.person_id)
    assert "Teacher" in [p.name for p in profiles]


def test_an_account_less_teacher_appears_in_the_list(ctx, tenant):
    from modules.teachers.services import list_teachers

    result = _hire_without_email()
    assert result["success"], result
    teacher_id = result["teacher"]["id"]

    listed = list_teachers()
    row = next((i for i in listed["items"] if i["id"] == teacher_id), None)
    assert row is not None, "account-less teacher missing from the list"
    assert row["name"] == "Meera Joshi"
    assert row["email"] is None


def test_search_finds_an_account_less_student(ctx, tenant, academic_year, db_session):
    """Global search reads the Person, not the login (ADR-001)."""
    from modules.auth.models import User
    from modules.search.services import _search_students

    created = _admit_without_email(academic_year)
    assert created["success"], created

    searcher = User(
        tenant_id=tenant.id,
        email=f"{_unique('admin')}@test.school",
        name="Search Admin",
    )
    searcher.set_password("x")
    db_session.add(searcher)
    db_session.flush()

    import modules.search.services as search_services

    original = search_services.has_permission
    search_services.has_permission = lambda *_args, **_kw: True
    try:
        hits = _search_students(searcher, "Kavya", 10)
    finally:
        search_services.has_permission = original

    assert created["student"]["id"] in [h["id"] for h in hits]
    assert any(h["name"] == "Kavya Trivedi" for h in hits)


def test_an_account_less_teacher_is_offered_as_class_teacher(
    ctx, tenant, academic_year, db_session
):
    """The NOT-IN-with-NULL trap must not hide account-less teachers."""
    from modules.classes.models import Class
    from modules.classes.services import get_available_class_teachers
    from modules.teachers.services import create_teacher

    accountless = _hire_without_email()
    assert accountless["success"], accountless

    # A second teacher WITH an account who already holds a class, so the
    # picker's user_id exclusion list is non-empty and NOT IN actually runs —
    # SQL's `NULL NOT IN (...)` is what used to hide the account-less teacher.
    with_account = create_teacher(
        name="Ravi Shah",
        email=f"{_unique('ravi')}@test.school",
        designation="Teacher",
    )
    assert with_account["success"], with_account

    from modules.teachers.models import Teacher

    holder = Teacher.query.get(with_account["teacher"]["id"])
    cls = Class(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        name="Grade 4",
        section="A",
        academic_year_id=academic_year.id,
        teacher_id=holder.id,
    )
    db_session.add(cls)
    db_session.flush()

    offered_ids = {t["id"] for t in get_available_class_teachers()}
    assert accountless["teacher"]["id"] in offered_ids


def test_deleting_an_account_less_teacher_withdraws_authority(ctx, tenant):
    from modules.rbac.authority_service import authority_profiles_for_person
    from modules.teachers.models import Teacher
    from modules.teachers.services import delete_teacher

    result = _hire_without_email()
    assert result["success"], result
    teacher = Teacher.query.get(result["teacher"]["id"])
    person_id = teacher.staff.person_id

    deleted = delete_teacher(result["teacher"]["id"])
    assert deleted["success"], deleted

    assert Teacher.query.get(result["teacher"]["id"]) is None
    assert authority_profiles_for_person(person_id) == []
