"""Student lifecycle over GraphQL — the write half of the pilot.

What is pinned here is not that a student can be withdrawn; the workflows
already have their own tests. It is that a workflow reached over GraphQL is
the same workflow: it refuses for the same reasons, tells the client which
kind of refusal it was, and stays inside the campus the caller works at.

The refusal codes matter more than they look. A transport that recognised
"already recorded as withdrawn" by matching the sentence would keep working
until somebody reworded it, and then quietly start reporting a conflict as
an unexpected error.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from graphql_api import GRAPHQL_PATH
from modules.students.models import (
    EVENT_GRADUATED,
    EVENT_TRANSFERRED_OUT,
    EVENT_WITHDRAWN,
)

WITHDRAW = """
mutation W($id: ID!, $reason: String, $on: Date) {
  withdrawStudent(id: $id, reason: $reason, occurredOn: $on) {
    id admissionNumber status currentClass { id }
  }
}
"""

GRADUATE = "mutation G($id: ID!) { graduateStudent(id: $id) { id status } }"

RE_ENROLL = """
mutation R($id: ID!, $classId: ID!) {
  reEnrollStudent(id: $id, classId: $classId) {
    id admissionNumber status currentClass { section }
  }
}
"""

MOVE_SECTION = """
mutation M($id: ID!, $to: ID!) {
  transferStudentToSection(id: $id, toClassId: $to) {
    id status currentClass { section }
  }
}
"""

TRANSFER_OUT = """
mutation T($id: ID!, $school: String) {
  transferStudentOut(id: $id, destinationSchool: $school) { id status }
}
"""

READ_ONE = "query One($id: ID!) { student(id: $id) { admissionNumber } }"


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def ready_school(db_session, tenant):
    """A school that has finished its setup wizard.

    Writes are gated on this, so a fixture that forgot it would make every
    mutation below fail for the wrong reason.
    """
    tenant.is_setup_complete = True
    db_session.flush()
    return tenant


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


@pytest.fixture
def classes(db_session, tenant, units, academic_year):
    """Grade 5 A on one campus, Grade 5 B on the other."""
    from modules.classes.models import Class

    rooms = [
        Class(
            id=_new_id("c-"), tenant_id=tenant.id, name="Grade 5", section=section,
            academic_year_id=academic_year.id, school_unit_id=unit.id,
        )
        for section, unit in zip(("A", "B"), units)
    ]
    db_session.add_all(rooms)
    db_session.flush()
    return rooms


def _admit(db_session, tenant, klass, academic_year, name="A Child"):
    from modules.people.models import Person
    from modules.students.models import Student

    person = Person(id=_new_id("p-"), tenant_id=tenant.id, full_name=name)
    db_session.add(person)
    db_session.flush()
    student = Student(
        id=_new_id("s-"), tenant_id=tenant.id, person_id=person.id,
        admission_number=f"ADM-{uuid.uuid4().hex[:8]}",
        academic_year_id=academic_year.id,
        class_id=klass.id if klass else None,
        student_status="active",
    )
    db_session.add(student)
    db_session.flush()
    return student


@pytest.fixture
def student(db_session, tenant, classes, academic_year):
    return _admit(db_session, tenant, classes[0], academic_year)


def _staff_with(db_session, tenant, *permission_keys, restricted_to=None):
    """Somebody employed here, holding exactly these Business Actions."""
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

    if restricted_to is not None:
        from modules.sub_admins.models import UserSchoolUnit

        db_session.add(
            UserSchoolUnit(
                id=_new_id("usu-"), tenant_id=tenant.id, user_id=user.id,
                school_unit_id=restricted_to.id,
            )
        )
        db_session.flush()

    return user, generate_access_token(user)


@pytest.fixture
def office(db_session, tenant):
    """Reads the school and changes where a student stands with it."""
    return _staff_with(db_session, tenant, "student.read.all", "student.update")


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


def _events(student_id):
    from modules.students.lifecycle_service import timeline_for

    return [entry.event for entry in timeline_for(student_id)]


# ---------------------------------------------------------------------------
# Authority
# ---------------------------------------------------------------------------

def test_changing_a_student_needs_more_than_reading_them(
    client, db_session, tenant, ready_school, student
):
    """Reading the school and changing it are different authorities."""
    _user, token = _staff_with(db_session, tenant, "student.read.all")

    body = _ask(client, tenant, token, WITHDRAW, id=student.id).get_json()

    assert "FORBIDDEN" in _codes(body)
    assert student.student_status == "active"


def test_a_school_still_in_its_wizard_can_be_read_but_not_written_to(
    client, db_session, tenant, student, office
):
    """Setup is incomplete: the dashboard still works, the writes do not."""
    _user, token = office
    tenant.is_setup_complete = False
    db_session.flush()

    refused = _ask(client, tenant, token, WITHDRAW, id=student.id).get_json()
    readable = _ask(client, tenant, token, READ_ONE, id=student.id).get_json()

    assert "SETUP_INCOMPLETE" in _codes(refused)
    assert readable["data"]["student"]["admissionNumber"] == student.admission_number


def test_a_refusal_raised_inside_a_service_keeps_its_meaning(
    client, db_session, tenant, ready_school, units, classes, academic_year
):
    """A campus admin reaching into another campus is forbidden, not broken.

    The service says no by raising its own exception, which no Flask error
    handler is around to catch here. Without the transport translating it the
    client is told an unexpected error occurred, and we log our own bug.
    """
    campus_a, campus_b = units
    theirs = _admit(db_session, tenant, classes[1], academic_year, name="Their Child")
    _user, token = _staff_with(
        db_session, tenant, "student.update", restricted_to=campus_a
    )

    body = _ask(client, tenant, token, WITHDRAW, id=theirs.id).get_json()

    assert "FORBIDDEN" in _codes(body)
    assert theirs.student_status == "active"


# ---------------------------------------------------------------------------
# The workflow, not the field
# ---------------------------------------------------------------------------

def test_withdrawing_ends_the_placement_and_writes_down_why(
    client, tenant, ready_school, student, office
):
    _user, token = office

    body = _ask(
        client, tenant, token, WITHDRAW,
        id=student.id, reason="Family moved city", on="2026-07-15",
    ).get_json()

    assert "errors" not in body, body
    changed = body["data"]["withdrawStudent"]
    assert changed["status"] == "withdrawn"
    assert changed["currentClass"] is None, "a student who left holds no place"
    assert changed["admissionNumber"] == student.admission_number
    assert EVENT_WITHDRAWN in _events(student.id)


def test_a_student_cannot_leave_twice(client, tenant, ready_school, student, office):
    _user, token = office
    _ask(client, tenant, token, WITHDRAW, id=student.id)

    body = _ask(client, tenant, token, WITHDRAW, id=student.id).get_json()

    assert "CONFLICT" in _codes(body)


def test_an_unknown_student_is_not_found(client, tenant, ready_school, office):
    _user, token = office

    body = _ask(client, tenant, token, WITHDRAW, id="s-nobody").get_json()

    assert "NOT_FOUND" in _codes(body)


def test_graduating_is_finishing_rather_than_leaving(
    client, tenant, ready_school, student, office
):
    _user, token = office

    body = _ask(client, tenant, token, GRADUATE, id=student.id).get_json()

    assert "errors" not in body, body
    assert body["data"]["graduateStudent"]["status"] == "graduated"
    assert EVENT_GRADUATED in _events(student.id)


def test_leaving_for_another_school_records_where_they_went(
    client, tenant, ready_school, student, office
):
    _user, token = office

    body = _ask(
        client, tenant, token, TRANSFER_OUT, id=student.id, school="St Xavier's"
    ).get_json()

    assert "errors" not in body, body
    assert body["data"]["transferStudentOut"]["status"] == "transferred"
    assert EVENT_TRANSFERRED_OUT in _events(student.id)


def test_a_returning_student_is_not_admitted_again(
    client, tenant, ready_school, student, classes, office
):
    """The same child, the same admission number, a new placement."""
    _user, token = office
    _ask(client, tenant, token, WITHDRAW, id=student.id)

    body = _ask(
        client, tenant, token, RE_ENROLL, id=student.id, classId=classes[0].id
    ).get_json()

    assert "errors" not in body, body
    returned = body["data"]["reEnrollStudent"]
    assert returned["status"] == "active"
    assert returned["admissionNumber"] == student.admission_number
    assert returned["currentClass"]["section"] == "A"


def test_moving_section_keeps_the_student_active(
    client, tenant, ready_school, student, classes, office
):
    _user, token = office

    body = _ask(
        client, tenant, token, MOVE_SECTION, id=student.id, to=classes[1].id
    ).get_json()

    assert "errors" not in body, body
    moved = body["data"]["transferStudentToSection"]
    assert moved["currentClass"]["section"] == "B"
    assert moved["status"] == "active", "moving rooms is not leaving the school"


# ---------------------------------------------------------------------------
# A refusal says which kind it is
# ---------------------------------------------------------------------------

def test_a_move_across_years_is_bad_input_rather_than_a_conflict(
    client, db_session, tenant, ready_school, student, units, next_year, office
):
    """Different refusals reach the client as different codes.

    Both this and "already withdrawn" are the workflow saying no; a client
    that shows one as a validation message and the other as a state error
    can only tell them apart because the service says which it is.
    """
    from modules.classes.models import Class

    _user, token = office
    elsewhere = Class(
        id=_new_id("c-"), tenant_id=tenant.id, name="Grade 6", section="A",
        academic_year_id=next_year.id, school_unit_id=units[0].id,
    )
    db_session.add(elsewhere)
    db_session.flush()

    body = _ask(
        client, tenant, token, MOVE_SECTION, id=student.id, to=elsewhere.id
    ).get_json()

    assert "VALIDATION_ERROR" in _codes(body)
    assert student.class_id != elsewhere.id


def test_a_campus_admin_cannot_move_their_student_to_another_campus(
    client, db_session, tenant, ready_school, student, units, classes
):
    """Where a child is going is as branch-restricted as where they are.

    The workflow asks this itself rather than trusting the caller to have
    asked, so it holds however the workflow is reached — REST, GraphQL, or
    the section merge that calls it in a loop.
    """
    campus_a, _campus_b = units
    _user, token = _staff_with(
        db_session, tenant, "student.update", restricted_to=campus_a
    )

    body = _ask(
        client, tenant, token, MOVE_SECTION, id=student.id, to=classes[1].id
    ).get_json()

    assert "FORBIDDEN" in _codes(body)
    assert student.class_id == classes[0].id


def test_moving_to_a_class_that_does_not_exist_is_not_found(
    client, tenant, ready_school, student, office
):
    _user, token = office

    body = _ask(
        client, tenant, token, MOVE_SECTION, id=student.id, to="c-nowhere"
    ).get_json()

    assert "NOT_FOUND" in _codes(body)


def test_a_refusal_carries_the_sentence_a_person_reads(
    client, tenant, ready_school, student, office
):
    """Codes are for the client; the message still has to be worth showing."""
    _user, token = office
    _ask(client, tenant, token, GRADUATE, id=student.id)

    body = _ask(client, tenant, token, GRADUATE, id=student.id).get_json()

    assert "already graduated" in body["errors"][0]["message"]
