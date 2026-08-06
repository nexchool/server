"""Two columns are caches. They must never become a second answer.

`students.class_id` mirrors the current academic enrollment.
`classes.teacher_id` mirrors the current class-teacher assignment.

Both are allowed (ADR-014): they make a listing fast, and a listing that has to
join to name a child's class on every row is a listing nobody wants. What is not
allowed is a cache drifting from its owner, because then the system has two
answers to one question and no way to tell which is right.

Correct-by-inspection is not correct. These tests exercise every path that
writes a cache and assert the owner agrees afterwards, so a future path that
sets one and forgets the other fails here rather than in a school's data.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from flask import g

from modules.academics.backbone.models import (
    ClassTeacherAssignment,
    StudentClassEnrollment,
)
from modules.auth.models import User
from modules.classes.models import Class
from modules.students.models import Student
from modules.teachers.models import Teacher


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


@pytest.fixture
def academic_year(db_session, tenant):
    from modules.academics.academic_year.models import AcademicYear

    year = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name=f"AY-{uuid.uuid4().hex[:6]}",
        start_date=date(2026, 6, 1), end_date=date(2027, 3, 31),
    )
    db_session.add(year)
    db_session.flush()
    return year


@pytest.fixture
def classes(db_session, tenant, academic_year):
    made = []
    for section in ("A", "B"):
        cls = Class(
            id=_new_id("c-"), tenant_id=tenant.id, name="Grade 4", section=section,
            academic_year_id=academic_year.id,
        )
        db_session.add(cls)
        made.append(cls)
    db_session.flush()
    return made


def _student(db_session, tenant, academic_year):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=_new_id("u-"), tenant_id=tenant.id, email=f"{suffix}@test.school",
        password_hash="x" * 60, name=f"Child {suffix}",
    )
    db_session.add(user)
    db_session.flush()
    student = Student(
        id=_new_id("s-"), tenant_id=tenant.id, user_id=user.id,
        person_id=user.person_id, admission_number=f"ADM-{suffix}",
        academic_year_id=academic_year.id,
    )
    db_session.add(student)
    db_session.flush()
    return student


def _teacher(db_session, tenant):
    from tests.conftest import employ_for

    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=_new_id("u-"), tenant_id=tenant.id, email=f"t-{suffix}@test.school",
        password_hash="x" * 60, name=f"Teacher {suffix}",
    )
    db_session.add(user)
    db_session.flush()
    teacher = Teacher(
        id=_new_id("t-"), tenant_id=tenant.id, user_id=user.id,
        staff_id=employ_for(user, employee_number=f"EMP-{suffix}").id,
    )
    db_session.add(teacher)
    db_session.flush()
    return teacher


def _current_enrollment(student):
    return StudentClassEnrollment.query.filter_by(
        student_id=student.id, is_current=True
    ).first()


def _responsible_for(cls):
    return ClassTeacherAssignment.query.filter_by(
        class_id=cls.id, role="primary", is_active=True, deleted_at=None
    ).first()


# ---------------------------------------------------------------------------
# students.class_id follows the enrollment
# ---------------------------------------------------------------------------

def test_admitting_a_child_leaves_the_cache_agreeing(
    ctx, tenant, db_session, classes, academic_year
):
    from modules.students.class_enrollment_service import assign_student_to_class

    student = _student(db_session, tenant, academic_year)
    first, _ = classes

    assign_student_to_class(student.id, first.id, academic_year.id, commit=False)
    db_session.flush()

    assert _current_enrollment(student).class_id == student.class_id == first.id


def test_moving_a_child_moves_the_cache_with_them(
    ctx, tenant, db_session, classes, academic_year
):
    """The failure this guards: the enrollment moves and the cache does not,
    so the child appears in two classes depending on which is asked."""
    from modules.students.class_enrollment_service import assign_student_to_class

    student = _student(db_session, tenant, academic_year)
    first, second = classes
    assign_student_to_class(student.id, first.id, academic_year.id, commit=False)
    db_session.flush()

    assign_student_to_class(student.id, second.id, academic_year.id, commit=False)
    db_session.flush()

    assert _current_enrollment(student).class_id == second.id
    assert student.class_id == second.id


def test_taking_a_child_out_of_a_class_clears_the_cache(
    ctx, tenant, db_session, classes, academic_year
):
    from modules.students.class_enrollment_service import assign_student_to_class

    student = _student(db_session, tenant, academic_year)
    first, _ = classes
    assign_student_to_class(student.id, first.id, academic_year.id, commit=False)
    db_session.flush()

    assign_student_to_class(student.id, None, academic_year.id, commit=False)
    db_session.flush()

    assert student.class_id is None
    assert _current_enrollment(student) is None


def test_no_student_anywhere_disagrees_with_their_enrollment(
    ctx, tenant, db_session, classes, academic_year
):
    """The invariant stated once, over everything the other tests created."""
    from modules.students.class_enrollment_service import assign_student_to_class

    first, second = classes
    for target in (first, second, first):
        student = _student(db_session, tenant, academic_year)
        assign_student_to_class(student.id, target.id, academic_year.id, commit=False)
    db_session.flush()

    disagreeing = [
        student
        for student in Student.query.filter_by(tenant_id=tenant.id).all()
        if (_current_enrollment(student).class_id if _current_enrollment(student) else None)
        != student.class_id
    ]

    assert not disagreeing, f"{len(disagreeing)} student(s) disagree with their enrollment"


# ---------------------------------------------------------------------------
# classes.teacher_id follows the assignment
# ---------------------------------------------------------------------------

def test_naming_a_class_teacher_leaves_the_cache_agreeing(
    ctx, tenant, db_session, classes
):
    from modules.classes.services import assign_teacher_to_class

    first, _ = classes
    teacher = _teacher(db_session, tenant)

    result = assign_teacher_to_class(first.id, teacher.id, is_class_teacher=True)
    assert result["success"], result

    assert _responsible_for(first).teacher_id == teacher.id
    assert first.teacher_id == teacher.user_id


def test_replacing_a_class_teacher_moves_the_cache(ctx, tenant, db_session, classes):
    from modules.classes.services import assign_teacher_to_class

    first, _ = classes
    was = _teacher(db_session, tenant)
    now = _teacher(db_session, tenant)
    assign_teacher_to_class(first.id, was.id, is_class_teacher=True)

    assign_teacher_to_class(first.id, now.id, is_class_teacher=True)

    assert _responsible_for(first).teacher_id == now.id
    assert first.teacher_id == now.user_id


def test_the_class_form_records_the_responsibility_too(ctx, tenant, db_session, classes):
    """Setting a class teacher on the class form used to write only the cache.

    That is how this concept came to have two homes, so it is guarded here.
    """
    from modules.classes.services import update_class

    first, _ = classes
    teacher = _teacher(db_session, tenant)

    result = update_class(first.id, teacher_id=teacher.user_id)
    assert result["success"], result
    db_session.flush()

    assert _responsible_for(first).teacher_id == teacher.id
    assert first.teacher_id == teacher.user_id


def test_removing_a_class_teacher_clears_the_cache(ctx, tenant, db_session, classes):
    from modules.classes.services import assign_teacher_to_class, remove_teacher_from_class

    first, _ = classes
    teacher = _teacher(db_session, tenant)
    assign_teacher_to_class(first.id, teacher.id, is_class_teacher=True)

    remove_teacher_from_class(first.id, teacher.id)
    db_session.flush()

    assert _responsible_for(first) is None
    assert first.teacher_id is None
