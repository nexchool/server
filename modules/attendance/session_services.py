"""
Daily attendance sessions (AttendanceSession + AttendanceRecord).

API writes use sessions. Legacy `attendance` reads remain in services.py only as a
fallback when no session exists for a date.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import IntegrityError

from core.branch_scope import (
    assert_class_allowed,
    assert_student_allowed,
    filter_classes_by_branch,
)
from core.database import db
from modules.academics.backbone.models import (
    AttendanceRecord,
    AttendanceSession,
)
from modules.classes.models import Class
from modules.academics.calendar.holiday_services import get_holiday_for_date
from modules.rbac.services import has_permission
from modules.students.models import Student
from modules.teachers.models import Teacher
from core.school_time import school_today


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


def can_user_mark_session(
    tenant_id: str,
    user_id: str,
    session: AttendanceSession,
    class_id: str,
) -> bool:
    """May this user write to this session?

    Resolved through Teaching Assignment (ADR-014): the class teacher in
    effect on the session's day — time is part of the question — provided the
    responsibility allows marking, or a teacher explicitly delegated as the
    session's marker. The old fallback that matched `classes.teacher_id`
    against the login is gone: that column is a cache, and it now names the
    teacher, not their account (migration 095).
    """
    from modules.academics.teaching_assignment import class_teacher_of

    if has_permission(user_id, "attendance.manage"):
        return True

    t = _teacher_for_user(tenant_id, user_id)
    if not t:
        return False

    if session.assigned_marker_teacher_id and session.assigned_marker_teacher_id == t.id:
        return True

    cta = class_teacher_of(class_id, on=session.session_date)
    return bool(cta and cta.teacher_id == t.id and cta.allow_attendance_marking)


def get_eligible_classes_for_user(tenant_id: str, user_id: str, session_day: date) -> Dict[str, Any]:
    """Classes the user may mark attendance for on session_day."""
    items: List[Dict[str, Any]] = []

    if has_permission(user_id, "attendance.manage"):
        # Branch scope: a restricted sub-admin with attendance.manage may only
        # see classes in their units. No-op when unrestricted.
        classes = (
            filter_classes_by_branch(Class.query.filter_by(tenant_id=tenant_id))
            .order_by(Class.name, Class.section)
            .all()
        )
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

    # Class-teacher responsibilities with attendance authority, in effect on
    # the requested day — asked of Teaching Assignment (ADR-014), not the
    # tables that happen to express it.
    from modules.academics.teaching_assignment import classes_taught_by

    seen = set()
    for held in classes_taught_by(teacher.id, on=session_day):
        if not held.allow_attendance_marking:
            continue
        c = Class.query.get(held.class_id)
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

    # Branch scope: restricted sub-admins may only touch classes in their units.
    assert_class_allowed(class_id)

    # Attendance can only be taken for a day that has occurred. school_today() is the
    # server date, matching the rest of this module (e.g. the route default); for
    # IST / UTC+ tenants the only divergence is before dawn local time, outside
    # marking hours.
    if session_date > school_today():
        return {
            "success": False,
            "error": "Attendance cannot be taken for a future date",
        }

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

    # A delegated marker must be a real teacher of this organization — the
    # column would otherwise accept any teacher id from any tenant.
    if assigned_marker_teacher_id:
        marker = Teacher.query.filter_by(
            id=assigned_marker_teacher_id, tenant_id=tenant_id
        ).first()
        if marker is None:
            return {"success": False, "error": "Unknown teacher for assigned marker"}

    # class_teacher_assignment_id is no longer written: nothing ever read it,
    # and "who was the class teacher that day" is answered by the dated
    # Teaching Assignment service (ADR-014), not a snapshot of a row id.
    s = AttendanceSession(
        tenant_id=tenant_id,
        class_id=class_id,
        session_date=session_date,
        status="draft",
        assigned_marker_teacher_id=assigned_marker_teacher_id,
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
    # Branch scope: restricted sub-admins may only read classes in their units.
    assert_class_allowed(class_id)
    return (
        AttendanceSession.query.filter_by(
            tenant_id=tenant_id, class_id=class_id, session_date=session_date
        )
        .filter(AttendanceSession.deleted_at.is_(None))
        .first()
    )


def get_session_by_id(tenant_id: str, session_id: str) -> Optional[AttendanceSession]:
    s = (
        AttendanceSession.query.filter_by(id=session_id, tenant_id=tenant_id)
        .filter(AttendanceSession.deleted_at.is_(None))
        .first()
    )
    # Branch scope: a session reaches a branch through its class. Restricted
    # sub-admins may only act on sessions for classes in their units (covers
    # POST records + finalize, which load the session by id). No-op when
    # unrestricted; a missing session defers to caller's not-found handling.
    if s is not None:
        assert_class_allowed(s.class_id)
    return s


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
    skipped: List[Dict[str, Any]] = []
    now = datetime.now(timezone.utc)

    for rec in records:
        student_id = rec.get("student_id")
        status = (rec.get("status") or "absent").strip()
        if status not in ("present", "absent", "late", "excused"):
            skipped.append({"student_id": student_id, "reason": f"invalid status '{status}'"})
            continue
        st = Student.query.filter_by(id=student_id, tenant_id=tenant_id).first()
        if not st or st.class_id != s.class_id:
            skipped.append(
                {"student_id": student_id, "reason": "student is not in this class"}
            )
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
    return {"success": True, "created": created, "updated": updated, "skipped": skipped}


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

    # Branch scope: restricted sub-admins may only read classes in their units.
    assert_class_allowed(class_id)

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

    # Branch scope: restricted sub-admins may only read students in their units.
    assert_student_allowed(student_id)

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
