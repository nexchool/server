"""Tests for core/branch_scope — per-sub-admin branch (school-unit) scoping.

Covers the resolver (unrestricted vs restricted, caching), the asserts
(in-branch pass, out-of-branch 403, classless fail-closed), and a filter
helper (restricted narrows rows, unrestricted is a strict no-op).

Runs against the localhost Postgres bound to the savepoint connection in
conftest (changes rolled back per test). g.current_user / g.tenant_id are
pushed via flask_app.test_request_context, mirroring
tests/test_superadmin_god_login.py.
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
    filter_by_class_ids,
    filter_classes_by_branch,
    filter_fees_by_branch,
    filter_students_by_branch,
    get_allowed_class_ids,
    get_allowed_unit_ids,
)
from modules.auth.models import User
from modules.classes.models import Class
from modules.students.models import Student
from modules.sub_admins.models import UserSchoolUnit


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Fixtures: school units, academic year, classes, students, users
# ---------------------------------------------------------------------------

@pytest.fixture
def units(db_session, tenant):
    """Two school units (branches) in the tenant."""
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
    """One class per unit: class_a in unit A, class_b in unit B."""
    unit_a, unit_b = units
    class_a = Class(
        id=_new_id("c-"),
        tenant_id=tenant.id,
        section="A",
        academic_year_id=academic_year.id,
        school_unit_id=unit_a.id,
    )
    class_b = Class(
        id=_new_id("c-"),
        tenant_id=tenant.id,
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
def platform_admin_user(db_session, tenant):
    u = User(
        id=_new_id("pa-"),
        tenant_id=tenant.id,
        email=f"pa-{uuid.uuid4().hex[:6]}@test.school",
        password_hash="x" * 60,
        name="Platform Admin",
        is_platform_admin=True,
    )
    db_session.add(u)
    db_session.flush()
    return u


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
# get_allowed_unit_ids
# ---------------------------------------------------------------------------

def test_platform_admin_is_unrestricted(flask_app, db_session, tenant, platform_admin_user):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = platform_admin_user
        assert get_allowed_unit_ids() is None


def test_user_with_no_rows_is_unrestricted(flask_app, db_session, tenant, unrestricted_user):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        assert get_allowed_unit_ids() is None


def test_restricted_user_returns_exact_set(flask_app, db_session, tenant, units, restricted_user):
    unit_a, _unit_b = units
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        assert get_allowed_unit_ids() == {unit_a.id}


def test_no_request_context_is_unrestricted():
    # Outside any request context the resolver must not blow up.
    assert get_allowed_unit_ids() is None


def test_allowed_units_cached_within_request(flask_app, db_session, tenant, restricted_user):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        first = get_allowed_unit_ids()
        # Drop the user: an uncached call would now return None, a cached one
        # returns the prior set. Confirms the result is cached on g.
        g.current_user = None
        second = get_allowed_unit_ids()
        assert second is first
        assert second is not None


# ---------------------------------------------------------------------------
# get_allowed_class_ids
# ---------------------------------------------------------------------------

def test_allowed_class_ids_restricted(flask_app, db_session, tenant, classes, restricted_user):
    class_a, class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        allowed = get_allowed_class_ids()
        assert allowed == {class_a.id}
        assert class_b.id not in allowed


def test_allowed_class_ids_none_when_unrestricted(flask_app, db_session, tenant, classes, unrestricted_user):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        assert get_allowed_class_ids() is None


# ---------------------------------------------------------------------------
# assert_unit_allowed
# ---------------------------------------------------------------------------

def test_assert_unit_allowed_in_branch(flask_app, db_session, tenant, units, restricted_user):
    unit_a, _unit_b = units
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        assert_unit_allowed(unit_a.id)  # no raise


def test_assert_unit_allowed_out_of_branch(flask_app, db_session, tenant, units, restricted_user):
    _unit_a, unit_b = units
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            assert_unit_allowed(unit_b.id)


def test_assert_unit_allowed_noop_for_unrestricted(flask_app, db_session, tenant, units, unrestricted_user):
    _unit_a, unit_b = units
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        assert_unit_allowed(unit_b.id)  # no raise even for "other" unit


# ---------------------------------------------------------------------------
# assert_class_allowed
# ---------------------------------------------------------------------------

def test_assert_class_allowed_in_branch(flask_app, db_session, tenant, classes, restricted_user):
    class_a, _class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        assert_class_allowed(class_a.id)  # no raise


def test_assert_class_allowed_out_of_branch(flask_app, db_session, tenant, classes, restricted_user):
    _class_a, class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            assert_class_allowed(class_b.id)


def test_assert_class_allowed_missing_class_defers(flask_app, db_session, tenant, restricted_user):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        # Non-existent class id -> no raise (caller's 404 path handles it).
        assert_class_allowed(_new_id("missing-"))


def test_assert_class_allowed_noop_for_platform_admin(flask_app, db_session, tenant, classes, platform_admin_user):
    _class_a, class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = platform_admin_user
        assert_class_allowed(class_b.id)  # no raise


# ---------------------------------------------------------------------------
# assert_student_allowed
# ---------------------------------------------------------------------------

def test_assert_student_allowed_in_branch(flask_app, db_session, tenant, students, restricted_user):
    student_a, _student_b, _classless = students
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        assert_student_allowed(student_a.id)  # no raise


def test_assert_student_allowed_out_of_branch(flask_app, db_session, tenant, students, restricted_user):
    _student_a, student_b, _classless = students
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            assert_student_allowed(student_b.id)


def test_assert_student_classless_fails_closed_for_restricted(flask_app, db_session, tenant, students, restricted_user):
    _student_a, _student_b, classless = students
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            assert_student_allowed(classless.id)


def test_assert_student_classless_passes_for_unrestricted(flask_app, db_session, tenant, students, unrestricted_user):
    _student_a, _student_b, classless = students
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        assert_student_allowed(classless.id)  # no raise


# ---------------------------------------------------------------------------
# 403 mapping via the registered error handler
# ---------------------------------------------------------------------------

def test_branch_forbidden_maps_to_403(flask_app):
    @flask_app.route("/__test_branch_forbidden__")
    def _raise():
        raise BranchForbidden()

    client = flask_app.test_client()
    resp = client.get("/__test_branch_forbidden__")
    assert resp.status_code == 403
    body = resp.get_json()
    assert body["success"] is False
    assert body["error"] == "BranchForbidden"


# ---------------------------------------------------------------------------
# Filter helpers
# ---------------------------------------------------------------------------

def test_filter_classes_by_branch_restricted(flask_app, db_session, tenant, classes, restricted_user):
    class_a, class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        rows = filter_classes_by_branch(Class.query).all()
        ids = {c.id for c in rows}
        assert class_a.id in ids
        assert class_b.id not in ids


def test_filter_classes_by_branch_noop_for_unrestricted(flask_app, db_session, tenant, classes, unrestricted_user):
    class_a, class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        ids = {c.id for c in filter_classes_by_branch(Class.query).all()}
        assert class_a.id in ids
        assert class_b.id in ids


def test_filter_students_by_branch_restricted(flask_app, db_session, tenant, students, restricted_user):
    student_a, student_b, classless = students
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        ids = {s.id for s in filter_students_by_branch(Student.query).all()}
        assert student_a.id in ids
        assert student_b.id not in ids
        assert classless.id not in ids  # classless excluded


# ---------------------------------------------------------------------------
# filter_by_class_ids — direct class-FK models (attendance / timetable)
# ---------------------------------------------------------------------------

def _make_attendance(db_session, tenant, class_id, student_id, marked_by):
    """One Attendance row (model carries a direct class_id FK)."""
    from datetime import date

    from modules.attendance.models import Attendance

    att = Attendance(
        id=_new_id("att-"),
        tenant_id=tenant.id,
        date=date(2025, 6, 2),
        class_id=class_id,
        student_id=student_id,
        status="present",
        marked_by=marked_by,
    )
    db_session.add(att)
    db_session.flush()
    return att


@pytest.fixture
def attendance_rows(db_session, tenant, classes, students, unrestricted_user):
    """Attendance in the in-branch class (A) and the out-of-branch class (B).

    ``marked_by`` reuses the unrestricted_user (a real users.id) so the
    non-null FK is satisfied without coupling to the row under test.
    """
    class_a, class_b = classes
    student_a, student_b, _classless = students
    att_a = _make_attendance(db_session, tenant, class_a.id, student_a.id, unrestricted_user.id)
    att_b = _make_attendance(db_session, tenant, class_b.id, student_b.id, unrestricted_user.id)
    return att_a, att_b


def test_filter_by_class_ids_restricted(flask_app, db_session, tenant, attendance_rows, restricted_user):
    from modules.attendance.models import Attendance

    att_a, att_b = attendance_rows
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        ids = {
            a.id
            for a in filter_by_class_ids(Attendance.query, Attendance.class_id).all()
        }
        assert att_a.id in ids          # in-branch class A
        assert att_b.id not in ids      # out-of-branch class B excluded


def test_filter_by_class_ids_noop_for_unrestricted(flask_app, db_session, tenant, attendance_rows, unrestricted_user):
    from modules.attendance.models import Attendance

    att_a, att_b = attendance_rows
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        ids = {
            a.id
            for a in filter_by_class_ids(Attendance.query, Attendance.class_id).all()
        }
        assert att_a.id in ids
        assert att_b.id in ids          # strict no-op: both rows returned


# ---------------------------------------------------------------------------
# filter_fees_by_branch — student-FK fee model (student -> class -> unit chain)
# ---------------------------------------------------------------------------

def _make_invoice(db_session, tenant, student_id):
    """One FeeInvoice row (model carries a direct student_id FK)."""
    from datetime import date

    from modules.fees.models import FeeInvoice

    invoice = FeeInvoice(
        id=_new_id("inv-"),
        tenant_id=tenant.id,
        student_id=student_id,
        invoice_number=f"INV-{uuid.uuid4().hex[:8]}",
        academic_year="2025-2026",
        issue_date=date(2025, 6, 1),
        due_date=date(2025, 6, 30),
        total_amount=1000,
    )
    db_session.add(invoice)
    db_session.flush()
    return invoice


@pytest.fixture
def fee_invoices(db_session, tenant, students):
    """Invoices for the in-branch student, out-of-branch student, and classless student."""
    student_a, student_b, classless = students
    inv_a = _make_invoice(db_session, tenant, student_a.id)
    inv_b = _make_invoice(db_session, tenant, student_b.id)
    inv_classless = _make_invoice(db_session, tenant, classless.id)
    return inv_a, inv_b, inv_classless


def test_filter_fees_by_branch_restricted(flask_app, db_session, tenant, fee_invoices, restricted_user):
    from modules.fees.models import FeeInvoice

    inv_a, inv_b, inv_classless = fee_invoices
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        ids = {
            i.id
            for i in filter_fees_by_branch(FeeInvoice.query, FeeInvoice.student_id).all()
        }
        assert inv_a.id in ids              # in-branch student
        assert inv_b.id not in ids          # out-of-branch student excluded
        assert inv_classless.id not in ids  # classless student fails closed


def test_filter_fees_by_branch_noop_for_unrestricted(flask_app, db_session, tenant, fee_invoices, unrestricted_user):
    from modules.fees.models import FeeInvoice

    inv_a, inv_b, inv_classless = fee_invoices
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        ids = {
            i.id
            for i in filter_fees_by_branch(FeeInvoice.query, FeeInvoice.student_id).all()
        }
        assert inv_a.id in ids
        assert inv_b.id in ids
        assert inv_classless.id in ids      # strict no-op: classless included too
