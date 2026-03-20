from typing import List, Dict, Optional
from sqlalchemy.exc import IntegrityError
from datetime import datetime, date

from backend.core.database import db
from backend.core.tenant import get_tenant_id
from backend.modules.classes.models import Class
from backend.modules.students.models import Student
from backend.modules.holidays.services import get_holiday_for_date
from .models import Attendance


def get_teacher_class_ids(user_id: str) -> List[str]:
    """
    Get class IDs for attendance marking.

    Only the class teacher (Class.teacher_id) can take attendance for a class.
    Users with attendance.manage permission bypass this and can mark any class (admin override).
    """
    # Only classes where this user is the class teacher (Class.teacher_id = user_id)
    direct_classes = Class.query.filter_by(teacher_id=user_id).all()
    return [c.id for c in direct_classes]


def mark_attendance(
    class_id: str,
    date_str: str,
    records: List[Dict],
    marked_by_user_id: str,
) -> Dict:
    """
    Mark attendance for a class on a given date.

    Args:
        class_id: Class ID
        date_str: Date in YYYY-MM-DD format
        records: List of {student_id, status, remarks?}
        marked_by_user_id: User ID of the person marking

    Returns:
        Dict with success and count of records created/updated
    """
    try:
        cls = Class.query.get(class_id)
        if not cls:
            return {'success': False, 'error': 'Class not found'}

        att_date = datetime.strptime(date_str, '%Y-%m-%d').date()

        # Date range validations
        if att_date > date.today():
            return {'success': False, 'error': 'Cannot mark attendance for future dates'}
        if cls.start_date and att_date < cls.start_date:
            return {'success': False, 'error': 'Date is before academic year start'}
        if cls.end_date and att_date > cls.end_date:
            return {'success': False, 'error': 'Date is after academic year end'}

        # Holiday check — attendance cannot be marked on holidays or weekly-off days
        tenant_id = get_tenant_id()
        holiday = get_holiday_for_date(att_date, tenant_id)
        if holiday:
            holiday_label = holiday.get('name') or ('Weekly Off' if holiday.get('is_recurring') else 'Holiday')
            return {
                'success': False,
                'error': f"Attendance cannot be marked on '{holiday_label}'. This day is a holiday.",
                'is_holiday': True,
                'holiday': holiday,
            }

        created = 0
        updated = 0

        for record in records:
            student_id = record.get('student_id')
            status = record.get('status', 'absent')
            remarks = record.get('remarks')

            if not student_id:
                continue

            if status not in ('present', 'absent', 'late'):
                continue

            # Check if student exists and belongs to this class
            student = Student.query.get(student_id)
            if not student or student.class_id != class_id:
                continue

            # Upsert: update if exists, create if not
            existing = Attendance.query.filter_by(
                date=att_date,
                class_id=class_id,
                student_id=student_id,
            ).first()

            if existing:
                existing.status = status
                existing.remarks = remarks
                existing.marked_by = marked_by_user_id
                existing.updated_at = datetime.utcnow()
                updated += 1
            else:
                tenant_id = get_tenant_id()
                att = Attendance(
                    tenant_id=tenant_id,
                    date=att_date,
                    class_id=class_id,
                    student_id=student_id,
                    status=status,
                    remarks=remarks,
                    marked_by=marked_by_user_id,
                )
                db.session.add(att)
                created += 1

        db.session.commit()

        return {
            'success': True,
            'message': f'Attendance marked: {created} created, {updated} updated',
            'created': created,
            'updated': updated,
        }

    except ValueError as e:
        db.session.rollback()
        return {'success': False, 'error': f'Invalid date format: {str(e)}'}
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': f'Failed to mark attendance: {str(e)}'}


def get_attendance_by_class_date(class_id: str, date_str: str) -> Dict:
    """
    Get attendance records for a class on a specific date.
    Also returns students who haven't been marked yet.
    Includes a `holiday_info` field if the date is a holiday.
    """
    try:
        cls = Class.query.get(class_id)
        if not cls:
            return {'success': False, 'error': 'Class not found'}

        att_date = datetime.strptime(date_str, '%Y-%m-%d').date()

        # Check if this date is a holiday
        tenant_id = get_tenant_id()
        holiday_info = get_holiday_for_date(att_date, tenant_id)

        # Get all students in this class, excluding those admitted after the attendance date
        students = Student.query.filter_by(class_id=class_id).all()
        students = [s for s in students if s.created_at.date() <= att_date]

        # Get existing attendance records
        records = Attendance.query.filter_by(
            class_id=class_id,
            date=att_date,
        ).all()

        records_map = {r.student_id: r for r in records}

        attendance_list = []
        for student in students:
            record = records_map.get(student.id)
            attendance_list.append({
                'student_id': student.id,
                'student_name': student.user.name if student.user else None,
                'admission_number': student.admission_number,
                'roll_number': student.roll_number,
                'status': record.status if record else None,
                'remarks': record.remarks if record else None,
                'marked': record is not None,
            })

        # Sort by roll number, then name
        attendance_list.sort(key=lambda x: (x['roll_number'] or 999, x['student_name'] or ''))

        return {
            'success': True,
            'data': {
                'class_id': class_id,
                'class_name': f"{cls.name}-{cls.section}",
                'date': date_str,
                'is_holiday': holiday_info is not None,
                'holiday_info': holiday_info,
                'total_students': len(students),
                'marked_count': len(records),
                'present_count': sum(1 for r in records if r.status == 'present'),
                'absent_count': sum(1 for r in records if r.status == 'absent'),
                'late_count': sum(1 for r in records if r.status == 'late'),
                'attendance': attendance_list,
            }
        }

    except ValueError:
        return {'success': False, 'error': 'Invalid date format. Use YYYY-MM-DD'}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def get_student_attendance(student_id: str, month: Optional[str] = None) -> Dict:
    """
    Get attendance history for a student.

    Args:
        student_id: Student ID
        month: Optional month filter in YYYY-MM format
    """
    try:
        student = Student.query.get(student_id)
        if not student:
            return {'success': False, 'error': 'Student not found'}

        query = Attendance.query.filter_by(student_id=student_id)

        if month:
            year, m = month.split('-')
            start_date = date(int(year), int(m), 1)
            if int(m) == 12:
                end_date = date(int(year) + 1, 1, 1)
            else:
                end_date = date(int(year), int(m) + 1, 1)
            query = query.filter(Attendance.date >= start_date, Attendance.date < end_date)

        records = query.order_by(Attendance.date.desc()).all()

        total = len(records)
        present = sum(1 for r in records if r.status == 'present')
        absent = sum(1 for r in records if r.status == 'absent')
        late = sum(1 for r in records if r.status == 'late')
        percentage = round((present / total) * 100, 1) if total > 0 else 0

        return {
            'success': True,
            'data': {
                'student_id': student_id,
                'student_name': student.user.name if student.user else None,
                'total_days': total,
                'present': present,
                'absent': absent,
                'late': late,
                'percentage': percentage,
                'records': [r.to_dict() for r in records],
            }
        }

    except Exception as e:
        return {'success': False, 'error': str(e)}


def get_my_classes(user_id: str) -> List[Dict]:
    """Get classes assigned to a teacher for attendance marking."""
    class_ids = get_teacher_class_ids(user_id)
    if not class_ids:
        return []

    classes = Class.query.filter(Class.id.in_(class_ids)).order_by(Class.name, Class.section).all()

    result = []
    for cls in classes:
        student_count = Student.query.filter_by(class_id=cls.id).count()
        result.append({
            **cls.to_dict(),
            'student_count': student_count,
        })

    return result
