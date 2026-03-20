"""
Timetable Validators

Reusable validation helpers for timetable constraint checking.
Used by:
  - The UI when admins manually create/edit timetable slots.
  - The check_slot_conflicts() function for comprehensive pre-flight checks.

All functions accept an optional tenant_id; when omitted they pull from
the current request context via get_tenant_id().
"""

from datetime import date, timedelta
from typing import Dict, List, Optional

from backend.core.tenant import get_tenant_id
from backend.modules.teachers.models import (
    TeacherAvailability,
    TeacherLeave,
    TeacherWorkloadRule,
)
from .models import TimetableSlot

DAYS_PER_WEEK = 5
MAX_SAME_SUBJECT_PER_DAY = 2
MAX_CONSECUTIVE_SAME_SUBJECT = 2

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday"]


def _monday_of_week(today: Optional[date] = None) -> date:
    d = today or date.today()
    return d - timedelta(days=d.weekday())


# ---------------------------------------------------------------------------
# Individual validators
# ---------------------------------------------------------------------------

def validate_teacher_conflict(
    teacher_id: str,
    day: int,
    period: int,
    tenant_id: Optional[str] = None,
    exclude_slot_id: Optional[str] = None,
) -> Dict:
    """Check if teacher is already assigned to another class at (day, period)."""
    tid = tenant_id or get_tenant_id()
    query = TimetableSlot.query.filter_by(
        tenant_id=tid,
        teacher_id=teacher_id,
        day_of_week=day,
        period_number=period,
    )
    if exclude_slot_id:
        query = query.filter(TimetableSlot.id != exclude_slot_id)

    conflict = query.first()
    if conflict:
        return {
            "valid": False,
            "type": "teacher_double_booking",
            "message": "Teacher is already teaching another class at this time",
            "detail": conflict.to_dict(),
        }
    return {"valid": True}


def validate_teacher_availability(
    teacher_id: str,
    day: int,
    period: int,
    tenant_id: Optional[str] = None,
) -> Dict:
    """
    Check if teacher is marked unavailable at (day, period) or on approved leave.

    TeacherAvailability uses 1-indexed days; this function accepts 0-indexed
    (matching the generator and TimetableSlot convention).
    """
    tid = tenant_id or get_tenant_id()
    day_1indexed = day + 1

    avail = TeacherAvailability.query.filter_by(
        tenant_id=tid,
        teacher_id=teacher_id,
        day_of_week=day_1indexed,
        period_number=period,
    ).first()

    if avail and not avail.available:
        return {
            "valid": False,
            "type": "teacher_unavailable",
            "message": (
                f"Teacher is not available on {DAY_NAMES[day] if day < len(DAY_NAMES) else day} "
                f"period {period}"
            ),
        }

    monday = _monday_of_week()
    slot_date = monday + timedelta(days=day)
    leave = TeacherLeave.query.filter(
        TeacherLeave.tenant_id == tid,
        TeacherLeave.teacher_id == teacher_id,
        TeacherLeave.status == TeacherLeave.STATUS_APPROVED,
        TeacherLeave.start_date <= slot_date,
        TeacherLeave.end_date >= slot_date,
    ).first()

    if leave:
        return {
            "valid": False,
            "type": "teacher_on_leave",
            "message": (
                f"Teacher is on approved leave on "
                f"{DAY_NAMES[day] if day < len(DAY_NAMES) else day} "
                f"({slot_date.isoformat()})"
            ),
        }

    return {"valid": True}


def validate_teacher_workload(
    teacher_id: str,
    day: int,
    tenant_id: Optional[str] = None,
    exclude_slot_id: Optional[str] = None,
) -> Dict:
    """Check if adding one more period would exceed the teacher's daily limit."""
    tid = tenant_id or get_tenant_id()

    rule = TeacherWorkloadRule.query.filter_by(
        tenant_id=tid,
        teacher_id=teacher_id,
    ).first()
    max_daily = rule.max_periods_per_day if rule else 6

    query = TimetableSlot.query.filter_by(
        tenant_id=tid,
        teacher_id=teacher_id,
        day_of_week=day,
    )
    if exclude_slot_id:
        query = query.filter(TimetableSlot.id != exclude_slot_id)

    current_count = query.count()

    if current_count >= max_daily:
        return {
            "valid": False,
            "type": "teacher_daily_limit_exceeded",
            "message": (
                f"Teacher already has {current_count} period(s) on "
                f"{DAY_NAMES[day] if day < len(DAY_NAMES) else day} "
                f"(max {max_daily})"
            ),
        }
    return {"valid": True}


def validate_subject_daily_limit(
    subject_id: str,
    day: int,
    class_id: str,
    tenant_id: Optional[str] = None,
    exclude_slot_id: Optional[str] = None,
) -> Dict:
    """Check if subject already appears MAX_SAME_SUBJECT_PER_DAY times on this day."""
    tid = tenant_id or get_tenant_id()

    query = TimetableSlot.query.filter_by(
        tenant_id=tid,
        class_id=class_id,
        subject_id=subject_id,
        day_of_week=day,
    )
    if exclude_slot_id:
        query = query.filter(TimetableSlot.id != exclude_slot_id)

    current_count = query.count()

    if current_count >= MAX_SAME_SUBJECT_PER_DAY:
        return {
            "valid": False,
            "type": "subject_daily_limit_exceeded",
            "message": (
                f"Subject already appears {current_count} time(s) on "
                f"{DAY_NAMES[day] if day < len(DAY_NAMES) else day} "
                f"(max {MAX_SAME_SUBJECT_PER_DAY})"
            ),
        }
    return {"valid": True}


def validate_subject_consecutive(
    subject_id: str,
    day: int,
    period: int,
    class_id: str,
    tenant_id: Optional[str] = None,
    exclude_slot_id: Optional[str] = None,
) -> Dict:
    """
    Check if placing this subject at (day, period) would create more than
    MAX_CONSECUTIVE_SAME_SUBJECT consecutive periods of the same subject.
    """
    tid = tenant_id or get_tenant_id()

    query = TimetableSlot.query.filter_by(
        tenant_id=tid,
        class_id=class_id,
        day_of_week=day,
    )
    if exclude_slot_id:
        query = query.filter(TimetableSlot.id != exclude_slot_id)

    slots = query.all()
    period_subject = {s.period_number: s.subject_id for s in slots}
    period_subject[period] = subject_id

    streak = 1
    p = period - 1
    while p >= 1 and period_subject.get(p) == subject_id:
        streak += 1
        p -= 1
    p = period + 1
    while period_subject.get(p) == subject_id:
        streak += 1
        p += 1

    if streak > MAX_CONSECUTIVE_SAME_SUBJECT:
        return {
            "valid": False,
            "type": "subject_consecutive_exceeded",
            "message": (
                f"Would create {streak} consecutive periods of the same subject "
                f"(max {MAX_CONSECUTIVE_SAME_SUBJECT})"
            ),
        }
    return {"valid": True}


# ---------------------------------------------------------------------------
# Comprehensive conflict checker
# ---------------------------------------------------------------------------

def check_slot_conflicts(
    class_id: str,
    teacher_id: str,
    subject_id: str,
    day: int,
    period: int,
    tenant_id: Optional[str] = None,
    exclude_slot_id: Optional[str] = None,
) -> Dict:
    """
    Run all constraint validations for a proposed slot placement.

    Returns:
        {
            "has_conflict": bool,
            "conflicts": [
                {
                    "type": "teacher_double_booking" | "teacher_unavailable" |
                            "teacher_on_leave" | "teacher_daily_limit_exceeded" |
                            "subject_daily_limit_exceeded",
                    "message": str,
                    "class_id": str,
                    "day": int,
                    "period": int,
                }
            ]
        }
    """
    tid = tenant_id or get_tenant_id()
    conflicts: List[Dict] = []

    result = validate_teacher_conflict(teacher_id, day, period, tid, exclude_slot_id)
    if not result["valid"]:
        conflicts.append({
            "type": result["type"],
            "message": result["message"],
            "class_id": result.get("detail", {}).get("class_id"),
            "day": day,
            "period": period,
        })

    result = validate_teacher_availability(teacher_id, day, period, tid)
    if not result["valid"]:
        conflicts.append({
            "type": result["type"],
            "message": result["message"],
            "class_id": class_id,
            "day": day,
            "period": period,
        })

    result = validate_teacher_workload(teacher_id, day, tid, exclude_slot_id)
    if not result["valid"]:
        conflicts.append({
            "type": result["type"],
            "message": result["message"],
            "class_id": class_id,
            "day": day,
            "period": period,
        })

    result = validate_subject_daily_limit(subject_id, day, class_id, tid, exclude_slot_id)
    if not result["valid"]:
        conflicts.append({
            "type": result["type"],
            "message": result["message"],
            "class_id": class_id,
            "day": day,
            "period": period,
        })

    result = validate_subject_consecutive(subject_id, day, period, class_id, tid, exclude_slot_id)
    if not result["valid"]:
        conflicts.append({
            "type": result["type"],
            "message": result["message"],
            "class_id": class_id,
            "day": day,
            "period": period,
        })

    return {
        "has_conflict": len(conflicts) > 0,
        "conflicts": conflicts,
    }
