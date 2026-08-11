"""Teaching Assignment answers business questions, and answers them for a date.

The distinction these tests exist for: a teacher who handed a class over in
December was still its teacher in November. A report card for November that
credits the new teacher is wrong in a way that looks right, which is the worst
kind of wrong a school system can be.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from flask import g

from modules.academics import teaching_assignment as teaching


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
def a_class(db_session, tenant, academic_year):
    from modules.classes.models import Class

    cls = Class(
        id=_new_id("c-"), tenant_id=tenant.id, name="Grade 5", section="A",
        academic_year_id=academic_year.id,
    )
    db_session.add(cls)
    db_session.flush()
    return cls


@pytest.fixture
def a_subject(db_session, tenant):
    from modules.subjects.models import Subject

    subject = Subject(
        id=_new_id("sub-"), tenant_id=tenant.id, name="Mathematics",
        code=f"M{uuid.uuid4().hex[:4]}",
    )
    db_session.add(subject)
    db_session.flush()
    return subject


def _teacher(db_session, tenant, name="Rohit Mehta"):
    from modules.auth.models import User
    from modules.teachers.models import Teacher
    from tests.conftest import employ_for

    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=_new_id("u-"), tenant_id=tenant.id, email=f"t-{suffix}@test.school",
        password_hash="x" * 60, name=name,
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


def _teaches_subject(db_session, tenant, cls, subject, teacher, **dates):
    from modules.academics.backbone.models import ClassSubjectTeacher
    from modules.classes.models import ClassSubject

    class_subject = ClassSubject.query.filter_by(
        tenant_id=tenant.id, class_id=cls.id, subject_id=subject.id
    ).first()
    if class_subject is None:
        class_subject = ClassSubject(
            id=_new_id("cs-"), tenant_id=tenant.id, class_id=cls.id,
            subject_id=subject.id, weekly_periods=5,
        )
        db_session.add(class_subject)
        db_session.flush()

    row = ClassSubjectTeacher(
        id=_new_id("cst-"), tenant_id=tenant.id,
        class_subject_id=class_subject.id, teacher_id=teacher.id,
        role=dates.pop("role", "primary"), is_active=dates.pop("is_active", True),
        **dates,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _is_class_teacher(db_session, tenant, cls, teacher, **dates):
    from modules.academics.backbone.models import ClassTeacherAssignment

    row = ClassTeacherAssignment(
        id=_new_id("cta-"), tenant_id=tenant.id, class_id=cls.id,
        teacher_id=teacher.id, role=dates.pop("role", "primary"),
        is_active=dates.pop("is_active", True), **dates,
    )
    db_session.add(row)
    db_session.flush()
    return row


# ---------------------------------------------------------------------------
# Who teaches this subject
# ---------------------------------------------------------------------------

def test_it_names_the_teacher_of_a_subject(ctx, tenant, db_session, a_class, a_subject):
    teacher = _teacher(db_session, tenant)
    _teaches_subject(db_session, tenant, a_class, a_subject, teacher)

    found = teaching.subject_teacher_of(a_class.id, a_subject.id)

    assert found is not None
    assert found.teacher_id == teacher.id
    assert found.class_id == a_class.id
    assert found.subject_id == a_subject.id


def test_the_primary_teacher_answers_for_the_subject(
    ctx, tenant, db_session, a_class, a_subject
):
    """An assistant supports; the primary is answerable."""
    assistant = _teacher(db_session, tenant, "Assistant")
    primary = _teacher(db_session, tenant, "Primary")
    _teaches_subject(db_session, tenant, a_class, a_subject, assistant, role="assistant")
    _teaches_subject(db_session, tenant, a_class, a_subject, primary, role="primary")

    assert teaching.subject_teacher_of(a_class.id, a_subject.id).teacher_id == primary.id


def test_an_assistant_answers_when_nobody_was_made_primary(
    ctx, tenant, db_session, a_class, a_subject
):
    """A school that recorded only an assistant still has somebody teaching it."""
    assistant = _teacher(db_session, tenant, "Assistant")
    _teaches_subject(db_session, tenant, a_class, a_subject, assistant, role="assistant")

    assert teaching.subject_teacher_of(a_class.id, a_subject.id).teacher_id == assistant.id


# ---------------------------------------------------------------------------
# Time is part of the question
# ---------------------------------------------------------------------------

def test_who_taught_it_then_is_not_who_teaches_it_now(
    ctx, tenant, db_session, a_class, a_subject
):
    """The reason this service takes a date at all.

    A report card for November must credit November's teacher, not the one who
    took the class over afterwards.
    """
    departed = _teacher(db_session, tenant, "Departed Teacher")
    arrived = _teacher(db_session, tenant, "Arrived Teacher")

    _teaches_subject(
        db_session, tenant, a_class, a_subject, departed,
        effective_from=date(2026, 6, 1), effective_to=date(2026, 11, 30),
        is_active=False,
    )
    _teaches_subject(
        db_session, tenant, a_class, a_subject, arrived,
        effective_from=date(2026, 12, 1),
    )

    in_november = teaching.subject_teacher_of(
        a_class.id, a_subject.id, on=date(2026, 11, 15)
    )
    in_january = teaching.subject_teacher_of(
        a_class.id, a_subject.id, on=date(2027, 1, 15)
    )

    assert in_november.teacher_id == departed.id
    assert in_january.teacher_id == arrived.id


def test_asking_about_now_ignores_an_assignment_that_has_ended(
    ctx, tenant, db_session, a_class, a_subject
):
    departed = _teacher(db_session, tenant, "Departed")
    _teaches_subject(
        db_session, tenant, a_class, a_subject, departed,
        effective_from=date(2026, 6, 1),
        effective_to=date.today() - timedelta(days=1),
        is_active=False,
    )

    assert teaching.subject_teacher_of(a_class.id, a_subject.id) is None


def test_an_undated_assignment_counts_for_any_date(
    ctx, tenant, db_session, a_class, a_subject
):
    """Records carried over from v1 have no dates.

    Reading them as "never in effect" would erase teaching that demonstrably
    happened.
    """
    teacher = _teacher(db_session, tenant)
    _teaches_subject(db_session, tenant, a_class, a_subject, teacher)

    long_ago = teaching.subject_teacher_of(a_class.id, a_subject.id, on=date(2020, 1, 1))

    assert long_ago is not None
    assert long_ago.teacher_id == teacher.id


# ---------------------------------------------------------------------------
# Class teacher responsibility is a separate question
# ---------------------------------------------------------------------------

def test_the_class_teacher_is_asked_for_separately(
    ctx, tenant, db_session, a_class, a_subject
):
    """The two questions were blurred once. They are not the same question."""
    subject_teacher = _teacher(db_session, tenant, "Subject Teacher")
    class_teacher = _teacher(db_session, tenant, "Class Teacher")
    _teaches_subject(db_session, tenant, a_class, a_subject, subject_teacher)
    _is_class_teacher(db_session, tenant, a_class, class_teacher)

    assert teaching.class_teacher_of(a_class.id).teacher_id == class_teacher.id
    assert teaching.subject_teacher_of(a_class.id, a_subject.id).teacher_id == subject_teacher.id


def test_a_class_teacher_who_handed_over_still_held_it_before(
    ctx, tenant, db_session, a_class
):
    was = _teacher(db_session, tenant, "Was")
    now = _teacher(db_session, tenant, "Now")

    # Relative to today, so the test does not quietly change meaning as the
    # calendar moves past whatever dates were hard-coded when it was written.
    handover = date.today() - timedelta(days=30)
    _is_class_teacher(
        db_session, tenant, a_class, was,
        effective_from=handover - timedelta(days=120),
        effective_to=handover - timedelta(days=1),
        is_active=False,
    )
    _is_class_teacher(db_session, tenant, a_class, now, effective_from=handover)

    before_handover = handover - timedelta(days=45)
    assert teaching.class_teacher_of(a_class.id, on=before_handover).teacher_id == was.id
    assert teaching.class_teacher_of(a_class.id).teacher_id == now.id


# ---------------------------------------------------------------------------
# Questions about a teacher
# ---------------------------------------------------------------------------

def test_it_lists_what_a_teacher_takes(ctx, tenant, db_session, a_class, a_subject):
    teacher = _teacher(db_session, tenant)
    _teaches_subject(db_session, tenant, a_class, a_subject, teacher)
    _is_class_teacher(db_session, tenant, a_class, teacher)

    assert [a.subject_id for a in teaching.subjects_taught_by(teacher.id)] == [a_subject.id]
    assert [a.class_id for a in teaching.classes_taught_by(teacher.id)] == [a_class.id]


def test_either_responsibility_makes_a_teacher_belong_to_a_class(
    ctx, tenant, db_session, a_class, a_subject
):
    only_subject = _teacher(db_session, tenant, "Subject only")
    only_class = _teacher(db_session, tenant, "Class only")
    neither = _teacher(db_session, tenant, "Neither")
    _teaches_subject(db_session, tenant, a_class, a_subject, only_subject)
    _is_class_teacher(db_session, tenant, a_class, only_class)

    assert teaching.teaches_anything_in(only_subject.id, a_class.id)
    assert teaching.teaches_anything_in(only_class.id, a_class.id)
    assert not teaching.teaches_anything_in(neither.id, a_class.id)


# ---------------------------------------------------------------------------
# A page is read once
# ---------------------------------------------------------------------------

def test_reading_a_page_of_classes_does_not_query_per_class(
    ctx, tenant, db_session, academic_year, a_subject
):
    """Resolving teaching row by row is how a list becomes a thousand queries."""
    from sqlalchemy import event

    from core.database import db
    from modules.classes.models import Class

    classes = []
    for index in range(8):
        cls = Class(
            id=_new_id("c-"), tenant_id=tenant.id, name=f"Grade {index}",
            section="A", academic_year_id=academic_year.id,
        )
        db_session.add(cls)
        db_session.flush()
        _teaches_subject(db_session, tenant, cls, a_subject, _teacher(db_session, tenant))
        classes.append(cls)

    def queries_for(how_many):
        seen = []

        def record(conn, cursor, statement, params, context, executemany):
            seen.append(statement)

        event.listen(db.engine, "before_cursor_execute", record)
        try:
            found = teaching.subject_teachers_for([c.id for c in classes[:how_many]])
            assert len(found) == how_many
        finally:
            event.remove(db.engine, "before_cursor_execute", record)
        return len(seen)

    assert queries_for(8) <= queries_for(2), "teaching queries grew with the page: N+1"
