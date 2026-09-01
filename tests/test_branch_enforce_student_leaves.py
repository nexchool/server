"""A leave request is a fact about a child, so it belongs to that child's campus.

Student leaves had no branch scoping at all. Their visibility is decided by
*permission* — read.all sees everything, read.class sees the teacher's own
classes, read.own sees your own — and permission says nothing about which
campus a sub-admin runs. So a head of Campus A holding `student.leave.read.all`
read every campus's leave requests, including the stated reason, which is
routinely medical.

The approval path is worse than a read leak. `_actor_is_authorized_approver`
lets an admin with `student.leave.approve.all` act as fallback whenever the
child's class teacher is away — with no check that the child is theirs. A
campus head could approve and reject leave for children at campuses they have
no authority over.

Same rule as everywhere else: no UserSchoolUnit rows means unrestricted, which
is what every existing admin is.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from flask import g

from modules.auth.models import User
from modules.classes.models import Class
from modules.students.models import Student
from modules.sub_admins.models import UserSchoolUnit
from modules.teachers.models import Teacher
from modules.student_leaves import services as leaves


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def units(db_session, tenant):
    from modules.school_units.models import SchoolUnit

    a = SchoolUnit(id=_new_id("su-"), tenant_id=tenant.id, name="Campus A",
                   code=f"A-{uuid.uuid4().hex[:6]}")
    b = SchoolUnit(id=_new_id("su-"), tenant_id=tenant.id, name="Campus B",
                   code=f"B-{uuid.uuid4().hex[:6]}")
    db_session.add_all([a, b])
    db_session.flush()
    return a, b


@pytest.fixture
def year(db_session, tenant):
    from modules.academics.academic_year.models import AcademicYear

    ay = AcademicYear(id=_new_id("ay-"), tenant_id=tenant.id,
                      name=f"AY-{uuid.uuid4().hex[:6]}",
                      start_date=date(2026, 6, 1), end_date=date(2027, 3, 31))
    db_session.add(ay)
    db_session.flush()
    return ay


@pytest.fixture
def classes(db_session, tenant, units, year):
    a, b = units
    ca = Class(id=_new_id("c-"), tenant_id=tenant.id, name="Grade 3",
               section="A", academic_year_id=year.id, school_unit_id=a.id)
    cb = Class(id=_new_id("c-"), tenant_id=tenant.id, name="Grade 3",
               section="B", academic_year_id=year.id, school_unit_id=b.id)
    db_session.add_all([ca, cb])
    db_session.flush()
    return ca, cb


def _child(db_session, tenant, cls):
    from modules.people.models import Person

    suffix = uuid.uuid4().hex[:10]
    person = Person(id=f"pe-{suffix}", tenant_id=tenant.id, full_name="Child")
    db_session.add(person)
    db_session.flush()
    user = User(id=f"u-{suffix}", tenant_id=tenant.id,
                email=f"{suffix}@test.school", password_hash="x" * 60,
                name="Child", person_id=person.id)
    db_session.add(user)
    db_session.flush()
    student = Student(id=f"s-{suffix}", tenant_id=tenant.id, user_id=user.id,
                      person_id=person.id, admission_number=f"A-{suffix[:8]}",
                      class_id=cls.id, academic_year_id=cls.academic_year_id)
    db_session.add(student)
    db_session.flush()
    return student


def _class_teacher(db_session, tenant, cls):
    from tests.conftest import employ_for

    suffix = uuid.uuid4().hex[:10]
    user = User(id=f"u-{suffix}", tenant_id=tenant.id,
                email=f"t-{suffix}@test.school", password_hash="x" * 60,
                name="Class Teacher")
    db_session.add(user)
    db_session.flush()
    teacher = Teacher(id=_new_id("t-"), tenant_id=tenant.id, user_id=user.id,
                      staff_id=employ_for(user, employee_number=f"E-{suffix[:8]}").id)
    db_session.add(teacher)
    db_session.flush()
    return teacher


def _leave(db_session, tenant, student, cls, teacher, *, status="pending_admin"):
    from modules.student_leaves.models import StudentLeave

    leave = StudentLeave(
        id=_new_id("sl-"), tenant_id=tenant.id, student_id=student.id,
        class_id=cls.id, class_teacher_id=teacher.id, leave_type="sick",
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 2),
        reason="Fever", status=status,
    )
    db_session.add(leave)
    db_session.flush()
    return leave


def _teacher_is_away(db_session, tenant, teacher):
    """The condition that lets an admin act as fallback approver."""
    from modules.teachers.models import TeacherLeave
    from core.school_time import school_today

    today = school_today()
    row = TeacherLeave(
        id=_new_id("tl-"), tenant_id=tenant.id, teacher_id=teacher.id,
        leave_type="sick", start_date=today - timedelta(days=1),
        end_date=today + timedelta(days=1), status="approved",
        reason="Unwell",
    )
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def restricted_to_campus_a(db_session, tenant, units):
    a, _ = units
    user = User(id=_new_id("ru-"), tenant_id=tenant.id,
                email=f"ru-{uuid.uuid4().hex[:6]}@test.school",
                password_hash="x" * 60, name="Head of Campus A")
    db_session.add(user)
    db_session.flush()
    db_session.add(UserSchoolUnit(id=_new_id("usu-"), tenant_id=tenant.id,
                                  user_id=user.id, school_unit_id=a.id))
    db_session.flush()
    return user


@pytest.fixture
def unrestricted(db_session, tenant):
    """No UserSchoolUnit rows — every existing admin looks like this."""
    user = User(id=_new_id("uu-"), tenant_id=tenant.id,
                email=f"uu-{uuid.uuid4().hex[:6]}@test.school",
                password_hash="x" * 60, name="Trust Administrator")
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def sees_everything(monkeypatch):
    """Give the actor `read.all` / `approve.all`; permission is not the subject."""
    monkeypatch.setattr(
        "modules.rbac.services.has_permission",
        lambda user_id, perm, *a, **k: perm in (
            "student.leave.read.all", "student.leave.approve.all",
        ),
    )


def _as(flask_app, tenant, user):
    ctx = flask_app.test_request_context("/")
    ctx.push()
    g.pop("_branch_scope_allowed_unit_ids", None)
    g.pop("_branch_scope_allowed_class_ids", None)
    g.tenant_id = tenant.id
    g.current_user = user
    return ctx


@pytest.fixture
def two_campus_leaves(db_session, tenant, classes):
    ca, cb = classes
    ta = _class_teacher(db_session, tenant, ca)
    tb = _class_teacher(db_session, tenant, cb)
    return {
        "ours": _leave(db_session, tenant, _child(db_session, tenant, ca), ca, ta),
        "theirs": _leave(db_session, tenant, _child(db_session, tenant, cb), cb, tb),
        "their_teacher": tb,
    }


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def test_a_campus_head_sees_only_their_campus_leaves(
    flask_app, db_session, tenant, two_campus_leaves, restricted_to_campus_a,
    sees_everything,
):
    """The reason on a leave request is routinely medical."""
    ctx = _as(flask_app, tenant, restricted_to_campus_a)
    try:
        visible = {
            row.id
            for row in leaves.list_visible_for_user(restricted_to_campus_a)["items"]
        }
    finally:
        ctx.pop()

    assert visible == {two_campus_leaves["ours"].id}


def test_the_trust_administrator_still_sees_every_leave(
    flask_app, db_session, tenant, two_campus_leaves, unrestricted, sees_everything
):
    ctx = _as(flask_app, tenant, unrestricted)
    try:
        visible = {
            row.id for row in leaves.list_visible_for_user(unrestricted)["items"]
        }
    finally:
        ctx.pop()

    assert {two_campus_leaves["ours"].id, two_campus_leaves["theirs"].id} <= visible


def test_the_fallback_queue_is_scoped_to_the_campus(
    flask_app, db_session, tenant, two_campus_leaves, restricted_to_campus_a,
    sees_everything,
):
    """This queue is what an admin acts on, so it must not offer other campuses."""
    ctx = _as(flask_app, tenant, restricted_to_campus_a)
    try:
        _teacher_is_away(db_session, tenant, two_campus_leaves["their_teacher"])
        visible = {row.id for row in leaves.admin_fallback_queue(restricted_to_campus_a)}
    finally:
        ctx.pop()

    assert two_campus_leaves["theirs"].id not in visible


# ---------------------------------------------------------------------------
# Authority — the part that is not just a read
# ---------------------------------------------------------------------------

def test_a_campus_head_cannot_approve_another_campus_leave(
    flask_app, db_session, tenant, two_campus_leaves, restricted_to_campus_a,
    sees_everything,
):
    """Fallback approval was gated on the teacher being away, not on the child."""
    _teacher_is_away(db_session, tenant, two_campus_leaves["their_teacher"])

    ctx = _as(flask_app, tenant, restricted_to_campus_a)
    try:
        with pytest.raises(leaves.AuthorizationError):
            leaves.approve(two_campus_leaves["theirs"].id,
                           restricted_to_campus_a.id)
    finally:
        ctx.pop()


def test_a_campus_head_cannot_reject_another_campus_leave(
    flask_app, db_session, tenant, two_campus_leaves, restricted_to_campus_a,
    sees_everything,
):
    _teacher_is_away(db_session, tenant, two_campus_leaves["their_teacher"])

    ctx = _as(flask_app, tenant, restricted_to_campus_a)
    try:
        with pytest.raises(leaves.AuthorizationError):
            leaves.reject(two_campus_leaves["theirs"].id,
                          restricted_to_campus_a.id, "no")
    finally:
        ctx.pop()


def test_the_trust_administrator_can_still_approve_as_fallback(
    flask_app, db_session, tenant, two_campus_leaves, unrestricted, sees_everything
):
    """Unrestricted must keep working — this is every existing admin."""
    _teacher_is_away(db_session, tenant, two_campus_leaves["their_teacher"])

    ctx = _as(flask_app, tenant, unrestricted)
    try:
        updated = leaves.approve(two_campus_leaves["theirs"].id, unrestricted.id)
    finally:
        ctx.pop()

    assert updated.status == "approved"
