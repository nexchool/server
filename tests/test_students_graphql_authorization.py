"""`student(id)` must answer "may you read *this* child", not just "children".

The REST twin (`GET /api/students/<id>`) has always narrowed twice: branch
scope first, then the class ceiling — a holder of `student.read.class` is
served only a child in a class they actually teach. The GraphQL field was
given the same *permission* gate and neither *object* check, so any class
teacher could read any child in the school, and a campus-restricted admin
could read any child in the trust.

Cross-tenant was never affected — the ORM scope handles that, and
`test_another_schools_student_is_not_found` pins it. This is about the
boundaries inside one school.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from graphql_api import GRAPHQL_PATH

ONE = "query One($id: ID!) { student(id: $id) { admissionNumber fullName } }"


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _ask(client, tenant, token, student_id):
    return client.post(
        GRAPHQL_PATH,
        json={"query": ONE, "variables": {"id": student_id}},
        headers={
            "X-Tenant-Subdomain": tenant.subdomain,
            "Authorization": f"Bearer {token}",
        },
    ).get_json()


# ---------------------------------------------------------------------------
# A trust with two campuses, one class and one child in each
# ---------------------------------------------------------------------------

@pytest.fixture
def units(db_session, tenant):
    from modules.school_units.models import SchoolUnit

    made = []
    for label in ("A", "B"):
        unit = SchoolUnit(
            id=_new_id("su-"), tenant_id=tenant.id, name=f"Campus {label}",
            code=f"{label}-{uuid.uuid4().hex[:6]}",
        )
        db_session.add(unit)
        made.append(unit)
    db_session.flush()
    return made


@pytest.fixture
def academic_year(db_session, tenant):
    from modules.academics.academic_year.models import AcademicYear

    year = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name=f"AY-{uuid.uuid4().hex[:6]}",
        start_date=date(2026, 6, 1), end_date=date(2027, 3, 31), is_active=True,
    )
    db_session.add(year)
    db_session.flush()
    return year


@pytest.fixture
def school(db_session, tenant, units, academic_year):
    """Grade 5-A on Campus A and Grade 5-B on Campus B, a child in each."""
    from modules.classes.models import Class
    from modules.people.models import Person
    from modules.students.models import Student

    made = {}
    for label, unit in zip(("A", "B"), units):
        cls = Class(
            id=_new_id("c-"), tenant_id=tenant.id, name="Grade 5", section=label,
            academic_year_id=academic_year.id, school_unit_id=unit.id,
        )
        db_session.add(cls)
        db_session.flush()

        person = Person(
            id=_new_id("p-"), tenant_id=tenant.id, full_name=f"Child of {label}"
        )
        db_session.add(person)
        db_session.flush()
        student = Student(
            id=_new_id("s-"), tenant_id=tenant.id, person_id=person.id,
            admission_number=f"ADM-{label}-{uuid.uuid4().hex[:6]}",
            academic_year_id=academic_year.id, class_id=cls.id,
            student_status="active",
        )
        db_session.add(student)
        db_session.flush()
        made[label] = {"class": cls, "student": student}
    return made


# ---------------------------------------------------------------------------
# Who is asking
# ---------------------------------------------------------------------------

def _account(db_session, tenant, *permission_keys, name, branches=()):
    from modules.auth.models import User
    from modules.auth.services import generate_access_token
    from modules.rbac.models import Permission, Role, RolePermission
    from modules.sub_admins.models import UserSchoolUnit
    from tests.conftest import grant_profile_to

    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=f"u-{suffix}", tenant_id=tenant.id, email=f"{suffix}@test.school",
        password_hash="x" * 60, name=name,
    )
    db_session.add(user)
    db_session.flush()

    role = Role(id=f"r-{suffix}", tenant_id=tenant.id, name=f"Role-{suffix}")
    db_session.add(role)
    db_session.flush()
    for key in permission_keys:
        permission = Permission.query.filter_by(name=key).first()
        if permission is None:
            permission = Permission(id=_new_id("perm-"), name=key)
            db_session.add(permission)
            db_session.flush()
        db_session.add(RolePermission(
            tenant_id=tenant.id, role_id=role.id, permission_id=permission.id
        ))
    for branch in branches:
        db_session.add(UserSchoolUnit(
            id=_new_id("usu-"), tenant_id=tenant.id,
            user_id=user.id, school_unit_id=branch.id,
        ))
    db_session.flush()
    staff = grant_profile_to(user, role.id, employee_number=f"EMP-{suffix}")
    return user, staff, generate_access_token(user)


@pytest.fixture
def class_teacher_of_a(db_session, tenant, school):
    """Teaches Grade 5-A, and only that."""
    from modules.academics.backbone.models import ClassTeacherAssignment
    from modules.teachers.models import Teacher

    user, staff, token = _account(
        db_session, tenant, "student.read.class", name="Class Teacher A"
    )
    teacher = Teacher(id=_new_id("te-"), tenant_id=tenant.id, staff_id=staff.id)
    db_session.add(teacher)
    db_session.flush()
    db_session.add(ClassTeacherAssignment(
        id=_new_id("cta-"), tenant_id=tenant.id,
        class_id=school["A"]["class"].id, teacher_id=teacher.id,
        role="primary", is_active=True, allow_attendance_marking=True,
    ))
    db_session.flush()
    return token


@pytest.fixture
def head_of_campus_a(db_session, tenant, units):
    _u, _s, token = _account(
        db_session, tenant, "student.read.all",
        name="Head of Campus A", branches=(units[0],),
    )
    return token


@pytest.fixture
def trust_admin(db_session, tenant):
    """No UserSchoolUnit rows — every existing admin looks like this."""
    _u, _s, token = _account(db_session, tenant, "student.read.all", name="Trust Admin")
    return token


# ---------------------------------------------------------------------------
# The class ceiling
# ---------------------------------------------------------------------------

def test_a_class_teacher_reads_a_child_they_teach(
    client, tenant, school, class_teacher_of_a
):
    body = _ask(client, tenant, class_teacher_of_a, school["A"]["student"].id)

    assert "errors" not in body, body
    assert body["data"]["student"]["admissionNumber"] == (
        school["A"]["student"].admission_number
    )


def test_a_class_teacher_cannot_read_a_child_from_another_class(
    client, tenant, school, class_teacher_of_a
):
    """The live defect: `student.read.class` was treated as "any child"."""
    body = _ask(client, tenant, class_teacher_of_a, school["B"]["student"].id)

    assert body["data"]["student"] is None, (
        "a teacher must not read a child they do not teach"
    )


# ---------------------------------------------------------------------------
# The campus ceiling
# ---------------------------------------------------------------------------

def test_a_campus_head_reads_a_child_on_their_own_campus(
    client, tenant, school, head_of_campus_a
):
    body = _ask(client, tenant, head_of_campus_a, school["A"]["student"].id)

    assert "errors" not in body, body
    assert body["data"]["student"] is not None


def test_a_campus_head_cannot_read_a_child_on_another_campus(
    client, tenant, school, head_of_campus_a
):
    body = _ask(client, tenant, head_of_campus_a, school["B"]["student"].id)

    assert body.get("errors"), "a campus-restricted admin must be refused"
    assert body["data"]["student"] is None


# ---------------------------------------------------------------------------
# The unrestricted admin is untouched
# ---------------------------------------------------------------------------

def test_an_unrestricted_admin_reads_any_child(client, tenant, school, trust_admin):
    """Regression guard: the narrowing is a no-op without a restriction."""
    for label in ("A", "B"):
        body = _ask(client, tenant, trust_admin, school[label]["student"].id)
        assert "errors" not in body, body
        assert body["data"]["student"] is not None
