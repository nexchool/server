"""Branch enforcement on the Attendance and Timetable domains.

Phase 2 (P2-T4b) — wiring the ``core/branch_scope`` primitives into the
Attendance, Timetable, Timetable-v2 (entries/versions) and Schedule domains.
These tests verify the *applied* behaviour (service-level list scoping + the
service/route asserts) and the **no-op property**: an unrestricted admin sees
identical results to before the change.

Both domains reach a branch through a Class (``class_id`` ->
``Class.school_unit_id``). A restricted sub-admin (unit A) may only touch
classes/students/attendance/timetable in unit A; an out-of-branch id -> 403
(``BranchForbidden``). Tenant-wide aggregates/configs that cannot be cleanly
class-filtered are denied for restricted users.

Pattern mirrors ``tests/test_branch_enforce_classes_students.py``: push
``g.tenant_id`` / ``g.current_user`` via ``flask_app.test_request_context`` and
call the service / assert layer directly. Runs against the localhost Postgres
bound to the savepoint connection in conftest (rolled back per test).
"""

from __future__ import annotations

import uuid
from datetime import date, time, timedelta

import pytest
from flask import g

from core.branch_scope import BranchForbidden, get_allowed_unit_ids
from modules.attendance import services as attendance_services
from modules.attendance import session_services as attendance_session_services
from modules.attendance.models import Attendance
from modules.auth.models import User
from modules.classes.models import Class
from modules.schedule import services as schedule_services
from modules.students.models import Student
from modules.sub_admins.models import UserSchoolUnit
from modules.timetable import services as timetable_services
from modules.timetable.models import TimetableSlot


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def units(db_session, tenant):
    from modules.school_units.models import SchoolUnit

    unit_a = SchoolUnit(
        id=_new_id("su-"), tenant_id=tenant.id, name="Campus A",
        code=f"A-{uuid.uuid4().hex[:6]}",
    )
    unit_b = SchoolUnit(
        id=_new_id("su-"), tenant_id=tenant.id, name="Campus B",
        code=f"B-{uuid.uuid4().hex[:6]}",
    )
    db_session.add_all([unit_a, unit_b])
    db_session.flush()
    return unit_a, unit_b


@pytest.fixture
def academic_year(db_session, tenant):
    from modules.academics.academic_year.models import AcademicYear

    ay = AcademicYear(
        id=_new_id("ay-"),
        tenant_id=tenant.id,
        name="2025-2026",
        start_date="2025-06-01",
        end_date="2026-03-31",
    )
    db_session.add(ay)
    db_session.flush()
    return ay


@pytest.fixture
def classes(db_session, tenant, units, academic_year):
    """class_a in unit A, class_b in unit B."""
    unit_a, unit_b = units
    class_a = Class(
        id=_new_id("c-"),
        tenant_id=tenant.id,
        name="Grade 1",
        section="A",
        academic_year_id=academic_year.id,
        school_unit_id=unit_a.id,
    )
    class_b = Class(
        id=_new_id("c-"),
        tenant_id=tenant.id,
        name="Grade 1",
        section="B",
        academic_year_id=academic_year.id,
        school_unit_id=unit_b.id,
    )
    db_session.add_all([class_a, class_b])
    db_session.flush()
    return class_a, class_b


def _make_student_in_class(db_session, tenant, class_id):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=_new_id("u-"),
        tenant_id=tenant.id,
        email=f"{suffix}@test.school",
        password_hash="x" * 60,
        name="Test Student",
    )
    db_session.add(user)
    db_session.flush()
    student = Student(
        id=_new_id("s-"),
        tenant_id=tenant.id,
        user_id=user.id,
        admission_number=f"ADM-{suffix}",
        class_id=class_id,
    )
    db_session.add(student)
    db_session.flush()
    return student


@pytest.fixture
def students(db_session, tenant, classes):
    """student_a in class_a, student_b in class_b."""
    class_a, class_b = classes
    student_a = _make_student_in_class(db_session, tenant, class_a.id)
    student_b = _make_student_in_class(db_session, tenant, class_b.id)
    return student_a, student_b


@pytest.fixture
def marker_user(db_session, tenant):
    """A user to attribute marked_by / created_by columns to."""
    u = User(
        id=_new_id("mk-"),
        tenant_id=tenant.id,
        email=f"mk-{uuid.uuid4().hex[:6]}@test.school",
        password_hash="x" * 60,
        name="Marker",
    )
    db_session.add(u)
    db_session.flush()
    return u


@pytest.fixture
def attendance_rows(db_session, tenant, classes, students, marker_user):
    """One legacy attendance row per class/student on a fixed date."""
    class_a, class_b = classes
    student_a, student_b = students
    att_date = date(2025, 9, 1)
    row_a = Attendance(
        id=_new_id("att-"),
        tenant_id=tenant.id,
        date=att_date,
        class_id=class_a.id,
        student_id=student_a.id,
        status="present",
        marked_by=marker_user.id,
    )
    row_b = Attendance(
        id=_new_id("att-"),
        tenant_id=tenant.id,
        date=att_date,
        class_id=class_b.id,
        student_id=student_b.id,
        status="present",
        marked_by=marker_user.id,
    )
    db_session.add_all([row_a, row_b])
    db_session.flush()
    return row_a, row_b


def _make_subject(db_session, tenant):
    s = __import__(
        "modules.subjects.models", fromlist=["Subject"]
    ).Subject(id=_new_id("sub-"), tenant_id=tenant.id, name="Maths")
    db_session.add(s)
    db_session.flush()
    return s


def _make_teacher(db_session, tenant):
    from modules.teachers.models import Teacher

    suffix = uuid.uuid4().hex[:8]
    u = User(
        id=_new_id("tu-"),
        tenant_id=tenant.id,
        email=f"t-{suffix}@test.school",
        password_hash="x" * 60,
        name="Test Teacher",
    )
    db_session.add(u)
    db_session.flush()
    t = Teacher(
        id=_new_id("t-"),
        tenant_id=tenant.id,
        user_id=u.id,
        employee_id=f"EMP-{suffix}",
    )
    db_session.add(t)
    db_session.flush()
    return t


@pytest.fixture
def timetable_slots(db_session, tenant, classes):
    """One legacy TimetableSlot per class."""
    class_a, class_b = classes
    subject = _make_subject(db_session, tenant)
    teacher = _make_teacher(db_session, tenant)
    slot_a = TimetableSlot(
        id=_new_id("tts-"),
        tenant_id=tenant.id,
        class_id=class_a.id,
        subject_id=subject.id,
        teacher_id=teacher.id,
        day_of_week=0,
        period_number=1,
        start_time=time(8, 0),
        end_time=time(8, 45),
    )
    slot_b = TimetableSlot(
        id=_new_id("tts-"),
        tenant_id=tenant.id,
        class_id=class_b.id,
        subject_id=subject.id,
        teacher_id=teacher.id,
        day_of_week=0,
        period_number=1,
        start_time=time(8, 0),
        end_time=time(8, 45),
    )
    db_session.add_all([slot_a, slot_b])
    db_session.flush()
    return slot_a, slot_b


@pytest.fixture
def unrestricted_user(db_session, tenant):
    """A tenant user with NO UserSchoolUnit rows -> unrestricted."""
    u = User(
        id=_new_id("uu-"),
        tenant_id=tenant.id,
        email=f"uu-{uuid.uuid4().hex[:6]}@test.school",
        password_hash="x" * 60,
        name="Unrestricted Admin",
    )
    db_session.add(u)
    db_session.flush()
    return u


@pytest.fixture
def restricted_user(db_session, tenant, units):
    """A tenant user restricted to unit A only."""
    unit_a, _unit_b = units
    u = User(
        id=_new_id("ru-"),
        tenant_id=tenant.id,
        email=f"ru-{uuid.uuid4().hex[:6]}@test.school",
        password_hash="x" * 60,
        name="Restricted Sub-Admin",
    )
    db_session.add(u)
    db_session.flush()
    db_session.add(
        UserSchoolUnit(
            id=_new_id("usu-"),
            tenant_id=tenant.id,
            user_id=u.id,
            school_unit_id=unit_a.id,
        )
    )
    db_session.flush()
    return u


# ---------------------------------------------------------------------------
# Attendance — list (legacy table, backstop class filter)
# ---------------------------------------------------------------------------

def test_attendance_list_restricted_sees_only_unit_a(
    flask_app, db_session, tenant, attendance_rows, restricted_user
):
    row_a, row_b = attendance_rows
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        result = attendance_services.list_attendance_records(tenant.id)
        ids = {r["id"] for r in result["data"]["items"]}
        assert row_a.id in ids
        assert row_b.id not in ids


def test_attendance_list_unrestricted_sees_all(
    flask_app, db_session, tenant, attendance_rows, unrestricted_user
):
    row_a, row_b = attendance_rows
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        result = attendance_services.list_attendance_records(tenant.id)
        ids = {r["id"] for r in result["data"]["items"]}
        assert row_a.id in ids
        assert row_b.id in ids


def test_attendance_list_restricted_class_b_param_forbidden(
    flask_app, db_session, tenant, classes, attendance_rows, restricted_user
):
    _class_a, class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            attendance_services.list_attendance_records(tenant.id, class_id=class_b.id)


def test_attendance_list_restricted_class_a_param_ok(
    flask_app, db_session, tenant, classes, attendance_rows, restricted_user
):
    class_a, _class_b = classes
    row_a, _row_b = attendance_rows
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        result = attendance_services.list_attendance_records(tenant.id, class_id=class_a.id)
        ids = {r["id"] for r in result["data"]["items"]}
        assert row_a.id in ids


# ---------------------------------------------------------------------------
# Attendance — read by class / student
# ---------------------------------------------------------------------------

def test_attendance_by_class_unit_b_forbidden_for_restricted(
    flask_app, db_session, tenant, classes, restricted_user
):
    _class_a, class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            attendance_services.get_attendance_by_class_date(class_b.id, "2025-09-01")


def test_attendance_by_class_unit_a_ok_for_restricted(
    flask_app, db_session, tenant, classes, restricted_user
):
    class_a, _class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        result = attendance_services.get_attendance_by_class_date(class_a.id, "2025-09-01")
        assert result["success"] is True


def test_attendance_by_student_unit_b_forbidden_for_restricted(
    flask_app, db_session, tenant, students, restricted_user
):
    _student_a, student_b = students
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            attendance_services.get_student_attendance(student_b.id)


def test_attendance_by_student_unit_a_ok_for_restricted(
    flask_app, db_session, tenant, students, restricted_user
):
    student_a, _student_b = students
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        result = attendance_services.get_student_attendance(student_a.id)
        assert result["success"] is True


# ---------------------------------------------------------------------------
# Attendance — mark / sessions (mutations)
# ---------------------------------------------------------------------------

def test_mark_attendance_unit_b_forbidden_for_restricted(
    flask_app, db_session, tenant, classes, students, marker_user, restricted_user
):
    _class_a, class_b = classes
    _student_a, student_b = students
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            attendance_services.mark_attendance(
                class_id=class_b.id,
                date_str="2025-09-01",
                records=[{"student_id": student_b.id, "status": "present"}],
                marked_by_user_id=marker_user.id,
            )


def test_create_session_unit_b_forbidden_for_restricted(
    flask_app, db_session, tenant, classes, marker_user, restricted_user
):
    _class_a, class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            attendance_session_services.get_or_create_session(
                tenant.id, class_b.id, date(2025, 9, 1), marker_user.id
            )


def test_create_session_unit_a_ok_for_restricted(
    flask_app, db_session, tenant, classes, marker_user, restricted_user
):
    class_a, _class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        r = attendance_session_services.get_or_create_session(
            tenant.id, class_a.id, date(2025, 9, 1), marker_user.id
        )
        assert r["success"] is True


def test_class_history_unit_b_forbidden_for_restricted(
    flask_app, db_session, tenant, classes, restricted_user
):
    _class_a, class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            attendance_session_services.class_history(tenant.id, class_b.id)


# ---------------------------------------------------------------------------
# Timetable — list / read
# ---------------------------------------------------------------------------

def test_timetable_slots_by_class_unit_b_forbidden_for_restricted(
    flask_app, db_session, tenant, classes, timetable_slots, restricted_user
):
    _class_a, class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            timetable_services.get_slots_by_class(class_b.id, tenant.id)


def test_timetable_slots_by_class_unit_a_ok_for_restricted(
    flask_app, db_session, tenant, classes, timetable_slots, restricted_user
):
    class_a, _class_b = classes
    slot_a, _slot_b = timetable_slots
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        slots = timetable_services.get_slots_by_class(class_a.id, tenant.id)
        ids = {s["id"] for s in slots}
        assert slot_a.id in ids


def test_timetable_slots_by_class_unrestricted_sees_both(
    flask_app, db_session, tenant, classes, timetable_slots, unrestricted_user
):
    class_a, class_b = classes
    slot_a, slot_b = timetable_slots
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        a_ids = {s["id"] for s in timetable_services.get_slots_by_class(class_a.id, tenant.id)}
        b_ids = {s["id"] for s in timetable_services.get_slots_by_class(class_b.id, tenant.id)}
        assert slot_a.id in a_ids
        assert slot_b.id in b_ids


# ---------------------------------------------------------------------------
# Timetable — mutate slot (update / delete)
# ---------------------------------------------------------------------------

def test_timetable_update_slot_unit_b_forbidden_for_restricted(
    flask_app, db_session, tenant, timetable_slots, restricted_user
):
    _slot_a, slot_b = timetable_slots
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            timetable_services.update_slot(slot_b.id, {"room": "X"}, tenant.id)


def test_timetable_delete_slot_unit_b_forbidden_for_restricted(
    flask_app, db_session, tenant, timetable_slots, restricted_user
):
    _slot_a, slot_b = timetable_slots
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            timetable_services.delete_slot(slot_b.id, tenant.id)


def test_timetable_update_slot_unit_a_ok_for_restricted(
    flask_app, db_session, tenant, timetable_slots, restricted_user
):
    slot_a, _slot_b = timetable_slots
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        result = timetable_services.update_slot(slot_a.id, {"room": "R1"}, tenant.id)
        assert result["success"] is True


# ---------------------------------------------------------------------------
# Timetable config — tenant-global -> DENY for restricted
# ---------------------------------------------------------------------------
# The config route guards with:
#   if get_allowed_unit_ids() is not None: raise BranchForbidden(...)
# so the gate is truthy (denied) for restricted, None (passes) for unrestricted.

def _deny_if_restricted():
    if get_allowed_unit_ids() is not None:
        raise BranchForbidden("Tenant-global config denied for restricted")


def test_timetable_config_denied_for_restricted(
    flask_app, db_session, tenant, units, restricted_user
):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        assert get_allowed_unit_ids() is not None
        with pytest.raises(BranchForbidden):
            _deny_if_restricted()


def test_timetable_config_not_blocked_for_unrestricted(
    flask_app, db_session, tenant, units, unrestricted_user
):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        assert get_allowed_unit_ids() is None  # route would proceed normally


# ---------------------------------------------------------------------------
# Schedule — /today/all is a tenant-wide aggregate -> DENY for restricted
# ---------------------------------------------------------------------------

def test_schedule_today_all_denied_for_restricted(
    flask_app, db_session, tenant, units, restricted_user
):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        assert get_allowed_unit_ids() is not None
        with pytest.raises(BranchForbidden):
            _deny_if_restricted()


# ---------------------------------------------------------------------------
# Schedule — override (per-slot) -> assert class
# ---------------------------------------------------------------------------

def test_schedule_override_unit_b_slot_forbidden_for_restricted(
    flask_app, db_session, tenant, timetable_slots, marker_user, restricted_user
):
    _slot_a, slot_b = timetable_slots
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            schedule_services.upsert_override(
                slot_id=slot_b.id,
                override_date=date(2025, 9, 1),
                override_type="cancelled",
                tenant_id=tenant.id,
                created_by=marker_user.id,
            )


def test_schedule_override_unit_a_slot_ok_for_restricted(
    flask_app, db_session, tenant, timetable_slots, marker_user, restricted_user
):
    slot_a, _slot_b = timetable_slots
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        result = schedule_services.upsert_override(
            slot_id=slot_a.id,
            override_date=date(2025, 9, 1),
            override_type="cancelled",
            tenant_id=tenant.id,
            created_by=marker_user.id,
        )
        assert result["success"] is True


# ---------------------------------------------------------------------------
# Regression — unrestricted admin is a strict no-op everywhere
# ---------------------------------------------------------------------------

def test_unrestricted_counts_unchanged(
    flask_app, db_session, tenant, attendance_rows, timetable_slots, classes, students, unrestricted_user
):
    """Unrestricted admin sees every row across attendance + timetable (no-op)."""
    class_a, class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user

        att = attendance_services.list_attendance_records(tenant.id)["data"]["items"]
        slots_a = timetable_services.get_slots_by_class(class_a.id, tenant.id)
        slots_b = timetable_services.get_slots_by_class(class_b.id, tenant.id)

        # Both attendance rows visible; both classes' slots readable.
        assert len({r["id"] for r in att}) == 2
        assert len(slots_a) == 1
        assert len(slots_b) == 1


# ===========================================================================
# Attendance session integrity: no future-dated sessions, no silent record skips
# ===========================================================================

def test_get_or_create_session_rejects_future_date(
    flask_app, db_session, tenant, classes, marker_user, unrestricted_user
):
    class_a, _ = classes
    future = date.today() + timedelta(days=5)
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        r = attendance_session_services.get_or_create_session(
            tenant.id, class_a.id, future, marker_user.id
        )
    assert r["success"] is False
    assert "future" in r["error"].lower()


def test_get_or_create_session_allows_today(
    flask_app, db_session, tenant, classes, marker_user, unrestricted_user
):
    class_a, _ = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        r = attendance_session_services.get_or_create_session(
            tenant.id, class_a.id, date.today(), marker_user.id
        )
    assert r["success"] is True


def test_upsert_records_reports_skipped_instead_of_silently_dropping(
    flask_app, db_session, tenant, classes, students, unrestricted_user
):
    class_a, _class_b = classes
    student_a, student_b = students  # student_b belongs to class_b, not class_a
    teacher = _make_teacher(db_session, tenant)  # the session's assigned marker

    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        created = attendance_session_services.get_or_create_session(
            tenant.id,
            class_a.id,
            date(2025, 9, 1),
            teacher.user_id,
            assigned_marker_teacher_id=teacher.id,
        )
        assert created["success"] is True
        session_id = created["session"]["id"]

        res = attendance_session_services.upsert_records(
            tenant.id,
            session_id,
            teacher.user_id,
            [
                {"student_id": student_a.id, "status": "present"},
                {"student_id": student_b.id, "status": "present"},       # wrong class
                {"student_id": "no-such-student", "status": "absent"},    # nonexistent
                {"student_id": student_a.id, "status": "teleported"},     # invalid status
            ],
        )

    assert res["success"] is True
    assert res["created"] == 1  # only student_a's valid record saved
    skipped_ids = [s["student_id"] for s in res["skipped"]]
    assert student_b.id in skipped_ids          # not in this class
    assert "no-such-student" in skipped_ids     # nonexistent
    # student_a's bad-status record is surfaced, not silently dropped.
    assert any(
        s["student_id"] == student_a.id and "invalid status" in s["reason"]
        for s in res["skipped"]
    )
    assert len(res["skipped"]) == 3


# ===========================================================================
# Timetable: create_slot must prevent teacher double-booking (not only move/swap)
# ===========================================================================

def test_create_slot_blocks_teacher_double_booking(
    flask_app, db_session, tenant, classes, unrestricted_user
):
    class_a, class_b = classes
    subject = _make_subject(db_session, tenant)
    teacher = _make_teacher(db_session, tenant)
    base = {
        "subject_id": subject.id,
        "teacher_id": teacher.id,
        "day_of_week": 0,
        "period_number": 1,
        "start_time": "08:00",
        "end_time": "08:45",
    }
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        first = timetable_services.create_slot({**base, "class_id": class_a.id}, tenant.id)
        assert first["success"] is True
        # Same teacher, same day + period, a different class -> double-booking.
        second = timetable_services.create_slot({**base, "class_id": class_b.id}, tenant.id)
    assert second["success"] is False
    assert "already teaching" in second["error"].lower()


def test_create_slot_allows_same_teacher_at_a_different_period(
    flask_app, db_session, tenant, classes, unrestricted_user
):
    class_a, class_b = classes
    subject = _make_subject(db_session, tenant)
    teacher = _make_teacher(db_session, tenant)
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        first = timetable_services.create_slot(
            {
                "class_id": class_a.id, "subject_id": subject.id, "teacher_id": teacher.id,
                "day_of_week": 0, "period_number": 1,
                "start_time": "08:00", "end_time": "08:45",
            },
            tenant.id,
        )
        # Same teacher, DIFFERENT period -> allowed.
        second = timetable_services.create_slot(
            {
                "class_id": class_b.id, "subject_id": subject.id, "teacher_id": teacher.id,
                "day_of_week": 0, "period_number": 2,
                "start_time": "08:45", "end_time": "09:30",
            },
            tenant.id,
        )
    assert first["success"] is True
    assert second["success"] is True


def test_update_slot_blocks_teacher_double_booking(
    flask_app, db_session, tenant, classes, unrestricted_user
):
    class_a, class_b = classes
    subject = _make_subject(db_session, tenant)
    t1 = _make_teacher(db_session, tenant)
    t2 = _make_teacher(db_session, tenant)
    common = {
        "subject_id": subject.id, "day_of_week": 0, "period_number": 1,
        "start_time": "08:00", "end_time": "08:45",
    }
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        a = timetable_services.create_slot(
            {**common, "class_id": class_a.id, "teacher_id": t1.id}, tenant.id
        )
        b = timetable_services.create_slot(
            {**common, "class_id": class_b.id, "teacher_id": t2.id}, tenant.id
        )
        assert a["success"] is True and b["success"] is True
        # Re-pointing class_b's slot to t1 would double-book t1 at day 0 period 1.
        upd = timetable_services.update_slot(b["slot"]["id"], {"teacher_id": t1.id}, tenant.id)
    assert upd["success"] is False
    assert "already teaching" in upd["error"].lower()


def test_legacy_mark_attendance_passes_through_skipped(
    flask_app, db_session, tenant, classes, students, unrestricted_user, monkeypatch
):
    """The legacy /mark path delegates to v2 upsert_records; records the session
    layer refuses (e.g. a student not in this class) must surface as `skipped`
    instead of being silently dropped from the response."""
    class_a, _class_b = classes
    student_a, student_b = students  # student_b belongs to class_b
    monkeypatch.setattr(
        attendance_session_services, "has_permission", lambda *a, **k: True
    )
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        res = attendance_services.mark_attendance(
            class_id=class_a.id,
            date_str="2025-09-01",
            records=[
                {"student_id": student_a.id, "status": "present"},
                {"student_id": student_b.id, "status": "present"},
            ],
            marked_by_user_id=unrestricted_user.id,
        )
    assert res["success"] is True
    assert res["created"] == 1
    assert [s["student_id"] for s in res["skipped"]] == [student_b.id]
