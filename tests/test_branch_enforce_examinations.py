"""A sub-admin restricted to one campus sees only that campus's examinations.

Examinations shipped with no branch scoping at all. On a trust running twenty
campuses, the head of one campus could list every campus's examinations, read
every campus's marking register, and record marks against children they have no
authority over. Tenancy kept one school out of another's data; nothing kept one
campus out of another's.

**An examination declares no campus** (ADR-016) — its *papers* carry the class,
and the class carries the campus. So an examination is visible to a restricted
user when at least one of its papers sits in a class in their branches, and the
papers, register, marks and results they can reach are only ever their own.

An examination whose papers are all elsewhere is invisible, the same way a
teacher with no class in your campus is invisible: it becomes visible the moment
a paper lands in a section you hold. The rule everywhere else holds here too —
no `UserSchoolUnit` rows means unrestricted, which is what every existing admin
is.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from flask import g

from core.branch_scope import BranchForbidden
from modules.academics.academic_year.models import AcademicYear
from modules.academics.backbone.models import (
    ClassSubjectTeacher,
    StudentClassEnrollment,
)
from modules.academics.cycles.services import default_cycle_for_year
from modules.auth.models import User
from modules.classes.models import Class, ClassSubject
from modules.examinations import marks_service, services as exam_services
from modules.examinations.models import ExamType
from modules.people.employment import Staff
from modules.people.models import Person
from modules.students.models import Student
from modules.subjects.models import Subject
from modules.sub_admins.models import UserSchoolUnit
from modules.teachers.models import Teacher


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# A trust with two campuses
# ---------------------------------------------------------------------------

@pytest.fixture
def units(db_session, tenant):
    from modules.school_units.models import SchoolUnit

    unit_a = SchoolUnit(
        id=_new_id("su-"), tenant_id=tenant.id, name="Campus A",
        code=f"A-{uuid.uuid4().hex[:6]}",
    )
    unit_b = SchoolUnit(
        id=_new_id("su-"), tenant_id=tenant.id, name="Campus B",
        code=f"B-{uuid.uuid4().hex[:6]}",
    )
    db_session.add_all([unit_a, unit_b])
    db_session.flush()
    return unit_a, unit_b


@pytest.fixture
def year(db_session, tenant):
    row = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id,
        name=f"2026-27-{uuid.uuid4().hex[:5]}",
        start_date=date(2026, 4, 1), end_date=date(2027, 3, 31),
    )
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def cycle(db_session, tenant, year):
    row = default_cycle_for_year(year.id, tenant.id)
    row.name = f"Main-{uuid.uuid4().hex[:5]}"
    row.start_date, row.end_date = date(2026, 4, 1), date(2027, 3, 31)
    db_session.flush()
    return row


def _person(db_session, tenant, name):
    row = Person(id=_new_id("pe-"), tenant_id=tenant.id, full_name=name)
    db_session.add(row)
    db_session.flush()
    return row


def _teacher(db_session, tenant, name):
    person = _person(db_session, tenant, name)
    staff = Staff(id=_new_id("sf-"), tenant_id=tenant.id, person_id=person.id)
    db_session.add(staff)
    db_session.flush()
    teacher = Teacher(id=_new_id("te-"), tenant_id=tenant.id, staff_id=staff.id)
    db_session.add(teacher)
    db_session.flush()
    return teacher


def _section(db_session, tenant, year, cycle, unit, label):
    row = Class(
        id=_new_id("cl-"), tenant_id=tenant.id, section=label,
        name=f"Section {label}", academic_year_id=year.id,
        academic_cycle_id=cycle.id, school_unit_id=unit.id,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _offering(db_session, tenant, cls, label):
    subject = Subject(
        id=_new_id("sb-"), tenant_id=tenant.id,
        name=f"{label}-{uuid.uuid4().hex[:6]}",
        code=f"{label[:3].upper()}{uuid.uuid4().hex[:4]}",
    )
    db_session.add(subject)
    db_session.flush()
    row = ClassSubject(
        id=_new_id("cs-"), tenant_id=tenant.id, class_id=cls.id,
        subject_id=subject.id, weekly_periods=5, status="active",
    )
    db_session.add(row)
    db_session.flush()
    return row


def _student_in(db_session, tenant, year, cls, name):
    person = _person(db_session, tenant, name)
    student = Student(
        id=_new_id("st-"), tenant_id=tenant.id, person_id=person.id,
        admission_number=f"A{uuid.uuid4().hex[:8]}", academic_year_id=year.id,
        class_id=cls.id,
    )
    db_session.add(student)
    db_session.flush()
    db_session.add(StudentClassEnrollment(
        id=_new_id("en-"), tenant_id=tenant.id, student_id=student.id,
        class_id=cls.id, academic_year_id=year.id,
        enrollment_type="primary", is_current=True, roll_number=1,
    ))
    db_session.flush()
    return student


@pytest.fixture
def school(db_session, tenant, year, cycle, units):
    """One section per campus, each with a subject, a teacher and a child."""
    unit_a, unit_b = units
    sec_a = _section(db_session, tenant, year, cycle, unit_a, "10A")
    sec_b = _section(db_session, tenant, year, cycle, unit_b, "10B")

    maths_a = _offering(db_session, tenant, sec_a, "MathsA")
    maths_b = _offering(db_session, tenant, sec_b, "MathsB")

    teacher = _teacher(db_session, tenant, "Asha Mehta")
    for offering in (maths_a, maths_b):
        db_session.add(ClassSubjectTeacher(
            id=_new_id("ct-"), tenant_id=tenant.id,
            class_subject_id=offering.id, teacher_id=teacher.id,
            role="primary", is_active=True,
        ))
    db_session.flush()

    return {
        "sec_a": sec_a, "sec_b": sec_b,
        "maths_a": maths_a, "maths_b": maths_b,
        "teacher": teacher,
        "child_a": _student_in(db_session, tenant, year, sec_a, "Riya Patel"),
        "child_b": _student_in(db_session, tenant, year, sec_b, "Dev Sharma"),
    }


@pytest.fixture
def exam_type(db_session, tenant):
    row = ExamType(
        id=_new_id("et-"), tenant_id=tenant.id,
        name=f"Half Yearly-{uuid.uuid4().hex[:5]}", sequence=10,
    )
    db_session.add(row)
    db_session.flush()
    return row


# ---------------------------------------------------------------------------
# Who is asking
# ---------------------------------------------------------------------------

#: Everything an assessment officer holds. Both users below get all of them, so
#: a refusal in these tests can only ever be the branch check — never a missing
#: permission wearing the same 403.
_ASSESSMENT_KEYS = (
    "assessment.enter", "assessment.update", "assessment.manage",
    "examination.manage", "examination.publish",
)


def _user(db_session, tenant, name):
    """An employed account holding the full assessment authority."""
    from modules.rbac.models import Permission, Role, RolePermission
    from tests.conftest import grant_profile_to

    suffix = uuid.uuid4().hex[:8]
    row = User(
        id=_new_id("us-"), tenant_id=tenant.id,
        email=f"{suffix}@example.test",
        password_hash="x" * 60, name=name,
    )
    db_session.add(row)
    db_session.flush()

    role = Role(id=f"r-{suffix}", tenant_id=tenant.id, name=f"Assessment-{suffix}")
    db_session.add(role)
    db_session.flush()
    for key in _ASSESSMENT_KEYS:
        permission = Permission.query.filter_by(name=key).first()
        if permission is None:
            permission = Permission(id=_new_id("perm-"), name=key)
            db_session.add(permission)
            db_session.flush()
        db_session.add(RolePermission(
            tenant_id=tenant.id, role_id=role.id, permission_id=permission.id
        ))
    db_session.flush()
    grant_profile_to(row, role.id, employee_number=f"EMP-{suffix}")
    return row


@pytest.fixture
def head_of_campus_a(db_session, tenant, units):
    unit_a, _ = units
    user = _user(db_session, tenant, "Head of Campus A")
    db_session.add(UserSchoolUnit(
        id=_new_id("usu-"), tenant_id=tenant.id,
        user_id=user.id, school_unit_id=unit_a.id,
    ))
    db_session.flush()
    return user


@pytest.fixture
def trust_admin(db_session, tenant):
    """No UserSchoolUnit rows — every existing admin looks like this."""
    return _user(db_session, tenant, "Trust Administrator")


@pytest.fixture
def as_user(flask_app, tenant):
    """Run a block as a given user, the way a request would.

    `g` lives on the *app* context, and `test_request_context` reuses an app
    context that is already pushed — so without clearing them, the branch-scope
    caches resolved for the previous user would answer for this one. A real
    request gets a fresh app context and cannot hit this.
    """
    from contextlib import contextmanager

    @contextmanager
    def _run(user):
        with flask_app.test_request_context("/"):
            g.pop("_branch_scope_allowed_unit_ids", None)
            g.pop("_branch_scope_allowed_class_ids", None)
            g.tenant_id = tenant.id
            g.current_user = user
            yield

    return _run


# ---------------------------------------------------------------------------
# An examination both campuses sit
# ---------------------------------------------------------------------------

@pytest.fixture
def half_yearly(as_user, db_session, tenant, cycle, exam_type, school, trust_admin):
    """One examination, one paper in each campus — the trust-wide shape."""
    with as_user(trust_admin):
        created = exam_services.create_examination(
            tenant_id=tenant.id, academic_cycle_id=cycle.id,
            exam_type_id=exam_type.id, name=f"HY-{uuid.uuid4().hex[:5]}",
            papers=[
                {"class_subject_id": school["maths_a"].id, "max_marks": 100,
                 "pass_marks": 35, "exam_date": date(2026, 10, 5)},
                {"class_subject_id": school["maths_b"].id, "max_marks": 100,
                 "pass_marks": 35, "exam_date": date(2026, 10, 5)},
            ],
            commit=False,
        )
    assert created["success"] is True, created
    examination = created["examination"]
    papers = exam_services.papers_for(examination.id, tenant.id)
    by_class = {p.class_id: p for p in papers}
    return {
        "examination": examination,
        "paper_a": by_class[school["sec_a"].id],
        "paper_b": by_class[school["sec_b"].id],
    }


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def test_a_campus_head_sees_only_their_own_campus_papers(
    as_user, tenant, school, half_yearly, head_of_campus_a
):
    """`papers_with_labels` is what the examination screen reads."""
    with as_user(head_of_campus_a):
        rows = exam_services.papers_with_labels(
            half_yearly["examination"].id, tenant.id
        )

    assert [paper.class_id for paper, _cls, _subject in rows] == [school["sec_a"].id]


def test_the_calculation_still_sees_every_campus_paper(
    as_user, tenant, half_yearly, head_of_campus_a
):
    """`papers_for` feeds result computation and must NOT be branch-scoped.

    A student's frozen result would otherwise depend on who pressed calculate.
    """
    with as_user(head_of_campus_a):
        papers = exam_services.papers_for(half_yearly["examination"].id, tenant.id)

    assert len(papers) == 2


def test_a_campus_head_sees_only_their_own_sections_sitting(
    as_user, tenant, school, half_yearly, head_of_campus_a
):
    with as_user(head_of_campus_a):
        sitting = exam_services.classes_sitting(
            half_yearly["examination"].id, tenant.id
        )

    assert sitting == [school["sec_a"].id]


def test_an_examination_only_another_campus_sits_is_not_listed(
    as_user, db_session, tenant, cycle, exam_type, school, head_of_campus_a,
    trust_admin, half_yearly,
):
    """A Campus-B-only examination must not appear for the head of Campus A."""
    with as_user(trust_admin):
        created = exam_services.create_examination(
            tenant_id=tenant.id, academic_cycle_id=cycle.id,
            exam_type_id=exam_type.id, name=f"B-only-{uuid.uuid4().hex[:5]}",
            papers=[{"class_subject_id": school["maths_b"].id, "max_marks": 50,
                     "pass_marks": 17, "exam_date": date(2026, 11, 3)}],
            commit=False,
        )
    assert created["success"] is True, created
    b_only = created["examination"]

    with as_user(head_of_campus_a):
        visible = {e.id for e in exam_services.list_examinations(tenant.id)}
        total = exam_services.count_examinations(tenant.id)

    assert b_only.id not in visible
    assert half_yearly["examination"].id in visible, (
        "the shared examination is still theirs — one of its papers is in Campus A"
    )
    assert total == len(visible), "the count must agree with the rows"


def test_a_campus_head_cannot_open_another_campus_marking_register(
    as_user, tenant, half_yearly, head_of_campus_a
):
    with as_user(head_of_campus_a):
        with pytest.raises(BranchForbidden):
            marks_service.marking_register(
                half_yearly["paper_b"].id, tenant.id
            )


def test_a_campus_head_can_open_their_own_marking_register(
    as_user, tenant, school, half_yearly, head_of_campus_a
):
    with as_user(head_of_campus_a):
        register = marks_service.marking_register(
            half_yearly["paper_a"].id, tenant.id
        )

    assert register is not None
    assert [row["student_id"] for row in register["students"]] == [school["child_a"].id]


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def test_a_campus_head_cannot_record_marks_on_another_campus_paper(
    as_user, tenant, school, half_yearly, head_of_campus_a
):
    with as_user(head_of_campus_a):
        with pytest.raises(BranchForbidden):
            marks_service.record_marks(
                tenant_id=tenant.id,
                exam_paper_id=half_yearly["paper_b"].id,
                rows=[{"student_id": school["child_b"].id, "marks_obtained": 90}],
                actor_user_id=head_of_campus_a.id,
                commit=False,
            )


def test_a_campus_head_cannot_add_a_paper_in_another_campus(
    as_user, tenant, school, half_yearly, head_of_campus_a
):
    with as_user(head_of_campus_a):
        with pytest.raises(BranchForbidden):
            exam_services.add_papers(
                half_yearly["examination"].id,
                tenant.id,
                [{"class_subject_id": school["maths_b"].id,
                  "max_marks": 100, "pass_marks": 35,
                  "exam_date": date(2026, 10, 9)}],
                commit=False,
            )


# ---------------------------------------------------------------------------
# Results, corrections and marksheets — a child's marks, scoped by the child
# ---------------------------------------------------------------------------

@pytest.fixture
def marked(as_user, tenant, school, half_yearly, trust_admin):
    """Both campuses marked and calculated, by someone who may see both."""
    from modules.examinations import results_service

    examination = half_yearly["examination"]
    with as_user(trust_admin):
        assert exam_services.schedule_examination(
            examination.id, tenant.id, actor_user_id=trust_admin.id, commit=False
        )["success"] is True
        assert exam_services.open_marks_entry(
            examination.id, tenant.id, actor_user_id=trust_admin.id, commit=False
        )["success"] is True

        for paper, child in (
            (half_yearly["paper_a"], school["child_a"]),
            (half_yearly["paper_b"], school["child_b"]),
        ):
            recorded = marks_service.record_marks(
                tenant_id=tenant.id, exam_paper_id=paper.id,
                rows=[{"student_id": child.id, "marks_obtained": 72,
                       "status": "present"}],
                actor_user_id=trust_admin.id, commit=False,
            )
            assert recorded["success"] is True, recorded

        calculated = results_service.calculate_results(
            examination.id, tenant_id=tenant.id,
            actor_user_id=trust_admin.id, commit=False,
        )
        assert calculated["success"] is True, calculated
    return examination


def test_a_campus_head_sees_only_their_own_campus_results(
    as_user, tenant, school, marked, head_of_campus_a
):
    from modules.examinations import results_service

    with as_user(head_of_campus_a):
        results = results_service.results_for(marked.id, tenant.id)

    assert [r.student_id for r in results] == [school["child_a"].id]


def test_a_campus_head_cannot_pull_another_campus_childs_marksheet(
    as_user, tenant, school, marked, head_of_campus_a
):
    from modules.examinations import marksheet_service

    with as_user(head_of_campus_a):
        with pytest.raises(BranchForbidden):
            marksheet_service.marksheet_model(
                marked.id, school["child_b"].id, tenant.id
            )


def test_a_campus_head_sees_only_their_own_campus_corrections(
    as_user, tenant, school, marked, half_yearly, head_of_campus_a, trust_admin
):
    from modules.examinations import corrections_service

    # A correction raised against each campus's mark. A correction only exists
    # against a *locked* register — an open one is edited directly.
    with as_user(trust_admin):
        for paper in (half_yearly["paper_a"], half_yearly["paper_b"]):
            register = marks_service.marking_register(paper.id, tenant.id)
            mark_id = register["students"][0]["mark_id"]
            assert mark_id is not None
            locked = marks_service.lock_paper(
                paper.id, tenant.id, actor_user_id=trust_admin.id, commit=False
            )
            assert locked["success"] is True, locked
            raised = corrections_service.request_correction(
                tenant.id, mark_id, to_status="present", to_marks=81,
                reason="Re-totalled", requested_by_user_id=trust_admin.id,
                commit=False,
            )
            assert raised["success"] is True, raised

    with as_user(head_of_campus_a):
        queue = corrections_service.correction_queue(tenant.id)

    assert len(queue) == 1, "a campus head reviews only their own campus's requests"


def test_a_campus_head_cannot_revise_another_campus_childs_result(
    as_user, tenant, school, marked, head_of_campus_a
):
    from modules.examinations import revision_service

    with as_user(head_of_campus_a):
        with pytest.raises(BranchForbidden):
            revision_service.revise_result(
                marked.id, school["child_b"].id, tenant.id,
                reason="Re-totalled", actor_user_id=head_of_campus_a.id,
                commit=False,
            )


def test_a_campus_head_cannot_publish_another_campus_childs_revision(
    as_user, tenant, school, marked, head_of_campus_a
):
    from modules.examinations import revision_service

    with as_user(head_of_campus_a):
        with pytest.raises(BranchForbidden):
            revision_service.publish_revision(
                marked.id, school["child_b"].id, tenant.id,
                actor_user_id=head_of_campus_a.id, commit=False,
            )


# ---------------------------------------------------------------------------
# The unrestricted admin is untouched
# ---------------------------------------------------------------------------

def test_an_unrestricted_admin_still_sees_every_campus(
    as_user, tenant, school, half_yearly, trust_admin
):
    """Regression guard: the helpers are a strict no-op without restrictions."""
    with as_user(trust_admin):
        papers = exam_services.papers_for(half_yearly["examination"].id, tenant.id)
        sitting = set(exam_services.classes_sitting(
            half_yearly["examination"].id, tenant.id
        ))
        register = marks_service.marking_register(
            half_yearly["paper_b"].id, tenant.id
        )

    assert len(papers) == 2
    assert sitting == {school["sec_a"].id, school["sec_b"].id}
    assert register is not None
