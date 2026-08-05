"""Correcting a record corrects the human it describes.

Admission recorded identity and family on the Person from the start, but
editing afterwards wrote only to the student and teacher tables. So a record
was right on the day it was created and drifted from that day on — which is
the drift the read path cannot tolerate once it reads from People.
"""

from __future__ import annotations

import uuid

import pytest
from flask import g

from modules.people.models import (
    FAMILY_ROLE_CHILD,
    FAMILY_ROLE_FATHER,
    FAMILY_ROLE_MOTHER,
    FamilyMember,
    Person,
)


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


@pytest.fixture
def academic_year(db_session, tenant):
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


def _admit(academic_year, *, name="Aarav Patel", father="Rajesh Patel", **extra):
    from modules.students.services import create_student

    result = create_student(
        name=name,
        academic_year_id=academic_year.id,
        father_name=father,
        father_phone="9811111111",
        # Admission insists on a guardian. Schools overwhelmingly name the
        # father, which is what the real records show, so the tests admit
        # students the way the school does.
        guardian_name=father,
        guardian_relationship="Father",
        guardian_phone="9811111111",
        **extra,
    )
    assert result["success"], result

    from modules.students.models import Student

    return Student.query.get(result["student"]["id"])


def _member(student, role):
    child = FamilyMember.query.filter_by(
        person_id=student.person_id, relationship=FAMILY_ROLE_CHILD
    ).first()
    if child is None:
        return None
    return FamilyMember.query.filter_by(
        family_id=child.family_id, relationship=role
    ).first()


# ---------------------------------------------------------------------------
# The student's own facts
# ---------------------------------------------------------------------------

def test_correcting_a_students_details_corrects_the_person(ctx, tenant, academic_year):
    from modules.students.services import update_student

    student = _admit(academic_year, phone="9800000000")

    assert update_student(student.id, phone="9899999999", gender="male")["success"]

    assert student.person.phone_number == "9899999999"
    assert student.person.gender == "male"


def test_a_correction_overwrites_what_was_already_known(ctx, tenant, academic_year):
    """fill_blank_identity would keep the old value; an edit is not a discovery."""
    from modules.students.services import update_student

    student = _admit(academic_year, address="12 Old Road")
    assert student.person.address == "12 Old Road"

    update_student(student.id, address="88 New Road")

    assert student.person.address == "88 New Road"


def test_an_edit_that_omits_a_field_leaves_it_alone(ctx, tenant, academic_year):
    from modules.students.services import update_student

    student = _admit(academic_year, phone="9800000000")

    update_student(student.id, roll_number="14")

    assert student.person.phone_number == "9800000000"


# ---------------------------------------------------------------------------
# The family
# ---------------------------------------------------------------------------

def test_correcting_a_fathers_phone_corrects_it_for_every_child(
    ctx, tenant, academic_year
):
    """One human, one record — that is the point of holding people once."""
    from modules.students.services import update_student

    older = _admit(academic_year, name="Aarav Patel")
    younger = _admit(academic_year, name="Isha Patel")

    father = _member(older, FAMILY_ROLE_FATHER)
    assert father is not None
    assert _member(younger, FAMILY_ROLE_FATHER).person_id == father.person_id

    update_student(older.id, father_phone="9700000000")

    assert Person.query.get(father.person_id).phone_number == "9700000000"


def test_naming_a_different_father_moves_the_household_rather_than_renaming_him(
    ctx, tenant, academic_year
):
    """Renaming would rewrite him on his other children too."""
    from modules.students.services import update_student

    student = _admit(academic_year, father="Rajesh Patel")
    was = _member(student, FAMILY_ROLE_FATHER)
    original_person_id = was.person_id

    update_student(student.id, father_name="Suresh Patel", father_phone="9700000000")

    now = _member(student, FAMILY_ROLE_FATHER)
    assert now.person_id != original_person_id
    assert Person.query.get(now.person_id).full_name == "Suresh Patel"
    # The man who was recorded before still exists, with his name intact.
    assert Person.query.get(original_person_id).full_name == "Rajesh Patel"


def test_an_edit_that_names_nobody_still_reaches_the_father_on_record(
    ctx, tenant, academic_year
):
    """The edit form sends a cleared phone without resending the name."""
    from modules.students.services import update_student

    student = _admit(academic_year, father="Rajesh Patel")
    father = _member(student, FAMILY_ROLE_FATHER)

    update_student(student.id, father_phone="9700000000")

    assert _member(student, FAMILY_ROLE_FATHER).person_id == father.person_id
    assert Person.query.get(father.person_id).phone_number == "9700000000"


def test_adding_a_mother_later_records_her(ctx, tenant, academic_year):
    from modules.students.services import update_student

    student = _admit(academic_year)
    assert _member(student, FAMILY_ROLE_MOTHER) is None

    update_student(student.id, mother_name="Sunita Patel", mother_phone="9600000000")

    mother = _member(student, FAMILY_ROLE_MOTHER)
    assert mother is not None
    assert Person.query.get(mother.person_id).full_name == "Sunita Patel"


# ---------------------------------------------------------------------------
# Teachers
# ---------------------------------------------------------------------------

def _appoint(**extra):
    from modules.teachers.models import Teacher
    from modules.teachers.services import create_teacher

    result = create_teacher(
        name="Rohit Mehta",
        email=f"{_unique('rohit')}@test.school",
        date_of_joining="2021-06-01",
        **extra,
    )
    assert result["success"], result
    return Teacher.query.get(result["teacher"]["id"])


def test_correcting_a_teachers_details_corrects_the_person(ctx, tenant):
    from modules.teachers.services import update_teacher

    teacher = _appoint(phone="9811111111")

    update_teacher(teacher.id, phone="9700000000", address="4 Station Road")

    assert teacher.staff.person.phone_number == "9700000000"
    assert teacher.staff.person.address == "4 Station Road"


def test_marking_a_teacher_inactive_ends_their_employment(ctx, tenant):
    """And with it, the authority the employment was holding (ADR-013)."""
    from modules.teachers.services import update_teacher

    teacher = _appoint()
    assert teacher.staff.is_employed

    update_teacher(teacher.id, status="inactive")

    assert not teacher.staff.is_employed


def test_an_edit_does_not_quietly_reinstate_a_suspended_teacher(ctx, tenant):
    """v1 calls suspension "inactive" too; saving the form must not undo it."""
    from modules.people.employment import EMPLOYMENT_STATUS_SUSPENDED
    from modules.teachers.services import update_teacher

    teacher = _appoint()
    teacher.staff.employment_status = EMPLOYMENT_STATUS_SUSPENDED

    update_teacher(teacher.id, status="active", phone="9700000000")

    assert teacher.staff.employment_status == EMPLOYMENT_STATUS_SUSPENDED


# ---------------------------------------------------------------------------
# What is shown and what is filtered must be the same fact
# ---------------------------------------------------------------------------

def test_a_teacher_marked_inactive_in_bulk_is_inactive_everywhere(ctx, tenant):
    """Display reads the employment; the filter must read it too.

    Reading one and filtering the other lets a teacher be shown as inactive
    while still turning up under "active" — and still being offered as a class
    teacher.
    """
    from modules.teachers.services import bulk_update_teacher_status, list_teachers

    teacher = _appoint()

    assert bulk_update_teacher_status([teacher.id], "inactive")["success"]

    assert teacher.to_dict()["status"] == "inactive"
    assert not teacher.staff.is_employed

    active = list_teachers(status="active")["items"]
    assert teacher.id not in {t["id"] for t in active}

    inactive = list_teachers(status="inactive")["items"]
    assert teacher.id in {t["id"] for t in inactive}


def test_a_teacher_who_has_left_is_not_offered_as_a_class_teacher(ctx, tenant):
    from modules.classes.services import _currently_teaching
    from modules.teachers.services import bulk_update_teacher_status

    teacher = _appoint()
    assert teacher.id in {t.id for t in _currently_teaching().all()}

    bulk_update_teacher_status([teacher.id], "inactive")

    assert teacher.id not in {t.id for t in _currently_teaching().all()}


# ---------------------------------------------------------------------------
# Every path that creates or renames someone reaches the person
# ---------------------------------------------------------------------------

def test_renaming_yourself_renames_the_person_not_just_the_login(
    ctx, tenant, db_session
):
    """A name belongs to the human, not to one of their logins (ADR-001).

    Otherwise the teachers list keeps showing the old name — it reads the
    person — while the account shows the new one.
    """
    from modules.auth.models import User

    user = User(
        tenant_id=tenant.id,
        email=f"{_unique('rename')}@test.school",
        password_hash="x" * 60,
        name="Rohit Mehta",
    )
    db_session.add(user)
    db_session.flush()

    from modules.people.service import revise_identity

    user.name = "Rohit Mehta-Shah"
    revise_identity(user.person, {"full_name": "Rohit Mehta-Shah"})

    assert user.person.full_name == "Rohit Mehta-Shah"


def test_an_imported_students_details_are_not_blank(ctx, tenant, academic_year):
    """The importer creates what admission creates, so it must fill the same
    places — the payload reads the person, and a row that skipped it shows
    empty fields for data the school supplied."""
    from modules.students.bulk_student_import_service import (
        _record_the_person_behind_the_row,
    )

    student = _admit(academic_year)
    student.person.date_of_birth = None
    student.person.gender = None
    student.person.phone_number = None

    _record_the_person_behind_the_row(
        student,
        {
            "date_of_birth": __import__("datetime").date(2014, 5, 2),
            "gender": "male",
            "phone": "9800000000",
            "aadhar_number": "111122223333",
            "mother_name": "Sunita Patel",
            "mother_phone": "9600000000",
        },
    )

    payload = student.to_dict(include_profile_picture=False)
    assert payload["date_of_birth"] == "2014-05-02"
    assert payload["gender"] == "male"
    assert payload["phone"] == "9800000000"
    assert payload["aadhar_number"] == "111122223333"
    assert _member(student, FAMILY_ROLE_MOTHER) is not None
