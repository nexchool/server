import logging
from typing import List, Dict, Optional
from sqlalchemy.exc import IntegrityError
from datetime import datetime

from backend.core.database import db
from backend.core.tenant import get_tenant_id
from .models import Class, ClassTeacher

logger = logging.getLogger(__name__)


def create_class(
    name: str,
    section: str,
    academic_year_id: str,
    teacher_id: str = None,
    start_date: str = None,
    end_date: str = None,
) -> Dict:
    """Create a new class (tenant-scoped). academic_year_id is required."""
    logger.warning(
        "[create_class] called: name=%r, section=%r, academic_year_id=%r, teacher_id=%r, start_date=%r, end_date=%r",
        name, section, academic_year_id, teacher_id, start_date, end_date,
    )
    try:
        tenant_id = get_tenant_id()
        logger.warning("[create_class] tenant_id=%r", tenant_id)
        if not tenant_id:
            logger.warning("create_class: FAILED - no tenant context")
            return {'success': False, 'error': 'Tenant context is required'}

        if not academic_year_id:
            logger.warning("create_class: FAILED - academic_year_id required")
            return {'success': False, 'error': 'academic_year_id is required'}

        # Normalize: empty string -> None for optional fields
        teacher_id = teacher_id if teacher_id else None

        # Check teacher is not already class teacher of another class (one teacher = one class)
        if teacher_id:
            existing_teacher_class = Class.query.filter_by(
                tenant_id=tenant_id,
                teacher_id=teacher_id,
            ).first()
            if existing_teacher_class:
                return {
                    'success': False,
                    'error': 'This teacher is already the class teacher of another class. A teacher can only be class teacher of one class.'
                }

        # Explicit duplicate check (name, section, academic_year_id) - gives clear error
        logger.warning("[create_class] checking for duplicate")
        existing = Class.query.filter_by(
            tenant_id=tenant_id,
            name=name.strip(),
            section=section.strip(),
            academic_year_id=academic_year_id,
        ).first()
        if existing:
            logger.warning("create_class: FAILED - duplicate found, existing id=%r", existing.id if existing else None)
            return {
                'success': False,
                'error': 'Class with this name, section and academic year already exists'
            }

        logger.warning("[create_class] no duplicate, creating Class object")
        new_class = Class(
            tenant_id=tenant_id,
            name=name.strip(),
            section=section.strip(),
            academic_year_id=academic_year_id,
            teacher_id=teacher_id,
            start_date=datetime.strptime(start_date, '%Y-%m-%d').date() if start_date else None,
            end_date=datetime.strptime(end_date, '%Y-%m-%d').date() if end_date else None,
        )
        logger.warning("[create_class] saving to database")
        new_class.save()
        logger.warning("[create_class] SUCCESS class_id=%r", new_class.id)

        return {
            'success': True,
            'class': new_class.to_dict()
        }
    except IntegrityError as e:
        db.session.rollback()
        pgcode = getattr(getattr(e, 'orig', None), 'pgcode', None)
        logger.exception(
            "create_class: IntegrityError pgcode=%r, orig=%r",
            pgcode, str(e.orig) if hasattr(e, 'orig') and e.orig else None,
        )
        # Differentiate constraint violations for clearer error messages
        if pgcode == '23505':  # unique_violation
            raw = str(e.orig).lower() if hasattr(e, 'orig') and e.orig else ''
            if 'teacher_id' in raw or 'uq_classes_teacher_id' in raw:
                return {
                    'success': False,
                    'error': 'This teacher is already the class teacher of another class. A teacher can only be class teacher of one class.'
                }
            return {
                'success': False,
                'error': 'Class with this name, section and academic year already exists'
            }
        if pgcode == '23503':  # foreign_key_violation
            return {
                'success': False,
                'error': 'Invalid academic year or teacher. Please ensure the academic year exists and the teacher (if selected) is valid.'
            }
        raw = str(e.orig) if hasattr(e, 'orig') and e.orig else str(e)
        return {
            'success': False,
            'error': raw,
            'raw_error': raw,
        }
    except Exception as e:
        db.session.rollback()
        err_str = str(e)
        logger.exception("create_class: Exception %s", err_str)
        return {
            'success': False,
            'error': err_str,
            'raw_error': err_str,
        }


def get_all_classes(
    academic_year_id: Optional[str] = None,
) -> List[Dict]:
    """Get all classes, optionally filtered by academic year."""
    query = Class.query
    if academic_year_id:
        query = query.filter_by(academic_year_id=academic_year_id)

    classes = query.order_by(Class.name, Class.section).all()

    result = []
    for c in classes:
        from backend.modules.students.models import Student
        student_count = Student.query.filter_by(class_id=c.id).count()
        teacher_count = ClassTeacher.query.filter_by(class_id=c.id).count()
        data = c.to_dict()
        data['student_count'] = student_count
        data['teacher_count'] = teacher_count
        result.append(data)

    return result


def get_class_by_id(class_id: str) -> Optional[Dict]:
    """Get class details by ID"""
    cls = Class.query.get(class_id)
    return cls.to_dict() if cls else None


def get_class_detail(class_id: str) -> Optional[Dict]:
    """Get class details with students and assigned teachers."""
    cls = Class.query.get(class_id)
    if not cls:
        return None

    from backend.modules.students.models import Student

    # Get students in this class
    students = Student.query.filter_by(class_id=class_id).all()
    students_data = [s.to_dict() for s in students]

    # Get assigned teachers via ClassTeacher junction
    class_teachers = ClassTeacher.query.filter_by(class_id=class_id).all()
    teachers_data = [ct.to_dict() for ct in class_teachers]

    data = cls.to_dict()
    data['students'] = students_data
    data['teachers'] = teachers_data
    data['student_count'] = len(students_data)
    data['teacher_count'] = len(teachers_data)

    return data


def update_class(
    class_id: str,
    name: str = None,
    section: str = None,
    academic_year_id: str = None,
    teacher_id: str = None,
    start_date: str = None,
    end_date: str = None,
) -> Dict:
    """Update class details."""
    try:
        cls = Class.query.get(class_id)
        if not cls:
            return {'success': False, 'error': 'Class not found'}

        tenant_id = get_tenant_id()

        if academic_year_id:
            from backend.modules.academics.academic_year.models import AcademicYear
            ay = AcademicYear.query.filter_by(id=academic_year_id, tenant_id=tenant_id).first()
            if not ay:
                return {'success': False, 'error': 'Invalid academic year.'}

        # Check teacher is not already class teacher of another class (one teacher = one class)
        new_teacher_id = teacher_id if teacher_id else None
        if teacher_id is not None and new_teacher_id:
            existing_teacher_class = Class.query.filter(
                Class.tenant_id == tenant_id,
                Class.teacher_id == new_teacher_id,
                Class.id != class_id,
            ).first()
            if existing_teacher_class:
                return {
                    'success': False,
                    'error': 'This teacher is already the class teacher of another class. A teacher can only be class teacher of one class.'
                }

        # If changing name/section/academic_year, check for duplicate
        new_name = (name or cls.name).strip() if name else cls.name
        new_section = (section or cls.section).strip() if section else cls.section
        new_ay_id = academic_year_id or cls.academic_year_id
        if (new_name != cls.name or new_section != cls.section or new_ay_id != cls.academic_year_id):
            existing = Class.query.filter(
                Class.tenant_id == tenant_id,
                Class.name == new_name,
                Class.section == new_section,
                Class.academic_year_id == new_ay_id,
                Class.id != class_id,
            ).first()
            if existing:
                return {'success': False, 'error': 'Class with this name, section and academic year already exists'}

        if name is not None:
            cls.name = name.strip() if name else name
        if section is not None:
            cls.section = section.strip() if section else section
        if academic_year_id is not None:
            cls.academic_year_id = academic_year_id
        if teacher_id is not None:
            cls.teacher_id = teacher_id if teacher_id else None
        if start_date is not None:
            cls.start_date = datetime.strptime(start_date, '%Y-%m-%d').date() if start_date else None
        if end_date is not None:
            cls.end_date = datetime.strptime(end_date, '%Y-%m-%d').date() if end_date else None

        cls.save()
        return {'success': True, 'class': cls.to_dict()}
    except IntegrityError as e:
        db.session.rollback()
        pgcode = getattr(getattr(e, 'orig', None), 'pgcode', None)
        if pgcode == '23505':
            raw = str(e.orig).lower() if hasattr(e, 'orig') and e.orig else ''
            if 'teacher_id' in raw or 'uq_classes_teacher_id' in raw:
                return {'success': False, 'error': 'This teacher is already the class teacher of another class. A teacher can only be class teacher of one class.'}
            return {'success': False, 'error': 'Class with this name, section and academic year already exists'}
        if pgcode == '23503':
            return {'success': False, 'error': 'Invalid academic year or teacher.'}
        return {'success': False, 'error': str(e.orig) if hasattr(e, 'orig') and e.orig else str(e)}
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': str(e)}


def delete_class(class_id: str) -> Dict:
    """Delete a class"""
    try:
        cls = Class.query.get(class_id)
        if not cls:
            return {'success': False, 'error': 'Class not found'}

        db.session.delete(cls)
        db.session.commit()
        return {'success': True, 'message': 'Class deleted'}
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': str(e)}


# ── Assignment Management ─────────────────────────────────────

def assign_student_to_class(class_id: str, student_id: str) -> Dict:
    """Assign a student to a class."""
    try:
        cls = Class.query.get(class_id)
        if not cls:
            return {'success': False, 'error': 'Class not found'}

        from backend.modules.students.models import Student
        student = Student.query.get(student_id)
        if not student:
            return {'success': False, 'error': 'Student not found'}

        student.class_id = class_id
        student.save()

        # Auto-assign any applicable fee structures for this student's class/year
        try:
            from backend.modules.finance.services import student_fee_service

            student_fee_service.auto_assign_fees_for_student(student.id)
        except Exception:
            db.session.rollback()

        return {'success': True, 'message': 'Student assigned to class'}
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': str(e)}


def remove_student_from_class(class_id: str, student_id: str) -> Dict:
    """Remove a student from a class."""
    try:
        from backend.modules.students.models import Student
        student = Student.query.get(student_id)
        if not student:
            return {'success': False, 'error': 'Student not found'}
        if student.class_id != class_id:
            return {'success': False, 'error': 'Student is not in this class'}

        student.class_id = None
        student.save()
        return {'success': True, 'message': 'Student removed from class'}
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': str(e)}


def assign_teacher_to_class(
    class_id: str,
    teacher_id: str,
    subject_id: str = None,
    is_class_teacher: bool = False,
) -> Dict:
    """
    Assign a teacher to a class.

    Validates: class exists, teacher exists, subject exists.
    """
    try:
        from backend.modules.teachers.models import Teacher
        from backend.modules.subjects.models import Subject

        cls = Class.query.get(class_id)
        if not cls:
            return {'success': False, 'error': 'Class not found'}

        teacher = Teacher.query.get(teacher_id)
        if not teacher:
            return {'success': False, 'error': 'Teacher not found'}

        subject_id_val = None
        if subject_id:
            subj = Subject.query.filter_by(id=subject_id, tenant_id=cls.tenant_id).first()
            if not subj:
                return {'success': False, 'error': 'Subject not found'}
            subject_id_val = subj.id

        # Check if already assigned
        existing = ClassTeacher.query.filter_by(class_id=class_id, teacher_id=teacher_id).first()
        if existing:
            return {'success': False, 'error': 'Teacher already assigned to this class'}

        if is_class_teacher:
            # One teacher can only be class teacher of one class
            existing_as_ct_via_class = Class.query.filter(
                Class.tenant_id == cls.tenant_id,
                Class.teacher_id == teacher.user_id,
                Class.id != class_id,
            ).first()
            if existing_as_ct_via_class:
                return {
                    'success': False,
                    'error': 'This teacher is already the class teacher of another class. A teacher can only be class teacher of one class.',
                }

            existing_as_ct_via_junction = ClassTeacher.query.filter(
                ClassTeacher.tenant_id == cls.tenant_id,
                ClassTeacher.teacher_id == teacher_id,
                ClassTeacher.is_class_teacher == True,
                ClassTeacher.class_id != class_id,
            ).first()
            if existing_as_ct_via_junction:
                return {
                    'success': False,
                    'error': 'This teacher is already the class teacher of another class. A teacher can only be class teacher of one class.',
                }

            # Only one class teacher per class: clear any existing for this class
            cls.teacher_id = None
            for ct_row in ClassTeacher.query.filter_by(class_id=class_id, is_class_teacher=True).all():
                ct_row.is_class_teacher = False
                db.session.add(ct_row)
            db.session.add(cls)

        ct = ClassTeacher(
            tenant_id=cls.tenant_id,
            class_id=class_id,
            teacher_id=teacher_id,
            subject_id=subject_id_val,
            subject=None,  # Use subject_id only
            is_class_teacher=is_class_teacher,
        )
        db.session.add(ct)

        # Keep Class.teacher_id in sync when adding as class teacher
        if is_class_teacher:
            cls.teacher_id = teacher.user_id
            db.session.add(cls)

        db.session.commit()
        return {'success': True, 'assignment': ct.to_dict(), 'message': 'Teacher assigned to class'}
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': str(e)}


def remove_teacher_from_class(class_id: str, teacher_id: str) -> Dict:
    """Remove a teacher from a class."""
    try:
        ct = ClassTeacher.query.filter_by(class_id=class_id, teacher_id=teacher_id).first()
        if not ct:
            return {'success': False, 'error': 'Teacher is not assigned to this class'}

        db.session.delete(ct)
        db.session.commit()
        return {'success': True, 'message': 'Teacher removed from class'}
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': str(e)}


def get_unassigned_students(class_id: str) -> List[Dict]:
    """Get students not assigned to any class (for assignment picker)."""
    from backend.modules.students.models import Student
    students = Student.query.filter(
        db.or_(Student.class_id.is_(None), Student.class_id == '')
    ).all()
    return [s.to_dict() for s in students]


def get_unassigned_teachers(class_id: str) -> List[Dict]:
    """Get teachers not yet assigned to this class."""
    from backend.modules.teachers.models import Teacher
    assigned_ids = [ct.teacher_id for ct in ClassTeacher.query.filter_by(class_id=class_id).all()]
    query = Teacher.query.filter(Teacher.status == 'active')
    if assigned_ids:
        query = query.filter(~Teacher.id.in_(assigned_ids))
    return [t.to_dict() for t in query.all()]


def get_available_class_teachers(class_id: str = None) -> List[Dict]:
    """
    Get teachers who can be selected as class teacher.
    Excludes teachers who are already class teachers of another class.
    If class_id is given (e.g. when editing), includes the current class's teacher.
    A teacher is "class teacher" if: Class.teacher_id = user_id, or ClassTeacher.is_class_teacher = True.
    """
    tenant_id = get_tenant_id()
    if not tenant_id:
        return []

    from backend.modules.teachers.models import Teacher

    # User IDs already assigned as class teacher via Class.teacher_id (exclude class_id if editing)
    class_filter = Class.query.filter(
        Class.tenant_id == tenant_id,
        Class.teacher_id.isnot(None),
    )
    if class_id:
        class_filter = class_filter.filter(Class.id != class_id)
    class_teacher_user_ids = {c.teacher_id for c in class_filter.all()}

    # Teacher IDs already assigned as class teacher via ClassTeacher.is_class_teacher (exclude class_id if editing)
    ct_filter = ClassTeacher.query.filter(
        ClassTeacher.tenant_id == tenant_id,
        ClassTeacher.is_class_teacher == True,
    )
    if class_id:
        ct_filter = ct_filter.filter(ClassTeacher.class_id != class_id)
    ct_class_teacher_ids = {ct.teacher_id for ct in ct_filter.all()}

    query = Teacher.query.filter(Teacher.status == 'active')
    if class_teacher_user_ids:
        query = query.filter(~Teacher.user_id.in_(class_teacher_user_ids))
    if ct_class_teacher_ids:
        query = query.filter(~Teacher.id.in_(ct_class_teacher_ids))

    return [t.to_dict() for t in query.all()]
