"""Fixtures for student_leaves service tests.

The top-level tests/conftest.py provides `db_session`, `tenant`, `student`.
We extend with the fixtures needed by the state machine tests:

  tenant_ctx           — pushes g.tenant_id so services using get_tenant_id() work
  class_with_teacher   — Class + Teacher + User; student is placed in this class
  student_user         — wraps existing `student` fixture's User row, exposes .student
  admin_user           — user holding student.leave.approve.all via a Role
  other_teacher_user   — Teacher whose user_id != class teacher's
  enable_admin_approval— flips AcademicSettings.student_leave_admin_approval_required
"""

from __future__ import annotations

import uuid

import pytest
from flask import g


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}" if prefix else str(uuid.uuid4())


@pytest.fixture
def tenant_ctx(flask_app, db_session, tenant):
    """Push g.tenant_id for services that read from request context."""
    # The session-scoped flask_app already provides an app context via
    # db_session's `with flask_app.app_context()`. We just need to set g.
    g.tenant_id = tenant.id
    yield tenant
    # No need to pop; teardown of db_session ends the app context.


@pytest.fixture
def academic_year(db_session, tenant):
    from datetime import date
    from modules.academics.academic_year.models import AcademicYear
    ay = AcademicYear(
        id=_new_id("ay-"),
        tenant_id=tenant.id,
        name="2025-2026",
        start_date=date(2025, 6, 1),
        end_date=date(2026, 3, 31),
        is_active=True,
    )
    db_session.add(ay)
    db_session.flush()
    return ay


@pytest.fixture
def class_with_teacher(db_session, tenant, academic_year):
    """Create a Class with a primary class teacher.

    Returns an object with attributes:
        .id, .class_teacher_id (teachers.id), .teacher_row (Teacher row)

    NOTE: the convenience pointer is `.teacher_row`, NOT `.teacher` — `Class.teacher`
    is a real ORM relationship to User (backref `assigned_classes`), so assigning a
    Teacher to it breaks the backref cascade.
    """
    from modules.auth.models import User
    from modules.teachers.models import Teacher
    from modules.classes.models import Class
    from modules.academics.backbone.models import ClassTeacherAssignment

    teacher_user = User(
        id=_new_id("u-t-"),
        tenant_id=tenant.id,
        email=f"teacher-{uuid.uuid4().hex[:6]}@test.school",
        password_hash="x" * 60,
        name="Class Teacher",
    )
    db_session.add(teacher_user)
    db_session.flush()

    teacher = Teacher(
        id=_new_id("teacher-"),
        tenant_id=tenant.id,
        user_id=teacher_user.id,
        employee_id=f"T-{uuid.uuid4().hex[:6]}",
    )
    db_session.add(teacher)
    db_session.flush()

    cls = Class(
        id=_new_id("c-"),
        tenant_id=tenant.id,
        section="A",
        academic_year_id=academic_year.id,
        teacher_id=teacher_user.id,  # legacy pointer; resolves via Teacher.user_id
    )
    db_session.add(cls)
    db_session.flush()

    cta = ClassTeacherAssignment(
        id=_new_id("cta-"),
        tenant_id=tenant.id,
        class_id=cls.id,
        teacher_id=teacher.id,
        role="primary",
        is_active=True,
        allow_attendance_marking=True,
    )
    db_session.add(cta)
    db_session.flush()

    cls.class_teacher_id = teacher.id  # convenience attribute for tests
    cls.teacher_row = teacher  # convenience attr (NOT cls.teacher — that's the User relationship)
    return cls


@pytest.fixture
def student_user(db_session, tenant, student, class_with_teacher):
    """The `student` fixture already creates User + Student. Place that student
    in the class_with_teacher, and expose user.student for the tests.
    """
    student.class_id = class_with_teacher.id
    db_session.flush()
    from modules.auth.models import User
    user = db_session.get(User, student.user_id)
    user.student = student  # convenience attribute
    return user


@pytest.fixture
def other_teacher_user(db_session, tenant):
    """A user who is a teacher but NOT the class teacher of class_with_teacher."""
    from modules.auth.models import User
    from modules.teachers.models import Teacher
    user = User(
        id=_new_id("u-ot-"),
        tenant_id=tenant.id,
        email=f"other-{uuid.uuid4().hex[:6]}@test.school",
        password_hash="x" * 60,
        name="Other Teacher",
    )
    db_session.add(user)
    db_session.flush()
    teacher = Teacher(
        id=_new_id("teacher-o-"),
        tenant_id=tenant.id,
        user_id=user.id,
        employee_id=f"OT-{uuid.uuid4().hex[:6]}",
    )
    db_session.add(teacher)
    db_session.flush()
    return user


@pytest.fixture
def admin_user(db_session, tenant):
    """A user with student.leave.approve.all permission (and read.all for completeness)."""
    from modules.auth.models import User
    from modules.rbac.models import Role, Permission, RolePermission, UserRole

    user = User(
        id=_new_id("u-a-"),
        tenant_id=tenant.id,
        email=f"admin-{uuid.uuid4().hex[:6]}@test.school",
        password_hash="x" * 60,
        name="Admin",
    )
    db_session.add(user)
    db_session.flush()

    role = Role(
        id=_new_id("r-"),
        tenant_id=tenant.id,
        name=f"TestAdmin-{uuid.uuid4().hex[:6]}",
        description="test admin",
    )
    db_session.add(role)
    db_session.flush()

    # Permission rows are global (no tenant_id). Re-use if already present.
    perm = (
        db_session.query(Permission)
        .filter(Permission.name == "student.leave.approve.all")
        .first()
    )
    if perm is None:
        perm = Permission(
            id=_new_id("p-"),
            name="student.leave.approve.all",
            description="Approve any student leave",
        )
        db_session.add(perm)
        db_session.flush()

    db_session.add(
        RolePermission(
            id=_new_id("rp-"),
            tenant_id=tenant.id,
            role_id=role.id,
            permission_id=perm.id,
        )
    )
    db_session.add(
        UserRole(
            id=_new_id("ur-"),
            tenant_id=tenant.id,
            user_id=user.id,
            role_id=role.id,
        )
    )
    db_session.flush()
    return user


@pytest.fixture
def enable_admin_approval(db_session, tenant):
    """Flip AcademicSettings.student_leave_admin_approval_required = True."""
    from modules.academics.backbone.models import AcademicSettings
    s = (
        db_session.query(AcademicSettings)
        .filter(AcademicSettings.tenant_id == tenant.id)
        .first()
    )
    if s is None:
        s = AcademicSettings(
            id=_new_id("as-"),
            tenant_id=tenant.id,
            student_leave_admin_approval_required=True,
        )
        db_session.add(s)
    else:
        s.student_leave_admin_approval_required = True
    db_session.flush()
    return s


@pytest.fixture
def teacher_on_leave_today(db_session, tenant, class_with_teacher):
    """Insert an approved TeacherLeave for the class teacher overlapping today,
    so the admin fallback eligibility check returns True."""
    from datetime import date
    from modules.teachers.models import TeacherLeave
    tl = TeacherLeave(
        id=_new_id("tl-"),
        tenant_id=tenant.id,
        teacher_id=class_with_teacher.class_teacher_id,
        leave_type="sick",
        start_date=date.today(),
        end_date=date.today(),
        reason="test",
        status="approved",
    )
    db_session.add(tl)
    db_session.flush()
    return tl


@pytest.fixture
def holiday_in_range(db_session, tenant):
    """Insert a non-recurring Holiday on the next Monday >= 2 weeks ahead.

    Holidays model uses (start_date, end_date) range, not a single 'date'
    column. The .date attribute we attach is for test convenience.
    """
    from datetime import date, timedelta
    from modules.holidays.models import Holiday

    today = date.today()
    days_ahead = (0 - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    target = today + timedelta(days=days_ahead + 14)

    h = Holiday(
        id=_new_id("h-"),
        tenant_id=tenant.id,
        name=f"Test Holiday {target.isoformat()}",
        holiday_type="school",
        start_date=target,
        end_date=target,
        is_recurring=False,
    )
    db_session.add(h)
    db_session.flush()
    h.date = target  # convenience attribute for tests
    return h
