"""
Schedule Services

Business logic for today's schedule. Returns slots enriched with:
  - teacher_on_leave: teacher has an approved leave covering today
  - teacher_unavailable: teacher has an availability record blocking this period
  - override: active ScheduleOverride for this slot+date (substitute/activity/cancelled)

TimetableEntry + TimetableVersion are the source of truth (migration 023).
The parallel `timetable_slots` table this module used to fall back to is gone
(migration 096); ``slot_id`` survives only as the name of the id in the API
payload, and it carries a timetable entry id.
"""
from shared.safe_error import safe_error

from datetime import date
from typing import List, Dict, Optional, Tuple

from core.branch_scope import assert_class_allowed
from core.database import db
from modules.academics.backbone.models import TimetableEntry, TimetableVersion
from modules.academics.services.common import class_display_name
from modules.academics.services.timetable_v2 import _bell_period_map
from modules.classes.models import Class
from modules.schedule.models import ScheduleOverride
from core.school_time import school_today


def _time_to_str(t) -> Optional[str]:
    """Format time object to HH:MM string."""
    if t is None:
        return None
    return t.strftime("%H:%M") if hasattr(t, "strftime") else str(t)


def _get_today_constraints(tenant_id: str, today: date, day_of_week: int):
    """Return (on_leave_ids, avail_unavail_set) for today."""
    from modules.teachers.models import TeacherLeave, TeacherAvailability

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


def _get_overrides_for_date(
    tenant_id: str,
    today: date,
    entry_ids: Optional[List[str]] = None,
) -> Dict[str, ScheduleOverride]:
    """Overrides on this date, keyed by the timetable entry they cover."""
    entry_ids = entry_ids or []
    if not entry_ids:
        return {}
    rows = ScheduleOverride.query.filter(
        ScheduleOverride.tenant_id == tenant_id,
        ScheduleOverride.override_date == today,
        ScheduleOverride.timetable_entry_id.in_(entry_ids),
    ).all()
    return {o.timetable_entry_id: o for o in rows if o.timetable_entry_id}


def _build_entry_schedule_response(
    e: TimetableEntry,
    cls: Class,
    bell_map: Dict,
    today: date,
    override: Optional[ScheduleOverride],
    on_leave_teacher_ids: set,
    unavail_set: set,
    py_weekday: int,
) -> Dict:
    """Build enriched slot dict for TimetableEntry; ``slot_id`` is the entry id (API contract)."""
    cs = e.class_subject
    subj = cs.subject_ref if cs else None
    class_name = class_display_name(cls) if cls else None
    subject_id = cs.subject_id if cs else None
    tid = e.teacher_id
    teacher_on_leave = tid in on_leave_teacher_ids if tid else False
    teacher_unavailable = (tid, py_weekday, e.period_number) in unavail_set if tid else False
    bp = bell_map.get(e.period_number) if bell_map else None
    start_time = None
    end_time = None
    if bp:
        start_time = _time_to_str(bp.get("starts_at"))
        end_time = _time_to_str(bp.get("ends_at"))
    return {
        "slot_id": e.id,
        "class_id": cls.id,
        "class_name": class_name,
        "subject_id": subject_id,
        "subject_name": subj.name if subj else None,
        "teacher_id": tid,
        # The name belongs to the Person, not the login (ADR-001) — a teacher
        # may have no account at all (migration 094).
        "teacher_name": (
            e.teacher.staff.person.full_name
            if e.teacher and e.teacher.staff and e.teacher.staff.person
            else None
        ),
        "period_number": e.period_number,
        "start_time": start_time,
        "end_time": end_time,
        "teacher_on_leave": teacher_on_leave,
        "teacher_unavailable": teacher_unavailable,
        "needs_coverage": teacher_on_leave or teacher_unavailable,
        "override": override.to_dict() if override else None,
    }


def _teacher_entries_today_v2(
    tenant_id: str, teacher_id: str, dow_iso: int
) -> List[Tuple[TimetableEntry, TimetableVersion, Class]]:
    return (
        db.session.query(TimetableEntry, TimetableVersion, Class)
        .join(TimetableVersion, TimetableEntry.timetable_version_id == TimetableVersion.id)
        .join(Class, TimetableVersion.class_id == Class.id)
        .filter(
            TimetableEntry.tenant_id == tenant_id,
            TimetableEntry.teacher_id == teacher_id,
            TimetableEntry.day_of_week == dow_iso,
            TimetableEntry.entry_status == "active",
            TimetableVersion.status == "active",
            Class.tenant_id == tenant_id,
        )
        .order_by(TimetableEntry.period_number)
        .all()
    )


def _student_entries_today_v2(
    tenant_id: str, class_id: str, dow_iso: int
) -> List[Tuple[TimetableEntry, TimetableVersion, Class]]:
    v = (
        TimetableVersion.query.filter_by(tenant_id=tenant_id, class_id=class_id)
        .filter(TimetableVersion.status == "active")
        .first()
    )
    if not v:
        return []
    rows = (
        db.session.query(TimetableEntry, TimetableVersion, Class)
        .join(TimetableVersion, TimetableEntry.timetable_version_id == TimetableVersion.id)
        .join(Class, TimetableVersion.class_id == Class.id)
        .filter(
            TimetableEntry.tenant_id == tenant_id,
            TimetableEntry.timetable_version_id == v.id,
            TimetableEntry.day_of_week == dow_iso,
            TimetableEntry.entry_status == "active",
            Class.tenant_id == tenant_id,
        )
        .order_by(TimetableEntry.period_number)
        .all()
    )
    return rows


def _all_entries_today_v2(tenant_id: str, dow_iso: int) -> List[Tuple[TimetableEntry, TimetableVersion, Class]]:
    return (
        db.session.query(TimetableEntry, TimetableVersion, Class)
        .join(TimetableVersion, TimetableEntry.timetable_version_id == TimetableVersion.id)
        .join(Class, TimetableVersion.class_id == Class.id)
        .filter(
            TimetableEntry.tenant_id == tenant_id,
            TimetableEntry.day_of_week == dow_iso,
            TimetableEntry.entry_status == "active",
            TimetableVersion.status == "active",
            Class.tenant_id == tenant_id,
        )
        .order_by(Class.name, Class.section, TimetableEntry.period_number)
        .all()
    )


def get_todays_schedule(user_id: str, tenant_id: str) -> List[Dict]:
    """
    Get today's enriched schedule for the current user.

    - Teacher: slots where they teach
    - Admin: all slots across all classes today (for coverage management)
    - Student: slots for their class

    Enriched with leave/unavailability detection and active overrides.
    """
    today = school_today()
    day_of_week = today.weekday()  # 0=Monday … 6=Sunday (legacy slots + availability tuples)
    dow_iso = today.isoweekday()  # 1=Monday … 7=Sunday (TimetableEntry)

    from modules.teachers.models import Teacher
    from modules.students.models import Student

    on_leave_ids, unavail_set = _get_today_constraints(tenant_id, today, day_of_week)

    teacher = Teacher.query.filter_by(user_id=user_id, tenant_id=tenant_id).first()
    if teacher:
        v2_rows = _teacher_entries_today_v2(tenant_id, teacher.id, dow_iso)
        if v2_rows:
            entry_ids = [e.id for e, _, _ in v2_rows]
            overrides = _get_overrides_for_date(tenant_id, today, entry_ids=entry_ids)
            return [
                _build_entry_schedule_response(
                    e,
                    cls,
                    _bell_period_map(tenant_id, ver.bell_schedule_id),
                    today,
                    overrides.get(e.id),
                    on_leave_ids,
                    unavail_set,
                    day_of_week,
                )
                for e, ver, cls in v2_rows
            ]
        return []

    from modules.students.services import student_for_user

    student = student_for_user(user_id, tenant_id)
    if student and student.class_id:
        v2_rows = _student_entries_today_v2(tenant_id, student.class_id, dow_iso)
        if v2_rows:
            entry_ids = [e.id for e, _, _ in v2_rows]
            overrides = _get_overrides_for_date(tenant_id, today, entry_ids=entry_ids)
            return [
                _build_entry_schedule_response(
                    e,
                    cls,
                    _bell_period_map(tenant_id, ver.bell_schedule_id),
                    today,
                    overrides.get(e.id),
                    on_leave_ids,
                    unavail_set,
                    day_of_week,
                )
                for e, ver, cls in v2_rows
            ]

    return []


def get_all_slots_today(tenant_id: str) -> List[Dict]:
    """Admin view: all timetable slots today, enriched with coverage data."""
    today = school_today()
    day_of_week = today.weekday()
    dow_iso = today.isoweekday()

    on_leave_ids, unavail_set = _get_today_constraints(tenant_id, today, day_of_week)
    v2_rows = _all_entries_today_v2(tenant_id, dow_iso)
    if v2_rows:
        entry_ids = [e.id for e, _, _ in v2_rows]
        overrides = _get_overrides_for_date(tenant_id, today, entry_ids=entry_ids)
        return [
            _build_entry_schedule_response(
                e,
                cls,
                _bell_period_map(tenant_id, ver.bell_schedule_id),
                today,
                overrides.get(e.id),
                on_leave_ids,
                unavail_set,
                day_of_week,
            )
            for e, ver, cls in v2_rows
        ]
    return []


def _override_target_class_id(
    tenant_id: str,
    entry: Optional[TimetableEntry],
) -> Optional[str]:
    """The class an override target reaches, through its TimetableVersion."""
    if entry is None:
        return None
    ver = TimetableVersion.query.filter_by(
        id=entry.timetable_version_id, tenant_id=tenant_id
    ).first()
    return ver.class_id if ver else None


def _assert_override_target_in_branch(
    tenant_id: str,
    entry: Optional[TimetableEntry],
) -> None:
    """Branch-scope guard for override targets. No-op when unrestricted."""
    class_id = _override_target_class_id(tenant_id, entry)
    if class_id is not None:
        assert_class_allowed(class_id)


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
    valid_types = {ScheduleOverride.TYPE_SUBSTITUTE, ScheduleOverride.TYPE_ACTIVITY, ScheduleOverride.TYPE_CANCELLED}
    if override_type not in valid_types:
        return {"success": False, "error": f"override_type must be one of {sorted(valid_types)}"}

    entry = TimetableEntry.query.filter_by(id=slot_id, tenant_id=tenant_id).first()
    if not entry:
        return {"success": False, "error": "Timetable entry not found"}

    # Branch scope: an override hangs off an entry that reaches a branch
    # through its class. Restricted sub-admins may only override in-branch
    # classes. No-op when unrestricted.
    _assert_override_target_in_branch(tenant_id, entry)

    if override_type == ScheduleOverride.TYPE_SUBSTITUTE:
        if not substitute_teacher_id:
            return {"success": False, "error": "substitute_teacher_id is required for substitute overrides"}
        from modules.teachers.models import Teacher
        sub = Teacher.query.filter_by(id=substitute_teacher_id, tenant_id=tenant_id).first()
        if not sub:
            return {"success": False, "error": "Substitute teacher not found"}

    try:
        existing = ScheduleOverride.query.filter_by(
            timetable_entry_id=entry.id, override_date=override_date, tenant_id=tenant_id
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
                timetable_entry_id=entry.id,
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
        return {"success": False, "error": safe_error(e)}


def delete_override(slot_id: str, override_date: date, tenant_id: str) -> Dict:
    """Remove an override (restore the scheduled period).

    ``slot_id`` is the timetable entry id — the name the API payload has
    always used for it.
    """
    override = ScheduleOverride.query.filter_by(
        timetable_entry_id=slot_id, override_date=override_date, tenant_id=tenant_id
    ).first()
    if not override:
        return {"success": False, "error": "No override found for this slot on this date"}

    # Branch scope: resolve the override's entry to its class and assert.
    # No-op when unrestricted.
    entry = (
        TimetableEntry.query.filter_by(id=override.timetable_entry_id, tenant_id=tenant_id).first()
        if override.timetable_entry_id
        else None
    )
    _assert_override_target_in_branch(tenant_id, entry)

    db.session.delete(override)
    db.session.commit()
    return {"success": True}
