"""The Students read surface — the pattern every later module copies.

Three properties are pinned here because they are the pattern, not the
feature: paging that walks by key rather than counting past rows, a class
fetched once for a whole page rather than once per child, and a total that
is only counted when somebody asks for it.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from flask import g
from sqlalchemy import event

from core.database import db
from graphql_api import GRAPHQL_PATH

PAGE = """
query Page($first: Int!, $after: String) {
  students(first: $first, after: $after) {
    edges { cursor node { id admissionNumber fullName } }
    pageInfo { hasNextPage endCursor }
  }
}
"""

PAGE_WITH_CLASS = """
query { students(first: 25) { edges { node { admissionNumber currentClass { id section } } } } }
"""

WITH_TOTAL = "query { students(first: 2) { totalCount edges { node { id } } } }"
WITHOUT_TOTAL = "query { students(first: 2) { edges { node { id } } } }"


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _headers(tenant, token):
    return {
        "X-Tenant-Subdomain": tenant.subdomain,
        "Authorization": f"Bearer {token}",
    }


def _errors(response):
    body = response.get_json()
    return [e["extensions"].get("code") for e in body.get("errors", [])]


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
def school(db_session, tenant, academic_year):
    """Thirty children spread over three classes."""
    from modules.classes.models import Class
    from modules.people.models import Person
    from modules.students.models import Student

    classes = []
    for label in ("A", "B", "C"):
        cls = Class(
            id=_new_id("c-"), tenant_id=tenant.id, name="Grade 5", section=label,
            academic_year_id=academic_year.id,
        )
        db_session.add(cls)
        classes.append(cls)
    db_session.flush()

    students = []
    for index in range(30):
        person = Person(
            id=_new_id("p-"), tenant_id=tenant.id, full_name=f"Child {index:02d}"
        )
        db_session.add(person)
        db_session.flush()
        student = Student(
            id=_new_id("s-"), tenant_id=tenant.id, person_id=person.id,
            admission_number=f"ADM-{index:04d}",
            academic_year_id=academic_year.id,
            class_id=classes[index % 3].id,
            student_status="active",
        )
        db_session.add(student)
        students.append(student)
    db_session.flush()
    return students


@pytest.fixture
def reader(db_session, tenant):
    """Somebody employed here who may read the whole school."""
    from modules.auth.models import User
    from modules.auth.services import generate_access_token
    from modules.rbac.models import Permission, Role, RolePermission
    from tests.conftest import employ_for, grant_profile_to

    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=f"u-{suffix}", tenant_id=tenant.id, email=f"{suffix}@test.school",
        password_hash="x" * 60, name="Office Admin",
    )
    db_session.add(user)
    db_session.flush()
    employ_for(user, employee_number=f"EMP-{suffix}")

    role = Role(id=f"r-{suffix}", tenant_id=tenant.id, name=f"Office-{suffix}")
    db_session.add(role)
    db_session.flush()
    permission = Permission.query.filter_by(name="student.read.all").first()
    if permission is None:
        permission = Permission(id=f"perm-{suffix}", name="student.read.all")
        db_session.add(permission)
        db_session.flush()
    db_session.add(
        RolePermission(tenant_id=tenant.id, role_id=role.id, permission_id=permission.id)
    )
    db_session.flush()
    grant_profile_to(user, role.id)

    return user, generate_access_token(user)


def _ask(client, tenant, token, query, **variables):
    return client.post(
        GRAPHQL_PATH,
        json={"query": query, "variables": variables or {}},
        headers=_headers(tenant, token),
    )


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------

def test_reading_students_requires_signing_in(client, tenant, school):
    response = client.post(
        GRAPHQL_PATH,
        json={"query": PAGE, "variables": {"first": 5}},
        headers={"X-Tenant-Subdomain": tenant.subdomain},
    )
    assert "UNAUTHENTICATED" in _errors(response)


def test_reading_students_requires_the_authority(client, tenant, db_session, school):
    """Signed in is not enough — the field states the action it performs."""
    from modules.auth.models import User
    from modules.auth.services import generate_access_token
    from tests.conftest import employ_for

    suffix = uuid.uuid4().hex[:8]
    nobody = User(
        id=f"u-{suffix}", tenant_id=tenant.id, email=f"{suffix}@test.school",
        password_hash="x" * 60, name="Visitor",
    )
    db_session.add(nobody)
    db_session.flush()
    employ_for(nobody, employee_number=f"EMP-{suffix}")

    response = _ask(client, tenant, generate_access_token(nobody), PAGE, first=5)
    assert "FORBIDDEN" in _errors(response)


# ---------------------------------------------------------------------------
# Paging walks, it does not count past rows
# ---------------------------------------------------------------------------

def test_a_page_says_whether_there_is_another(client, tenant, school, reader):
    _user, token = reader

    response = _ask(client, tenant, token, PAGE, first=10)
    body = response.get_json()
    assert "errors" not in body, body

    page = body["data"]["students"]
    assert len(page["edges"]) == 10
    assert page["pageInfo"]["hasNextPage"] is True
    assert page["pageInfo"]["endCursor"]


def test_following_the_cursor_reads_every_child_exactly_once(
    client, tenant, school, reader
):
    """The property offset paging cannot promise while the school admits."""
    _user, token = reader

    seen = []
    cursor = None
    for _ in range(10):
        body = _ask(client, tenant, token, PAGE, first=7, after=cursor).get_json()
        page = body["data"]["students"]
        seen.extend(edge["node"]["admissionNumber"] for edge in page["edges"])
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]

    assert len(seen) == 30
    assert len(set(seen)) == 30, "no child may appear on two pages"
    assert seen == sorted(seen), "order is the admission number, stably"


def test_the_last_page_says_so(client, tenant, school, reader):
    _user, token = reader

    body = _ask(client, tenant, token, PAGE, first=100).get_json()
    page = body["data"]["students"]
    assert len(page["edges"]) == 30
    assert page["pageInfo"]["hasNextPage"] is False


def test_a_page_size_cannot_be_made_unbounded(client, tenant, school, reader):
    """A client asking for everything must not be able to have it."""
    from modules.students.services import students_page

    rows, _more = students_page(first=100000)
    assert len(rows) <= 100


# ---------------------------------------------------------------------------
# A page costs the same whatever its size
# ---------------------------------------------------------------------------

def test_the_class_is_fetched_once_for_the_whole_page(
    client, tenant, school, reader, flask_app
):
    """Without the loader this is one query per child — the N+1 that a list
    of fifteen thousand turns into an outage."""
    _user, token = reader

    statements = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        if "FROM classes" in statement:
            statements.append(statement)

    event.listen(db.engine, "before_cursor_execute", _record)
    try:
        body = _ask(client, tenant, token, PAGE_WITH_CLASS).get_json()
    finally:
        event.remove(db.engine, "before_cursor_execute", _record)

    assert "errors" not in body, body
    edges = body["data"]["students"]["edges"]
    assert len(edges) == 25
    assert {edge["node"]["currentClass"]["section"] for edge in edges} == {"A", "B", "C"}
    assert len(statements) <= 1, (
        f"the page fetched classes {len(statements)} times; the loader should "
        "batch them into one"
    )


# ---------------------------------------------------------------------------
# You pay for what you ask for
# ---------------------------------------------------------------------------

def test_a_total_is_counted_only_when_asked_for(client, tenant, school, reader):
    _user, token = reader

    counted = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        if "count(" in statement.lower():
            counted.append(statement)

    event.listen(db.engine, "before_cursor_execute", _record)
    try:
        without = _ask(client, tenant, token, WITHOUT_TOTAL).get_json()
        counts_without = len(counted)
        with_total = _ask(client, tenant, token, WITH_TOTAL).get_json()
        counts_with = len(counted)
    finally:
        event.remove(db.engine, "before_cursor_execute", _record)

    assert "errors" not in without, without
    assert with_total["data"]["students"]["totalCount"] == 30
    assert counts_with > counts_without, "asking for the total should do the counting"


# ---------------------------------------------------------------------------
# One student
# ---------------------------------------------------------------------------

def test_one_student_can_be_read_by_id(client, tenant, school, reader):
    _user, token = reader
    wanted = school[3]

    body = _ask(
        client, tenant, token,
        "query One($id: ID!) { student(id: $id) { admissionNumber fullName } }",
        id=wanted.id,
    ).get_json()

    assert "errors" not in body, body
    assert body["data"]["student"]["admissionNumber"] == wanted.admission_number


def test_another_schools_student_is_not_found(client, tenant, db_session, school, reader):
    """The ORM scope restricts the read; the field simply sees nothing."""
    from core.models import Tenant
    from modules.people.models import Person
    from modules.students.models import Student

    other = Tenant(
        id=_new_id("t-"), name="Other School",
        subdomain=f"other-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(other)
    db_session.flush()
    person = Person(id=_new_id("p-"), tenant_id=other.id, full_name="Their Child")
    db_session.add(person)
    db_session.flush()
    theirs = Student(
        id=_new_id("s-"), tenant_id=other.id, person_id=person.id,
        admission_number="ADM-9999",
    )
    db_session.add(theirs)
    db_session.flush()

    _user, token = reader
    body = _ask(
        client, tenant, token,
        "query One($id: ID!) { student(id: $id) { admissionNumber } }",
        id=theirs.id,
    ).get_json()

    assert body["data"]["student"] is None
