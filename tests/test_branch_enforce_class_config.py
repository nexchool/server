"""Branch enforcement on class-subject and class-teacher config endpoints.

Phase 2 (P2-T4 follow-up) — the 13 class-configuration service functions in
``modules/academics/services/class_subjects``, ``class_subject_teachers`` and
``class_teacher_assignments`` are keyed by ``class_id`` and previously had **no**
branch check: a restricted sub-admin (granted the classes module) could read or
mutate another branch's class config by passing an out-of-branch ``class_id``.

Each of those functions now calls ``assert_class_allowed(class_id)`` (no-op for
unrestricted users, ``BranchForbidden`` -> 403 for a restricted user hitting an
out-of-branch class). These tests verify a representative read and mutation per
domain at the service layer, mirroring
``tests/test_branch_enforce_attendance_timetable.py``: push ``g.tenant_id`` /
``g.current_user`` via ``flask_app.test_request_context`` and call the service
directly. Runs against the localhost Postgres bound to the savepoint connection
in conftest (rolled back per test).
"""

from __future__ import annotations

import uuid

import pytest
from flask import g

from core.branch_scope import BranchForbidden
from modules.academics.services import (
    class_subject_teachers,
    class_subjects,
    class_teacher_assignments,
)
from modules.auth.models import User
from modules.classes.models import Class
from modules.sub_admins.models import UserSchoolUnit


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Fixtures
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
def academic_year(db_session, tenant):
    from modules.academics.academic_year.models import AcademicYear

    ay = AcademicYear(
        id=_new_id("ay-"),
        tenant_id=tenant.id,
        name="2025-2026",
        start_date="2025-06-01",
        end_date="2026-03-31",
    )
    db_session.add(ay)
    db_session.flush()
    return ay


@pytest.fixture
def classes(db_session, tenant, units, academic_year):
    """class_a in unit A, class_b in unit B."""
    unit_a, unit_b = units
    class_a = Class(
        id=_new_id("c-"),
        tenant_id=tenant.id,
        name="Grade 1",
        section="A",
        academic_year_id=academic_year.id,
        school_unit_id=unit_a.id,
    )
    class_b = Class(
        id=_new_id("c-"),
        tenant_id=tenant.id,
        name="Grade 1",
        section="B",
        academic_year_id=academic_year.id,
        school_unit_id=unit_b.id,
    )
    db_session.add_all([class_a, class_b])
    db_session.flush()
    return class_a, class_b


@pytest.fixture
def unrestricted_user(db_session, tenant):
    """A tenant user with NO UserSchoolUnit rows -> unrestricted."""
    u = User(
        id=_new_id("uu-"),
        tenant_id=tenant.id,
        email=f"uu-{uuid.uuid4().hex[:6]}@test.school",
        password_hash="x" * 60,
        name="Unrestricted Admin",
    )
    db_session.add(u)
    db_session.flush()
    return u


@pytest.fixture
def restricted_user(db_session, tenant, units):
    """A tenant user restricted to unit A only."""
    unit_a, _unit_b = units
    u = User(
        id=_new_id("ru-"),
        tenant_id=tenant.id,
        email=f"ru-{uuid.uuid4().hex[:6]}@test.school",
        password_hash="x" * 60,
        name="Restricted Sub-Admin",
    )
    db_session.add(u)
    db_session.flush()
    db_session.add(
        UserSchoolUnit(
            id=_new_id("usu-"),
            tenant_id=tenant.id,
            user_id=u.id,
            school_unit_id=unit_a.id,
        )
    )
    db_session.flush()
    return u


# ---------------------------------------------------------------------------
# Class subjects — read (list_for_class) + mutation (create_offering)
# ---------------------------------------------------------------------------

def test_class_subjects_read_unit_b_forbidden_for_restricted(
    flask_app, db_session, tenant, classes, restricted_user
):
    _class_a, class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            class_subjects.list_for_class(tenant.id, class_b.id)


def test_class_subjects_read_unit_a_ok_for_restricted(
    flask_app, db_session, tenant, classes, restricted_user
):
    class_a, _class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        result = class_subjects.list_for_class(tenant.id, class_a.id)
        assert result["success"] is True


def test_class_subjects_read_unrestricted_no_op_both(
    flask_app, db_session, tenant, classes, unrestricted_user
):
    class_a, class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        assert class_subjects.list_for_class(tenant.id, class_a.id)["success"] is True
        assert class_subjects.list_for_class(tenant.id, class_b.id)["success"] is True


def test_class_subjects_create_unit_b_forbidden_for_restricted(
    flask_app, db_session, tenant, classes, restricted_user
):
    _class_a, class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        # The branch assert runs before any payload validation / DB read.
        with pytest.raises(BranchForbidden):
            class_subjects.create_offering(tenant.id, class_b.id, {})


def test_class_subjects_create_unit_a_not_branch_blocked_for_restricted(
    flask_app, db_session, tenant, classes, restricted_user
):
    """In-branch class: the assert is a no-op, so no BranchForbidden is raised.

    The call may still fail validation (no subject_id) but that is *not* a
    branch error — what matters is the branch gate lets the in-branch class
    through.
    """
    class_a, _class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        result = class_subjects.create_offering(tenant.id, class_a.id, {})
        # Reaches validation logic (subject_id required) -> not a branch block.
        assert result["success"] is False
        assert "subject_id" in result["error"]


# ---------------------------------------------------------------------------
# Subject teachers — read (list_for_class) + mutation (create_assignment)
# ---------------------------------------------------------------------------

def test_subject_teachers_read_unit_b_forbidden_for_restricted(
    flask_app, db_session, tenant, classes, restricted_user
):
    _class_a, class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            class_subject_teachers.list_for_class(tenant.id, class_b.id)


def test_subject_teachers_read_unit_a_ok_for_restricted(
    flask_app, db_session, tenant, classes, restricted_user
):
    class_a, _class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        result = class_subject_teachers.list_for_class(tenant.id, class_a.id)
        assert result["success"] is True


def test_subject_teachers_create_unit_b_forbidden_for_restricted(
    flask_app, db_session, tenant, classes, restricted_user
):
    _class_a, class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            class_subject_teachers.create_assignment(tenant.id, class_b.id, {})


# ---------------------------------------------------------------------------
# Class teachers — read (list_for_class) + mutation (create_assignment)
# ---------------------------------------------------------------------------

def test_class_teachers_read_unit_b_forbidden_for_restricted(
    flask_app, db_session, tenant, classes, restricted_user
):
    _class_a, class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            class_teacher_assignments.list_for_class(tenant.id, class_b.id)


def test_class_teachers_read_unit_a_ok_for_restricted(
    flask_app, db_session, tenant, classes, restricted_user
):
    class_a, _class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        result = class_teacher_assignments.list_for_class(tenant.id, class_a.id)
        assert result["success"] is True


def test_class_teachers_create_unit_b_forbidden_for_restricted(
    flask_app, db_session, tenant, classes, restricted_user
):
    _class_a, class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            class_teacher_assignments.create_assignment(tenant.id, class_b.id, {})


def test_class_teachers_create_unrestricted_no_op_both(
    flask_app, db_session, tenant, classes, unrestricted_user
):
    """Unrestricted admin is not branch-blocked on either class (no-op)."""
    class_a, class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        # No BranchForbidden for either; both reach validation (teacher_id req).
        for cls in (class_a, class_b):
            result = class_teacher_assignments.create_assignment(tenant.id, cls.id, {})
            assert result["success"] is False
            assert "teacher_id" in result["error"]
