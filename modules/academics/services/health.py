"""Academic configuration health checks."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

from core.database import db
from modules.academics.backbone.models import ClassSubjectTeacher, TimetableEntry, TimetableVersion
from modules.classes.models import Class, ClassSubject

from modules.attendance.session_services import attendance_pending_for_class_today


def compute_health(tenant_id: str) -> Dict[str, Any]:
    today = date.today()

    classes_without_subjects: List[Dict[str, str]] = []
    for c in Class.query.filter_by(tenant_id=tenant_id).all():
        n = (
            ClassSubject.query.filter_by(tenant_id=tenant_id, class_id=c.id)
            .filter(ClassSubject.deleted_at.is_(None), ClassSubject.status == "active")
            .count()
        )
        if n == 0:
            classes_without_subjects.append(
                {"class_id": c.id, "class_name": f"{c.name}-{c.section}"}
            )

    classes_without_timetable: List[Dict[str, str]] = []
    for c in Class.query.filter_by(tenant_id=tenant_id).all():
        has = TimetableVersion.query.filter_by(tenant_id=tenant_id, class_id=c.id).filter(
            TimetableVersion.status == "active"
        ).first()
        if not has:
            classes_without_timetable.append(
                {"class_id": c.id, "class_name": f"{c.name}-{c.section}"}
            )

    class_subjects_without_teacher: List[Dict[str, str]] = []
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
            c = db.session.get(Class, cs.class_id)
            class_subjects_without_teacher.append(
                {
                    "class_subject_id": cs.id,
                    "class_id": cs.class_id,
                    "class_name": f"{c.name}-{c.section}" if c else cs.class_id,
                }
            )

    # Teacher double-booking: same teacher, same dow, same period, two active timetables
    conflicts: List[Dict[str, Any]] = []
    rows = (
        db.session.query(
            TimetableEntry.teacher_id,
            TimetableEntry.day_of_week,
            TimetableEntry.period_number,
            db.func.count(TimetableEntry.id),
        )
        .join(TimetableVersion, TimetableEntry.timetable_version_id == TimetableVersion.id)
        .filter(
            TimetableEntry.tenant_id == tenant_id,
            TimetableVersion.status == "active",
            TimetableEntry.entry_status == "active",
            TimetableEntry.teacher_id.isnot(None),
        )
        .group_by(
            TimetableEntry.teacher_id,
            TimetableEntry.day_of_week,
            TimetableEntry.period_number,
        )
        .having(db.func.count(TimetableEntry.id) > 1)
        .all()
    )
    for tid, dow, pn, cnt in rows:
        conflicts.append(
            {
                "teacher_id": tid,
                "day_of_week": dow,
                "period_number": pn,
                "slot_count": int(cnt),
            }
        )

    attendance_pending: List[Dict[str, str]] = []
    for c in Class.query.filter_by(tenant_id=tenant_id).all():
        if attendance_pending_for_class_today(tenant_id, c.id, today):
            attendance_pending.append(
                {"class_id": c.id, "class_name": f"{c.name}-{c.section}"}
            )

    return {
        "success": True,
        "as_of": today.isoformat(),
        "classes_without_subjects": classes_without_subjects,
        "classes_without_timetable": classes_without_timetable,
        "class_subjects_without_teacher": class_subjects_without_teacher,
        "timetable_conflicts": conflicts,
        "attendance_pending_today": attendance_pending,
    }
