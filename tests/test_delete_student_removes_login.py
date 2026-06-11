"""delete_student must not leave an orphaned, still-active login behind.

Deleting a student hard-deletes the Student row; the backing User (Student role,
no other access) must go with it — otherwise it can still authenticate with no
profile row (its dashboard 404s) and the email stays reserved. A user who also
holds another role keeps their login and only loses the Student role.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

from flask import g

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def _give_role(db_session, tenant, user_id: str, role_name: str):
    from modules.rbac.models import Role, UserRole

    role = Role.query.filter_by(tenant_id=tenant.id, name=role_name).first()
    if not role:
        role = Role(id=uuid.uuid4().hex, tenant_id=tenant.id, name=role_name)
        db_session.add(role)
        db_session.flush()
    db_session.add(
        UserRole(
            id=uuid.uuid4().hex,
            tenant_id=tenant.id,
            user_id=user_id,
            role_id=role.id,
        )
    )
    db_session.flush()
    return role


def test_delete_student_removes_backing_user(flask_app, db_session, tenant, student):
    from modules.auth.models import User
    from modules.students.models import Student
    from modules.students import services

    user_id = student.user_id
    student_id = student.id
    _give_role(db_session, tenant, user_id, "Student")

    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        result = services.delete_student(student_id)

    assert result["success"] is True
    assert Student.query.get(student_id) is None
    # The orphan is gone: no user with that id remains (login + email freed).
    assert User.query.filter_by(id=user_id).first() is None


def test_delete_student_keeps_user_holding_another_role(
    flask_app, db_session, tenant, student
):
    from modules.auth.models import User
    from modules.rbac.models import Role, UserRole
    from modules.students.models import Student
    from modules.students import services

    user_id = student.user_id
    _give_role(db_session, tenant, user_id, "Student")
    _give_role(db_session, tenant, user_id, "Teacher")

    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        result = services.delete_student(student.id)

    assert result["success"] is True
    # Login preserved because the person holds another role...
    assert User.query.filter_by(id=user_id).first() is not None
    # ...but the Student role is detached, leaving only the other role.
    remaining = {
        r.name
        for r in Role.query.join(UserRole, Role.id == UserRole.role_id)
        .filter(UserRole.user_id == user_id)
        .all()
    }
    assert remaining == {"Teacher"}
