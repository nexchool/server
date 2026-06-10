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

    # Load the tenant's classes once, then answer each question with a single
    # batched query + in-memory set membership — no per-class / per-subject N+1.
    classes = Class.query.filter_by(tenant_id=tenant_id).all()
    class_map = {c.id: c for c in classes}

    def _label(c) -> str:
        return f"{c.name}-{c.section}"

    active_class_subjects = (
        ClassSubject.query.filter_by(tenant_id=tenant_id)
        .filter(ClassSubject.deleted_at.is_(None), ClassSubject.status == "active")
        .all()
    )

    class_ids_with_subjects = {cs.class_id for cs in active_class_subjects}
    classes_without_subjects: List[Dict[str, str]] = [
        {"class_id": c.id, "class_name": _label(c)}
        for c in classes
        if c.id not in class_ids_with_subjects
    ]

    class_ids_with_timetable = {
        cid
        for (cid,) in (
            db.session.query(TimetableVersion.class_id)
            .filter(
                TimetableVersion.tenant_id == tenant_id,
                TimetableVersion.status == "active",
            )
            .distinct()
            .all()
        )
    }
    classes_without_timetable: List[Dict[str, str]] = [
        {"class_id": c.id, "class_name": _label(c)}
        for c in classes
        if c.id not in class_ids_with_timetable
    ]

    cs_ids = [cs.id for cs in active_class_subjects]
    cs_ids_with_primary_teacher: set = set()
    if cs_ids:
        cs_ids_with_primary_teacher = {
            csid
            for (csid,) in (
                db.session.query(ClassSubjectTeacher.class_subject_id)
                .filter(
                    ClassSubjectTeacher.class_subject_id.in_(cs_ids),
                    ClassSubjectTeacher.role == "primary",
                    ClassSubjectTeacher.is_active.is_(True),
                    ClassSubjectTeacher.deleted_at.is_(None),
                )
                .distinct()
                .all()
            )
        }
    class_subjects_without_teacher: List[Dict[str, str]] = [
        {
            "class_subject_id": cs.id,
            "class_id": cs.class_id,
            "class_name": _label(class_map[cs.class_id])
            if cs.class_id in class_map
            else cs.class_id,
        }
        for cs in active_class_subjects
        if cs.id not in cs_ids_with_primary_teacher
    ]

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

    # Attendance health is reported only when the feature is enabled —
    # otherwise it would always read as "pending" since nothing is being marked.
    from core.feature_flags import is_feature_enabled

    attendance_pending: List[Dict[str, str]] = []
    if is_feature_enabled(tenant_id, "attendance"):
        for c in classes:
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
