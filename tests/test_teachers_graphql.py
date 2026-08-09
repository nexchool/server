"""Teachers over GraphQL — the Academic domain's view of employed staff.

What is pinned here beyond the feature:

A teacher's name, contact, employee number and status do not live on the
teacher row. They come from Person and from the employment (ADR-001/ADR-005),
and `status` is derived from whether that employment is open. The tests read
those through the field rather than trusting the column.

The list carries its own filter catalogues. A filter offering only the
departments already in use cannot be used to find the ones that are missing.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from graphql_api import GRAPHQL_PATH

TEACHERS = """
query T(
  $first: Int!, $offset: Int, $orderBy: TeacherOrder!,
  $direction: TeacherOrderDirection!, $where: TeacherFilter
) {
  teachers(
    first: $first, offset: $offset, orderBy: $orderBy,
    direction: $direction, where: $where
  ) {
    totalCount
    hasNextPage
    departments { id name }
    designations
    nodes {
      id name employeeId email phone designation department departmentId
      dateOfJoining status qualification specialization experienceYears
    }
  }
}
"""

DETAIL = """
query D($id: ID!) {
  teacher(id: $id) {
    id name employeeId status designation
    subjects { id name code }
  }
}
"""


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def department(db_session, tenant):
    from modules.departments.models import Department

    row = Department(
        id=_new_id("dept-"), tenant_id=tenant.id, name="Primary",
        type="academic_division", status="active",
    )
    db_session.add(row)
    db_session.flush()
    return row


def _make_teacher(db_session, tenant, *, name, employee_number, department=None,
                  designation="Teacher", joined=date(2024, 6, 1), employed=True):
    """A teacher the way the domain builds one: Person → Staff → Teacher."""
    from modules.people.employment import Staff, StaffEmploymentPeriod
    from modules.people.models import Person
    from modules.teachers.models import Teacher

    person = Person(id=_new_id("p-"), tenant_id=tenant.id, full_name=name,
                    phone_number="9800000000")
    db_session.add(person)
    db_session.flush()

    staff = Staff(
        id=_new_id("s-"), tenant_id=tenant.id, person=person,
        employee_number=employee_number, designation=designation,
        department_id=department.id if department else None,
        employment_status="working" if employed else "left",
    )
    db_session.add(staff)
    db_session.flush()
    db_session.add(
        StaffEmploymentPeriod(
            id=_new_id("per-"), tenant_id=tenant.id, staff=staff,
            joined_on=joined,
            left_on=None if employed else date(2025, 3, 31),
            end_reason=None if employed else "left",
        )
    )
    teacher = Teacher(
        id=_new_id("t-"), tenant_id=tenant.id, staff=staff,
        qualification="B.Ed", specialization="Mathematics", experience_years=5,
    )
    db_session.add(teacher)
    db_session.flush()
    return teacher


@pytest.fixture
def staffroom(db_session, tenant, department):
    working = _make_teacher(
        db_session, tenant, name="Rekha Solanki", employee_number="EMP001",
        department=department, joined=date(2020, 6, 1),
    )
    departed = _make_teacher(
        db_session, tenant, name="Sanjay Vyas", employee_number="EMP002",
        department=department, designation="Senior Teacher",
        joined=date(2018, 6, 1), employed=False,
    )
    return working, departed


def _staff_with(db_session, tenant, *permission_keys):
    from modules.auth.models import User
    from modules.auth.services import generate_access_token
    from modules.rbac.models import Permission, Role, RolePermission
    from tests.conftest import grant_profile_to

    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=f"u-{suffix}", tenant_id=tenant.id, email=f"{suffix}@test.school",
        password_hash="x" * 60, name="Office",
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
        db_session.add(
            RolePermission(
                tenant_id=tenant.id, role_id=role.id, permission_id=permission.id
            )
        )
    db_session.flush()
    grant_profile_to(user, role.id, employee_number=f"ADM-{suffix}")
    return user, generate_access_token(user)


def _ask(client, tenant, token, query, **variables):
    return client.post(
        GRAPHQL_PATH,
        json={"query": query, "variables": variables},
        headers={
            "X-Tenant-Subdomain": tenant.subdomain,
            "Authorization": f"Bearer {token}",
        },
    ).get_json()


def _codes(body):
    return [error["extensions"].get("code") for error in body.get("errors", [])]


def _list(client, tenant, token, **overrides):
    variables = {
        "first": 25, "offset": None, "orderBy": "EMPLOYEE_ID",
        "direction": "ASC", "where": None,
    }
    variables.update(overrides)
    return _ask(client, tenant, token, TEACHERS, **variables)


# ---------------------------------------------------------------------------
# Who the school employs
# ---------------------------------------------------------------------------

def test_the_teachers_a_school_employs(client, db_session, tenant, staffroom):
    _user, token = _staff_with(db_session, tenant, "teacher.read")

    body = _list(client, tenant, token)

    assert "errors" not in body, body
    page = body["data"]["teachers"]
    assert page["totalCount"] == 2
    assert [n["employeeId"] for n in page["nodes"]] == ["EMP001", "EMP002"]


def test_a_teachers_name_comes_from_their_person(
    client, db_session, tenant, staffroom
):
    """`teachers` has no name column; ADR-001 put it on the Person."""
    _user, token = _staff_with(db_session, tenant, "teacher.read")

    nodes = _list(client, tenant, token)["data"]["teachers"]["nodes"]

    assert {n["name"] for n in nodes} == {"Rekha Solanki", "Sanjay Vyas"}


def test_the_employee_number_and_joining_date_come_from_the_employment(
    client, db_session, tenant, staffroom
):
    _user, token = _staff_with(db_session, tenant, "teacher.read")

    first = _list(client, tenant, token)["data"]["teachers"]["nodes"][0]

    assert first["employeeId"] == "EMP001"
    assert first["dateOfJoining"] == "2020-06-01"


def test_status_is_derived_from_whether_the_employment_is_open(
    client, db_session, tenant, staffroom
):
    """A teacher who has left reads as inactive; nothing sets a status column
    on the teacher."""
    _user, token = _staff_with(db_session, tenant, "teacher.read")

    by_number = {
        n["employeeId"]: n
        for n in _list(client, tenant, token)["data"]["teachers"]["nodes"]
    }

    assert by_number["EMP001"]["status"] == "active"
    assert by_number["EMP002"]["status"] == "inactive"


def test_filtering_to_who_is_still_here(client, db_session, tenant, staffroom):
    _user, token = _staff_with(db_session, tenant, "teacher.read")

    body = _list(client, tenant, token, where={"status": "active"})

    page = body["data"]["teachers"]
    assert page["totalCount"] == 1
    assert page["nodes"][0]["employeeId"] == "EMP001"


def test_searching_by_name(client, db_session, tenant, staffroom):
    _user, token = _staff_with(db_session, tenant, "teacher.read")

    body = _list(client, tenant, token, where={"search": "rekha", "searchField": "NAME"})

    assert [n["name"] for n in body["data"]["teachers"]["nodes"]] == ["Rekha Solanki"]


def test_the_filter_catalogues_ride_with_the_page(
    client, db_session, tenant, staffroom, department
):
    """A filter that only offers what is already chosen cannot find what is
    missing, so the catalogue is the school's, not the page's."""
    _user, token = _staff_with(db_session, tenant, "teacher.read")

    page = _list(client, tenant, token)["data"]["teachers"]

    assert department.id in [d["id"] for d in page["departments"]]
    assert "Senior Teacher" in page["designations"]


def test_a_page_says_whether_another_follows(client, db_session, tenant, staffroom):
    _user, token = _staff_with(db_session, tenant, "teacher.read")

    first = _list(client, tenant, token, first=1)
    assert first["data"]["teachers"]["hasNextPage"] is True

    second = _list(client, tenant, token, first=1, offset=1)
    assert second["data"]["teachers"]["hasNextPage"] is False
    assert (
        first["data"]["teachers"]["nodes"][0]["id"]
        != second["data"]["teachers"]["nodes"][0]["id"]
    )


def test_an_offset_that_is_not_a_page_boundary_is_refused(
    client, db_session, tenant, staffroom
):
    """The service pages by page number, so a boundary is the only offset it
    can express — rounding to the containing page would answer a question
    nobody asked."""
    _user, token = _staff_with(db_session, tenant, "teacher.read")

    body = _list(client, tenant, token, first=2, offset=1)

    assert "VALIDATION_ERROR" in _codes(body)


def test_a_negative_offset_is_refused(client, db_session, tenant, staffroom):
    _user, token = _staff_with(db_session, tenant, "teacher.read")

    assert "VALIDATION_ERROR" in _codes(_list(client, tenant, token, offset=-1))


def test_sorting_by_when_they_joined(client, db_session, tenant, staffroom):
    _user, token = _staff_with(db_session, tenant, "teacher.read")

    body = _list(client, tenant, token, orderBy="DATE_OF_JOINING", direction="ASC")

    dates = [n["dateOfJoining"] for n in body["data"]["teachers"]["nodes"]]
    assert dates == sorted(dates)


# ---------------------------------------------------------------------------
# One teacher
# ---------------------------------------------------------------------------

def test_one_teacher_with_what_they_teach(client, db_session, tenant, staffroom):
    working, _departed = staffroom
    _user, token = _staff_with(db_session, tenant, "teacher.read")

    body = _ask(client, tenant, token, DETAIL, id=working.id)

    assert "errors" not in body, body
    detail = body["data"]["teacher"]
    assert detail["name"] == "Rekha Solanki"
    assert detail["employeeId"] == "EMP001"
    assert isinstance(detail["subjects"], list)


def test_a_teacher_nobody_employs_is_not_found(client, db_session, tenant, staffroom):
    _user, token = _staff_with(db_session, tenant, "teacher.read")

    body = _ask(client, tenant, token, DETAIL, id=_new_id("t-"))

    assert "errors" not in body, body
    assert body["data"]["teacher"] is None


# ---------------------------------------------------------------------------
# Who may read them
# ---------------------------------------------------------------------------

def test_reading_teachers_needs_the_teacher_authority(
    client, db_session, tenant, staffroom
):
    _user, token = _staff_with(db_session, tenant, "student.read.all")

    assert "FORBIDDEN" in _codes(_list(client, tenant, token))


def test_managing_teachers_carries_reading_them(client, db_session, tenant, staffroom):
    _user, token = _staff_with(db_session, tenant, "teacher.manage")

    assert "errors" not in _list(client, tenant, token)


def test_a_stranger_reads_nothing(client, tenant, staffroom):
    body = _list(client, tenant, None)

    assert "UNAUTHENTICATED" in _codes(body)
