"""delete_teacher must not leave an orphaned, still-active login behind.

Deleting a teacher removes the Teacher profile and SOFT-deactivates its backing
user (sets deleted_at) rather than hard-deleting it: a teacher's user is
referenced by NOT NULL / NO ACTION FKs (attendance.marked_by, classes.teacher_id),
so soft delete blocks login while preserving history. A user who also holds
another role keeps their login, losing only the Teacher role.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

from flask import g

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def _make_teacher(db_session, tenant):
    from modules.auth.models import User
    from modules.teachers.models import Teacher

    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=uuid.uuid4().hex,
        tenant_id=tenant.id,
        email=f"t-{suffix}@test.school",
        password_hash="x" * 60,
        name="Test Teacher",
    )
    db_session.add(user)
    db_session.flush()
    teacher = Teacher(
        id=uuid.uuid4().hex,
        tenant_id=tenant.id,
        user_id=user.id,
        employee_id=f"EMP-{suffix}",
    )
    db_session.add(teacher)
    db_session.flush()
    return teacher


def _give_role(db_session, tenant, user_id: str, role_name: str):
    from modules.rbac.models import Role, UserRole

    role = Role.query.filter_by(tenant_id=tenant.id, name=role_name).first()
    if not role:
        role = Role(id=uuid.uuid4().hex, tenant_id=tenant.id, name=role_name)
        db_session.add(role)
        db_session.flush()
    db_session.add(
        UserRole(id=uuid.uuid4().hex, tenant_id=tenant.id, user_id=user_id, role_id=role.id)
    )
    db_session.flush()


def test_delete_teacher_soft_deactivates_backing_user(flask_app, db_session, tenant):
    from modules.auth.models import User
    from modules.teachers.models import Teacher
    from modules.teachers import services

    teacher = _make_teacher(db_session, tenant)
    user_id = teacher.user_id
    teacher_id = teacher.id
    email = User.query.get(user_id).email
    _give_role(db_session, tenant, user_id, "Teacher")

    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        result = services.delete_teacher(teacher_id)

    assert result["success"] is True
    assert Teacher.query.get(teacher_id) is None
    user = User.query.filter_by(id=user_id).first()
    assert user is not None              # row kept — preserves FK history
    assert user.deleted_at is not None   # deactivated — cannot log in
    assert User.get_user_by_email(email, tenant_id=tenant.id) is None  # no active login


def test_delete_teacher_clears_homeroom_pointer_and_deletes_cleanly(
    flask_app, db_session, tenant
):
    """A teacher who is a class's homeroom teacher (classes.teacher_id -> users.id,
    NO ACTION) deletes cleanly, and the pointer is cleared while the class survives."""
    from modules.academics.academic_year.models import AcademicYear
    from modules.classes.models import Class
    from modules.teachers import services

    teacher = _make_teacher(db_session, tenant)
    ay = AcademicYear(
        id=uuid.uuid4().hex,
        tenant_id=tenant.id,
        name="2025-2026",
        start_date="2025-06-01",
        end_date="2026-03-31",
    )
    db_session.add(ay)
    db_session.flush()
    cls = Class(
        id=uuid.uuid4().hex,
        tenant_id=tenant.id,
        name="Grade 5",
        section="A",
        academic_year_id=ay.id,
        teacher_id=teacher.user_id,  # homeroom pointer -> this teacher's user
    )
    db_session.add(cls)
    db_session.flush()
    class_id = cls.id

    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        result = services.delete_teacher(teacher.id)

    assert result["success"] is True
    # Fresh scalar reads (bulk UPDATE used synchronize_session=False).
    assert db_session.query(Class.id).filter_by(id=class_id).scalar() == class_id
    assert db_session.query(Class.teacher_id).filter_by(id=class_id).scalar() is None


def test_delete_teacher_keeps_user_holding_another_role(flask_app, db_session, tenant):
    from modules.auth.models import User
    from modules.rbac.models import Role, UserRole
    from modules.teachers import services

    teacher = _make_teacher(db_session, tenant)
    user_id = teacher.user_id
    _give_role(db_session, tenant, user_id, "Teacher")
    _give_role(db_session, tenant, user_id, "Admin")

    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        result = services.delete_teacher(teacher.id)

    assert result["success"] is True
    # Login preserved (still active) because the person holds another role...
    user = User.query.filter_by(id=user_id).first()
    assert user is not None and user.deleted_at is None
    # ...and only the Teacher role was detached.
    remaining = {
        r.name
        for r in Role.query.join(UserRole, Role.id == UserRole.role_id)
        .filter(UserRole.user_id == user_id)
        .all()
    }
    assert remaining == {"Admin"}
