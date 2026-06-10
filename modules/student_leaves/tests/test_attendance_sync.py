"""Tests for _sync_attendance_rows / _unsync_attendance_rows (Task 5).

Covers:
  - one row per school day in range
  - skipping weekends
  - skipping holidays
  - overwriting an existing manual attendance row (status replacement)
"""

from datetime import date, timedelta

from core.database import db
from modules.attendance.models import Attendance
from modules.student_leaves.services import create_request, approve


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_sync_creates_one_row_per_school_day(
    tenant_ctx, student_user, class_with_teacher
):
    """3-day range (Mon-Wed) with no holidays produces 3 attendance rows."""
    target_monday = _next_weekday(weeks_ahead=1, weekday=0)
    end_d = target_monday + timedelta(days=2)  # Mon, Tue, Wed
    payload = {
        "student_id": student_user.student.id,
        "leave_type": "sick",
        "start_date": target_monday.isoformat(),
        "end_date": end_d.isoformat(),
        "reason": "x",
    }
    leave = create_request(payload, actor_user_id=student_user.id)
    approve(leave.id, actor_user_id=class_with_teacher.teacher_row.user_id)

    rows = db.session.query(Attendance).filter_by(leave_id=leave.id).all()
    assert len(rows) == 3
    for r in rows:
        assert r.status == "leave"
        assert r.student_id == student_user.student.id


def test_sync_skips_weekends(tenant_ctx, student_user, class_with_teacher):
    """Range Fri-Mon produces 2 rows (Fri, Mon), skipping Sat/Sun."""
    target_friday = _next_weekday(weeks_ahead=1, weekday=4)
    end_d = target_friday + timedelta(days=3)  # Monday
    payload = {
        "student_id": student_user.student.id,
        "leave_type": "sick",
        "start_date": target_friday.isoformat(),
        "end_date": end_d.isoformat(),
        "reason": "x",
    }
    leave = create_request(payload, actor_user_id=student_user.id)
    approve(leave.id, actor_user_id=class_with_teacher.teacher_row.user_id)

    rows = db.session.query(Attendance).filter_by(leave_id=leave.id).all()
    dates = sorted([r.date for r in rows])
    assert dates == [target_friday, end_d]


def test_sync_skips_holidays(
    tenant_ctx, student_user, class_with_teacher, holiday_in_range
):
    """Holiday date does not get an attendance row; surrounding school days do."""
    target_date = holiday_in_range.date  # Monday, 2 weeks ahead
    # 2-day range: holiday + next school day (Tuesday)
    next_day = _next_school_day(target_date + timedelta(days=1))
    payload = {
        "student_id": student_user.student.id,
        "leave_type": "sick",
        "start_date": target_date.isoformat(),
        "end_date": next_day.isoformat(),
        "reason": "x",
    }
    leave = create_request(payload, actor_user_id=student_user.id)
    approve(leave.id, actor_user_id=class_with_teacher.teacher_row.user_id)

    rows = db.session.query(Attendance).filter_by(leave_id=leave.id).all()
    dates = sorted([r.date for r in rows])
    assert target_date not in dates
    assert next_day in dates


def test_sync_overwrites_prior_attendance_status(
    tenant_ctx, student_user, class_with_teacher
):
    """If a manual attendance row already exists for the date, sync replaces
    its status with 'leave' and binds leave_id."""
    target_date = _next_weekday(weeks_ahead=1, weekday=0)  # Monday
    existing = Attendance(
        tenant_id=class_with_teacher.tenant_id,
        date=target_date,
        class_id=class_with_teacher.id,
        student_id=student_user.student.id,
        status="absent",
        marked_by=class_with_teacher.teacher_row.user_id,
    )
    db.session.add(existing)
    db.session.commit()
    existing_id = existing.id

    payload = {
        "student_id": student_user.student.id,
        "leave_type": "sick",
        "start_date": target_date.isoformat(),
        "end_date": target_date.isoformat(),
        "reason": "x",
    }
    leave = create_request(payload, actor_user_id=student_user.id)
    approve(leave.id, actor_user_id=class_with_teacher.teacher_row.user_id)

    db.session.expire_all()
    refetched = db.session.query(Attendance).filter_by(id=existing_id).first()
    assert refetched.status == "leave"
    assert refetched.leave_id == leave.id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _next_weekday(*, weeks_ahead: int = 0, weekday: int = 0) -> date:
    """Return the next instance of the given weekday (0=Mon..6=Sun), offset by
    N additional weeks ahead."""
    today = date.today()
    days_ahead = (weekday - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return today + timedelta(days=days_ahead + 7 * weeks_ahead)


def _next_school_day(d: date) -> date:
    """Advance d forward until it lands on a weekday."""
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d
