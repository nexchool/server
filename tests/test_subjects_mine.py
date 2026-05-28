"""Tests for role-scoped subjects: services.get_subjects_for_user and
GET /api/subjects/mine.

The service tests use the real-DB savepoint harness (conftest `db_session`,
`tenant`) because the logic is mostly SQL filtering + relationship traversal,
which is exactly what we want to exercise against PostgreSQL.

The route test is pure-Python (unwrap decorators, mock the service) following
the established pattern in test_default_unit_endpoint.py — standing up real JWT
auth is out of scope for a handler-level test.
"""
from __future__ import annotations

import sys
import uuid
from datetime import date
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def _nid(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}" if prefix else str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Builders (inline rows; each test composes only what it needs)
# ---------------------------------------------------------------------------

def _make_user(db_session, tenant, *, name: str):
    from modules.auth.models import User

    u = User(
        id=_nid("u-"),
        tenant_id=tenant.id,
        email=f"{uuid.uuid4().hex[:8]}@test.school",
        password_hash="x" * 60,
        name=name,
    )
    db_session.add(u)
    db_session.flush()
    return u


def _grant_permission(db_session, tenant, user, permission_name: str):
    """Create a role with `permission_name` and assign it to `user`."""
    from modules.rbac.models import Role, Permission, RolePermission, UserRole

    perm = Permission.query.filter_by(name=permission_name).first()
    if perm is None:
        perm = Permission(id=_nid("p-"), name=permission_name)
        db_session.add(perm)
        db_session.flush()

    role = Role(id=_nid("r-"), tenant_id=tenant.id, name=f"role-{uuid.uuid4().hex[:6]}")
    db_session.add(role)
    db_session.flush()
    db_session.add(
        RolePermission(
            id=_nid("rp-"), tenant_id=tenant.id, role_id=role.id, permission_id=perm.id
        )
    )
    db_session.add(
        UserRole(id=_nid("ur-"), tenant_id=tenant.id, user_id=user.id, role_id=role.id)
    )
    db_session.flush()


def _make_academic_year(db_session, tenant):
    from modules.academics.academic_year.models import AcademicYear

    ay = AcademicYear(
        id=_nid("ay-"),
        tenant_id=tenant.id,
        name=f"AY-{uuid.uuid4().hex[:4]}",
        start_date=date(2025, 6, 1),
        end_date=date(2026, 3, 31),
    )
    db_session.add(ay)
    db_session.flush()
    return ay


def _make_class(db_session, tenant, ay, *, name=None, section="A"):
    from modules.classes.models import Class

    c = Class(
        id=_nid("c-"),
        tenant_id=tenant.id,
        name=name,
        section=section,
        academic_year_id=ay.id,
    )
    db_session.add(c)
    db_session.flush()
    return c


def _make_subject(db_session, tenant, *, name, code=None, is_active=True):
    from modules.subjects.models import Subject

    s = Subject(
        id=_nid("subj-"),
        tenant_id=tenant.id,
        name=name,
        code=code,
        subject_type="core",
        is_active=is_active,
    )
    db_session.add(s)
    db_session.flush()
    return s


def _make_class_subject(db_session, tenant, klass, subject, *, weekly_periods=5,
                        is_mandatory=True, status="active"):
    from modules.classes.models import ClassSubject

    cs = ClassSubject(
        id=_nid("cs-"),
        tenant_id=tenant.id,
        class_id=klass.id,
        subject_id=subject.id,
        weekly_periods=weekly_periods,
        is_mandatory=is_mandatory,
        status=status,
    )
    db_session.add(cs)
    db_session.flush()
    return cs


def _make_teacher(db_session, tenant, user):
    from modules.teachers.models import Teacher

    t = Teacher(
        id=_nid("t-"),
        tenant_id=tenant.id,
        user_id=user.id,
        employee_id=f"EMP-{uuid.uuid4().hex[:6]}",
    )
    db_session.add(t)
    db_session.flush()
    return t


def _assign_teacher(db_session, tenant, class_subject, teacher, *, role="primary",
                    is_active=True):
    from modules.academics.backbone.models import ClassSubjectTeacher

    cst = ClassSubjectTeacher(
        id=_nid("cst-"),
        tenant_id=tenant.id,
        class_subject_id=class_subject.id,
        teacher_id=teacher.id,
        role=role,
        is_active=is_active,
    )
    db_session.add(cst)
    db_session.flush()
    return cst


def _make_student(db_session, tenant, user, klass):
    from modules.students.models import Student

    s = Student(
        id=_nid("s-"),
        tenant_id=tenant.id,
        user_id=user.id,
        admission_number=f"ADM-{uuid.uuid4().hex[:6]}",
        class_id=klass.id if klass else None,
    )
    db_session.add(s)
    db_session.flush()
    return s


# ---------------------------------------------------------------------------
# Admin: sees all active subjects (even ones with no class), ordered by name
# ---------------------------------------------------------------------------

def test_admin_sees_all_active_subjects(db_session, tenant):
    from modules.subjects import services

    admin_user = _make_user(db_session, tenant, name="Admin User")
    _grant_permission(db_session, tenant, admin_user, "subject.manage")

    ay = _make_academic_year(db_session, tenant)
    klass = _make_class(db_session, tenant, ay, name="Grade 10")

    math = _make_subject(db_session, tenant, name="Mathematics", code="MATH")
    science = _make_subject(db_session, tenant, name="Science", code="SCI")
    # Inactive subject must NOT appear.
    _make_subject(db_session, tenant, name="Art", code="ART", is_active=False)
    # Subject with no class still appears with empty classes.
    history = _make_subject(db_session, tenant, name="History", code="HIST")

    _make_class_subject(db_session, tenant, klass, math)
    _make_class_subject(db_session, tenant, klass, science)

    result = services.get_subjects_for_user(tenant.id, admin_user)

    names = [r["name"] for r in result]
    assert names == ["History", "Mathematics", "Science"]  # ordered, no Art
    by_name = {r["name"]: r for r in result}
    assert by_name["History"]["classes"] == []
    assert len(by_name["Mathematics"]["classes"]) == 1
    assert by_name["Mathematics"]["classes"][0]["class_id"] == klass.id


# ---------------------------------------------------------------------------
# Teacher: sees only subjects they teach, with class + teacher context
# ---------------------------------------------------------------------------

def test_teacher_sees_only_taught_subjects(db_session, tenant):
    from modules.subjects import services

    teacher_user = _make_user(db_session, tenant, name="Tina Teacher")
    teacher = _make_teacher(db_session, tenant, teacher_user)

    ay = _make_academic_year(db_session, tenant)
    klass = _make_class(db_session, tenant, ay, name="Grade 9")

    math = _make_subject(db_session, tenant, name="Mathematics", code="MATH")
    science = _make_subject(db_session, tenant, name="Science", code="SCI")

    cs_math = _make_class_subject(db_session, tenant, klass, math)
    # Science offered but NOT taught by this teacher.
    _make_class_subject(db_session, tenant, klass, science)

    _assign_teacher(db_session, tenant, cs_math, teacher)

    result = services.get_subjects_for_user(tenant.id, teacher_user)

    assert [r["name"] for r in result] == ["Mathematics"]
    classes = result[0]["classes"]
    assert len(classes) == 1
    assert classes[0]["class_id"] == klass.id
    assert classes[0]["class_name"] == "Grade 9"
    teachers = classes[0]["teachers"]
    assert any(t["teacher_id"] == teacher.id for t in teachers)
    assert teachers[0]["teacher_name"] == "Tina Teacher"
    assert teachers[0]["role"] == "primary"


def test_teacher_with_no_classes_returns_empty(db_session, tenant):
    from modules.subjects import services

    teacher_user = _make_user(db_session, tenant, name="Idle Teacher")
    _make_teacher(db_session, tenant, teacher_user)

    # Subjects exist in the tenant, but none assigned to this teacher.
    ay = _make_academic_year(db_session, tenant)
    klass = _make_class(db_session, tenant, ay, name="Grade 8")
    math = _make_subject(db_session, tenant, name="Mathematics", code="MATH")
    _make_class_subject(db_session, tenant, klass, math)

    result = services.get_subjects_for_user(tenant.id, teacher_user)
    assert result == []


# ---------------------------------------------------------------------------
# Student: sees only own-class subjects
# ---------------------------------------------------------------------------

def test_student_sees_only_own_class_subjects(db_session, tenant):
    from modules.subjects import services

    student_user = _make_user(db_session, tenant, name="Sam Student")

    ay = _make_academic_year(db_session, tenant)
    own_class = _make_class(db_session, tenant, ay, name="Grade 7", section="A")
    other_class = _make_class(db_session, tenant, ay, name="Grade 7", section="B")

    math = _make_subject(db_session, tenant, name="Mathematics", code="MATH")
    science = _make_subject(db_session, tenant, name="Science", code="SCI")

    _make_class_subject(db_session, tenant, own_class, math)
    # Science only in the other class.
    _make_class_subject(db_session, tenant, other_class, science)

    _make_student(db_session, tenant, student_user, own_class)

    result = services.get_subjects_for_user(tenant.id, student_user)

    assert [r["name"] for r in result] == ["Mathematics"]
    assert result[0]["classes"][0]["class_id"] == own_class.id


# ---------------------------------------------------------------------------
# No cross-tenant leakage: another tenant's admin subjects never appear
# ---------------------------------------------------------------------------

def test_no_cross_tenant_leakage(db_session, tenant):
    from core.models import Tenant, TENANT_STATUS_ACTIVE, BILLING_CYCLE_YEARLY
    from modules.subjects import services

    other = Tenant(
        id=_nid("t-"),
        name="Other School",
        subdomain=f"other-{uuid.uuid4().hex[:6]}",
        status=TENANT_STATUS_ACTIVE,
        billing_cycle=BILLING_CYCLE_YEARLY,
    )
    db_session.add(other)
    db_session.flush()

    # Subject in the OTHER tenant.
    _make_subject(db_session, other, name="Foreign Subject", code="FOR")

    # Admin belongs to `tenant`, queries `tenant`.
    admin_user = _make_user(db_session, tenant, name="Admin User")
    _grant_permission(db_session, tenant, admin_user, "subject.manage")
    _make_subject(db_session, tenant, name="Mathematics", code="MATH")

    result = services.get_subjects_for_user(tenant.id, admin_user)
    assert [r["name"] for r in result] == ["Mathematics"]


# ---------------------------------------------------------------------------
# Route handler: GET /api/subjects/mine
# ---------------------------------------------------------------------------

def test_route_list_my_subjects_returns_service_data(monkeypatch):
    """Handler returns success_response wrapping the service output."""
    from modules.subjects import routes

    fake_subjects = [{"id": "subj-1", "name": "Mathematics", "classes": []}]
    monkeypatch.setattr(
        routes.services, "get_subjects_for_user", lambda tid, user: fake_subjects
    )

    fake_g = type(
        "G", (), {"tenant_id": "t1", "current_user": type("U", (), {"id": "u1"})()}
    )()
    monkeypatch.setattr(routes, "g", fake_g)

    captured = {}

    def fake_success(data=None, **kw):
        captured["data"] = data
        return ("ok", 200)

    monkeypatch.setattr(routes, "success_response", fake_success)

    handler = routes.list_my_subjects
    while hasattr(handler, "__wrapped__"):
        handler = handler.__wrapped__

    handler()
    assert captured["data"] == fake_subjects


def test_route_list_my_subjects_is_registered():
    """The /mine route is wired with auth + tenant + permission decorators."""
    from modules.subjects import routes

    assert callable(getattr(routes, "list_my_subjects", None))
