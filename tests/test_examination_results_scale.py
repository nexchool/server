"""Calculating an examination must not cost a query per student per paper.

`calculate_results` walked the cohort and, for every student, re-read the
paper list and then asked `is_eligible` once **per paper**. So the cost was
`cohort x (3 + papers)`: a grade of 1,600 children sitting 8 subjects across
20 sections is ~200,000 queries, and a whole-school annual examination at the
product's stated scale runs to millions. It could not finish inside the
request timeout, and because the batch is all-or-nothing it rolled back with
nothing to show for the wait.

The rule itself is not the problem and is unchanged: an open paper answers
from current enrolment, a locked one from its own register (EX-02A.1). It is
simply the same question asked once per student instead of once per paper —
`is_eligible(paper, s)` is exactly `s in paper_cohort(paper)`, as its own
docstring says.

The guard here is the one `test_teaching_assignment_service` uses: run the
same work over two cohort sizes and hold the growth to what genuinely scales
with it (one read and one write per student's own result row).
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from flask import g
from sqlalchemy import event

from core.database import db
from modules.academics.academic_year.models import AcademicYear
from modules.academics.backbone.models import (
    ClassSubjectTeacher,
    StudentClassEnrollment,
)
from modules.academics.cycles.services import default_cycle_for_year
from modules.classes.models import Class, ClassSubject
from modules.examinations import results_service, services as exam_services
from modules.examinations.models import ExamType
from modules.people.employment import Staff
from modules.people.models import Person
from modules.students.models import Student
from modules.subjects.models import Subject
from modules.teachers.models import Teacher

#: Papers per student. The per-student cost used to grow with this.
PAPERS = 3


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


@pytest.fixture
def year(db_session, tenant):
    row = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name=f"AY-{uuid.uuid4().hex[:5]}",
        start_date=date(2026, 4, 1), end_date=date(2027, 3, 31),
    )
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def cycle(db_session, tenant, year):
    row = default_cycle_for_year(year.id, tenant.id)
    row.start_date, row.end_date = date(2026, 4, 1), date(2027, 3, 31)
    db_session.flush()
    return row


@pytest.fixture
def exam_type(db_session, tenant):
    row = ExamType(
        id=_new_id("et-"), tenant_id=tenant.id,
        name=f"Annual-{uuid.uuid4().hex[:5]}", sequence=10,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _teacher(db_session, tenant):
    person = Person(
        id=_new_id("pe-"), tenant_id=tenant.id, full_name="Asha Mehta"
    )
    db_session.add(person)
    db_session.flush()
    staff = Staff(id=_new_id("sf-"), tenant_id=tenant.id, person_id=person.id)
    db_session.add(staff)
    db_session.flush()
    row = Teacher(id=_new_id("te-"), tenant_id=tenant.id, staff_id=staff.id)
    db_session.add(row)
    db_session.flush()
    return row


def _school(db_session, tenant, year, cycle, *, students: int):
    """One section, `PAPERS` subjects, and `students` children enrolled."""
    section = Class(
        id=_new_id("cl-"), tenant_id=tenant.id, section="A", name="Grade 10",
        academic_year_id=year.id, academic_cycle_id=cycle.id,
    )
    db_session.add(section)
    db_session.flush()

    teacher = _teacher(db_session, tenant)
    offerings = []
    for index in range(PAPERS):
        subject = Subject(
            id=_new_id("sb-"), tenant_id=tenant.id,
            name=f"Subject {index}-{uuid.uuid4().hex[:5]}",
            code=f"S{index}{uuid.uuid4().hex[:4]}",
        )
        db_session.add(subject)
        db_session.flush()
        offering = ClassSubject(
            id=_new_id("cs-"), tenant_id=tenant.id, class_id=section.id,
            subject_id=subject.id, weekly_periods=5, status="active",
        )
        db_session.add(offering)
        db_session.flush()
        db_session.add(ClassSubjectTeacher(
            id=_new_id("ct-"), tenant_id=tenant.id,
            class_subject_id=offering.id, teacher_id=teacher.id,
            role="primary", is_active=True,
        ))
        offerings.append(offering)

    for _ in range(students):
        person = Person(
            id=_new_id("pe-"), tenant_id=tenant.id,
            full_name=f"Child {uuid.uuid4().hex[:6]}",
        )
        db_session.add(person)
        db_session.flush()
        student = Student(
            id=_new_id("st-"), tenant_id=tenant.id, person_id=person.id,
            admission_number=f"A{uuid.uuid4().hex[:8]}",
            academic_year_id=year.id, class_id=section.id,
        )
        db_session.add(student)
        db_session.flush()
        db_session.add(StudentClassEnrollment(
            id=_new_id("en-"), tenant_id=tenant.id, student_id=student.id,
            class_id=section.id, academic_year_id=year.id,
            enrollment_type="primary", is_current=True,
        ))
    db_session.flush()
    return offerings


def _examination(tenant, cycle, exam_type, offerings):
    created = exam_services.create_examination(
        tenant_id=tenant.id, academic_cycle_id=cycle.id,
        exam_type_id=exam_type.id, name=f"Annual-{uuid.uuid4().hex[:5]}",
        papers=[
            {"class_subject_id": offering.id, "max_marks": 100,
             "pass_marks": 35, "exam_date": date(2026, 10, 5)}
            for offering in offerings
        ],
        commit=False,
    )
    assert created["success"] is True, created
    return created["examination"]


def _queries_to_calculate(tenant, cycle, exam_type, db_session, year, *, students):
    """How many statements calculating an examination of this size costs."""
    offerings = _school(db_session, tenant, year, cycle, students=students)
    examination = _examination(tenant, cycle, exam_type, offerings)

    seen: list = []

    def record(conn, cursor, statement, params, context, executemany):
        seen.append(statement)

    event.listen(db.engine, "before_cursor_execute", record)
    try:
        outcome = results_service.calculate_results(
            examination.id, tenant_id=tenant.id,
            actor_user_id=_ACTOR["id"], commit=False,
        )
    finally:
        event.remove(db.engine, "before_cursor_execute", record)

    assert outcome["success"] is True, outcome
    assert len(outcome["results"]) == students, outcome
    return len(seen)


_ACTOR: dict = {}


@pytest.fixture(autouse=True)
def actor(db_session, tenant):
    """Somebody who may run assessment for the school."""
    from modules.auth.models import User
    from modules.rbac.models import Permission, Role, RolePermission
    from tests.conftest import grant_profile_to

    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=f"u-{suffix}", tenant_id=tenant.id, email=f"{suffix}@test.school",
        password_hash="x" * 60, name="Examinations Officer",
    )
    db_session.add(user)
    db_session.flush()
    role = Role(id=f"r-{suffix}", tenant_id=tenant.id, name=f"Exams-{suffix}")
    db_session.add(role)
    db_session.flush()
    permission = Permission.query.filter_by(name="assessment.manage").first()
    if permission is None:
        permission = Permission(id=_new_id("perm-"), name="assessment.manage")
        db_session.add(permission)
        db_session.flush()
    db_session.add(RolePermission(
        tenant_id=tenant.id, role_id=role.id, permission_id=permission.id
    ))
    db_session.flush()
    grant_profile_to(user, role.id, employee_number=f"EMP-{suffix}")
    _ACTOR["id"] = user.id
    return user


def test_calculating_does_not_cost_a_query_per_student_per_paper(
    ctx, db_session, tenant, cycle, exam_type, year
):
    small = _queries_to_calculate(
        tenant, cycle, exam_type, db_session, year, students=2
    )
    large = _queries_to_calculate(
        tenant, cycle, exam_type, db_session, year, students=8
    )

    extra_students = 8 - 2
    #: A student's own result row is genuinely per-student: one read to find an
    #: existing row, one write. Anything beyond that scales with the cohort and
    #: should not. Before this was fixed the slope was `3 + PAPERS` per student.
    allowed_slope = 3
    assert large - small <= allowed_slope * extra_students, (
        f"calculating grew by {large - small} queries for {extra_students} more "
        f"students ({(large - small) / extra_students:.1f} each) — the paper "
        f"eligibility lookup is still per-student"
    )


def _queries_for_readiness(tenant, cycle, exam_type, db_session, year, *, students):
    """How many statements asking "can this publish?" costs at this size."""
    from modules.examinations import publication_service

    offerings = _school(db_session, tenant, year, cycle, students=students)
    examination = _examination(tenant, cycle, exam_type, offerings)

    seen: list = []

    def record(conn, cursor, statement, params, context, executemany):
        seen.append(statement)

    event.listen(db.engine, "before_cursor_execute", record)
    try:
        readiness = publication_service.publication_readiness(
            examination.id, tenant.id
        )
    finally:
        event.remove(db.engine, "before_cursor_execute", record)

    assert readiness["cohort"] == students, readiness
    return len(seen)


def test_publication_readiness_does_not_cost_a_query_per_student(
    ctx, db_session, tenant, cycle, exam_type, year
):
    """The results screen asks this on every load, beside the board itself."""
    small = _queries_for_readiness(
        tenant, cycle, exam_type, db_session, year, students=2
    )
    large = _queries_for_readiness(
        tenant, cycle, exam_type, db_session, year, students=8
    )

    assert large <= small, (
        f"readiness grew from {small} to {large} queries as the cohort grew — "
        "it is still reading one result row per student"
    )


def test_every_student_still_gets_the_papers_they_sit(
    ctx, db_session, tenant, cycle, exam_type, year
):
    """The batching must not change the answer, only how it is reached."""
    offerings = _school(db_session, tenant, year, cycle, students=3)
    examination = _examination(tenant, cycle, exam_type, offerings)

    cohort = results_service.examination_cohort(examination, tenant.id)
    assert len(cohort) == 3

    for student_id in cohort:
        papers = results_service.applicable_papers(
            examination, student_id, tenant.id
        )
        assert len(papers) == PAPERS, (
            "an enrolled child sits every open paper of their section"
        )
