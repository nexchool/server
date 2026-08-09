"""Section merge over GraphQL — the transport half.

The service already has its own tests: children move, history stays, and the
refusals hold. What is pinned here is everything the service cannot say for
itself.

The authority, first. A merge retires a section *and* moves every child in it,
so it answers to both `class.manage` and `student.update`. Someone holding only
the first could otherwise move a whole section of children with an operation
that never mentions students — which is how an authority model develops a hole
that nobody notices, because every individual permission looks correct.

And the disappearance. A merged section takes no more students, so it must
stop being offered as a choice — while staying visible to anyone asking what
happened to it.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from graphql_api import GRAPHQL_PATH

MERGE = """
mutation M($source: ID!, $into: ID!, $reason: String, $on: Date) {
  mergeSections(sourceId: $source, intoId: $into, reason: $reason, occurredOn: $on) {
    mergedSectionId intoSectionId studentsMoved mergedOn
  }
}
"""

LIST_SECTIONS = """
query L($where: ClassFilter) {
  classes(first: 50, where: $where) {
    nodes { id section mergedInto { intoClassId intoDisplayName reason mergedByName } }
    totalCount
  }
}
"""

ONE_SECTION = """
query One($id: ID!) {
  class(id: $id) {
    id section
    mergedInto { intoClassId intoDisplayName mergedOn reason mergedByName }
  }
}
"""


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def ready_school(db_session, tenant):
    tenant.is_setup_complete = True
    db_session.flush()
    return tenant


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
def next_year(db_session, tenant):
    from modules.academics.academic_year.models import AcademicYear

    year = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name=f"AY-{uuid.uuid4().hex[:6]}",
        start_date=date(2027, 6, 1), end_date=date(2028, 3, 31),
    )
    db_session.add(year)
    db_session.flush()
    return year


def _section(db_session, tenant, academic_year, label):
    from modules.classes.models import Class

    cls = Class(
        id=_new_id("c-"), tenant_id=tenant.id, name="Grade 8", section=label,
        academic_year_id=academic_year.id,
    )
    db_session.add(cls)
    db_session.flush()
    return cls


@pytest.fixture
def sections(db_session, tenant, academic_year):
    """8A and 8B, both taking students."""
    return (
        _section(db_session, tenant, academic_year, "A"),
        _section(db_session, tenant, academic_year, "B"),
    )


def _child_in(flask_app, db_session, tenant, academic_year, cls, name="Aarav Patel"):
    """A child placed in a section, through the enrollment that owns placement.

    `assign_student_to_class` reads the tenant off `g`, and answers
    "Tenant context is required" rather than raising when there is none — so
    calling it outside a request context creates the student, creates no
    enrollment, and reports nothing. The merge then finds no one to move and
    still succeeds, which is a green test asserting the wrong thing.
    """
    from flask import g
    from modules.people.models import Person
    from modules.students.class_enrollment_service import assign_student_to_class
    from modules.students.models import Student

    person = Person(id=_new_id("p-"), tenant_id=tenant.id, full_name=name)
    db_session.add(person)
    db_session.flush()
    student = Student(
        id=_new_id("s-"), tenant_id=tenant.id, person_id=person.id,
        admission_number=f"ADM-{uuid.uuid4().hex[:6]}",
        academic_year_id=academic_year.id, class_id=cls.id, student_status="active",
    )
    db_session.add(student)
    db_session.flush()

    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        outcome = assign_student_to_class(
            student.id, cls.id, academic_year.id, commit=False
        )
    assert outcome["success"], outcome
    return student


def _staff_with(db_session, tenant, *permission_keys, full_name=None):
    from modules.auth.models import User
    from modules.auth.services import generate_access_token
    from modules.people.models import Person
    from modules.rbac.models import Permission, Role, RolePermission
    from tests.conftest import grant_profile_to

    suffix = uuid.uuid4().hex[:8]
    person = None
    if full_name:
        person = Person(id=_new_id("p-"), tenant_id=tenant.id, full_name=full_name)
        db_session.add(person)
        db_session.flush()

    user = User(
        id=f"u-{suffix}", tenant_id=tenant.id, email=f"{suffix}@test.school",
        password_hash="x" * 60, name="Office Admin",
        person_id=person.id if person else None,
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
def registrar(db_session, tenant):
    """Holds both halves of a merge, and reads classes back."""
    return _staff_with(
        db_session, tenant,
        "class.manage", "student.update", "class.read",
        full_name="Meera Shah",
    )


def _ask(client, tenant, token, query, **variables):
    return client.post(
        GRAPHQL_PATH,
        json={"query": query, "variables": variables},
        headers={
            "X-Tenant-Subdomain": tenant.subdomain,
            "Authorization": f"Bearer {token}",
        },
    )


def _codes(body):
    return [error["extensions"].get("code") for error in body.get("errors", [])]


# ---------------------------------------------------------------------------
# Authority — a merge is two operations, so it answers to two keys
# ---------------------------------------------------------------------------

def test_retiring_a_section_is_not_enough_to_move_the_children_in_it(
    client, db_session, tenant, ready_school, sections
):
    """`class.manage` alone must not move students.

    This is the whole reason the mutation stacks two permissions. Someone who
    may reorganise rooms but not move children can otherwise move an entire
    section of them, because the operation is named after the room.
    """
    source, target = sections
    _user, token = _staff_with(db_session, tenant, "class.manage")

    body = _ask(
        client, tenant, token, MERGE, source=source.id, into=target.id
    ).get_json()

    assert "FORBIDDEN" in _codes(body)
    db_session.refresh(source)
    assert source.merged_into_class_id is None


def test_moving_one_child_is_not_enough_to_retire_a_section(
    client, db_session, tenant, ready_school, sections
):
    """And the other way round: `student.update` alone must not retire a room."""
    source, target = sections
    _user, token = _staff_with(db_session, tenant, "student.update")

    body = _ask(
        client, tenant, token, MERGE, source=source.id, into=target.id
    ).get_json()

    assert "FORBIDDEN" in _codes(body)
    db_session.refresh(source)
    assert source.merged_into_class_id is None


def test_holding_both_lets_the_merge_through(
    client, flask_app, db_session, tenant, ready_school, sections, academic_year,
    registrar,
):
    source, target = sections
    _child_in(flask_app, db_session, tenant, academic_year, source, name="Aarav Patel")
    _child_in(flask_app, db_session, tenant, academic_year, source, name="Diya Shah")
    _user, token = registrar

    body = _ask(
        client, tenant, token, MERGE,
        source=source.id, into=target.id, reason="Grade 8 lost students",
    ).get_json()

    assert body.get("errors") is None, body
    result = body["data"]["mergeSections"]
    assert result["mergedSectionId"] == source.id
    assert result["intoSectionId"] == target.id
    assert result["studentsMoved"] == 2


# ---------------------------------------------------------------------------
# Refusals arrive as codes, not prose
# ---------------------------------------------------------------------------

def test_merging_a_section_into_itself_is_a_conflict(
    client, tenant, ready_school, sections, registrar
):
    source, _target = sections
    _user, token = registrar

    body = _ask(
        client, tenant, token, MERGE, source=source.id, into=source.id
    ).get_json()

    assert "CONFLICT" in _codes(body)


def test_merging_across_academic_years_is_a_validation_failure(
    client, db_session, tenant, ready_school, academic_year, next_year, registrar
):
    """Moving children between years is promotion, which decides other things."""
    source = _section(db_session, tenant, academic_year, "A")
    target = _section(db_session, tenant, next_year, "A")
    _user, token = registrar

    body = _ask(
        client, tenant, token, MERGE, source=source.id, into=target.id
    ).get_json()

    assert "VALIDATION_ERROR" in _codes(body)


def test_a_section_that_does_not_exist_is_not_found(
    client, tenant, ready_school, sections, registrar
):
    _source, target = sections
    _user, token = registrar

    body = _ask(
        client, tenant, token, MERGE, source="c-nope", into=target.id
    ).get_json()

    assert "NOT_FOUND" in _codes(body)


def test_merging_the_same_section_twice_is_a_conflict(
    client, db_session, tenant, ready_school, sections, academic_year, registrar
):
    source, target = sections
    third = _section(db_session, tenant, academic_year, "C")
    _user, token = registrar

    first = _ask(client, tenant, token, MERGE, source=source.id, into=target.id)
    assert first.get_json().get("errors") is None

    body = _ask(
        client, tenant, token, MERGE, source=source.id, into=third.id
    ).get_json()
    assert "CONFLICT" in _codes(body)


# ---------------------------------------------------------------------------
# A retired section stops being a choice, without disappearing
# ---------------------------------------------------------------------------

def test_a_merged_section_is_not_offered_in_the_class_list(
    client, db_session, tenant, ready_school, sections, registrar
):
    """The defect this whole slice exists to close.

    Placing a student into a merged section is refused at the primitive, so a
    picker that still lists one is offering a choice the system will reject.
    """
    source, target = sections
    _user, token = registrar

    _ask(client, tenant, token, MERGE, source=source.id, into=target.id)

    body = _ask(client, tenant, token, LIST_SECTIONS).get_json()
    assert body.get("errors") is None, body
    listed = {node["id"] for node in body["data"]["classes"]["nodes"]}
    assert target.id in listed
    assert source.id not in listed


def test_the_total_agrees_with_the_list(
    client, db_session, tenant, ready_school, sections, registrar
):
    """`totalCount` re-runs the filters, so it must drop merged sections too.

    A count that still included them would page a screen to a row it never
    shows.
    """
    source, target = sections
    _user, token = registrar

    before = _ask(client, tenant, token, LIST_SECTIONS).get_json()
    started_with = before["data"]["classes"]["totalCount"]

    _ask(client, tenant, token, MERGE, source=source.id, into=target.id)

    after = _ask(client, tenant, token, LIST_SECTIONS).get_json()
    assert after["data"]["classes"]["totalCount"] == started_with - 1
    assert len(after["data"]["classes"]["nodes"]) == started_with - 1


def test_asking_for_merged_sections_brings_them_back(
    client, db_session, tenant, ready_school, sections, registrar
):
    """Retired is not deleted — a history view must still be able to see it."""
    source, target = sections
    _user, token = registrar

    _ask(client, tenant, token, MERGE, source=source.id, into=target.id)

    body = _ask(
        client, tenant, token, LIST_SECTIONS, where={"includeMerged": True}
    ).get_json()
    assert body.get("errors") is None, body
    listed = {node["id"] for node in body["data"]["classes"]["nodes"]}
    assert source.id in listed


def test_a_retired_section_says_where_its_future_went(
    client, db_session, tenant, ready_school, sections, registrar
):
    """Who, why and where — the three questions asked a term later."""
    source, target = sections
    _user, token = registrar

    _ask(
        client, tenant, token, MERGE,
        source=source.id, into=target.id, reason="Grade 8 lost students",
    )

    body = _ask(client, tenant, token, ONE_SECTION, id=source.id).get_json()
    assert body.get("errors") is None, body
    merge = body["data"]["class"]["mergedInto"]
    assert merge["intoClassId"] == target.id
    # The survivor named as a reader knows it, not as an id — `sections` is
    # (A, B) and B is the one that stays.
    assert merge["intoDisplayName"] == "Grade 8 B"
    assert merge["reason"] == "Grade 8 lost students"
    # Read from the person, not the login copy — see debt 15.
    assert merge["mergedByName"] == "Meera Shah"


def test_a_living_section_has_no_merge_to_report(
    client, tenant, ready_school, sections, registrar
):
    _source, target = sections
    _user, token = registrar

    body = _ask(client, tenant, token, ONE_SECTION, id=target.id).get_json()
    assert body["data"]["class"]["mergedInto"] is None
