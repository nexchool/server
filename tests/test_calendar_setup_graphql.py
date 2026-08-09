"""Holidays and setup readiness over GraphQL.

Two things are pinned beyond the feature:

The calendar is an *optional* module, so unlike classes and subjects these
fields carry the feature gate. A school that takes the register on paper and
never bought the calendar should not be answerable about its holidays.

`setupStatus` returns a list of modules rather than a field per module. The
REST payload is a map keyed by module name, and a schema cannot express that
as a record without changing shape every time a module is added.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from graphql_api import GRAPHQL_PATH

HOLIDAYS = """
query H($first: Int!, $offset: Int, $where: HolidayFilter) {
  holidays(first: $first, offset: $offset, where: $where) {
    totalCount
    hasNextPage
    nodes {
      id name holidayType startDate endDate isRecurring recurringDayName
      academicYearName
    }
  }
}
"""

UPCOMING = "query U($limit: Int!) { upcomingHolidays(limit: $limit) { name startDate } }"
RECURRING = "query { recurringHolidays { name isRecurring recurringDayName } }"
SETUP = """
query {
  setupStatus {
    modules { key ready count optional blockers activeAcademicYearId }
    overall { ready isSetupComplete needsReconfirm regressedModules }
  }
}
"""


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


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


@pytest.fixture
def calendar(db_session, tenant, year):
    """Two dated closures and one weekly one."""
    from modules.academics.calendar.holidays import Holiday

    soon = date.today() + timedelta(days=7)
    rows = [
        Holiday(
            id=_new_id("h-"), tenant_id=tenant.id, name="Diwali",
            holiday_type="public", start_date=soon,
            end_date=soon + timedelta(days=4), academic_year_id=year.id,
        ),
        Holiday(
            id=_new_id("h-"), tenant_id=tenant.id, name="Founder's Day",
            holiday_type="school", start_date=soon + timedelta(days=30),
            end_date=soon + timedelta(days=30), academic_year_id=year.id,
        ),
        Holiday(
            id=_new_id("h-"), tenant_id=tenant.id, name="Sunday",
            holiday_type="weekly_off", is_recurring=True,
            recurring_day_of_week=6, academic_year_id=year.id,
        ),
    ]
    db_session.add_all(rows)
    db_session.flush()
    return rows


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


def _list(client, tenant, token, **overrides):
    variables = {"first": 50, "offset": None, "where": None}
    variables.update(overrides)
    return _ask(client, tenant, token, HOLIDAYS, **variables)


# ---------------------------------------------------------------------------
# The days a school is closed
# ---------------------------------------------------------------------------

def test_the_closures_a_school_has(client, db_session, tenant, calendar):
    _user, token = _staff_with(db_session, tenant, "holiday.read")

    body = _list(client, tenant, token)

    assert "errors" not in body, body
    page = body["data"]["holidays"]
    assert page["totalCount"] == 3
    assert {node["name"] for node in page["nodes"]} == {
        "Diwali", "Founder's Day", "Sunday",
    }


def test_a_weekly_closure_comes_last_and_carries_no_dates(
    client, db_session, tenant, calendar
):
    """Recurring rows sort last: a list of the year's closures is read by date,
    and 'every Sunday' has none."""
    _user, token = _staff_with(db_session, tenant, "holiday.read")

    nodes = _list(client, tenant, token)["data"]["holidays"]["nodes"]

    assert nodes[-1]["name"] == "Sunday"
    assert nodes[-1]["isRecurring"] is True
    assert nodes[-1]["startDate"] is None


def test_asking_for_dated_closures_only(client, db_session, tenant, calendar):
    _user, token = _staff_with(db_session, tenant, "holiday.read")

    body = _list(client, tenant, token, where={"includeRecurring": False})

    page = body["data"]["holidays"]
    assert page["totalCount"] == 2
    assert all(node["isRecurring"] is False for node in page["nodes"])


def test_searching_the_calendar(client, db_session, tenant, calendar):
    _user, token = _staff_with(db_session, tenant, "holiday.read")

    body = _list(client, tenant, token, where={"search": "diwali"})

    assert [n["name"] for n in body["data"]["holidays"]["nodes"]] == ["Diwali"]


def test_a_page_says_whether_another_follows(client, db_session, tenant, calendar):
    _user, token = _staff_with(db_session, tenant, "holiday.read")

    first = _list(client, tenant, token, first=2)
    assert first["data"]["holidays"]["hasNextPage"] is True

    rest = _list(client, tenant, token, first=2, offset=2)
    assert rest["data"]["holidays"]["hasNextPage"] is False
    assert len(rest["data"]["holidays"]["nodes"]) == 1


def test_a_negative_offset_is_refused(client, db_session, tenant, calendar):
    _user, token = _staff_with(db_session, tenant, "holiday.read")

    assert "VALIDATION_ERROR" in _codes(_list(client, tenant, token, offset=-1))


def test_what_is_coming_up_excludes_the_weekly_ones(
    client, db_session, tenant, calendar
):
    _user, token = _staff_with(db_session, tenant, "holiday.read")

    body = _ask(client, tenant, token, UPCOMING, limit=10)

    names = [node["name"] for node in body["data"]["upcomingHolidays"]]
    assert "Sunday" not in names
    assert "Diwali" in names


def test_the_weekly_closures_on_their_own(client, db_session, tenant, calendar):
    _user, token = _staff_with(db_session, tenant, "holiday.read")

    body = _ask(client, tenant, token, RECURRING)

    assert [n["name"] for n in body["data"]["recurringHolidays"]] == ["Sunday"]


def test_managing_the_calendar_carries_reading_it(
    client, db_session, tenant, calendar
):
    _user, token = _staff_with(db_session, tenant, "holiday.manage")

    assert "errors" not in _list(client, tenant, token)


def test_reading_the_calendar_needs_a_calendar_authority(
    client, db_session, tenant, calendar
):
    _user, token = _staff_with(db_session, tenant, "class.read")

    assert "FORBIDDEN" in _codes(_list(client, tenant, token))


def test_a_school_without_the_calendar_module_is_not_asked_about_it(
    client, db_session, tenant, calendar
):
    """Unlike classes, this one can be switched off — so the gate can fire."""
    tenant.feature_flags = {"academic_calendar": False}
    db_session.flush()
    _user, token = _staff_with(db_session, tenant, "holiday.read")

    assert "FEATURE_DISABLED" in _codes(_list(client, tenant, token))


# ---------------------------------------------------------------------------
# How far the school has got
# ---------------------------------------------------------------------------

def test_setup_readiness_is_a_list_of_modules(client, db_session, tenant, year):
    _user, token = _staff_with(db_session, tenant, "school_setup.read")

    body = _ask(client, tenant, token, SETUP)

    assert "errors" not in body, body
    status = body["data"]["setupStatus"]
    keys = {module["key"] for module in status["modules"]}
    assert {"units", "programmes", "grades", "academic_year", "classes",
            "subjects", "terms"} <= keys


def test_a_module_that_is_not_ready_says_what_is_missing(
    client, db_session, tenant
):
    _user, token = _staff_with(db_session, tenant, "school_setup.read")

    body = _ask(client, tenant, token, SETUP)

    units = next(m for m in body["data"]["setupStatus"]["modules"] if m["key"] == "units")
    assert units["ready"] is False
    assert units["blockers"] == ["add_at_least_one_unit"]


def test_terms_are_optional_and_say_so(client, db_session, tenant):
    _user, token = _staff_with(db_session, tenant, "school_setup.read")

    body = _ask(client, tenant, token, SETUP)

    terms = next(m for m in body["data"]["setupStatus"]["modules"] if m["key"] == "terms")
    assert terms["optional"] is True


def test_the_active_year_rides_on_the_academic_year_module(
    client, db_session, tenant, year
):
    _user, token = _staff_with(db_session, tenant, "school_setup.read")

    body = _ask(client, tenant, token, SETUP)

    module = next(
        m for m in body["data"]["setupStatus"]["modules"] if m["key"] == "academic_year"
    )
    assert module["activeAcademicYearId"] == year.id


def test_an_empty_school_is_not_ready(client, db_session, tenant):
    _user, token = _staff_with(db_session, tenant, "school_setup.read")

    body = _ask(client, tenant, token, SETUP)

    assert body["data"]["setupStatus"]["overall"]["ready"] is False


def test_reading_setup_needs_the_setup_authority(client, db_session, tenant):
    _user, token = _staff_with(db_session, tenant, "class.read")

    assert "FORBIDDEN" in _codes(_ask(client, tenant, token, SETUP))
