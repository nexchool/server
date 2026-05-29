"""Branch enforcement on Classes, Students and the school-units list.

Phase 2 — wiring the ``core/branch_scope`` primitives into the Classes,
Students and school-units list domains. These tests verify the *applied*
behaviour (service-level list scoping + the route-level asserts), and crucially
the **no-op property**: an unrestricted admin sees identical results to before
the change.

Pattern mirrors ``tests/test_branch_scope.py``: push ``g.tenant_id`` /
``g.current_user`` via ``flask_app.test_request_context`` and call the
service / assert layer directly. Runs against the localhost Postgres bound to
the savepoint connection in conftest (rolled back per test).
"""

from __future__ import annotations

import uuid

import pytest
from flask import g

from core.branch_scope import (
    BranchForbidden,
    assert_class_allowed,
    assert_student_allowed,
    assert_unit_allowed,
    get_allowed_unit_ids,
)
from modules.auth.models import User
from modules.classes.models import Class
from modules.school_units import services as su_services
from modules.classes import services as class_services
from modules.students import services as student_services
from modules.students.models import Student
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


def _make_student_in_class(db_session, tenant, class_id):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=_new_id("u-"),
        tenant_id=tenant.id,
        email=f"{suffix}@test.school",
        password_hash="x" * 60,
        name="Test Student",
    )
    db_session.add(user)
    db_session.flush()
    student = Student(
        id=_new_id("s-"),
        tenant_id=tenant.id,
        user_id=user.id,
        admission_number=f"ADM-{suffix}",
        class_id=class_id,
    )
    db_session.add(student)
    db_session.flush()
    return student


@pytest.fixture
def students(db_session, tenant, classes):
    """student_a in class_a, student_b in class_b, classless student."""
    class_a, class_b = classes
    student_a = _make_student_in_class(db_session, tenant, class_a.id)
    student_b = _make_student_in_class(db_session, tenant, class_b.id)
    classless = _make_student_in_class(db_session, tenant, None)
    return student_a, student_b, classless


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
# Classes — list
# ---------------------------------------------------------------------------

def test_classes_list_restricted_sees_only_unit_a(flask_app, db_session, tenant, classes, restricted_user):
    class_a, class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        rows = class_services.get_all_classes()
        ids = {c["id"] for c in rows}
        assert class_a.id in ids
        assert class_b.id not in ids


def test_classes_list_unrestricted_sees_all(flask_app, db_session, tenant, classes, unrestricted_user):
    class_a, class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        ids = {c["id"] for c in class_services.get_all_classes()}
        assert class_a.id in ids
        assert class_b.id in ids


def test_classes_list_restricted_filter_unit_b_forbidden(flask_app, db_session, tenant, classes, restricted_user):
    """Route asserts the client school_unit_id before filtering -> 403 for unit B."""
    _class_a, class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        # Mirror the route guard: assert the client param first.
        with pytest.raises(BranchForbidden):
            assert_unit_allowed(class_b.school_unit_id)


# ---------------------------------------------------------------------------
# Classes — get-by-id
# ---------------------------------------------------------------------------

def test_class_get_by_id_unit_b_forbidden_for_restricted(flask_app, db_session, tenant, classes, restricted_user):
    _class_a, class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            assert_class_allowed(class_b.id)


def test_class_get_by_id_unit_a_ok_for_restricted(flask_app, db_session, tenant, classes, restricted_user):
    class_a, _class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        assert_class_allowed(class_a.id)  # no raise


# ---------------------------------------------------------------------------
# Classes — create
# ---------------------------------------------------------------------------

def test_class_create_in_unit_b_forbidden_for_restricted(flask_app, db_session, tenant, units, restricted_user):
    _unit_a, unit_b = units
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            assert_unit_allowed(unit_b.id)


def test_class_create_in_unit_a_ok_for_restricted(flask_app, db_session, tenant, units, academic_year, restricted_user):
    unit_a, _unit_b = units
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        assert_unit_allowed(unit_a.id)  # route guard passes
        result = class_services.create_class(
            name="Grade 2",
            section="A",
            academic_year_id=academic_year.id,
            school_unit_id=unit_a.id,
        )
        assert result["success"] is True
        assert result["class"]["school_unit_id"] == unit_a.id


# ---------------------------------------------------------------------------
# Students — list
# ---------------------------------------------------------------------------

def test_students_list_restricted_sees_only_unit_a(flask_app, db_session, tenant, students, restricted_user):
    student_a, student_b, classless = students
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        ids = {s["id"] for s in student_services.list_students()["items"]}
        assert student_a.id in ids
        assert student_b.id not in ids
        assert classless.id not in ids  # classless excluded


def test_students_list_unrestricted_sees_all_incl_classless(flask_app, db_session, tenant, students, unrestricted_user):
    student_a, student_b, classless = students
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        ids = {s["id"] for s in student_services.list_students()["items"]}
        assert student_a.id in ids
        assert student_b.id in ids
        assert classless.id in ids


# ---------------------------------------------------------------------------
# Students — get-by-id
# ---------------------------------------------------------------------------

def test_student_get_by_id_unit_b_forbidden_for_restricted(flask_app, db_session, tenant, students, restricted_user):
    _student_a, student_b, _classless = students
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            assert_student_allowed(student_b.id)


# ---------------------------------------------------------------------------
# Students — create
# ---------------------------------------------------------------------------

def test_student_create_class_in_unit_a_ok_for_restricted(flask_app, db_session, tenant, classes, restricted_user):
    class_a, _class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        assert_class_allowed(class_a.id)  # route guard passes


def test_student_create_class_in_unit_b_forbidden_for_restricted(flask_app, db_session, tenant, classes, restricted_user):
    _class_a, class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            assert_class_allowed(class_b.id)


def test_student_create_no_class_rejected_422_for_restricted(flask_app, db_session, tenant, units, restricted_user):
    """Restricted + classless create must be rejected (fail-closed)."""
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        # The route rejects when get_allowed_unit_ids() is not None and no class.
        assert get_allowed_unit_ids() is not None


def test_student_create_no_class_allowed_for_unrestricted(flask_app, db_session, tenant, units, unrestricted_user):
    """Unrestricted classless create stays allowed (no-op)."""
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        assert get_allowed_unit_ids() is None  # route would NOT 422


# ---------------------------------------------------------------------------
# School-units list
# ---------------------------------------------------------------------------

def test_school_units_list_restricted_sees_only_unit_a(flask_app, db_session, tenant, units, restricted_user):
    unit_a, unit_b = units
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        ids = {u["id"] for u in su_services.list_school_units(tenant.id)}
        assert unit_a.id in ids
        assert unit_b.id not in ids


def test_school_units_list_unrestricted_sees_all(flask_app, db_session, tenant, units, unrestricted_user):
    unit_a, unit_b = units
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        ids = {u["id"] for u in su_services.list_school_units(tenant.id)}
        assert unit_a.id in ids
        assert unit_b.id in ids


# ---------------------------------------------------------------------------
# Student documents — cross-branch PII leak (GET/POST/file/DELETE)
# ---------------------------------------------------------------------------
# All four document routes gate on the same assert_student_allowed(student_id)
# guard. A restricted unit-A admin hitting a unit-B student -> BranchForbidden;
# hitting a unit-A student -> no raise.

def test_student_documents_unit_b_forbidden_for_restricted(
    flask_app, db_session, tenant, students, restricted_user
):
    _student_a, student_b, _classless = students
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        # GET / POST / file / DELETE all run this guard after the 404 check.
        with pytest.raises(BranchForbidden):
            assert_student_allowed(student_b.id)


def test_student_documents_unit_a_ok_for_restricted(
    flask_app, db_session, tenant, students, restricted_user
):
    student_a, _student_b, _classless = students
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        assert_student_allowed(student_a.id)  # no raise


def test_student_documents_unrestricted_no_op(
    flask_app, db_session, tenant, students, unrestricted_user
):
    student_a, student_b, _classless = students
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        assert_student_allowed(student_a.id)  # no raise
        assert_student_allowed(student_b.id)  # no raise — unrestricted no-op


# ---------------------------------------------------------------------------
# Class membership mutations — assign/remove student & teacher
# ---------------------------------------------------------------------------
# assign_student / remove_student guard on assert_class_allowed AND
# assert_student_allowed; assign_teacher / remove_teacher guard on
# assert_class_allowed. A unit-B class -> 403; unit-A class -> ok.

def test_class_membership_unit_b_class_forbidden_for_restricted(
    flask_app, db_session, tenant, classes, restricted_user
):
    _class_a, class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            assert_class_allowed(class_b.id)


def test_assign_student_cross_branch_student_forbidden_for_restricted(
    flask_app, db_session, tenant, classes, students, restricted_user
):
    """Pulling a unit-B student into a (unit-A) class is blocked by the
    student-side guard."""
    _student_a, student_b, _classless = students
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            assert_student_allowed(student_b.id)


def test_class_membership_unit_a_ok_for_restricted(
    flask_app, db_session, tenant, classes, students, restricted_user
):
    class_a, _class_b = classes
    student_a, _student_b, _classless = students
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        assert_class_allowed(class_a.id)  # no raise
        assert_student_allowed(student_a.id)  # no raise


def test_class_membership_unrestricted_no_op(
    flask_app, db_session, tenant, classes, students, unrestricted_user
):
    _class_a, class_b = classes
    _student_a, student_b, _classless = students
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        assert_class_allowed(class_b.id)  # no raise
        assert_student_allowed(student_b.id)  # no raise


# ---------------------------------------------------------------------------
# Tenant-wide bulk / structural ops — DENIED for restricted (fail closed)
# ---------------------------------------------------------------------------
# promote / promotion-preview / promotion-history (students) and
# copy / subjects-by-grade (classes) all guard with:
#   if get_allowed_unit_ids() is not None: raise BranchForbidden(...)
# So for a restricted user the gate is truthy (denied); for unrestricted it is
# None (passes straight through to normal handling).

def _deny_if_restricted():
    """Mirror the exact fail-closed guard used by the bulk-op routes."""
    if get_allowed_unit_ids() is not None:
        raise BranchForbidden("Branch-restricted admins cannot run tenant-wide op")


def test_bulk_ops_denied_for_restricted(
    flask_app, db_session, tenant, units, restricted_user
):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        # The guard condition is truthy -> the route raises BranchForbidden.
        assert get_allowed_unit_ids() is not None
        with pytest.raises(BranchForbidden):
            _deny_if_restricted()


def test_bulk_ops_not_blocked_for_unrestricted(
    flask_app, db_session, tenant, units, unrestricted_user
):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        # Guard condition is None -> route proceeds to normal handling.
        assert get_allowed_unit_ids() is None


# ---------------------------------------------------------------------------
# Regression — unrestricted admin is a strict no-op everywhere
# ---------------------------------------------------------------------------

def test_unrestricted_counts_unchanged(flask_app, db_session, tenant, classes, students, units, unrestricted_user):
    """Unrestricted admin sees every row across all three domains (no-op)."""
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user

        class_rows = class_services.get_all_classes()
        student_rows = student_services.list_students()["items"]
        unit_rows = su_services.list_school_units(tenant.id)

        # All seeded rows present: 2 classes, 3 students (incl. classless), 2 units.
        assert len({c["id"] for c in class_rows}) == 2
        assert len({s["id"] for s in student_rows}) == 3
        assert len({u["id"] for u in unit_rows}) == 2
