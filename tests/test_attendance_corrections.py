"""Changing attendance that has already been settled.

A settled register could be rewritten by anyone holding `attendance.manage`
and nothing was kept — not what it said before, not who changed it, not why.
For a record a school may have to produce, that is the wrong shape.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from flask import g

from modules.attendance.models import (
    CORRECTION_APPROVED,
    CORRECTION_REJECTED,
    CORRECTION_REQUESTED,
    AttendanceCorrection,
)


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


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
    """One register entry: a child marked absent."""
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
    return record, session


@pytest.fixture
def people(db_session, tenant):
    """A teacher who asks, and a head who decides."""
    from modules.auth.models import User

    made = {}
    for key, name in (("teacher", "Class Teacher"), ("head", "Head of Year")):
        user = User(
            id=_new_id("u-"), tenant_id=tenant.id,
            email=f"{uuid.uuid4().hex[:8]}@test.school",
            password_hash="x" * 60, name=name,
        )
        db_session.add(user)
        made[key] = user
    db_session.flush()
    return made


@pytest.fixture
def settings(db_session, tenant):
    from modules.academics.backbone.models import AcademicSettings

    row = AcademicSettings.query.filter_by(tenant_id=tenant.id).first()
    if row is None:
        row = AcademicSettings(id=_new_id("as-"), tenant_id=tenant.id)
        db_session.add(row)
        db_session.flush()
    return row


# ---------------------------------------------------------------------------
# A correction is not an edit
# ---------------------------------------------------------------------------

def test_a_correction_needs_a_reason(ctx, tenant, db_session, marked, settings, people):
    from modules.attendance.correction_service import request_correction

    record, _session = marked

    result = request_correction(
        tenant.id, record.id, to_status="present", reason="  ",
        requested_by_user_id=people["teacher"].id,
    )
    assert result["success"] is False
    assert "reason" in result["error"].lower()


def test_a_correction_records_what_it_changed(ctx, tenant, db_session, marked, settings, people):
    """What it said before is the part the record itself cannot keep."""
    from modules.attendance.correction_service import request_correction

    record, _session = marked

    result = request_correction(
        tenant.id, record.id, to_status="present",
        reason="Arrived late, marked absent in error",
        requested_by_user_id=people["teacher"].id,
    )
    assert result["success"], result
    assert result["applied"] is True

    written = AttendanceCorrection.query.filter_by(
        attendance_record_id=record.id
    ).first()
    assert written.from_status == "absent"
    assert written.to_status == "present"
    assert written.reason == "Arrived late, marked absent in error"
    assert written.requested_by_user_id == people["teacher"].id

    db_session.refresh(record)
    assert record.status == "present"


def test_correcting_to_what_it_already_says_is_refused(
    ctx, tenant, db_session, marked, settings, people
):
    from modules.attendance.correction_service import request_correction

    record, _session = marked

    result = request_correction(
        tenant.id, record.id, to_status="absent", reason="No change",
        requested_by_user_id=people["teacher"].id,
    )
    assert result["success"] is False


# ---------------------------------------------------------------------------
# Approval, where the school wants it
# ---------------------------------------------------------------------------

def test_a_school_can_require_someone_to_agree(
    ctx, tenant, db_session, marked, settings, people
):
    from modules.attendance.correction_service import request_correction

    settings.attendance_corrections_require_approval = True
    db_session.flush()
    record, _session = marked

    result = request_correction(
        tenant.id, record.id, to_status="present", reason="Was here",
        requested_by_user_id=people["teacher"].id,
    )
    assert result["success"], result
    # Asked for, not done.
    assert result["applied"] is False
    assert result["correction"]["status"] == CORRECTION_REQUESTED

    db_session.refresh(record)
    assert record.status == "absent", "the record must not move until agreed"


def test_approving_makes_the_change(ctx, tenant, db_session, marked, settings, people):
    from modules.attendance.correction_service import (
        approve_correction,
        request_correction,
    )

    settings.attendance_corrections_require_approval = True
    db_session.flush()
    record, _session = marked
    asked = request_correction(
        tenant.id, record.id, to_status="present", reason="Was here",
        requested_by_user_id=people["teacher"].id,
    )["correction"]

    decided = approve_correction(
        tenant.id, asked["id"], decided_by_user_id=people["head"].id, note="Confirmed"
    )
    assert decided["success"], decided
    assert decided["correction"]["status"] == CORRECTION_APPROVED

    db_session.refresh(record)
    assert record.status == "present"
    assert record.updated_by_user_id == people["head"].id


def test_rejecting_leaves_the_record_and_keeps_the_request(
    ctx, tenant, db_session, marked, settings, people
):
    """A refused correction is still something the school asked about."""
    from modules.attendance.correction_service import (
        reject_correction,
        request_correction,
    )

    settings.attendance_corrections_require_approval = True
    db_session.flush()
    record, _session = marked
    asked = request_correction(
        tenant.id, record.id, to_status="present", reason="Parent says present",
        requested_by_user_id=people["teacher"].id,
    )["correction"]

    decided = reject_correction(
        tenant.id, asked["id"], decided_by_user_id=people["head"].id, note="Register stands"
    )
    assert decided["success"], decided
    assert decided["correction"]["status"] == CORRECTION_REJECTED

    db_session.refresh(record)
    assert record.status == "absent"
    assert AttendanceCorrection.query.filter_by(id=asked["id"]).first() is not None


def test_a_decided_correction_cannot_be_decided_again(
    ctx, tenant, db_session, marked, settings, people
):
    from modules.attendance.correction_service import (
        approve_correction,
        reject_correction,
        request_correction,
    )

    settings.attendance_corrections_require_approval = True
    db_session.flush()
    record, _session = marked
    asked = request_correction(
        tenant.id, record.id, to_status="present", reason="Was here",
        requested_by_user_id=people["teacher"].id,
    )["correction"]
    approve_correction(tenant.id, asked["id"], decided_by_user_id=people["head"].id)

    again = reject_correction(tenant.id, asked["id"], decided_by_user_id=people["head"].id)
    assert again["success"] is False


def test_someone_who_could_approve_does_not_ask_themselves(
    ctx, tenant, db_session, marked, settings, people
):
    """Asking yourself for permission is a step, not a control."""
    from modules.attendance.correction_service import request_correction

    settings.attendance_corrections_require_approval = True
    db_session.flush()
    record, _session = marked

    result = request_correction(
        tenant.id, record.id, to_status="present", reason="Was here",
        requested_by_user_id=people["head"].id, may_decide=True,
    )
    assert result["applied"] is True
    db_session.refresh(record)
    assert record.status == "present"


# ---------------------------------------------------------------------------
# The register closes
# ---------------------------------------------------------------------------

def test_a_finalised_register_is_settled(ctx, tenant, db_session, marked, settings, people):
    from modules.attendance.correction_service import is_locked

    _record, session = marked
    assert is_locked(session) is True


def test_the_school_can_set_its_own_deadline(
    ctx, tenant, db_session, marked, settings, people
):
    """What stops a register being filled in at the end of term for a day
    nobody remembers."""
    from modules.attendance.correction_service import is_locked

    _record, session = marked
    session.status = "draft"
    session.session_date = date.today() - timedelta(days=3)
    settings.attendance_lock_after_hours = 24
    db_session.flush()

    assert is_locked(session) is True


def test_without_a_deadline_only_finalising_closes_it(
    ctx, tenant, db_session, marked, settings, people
):
    from modules.attendance.correction_service import is_locked

    _record, session = marked
    session.status = "draft"
    session.session_date = date.today() - timedelta(days=30)
    settings.attendance_lock_after_hours = None
    db_session.flush()

    assert is_locked(session) is False


def test_a_settled_register_is_not_marked_again(
    ctx, tenant, db_session, marked, settings, people
):
    """Marking is refused with a message pointing at the sanctioned path."""
    from modules.attendance import session_services

    record, session = marked

    result = session_services.upsert_records(
        tenant.id, session.id, people["teacher"].id,
        [{"student_id": record.student_id, "status": "present"}],
    )
    assert result["success"] is False
    assert "correction" in result["error"].lower()
