"""Changing the structure a school is arranged into, over GraphQL.

Four catalogues everything else refers to — campuses, programmes, grades and
mediums. What is pinned here is not that a grade can be added; the services
have their own tests. It is that each catalogue keeps its own authority, that a
refusal arrives as a code rather than prose, and that a partial change leaves
alone what it does not mention.

The authorities are separate on purpose. A school may let somebody name a new
grade without letting them open a campus, and one "structure.manage" key would
make that impossible to express.
"""

from __future__ import annotations

import uuid

import pytest

from graphql_api import GRAPHQL_PATH

ADD_GRADE = """
mutation A($input: GradeInput!) { addGrade(input: $input) { id name sequence } }
"""
UPDATE_GRADE = """
mutation U($id: ID!, $changes: GradeChanges!) {
  updateGrade(id: $id, changes: $changes) { id name sequence }
}
"""
REMOVE_GRADE = "mutation R($id: ID!) { removeGrade(id: $id) }"
ADD_CAMPUS = """
mutation A($input: CampusInput!) {
  addCampus(input: $input) { id name code grNumberScheme }
}
"""
UPDATE_CAMPUS = """
mutation U($id: ID!, $changes: CampusChanges!) {
  updateCampus(id: $id, changes: $changes) { id name code grNumberScheme }
}
"""
ADD_MEDIUM = "mutation A($input: MediumInput!) { addMedium(input: $input) { id name } }"


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


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
    return [e["extensions"].get("code") for e in body.get("errors", [])]


@pytest.fixture
def keeper(db_session, tenant):
    """Somebody who may change every one of the four catalogues."""
    return _staff_with(
        db_session, tenant,
        "grade.manage", "school_unit.manage", "programme.manage",
        "school_setup.manage",
    )


# ---------------------------------------------------------------------------
# Each catalogue keeps its own authority
# ---------------------------------------------------------------------------

def test_managing_grades_does_not_let_you_open_a_campus(db_session, tenant, client):
    """The reason these are four permissions and not one."""
    _user, token = _staff_with(db_session, tenant, "grade.manage")

    body = _ask(
        client, tenant, token, ADD_CAMPUS,
        input={"name": "North Campus", "code": f"N-{uuid.uuid4().hex[:5]}"},
    )
    assert "FORBIDDEN" in _codes(body)


def test_managing_campuses_does_not_let_you_add_a_grade(db_session, tenant, client):
    _user, token = _staff_with(db_session, tenant, "school_unit.manage")

    body = _ask(client, tenant, token, ADD_GRADE, input={"name": "9"})
    assert "FORBIDDEN" in _codes(body)


def test_a_medium_answers_to_setup_or_to_class_subjects(db_session, tenant, client):
    """Matching the route it replaces, which accepted either.

    Whoever assigns subjects to a class works in a medium, so that authority
    reaches this too.
    """
    _user, token = _staff_with(db_session, tenant, "class_subject.manage")

    body = _ask(client, tenant, token, ADD_MEDIUM, input={"name": "Hindi"})
    assert body.get("errors") is None, body
    assert body["data"]["addMedium"]["name"] == "Hindi"


# ---------------------------------------------------------------------------
# The catalogues themselves
# ---------------------------------------------------------------------------

def test_a_grade_can_be_added_and_read_back(client, tenant, keeper):
    _user, token = keeper

    body = _ask(client, tenant, token, ADD_GRADE, input={"name": "11", "sequence": 11})
    assert body.get("errors") is None, body
    added = body["data"]["addGrade"]
    assert added["name"] == "11"
    assert added["sequence"] == 11


def test_changing_one_field_leaves_the_others_alone(client, tenant, keeper):
    """A partial change must not blank what it does not mention.

    Every field an input object does not carry arrives as None, so a mutation
    that passed the whole input through would clear the sequence whenever a
    caller renamed a grade.
    """
    _user, token = keeper
    added = _ask(
        client, tenant, token, ADD_GRADE, input={"name": "7", "sequence": 7}
    )["data"]["addGrade"]

    body = _ask(
        client, tenant, token, UPDATE_GRADE, id=added["id"], changes={"name": "Std 7"}
    )
    assert body.get("errors") is None, body
    changed = body["data"]["updateGrade"]
    assert changed["name"] == "Std 7"
    assert changed["sequence"] == 7, "the sequence was cleared by a rename"


def test_removing_a_grade_nothing_uses_succeeds(client, tenant, keeper):
    _user, token = keeper
    added = _ask(client, tenant, token, ADD_GRADE, input={"name": "12"})["data"]["addGrade"]

    body = _ask(client, tenant, token, REMOVE_GRADE, id=added["id"])
    assert body.get("errors") is None, body
    assert body["data"]["removeGrade"] is True


def test_a_campus_keeps_its_gr_number_scheme_through_create_and_change(
    client, tenant, keeper
):
    """The pattern a campus mints admission numbers from.

    It survived a rename to camelCase on the way through the schema and back,
    which is the part worth pinning — the value carries braces and a dash and
    would look plausible if it silently arrived as null.
    """
    _user, token = keeper
    campus = _ask(
        client, tenant, token, ADD_CAMPUS,
        input={
            "name": "North Campus", "code": f"N-{uuid.uuid4().hex[:5]}",
            "grNumberScheme": "NC-{SEQ}",
        },
    )["data"]["addCampus"]
    assert campus["grNumberScheme"] == "NC-{SEQ}"

    changed = _ask(
        client, tenant, token, UPDATE_CAMPUS,
        id=campus["id"], changes={"grNumberScheme": "SC-{SEQ}"},
    )
    assert changed.get("errors") is None, changed
    assert changed["data"]["updateCampus"]["grNumberScheme"] == "SC-{SEQ}"


def test_a_blank_string_clears_a_field_too(client, tenant, keeper):
    """What the route accepted, kept.

    The form sends null today, but a blank is the same intent and the service
    already treats it that way; nothing in the move should have narrowed it.
    """
    _user, token = keeper
    campus = _ask(
        client, tenant, token, ADD_CAMPUS,
        input={
            "name": "East Campus", "code": f"E-{uuid.uuid4().hex[:5]}",
            "grNumberScheme": "EC-{SEQ}",
        },
    )["data"]["addCampus"]

    changed = _ask(
        client, tenant, token, UPDATE_CAMPUS,
        id=campus["id"], changes={"grNumberScheme": ""},
    )
    assert changed.get("errors") is None, changed
    assert changed["data"]["updateCampus"]["grNumberScheme"] is None


def test_removing_a_campus_nothing_uses_succeeds(client, tenant, keeper):
    _user, token = keeper
    campus = _ask(
        client, tenant, token, ADD_CAMPUS,
        input={"name": "Spare", "code": f"S-{uuid.uuid4().hex[:5]}"},
    )["data"]["addCampus"]

    body = _ask(
        client, tenant, token, "mutation R($id: ID!) { removeCampus(id: $id) }",
        id=campus["id"],
    )
    assert body.get("errors") is None, body
    assert body["data"]["removeCampus"] is True


def test_an_explicit_null_clears_a_field_and_an_omission_does_not(
    client, tenant, keeper
):
    """The two meanings of "no value", which a partial update must keep apart.

    The branch form sends null for a box the user emptied, so null has to reach
    the service and clear the column — while a field the caller never mentioned
    must survive untouched. Both look like None to Python, which is why the
    inputs default to UNSET rather than None.
    """
    _user, token = keeper
    campus = _ask(
        client, tenant, token, ADD_CAMPUS,
        input={
            "name": "Riverside", "code": f"R-{uuid.uuid4().hex[:5]}",
            "grNumberScheme": "RS-{SEQ}", "phone": "0261-000000",
        },
    )["data"]["addCampus"]

    changed = _ask(
        client, tenant, token,
        """
        mutation U($id: ID!, $changes: CampusChanges!) {
          updateCampus(id: $id, changes: $changes) { id phone grNumberScheme }
        }
        """,
        id=campus["id"], changes={"grNumberScheme": None},
    )
    assert changed.get("errors") is None, changed
    campus_now = changed["data"]["updateCampus"]
    assert campus_now["grNumberScheme"] is None, "an explicit null did not clear it"
    assert campus_now["phone"] == "0261-000000", "an untouched field was cleared"


# ---------------------------------------------------------------------------
# Refusals arrive as codes
# ---------------------------------------------------------------------------

def test_removing_a_grade_a_class_is_in_is_refused(
    client, tenant, db_session, keeper
):
    """The catalogue serves the classes; it cannot be emptied from under them."""
    from datetime import date

    from modules.academics.academic_year.models import AcademicYear
    from modules.classes.models import Class

    _user, token = keeper
    added = _ask(client, tenant, token, ADD_GRADE, input={"name": "6"})["data"]["addGrade"]

    year = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name=f"AY-{uuid.uuid4().hex[:6]}",
        start_date=date(2026, 6, 1), end_date=date(2027, 3, 31), is_active=True,
    )
    db_session.add(year)
    db_session.flush()
    db_session.add(
        Class(
            id=_new_id("c-"), tenant_id=tenant.id, name="", section="A",
            grade_id=added["id"], academic_year_id=year.id,
        )
    )
    db_session.flush()

    body = _ask(client, tenant, token, REMOVE_GRADE, id=added["id"])
    assert "CONFLICT" in _codes(body), body


def test_removing_a_campus_that_still_teaches_classes_is_refused(
    client, tenant, db_session, keeper
):
    """Same refusal as a grade's, worded completely differently by its service.

    Which is the point of covering both: the two messages share no phrase, so a
    classifier tuned to one of them silently reports the other as bad input.
    """
    from datetime import date

    from modules.academics.academic_year.models import AcademicYear
    from modules.classes.models import Class

    _user, token = keeper
    campus = _ask(
        client, tenant, token, ADD_CAMPUS,
        input={"name": "North", "code": f"N-{uuid.uuid4().hex[:5]}"},
    )["data"]["addCampus"]

    year = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name=f"AY-{uuid.uuid4().hex[:6]}",
        start_date=date(2026, 6, 1), end_date=date(2027, 3, 31), is_active=True,
    )
    db_session.add(year)
    db_session.flush()
    db_session.add(
        Class(
            id=_new_id("c-"), tenant_id=tenant.id, name="", section="A",
            school_unit_id=campus["id"], academic_year_id=year.id,
        )
    )
    db_session.flush()

    body = _ask(
        client, tenant, token, "mutation R($id: ID!) { removeCampus(id: $id) }",
        id=campus["id"],
    )
    assert "CONFLICT" in _codes(body), body


def test_removing_a_medium_a_programme_is_taught_in_is_refused(
    client, tenant, db_session, keeper
):
    """The guard the other three catalogues always had, and this one did not.

    A programme is checked as well as a class on purpose: a school that stops
    offering Gujarati still has programmes declared in it, and deleting the
    medium out from under them leaves a reference to a row nothing can read.
    """
    from modules.academic_programmes.models import AcademicProgramme

    _user, token = keeper
    medium = _ask(
        client, tenant, token, ADD_MEDIUM, input={"name": f"Marathi-{uuid.uuid4().hex[:5]}"}
    )["data"]["addMedium"]

    db_session.add(
        AcademicProgramme(
            id=_new_id("ap-"), tenant_id=tenant.id, name="State Board",
            board="GSEB", code=f"GS-{uuid.uuid4().hex[:5]}", medium_id=medium["id"],
        )
    )
    db_session.flush()

    body = _ask(
        client, tenant, token, "mutation R($id: ID!) { removeMedium(id: $id) }",
        id=medium["id"],
    )
    assert "CONFLICT" in _codes(body), body


def test_removing_a_medium_nothing_teaches_in_succeeds(client, tenant, keeper):
    _user, token = keeper
    medium = _ask(
        client, tenant, token, ADD_MEDIUM, input={"name": f"Spare-{uuid.uuid4().hex[:5]}"}
    )["data"]["addMedium"]

    body = _ask(
        client, tenant, token, "mutation R($id: ID!) { removeMedium(id: $id) }",
        id=medium["id"],
    )
    assert body.get("errors") is None, body
    assert body["data"]["removeMedium"] is True


def test_removing_something_that_is_not_there_is_not_found(client, tenant, keeper):
    _user, token = keeper

    body = _ask(client, tenant, token, REMOVE_GRADE, id="gr-nope")
    assert "NOT_FOUND" in _codes(body), body


def test_a_duplicate_campus_code_is_a_conflict(client, tenant, keeper):
    _user, token = keeper
    code = f"C-{uuid.uuid4().hex[:5]}"

    first = _ask(client, tenant, token, ADD_CAMPUS, input={"name": "Main", "code": code})
    assert first.get("errors") is None, first

    again = _ask(client, tenant, token, ADD_CAMPUS, input={"name": "Second", "code": code})
    assert "CONFLICT" in _codes(again), again
