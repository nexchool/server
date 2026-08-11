"""Attendance resolves teaching through the Teaching Assignment service.

ADR-014: operational modules never read the tables that express teaching, and
never the `classes.teacher_id` cache — which names the teacher, not their
login, since migration 095. These tests pin the cutover:

- marking rights come from the class-teacher responsibility (with its
  `allow_attendance_marking` toggle), not from the cache;
- the deleted legacy branch (cache == login) grants nothing any more;
- the owner-table writers keep the cache agreeing (the drift family the
  original guard did not cover);
- a delegated session marker must be this organization's teacher.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from flask import g

from modules.academics.backbone.models import ClassTeacherAssignment
from modules.auth.models import User
from modules.classes.models import Class
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
def klass(db_session, tenant, academic_year):
    cls = Class(
        id=_new_id("c-"), tenant_id=tenant.id, name="Grade 6", section="A",
        academic_year_id=academic_year.id,
    )
    db_session.add(cls)
    db_session.flush()
    return cls


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


def _make_class_teacher(db_session, tenant, cls, teacher, *, may_mark=True):
    db_session.add(
        ClassTeacherAssignment(
            id=_new_id("cta-"), tenant_id=tenant.id, class_id=cls.id,
            teacher_id=teacher.id, role="primary", is_active=True,
            allow_attendance_marking=may_mark,
        )
    )
    cls.teacher_id = teacher.id
    db_session.flush()


def test_marking_rights_come_from_the_responsibility(ctx, tenant, db_session, klass):
    from modules.attendance.services import get_teacher_class_ids

    marker = _teacher(db_session, tenant)
    _make_class_teacher(db_session, tenant, klass, marker, may_mark=True)

    assert klass.id in get_teacher_class_ids(marker.user_id)


def test_a_responsibility_without_marking_rights_grants_none(
    ctx, tenant, db_session, klass
):
    from modules.attendance.services import get_teacher_class_ids

    watcher = _teacher(db_session, tenant)
    _make_class_teacher(db_session, tenant, klass, watcher, may_mark=False)

    assert klass.id not in get_teacher_class_ids(watcher.user_id)


def test_the_cache_alone_no_longer_grants_marking(ctx, tenant, db_session, klass):
    """The deleted legacy branch: cache set, no owner row -> no access.

    Migration 095 gives every cached class teacher an owner row, so this
    state cannot arise from data it migrates — only from a writer bypassing
    the owner table, which must not quietly confer authority.
    """
    from modules.attendance.services import get_teacher_class_ids
    from modules.attendance.session_services import can_user_mark_session

    impostor = _teacher(db_session, tenant)
    klass.teacher_id = impostor.id  # cache only, no ClassTeacherAssignment
    db_session.flush()

    assert klass.id not in get_teacher_class_ids(impostor.user_id)

    session = _draft_session(db_session, tenant, klass)
    assert not can_user_mark_session(tenant.id, impostor.user_id, session, klass.id)


def _draft_session(db_session, tenant, cls):
    from modules.academics.backbone.models import AttendanceSession
    from core.school_time import school_today

    s = AttendanceSession(
        id=_new_id("as-"), tenant_id=tenant.id, class_id=cls.id,
        session_date=school_today(), status="draft",
    )
    db_session.add(s)
    db_session.flush()
    return s


def test_the_class_teacher_of_the_day_may_mark(ctx, tenant, db_session, klass):
    from modules.attendance.session_services import can_user_mark_session

    marker = _teacher(db_session, tenant)
    bystander = _teacher(db_session, tenant)
    _make_class_teacher(db_session, tenant, klass, marker, may_mark=True)

    session = _draft_session(db_session, tenant, klass)
    assert can_user_mark_session(tenant.id, marker.user_id, session, klass.id)
    assert not can_user_mark_session(tenant.id, bystander.user_id, session, klass.id)


def test_owner_writes_keep_the_cache_agreeing(ctx, tenant, db_session, klass):
    """The CTA APIs used to write the owner and leave the cache stale."""
    from modules.academics.services.class_teacher_assignments import (
        create_assignment,
        delete_assignment,
    )

    teacher = _teacher(db_session, tenant)
    created = create_assignment(
        tenant.id, klass.id, {"teacher_id": teacher.id, "role": "primary"}
    )
    assert created["success"], created
    assert klass.teacher_id == teacher.id

    removed = delete_assignment(tenant.id, klass.id, created["assignment"]["id"])
    assert removed["success"], removed
    db_session.refresh(klass)
    assert klass.teacher_id is None


def test_a_session_marker_must_be_our_teacher(ctx, tenant, db_session, klass):
    from modules.attendance.session_services import get_or_create_session
    from core.school_time import school_today

    admin = _teacher(db_session, tenant)
    result = get_or_create_session(
        tenant_id=tenant.id,
        class_id=klass.id,
        session_date=school_today(),
        user_id=admin.user_id,
        assigned_marker_teacher_id=_new_id("t-"),  # nobody here
    )
    assert result["success"] is False
    assert "Unknown teacher" in result["error"]
