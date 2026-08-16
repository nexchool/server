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
        # Real dates, not strings: `AcademicYear.to_dict()` calls .isoformat()
        # on them, and the calendar payload nests that serializer.
        start_date=date(2026, 6, 1), end_date=date(2027, 3, 31), is_active=True,
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


# ---------------------------------------------------------------------------
# The calendar document, its days and what is planned in it
# ---------------------------------------------------------------------------

CALENDAR = """
query C($yearId: ID!) {
  academicCalendar(academicYearId: $yearId) {
    id academicYearId academicYearName status currentStep totalSteps
  }
}
"""

SUMMARY = """
query S($calendarId: ID!) {
  calendarSummary(calendarId: $calendarId) {
    totalDays workingDays publicHolidayDays weeklyHolidayDays
    eventCount examWindowCount eventsByType { eventType count }
    weeklyHolidaysConfig { days secondSaturday fourthSaturday }
  }
}
"""

DAYS = """
query D($calendarId: ID!) {
  calendarDays(calendarId: $calendarId) { date dayType hasEvent hasExam holidays { id name holidayType } }
}
"""

EVENTS = (
    "query E($yearId: ID!) { calendarEvents(academicYearId: $yearId) "
    "{ name eventType eventDate status appliesTo } }"
)
WINDOWS = (
    "query W($yearId: ID!) { examWindows(academicYearId: $yearId) "
    "{ name examType status startDate endDate durationDays applicableClassIds description } }"
)
TERMS = "query T($yearId: ID) { academicTerms(academicYearId: $yearId) { name sequence startDate isActive } }"


@pytest.fixture
def calendar_doc(db_session, tenant, year):
    """Built directly rather than through `get_or_create_calendar`.

    That service commits, and a commit inside the savepoint-bound test session
    releases the savepoint the fixture rolls back — the row lands but the
    session it lands in is no longer the one the request reads.
    """
    from modules.academics.calendar.models import AcademicCalendar
    from modules.academics.calendar.services import default_weekly_holidays_config

    calendar = AcademicCalendar(
        id=_new_id("cal-"), tenant_id=tenant.id, academic_year_id=year.id,
        status="draft", current_step=1,
        weekly_holidays_config=default_weekly_holidays_config(),
    )
    db_session.add(calendar)
    db_session.flush()
    return calendar


def test_a_school_without_a_calendar_gets_null_not_an_error(
    client, db_session, tenant, year
):
    _user, token = _staff_with(db_session, tenant, "academic_calendar.read")

    body = _ask(client, tenant, token, CALENDAR, yearId=year.id)

    assert "errors" not in body, body
    assert body["data"]["academicCalendar"] is None


def test_the_calendar_a_school_is_working_on(
    client, db_session, tenant, year, calendar_doc
):
    _user, token = _staff_with(db_session, tenant, "academic_calendar.read")

    body = _ask(client, tenant, token, CALENDAR, yearId=year.id)

    calendar = body["data"]["academicCalendar"]
    assert calendar["academicYearId"] == year.id
    assert calendar["status"] == "draft"


def test_the_year_adds_up(client, db_session, tenant, year, calendar_doc, calendar):
    _user, token = _staff_with(db_session, tenant, "academic_calendar.read")

    body = _ask(client, tenant, token, SUMMARY, calendarId=calendar_doc.id)

    summary = body["data"]["calendarSummary"]
    assert summary["totalDays"] > 0
    assert summary["workingDays"] <= summary["totalDays"]


def test_events_by_type_is_a_list_not_a_map(
    client, db_session, tenant, year, calendar_doc
):
    """The types are the school's to invent, so a schema cannot grow a field
    for each one."""
    _user, token = _staff_with(db_session, tenant, "academic_calendar.read")

    body = _ask(client, tenant, token, SUMMARY, calendarId=calendar_doc.id)

    assert isinstance(body["data"]["calendarSummary"]["eventsByType"], list)


def test_every_day_of_the_year_is_classified(
    client, db_session, tenant, year, calendar_doc, calendar
):
    _user, token = _staff_with(db_session, tenant, "academic_calendar.read")

    body = _ask(client, tenant, token, DAYS, calendarId=calendar_doc.id)

    days = body["data"]["calendarDays"]
    assert len(days) > 300, "a year of days"
    assert all(day["dayType"] for day in days)


def test_a_calendar_nobody_has_is_not_found(client, db_session, tenant, year):
    _user, token = _staff_with(db_session, tenant, "academic_calendar.read")

    body = _ask(client, tenant, token, SUMMARY, calendarId=_new_id("cal-"))

    assert "errors" not in body, body
    assert body["data"]["calendarSummary"] is None


def test_what_the_school_has_planned(client, db_session, tenant, year):
    _user, token = _staff_with(db_session, tenant, "academic_calendar.read")

    body = _ask(client, tenant, token, EVENTS, yearId=year.id)

    assert "errors" not in body, body
    assert isinstance(body["data"]["calendarEvents"], list)


def test_the_exam_windows(client, db_session, tenant, year):
    _user, token = _staff_with(db_session, tenant, "academic_calendar.read")

    body = _ask(client, tenant, token, WINDOWS, yearId=year.id)

    assert "errors" not in body, body
    assert isinstance(body["data"]["examWindows"], list)


def test_an_exam_window_says_which_classes_sit_it(client, db_session, tenant, year):
    """The count of classes is what the calendar prints next to a window, so
    the field has to arrive — and arrive as a list even when it is empty."""
    from modules.academics.calendar.models import ExamWindow

    db_session.add(
        ExamWindow(
            id=_new_id("exam-"), tenant_id=tenant.id, academic_year_id=year.id,
            name="Mid Term", exam_type="mid_term", status="active",
            start_date=date(2026, 9, 1), end_date=date(2026, 9, 8),
            applicable_class_ids=["class-a", "class-b"], description="Half-yearly",
        )
    )
    db_session.flush()
    _user, token = _staff_with(db_session, tenant, "academic_calendar.read")

    body = _ask(client, tenant, token, WINDOWS, yearId=year.id)

    assert "errors" not in body, body
    window = body["data"]["examWindows"][0]
    assert window["applicableClassIds"] == ["class-a", "class-b"]
    assert window["status"] == "active"
    assert window["durationDays"] == 8
    assert window["description"] == "Half-yearly"


def test_a_window_the_whole_school_sits_carries_an_empty_list_not_null(
    client, db_session, tenant, year
):
    """Null here is what broke the calendar page: the client counts this."""
    from modules.academics.calendar.models import ExamWindow

    db_session.add(
        ExamWindow(
            id=_new_id("exam-"), tenant_id=tenant.id, academic_year_id=year.id,
            name="Final", exam_type="final", status="active",
            start_date=date(2027, 3, 1), end_date=date(2027, 3, 10),
            applicable_class_ids=None,
        )
    )
    db_session.flush()
    _user, token = _staff_with(db_session, tenant, "academic_calendar.read")

    body = _ask(client, tenant, token, WINDOWS, yearId=year.id)

    assert body["data"]["examWindows"][0]["applicableClassIds"] == []


def test_an_event_happens_on_its_own_date(client, db_session, tenant, year):
    """An event has one date. The schema used to offer a start and an end that
    the model never filled, so every event read back undated."""
    from modules.academics.calendar.models import SchoolEvent

    db_session.add(
        SchoolEvent(
            id=_new_id("evt-"), tenant_id=tenant.id, academic_year_id=year.id,
            name="Sports Day", event_type="activity", status="active",
            event_date=date(2026, 12, 12), applies_to="entire_school",
        )
    )
    db_session.flush()
    _user, token = _staff_with(db_session, tenant, "academic_calendar.read")

    body = _ask(client, tenant, token, EVENTS, yearId=year.id)

    assert "errors" not in body, body
    event = body["data"]["calendarEvents"][0]
    assert event["eventDate"] == "2026-12-12"
    assert event["status"] == "active"
    assert event["appliesTo"] == "entire_school"


def test_reading_the_calendar_document_needs_the_calendar_authority(
    client, db_session, tenant, year
):
    _user, token = _staff_with(db_session, tenant, "class.read")

    assert "FORBIDDEN" in _codes(_ask(client, tenant, token, CALENDAR, yearId=year.id))


# ---------------------------------------------------------------------------
# Terms answer to their own authority
# ---------------------------------------------------------------------------

@pytest.fixture
def terms(db_session, tenant, year):
    from modules.academics.backbone.models import AcademicTerm

    rows = [
        AcademicTerm(
            id=_new_id("term-"), tenant_id=tenant.id, academic_year_id=year.id,
            name=name, sequence=seq, is_active=True,
            start_date=date(2026, 6, 1) if seq == 1 else date(2026, 11, 1),
            end_date=date(2026, 10, 31) if seq == 1 else date(2027, 3, 31),
        )
        for name, seq in (("Term 2", 2), ("Term 1", 1))
    ]
    db_session.add_all(rows)
    db_session.flush()
    return rows


def test_terms_come_back_in_teaching_order(client, db_session, tenant, year, terms):
    _user, token = _staff_with(db_session, tenant, "academic_term.read")

    body = _ask(client, tenant, token, TERMS, yearId=year.id)

    assert "errors" not in body, body
    assert [t["name"] for t in body["data"]["academicTerms"]] == ["Term 1", "Term 2"]


def test_terms_do_not_answer_to_the_calendar_authority(
    client, db_session, tenant, year, terms
):
    """A person may hold one and not the other; the routes ask for different
    keys and the fields keep that."""
    _user, token = _staff_with(db_session, tenant, "academic_calendar.manage")

    assert "FORBIDDEN" in _codes(_ask(client, tenant, token, TERMS, yearId=year.id))


# ---------------------------------------------------------------------------
# A class's week
# ---------------------------------------------------------------------------

VERSIONS = """
query V($classId: ID!, $includeDrafts: Boolean!) {
  timetableVersions(classId: $classId, includeDrafts: $includeDrafts) {
    id classId label status
  }
}
"""

TIMETABLE = """
query T($classId: ID!) {
  timetable(classId: $classId) {
    editable
    workingDays
    version { id status label }
    bellSchedule { id name lessonPeriods { id label } }
    entries { id dayOfWeek periodLabel subjectName conflictFlags }
  }
}
"""


@pytest.fixture
def a_class(db_session, tenant, year):
    from modules.classes.models import Class

    row = Class(
        id=_new_id("c-"), tenant_id=tenant.id, name="Grade 5", section="A",
        academic_year_id=year.id,
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_a_class_with_no_timetable_yet(client, db_session, tenant, a_class):
    _user, token = _staff_with(db_session, tenant, "timetable.read")

    body = _ask(
        client, tenant, token, VERSIONS, classId=a_class.id, includeDrafts=True
    )

    assert "errors" not in body, body
    assert body["data"]["timetableVersions"] == []


def test_reading_a_timetable_needs_a_timetable_authority(
    client, db_session, tenant, a_class
):
    _user, token = _staff_with(db_session, tenant, "class.read")

    body = _ask(
        client, tenant, token, VERSIONS, classId=a_class.id, includeDrafts=True
    )

    assert "FORBIDDEN" in _codes(body)


def test_a_school_without_the_timetable_module_is_not_asked_about_it(
    client, db_session, tenant, a_class
):
    tenant.feature_flags = {"timetable": False}
    db_session.flush()
    _user, token = _staff_with(db_session, tenant, "timetable.read")

    body = _ask(
        client, tenant, token, VERSIONS, classId=a_class.id, includeDrafts=True
    )

    assert "FEATURE_DISABLED" in _codes(body)


def test_a_reader_is_served_the_readers_view(client, db_session, tenant, a_class):
    """`timetable.read` without `timetable.manage` gets reader mode, exactly
    as the REST route decides it. The guard says whether the field runs; the
    resolver decides how much."""
    _user, token = _staff_with(db_session, tenant, "timetable.read")

    body = _ask(client, tenant, token, TIMETABLE, classId=a_class.id)

    assert "errors" not in body, body
    assert body["data"]["timetable"]["editable"] is False


def test_an_editor_is_told_it_is_editable(client, db_session, tenant, a_class):
    _user, token = _staff_with(db_session, tenant, "timetable.manage")

    body = _ask(client, tenant, token, TIMETABLE, classId=a_class.id)

    assert "errors" not in body, body
    assert isinstance(body["data"]["timetable"]["entries"], list)
