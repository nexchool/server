"""
Schedule Services

Business logic for today's schedule. Returns slots enriched with:
  - teacher_on_leave: teacher has an approved leave covering today
  - teacher_unavailable: teacher has an availability record blocking this period
  - override: active ScheduleOverride for this slot+date (substitute/activity/cancelled)
"""

from datetime import date, datetime, timedelta
from typing import List, Dict, Optional

from backend.modules.timetable.models import TimetableSlot
from backend.modules.schedule.models import ScheduleOverride


def _time_to_str(t) -> Optional[str]:
    """Format time object to HH:MM string."""
    if t is None:
        return None
    return t.strftime("%H:%M") if hasattr(t, "strftime") else str(t)


def _build_slot_response(
    slot: TimetableSlot,
    today: date,
    override: Optional[ScheduleOverride],
    on_leave_teacher_ids: set,
    unavail_set: set,
) -> Dict:
    """Build enriched slot response dict."""
    class_name = None
    if slot.class_ref:
        class_name = f"{slot.class_ref.name}-{slot.class_ref.section}"

    teacher_on_leave = slot.teacher_id in on_leave_teacher_ids
    teacher_unavailable = (slot.teacher_id, slot.day_of_week, slot.period_number) in unavail_set

    base = {
        "slot_id": slot.id,
        "class_id": slot.class_id,
        "class_name": class_name,
        "subject_id": slot.subject_id,
        "subject_name": slot.subject_ref.name if slot.subject_ref else None,
        "teacher_id": slot.teacher_id,
        "teacher_name": (
            slot.teacher_ref.user.name
            if slot.teacher_ref and slot.teacher_ref.user
            else None
        ),
        "period_number": slot.period_number,
        "start_time": _time_to_str(slot.start_time),
        "end_time": _time_to_str(slot.end_time),
        "teacher_on_leave": teacher_on_leave,
        "teacher_unavailable": teacher_unavailable,
        "needs_coverage": teacher_on_leave or teacher_unavailable,
        "override": override.to_dict() if override else None,
    }
    return base


def _get_today_constraints(tenant_id: str, today: date, day_of_week: int):
    """Return (on_leave_ids, avail_unavail_set) for today."""
    from backend.modules.teachers.models import TeacherLeave, TeacherAvailability

    # Teachers on approved leave today
    leave_rows = TeacherLeave.query.filter_by(
        tenant_id=tenant_id, status=TeacherLeave.STATUS_APPROVED
    ).all()
    on_leave_ids = set()
    for leave in leave_rows:
        if leave.start_date <= today <= leave.end_date:
            on_leave_ids.add(leave.teacher_id)

    # Teacher unavailability for today's weekday (TeacherAvailability uses 1-indexed Mon=1)
    avail_day = day_of_week + 1
    avail_rows = TeacherAvailability.query.filter_by(
        tenant_id=tenant_id,
    ).filter(
        TeacherAvailability.day_of_week == avail_day,
        TeacherAvailability.available == False,
    ).all()
    unavail_set = {(a.teacher_id, day_of_week, a.period_number) for a in avail_rows}

    return on_leave_ids, unavail_set


def _get_overrides_for_date(tenant_id: str, slot_ids: List[str], today: date) -> Dict[str, ScheduleOverride]:
    """Return dict of slot_id → ScheduleOverride for today's date."""
    if not slot_ids:
        return {}
    overrides = ScheduleOverride.query.filter(
        ScheduleOverride.tenant_id == tenant_id,
        ScheduleOverride.slot_id.in_(slot_ids),
        ScheduleOverride.override_date == today,
    ).all()
    return {o.slot_id: o for o in overrides}


def get_todays_schedule(user_id: str, tenant_id: str) -> List[Dict]:
    """
    Get today's enriched schedule for the current user.

    - Teacher: slots where they teach
    - Admin: all slots across all classes today (for coverage management)
    - Student: slots for their class

    Enriched with leave/unavailability detection and active overrides.
    """
    today = date.today()
    day_of_week = today.weekday()  # 0=Monday … 6=Sunday

    from backend.modules.teachers.models import Teacher
    from backend.modules.students.models import Student

    on_leave_ids, unavail_set = _get_today_constraints(tenant_id, today, day_of_week)

    teacher = Teacher.query.filter_by(user_id=user_id, tenant_id=tenant_id).first()
    if teacher:
        slots = (
            TimetableSlot.query.filter_by(
                tenant_id=tenant_id,
                teacher_id=teacher.id,
                day_of_week=day_of_week,
            )
            .order_by(TimetableSlot.period_number)
            .all()
        )
        overrides = _get_overrides_for_date(tenant_id, [s.id for s in slots], today)
        return [
            _build_slot_response(s, today, overrides.get(s.id), on_leave_ids, unavail_set)
            for s in slots
        ]

    student = Student.query.filter_by(user_id=user_id, tenant_id=tenant_id).first()
    if student and student.class_id:
        slots = (
            TimetableSlot.query.filter_by(
                tenant_id=tenant_id,
                class_id=student.class_id,
                day_of_week=day_of_week,
            )
            .order_by(TimetableSlot.period_number)
            .all()
        )
        overrides = _get_overrides_for_date(tenant_id, [s.id for s in slots], today)
        return [
            _build_slot_response(s, today, overrides.get(s.id), on_leave_ids, unavail_set)
            for s in slots
        ]

    return []


def get_all_slots_today(tenant_id: str) -> List[Dict]:
    """Admin view: all timetable slots today, enriched with coverage data."""
    today = date.today()
    day_of_week = today.weekday()

    on_leave_ids, unavail_set = _get_today_constraints(tenant_id, today, day_of_week)
    slots = (
        TimetableSlot.query.filter_by(tenant_id=tenant_id, day_of_week=day_of_week)
        .order_by(TimetableSlot.class_id, TimetableSlot.period_number)
        .all()
    )
    overrides = _get_overrides_for_date(tenant_id, [s.id for s in slots], today)
    return [
        _build_slot_response(s, today, overrides.get(s.id), on_leave_ids, unavail_set)
        for s in slots
    ]


def upsert_override(
    slot_id: str,
    override_date: date,
    override_type: str,
    tenant_id: str,
    created_by: str,
    substitute_teacher_id: Optional[str] = None,
    activity_label: Optional[str] = None,
    note: Optional[str] = None,
) -> Dict:
    """Create or update an override for a slot on a specific date."""
    from sqlalchemy.exc import IntegrityError
    from backend.core.database import db

    valid_types = {ScheduleOverride.TYPE_SUBSTITUTE, ScheduleOverride.TYPE_ACTIVITY, ScheduleOverride.TYPE_CANCELLED}
    if override_type not in valid_types:
        return {"success": False, "error": f"override_type must be one of {sorted(valid_types)}"}

    slot = TimetableSlot.query.filter_by(id=slot_id, tenant_id=tenant_id).first()
    if not slot:
        return {"success": False, "error": "Timetable slot not found"}

    if override_type == ScheduleOverride.TYPE_SUBSTITUTE:
        if not substitute_teacher_id:
            return {"success": False, "error": "substitute_teacher_id is required for substitute overrides"}
        from backend.modules.teachers.models import Teacher
        sub = Teacher.query.filter_by(id=substitute_teacher_id, tenant_id=tenant_id).first()
        if not sub:
            return {"success": False, "error": "Substitute teacher not found"}

    try:
        existing = ScheduleOverride.query.filter_by(
            slot_id=slot_id, override_date=override_date, tenant_id=tenant_id
        ).first()

        if existing:
            existing.override_type = override_type
            existing.substitute_teacher_id = substitute_teacher_id
            existing.activity_label = activity_label
            existing.note = note
            db.session.commit()
            return {"success": True, "override": existing.to_dict()}
        else:
            override = ScheduleOverride(
                tenant_id=tenant_id,
                slot_id=slot_id,
                override_date=override_date,
                override_type=override_type,
                substitute_teacher_id=substitute_teacher_id,
                activity_label=activity_label,
                note=note,
                created_by=created_by,
            )
            db.session.add(override)
            db.session.commit()
            return {"success": True, "override": override.to_dict()}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}


def delete_override(slot_id: str, override_date: date, tenant_id: str) -> Dict:
    """Remove an override (restore original slot)."""
    from backend.core.database import db
    override = ScheduleOverride.query.filter_by(
        slot_id=slot_id, override_date=override_date, tenant_id=tenant_id
    ).first()
    if not override:
        return {"success": False, "error": "No override found for this slot on this date"}
    db.session.delete(override)
    db.session.commit()
    return {"success": True}
