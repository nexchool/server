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

from tests.conftest import grant_profile_to

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def _give_role(db_session, tenant, user_id: str, role_name: str):
    """Give the person behind this account an Authority Profile (ADR-013)."""
    from modules.auth.models import User
    from modules.rbac.models import Role

    role = Role.query.filter_by(tenant_id=tenant.id, name=role_name).first()
    if not role:
        role = Role(id=uuid.uuid4().hex, tenant_id=tenant.id, name=role_name)
        db_session.add(role)
        db_session.flush()

    grant_profile_to(User.query.get(user_id), role.id)
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
    from modules.rbac.services import get_user_roles
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
    remaining = {r["name"] for r in get_user_roles(user_id)}
    assert remaining == {"Teacher"}
