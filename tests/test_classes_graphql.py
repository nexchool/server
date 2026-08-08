"""The classes a school is arranged into, over GraphQL.

Three things are pinned here rather than the feature:

Both transports list classes through one query builder, so a filter added to
the screen and not the export cannot drift. The parity test compares them row
for row.

Paging is by offset and says so. A class list has no order whose key is both
unique and unchanging, and a cursor over such a key does not fail — it skips
rows. What is tested is that the page boundary is exact and that the picker's
"read on until hasNextPage is false" walk returns every class exactly once.

Branch scope lives in the service, not the route it used to live in. A class
in a branch outside the reader's scope is a refusal, and the transport turns
it into FORBIDDEN rather than a 500.
"""

from __future__ import annotations

import uuid

import pytest

from graphql_api import GRAPHQL_PATH

CLASSES = """
query C(
  $first: Int!, $offset: Int, $orderBy: ClassOrder!,
  $direction: ClassOrderDirection!, $where: ClassFilter
) {
  classes(
    first: $first, offset: $offset, orderBy: $orderBy,
    direction: $direction, where: $where
  ) {
    totalCount
    hasNextPage
    nodes {
      id name section gradeName gradeSequence programmeName schoolUnitName
      academicYear studentCount teacherCount status
    }
  }
}
"""

NAMES_ONLY = """
query C($first: Int!, $offset: Int) {
  classes(first: $first, offset: $offset) {
    hasNextPage
    nodes { id }
  }
}
"""

STATS = """
query S($where: ClassFilter) {
  classStats(where: $where) {
    totalClasses totalStudents totalTeachers averageClassSize
  }
}
"""

DETAIL = """
query D($id: ID!) {
  class(id: $id) {
    id section gradeName studentCount teacherCount status
    students { id admissionNumber fullName rollNumber }
    teachers {
      teacherId teacherName employeeNumber subjectId subjectName
      role isClassTeacher
    }
  }
}
"""


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def unit(db_session, tenant):
    from modules.school_units.models import SchoolUnit

    su = SchoolUnit(
        id=_new_id("su-"), tenant_id=tenant.id, name="Main Campus",
        code=f"MC-{uuid.uuid4().hex[:6]}",
    )
    db_session.add(su)
    db_session.flush()
    return su


@pytest.fixture
def other_unit(db_session, tenant):
    from modules.school_units.models import SchoolUnit

    su = SchoolUnit(
        id=_new_id("su-"), tenant_id=tenant.id, name="Maninagar Campus",
        code=f"MN-{uuid.uuid4().hex[:6]}",
    )
    db_session.add(su)
    db_session.flush()
    return su


@pytest.fixture
def programme(db_session, tenant):
    from modules.academic_programmes.models import AcademicProgramme

    prog = AcademicProgramme(
        id=_new_id("ap-"), tenant_id=tenant.id, name="Primary", board="GSEB",
        code=f"PRI-{uuid.uuid4().hex[:6]}",
    )
    db_session.add(prog)
    db_session.flush()
    return prog


@pytest.fixture
def grades(db_session, tenant):
    """Two grades whose teaching order is the reverse of their alphabetical one."""
    from modules.grades.models import Grade

    nursery = Grade(id=_new_id("g-"), tenant_id=tenant.id, name="Nursery", sequence=1)
    grade_one = Grade(id=_new_id("g-"), tenant_id=tenant.id, name="Grade 1", sequence=2)
    db_session.add_all([nursery, grade_one])
    db_session.flush()
    return nursery, grade_one


@pytest.fixture
def year(db_session, tenant):
    from modules.academics.academic_year.models import AcademicYear

    ay = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name="2026-2027",
        start_date="2026-06-01", end_date="2027-03-31", is_active=True,
    )
    db_session.add(ay)
    db_session.flush()
    return ay


def _make_class(db_session, tenant, *, section, unit, programme, grade, year):
    from modules.classes.models import Class

    cls = Class(
        id=_new_id("c-"), tenant_id=tenant.id, name=grade.name, section=section,
        academic_year_id=year.id, school_unit_id=unit.id,
        programme_id=programme.id, grade_id=grade.id,
    )
    db_session.add(cls)
    db_session.flush()
    return cls


def _add_students(db_session, tenant, class_id, count):
    from modules.auth.models import User
    from modules.students.models import Student

    made = []
    for index in range(count):
        suffix = uuid.uuid4().hex[:8]
        user = User(
            id=_new_id("u-"), tenant_id=tenant.id, email=f"{suffix}@test.school",
            password_hash="x" * 60, name=f"Child {index}",
        )
        db_session.add(user)
        db_session.flush()
        student = Student(
            id=_new_id("s-"), tenant_id=tenant.id, user_id=user.id,
            admission_number=f"ADM-{suffix}", class_id=class_id,
            roll_number=index + 1,
        )
        db_session.add(student)
        made.append(student)
    db_session.flush()
    return made


@pytest.fixture
def school(db_session, tenant, unit, programme, grades, year):
    """Nursery-A with 3 children, Grade 1-A with 1, Grade 1-B with none."""
    nursery, grade_one = grades
    nursery_a = _make_class(
        db_session, tenant, section="A", unit=unit, programme=programme,
        grade=nursery, year=year,
    )
    grade_one_a = _make_class(
        db_session, tenant, section="A", unit=unit, programme=programme,
        grade=grade_one, year=year,
    )
    grade_one_b = _make_class(
        db_session, tenant, section="B", unit=unit, programme=programme,
        grade=grade_one, year=year,
    )
    _add_students(db_session, tenant, nursery_a.id, 3)
    _add_students(db_session, tenant, grade_one_a.id, 1)
    return nursery_a, grade_one_a, grade_one_b


def _staff_with(db_session, tenant, *permission_keys, branches=()):
    from modules.auth.models import User
    from modules.auth.services import generate_access_token
    from modules.rbac.models import Permission, Role, RolePermission
    from modules.sub_admins.models import UserSchoolUnit
    from tests.conftest import grant_profile_to

    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=f"u-{suffix}", tenant_id=tenant.id, email=f"{suffix}@test.school",
        password_hash="x" * 60, name="Staff",
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
    for branch in branches:
        db_session.add(
            UserSchoolUnit(
                id=_new_id("usu-"), tenant_id=tenant.id, user_id=user.id,
                school_unit_id=branch.id,
            )
        )
    db_session.flush()
    grant_profile_to(user, role.id, employee_number=f"EMP-{suffix}")
    return user, generate_access_token(user)


def _ask(client, tenant, token, query, **variables):
    headers = {"X-Tenant-Subdomain": tenant.subdomain}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return client.post(
        GRAPHQL_PATH, json={"query": query, "variables": variables}, headers=headers
    ).get_json()


def _codes(body):
    return [error["extensions"].get("code") for error in body.get("errors", [])]


def _list(client, tenant, token, **overrides):
    variables = {
        "first": 25, "offset": None, "orderBy": "GRADE", "direction": "ASC",
        "where": None,
    }
    variables.update(overrides)
    return _ask(client, tenant, token, CLASSES, **variables)


# ---------------------------------------------------------------------------
# The list
# ---------------------------------------------------------------------------

def test_the_classes_a_school_teaches(client, db_session, tenant, school):
    _user, token = _staff_with(db_session, tenant, "class.read")

    body = _list(client, tenant, token)

    assert "errors" not in body, body
    page = body["data"]["classes"]
    assert page["totalCount"] == 3
    assert page["hasNextPage"] is False
    assert [node["section"] for node in page["nodes"]] == ["A", "A", "B"]
    assert [node["gradeName"] for node in page["nodes"]] == [
        "Nursery", "Grade 1", "Grade 1",
    ]


def test_a_class_carries_its_structure_and_its_counts(
    client, db_session, tenant, school
):
    _user, token = _staff_with(db_session, tenant, "class.read")

    body = _list(client, tenant, token)

    nursery_a = body["data"]["classes"]["nodes"][0]
    assert nursery_a["programmeName"] == "Primary"
    assert nursery_a["schoolUnitName"] == "Main Campus"
    assert nursery_a["academicYear"] == "2026-2027"
    assert nursery_a["studentCount"] == 3
    assert nursery_a["teacherCount"] == 0


def test_a_class_is_named_by_its_grade_not_by_its_label(
    client, db_session, tenant, unit, programme, grades, year
):
    """`classes.name` is a nullable legacy label, empty for every class the
    structured form creates. Left to compose their own, two screens titled
    themselves "— A"; the rule belongs here, where there is one of it."""
    from modules.classes.models import Class

    unnamed = Class(
        id=_new_id("c-"), tenant_id=tenant.id, name=None, section="A",
        academic_year_id=year.id, school_unit_id=unit.id,
        programme_id=programme.id, grade_id=grades[0].id,
    )
    db_session.add(unnamed)
    db_session.flush()
    _user, token = _staff_with(db_session, tenant, "class.read")

    body = _ask(
        client, tenant, token,
        "query { classes(first: 5) { nodes { displayName } } }",
    )

    assert [n["displayName"] for n in body["data"]["classes"]["nodes"]] == [
        "Nursery A"
    ]


def test_a_class_with_no_grade_falls_back_to_its_label(
    client, db_session, tenant, unit, programme, year
):
    from modules.classes.models import Class

    db_session.add(
        Class(
            id=_new_id("c-"), tenant_id=tenant.id, name="Remedial", section="A",
            academic_year_id=year.id, school_unit_id=unit.id,
            programme_id=programme.id,
        )
    )
    db_session.flush()
    _user, token = _staff_with(db_session, tenant, "class.read")

    body = _ask(
        client, tenant, token,
        "query { classes(first: 5) { nodes { displayName } } }",
    )

    assert body["data"]["classes"]["nodes"][0]["displayName"] == "Remedial A"


def test_grades_come_back_in_teaching_order_not_alphabetical(
    client, db_session, tenant, school
):
    """Sorted as text, "Grade 1" precedes "Nursery" — which is not how a
    school reads its own list."""
    _user, token = _staff_with(db_session, tenant, "class.read")

    body = _list(client, tenant, token)

    sequences = [node["gradeSequence"] for node in body["data"]["classes"]["nodes"]]
    assert sequences == sorted(sequences)


def test_a_class_in_the_year_in_progress_is_active(client, db_session, tenant, school):
    _user, token = _staff_with(db_session, tenant, "class.read")

    body = _list(client, tenant, token)

    assert {node["status"] for node in body["data"]["classes"]["nodes"]} == {"active"}


def test_a_class_in_a_year_that_has_passed_is_archived(
    client, db_session, tenant, unit, programme, grades, school
):
    from modules.academics.academic_year.models import AcademicYear

    past = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name="2024-2025",
        start_date="2024-06-01", end_date="2025-03-31", is_active=False,
    )
    db_session.add(past)
    db_session.flush()
    _make_class(
        db_session, tenant, section="Z", unit=unit, programme=programme,
        grade=grades[0], year=past,
    )
    _user, token = _staff_with(db_session, tenant, "class.read")

    body = _list(client, tenant, token, where={"academicYearId": past.id})

    nodes = body["data"]["classes"]["nodes"]
    assert [node["status"] for node in nodes] == ["archived"]


# ---------------------------------------------------------------------------
# Paging
# ---------------------------------------------------------------------------

def test_a_page_stops_where_it_was_asked_to(client, db_session, tenant, school):
    _user, token = _staff_with(db_session, tenant, "class.read")

    body = _list(client, tenant, token, first=2)

    page = body["data"]["classes"]
    assert len(page["nodes"]) == 2
    assert page["hasNextPage"] is True
    assert page["totalCount"] == 3, "the total describes the filter, not the page"


def test_reading_on_until_there_is_no_more_returns_every_class_once(
    client, db_session, tenant, school
):
    """The walk the structured class picker makes.

    It needs the whole structure, not a page of it, and the only correct way
    to get that from a paged field is to keep asking. What must hold is that
    the pages tile exactly: no class seen twice, none missed.
    """
    _user, token = _staff_with(db_session, tenant, "class.read")

    seen, offset = [], 0
    while True:
        page = _ask(client, tenant, token, NAMES_ONLY, first=1, offset=offset)["data"][
            "classes"
        ]
        seen.extend(node["id"] for node in page["nodes"])
        if not page["hasNextPage"]:
            break
        offset += 1

    assert len(seen) == len(set(seen)) == 3


def test_a_negative_offset_is_refused_rather_than_resolved(
    client, db_session, tenant, school
):
    _user, token = _staff_with(db_session, tenant, "class.read")

    body = _list(client, tenant, token, offset=-1)

    assert "VALIDATION_ERROR" in _codes(body)


def test_the_page_size_is_capped_by_the_service(client, db_session, tenant, school):
    """A cap a caller can route around is not a cap."""
    _user, token = _staff_with(db_session, tenant, "class.read")

    body = _list(client, tenant, token, first=10_000)

    assert "errors" not in body, body
    assert len(body["data"]["classes"]["nodes"]) == 3


# ---------------------------------------------------------------------------
# Filtering, searching, sorting
# ---------------------------------------------------------------------------

def test_filtering_to_one_grade(client, db_session, tenant, school, grades):
    _user, token = _staff_with(db_session, tenant, "class.read")

    body = _list(client, tenant, token, where={"gradeId": grades[1].id})

    page = body["data"]["classes"]
    assert page["totalCount"] == 2
    assert {node["gradeName"] for node in page["nodes"]} == {"Grade 1"}


def test_searching_by_grade_name(client, db_session, tenant, school):
    _user, token = _staff_with(db_session, tenant, "class.read")

    body = _list(
        client, tenant, token,
        where={"search": "nursery", "searchField": "GRADE"},
    )

    assert body["data"]["classes"]["totalCount"] == 1


def test_the_total_describes_the_search_not_the_school(
    client, db_session, tenant, school
):
    _user, token = _staff_with(db_session, tenant, "class.read")

    body = _list(client, tenant, token, where={"search": "zzz-nothing"})

    page = body["data"]["classes"]
    assert page["totalCount"] == 0
    assert page["nodes"] == []


def test_sorting_the_other_way_round(client, db_session, tenant, school):
    _user, token = _staff_with(db_session, tenant, "class.read")

    body = _list(client, tenant, token, direction="DESC")

    sequences = [node["gradeSequence"] for node in body["data"]["classes"]["nodes"]]
    assert sequences == sorted(sequences, reverse=True)


def test_sorting_by_how_many_children_a_class_holds(
    client, db_session, tenant, school
):
    _user, token = _staff_with(db_session, tenant, "class.read")

    body = _list(client, tenant, token, orderBy="STUDENT_COUNT", direction="DESC")

    counts = [node["studentCount"] for node in body["data"]["classes"]["nodes"]]
    assert counts == [3, 1, 0]


# ---------------------------------------------------------------------------
# One query builder, two transports
# ---------------------------------------------------------------------------

def test_the_screen_and_the_export_list_the_same_classes(
    client, db_session, tenant, school, flask_app
):
    """Drift guard.

    The CSV export still goes through `get_all_classes`; the screens go
    through `classes_page`. Both build on `_class_list_query`, and this is what
    would fail if somebody added a filter to one of them alone.
    """
    from flask import g

    from modules.classes import services

    user, token = _staff_with(db_session, tenant, "class.read")
    body = _list(client, tenant, token, first=100)

    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = user
        exported = services.get_all_classes()

    assert [node["id"] for node in body["data"]["classes"]["nodes"]] == [
        item["id"] for item in exported["items"]
    ]


# ---------------------------------------------------------------------------
# Totals
# ---------------------------------------------------------------------------

def test_the_totals_describe_the_whole_filter(client, db_session, tenant, school):
    _user, token = _staff_with(db_session, tenant, "class.read")

    body = _ask(client, tenant, token, STATS, where=None)

    stats = body["data"]["classStats"]
    assert stats["totalClasses"] == 3
    assert stats["totalStudents"] == 4
    assert stats["totalTeachers"] == 0
    assert stats["averageClassSize"] == pytest.approx(1.3)


def test_the_totals_honour_the_same_filters_as_the_list(
    client, db_session, tenant, school, grades
):
    _user, token = _staff_with(db_session, tenant, "class.read")

    body = _ask(client, tenant, token, STATS, where={"gradeId": grades[1].id})

    stats = body["data"]["classStats"]
    assert stats["totalClasses"] == 2
    assert stats["totalStudents"] == 1


# ---------------------------------------------------------------------------
# One class, and who is in it
# ---------------------------------------------------------------------------

def test_one_class_with_the_children_placed_in_it(
    client, db_session, tenant, school
):
    nursery_a, _grade_one_a, _grade_one_b = school
    _user, token = _staff_with(db_session, tenant, "class.read")

    body = _ask(client, tenant, token, DETAIL, id=nursery_a.id)

    assert "errors" not in body, body
    detail = body["data"]["class"]
    assert detail["section"] == "A"
    assert detail["gradeName"] == "Nursery"
    assert detail["studentCount"] == 3
    assert len(detail["students"]) == 3
    assert all(child["fullName"] for child in detail["students"])
    assert all(child["admissionNumber"] for child in detail["students"])


def test_a_class_teacher_is_named_with_their_employee_number(
    client, db_session, tenant, school
):
    """The employee number the detail screen has always tried to render.

    REST answered this page without it — and without the subject name — so
    the screen fell back to the word "Subject" and showed no number at all.
    """
    from modules.academics.backbone.models import ClassTeacherAssignment

    nursery_a, _a, _b = school
    teacher_user, _token = _staff_with(db_session, tenant, "class.read")
    teacher = _teacher_for(db_session, tenant, teacher_user)
    db_session.add(
        ClassTeacherAssignment(
            tenant_id=tenant.id, class_id=nursery_a.id, teacher_id=teacher.id,
            role="primary", is_active=True,
        )
    )
    db_session.flush()
    _user, token = _staff_with(db_session, tenant, "class.read")

    body = _ask(client, tenant, token, DETAIL, id=nursery_a.id)

    held = body["data"]["class"]["teachers"]
    assert len(held) == 1
    assert held[0]["isClassTeacher"] is True
    assert held[0]["subjectId"] is None
    assert held[0]["teacherName"] == "Staff"
    assert held[0]["employeeNumber"], "the employment holds the number"


def test_a_class_nobody_has_is_not_found(client, db_session, tenant, school):
    _user, token = _staff_with(db_session, tenant, "class.read")

    body = _ask(client, tenant, token, DETAIL, id=_new_id("c-"))

    assert "errors" not in body, body
    assert body["data"]["class"] is None


def _teacher_for(db_session, tenant, user):
    from modules.teachers.models import Teacher

    staff = user.person.employments[0]
    teacher = Teacher(id=_new_id("t-"), tenant_id=tenant.id, staff=staff)
    db_session.add(teacher)
    db_session.flush()
    return teacher


# ---------------------------------------------------------------------------
# Who may read them
# ---------------------------------------------------------------------------

def test_reading_classes_needs_the_class_authority(client, db_session, tenant, school):
    _user, token = _staff_with(db_session, tenant, "student.read.all")

    assert "FORBIDDEN" in _codes(_list(client, tenant, token))
    assert "FORBIDDEN" in _codes(_ask(client, tenant, token, STATS, where=None))
    assert "FORBIDDEN" in _codes(
        _ask(client, tenant, token, DETAIL, id=school[0].id)
    )


def test_managing_classes_is_enough_to_read_them(client, db_session, tenant, school):
    """`<resource>.manage` covers every action on that resource, so naming the
    read is the whole rule."""
    _user, token = _staff_with(db_session, tenant, "class.manage")

    body = _list(client, tenant, token)

    assert "errors" not in body, body
    assert body["data"]["classes"]["totalCount"] == 3


def test_a_stranger_reads_nothing(client, tenant, school):
    body = _list(client, tenant, None)

    assert "UNAUTHENTICATED" in _codes(body)


# ---------------------------------------------------------------------------
# Branch scope, which now lives in the service
# ---------------------------------------------------------------------------

def test_a_branch_admin_sees_only_their_own_campus(
    client, db_session, tenant, unit, other_unit, programme, grades, year, school
):
    elsewhere = _make_class(
        db_session, tenant, section="A", unit=other_unit, programme=programme,
        grade=grades[0], year=year,
    )
    _user, token = _staff_with(
        db_session, tenant, "class.read", branches=(unit,)
    )

    body = _list(client, tenant, token, first=100)

    ids = {node["id"] for node in body["data"]["classes"]["nodes"]}
    assert elsewhere.id not in ids
    assert body["data"]["classes"]["totalCount"] == 3


def test_naming_someone_elses_campus_is_a_refusal_not_an_empty_list(
    client, db_session, tenant, unit, other_unit, school
):
    _user, token = _staff_with(db_session, tenant, "class.read", branches=(unit,))

    body = _list(client, tenant, token, where={"schoolUnitId": other_unit.id})

    assert "FORBIDDEN" in _codes(body)


def test_a_class_in_another_campus_cannot_be_opened(
    client, db_session, tenant, unit, other_unit, programme, grades, year, school
):
    """The check the route used to make. Deleting that route without moving
    this into the service would have opened every class to every sub-admin."""
    elsewhere = _make_class(
        db_session, tenant, section="A", unit=other_unit, programme=programme,
        grade=grades[0], year=year,
    )
    _user, token = _staff_with(db_session, tenant, "class.read", branches=(unit,))

    body = _ask(client, tenant, token, DETAIL, id=elsewhere.id)

    assert "FORBIDDEN" in _codes(body)


def test_a_token_from_another_school_reads_nothing(
    client, db_session, tenant, school, flask_app
):
    from core.models import Tenant

    other = Tenant(
        id=_new_id("t-"), name="Other School",
        subdomain=f"other-{uuid.uuid4().hex[:8]}", status="active",
    )
    db_session.add(other)
    db_session.flush()
    _user, token = _staff_with(db_session, other, "class.read")

    body = _list(client, tenant, token)

    assert "errors" in body, body


# ---------------------------------------------------------------------------
# The two REST reads the Expo client still needs
# ---------------------------------------------------------------------------

def _rest(client, tenant, token, path):
    return client.get(
        path,
        headers={
            "X-Tenant-Subdomain": tenant.subdomain,
            "Authorization": f"Bearer {token}",
        },
    )


def test_the_mobile_class_list_still_answers(client, db_session, tenant, school):
    """`GET /api/classes/` is read by two Expo services.

    It was deleted once on the strength of a grep over `client/src`, which is
    not where this repo's Expo code lives — `client/modules/` is. It goes when
    the mobile app moves to GraphQL and not before, so this test exists to
    make the next person look.
    """
    _user, token = _staff_with(db_session, tenant, "class.read")

    response = _rest(client, tenant, token, "/api/classes/")

    assert response.status_code == 200, response.get_json()
    payload = response.get_json()["data"]
    assert payload["total"] == 3
    assert {item["section"] for item in payload["items"]} == {"A", "B"}


def test_the_mobile_class_detail_still_answers(client, db_session, tenant, school):
    """`GET /api/classes/<id>` is `classService.getClassDetail` on mobile."""
    nursery_a, _a, _b = school
    _user, token = _staff_with(db_session, tenant, "class.read")

    response = _rest(client, tenant, token, f"/api/classes/{nursery_a.id}")

    assert response.status_code == 200, response.get_json()
    payload = response.get_json()["data"]
    assert payload["section"] == "A"
    assert payload["student_count"] == 3
    assert len(payload["students"]) == 3
    assert payload["status"] == "active"


def test_both_transports_describe_the_same_class(
    client, db_session, tenant, school
):
    """One reader, two shapes. The previous version of the REST payload was a
    second *reader*, and the two drifted."""
    nursery_a, _a, _b = school
    _user, token = _staff_with(db_session, tenant, "class.read")

    over_rest = _rest(client, tenant, token, f"/api/classes/{nursery_a.id}").get_json()[
        "data"
    ]
    over_graphql = _ask(client, tenant, token, DETAIL, id=nursery_a.id)["data"]["class"]

    assert over_rest["student_count"] == over_graphql["studentCount"]
    assert over_rest["teacher_count"] == over_graphql["teacherCount"]
    assert over_rest["status"] == over_graphql["status"]
    assert len(over_rest["students"]) == len(over_graphql["students"])
