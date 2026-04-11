"""
Daily attendance sessions (AttendanceSession + AttendanceRecord).

Legacy flat `attendance` table remains for old reads; new writes use sessions.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import IntegrityError

from core.database import db
from modules.academics.backbone.models import (
    AttendanceRecord,
    AttendanceSession,
    ClassTeacherAssignment,
)
from modules.classes.models import Class
from modules.holidays.services import get_holiday_for_date
from modules.rbac.services import has_permission
from modules.students.models import Student
from modules.teachers.models import Teacher


def serialize_session(s: AttendanceSession, class_name: Optional[str] = None) -> Dict[str, Any]:
    return {
        "id": s.id,
        "class_id": s.class_id,
        "class_name": class_name,
        "session_date": s.session_date.isoformat() if s.session_date else None,
        "status": s.status,
        "marked_by_user_id": s.marked_by_user_id,
        "assigned_marker_teacher_id": s.assigned_marker_teacher_id,
        "class_teacher_assignment_id": s.class_teacher_assignment_id,
        "attendance_source": s.attendance_source,
        "taken_by_role": s.taken_by_role,
        "notes": s.notes,
        "marked_at": s.marked_at.isoformat() if s.marked_at else None,
        "finalized_at": s.finalized_at.isoformat() if s.finalized_at else None,
        "finalized_by_user_id": s.finalized_by_user_id,
    }


def _teacher_for_user(tenant_id: str, user_id: str) -> Optional[Teacher]:
    return Teacher.query.filter_by(tenant_id=tenant_id, user_id=user_id).first()


def _primary_class_teacher_assignment(
    tenant_id: str, class_id: str, on_date: date
) -> Optional[ClassTeacherAssignment]:
    rows = (
        ClassTeacherAssignment.query.filter_by(tenant_id=tenant_id, class_id=class_id)
        .filter(
            ClassTeacherAssignment.role == "primary",
            ClassTeacherAssignment.is_active.is_(True),
            ClassTeacherAssignment.deleted_at.is_(None),
        )
        .all()
    )
    for r in rows:
        ef, et = r.effective_from, r.effective_to
        if ef and on_date < ef:
            continue
        if et and on_date > et:
            continue
        return r
    return None


def can_user_mark_session(
    tenant_id: str,
    user_id: str,
    session: AttendanceSession,
    class_id: str,
) -> bool:
    if has_permission(user_id, "attendance.manage"):
        return True

    t = _teacher_for_user(tenant_id, user_id)
    if not t:
        return False

    if session.assigned_marker_teacher_id and session.assigned_marker_teacher_id == t.id:
        return True

    cta = _primary_class_teacher_assignment(tenant_id, class_id, session.session_date)
    if cta and cta.teacher_id == t.id and cta.allow_attendance_marking:
        return True

    # Legacy: class.teacher_id (User) matches
    cls = Class.query.filter_by(id=class_id, tenant_id=tenant_id).first()
    if cls and cls.teacher_id == user_id:
        return True

    return False


def get_eligible_classes_for_user(tenant_id: str, user_id: str, session_day: date) -> Dict[str, Any]:
    """Classes the user may mark attendance for on session_day."""
    items: List[Dict[str, Any]] = []

    if has_permission(user_id, "attendance.manage"):
        classes = Class.query.filter_by(tenant_id=tenant_id).order_by(Class.name, Class.section).all()
        for c in classes:
            items.append(
                {
                    "class_id": c.id,
                    "class_name": f"{c.name}-{c.section}",
                    "reason": "admin",
                    "can_mark": True,
                }
            )
        return {"success": True, "items": items}

    teacher = _teacher_for_user(tenant_id, user_id)
    if not teacher:
        return {"success": True, "items": []}

    # Primary assignments with attendance authority
    ctas = (
        ClassTeacherAssignment.query.filter_by(tenant_id=tenant_id, teacher_id=teacher.id)
        .filter(
            ClassTeacherAssignment.is_active.is_(True),
            ClassTeacherAssignment.deleted_at.is_(None),
            ClassTeacherAssignment.allow_attendance_marking.is_(True),
        )
        .all()
    )
    seen = set()
    for cta in ctas:
        ef, et = cta.effective_from, cta.effective_to
        if ef and session_day < ef:
            continue
        if et and session_day > et:
            continue
        c = Class.query.get(cta.class_id)
        if not c:
            continue
        seen.add(c.id)
        items.append(
            {
                "class_id": c.id,
                "class_name": f"{c.name}-{c.section}",
                "reason": "class_teacher",
                "can_mark": True,
            }
        )

    # Delegated marker for today
    delegated = AttendanceSession.query.filter(
        AttendanceSession.tenant_id == tenant_id,
        AttendanceSession.session_date == session_day,
        AttendanceSession.assigned_marker_teacher_id == teacher.id,
        AttendanceSession.deleted_at.is_(None),
    ).all()
    for s in delegated:
        if s.class_id in seen:
            continue
        c = Class.query.get(s.class_id)
        if not c:
            continue
        items.append(
            {
                "class_id": c.id,
                "class_name": f"{c.name}-{c.section}",
                "reason": "delegated",
                "can_mark": True,
            }
        )
        seen.add(c.id)

    # Legacy class teacher user pointer
    legacy = Class.query.filter_by(tenant_id=tenant_id, teacher_id=user_id).all()
    for c in legacy:
        if c.id in seen:
            continue
        items.append(
            {
                "class_id": c.id,
                "class_name": f"{c.name}-{c.section}",
                "reason": "legacy_class_teacher",
                "can_mark": True,
            }
        )

    items.sort(key=lambda x: x["class_name"])
    return {"success": True, "items": items}


def get_or_create_session(
    tenant_id: str,
    class_id: str,
    session_date: date,
    user_id: str,
    assigned_marker_teacher_id: Optional[str] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    cls = Class.query.filter_by(id=class_id, tenant_id=tenant_id).first()
    if not cls:
        return {"success": False, "error": "Class not found"}

    holiday = get_holiday_for_date(session_date, tenant_id)
    if holiday:
        return {
            "success": False,
            "error": "Attendance cannot be taken on a holiday",
            "holiday": holiday,
        }

    existing = (
        AttendanceSession.query.filter_by(
            tenant_id=tenant_id, class_id=class_id, session_date=session_date
        )
        .filter(AttendanceSession.deleted_at.is_(None))
        .first()
    )
    if existing:
        return {
            "success": True,
            "session": serialize_session(existing, f"{cls.name}-{cls.section}"),
            "created": False,
        }

    cta = _primary_class_teacher_assignment(tenant_id, class_id, session_date)

    s = AttendanceSession(
        tenant_id=tenant_id,
        class_id=class_id,
        session_date=session_date,
        status="draft",
        assigned_marker_teacher_id=assigned_marker_teacher_id,
        class_teacher_assignment_id=cta.id if cta else None,
        notes=notes,
        attendance_source="manual",
        created_by=user_id,
        updated_by=user_id,
    )
    db.session.add(s)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing = (
            AttendanceSession.query.filter_by(
                tenant_id=tenant_id, class_id=class_id, session_date=session_date
            )
            .filter(AttendanceSession.deleted_at.is_(None))
            .first()
        )
        if existing:
            return {
                "success": True,
                "session": serialize_session(existing, f"{cls.name}-{cls.section}"),
                "created": False,
            }
        return {"success": False, "error": "Could not create attendance session"}

    return {
        "success": True,
        "session": serialize_session(s, f"{cls.name}-{cls.section}"),
        "created": True,
    }


def get_session_for_class_date(
    tenant_id: str, class_id: str, session_date: date
) -> Optional[AttendanceSession]:
    return (
        AttendanceSession.query.filter_by(
            tenant_id=tenant_id, class_id=class_id, session_date=session_date
        )
        .filter(AttendanceSession.deleted_at.is_(None))
        .first()
    )


def get_session_by_id(tenant_id: str, session_id: str) -> Optional[AttendanceSession]:
    return (
        AttendanceSession.query.filter_by(id=session_id, tenant_id=tenant_id)
        .filter(AttendanceSession.deleted_at.is_(None))
        .first()
    )


def list_records_for_session(tenant_id: str, session_id: str) -> List[Dict[str, Any]]:
    """Per-student rows for a session (for marking UI)."""
    rows = AttendanceRecord.query.filter_by(
        tenant_id=tenant_id, attendance_session_id=session_id
    ).all()
    out: List[Dict[str, Any]] = []
    for r in rows:
        st = Student.query.get(r.student_id)
        out.append(
            {
                "student_id": r.student_id,
                "student_name": st.user.name if st and st.user else None,
                "admission_number": st.admission_number if st else None,
                "status": r.status,
                "remarks": r.remarks,
            }
        )
    return out


def upsert_records(
    tenant_id: str,
    session_id: str,
    user_id: str,
    records: List[Dict[str, Any]],
) -> Dict[str, Any]:
    s = get_session_by_id(tenant_id, session_id)
    if not s:
        return {"success": False, "error": "Session not found"}

    if s.status == "finalized" and not has_permission(user_id, "attendance.manage"):
        return {"success": False, "error": "Session is finalized"}

    if not can_user_mark_session(tenant_id, user_id, s, s.class_id):
        return {"success": False, "error": "Not allowed to mark this session"}

    cls = Class.query.filter_by(id=s.class_id, tenant_id=tenant_id).first()
    if not cls:
        return {"success": False, "error": "Class not found"}

    updated = 0
    created = 0
    now = datetime.now(timezone.utc)

    for rec in records:
        student_id = rec.get("student_id")
        status = (rec.get("status") or "absent").strip()
        if status not in ("present", "absent", "late", "excused"):
            continue
        st = Student.query.filter_by(id=student_id, tenant_id=tenant_id).first()
        if not st or st.class_id != s.class_id:
            continue

        row = AttendanceRecord.query.filter_by(
            attendance_session_id=session_id, student_id=student_id
        ).first()
        if row:
            row.status = status
            row.remarks = rec.get("remarks")
            row.updated_at = now
            row.updated_by_user_id = user_id
            updated += 1
        else:
            row = AttendanceRecord(
                tenant_id=tenant_id,
                attendance_session_id=session_id,
                student_id=student_id,
                status=status,
                remarks=rec.get("remarks"),
                recorded_by_user_id=user_id,
            )
            db.session.add(row)
            created += 1

    s.marked_by_user_id = user_id
    s.marked_at = now
    s.taken_by_role = "teacher"
    s.updated_at = now
    s.updated_by = user_id

    db.session.commit()
    return {"success": True, "created": created, "updated": updated}


def finalize_session(tenant_id: str, session_id: str, user_id: str) -> Dict[str, Any]:
    s = get_session_by_id(tenant_id, session_id)
    if not s:
        return {"success": False, "error": "Session not found"}

    if not can_user_mark_session(tenant_id, user_id, s, s.class_id) and not has_permission(
        user_id, "attendance.manage"
    ):
        return {"success": False, "error": "Not allowed to finalize this session"}

    s.status = "finalized"
    s.finalized_at = datetime.now(timezone.utc)
    s.finalized_by_user_id = user_id
    s.updated_at = s.finalized_at
    s.updated_by = user_id
    db.session.commit()
    cls = Class.query.get(s.class_id)
    name = f"{cls.name}-{cls.section}" if cls else None
    return {"success": True, "session": serialize_session(s, name)}


def class_history(
    tenant_id: str, class_id: str, limit: int = 90
) -> Dict[str, Any]:
    cls = Class.query.filter_by(id=class_id, tenant_id=tenant_id).first()
    if not cls:
        return {"success": False, "error": "Class not found"}

    sessions = (
        AttendanceSession.query.filter_by(tenant_id=tenant_id, class_id=class_id)
        .filter(AttendanceSession.deleted_at.is_(None))
        .order_by(AttendanceSession.session_date.desc())
        .limit(limit)
        .all()
    )

    out = []
    for s in sessions:
        out.append(serialize_session(s, f"{cls.name}-{cls.section}"))

    return {"success": True, "items": out}


def student_history_v2(tenant_id: str, student_id: str, month: Optional[str] = None) -> Dict[str, Any]:
    st = Student.query.filter_by(id=student_id, tenant_id=tenant_id).first()
    if not st:
        return {"success": False, "error": "Student not found"}

    q = (
        db.session.query(AttendanceRecord, AttendanceSession)
        .join(AttendanceSession, AttendanceRecord.attendance_session_id == AttendanceSession.id)
        .filter(
            AttendanceRecord.tenant_id == tenant_id,
            AttendanceRecord.student_id == student_id,
            AttendanceSession.deleted_at.is_(None),
        )
    )

    if month:
        y, m = month.split("-")
        start = date(int(y), int(m), 1)
        if int(m) == 12:
            end = date(int(y) + 1, 1, 1)
        else:
            end = date(int(y), int(m) + 1, 1)
        q = q.filter(AttendanceSession.session_date >= start, AttendanceSession.session_date < end)

    rows = q.order_by(AttendanceSession.session_date.desc()).all()

    recs = []
    for ar, sess in rows:
        recs.append(
            {
                "date": sess.session_date.isoformat(),
                "status": ar.status,
                "remarks": ar.remarks,
                "session_id": sess.id,
            }
        )

    total = len(recs)
    present = sum(1 for r in recs if r["status"] == "present")
    pct = round(100.0 * present / total, 1) if total else 0.0

    return {
        "success": True,
        "data": {
            "student_id": student_id,
            "source": "sessions_v2",
            "total_days": total,
            "present": present,
            "percentage": pct,
            "records": recs,
        },
    }


def me_student_attendance_v2(tenant_id: str, user_id: str, month: Optional[str] = None) -> Dict[str, Any]:
    st = Student.query.filter_by(user_id=user_id, tenant_id=tenant_id).first()
    if not st:
        return {"success": False, "error": "Student not found"}
    return student_history_v2(tenant_id, st.id, month=month)


def attendance_pending_for_class_today(tenant_id: str, class_id: str, today: date) -> bool:
    s = (
        AttendanceSession.query.filter_by(
            tenant_id=tenant_id, class_id=class_id, session_date=today
        )
        .filter(AttendanceSession.deleted_at.is_(None))
        .first()
    )
    if not s:
        return True
    return s.status != "finalized"
