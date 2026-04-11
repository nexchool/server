"""
Attendance services — class-day views and legacy POST /mark delegate to V2 sessions.

Reads prefer AttendanceSession + AttendanceRecord (v2). If no session exists for the date,
responses fall back to the legacy `attendance` table so older rows remain visible until fully
migrated. New marks via POST /api/attendance/mark write only to v2.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import joinedload

from core.database import db
from core.tenant import get_tenant_id
from modules.academics.backbone.models import AttendanceRecord, AttendanceSession
from modules.auth.models import User
from modules.classes.models import Class
from modules.students.models import Student
from modules.holidays.services import get_holiday_for_date

from . import session_services as session_svc
from .models import Attendance


def get_teacher_class_ids(user_id: str) -> List[str]:
    """
    Get class IDs for attendance marking.

    Includes legacy Class.teacher_id and authoritative ClassTeacherAssignment (primary + allow_attendance).
    Users with attendance.manage permission bypass this and can mark any class (admin override).
    """
    from modules.academics.backbone.models import ClassTeacherAssignment
    from modules.teachers.models import Teacher

    ids: List[str] = []

    direct_classes = Class.query.filter_by(teacher_id=user_id).all()
    ids.extend(c.id for c in direct_classes)

    teacher = Teacher.query.filter_by(user_id=user_id).first()
    if teacher:
        rows = (
            ClassTeacherAssignment.query.filter_by(
                tenant_id=teacher.tenant_id,
                teacher_id=teacher.id,
            )
            .filter(
                ClassTeacherAssignment.is_active.is_(True),
                ClassTeacherAssignment.deleted_at.is_(None),
                ClassTeacherAssignment.allow_attendance_marking.is_(True),
            )
            .all()
        )
        ids.extend(r.class_id for r in rows)

    return list(dict.fromkeys(ids))


def mark_attendance(
    class_id: str,
    date_str: str,
    records: List[Dict],
    marked_by_user_id: str,
) -> Dict:
    """
    Mark attendance for a class on a given date (delegates to v2 session + records).

    Legacy flat `attendance` rows are no longer written; clients should prefer session APIs.
    """
    try:
        cls = Class.query.get(class_id)
        if not cls:
            return {"success": False, "error": "Class not found"}

        att_date = datetime.strptime(date_str, "%Y-%m-%d").date()

        if att_date > date.today():
            return {"success": False, "error": "Cannot mark attendance for future dates"}

        tenant_id = get_tenant_id()

        r = session_svc.get_or_create_session(
            tenant_id,
            class_id,
            att_date,
            marked_by_user_id,
            assigned_marker_teacher_id=None,
            notes=None,
        )
        if not r.get("success"):
            err = r.get("error", "Failed to create session")
            out: Dict[str, Any] = {"success": False, "error": err}
            if r.get("holiday"):
                out["holiday"] = r["holiday"]
                out["is_holiday"] = True
            return out

        session_id = r["session"]["id"]
        body = []
        for record in records:
            student_id = record.get("student_id")
            status = (record.get("status") or "absent").strip()
            if not student_id:
                continue
            if status not in ("present", "absent", "late", "excused"):
                continue
            body.append(
                {
                    "student_id": student_id,
                    "status": status,
                    "remarks": record.get("remarks"),
                }
            )

        if not body:
            return {"success": False, "error": "No valid attendance records to save"}

        ur = session_svc.upsert_records(tenant_id, session_id, marked_by_user_id, body)
        if not ur.get("success"):
            return {"success": False, "error": ur.get("error", "Failed to save records")}

        return {
            "success": True,
            "message": f"Attendance saved: {ur.get('created', 0)} created, {ur.get('updated', 0)} updated",
            "created": ur.get("created", 0),
            "updated": ur.get("updated", 0),
            "session_id": session_id,
            "source": "sessions_v2",
        }

    except ValueError as e:
        return {"success": False, "error": f"Invalid date format: {str(e)}"}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": f"Failed to mark attendance: {str(e)}"}


def _user_names_map(user_ids: List[Optional[str]]) -> Dict[str, str]:
    ids = [u for u in user_ids if u]
    if not ids:
        return {}
    rows = User.query.filter(User.id.in_(ids)).all()
    return {u.id: u.name for u in rows}


def _finalize_overview_payload(
    cls: Class,
    class_id: str,
    date_str: str,
    att_date: date,
    holiday_info: Optional[Dict],
    students: List[Student],
    attendance_list: List[Dict[str, Any]],
    *,
    source: str,
    session: Optional[AttendanceSession] = None,
) -> Dict[str, Any]:
    total_students = len(students)
    marked_count = sum(1 for row in attendance_list if row["marked"])
    unmarked_count = total_students - marked_count

    present_count = sum(1 for row in attendance_list if row.get("status") == "present")
    absent_count = sum(1 for row in attendance_list if row.get("status") == "absent")
    late_count = sum(1 for row in attendance_list if row.get("status") == "late")
    excused_count = sum(1 for row in attendance_list if row.get("status") == "excused")

    attendance_rate_percent = None
    if total_students > 0:
        attendance_rate_percent = round(
            ((present_count + late_count + excused_count) / total_students) * 100, 1
        )

    marked_status_count = present_count + absent_count + late_count + excused_count
    participation_rate_percent = None
    if marked_status_count > 0:
        participation_rate_percent = round(
            ((present_count + late_count + excused_count) / marked_status_count) * 100, 1
        )

    date_within_academic_window = True
    if cls.start_date and att_date < cls.start_date:
        date_within_academic_window = False
    if cls.end_date and att_date > cls.end_date:
        date_within_academic_window = False

    payload: Dict[str, Any] = {
        "class_id": class_id,
        "class_name": f"{cls.name}-{cls.section}",
        "date": date_str,
        "is_holiday": holiday_info is not None,
        "holiday_info": holiday_info,
        "grade_level": cls.grade_level,
        "academic_year": cls.academic_year_ref.name if cls.academic_year_ref else None,
        "academic_year_id": cls.academic_year_id,
        "class_teacher_name": cls.teacher.name if cls.teacher else None,
        "class_start_date": cls.start_date.isoformat() if cls.start_date else None,
        "class_end_date": cls.end_date.isoformat() if cls.end_date else None,
        "date_within_academic_window": date_within_academic_window,
        "total_students": total_students,
        "marked_count": marked_count,
        "unmarked_count": unmarked_count,
        "present_count": present_count,
        "absent_count": absent_count,
        "late_count": late_count,
        "excused_count": excused_count,
        "attendance_rate_percent": attendance_rate_percent,
        "participation_rate_percent": participation_rate_percent,
        "attendance": attendance_list,
        "attendance_source": source,
        "session_id": session.id if session else None,
        "session_status": session.status if session else None,
    }
    return {"success": True, "data": payload}


def get_attendance_by_class_date(class_id: str, date_str: str) -> Dict:
    """
    Class roster for a date with attendance — prefers v2 session + records, else legacy rows.
    """
    try:
        cls = (
            Class.query.options(
                joinedload(Class.teacher),
                joinedload(Class.academic_year_ref),
            ).get(class_id)
        )
        if not cls:
            return {"success": False, "error": "Class not found"}

        att_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        tenant_id = get_tenant_id()
        holiday_info = get_holiday_for_date(att_date, tenant_id)

        students = Student.query.filter_by(class_id=class_id).all()
        students = [s for s in students if s.created_at.date() <= att_date]

        session = session_svc.get_session_for_class_date(tenant_id, class_id, att_date)

        if session:
            rows = (
                AttendanceRecord.query.filter_by(
                    tenant_id=tenant_id,
                    attendance_session_id=session.id,
                )
                .options(
                    joinedload(AttendanceRecord.student).joinedload(Student.user),
                )
                .all()
            )
            uid_list: List[Optional[str]] = []
            for ar in rows:
                uid_list.append(ar.updated_by_user_id or ar.recorded_by_user_id)
            names = _user_names_map(uid_list)
            records_map = {ar.student_id: ar for ar in rows}

            attendance_list = []
            for student in students:
                ar = records_map.get(student.id)
                uid = (ar.updated_by_user_id or ar.recorded_by_user_id) if ar else None
                attendance_list.append(
                    {
                        "student_id": student.id,
                        "student_name": student.user.name if student.user else None,
                        "admission_number": student.admission_number,
                        "roll_number": student.roll_number,
                        "status": ar.status if ar else None,
                        "remarks": ar.remarks if ar else None,
                        "marked": ar is not None,
                        "marked_by_user_id": uid,
                        "marked_by_name": names.get(uid) if uid else None,
                        "recorded_at": ar.updated_at.isoformat() if ar and ar.updated_at else None,
                    }
                )
            attendance_list.sort(
                key=lambda x: (x["roll_number"] or 999, x["student_name"] or "")
            )
            return _finalize_overview_payload(
                cls,
                class_id,
                date_str,
                att_date,
                holiday_info,
                students,
                attendance_list,
                source="sessions_v2",
                session=session,
            )

        # Legacy fallback (no v2 session for this date)
        records = (
            Attendance.query.filter_by(class_id=class_id, date=att_date)
            .options(joinedload(Attendance.marker))
            .all()
        )
        records_map = {r.student_id: r for r in records}

        attendance_list = []
        for student in students:
            record = records_map.get(student.id)
            uid = record.marked_by if record else None
            attendance_list.append(
                {
                    "student_id": student.id,
                    "student_name": student.user.name if student.user else None,
                    "admission_number": student.admission_number,
                    "roll_number": student.roll_number,
                    "status": record.status if record else None,
                    "remarks": record.remarks if record else None,
                    "marked": record is not None,
                    "marked_by_user_id": uid,
                    "marked_by_name": record.marker.name if record and record.marker else None,
                    "recorded_at": record.updated_at.isoformat()
                    if record and record.updated_at
                    else None,
                }
            )
        attendance_list.sort(
            key=lambda x: (x["roll_number"] or 999, x["student_name"] or "")
        )
        return _finalize_overview_payload(
            cls,
            class_id,
            date_str,
            att_date,
            holiday_info,
            students,
            attendance_list,
            source="legacy_table",
            session=None,
        )

    except ValueError:
        return {"success": False, "error": "Invalid date format. Use YYYY-MM-DD"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_student_attendance(student_id: str, month: Optional[str] = None) -> Dict:
    """
    Monthly / all-time attendance for a student — prefers v2 session records, else legacy.
    """
    try:
        student = Student.query.get(student_id)
        if not student:
            return {"success": False, "error": "Student not found"}

        tenant_id = get_tenant_id()

        q = (
            db.session.query(AttendanceRecord, AttendanceSession)
            .join(
                AttendanceSession,
                AttendanceRecord.attendance_session_id == AttendanceSession.id,
            )
            .filter(
                AttendanceRecord.tenant_id == tenant_id,
                AttendanceRecord.student_id == student_id,
                AttendanceSession.deleted_at.is_(None),
            )
        )

        if month:
            year, m = month.split("-")
            start_d = date(int(year), int(m), 1)
            if int(m) == 12:
                end_d = date(int(year) + 1, 1, 1)
            else:
                end_d = date(int(year), int(m) + 1, 1)
            q = q.filter(
                AttendanceSession.session_date >= start_d,
                AttendanceSession.session_date < end_d,
            )

        v2_rows = q.order_by(AttendanceSession.session_date.desc()).all()

        if v2_rows:
            records_out: List[Dict[str, Any]] = []
            marker_ids: List[Optional[str]] = []
            for ar, sess in v2_rows:
                marker_ids.append(ar.updated_by_user_id or ar.recorded_by_user_id)
            names = _user_names_map(marker_ids)

            for ar, sess in v2_rows:
                uid = ar.updated_by_user_id or ar.recorded_by_user_id
                records_out.append(
                    {
                        "id": ar.id,
                        "date": sess.session_date.isoformat(),
                        "class_id": sess.class_id,
                        "student_id": ar.student_id,
                        "student_name": student.user.name if student.user else None,
                        "admission_number": student.admission_number,
                        "status": ar.status,
                        "remarks": ar.remarks,
                        "marked_by": uid,
                        "marked_by_name": names.get(uid) if uid else None,
                        "created_at": ar.recorded_at.isoformat() if ar.recorded_at else None,
                    }
                )

            total = len(records_out)
            present = sum(1 for r in records_out if r["status"] == "present")
            absent = sum(1 for r in records_out if r["status"] == "absent")
            late = sum(1 for r in records_out if r["status"] == "late")
            percentage = round((present / total) * 100, 1) if total > 0 else 0

            return {
                "success": True,
                "data": {
                    "student_id": student_id,
                    "student_name": student.user.name if student.user else None,
                    "total_days": total,
                    "present": present,
                    "absent": absent,
                    "late": late,
                    "percentage": percentage,
                    "records": records_out,
                    "attendance_source": "sessions_v2",
                },
            }

        # Legacy fallback
        query = Attendance.query.filter_by(student_id=student_id)
        if month:
            year, m = month.split("-")
            start_date = date(int(year), int(m), 1)
            if int(m) == 12:
                end_date = date(int(year) + 1, 1, 1)
            else:
                end_date = date(int(year), int(m) + 1, 1)
            query = query.filter(Attendance.date >= start_date, Attendance.date < end_date)

        legacy = query.order_by(Attendance.date.desc()).all()
        total = len(legacy)
        present = sum(1 for r in legacy if r.status == "present")
        absent = sum(1 for r in legacy if r.status == "absent")
        late = sum(1 for r in legacy if r.status == "late")
        percentage = round((present / total) * 100, 1) if total > 0 else 0

        return {
            "success": True,
            "data": {
                "student_id": student_id,
                "student_name": student.user.name if student.user else None,
                "total_days": total,
                "present": present,
                "absent": absent,
                "late": late,
                "percentage": percentage,
                "records": [r.to_dict() for r in legacy],
                "attendance_source": "legacy_table",
            },
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def get_my_classes(user_id: str) -> List[Dict]:
    """Get classes assigned to a teacher for attendance marking."""
    class_ids = get_teacher_class_ids(user_id)
    if not class_ids:
        return []

    classes = Class.query.filter(Class.id.in_(class_ids)).order_by(Class.name, Class.section).all()

    result = []
    for cls in classes:
        student_count = Student.query.filter_by(class_id=cls.id).count()
        result.append(
            {
                **cls.to_dict(),
                "student_count": student_count,
            }
        )

    return result
