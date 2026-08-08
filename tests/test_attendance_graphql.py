"""Attendance over GraphQL — corrections, and the gate the module needs.

Two things start here. The correction workflow gets a surface at last: it
has been complete and tested since Phase 2 and unreachable by the people who
need it, which made the sanctioned way to change a mark the one nobody could
take.

And attendance is the first *optional* module to move. A school may still be
on paper, and a school that has switched the module off must not be able to
work through it on either transport. Students never needed that gate — they
cannot be switched off — so nothing has proved it before.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from graphql_api import GRAPHQL_PATH

REQUEST = """
mutation R($recordId: ID!, $toStatus: String!, $reason: String!) {
  requestAttendanceCorrection(recordId: $recordId, toStatus: $toStatus, reason: $reason) {
    applied
    correction { id fromStatus toStatus reason status }
  }
}
"""

APPROVE = """
mutation A($id: ID!, $note: String) {
  approveAttendanceCorrection(id: $id, note: $note) { id status decisionNote }
}
"""

REJECT = "mutation J($id: ID!) { rejectAttendanceCorrection(id: $id) { id status } }"

PENDING = "query { pendingAttendanceCorrections { id toStatus reason } }"

HISTORY = """
query H($recordId: ID!) {
  attendanceRecordCorrections(recordId: $recordId) { toStatus status }
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
def marked(db_session, tenant, academic_year):
    """One register entry: a child marked absent, the session finalized."""
    from modules.academics.backbone.models import AttendanceRecord, AttendanceSession
    from modules.classes.models import Class
    from modules.people.models import Person
    from modules.students.models import Student

    cls = Class(
        id=_new_id("c-"), tenant_id=tenant.id, name="Grade 4", section="A",
        academic_year_id=academic_year.id,
    )
    person = Person(id=_new_id("p-"), tenant_id=tenant.id, full_name="Riya Shah")
    db_session.add_all([cls, person])
    db_session.flush()
    student = Student(
        id=_new_id("s-"), tenant_id=tenant.id, person_id=person.id,
        admission_number=f"ADM-{uuid.uuid4().hex[:6]}",
        academic_year_id=academic_year.id, class_id=cls.id,
    )
    session = AttendanceSession(
        id=_new_id("as-"), tenant_id=tenant.id, class_id=cls.id,
        session_date=date(2026, 9, 1), status="finalized",
    )
    db_session.add_all([student, session])
    db_session.flush()
    record = AttendanceRecord(
        id=_new_id("ar-"), tenant_id=tenant.id,
        attendance_session_id=session.id, student_id=student.id, status="absent",
    )
    db_session.add(record)
    db_session.flush()
    return record


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


@pytest.fixture
def reviews_corrections(db_session, tenant):
    """A school that wants a change to the register seen before it lands.

    Schools genuinely differ here — a small primary trusts its teachers to
    fix their own registers — so most of these tests turn review on to
    exercise the queue at all.
    """
    from modules.academics.backbone.models import AcademicSettings

    settings = AcademicSettings.query.filter_by(tenant_id=tenant.id).first()
    if settings is None:
        settings = AcademicSettings(id=_new_id("acs-"), tenant_id=tenant.id)
        db_session.add(settings)
    settings.attendance_corrections_require_approval = True
    db_session.flush()
    return settings


@pytest.fixture
def teacher(db_session, tenant):
    """Marks the register, and may ask for a mark to be changed."""
    return _staff_with(db_session, tenant, "attendance.mark")


@pytest.fixture
def head(db_session, tenant):
    """Answerable for the register as a whole."""
    return _staff_with(db_session, tenant, "attendance.manage")


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


def _status_of(record_id):
    from modules.academics.backbone.models import AttendanceRecord

    return AttendanceRecord.query.filter_by(id=record_id).first().status


# ---------------------------------------------------------------------------
# The gate an optional module needs
# ---------------------------------------------------------------------------

def test_a_school_that_has_switched_attendance_off_cannot_reach_it(
    client, db_session, tenant, ready_school, marked, head
):
    """The first module where forgetting the gate would matter.

    REST refuses every attendance route when the flag is off. Until this
    field carried the same check, GraphQL was a door the school had closed
    and could still be walked through.
    """
    _user, token = head
    tenant.feature_flags = {"attendance": False}
    db_session.flush()

    reading = _ask(client, tenant, token, PENDING)
    writing = _ask(
        client, tenant, token, REQUEST,
        recordId=marked.id, toStatus="present", reason="Was in the sick room",
    )

    assert "FEATURE_DISABLED" in _codes(reading)
    assert "FEATURE_DISABLED" in _codes(writing)
    assert _status_of(marked.id) == "absent", "nothing may change through a closed door"


def test_the_gate_lets_a_school_that_uses_attendance_through(
    client, db_session, tenant, ready_school, marked, head
):
    """The other half — a gate that refuses everyone proves nothing."""
    _user, token = head
    tenant.feature_flags = {"attendance": True}
    db_session.flush()

    body = _ask(client, tenant, token, PENDING)

    assert "errors" not in body, body


# ---------------------------------------------------------------------------
# Asking, and deciding, are different jobs
# ---------------------------------------------------------------------------

def test_a_teachers_request_waits_for_somebody_to_decide(
    client, tenant, ready_school, marked, teacher, reviews_corrections
):
    _user, token = teacher

    body = _ask(
        client, tenant, token, REQUEST,
        recordId=marked.id, toStatus="present", reason="Was in the sick room",
    )

    assert "errors" not in body, body
    outcome = body["data"]["requestAttendanceCorrection"]
    assert outcome["applied"] is False
    assert outcome["correction"]["status"] == "requested"
    assert outcome["correction"]["fromStatus"] == "absent"
    assert _status_of(marked.id) == "absent", "the register stands until decided"


def test_a_school_that_does_not_review_lets_a_teacher_fix_their_own_register(
    client, tenant, ready_school, marked, teacher
):
    """The default. A small primary trusts its teachers, and the request is
    still written down — what is configurable is the review, not the record."""
    _user, token = teacher

    body = _ask(
        client, tenant, token, REQUEST,
        recordId=marked.id, toStatus="present", reason="Was in the sick room",
    )

    outcome = body["data"]["requestAttendanceCorrection"]
    assert outcome["applied"] is True
    assert _status_of(marked.id) == "present"
    history = _ask(client, tenant, token, HISTORY, recordId=marked.id)
    assert history["data"]["attendanceRecordCorrections"] == [
        {"toStatus": "present", "status": "approved"}
    ]


def test_somebody_who_could_approve_it_does_not_have_to_ask_themselves(
    client, tenant, ready_school, marked, head
):
    """Asking yourself for permission is a step, not a control — but the
    request is still written down, so the change is never the only evidence
    that it happened."""
    _user, token = head

    body = _ask(
        client, tenant, token, REQUEST,
        recordId=marked.id, toStatus="present", reason="Marked in error",
    )

    outcome = body["data"]["requestAttendanceCorrection"]
    assert outcome["applied"] is True
    assert outcome["correction"]["status"] == "approved"
    assert _status_of(marked.id) == "present"


def test_deciding_is_not_something_a_teacher_may_do(
    client, tenant, ready_school, marked, teacher, reviews_corrections
):
    _user, token = teacher
    asked = _ask(
        client, tenant, token, REQUEST,
        recordId=marked.id, toStatus="present", reason="Was in the sick room",
    )["data"]["requestAttendanceCorrection"]["correction"]

    body = _ask(client, tenant, token, APPROVE, id=asked["id"])

    assert "FORBIDDEN" in _codes(body)
    assert _status_of(marked.id) == "absent"


def test_a_head_approves_and_the_register_changes(
    client, tenant, ready_school, marked, teacher, head, reviews_corrections
):
    _teacher_user, teacher_token = teacher
    _head_user, head_token = head
    asked = _ask(
        client, tenant, teacher_token, REQUEST,
        recordId=marked.id, toStatus="present", reason="Was in the sick room",
    )["data"]["requestAttendanceCorrection"]["correction"]

    body = _ask(
        client, tenant, head_token, APPROVE, id=asked["id"], note="Nurse confirmed"
    )

    assert "errors" not in body, body
    assert body["data"]["approveAttendanceCorrection"]["status"] == "approved"
    assert body["data"]["approveAttendanceCorrection"]["decisionNote"] == "Nurse confirmed"
    assert _status_of(marked.id) == "present"


def test_a_rejected_correction_leaves_the_register_alone_and_is_kept(
    client, tenant, ready_school, marked, teacher, head, reviews_corrections
):
    _teacher_user, teacher_token = teacher
    _head_user, head_token = head
    asked = _ask(
        client, tenant, teacher_token, REQUEST,
        recordId=marked.id, toStatus="present", reason="Says he was there",
    )["data"]["requestAttendanceCorrection"]["correction"]

    body = _ask(client, tenant, head_token, REJECT, id=asked["id"])

    assert body["data"]["rejectAttendanceCorrection"]["status"] == "rejected"
    assert _status_of(marked.id) == "absent"
    history = _ask(client, tenant, head_token, HISTORY, recordId=marked.id)
    assert history["data"]["attendanceRecordCorrections"] == [
        {"toStatus": "present", "status": "rejected"}
    ]


def test_a_correction_cannot_be_decided_twice(
    client, tenant, ready_school, marked, head
):
    _user, token = head
    asked = _ask(
        client, tenant, token, REQUEST,
        recordId=marked.id, toStatus="present", reason="Marked in error",
    )["data"]["requestAttendanceCorrection"]["correction"]

    body = _ask(client, tenant, token, APPROVE, id=asked["id"])

    assert "CONFLICT" in _codes(body)


# ---------------------------------------------------------------------------
# A correction without a reason is an edit
# ---------------------------------------------------------------------------

def test_a_correction_needs_a_reason(client, tenant, ready_school, marked, head):
    _user, token = head

    body = _ask(
        client, tenant, token, REQUEST,
        recordId=marked.id, toStatus="present", reason="   ",
    )

    assert "VALIDATION_ERROR" in _codes(body)
    assert _status_of(marked.id) == "absent"


def test_a_mark_that_is_not_a_mark_is_refused(
    client, tenant, ready_school, marked, head
):
    _user, token = head

    body = _ask(
        client, tenant, token, REQUEST,
        recordId=marked.id, toStatus="probably-there", reason="Not sure",
    )

    assert "VALIDATION_ERROR" in _codes(body)


def test_correcting_a_mark_to_what_it_already_says_is_refused(
    client, tenant, ready_school, marked, head
):
    _user, token = head

    body = _ask(
        client, tenant, token, REQUEST,
        recordId=marked.id, toStatus="absent", reason="Confirming",
    )

    assert "CONFLICT" in _codes(body)


def test_a_correction_to_a_record_that_does_not_exist_is_not_found(
    client, tenant, ready_school, head
):
    _user, token = head

    body = _ask(
        client, tenant, token, REQUEST,
        recordId="ar-nobody", toStatus="present", reason="Testing",
    )

    assert "NOT_FOUND" in _codes(body)


# ---------------------------------------------------------------------------
# The queue
# ---------------------------------------------------------------------------

def test_the_pending_queue_shows_what_is_waiting_on_a_decision(
    client, tenant, ready_school, marked, teacher, head, reviews_corrections
):
    _teacher_user, teacher_token = teacher
    _head_user, head_token = head
    _ask(
        client, tenant, teacher_token, REQUEST,
        recordId=marked.id, toStatus="late", reason="Arrived at 9:20",
    )

    body = _ask(client, tenant, head_token, PENDING)

    assert [c["toStatus"] for c in body["data"]["pendingAttendanceCorrections"]] == [
        "late"
    ]


def test_a_decided_correction_leaves_the_queue(
    client, tenant, ready_school, marked, teacher, head, reviews_corrections
):
    _teacher_user, teacher_token = teacher
    _head_user, head_token = head
    asked = _ask(
        client, tenant, teacher_token, REQUEST,
        recordId=marked.id, toStatus="late", reason="Arrived at 9:20",
    )["data"]["requestAttendanceCorrection"]["correction"]
    _ask(client, tenant, head_token, APPROVE, id=asked["id"])

    body = _ask(client, tenant, head_token, PENDING)

    assert body["data"]["pendingAttendanceCorrections"] == []


def test_the_queue_is_not_a_teachers_to_read(
    client, tenant, ready_school, marked, teacher
):
    """Who decides sees the queue. Marking the register is not that job."""
    _user, token = teacher

    body = _ask(client, tenant, token, PENDING)

    assert "FORBIDDEN" in _codes(body)
