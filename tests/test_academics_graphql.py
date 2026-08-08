"""The structure a school is arranged into, over GraphQL.

Campuses and academic years are what almost every other read hangs off, and
they are the first Academics reads to move. What is pinned here is mostly the
decision *not* to bundle them: they answer to different permissions, and a
person holding one but not the other still gets what they may see.

A client that wants both still asks once and pays for one round-trip. The
saving is in the transport; the authorities stay separate because they are
separate.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from graphql_api import GRAPHQL_PATH

BOTH = """
query {
  campuses { id name code status }
  academicYears { id name startDate endDate isActive }
}
"""

CAMPUSES = "query { campuses { id name code status } }"
YEARS = """
query Y($activeOnly: Boolean) {
  academicYears(activeOnly: $activeOnly) { name isActive }
}
"""


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def structure(db_session, tenant):
    """Two campuses and three years, one of them the one in progress."""
    from modules.academics.academic_year.models import AcademicYear
    from modules.school_units.models import SchoolUnit

    campuses = [
        SchoolUnit(
            id=_new_id("su-"), tenant_id=tenant.id, name=name,
            code=f"{code}-{uuid.uuid4().hex[:6]}",
        )
        for name, code in (("Naranpura Campus", "NRP"), ("Maninagar Campus", "MNG"))
    ]
    db_session.add_all(campuses)

    years = []
    for name, start, active in (
        ("2024-2025", date(2024, 6, 1), False),
        ("2025-2026", date(2025, 6, 1), False),
        ("2026-2027", date(2026, 6, 1), True),
    ):
        years.append(
            AcademicYear(
                id=_new_id("ay-"), tenant_id=tenant.id, name=name,
                start_date=start, end_date=date(start.year + 1, 3, 31),
                is_active=active,
            )
        )
    db_session.add_all(years)
    db_session.flush()
    return campuses, years


def _staff_with(db_session, tenant, *permission_keys):
    from modules.auth.models import User
    from modules.auth.services import generate_access_token
    from modules.rbac.models import Permission, Role, RolePermission
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
    return [error["extensions"].get("code") for error in body.get("errors", [])]


# ---------------------------------------------------------------------------
# What a school is arranged into
# ---------------------------------------------------------------------------

def test_the_campuses_a_school_teaches_at(client, db_session, tenant, structure):
    _user, token = _staff_with(db_session, tenant, "school_unit.read")

    body = _ask(client, tenant, token, CAMPUSES)

    assert "errors" not in body, body
    names = {campus["name"] for campus in body["data"]["campuses"]}
    assert names == {"Naranpura Campus", "Maninagar Campus"}


def test_the_years_a_school_teaches_through(client, db_session, tenant, structure):
    _user, token = _staff_with(db_session, tenant, "class.read")

    body = _ask(client, tenant, token, YEARS)

    names = [year["name"] for year in body["data"]["academicYears"]]
    assert set(names) == {"2024-2025", "2025-2026", "2026-2027"}


def test_asking_for_only_the_year_in_progress(client, db_session, tenant, structure):
    _user, token = _staff_with(db_session, tenant, "class.read")

    body = _ask(client, tenant, token, YEARS, activeOnly=True)

    years = body["data"]["academicYears"]
    assert [year["name"] for year in years] == ["2026-2027"]
    assert years[0]["isActive"] is True


def test_both_are_answered_in_one_request(client, db_session, tenant, structure):
    """The round-trip saving, which is the part GraphQL is actually for."""
    _user, token = _staff_with(db_session, tenant, "school_unit.read")

    body = _ask(client, tenant, token, BOTH)

    assert "errors" not in body, body
    assert len(body["data"]["campuses"]) == 2
    assert len(body["data"]["academicYears"]) == 3


# ---------------------------------------------------------------------------
# Two reads, two authorities — deliberately not merged
# ---------------------------------------------------------------------------

def test_reading_campuses_needs_the_campus_authority(
    client, db_session, tenant, structure
):
    _user, token = _staff_with(db_session, tenant, "class.read")

    body = _ask(client, tenant, token, CAMPUSES)

    assert "FORBIDDEN" in _codes(body)


def test_anyone_signed_in_may_ask_which_year_it_is(
    client, db_session, tenant, structure
):
    """Deliberately unguarded, matching the REST route.

    A student looking at their own attendance and a teacher opening a register
    both need to know the year, and neither holds a class permission. Guarding
    this emptied the year picker for everyone but administrators — which is
    what happened when the field was first written by guessing the permission
    from the module rather than reading the route.
    """
    _user, token = _staff_with(db_session, tenant, "attendance.read.self")

    body = _ask(client, tenant, token, YEARS)

    assert "errors" not in body, body
    assert len(body["data"]["academicYears"]) == 3


def test_holding_one_authority_still_answers_that_half(
    client, db_session, tenant, structure, offerings
):
    """Why these are separate fields rather than one `academicScope`.

    The structure reads answer to different permissions. Bundled behind one
    guard, a person holding four of them would get a blank screen instead of
    the four they may see; bundled behind one field, one refusal would fail
    the whole response. Kept apart, a client asks for what it is allowed to
    and still pays for one round-trip.
    """
    _user, token = _staff_with(db_session, tenant, "grade.read")

    refused = _ask(client, tenant, token, CAMPUSES)
    answered = _ask(client, tenant, token, GRADES)

    assert "FORBIDDEN" in _codes(refused)
    assert "errors" not in answered, answered
    assert len(answered["data"]["grades"]) == 3


def test_another_schools_structure_is_not_visible(
    client, db_session, tenant, structure
):
    from core.models import Tenant
    from modules.school_units.models import SchoolUnit

    other = Tenant(
        id=_new_id("t-"), name="Other School",
        subdomain=f"other-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(other)
    db_session.flush()
    db_session.add(
        SchoolUnit(
            id=_new_id("su-"), tenant_id=other.id, name="Their Campus",
            code=f"THR-{uuid.uuid4().hex[:6]}",
        )
    )
    db_session.flush()

    _user, token = _staff_with(db_session, tenant, "school_unit.read")
    body = _ask(client, tenant, token, CAMPUSES)

    names = {campus["name"] for campus in body["data"]["campuses"]}
    assert "Their Campus" not in names


# ---------------------------------------------------------------------------
# Programmes, grades and mediums — three more lists, three more authorities
# ---------------------------------------------------------------------------

PROGRAMMES = "query { programmes { id name board code status medium } }"
GRADES = "query { grades { id name sequence } }"
MEDIUMS = """
query M($includeInactive: Boolean) {
  mediums(includeInactive: $includeInactive) { name code isActive }
}
"""


@pytest.fixture
def offerings(db_session, tenant):
    """Two boards, year-groups that sort wrong as text, and two mediums."""
    from modules.academic_programmes.models import AcademicProgramme
    from modules.grades.models import Grade
    from modules.mediums.models import Medium

    mediums = [
        Medium(
            id=_new_id("med-"), tenant_id=tenant.id, name=name,
            code=code, is_active=active,
        )
        for name, code, active in (
            ("English", "EN", True),
            ("Gujarati", "GU", True),
            ("Hindi", "HI", False),
        )
    ]
    db_session.add_all(mediums)

    programmes = [
        AcademicProgramme(
            id=_new_id("prog-"), tenant_id=tenant.id, name=name, board=board,
            code=f"{board}-{uuid.uuid4().hex[:6]}",
        )
        for name, board in (("CBSE English", "cbse"), ("GSEB Gujarati", "gseb"))
    ]
    db_session.add_all(programmes)

    # Named so a text sort would put Std 10 before Std 2.
    grades = [
        Grade(id=_new_id("g-"), tenant_id=tenant.id, name=name, sequence=seq)
        for name, seq in (("Std 2", 2), ("Std 10", 10), ("Std 1", 1))
    ]
    db_session.add_all(grades)
    db_session.flush()
    return programmes, grades, mediums


def test_the_programmes_a_school_offers(client, db_session, tenant, offerings):
    _user, token = _staff_with(db_session, tenant, "programme.read")

    body = _ask(client, tenant, token, PROGRAMMES)

    assert "errors" not in body, body
    boards = {p["board"] for p in body["data"]["programmes"]}
    assert boards == {"cbse", "gseb"}


def test_grades_come_back_in_teaching_order_not_alphabetical(
    client, db_session, tenant, offerings
):
    """Std 10 after Std 2. Sorted as text it comes first, which is the whole
    reason `sequence` exists."""
    _user, token = _staff_with(db_session, tenant, "grade.read")

    body = _ask(client, tenant, token, GRADES)

    assert [g["name"] for g in body["data"]["grades"]] == [
        "Std 1", "Std 2", "Std 10",
    ]


def test_the_mediums_a_school_currently_teaches_in(
    client, db_session, tenant, offerings
):
    _user, token = _staff_with(db_session, tenant, "school_setup.read")

    body = _ask(client, tenant, token, MEDIUMS)

    assert [m["name"] for m in body["data"]["mediums"]] == ["English", "Gujarati"]


def test_a_medium_the_school_has_stopped_offering_can_still_be_asked_for(
    client, db_session, tenant, offerings
):
    """Old records still name it, so it has to remain readable."""
    _user, token = _staff_with(db_session, tenant, "school_setup.read")

    body = _ask(client, tenant, token, MEDIUMS, includeInactive=True)

    names = [m["name"] for m in body["data"]["mediums"]]
    assert "Hindi" in names


@pytest.mark.parametrize(
    "query,key",
    [(PROGRAMMES, "programme.read"), (GRADES, "grade.read"), (MEDIUMS, "school_setup.read")],
)
def test_each_list_answers_to_its_own_authority(
    client, db_session, tenant, offerings, query, key
):
    """Holding every *other* structure permission is not enough for this one.

    This is the property that decided against one bundled `academicScope`
    field: five reads, five authorities.
    """
    others = {
        "school_unit.read", "class.read", "programme.read", "grade.read",
        "school_setup.read",
    } - {key}
    # `class_subject.manage` also opens mediums, so it is deliberately not in
    # the set of "every other structure permission".
    _user, token = _staff_with(db_session, tenant, *others)

    body = _ask(client, tenant, token, query)

    assert "FORBIDDEN" in _codes(body)


def test_whoever_assigns_subjects_to_a_class_may_read_the_mediums(
    client, db_session, tenant, offerings
):
    """The REST route accepts three keys, not two.

    A class-subject is taught in a medium, so the person assigning subjects
    needs the list — and gating the field on the school-setup keys alone took
    it away from them. Caught by an admin being refused on the live stack, not
    by any test here, which is the argument for reading the route's decorator
    rather than guessing from the module name.
    """
    _user, token = _staff_with(db_session, tenant, "class_subject.manage")

    body = _ask(client, tenant, token, MEDIUMS)

    assert "errors" not in body, body
    assert [m["name"] for m in body["data"]["mediums"]] == ["English", "Gujarati"]


# ---------------------------------------------------------------------------
# The subject catalogue
# ---------------------------------------------------------------------------

SUBJECTS = """
query S($includeInactive: Boolean) {
  subjects(includeInactive: $includeInactive) {
    id name code subjectType isActive
  }
}
"""


@pytest.fixture
def catalogue(db_session, tenant):
    from modules.subjects.models import Subject

    rows = [
        Subject(
            id=_new_id("sub-"), tenant_id=tenant.id, name=name,
            code=code, is_active=active,
        )
        for name, code, active in (
            ("Mathematics", "MATH", True),
            ("English", "ENG", True),
            ("Sanskrit", "SAN", False),
        )
    ]
    db_session.add_all(rows)
    db_session.flush()
    return rows


def test_the_subjects_a_school_teaches(client, db_session, tenant, catalogue):
    _user, token = _staff_with(db_session, tenant, "subject.read")

    body = _ask(client, tenant, token, SUBJECTS)

    assert "errors" not in body, body
    assert [s["name"] for s in body["data"]["subjects"]] == [
        "English", "Mathematics",
    ]


def test_a_subject_no_longer_offered_can_still_be_asked_for(
    client, db_session, tenant, catalogue
):
    """Old timetables and results still name it."""
    _user, token = _staff_with(db_session, tenant, "subject.read")

    body = _ask(client, tenant, token, SUBJECTS, includeInactive=True)

    assert "Sanskrit" in [s["name"] for s in body["data"]["subjects"]]


def test_managing_subjects_carries_reading_them(
    client, db_session, tenant, catalogue
):
    """`<resource>.manage` covers every action on that resource, so the field
    names the read alone and the whole rule is stated once."""
    _user, token = _staff_with(db_session, tenant, "subject.manage")

    body = _ask(client, tenant, token, SUBJECTS)

    assert "errors" not in body, body
    assert len(body["data"]["subjects"]) == 2


def test_the_catalogue_needs_the_subject_authority(
    client, db_session, tenant, catalogue
):
    _user, token = _staff_with(db_session, tenant, "class.read", "grade.read")

    body = _ask(client, tenant, token, SUBJECTS)

    assert "FORBIDDEN" in _codes(body)


# ---------------------------------------------------------------------------
# The catalogue an administrator manages — subject + where it is taught
# ---------------------------------------------------------------------------

CATALOGUE = """
query C(
  $first: Int!, $offset: Int, $orderBy: SubjectOrder!,
  $direction: SubjectOrderDirection!, $where: SubjectFilter
) {
  subjectCatalogue(
    first: $first, offset: $offset, orderBy: $orderBy,
    direction: $direction, where: $where
  ) {
    totalCount
    hasNextPage
    nodes {
      id name code subjectType isActive
      classes {
        classSubjectId classId className gradeName
        programmeId programmeName weeklyPeriods isMandatory
      }
      programmes { id name }
    }
  }
}
"""


def _catalogue(client, tenant, token, **overrides):
    variables = {
        "first": 20, "offset": None, "orderBy": "NAME", "direction": "ASC",
        "where": None,
    }
    variables.update(overrides)
    return _ask(client, tenant, token, CATALOGUE, **variables)


@pytest.fixture
def taught_somewhere(db_session, tenant, structure, catalogue):
    """Mathematics taught in one class; the rest assigned nowhere."""
    from modules.academic_programmes.models import AcademicProgramme
    from modules.classes.models import Class, ClassSubject
    from modules.grades.models import Grade

    _campuses, years = structure
    programme = AcademicProgramme(
        id=_new_id("ap-"), tenant_id=tenant.id, name="GSEB Gujarati",
        board="GSEB", code=f"GG-{uuid.uuid4().hex[:6]}",
    )
    grade = Grade(id=_new_id("g-"), tenant_id=tenant.id, name="Grade 5", sequence=5)
    db_session.add_all([programme, grade])
    db_session.flush()

    klass = Class(
        id=_new_id("c-"), tenant_id=tenant.id, name="5", section="A",
        academic_year_id=years[-1].id, programme_id=programme.id,
        grade_id=grade.id,
    )
    db_session.add(klass)
    db_session.flush()

    maths = next(s for s in catalogue if s.name == "Mathematics")
    class_subject = ClassSubject(
        id=_new_id("cs-"), tenant_id=tenant.id, class_id=klass.id,
        subject_id=maths.id, weekly_periods=6, is_mandatory=True,
        status="active",
    )
    db_session.add(class_subject)
    db_session.flush()
    return {"class": klass, "programme": programme, "class_subject": class_subject}


def test_the_catalogue_says_where_each_subject_is_taught(
    client, db_session, tenant, taught_somewhere
):
    _user, token = _staff_with(db_session, tenant, "subject.read")

    body = _catalogue(client, tenant, token)

    assert "errors" not in body, body
    by_name = {s["name"]: s for s in body["data"]["subjectCatalogue"]["nodes"]}
    taught = by_name["Mathematics"]["classes"]
    assert len(taught) == 1
    assert taught[0]["classId"] == taught_somewhere["class"].id
    assert taught[0]["gradeName"] == "Grade 5"
    assert taught[0]["weeklyPeriods"] == 6
    assert by_name["Mathematics"]["programmes"] == [
        {"id": taught_somewhere["programme"].id, "name": "GSEB Gujarati"}
    ]


def test_a_subject_taught_nowhere_says_so_rather_than_being_hidden(
    client, db_session, tenant, taught_somewhere
):
    _user, token = _staff_with(db_session, tenant, "subject.read")

    body = _catalogue(client, tenant, token)

    by_name = {s["name"]: s for s in body["data"]["subjectCatalogue"]["nodes"]}
    assert by_name["English"]["classes"] == []
    assert by_name["English"]["programmes"] == []


def test_a_class_that_stopped_taking_a_subject_is_not_listed(
    client, db_session, tenant, taught_somewhere
):
    taught_somewhere["class_subject"].status = "inactive"
    db_session.flush()
    _user, token = _staff_with(db_session, tenant, "subject.read")

    body = _catalogue(client, tenant, token)

    by_name = {s["name"]: s for s in body["data"]["subjectCatalogue"]["nodes"]}
    assert by_name["Mathematics"]["classes"] == []


def test_the_catalogue_pages(client, db_session, tenant, catalogue):
    _user, token = _staff_with(db_session, tenant, "subject.read")

    first = _catalogue(client, tenant, token, first=1)
    assert first["data"]["subjectCatalogue"]["hasNextPage"] is True
    assert first["data"]["subjectCatalogue"]["totalCount"] == 2

    second = _catalogue(client, tenant, token, first=1, offset=1)
    assert second["data"]["subjectCatalogue"]["hasNextPage"] is False
    assert (
        first["data"]["subjectCatalogue"]["nodes"][0]["id"]
        != second["data"]["subjectCatalogue"]["nodes"][0]["id"]
    )


def test_the_total_describes_the_search_not_the_catalogue(
    client, db_session, tenant, catalogue
):
    _user, token = _staff_with(db_session, tenant, "subject.read")

    body = _catalogue(client, tenant, token, where={"search": "math"})

    page = body["data"]["subjectCatalogue"]
    assert page["totalCount"] == 1
    assert [s["name"] for s in page["nodes"]] == ["Mathematics"]


def test_the_catalogue_can_be_asked_for_what_is_no_longer_offered(
    client, db_session, tenant, catalogue
):
    _user, token = _staff_with(db_session, tenant, "subject.read")

    body = _catalogue(client, tenant, token, where={"includeInactive": True})

    names = [s["name"] for s in body["data"]["subjectCatalogue"]["nodes"]]
    assert "Sanskrit" in names


def test_sorting_the_catalogue_by_code_backwards(
    client, db_session, tenant, catalogue
):
    _user, token = _staff_with(db_session, tenant, "subject.read")

    body = _catalogue(client, tenant, token, orderBy="CODE", direction="DESC")

    assert [s["code"] for s in body["data"]["subjectCatalogue"]["nodes"]] == [
        "MATH", "ENG",
    ]


def test_a_subject_type_the_schema_does_not_know_is_refused(
    client, db_session, tenant, catalogue
):
    """The enum does what the REST route's hand-written check used to."""
    _user, token = _staff_with(db_session, tenant, "subject.read")

    body = _catalogue(client, tenant, token, where={"subjectType": "WIZARDRY"})

    assert "errors" in body, body


def test_a_negative_offset_is_refused_rather_than_resolved(
    client, db_session, tenant, catalogue
):
    _user, token = _staff_with(db_session, tenant, "subject.read")

    body = _catalogue(client, tenant, token, offset=-1)

    assert "VALIDATION_ERROR" in _codes(body)


def test_reading_the_catalogue_needs_the_subject_authority(
    client, db_session, tenant, catalogue
):
    _user, token = _staff_with(db_session, tenant, "class.read")

    assert "FORBIDDEN" in _codes(_catalogue(client, tenant, token))
