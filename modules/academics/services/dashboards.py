"""Teacher today schedule, student dashboard, admin academic dashboard."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

from backend.core.database import db
from backend.modules.academics.backbone.models import (
    AttendanceSession,
    ClassSubjectTeacher,
    TimetableEntry,
    TimetableVersion,
)
from backend.modules.classes.models import Class, ClassSubject
from backend.modules.students.models import Student
from backend.modules.teachers.models import Teacher

from backend.modules.attendance.session_services import (
    attendance_pending_for_class_today,
    student_history_v2,
)

from .common import class_display_name, get_class_for_tenant
from .health import compute_health
from .timetable_v2 import _bell_period_map, _serialize_entry


def _today_weekday() -> int:
    return date.today().isoweekday()


def teacher_today_schedule(tenant_id: str, user_id: str) -> Dict[str, Any]:
    teacher = Teacher.query.filter_by(tenant_id=tenant_id, user_id=user_id).first()
    if not teacher:
        return {"success": False, "error": "Teacher profile not found"}

    today = date.today()
    dow = _today_weekday()

    entries = (
        db.session.query(TimetableEntry, TimetableVersion, Class)
        .join(TimetableVersion, TimetableEntry.timetable_version_id == TimetableVersion.id)
        .join(Class, TimetableVersion.class_id == Class.id)
        .filter(
            TimetableEntry.tenant_id == tenant_id,
            TimetableEntry.teacher_id == teacher.id,
            TimetableEntry.day_of_week == dow,
            TimetableEntry.entry_status == "active",
            TimetableVersion.status == "active",
            Class.tenant_id == tenant_id,
        )
        .order_by(TimetableEntry.period_number)
        .all()
    )

    lectures: List[Dict[str, Any]] = []
    for e, ver, cls in entries:
        bell_map = _bell_period_map(tenant_id, ver.bell_schedule_id)
        slot = _serialize_entry(e, bell_map)
        slot["class_id"] = cls.id
        slot["class_name"] = class_display_name(cls)
        slot["attendance_pending_today"] = attendance_pending_for_class_today(tenant_id, cls.id, today)
        lectures.append(slot)

    next_lecture = lectures[0] if lectures else None

    return {
        "success": True,
        "date": today.isoformat(),
        "lectures": lectures,
        "next_lecture": next_lecture,
    }


def student_dashboard(tenant_id: str, user_id: str) -> Dict[str, Any]:
    st = Student.query.filter_by(tenant_id=tenant_id, user_id=user_id).first()
    if not st:
        return {"success": False, "error": "Student profile not found"}

    cls = get_class_for_tenant(st.class_id, tenant_id) if st.class_id else None
    dow = _today_weekday()

    week_preview: List[Dict[str, Any]] = []
    today_schedule: List[Dict[str, Any]] = []

    if st.class_id:
        v = (
            TimetableVersion.query.filter_by(tenant_id=tenant_id, class_id=st.class_id)
            .filter(TimetableVersion.status == "active")
            .first()
        )
        if v:
            bell_map = _bell_period_map(tenant_id, v.bell_schedule_id)
            rows = (
                TimetableEntry.query.filter_by(tenant_id=tenant_id, timetable_version_id=v.id)
                .filter(TimetableEntry.entry_status == "active")
                .order_by(TimetableEntry.day_of_week, TimetableEntry.period_number)
                .all()
            )
            for e in rows:
                item = _serialize_entry(e, bell_map)
                item["day_of_week"] = e.day_of_week
                week_preview.append(item)
                if e.day_of_week == dow:
                    today_schedule.append(item)

    hist = student_history_v2(tenant_id, st.id, month=None)
    att = hist.get("data", {}) if hist.get("success") else {}

    return {
        "success": True,
        "student_id": st.id,
        "class_id": st.class_id,
        "class_name": class_display_name(cls) if cls else None,
        "today_schedule": today_schedule,
        "weekly_timetable_preview": week_preview,
        "attendance_summary": {
            "total_days": att.get("total_days", 0),
            "present": att.get("present", 0),
            "percentage": att.get("percentage", 0),
            "source": att.get("source", "sessions_v2"),
        },
    }


def admin_academic_dashboard(tenant_id: str) -> Dict[str, Any]:
    today = date.today()
    dow = _today_weekday()

    total_classes = Class.query.filter_by(tenant_id=tenant_id).count()

    lecture_count = (
        db.session.query(TimetableEntry)
        .join(TimetableVersion, TimetableEntry.timetable_version_id == TimetableVersion.id)
        .filter(
            TimetableEntry.tenant_id == tenant_id,
            TimetableEntry.day_of_week == dow,
            TimetableEntry.entry_status == "active",
            TimetableVersion.status == "active",
        )
        .count()
    )

    pending_sessions = (
        AttendanceSession.query.filter(
            AttendanceSession.tenant_id == tenant_id,
            AttendanceSession.session_date == today,
            AttendanceSession.status != "finalized",
            AttendanceSession.deleted_at.is_(None),
        ).count()
    )

    classes_without_timetable = 0
    for c in Class.query.filter_by(tenant_id=tenant_id).all():
        has = TimetableVersion.query.filter_by(tenant_id=tenant_id, class_id=c.id).filter(
            TimetableVersion.status == "active"
        ).first()
        if not has:
            classes_without_timetable += 1

    subjects_without_teacher = 0
    for cs in (
        ClassSubject.query.filter_by(tenant_id=tenant_id)
        .filter(ClassSubject.deleted_at.is_(None), ClassSubject.status == "active")
        .all()
    ):
        prim = (
            ClassSubjectTeacher.query.filter(
                ClassSubjectTeacher.class_subject_id == cs.id,
                ClassSubjectTeacher.role == "primary",
                ClassSubjectTeacher.is_active.is_(True),
                ClassSubjectTeacher.deleted_at.is_(None),
            ).first()
        )
        if not prim:
            subjects_without_teacher += 1

    health = compute_health(tenant_id)

    return {
        "success": True,
        "date": today.isoformat(),
        "total_classes": total_classes,
        "lectures_today": lecture_count,
        "pending_attendance_sessions": pending_sessions,
        "classes_without_timetable": classes_without_timetable,
        "class_subjects_without_primary_teacher": subjects_without_teacher,
        "timetable_conflicts": health.get("timetable_conflicts", []),
    }


def health_report(tenant_id: str) -> Dict[str, Any]:
    return compute_health(tenant_id)
