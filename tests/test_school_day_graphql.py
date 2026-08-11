"""What a class is taught, by whom, and to what clock.

Three fields that look neighbourly and are not. `classSubjects` and
`subjectTeachers` share their authorities and differ only in feature — a
school with no timetable still has subjects on its classes — and the bell
schedules answer to a different authority again. Each test below pins one of
those seams, because a single shared guard would have swallowed all three.
"""

from __future__ import annotations

import uuid
from datetime import date, time

import pytest

from graphql_api import GRAPHQL_PATH

CLASS_SUBJECTS = """
query CS($classId: ID!) {
  classSubjects(classId: $classId) {
    id classId subjectId subjectName subjectCode weeklyPeriods
    isMandatory isElectiveBucket status
  }
}
"""

SUBJECT_TEACHERS = """
query ST($classId: ID!) {
  subjectTeachers(classId: $classId) {
    id classSubjectId teacherId teacherName employeeId role isActive
  }
}
"""

BELLS = """
query B {
  bellSchedules {
    defaultBellScheduleId
    items { id name isDefault dayOfWeek validFrom validTo }
  }
}
"""

BELL = """
query BD($id: ID!) {
  bellSchedule(id: $id) {
    id name isDefault timetableVersionsLinked
    periods { id periodNumber periodKind label startsAt endsAt sortOrder }
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

    row = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name="2026-2027",
        start_date=date(2026, 6, 1), end_date=date(2027, 3, 31), is_active=True,
    )
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def taught_class(db_session, tenant, year):
    """A class with one subject on it."""
    from modules.classes.models import Class, ClassSubject
    from modules.subjects.models import Subject

    klass = Class(
        id=_new_id("c-"), tenant_id=tenant.id, name="Grade 5", section="A",
        academic_year_id=year.id,
    )
    subject = Subject(
        id=_new_id("sub-"), tenant_id=tenant.id, name="Mathematics", code="MATH"
    )
    db_session.add_all([klass, subject])
    db_session.flush()
    offering = ClassSubject(
        id=_new_id("cs-"), tenant_id=tenant.id, class_id=klass.id,
        subject_id=subject.id, weekly_periods=6, is_mandatory=True, status="active",
    )
    db_session.add(offering)
    db_session.flush()
    return klass, subject, offering


@pytest.fixture
def bell(db_session, tenant, year):
    from modules.academics.backbone.models import BellSchedule, BellSchedulePeriod

    schedule = BellSchedule(
        id=_new_id("bs-"), tenant_id=tenant.id, name="Regular Day",
        academic_year_id=year.id, is_default=True,
    )
    db_session.add(schedule)
    db_session.flush()
    db_session.add(
        BellSchedulePeriod(
            id=_new_id("bp-"), tenant_id=tenant.id, bell_schedule_id=schedule.id,
            period_number=1, period_kind="lesson", label="Period 1",
            starts_at=time(7, 45), ends_at=time(8, 30), sort_order=1,
        )
    )
    db_session.flush()
    return schedule


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
# What a class is taught
# ---------------------------------------------------------------------------

def test_the_subjects_a_class_takes(client, db_session, tenant, taught_class):
    klass, subject, _offering = taught_class
    _user, token = _staff_with(db_session, tenant, "class_subject.read")

    body = _ask(client, tenant, token, CLASS_SUBJECTS, classId=klass.id)

    assert "errors" not in body, body
    offerings = body["data"]["classSubjects"]
    assert len(offerings) == 1
    assert offerings[0]["subjectName"] == "Mathematics"
    assert offerings[0]["weeklyPeriods"] == 6


def test_class_subjects_survive_a_school_with_no_timetable(
    client, db_session, tenant, taught_class
):
    """The seam: subjects belong to a class whether or not the school has
    bought the timetable. Sharing one gate with subjectTeachers would have
    emptied this screen."""
    klass, _subject, _offering = taught_class
    tenant.feature_flags = {"timetable": False}
    db_session.flush()
    _user, token = _staff_with(db_session, tenant, "class_subject.read")

    body = _ask(client, tenant, token, CLASS_SUBJECTS, classId=klass.id)

    assert "errors" not in body, body
    assert len(body["data"]["classSubjects"]) == 1


def test_who_teaches_them_is_behind_the_timetable_module(
    client, db_session, tenant, taught_class
):
    klass, _subject, _offering = taught_class
    tenant.feature_flags = {"timetable": False}
    db_session.flush()
    _user, token = _staff_with(db_session, tenant, "class_subject.read")

    body = _ask(client, tenant, token, SUBJECT_TEACHERS, classId=klass.id)

    assert "FEATURE_DISABLED" in _codes(body)


def test_managing_classes_is_enough_to_read_their_subjects(
    client, db_session, tenant, taught_class
):
    """The route names three authorities; whoever runs classes reads what
    they are taught."""
    klass, _subject, _offering = taught_class
    _user, token = _staff_with(db_session, tenant, "class.manage")

    assert "errors" not in _ask(client, tenant, token, CLASS_SUBJECTS, classId=klass.id)


def test_reading_class_subjects_needs_one_of_its_authorities(
    client, db_session, tenant, taught_class
):
    klass, _subject, _offering = taught_class
    _user, token = _staff_with(db_session, tenant, "student.read.all")

    assert "FORBIDDEN" in _codes(
        _ask(client, tenant, token, CLASS_SUBJECTS, classId=klass.id)
    )


def test_who_teaches_a_class(client, db_session, tenant, taught_class):
    klass, _subject, _offering = taught_class
    _user, token = _staff_with(db_session, tenant, "class_subject.manage")

    body = _ask(client, tenant, token, SUBJECT_TEACHERS, classId=klass.id)

    assert "errors" not in body, body
    assert isinstance(body["data"]["subjectTeachers"], list)


# ---------------------------------------------------------------------------
# The clock the school teaches to
# ---------------------------------------------------------------------------

def test_the_clocks_a_school_keeps(client, db_session, tenant, bell):
    _user, token = _staff_with(db_session, tenant, "academics.read")

    body = _ask(client, tenant, token, BELLS)

    assert "errors" not in body, body
    schedules = body["data"]["bellSchedules"]["items"]
    assert [s["name"] for s in schedules] == ["Regular Day"]
    assert schedules[0]["isDefault"] is True


def test_one_clock_with_its_periods(client, db_session, tenant, bell):
    _user, token = _staff_with(db_session, tenant, "academics.read")

    body = _ask(client, tenant, token, BELL, id=bell.id)

    assert "errors" not in body, body
    detail = body["data"]["bellSchedule"]
    assert detail["name"] == "Regular Day"
    assert len(detail["periods"]) == 1
    assert detail["periods"][0]["label"] == "Period 1"
    assert detail["periods"][0]["startsAt"] is not None


def test_a_clock_says_what_depends_on_it(client, db_session, tenant, bell):
    """What a school breaks by editing it."""
    _user, token = _staff_with(db_session, tenant, "academics.read")

    body = _ask(client, tenant, token, BELL, id=bell.id)

    assert body["data"]["bellSchedule"]["timetableVersionsLinked"] == 0


def test_a_clock_nobody_keeps_is_not_found(client, db_session, tenant, bell):
    _user, token = _staff_with(db_session, tenant, "academics.read")

    body = _ask(client, tenant, token, BELL, id=_new_id("bs-"))

    assert "errors" not in body, body
    assert body["data"]["bellSchedule"] is None


def test_whoever_runs_timetables_reads_the_clocks(client, db_session, tenant, bell):
    """The route offers `timetable.manage` as well as the academics keys."""
    _user, token = _staff_with(db_session, tenant, "timetable.manage")

    assert "errors" not in _ask(client, tenant, token, BELLS)


def test_the_clocks_answer_to_neither_class_nor_subject_authority(
    client, db_session, tenant, bell
):
    _user, token = _staff_with(db_session, tenant, "class_subject.manage")

    assert "FORBIDDEN" in _codes(_ask(client, tenant, token, BELLS))


def test_a_school_without_the_timetable_module_keeps_no_clocks(
    client, db_session, tenant, bell
):
    tenant.feature_flags = {"timetable": False}
    db_session.flush()
    _user, token = _staff_with(db_session, tenant, "academics.read")

    assert "FEATURE_DISABLED" in _codes(_ask(client, tenant, token, BELLS))
