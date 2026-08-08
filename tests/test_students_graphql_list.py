"""What the GraphQL student list must do before the REST one can go.

The REST list grew every control a screen asked for: five sort keys, six
search fields, a dozen filters, page numbers. Replacing it is not "add
pagination" — it is matching all of that, and the tests here are the
inventory. Anything missing is a screen that loses a control.

Two things are pinned beyond parity. Both transports now run one query
builder, so a filter cannot mean different things depending on who asked;
and a cursor is refused for orders whose key can be empty, because over
those it would quietly lose students rather than fail.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from graphql_api import GRAPHQL_PATH

LIST = """
query L(
  $first: Int, $after: String, $offset: Int,
  $orderBy: StudentOrder, $direction: OrderDirection, $where: StudentFilter
) {
  students(
    first: $first, after: $after, offset: $offset,
    orderBy: $orderBy, direction: $direction, where: $where
  ) {
    totalCount
    edges { cursor node { admissionNumber fullName rollNumber gender guardianPhone
                          currentClass { section gradeName programmeName } } }
    pageInfo { hasNextPage endCursor }
  }
}
"""


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


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
def units(db_session, tenant):
    from modules.school_units.models import SchoolUnit

    campuses = [
        SchoolUnit(
            id=_new_id("su-"), tenant_id=tenant.id, name=name,
            code=f"{name[-1]}-{uuid.uuid4().hex[:6]}",
        )
        for name in ("Campus A", "Campus B")
    ]
    db_session.add_all(campuses)
    db_session.flush()
    return campuses


@pytest.fixture
def programmes(db_session, tenant):
    from modules.academic_programmes.models import AcademicProgramme

    rows = [
        AcademicProgramme(
            id=_new_id("prog-"), tenant_id=tenant.id, name=name, board=code,
            code=f"{code}-{uuid.uuid4().hex[:6]}",
        )
        for name, code in (("CBSE English", "cbse"), ("GSEB Gujarati", "gseb"))
    ]
    db_session.add_all(rows)
    db_session.flush()
    return rows


@pytest.fixture
def school(db_session, tenant, academic_year, units, programmes):
    """Two grades on two campuses under two boards, with named children.

    Deliberately not uniform: sorting and filtering are only interesting when
    the answers differ, and a trust running two boards on one campus is the
    product's stated shape rather than an edge case.
    """
    from modules.classes.models import Class
    from modules.people.models import Person
    from modules.students.models import Student

    cbse, gseb = programmes
    campus_a, campus_b = units

    classes = {}
    for label, grade_level, unit, programme in (
        ("5A", 5, campus_a, cbse),
        ("5B", 5, campus_a, gseb),
        ("10A", 10, campus_b, gseb),
    ):
        row = Class(
            id=_new_id("c-"), tenant_id=tenant.id, name=f"Grade {grade_level}",
            section=label[-1], grade_level=grade_level,
            academic_year_id=academic_year.id, school_unit_id=unit.id,
            programme_id=programme.id,
        )
        db_session.add(row)
        classes[label] = row
    db_session.flush()

    people = [
        # name,          class, roll, gender,   admitted,   transport, adm no
        ("Zara Mehta", "5A", 3, "female", date(2026, 6, 1), True, "ADM-0003"),
        ("Aarav Shah", "5A", 1, "male", date(2026, 6, 2), False, "ADM-0001"),
        ("Manan Patel", "5B", 2, "male", date(2026, 7, 1), True, "ADM-0002"),
        ("Isha Desai", "10A", None, "female", date(2026, 8, 1), False, "ADM-0004"),
    ]
    students = []
    for name, label, roll, gender, admitted, transport, admission_number in people:
        person = Person(
            id=_new_id("p-"), tenant_id=tenant.id, full_name=name, gender=gender
        )
        db_session.add(person)
        db_session.flush()
        student = Student(
            id=_new_id("s-"), tenant_id=tenant.id, person_id=person.id,
            admission_number=admission_number, academic_year_id=academic_year.id,
            class_id=classes[label].id, roll_number=roll,
            student_status="active", admission_date=admitted,
            is_transport_opted=transport, guardian_phone=f"98{admission_number[-6:]}",
        )
        db_session.add(student)
        students.append(student)
    db_session.flush()
    return {"classes": classes, "students": students}


def _staff_with(db_session, tenant, *permission_keys):
    from modules.auth.models import User
    from modules.auth.services import generate_access_token
    from modules.rbac.models import Permission, Role, RolePermission
    from tests.conftest import grant_profile_to

    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=f"u-{suffix}", tenant_id=tenant.id, email=f"{suffix}@test.school",
        password_hash="x" * 60, name="Office Admin",
    )
    db_session.add(user)
    db_session.flush()

    role = Role(id=f"r-{suffix}", tenant_id=tenant.id, name=f"Office-{suffix}")
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
    grant_profile_to(user, role.id, employee_number=f"EMP-{suffix}")
    return user, generate_access_token(user)


@pytest.fixture
def office(db_session, tenant):
    return _staff_with(db_session, tenant, "student.read.all")


def _ask(client, tenant, token, **variables):
    return client.post(
        GRAPHQL_PATH,
        json={"query": LIST, "variables": variables},
        headers={
            "X-Tenant-Subdomain": tenant.subdomain,
            "Authorization": f"Bearer {token}",
        },
    ).get_json()


def _names(body):
    return [edge["node"]["fullName"] for edge in body["data"]["students"]["edges"]]


def _codes(body):
    return [error["extensions"].get("code") for error in body.get("errors", [])]


# ---------------------------------------------------------------------------
# Ordering — every key the table offers
# ---------------------------------------------------------------------------

def test_the_default_order_is_the_admission_number(client, tenant, school, office):
    _user, token = office

    body = _ask(client, tenant, token, first=10)

    assert "errors" not in body, body
    assert [e["node"]["admissionNumber"] for e in body["data"]["students"]["edges"]] == [
        "ADM-0001", "ADM-0002", "ADM-0003", "ADM-0004",
    ]


def test_students_can_be_ordered_by_name(client, tenant, school, office):
    _user, token = office

    body = _ask(client, tenant, token, first=10, orderBy="NAME")

    assert _names(body) == ["Aarav Shah", "Isha Desai", "Manan Patel", "Zara Mehta"]


def test_an_order_can_be_reversed(client, tenant, school, office):
    _user, token = office

    body = _ask(client, tenant, token, first=10, orderBy="NAME", direction="DESC")

    assert _names(body) == ["Zara Mehta", "Manan Patel", "Isha Desai", "Aarav Shah"]


def test_ordering_by_class_reads_the_grade_not_its_name(client, tenant, school, office):
    """Grade 10 sorts after Grade 5, and sections order within a grade.

    A lexical sort on the class name puts "Grade 10" first, which is the bug
    this ordering exists to avoid.
    """
    _user, token = office

    body = _ask(client, tenant, token, first=10, orderBy="CLASS")

    assert [e["node"]["admissionNumber"] for e in body["data"]["students"]["edges"]] == [
        "ADM-0001",  # 5 A
        "ADM-0003",  # 5 A
        "ADM-0002",  # 5 B
        "ADM-0004",  # 10 A — last, because 10 > 5 as a number
    ]


def test_ordering_by_roll_number_puts_the_unnumbered_last(
    client, tenant, school, office
):
    """A student with no roll number sorts to the bottom, both directions."""
    _user, token = office

    ascending = _ask(client, tenant, token, first=10, orderBy="ROLL_NUMBER")
    descending = _ask(
        client, tenant, token, first=10, orderBy="ROLL_NUMBER", direction="DESC"
    )

    assert _names(ascending)[-1] == "Isha Desai"
    assert _names(descending)[-1] == "Isha Desai"


def test_students_can_be_ordered_by_programme(client, tenant, school, office):
    _user, token = office

    body = _ask(client, tenant, token, first=10, orderBy="PROGRAMME")
    programmes = [
        e["node"]["currentClass"]["programmeName"]
        for e in body["data"]["students"]["edges"]
    ]

    assert programmes == sorted(programmes)


# ---------------------------------------------------------------------------
# Paging — a cursor where it is sound, an offset where a page number must jump
# ---------------------------------------------------------------------------

def test_a_cursor_walks_a_named_order_without_repeating_anyone(
    client, tenant, school, office
):
    _user, token = office

    seen, cursor = [], None
    for _ in range(5):
        body = _ask(client, tenant, token, first=2, after=cursor, orderBy="NAME")
        page = body["data"]["students"]
        seen.extend(edge["node"]["fullName"] for edge in page["edges"])
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]

    assert seen == ["Aarav Shah", "Isha Desai", "Manan Patel", "Zara Mehta"]


def test_a_cursor_walks_a_reversed_order_too(client, tenant, school, office):
    _user, token = office

    first_page = _ask(
        client, tenant, token, first=2, orderBy="NAME", direction="DESC"
    )["data"]["students"]
    second_page = _ask(
        client, tenant, token, first=2, orderBy="NAME", direction="DESC",
        after=first_page["pageInfo"]["endCursor"],
    )["data"]["students"]

    walked = [e["node"]["fullName"] for e in first_page["edges"] + second_page["edges"]]
    assert walked == ["Zara Mehta", "Manan Patel", "Isha Desai", "Aarav Shah"]


def test_a_reversed_cursor_does_not_lose_a_namesake(
    client, db_session, tenant, school, academic_year, office
):
    """Two children with the same name, paged backwards through the name.

    The tie-breaker runs ascending even when the sort runs descending, so the
    predicate that resumes the walk is not a plain row comparison: it is "an
    earlier name, OR the same name and a later admission number". Written as
    one row comparison it silently drops the second namesake — and with every
    name distinct, no test notices.
    """
    from modules.people.models import Person
    from modules.students.models import Student

    _user, token = office
    twin = Person(id=_new_id("p-"), tenant_id=tenant.id, full_name="Manan Patel",
                  gender="male")
    db_session.add(twin)
    db_session.flush()
    db_session.add(
        Student(
            id=_new_id("s-"), tenant_id=tenant.id, person_id=twin.id,
            admission_number="ADM-0005", academic_year_id=academic_year.id,
            class_id=school["classes"]["5A"].id, student_status="active",
        )
    )
    db_session.flush()

    seen, cursor = [], None
    for _ in range(6):
        page = _ask(
            client, tenant, token, first=2, after=cursor,
            orderBy="NAME", direction="DESC",
        )["data"]["students"]
        seen.extend(
            (e["node"]["fullName"], e["node"]["admissionNumber"]) for e in page["edges"]
        )
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]

    assert seen == [
        ("Zara Mehta", "ADM-0003"),
        ("Manan Patel", "ADM-0002"),
        ("Manan Patel", "ADM-0005"),
        ("Isha Desai", "ADM-0004"),
        ("Aarav Shah", "ADM-0001"),
    ]


def test_an_offset_jumps_to_a_page_a_cursor_cannot_reach(
    client, tenant, school, office
):
    """What a page-number control needs: page 2 without reading page 1."""
    _user, token = office

    body = _ask(client, tenant, token, first=2, offset=2)

    assert [e["node"]["admissionNumber"] for e in body["data"]["students"]["edges"]] == [
        "ADM-0003", "ADM-0004",
    ]
    assert body["data"]["students"]["pageInfo"]["hasNextPage"] is False


def test_an_order_whose_key_can_be_empty_refuses_a_cursor(
    client, tenant, school, office
):
    """Refusing beats losing students.

    A cursor over a nullable, mutable key skips or repeats rows silently. The
    field says so instead, and names the way through.
    """
    _user, token = office
    page = _ask(client, tenant, token, first=2, orderBy="CLASS")["data"]["students"]

    body = _ask(
        client, tenant, token, first=2, orderBy="CLASS",
        after=page["pageInfo"]["endCursor"],
    )

    assert "VALIDATION_ERROR" in _codes(body)
    assert "offset" in body["errors"][0]["message"]


def test_asking_for_both_a_cursor_and_an_offset_is_refused(
    client, tenant, school, office
):
    _user, token = office

    body = _ask(client, tenant, token, first=2, after="anything", offset=2)

    assert "VALIDATION_ERROR" in _codes(body)


def test_a_cursor_this_server_did_not_issue_is_refused(client, tenant, school, office):
    _user, token = office

    body = _ask(client, tenant, token, first=2, after="not-a-real-cursor")

    assert "VALIDATION_ERROR" in _codes(body)


# ---------------------------------------------------------------------------
# Filters — the inventory the REST list carried
# ---------------------------------------------------------------------------

def test_students_can_be_filtered_by_campus(client, tenant, school, units, office):
    _user, token = office
    _campus_a, campus_b = units

    body = _ask(
        client, tenant, token, first=10, where={"schoolUnitId": campus_b.id}
    )

    assert _names(body) == ["Isha Desai"]


def test_students_can_be_filtered_by_programme(
    client, tenant, school, programmes, office
):
    """Two boards on one campus is the product's stated shape."""
    _user, token = office
    cbse, _gseb = programmes

    body = _ask(client, tenant, token, first=10, where={"programmeId": cbse.id})

    assert sorted(_names(body)) == ["Aarav Shah", "Zara Mehta"]


def test_students_can_be_filtered_by_gender(client, tenant, school, office):
    _user, token = office

    body = _ask(client, tenant, token, first=10, where={"gender": "female"})

    assert sorted(_names(body)) == ["Isha Desai", "Zara Mehta"]


def test_students_can_be_filtered_by_whether_they_take_the_bus(
    client, tenant, school, office
):
    _user, token = office

    body = _ask(client, tenant, token, first=10, where={"isTransportOpted": True})

    assert sorted(_names(body)) == ["Manan Patel", "Zara Mehta"]


def test_students_can_be_filtered_by_when_they_were_admitted(
    client, tenant, school, office
):
    _user, token = office

    body = _ask(
        client, tenant, token, first=10,
        where={"admittedFrom": "2026-07-01", "admittedTo": "2026-07-31"},
    )

    assert _names(body) == ["Manan Patel"]


def test_a_search_can_be_narrowed_to_one_field(client, tenant, school, office):
    """"Shah" is a name here and nothing else; searching guardian phones for
    it must find nobody, or the dropdown is decorative."""
    _user, token = office

    everywhere = _ask(client, tenant, token, first=10, where={"search": "Shah"})
    by_phone = _ask(
        client, tenant, token, first=10,
        where={"search": "Shah", "searchField": "guardian_phone"},
    )

    assert _names(everywhere) == ["Aarav Shah"]
    assert _names(by_phone) == []


def test_several_classes_can_be_asked_for_at_once(client, tenant, school, office):
    _user, token = office
    classes = school["classes"]

    body = _ask(
        client, tenant, token, first=10,
        where={"classIds": [classes["5B"].id, classes["10A"].id]},
    )

    assert sorted(_names(body)) == ["Isha Desai", "Manan Patel"]


def test_the_total_counts_the_filter_not_the_page(client, tenant, school, office):
    _user, token = office

    body = _ask(client, tenant, token, first=1, where={"gender": "female"})

    assert len(body["data"]["students"]["edges"]) == 1
    assert body["data"]["students"]["totalCount"] == 2


# ---------------------------------------------------------------------------
# A class teacher reads the same field, and sees less
# ---------------------------------------------------------------------------

def test_a_class_teacher_sees_only_the_classes_they_teach(
    client, db_session, tenant, school, office
):
    from modules.attendance import services as attendance_services

    _user, token = _staff_with(db_session, tenant, "student.read.class")
    only_5b = school["classes"]["5B"].id
    original = attendance_services.get_teacher_class_ids
    attendance_services.get_teacher_class_ids = lambda user_id: [only_5b]
    try:
        body = _ask(client, tenant, token, first=10)
    finally:
        attendance_services.get_teacher_class_ids = original

    assert _names(body) == ["Manan Patel"]
    assert body["data"]["students"]["totalCount"] == 1


def test_a_teacher_of_nothing_sees_nobody_rather_than_everybody(
    client, db_session, tenant, school
):
    """An empty ceiling is a real answer. Treated as "no filter" it would
    hand a teacher the whole school."""
    from modules.attendance import services as attendance_services

    _user, token = _staff_with(db_session, tenant, "student.read.class")
    original = attendance_services.get_teacher_class_ids
    attendance_services.get_teacher_class_ids = lambda user_id: []
    try:
        body = _ask(client, tenant, token, first=10)
    finally:
        attendance_services.get_teacher_class_ids = original

    assert _names(body) == []
    assert body["data"]["students"]["totalCount"] == 0


def test_reading_students_still_needs_one_of_the_two_authorities(
    client, db_session, tenant, school
):
    _user, token = _staff_with(db_session, tenant, "student.create")

    body = _ask(client, tenant, token, first=10)

    assert "FORBIDDEN" in _codes(body)


# ---------------------------------------------------------------------------
# One query builder, so the two transports cannot disagree
# ---------------------------------------------------------------------------

def test_both_transports_answer_the_same_question_the_same_way(
    client, tenant, school, office
):
    """While REST and GraphQL both exist, a filter must mean one thing.

    Asked through both real entry points, not through the shared function —
    the point is that the two front doors agree, which is only interesting if
    each is reached the way a client reaches it.
    """
    _user, token = office
    headers = {
        "X-Tenant-Subdomain": tenant.subdomain,
        "Authorization": f"Bearer {token}",
    }

    over_rest = client.get(
        "/api/students/?gender=female&search=a&sort_by=name&page=1&per_page=50",
        headers=headers,
    ).get_json()["data"]
    over_graphql = _ask(
        client, tenant, token, first=50, orderBy="NAME",
        where={"gender": "female", "search": "a"},
    )

    assert [row["name"] for row in over_rest["items"]] == _names(over_graphql)
    assert over_rest["total"] == over_graphql["data"]["students"]["totalCount"]
    assert over_rest["total"] == 2
