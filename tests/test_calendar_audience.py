"""Who sees what on the academic calendar.

The matrix in `docs/architecture/specs/2026-09-15-mobile-academic-calendar.md`
§1, one test per row. These are authorization tests: a failure here is a
teacher reading another class's exam schedule, not a cosmetic defect.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def academic_year(db_session, tenant):
    from modules.academics.academic_year.models import AcademicYear

    ay = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name="2026-2027",
        start_date=date(2026, 6, 1), end_date=date(2027, 3, 31), is_active=True,
    )
    db_session.add(ay)
    db_session.flush()
    return ay


@pytest.fixture
def two_classes(db_session, tenant, academic_year):
    """Two classes in one tenant. The teacher below teaches the first."""
    from modules.classes.models import Class

    rows = [
        Class(
            id=_new_id("c-"), tenant_id=tenant.id, name="Std 8", section="A",
            academic_year_id=academic_year.id,
        ),
        Class(
            id=_new_id("c-"), tenant_id=tenant.id, name="Std 12", section="B",
            academic_year_id=academic_year.id,
        ),
    ]
    db_session.add_all(rows)
    db_session.flush()
    return rows


def _a_teacher(db_session, tenant):
    """A Teacher row reached the way `teacher_for_user` reaches one.

    Account -> Person -> Staff -> Teacher (ADR-001/003/005). Setting
    `teachers.user_id` instead resolves to nobody — that column is a leftover
    from before the chain existed.
    """
    from modules.auth.models import User
    from modules.teachers.models import Teacher
    from tests.conftest import employ_for

    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=f"u-{suffix}", tenant_id=tenant.id, email=f"{suffix}@test.school",
        password_hash="x" * 60, name="Teacher",
    )
    db_session.add(user)
    db_session.flush()
    staff = employ_for(user, employee_number=f"EMP-{suffix}")
    teacher = Teacher(id=_new_id("t-"), tenant_id=tenant.id, staff_id=staff.id)
    db_session.add(teacher)
    db_session.flush()
    return user, teacher


# ---------------------------------------------------------------------------
# "Their students" — both ways a teacher meets a class
# ---------------------------------------------------------------------------

def test_subject_teaching_counts_as_teaching_the_class(db_session, tenant, two_classes):
    """A subject teacher who is not the class teacher still teaches the class.

    `classes_taught_by` answers "class teacher of", which is the narrower
    question attendance asks. Reusing it here would have hidden a maths
    teacher's own exam window from them.
    """
    from modules.academics.backbone.models import ClassSubjectTeacher
    from modules.academics.teaching_assignment import class_ids_taught_by
    from modules.classes.models import ClassSubject
    from modules.subjects.models import Subject

    taught, other = two_classes
    _user, teacher = _a_teacher(db_session, tenant)

    subject = Subject(id=_new_id("s-"), tenant_id=tenant.id, name="Mathematics")
    db_session.add(subject)
    db_session.flush()
    offering = ClassSubject(
        id=_new_id("cs-"), tenant_id=tenant.id, class_id=taught.id,
        subject_id=subject.id, weekly_periods=5,
    )
    db_session.add(offering)
    db_session.flush()
    db_session.add(
        ClassSubjectTeacher(
            id=_new_id("cst-"), tenant_id=tenant.id, class_subject_id=offering.id,
            teacher_id=teacher.id, role="primary", is_active=True,
        )
    )
    db_session.flush()

    reached = class_ids_taught_by(teacher.id)

    assert taught.id in reached
    assert other.id not in reached


def test_class_teacher_duty_counts_too(db_session, tenant, two_classes):
    from modules.academics.backbone.models import ClassTeacherAssignment
    from modules.academics.teaching_assignment import class_ids_taught_by

    owned, other = two_classes
    _user, teacher = _a_teacher(db_session, tenant)

    db_session.add(
        ClassTeacherAssignment(
            id=_new_id("cta-"), tenant_id=tenant.id, class_id=owned.id,
            teacher_id=teacher.id, role="primary", is_active=True,
        )
    )
    db_session.flush()

    reached = class_ids_taught_by(teacher.id)

    assert reached == {owned.id}
    assert other.id not in reached
