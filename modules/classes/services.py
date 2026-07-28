from shared.safe_error import safe_error
import logging
import uuid
from typing import List, Dict, Optional
from sqlalchemy import distinct, func, or_
from sqlalchemy.exc import IntegrityError, DataError
from sqlalchemy.orm import joinedload
from datetime import datetime

from core.database import db
from core.tenant import get_tenant_id
from .models import Class, ClassTeacher

logger = logging.getLogger(__name__)

_MISSING = object()

def _resolve_class_teacher_user_id(tenant_id: str, teacher_id: str | None) -> str | None:
    """
    `classes.teacher_id` points to `users.id`, but many client screens deal in `teachers.id`.
    Accept either:
    - a `users.id` (teacher user's id)
    - a `teachers.id` (teacher profile id)

    Returns the resolved `users.id` to store in `classes.teacher_id`, or None.
    Raises ValueError if the provided id cannot be resolved for this tenant.
    """
    if not teacher_id:
        return None

    # Try interpreting as Teacher.id first (most common client payload)
    from modules.teachers.models import Teacher

    teacher = Teacher.query.filter_by(id=teacher_id, tenant_id=tenant_id).first()
    if teacher:
        return teacher.user_id

    # Otherwise treat as User.id; validate that it's a teacher user in this tenant.
    # (At minimum validate existence; role validation may vary by deployment.)
    from modules.auth.models import User

    user = User.query.filter_by(id=teacher_id, tenant_id=tenant_id).first()
    if user:
        return user.id

    raise ValueError("Invalid teacher.")


def _resolve_department_id(department_id: Optional[str], tenant_id: str) -> tuple:
    """Validate a department_id belongs to this tenant.

    `classes.department_id` has no tenant component in its FK, so without this
    explicit lookup a department id belonging to another tenant would be
    accepted by Postgres. Mirrors `modules.teachers.services._resolve_department`,
    minus the legacy name-resolution branch — classes have no free-text
    department field to fall back to.

    Returns (department_id_or_None, error_message_or_None).
    """
    if not department_id:
        return None, None

    from modules.departments.models import Department

    exists = Department.query.filter_by(
        id=department_id, tenant_id=tenant_id, deleted_at=None
    ).first()
    if not exists:
        return None, "Department not found"
    return department_id, None


def create_class(
    name: str,
    section: str,
    academic_year_id: str,
    teacher_id: str = None,
    start_date: str = None,
    end_date: str = None,
    grade_level: Optional[int] = None,
    grade_id: Optional[str] = None,
    programme_id: Optional[str] = None,
    school_unit_id: Optional[str] = None,
    medium_id: Optional[str] = None,
    stream: Optional[str] = None,
    department_id: Optional[str] = None,
) -> Dict:
    """Create a new class (tenant-scoped). academic_year_id is required."""
    logger.warning(
        "[create_class] called: name=%r, section=%r, academic_year_id=%r, teacher_id=%r, start_date=%r, end_date=%r, grade_id=%r, programme_id=%r, school_unit_id=%r",
        name, section, academic_year_id, teacher_id, start_date, end_date, grade_id, programme_id, school_unit_id,
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
        try:
            teacher_id = _resolve_class_teacher_user_id(tenant_id, teacher_id)
        except ValueError:
            return {
                'success': False,
                'error': 'Invalid academic year or teacher. Please ensure the academic year exists and the teacher (if selected) is valid.',
            }

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

        resolved_department_id, department_error = _resolve_department_id(department_id, tenant_id)
        if department_error:
            return {'success': False, 'error': department_error}

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
            grade_level=grade_level,
            grade_id=grade_id or None,
            programme_id=programme_id or None,
            school_unit_id=school_unit_id or None,
            medium_id=medium_id or None,
            stream=stream or None,
            department_id=resolved_department_id,
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
        # Unrecognized integrity violation — log the detail, return a safe
        # message (never leak the raw SQL / parameters to the client).
        return {
            'success': False,
            'error': 'Could not create the class because it conflicts with existing data.',
        }
    except DataError as e:
        db.session.rollback()
        logger.exception(
            "create_class: DataError orig=%r",
            str(e.orig) if hasattr(e, 'orig') and e.orig else None,
        )
        # e.g. StringDataRightTruncation when section/name is too long.
        return {
            'success': False,
            'error': 'One or more fields are too long. Section must be 10 characters or fewer.',
        }
    except Exception as e:
        db.session.rollback()
        logger.exception("create_class: Exception %s", str(e))
        # Generic safe message — the detail is logged, not returned.
        return {
            'success': False,
            'error': 'Could not create the class. Please check the details and try again.',
        }


# Columns the client may sort by. Mapped to real ordering expressions in
# `_build_sort_order` so `grade` sorts by Grade.sequence (Nursery < LKG < 1)
# rather than lexicographically on the label.
SORTABLE_COLUMNS = {
    "name", "grade", "programme", "branch", "student_count", "teacher_count",
}

# Fields the client may target with `search`.
SEARCH_FIELDS = {"all", "name", "section", "grade", "programme", "branch"}

MAX_PER_PAGE = 100


def _teacher_links(tenant_id: str):
    """(class_id, user_id) for every teacher attached to a class, deduplicated.

    A class reaches its teachers two ways and both have to be counted:

    - `class_teachers` rows — subject-teacher assignments, keyed by `teachers.id`.
    - `classes.teacher_id` — the class teacher, keyed by `users.id`.

    `assign_teacher_to_class` writes both, but `create_class` / `update_class`
    set only `classes.teacher_id`, so a class whose teacher came from the normal
    form has no junction row at all. Counting the junction alone reported
    `teacher_count: 0` next to a populated `teacher_name` on the same row.

    The two columns point at different tables, so they're unioned in *user* id
    space — `teachers.user_id` is the common denominator — and UNION dedupes a
    teacher who is both class teacher and subject teacher.
    """
    from modules.teachers.models import Teacher

    via_junction = (
        db.session.query(
            ClassTeacher.class_id.label("class_id"),
            Teacher.user_id.label("user_id"),
        )
        .join(Teacher, Teacher.id == ClassTeacher.teacher_id)
        .filter(ClassTeacher.tenant_id == tenant_id)
    )
    via_class_teacher = db.session.query(
        Class.id.label("class_id"),
        Class.teacher_id.label("user_id"),
    ).filter(Class.tenant_id == tenant_id, Class.teacher_id.isnot(None))

    return via_junction.union(via_class_teacher)


def _count_subqueries(tenant_id: str):
    """Per-class student/teacher count subqueries, grouped in SQL.

    Returns (student_counts, teacher_counts) subqueries keyed by class_id.

    The tenant filter is written out explicitly rather than left to the
    automatic scope in `core.database._tenant_scope_execute`: that hook uses
    `with_loader_criteria`, which applies to ORM *entity* loads, and these are
    column-level SELECTs with no entity to hang the criterion on. Without the
    explicit filter these aggregates would count every tenant's rows.
    """
    from modules.students.models import Student

    student_counts = (
        db.session.query(
            Student.class_id.label("class_id"),
            func.count(Student.id).label("count"),
        )
        .filter(Student.tenant_id == tenant_id, Student.class_id.isnot(None))
        .group_by(Student.class_id)
        .subquery()
    )

    links = _teacher_links(tenant_id).subquery()
    teacher_counts = (
        db.session.query(
            links.c.class_id.label("class_id"),
            func.count(distinct(links.c.user_id)).label("count"),
        )
        .group_by(links.c.class_id)
        .subquery()
    )
    return student_counts, teacher_counts


def _build_sort_order(sort_by: str, sort_dir: str, student_col, teacher_col):
    """Ordering expression list for the class list query."""
    from modules.academic_programmes.models import AcademicProgramme
    from modules.grades.models import Grade
    from modules.school_units.models import SchoolUnit

    descending = sort_dir == "desc"
    column = {
        "name": Class.name,
        "grade": Grade.sequence,
        "programme": AcademicProgramme.name,
        "branch": SchoolUnit.name,
        "student_count": student_col,
        "teacher_count": teacher_col,
    }.get(sort_by, Grade.sequence)

    primary = column.desc() if descending else column.asc()
    # Section groups sensibly, but it is not unique — the same letter repeats
    # across branches and programmes, and sorting by a count ties every empty
    # class together. Without a unique final key Postgres is free to order ties
    # differently between the count and the paged query, which silently skips
    # or repeats rows across pages. Class.id is the guaranteed tiebreaker.
    return [primary, Class.section.asc(), Class.id.asc()]


def get_all_classes(
    academic_year_id: Optional[str] = None,
    school_unit_id: Optional[str] = None,
    programme_id: Optional[str] = None,
    grade_id: Optional[str] = None,
    department_id: Optional[str] = None,
    search: Optional[str] = None,
    search_field: str = "all",
    sort_by: str = "grade",
    sort_dir: str = "asc",
    page: Optional[int] = None,
    per_page: Optional[int] = None,
) -> Dict:
    """List classes for the current tenant with filters, search, sort, paging.

    Returns an envelope: {items, total, page, per_page, total_pages}. When
    `page`/`per_page` are omitted every matching row is returned with
    total_pages = 1, so callers that just want the full list (the structured
    class pickers) keep working.

    Each item carries `student_count`, `teacher_count` and a derived `status`
    ("active" when the class sits in the tenant's active academic year, else
    "archived" — `classes` has no status column of its own).
    """
    from core.branch_scope import filter_classes_by_branch
    from modules.academic_programmes.models import AcademicProgramme
    from modules.academics.academic_year.models import AcademicYear
    from modules.grades.models import Grade
    from modules.school_units.models import SchoolUnit

    tenant_id = get_tenant_id()
    student_counts, teacher_counts = _count_subqueries(tenant_id)
    student_col = func.coalesce(student_counts.c.count, 0)
    teacher_col = func.coalesce(teacher_counts.c.count, 0)

    query = (
        db.session.query(Class, student_col, teacher_col, AcademicYear.is_active)
        .outerjoin(student_counts, student_counts.c.class_id == Class.id)
        .outerjoin(teacher_counts, teacher_counts.c.class_id == Class.id)
        .outerjoin(Grade, Class.grade_id == Grade.id)
        .outerjoin(AcademicProgramme, Class.programme_id == AcademicProgramme.id)
        .outerjoin(SchoolUnit, Class.school_unit_id == SchoolUnit.id)
        .outerjoin(AcademicYear, Class.academic_year_id == AcademicYear.id)
        # Explicit tenant filter: this is a multi-entity query, so don't rely
        # on the automatic scope alone (see `_count_subqueries`).
        .filter(Class.tenant_id == tenant_id)
    )

    # Branch scope backstop: restrict to allowed branches even when no client
    # school_unit_id filter is supplied. No-op for unrestricted users.
    query = filter_classes_by_branch(query)

    if academic_year_id:
        query = query.filter(Class.academic_year_id == academic_year_id)
    if school_unit_id:
        query = query.filter(Class.school_unit_id == school_unit_id)
    if programme_id:
        query = query.filter(Class.programme_id == programme_id)
    if grade_id:
        query = query.filter(Class.grade_id == grade_id)
    if department_id:
        query = query.filter(Class.department_id == department_id)

    term = (search or "").strip()
    if term:
        like = f"%{term}%"
        by_field = {
            "name": [Class.name.ilike(like), Class.section.ilike(like)],
            "section": [Class.section.ilike(like)],
            "grade": [Grade.name.ilike(like)],
            "programme": [AcademicProgramme.name.ilike(like)],
            "branch": [SchoolUnit.name.ilike(like)],
        }
        clauses = by_field.get(search_field) or [
            c for group in by_field.values() for c in group
        ]
        query = query.filter(or_(*clauses))

    # Eager-load what to_dict() touches; otherwise each row lazy-loads six
    # relationships and we're back to the N+1 this query exists to kill.
    query = query.options(
        joinedload(Class.school_unit),
        joinedload(Class.programme),
        joinedload(Class.grade),
        joinedload(Class.medium),
        joinedload(Class.academic_year_ref),
        joinedload(Class.teacher),
    )

    total = query.order_by(None).count()

    query = query.order_by(*_build_sort_order(sort_by, sort_dir, student_col, teacher_col))

    if page and per_page:
        query = query.limit(per_page).offset((page - 1) * per_page)
        total_pages = (total + per_page - 1) // per_page if per_page else 1
    else:
        total_pages = 1

    items = []
    for cls, student_count, teacher_count, year_is_active in query.all():
        data = cls.to_dict()
        data["student_count"] = student_count or 0
        data["teacher_count"] = teacher_count or 0
        data["status"] = "active" if year_is_active else "archived"
        items.append(data)

    return {
        "items": items,
        "total": total,
        "page": page or 1,
        "per_page": per_page or total,
        "total_pages": total_pages,
    }


def get_classes_stats(
    academic_year_id: Optional[str] = None,
    school_unit_id: Optional[str] = None,
    programme_id: Optional[str] = None,
    grade_id: Optional[str] = None,
) -> Dict:
    """Aggregate totals for the classes overview header.

    Honours the same structural filters and branch scope as `get_all_classes`
    so the header always describes the list under it. Computed in one grouped
    pass rather than by summing the current page.

    `total_teachers` counts *distinct* teachers across the matching classes —
    one teacher taking four classes is one teacher, not four.
    """
    from core.branch_scope import filter_classes_by_branch
    from modules.students.models import Student

    tenant_id = get_tenant_id()

    scoped = db.session.query(Class.id).filter(Class.tenant_id == tenant_id)
    scoped = filter_classes_by_branch(scoped)
    if academic_year_id:
        scoped = scoped.filter(Class.academic_year_id == academic_year_id)
    if school_unit_id:
        scoped = scoped.filter(Class.school_unit_id == school_unit_id)
    if programme_id:
        scoped = scoped.filter(Class.programme_id == programme_id)
    if grade_id:
        scoped = scoped.filter(Class.grade_id == grade_id)

    class_ids = [row[0] for row in scoped.all()]
    total_classes = len(class_ids)
    if not total_classes:
        return {
            "total_classes": 0,
            "total_students": 0,
            "total_teachers": 0,
            "average_class_size": 0.0,
        }

    total_students = (
        db.session.query(func.count(Student.id))
        .filter(Student.tenant_id == tenant_id, Student.class_id.in_(class_ids))
        .scalar()
    ) or 0

    # Counts both attachment routes (see `_teacher_links`) in user-id space, so
    # a class teacher set through the class form is included and a teacher who
    # is both class teacher and subject teacher is counted once.
    links = _teacher_links(tenant_id).subquery()
    total_teachers = (
        db.session.query(func.count(distinct(links.c.user_id)))
        .filter(links.c.class_id.in_(class_ids))
        .scalar()
    ) or 0

    return {
        "total_classes": total_classes,
        "total_students": total_students,
        "total_teachers": total_teachers,
        "average_class_size": round(total_students / total_classes, 1),
    }


def get_class_by_id(class_id: str) -> Optional[Dict]:
    """Get class details by ID"""
    cls = Class.query.get(class_id)
    return cls.to_dict() if cls else None


def get_class_detail(class_id: str) -> Optional[Dict]:
    """Get class details with students and assigned teachers."""
    cls = Class.query.get(class_id)
    if not cls:
        return None

    from modules.students.models import Student

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
    grade_level=_MISSING,
    grade_id: Optional[str] = None,
    programme_id: Optional[str] = None,
    school_unit_id: Optional[str] = None,
    medium_id: Optional[str] = None,
    stream: Optional[str] = None,
    department_id: Optional[str] = None,
) -> Dict:
    """Update class details."""
    try:
        tenant_id = get_tenant_id()
        # Explicit tenant filter — defense in depth even though
        # TenantBaseModel scopes queries automatically.
        cls = Class.query.filter_by(id=class_id, tenant_id=tenant_id).first()
        if not cls:
            return {'success': False, 'error': 'Class not found'}

        resolved_department_id = None
        if department_id is not None:
            resolved_department_id, department_error = _resolve_department_id(department_id, tenant_id)
            if department_error:
                return {'success': False, 'error': department_error}

        if academic_year_id:
            from modules.academics.academic_year.models import AcademicYear
            ay = AcademicYear.query.filter_by(id=academic_year_id, tenant_id=tenant_id).first()
            if not ay:
                return {'success': False, 'error': 'Invalid academic year.'}

        # Check teacher is not already class teacher of another class (one teacher = one class)
        if teacher_id is not None:
            try:
                teacher_id = _resolve_class_teacher_user_id(tenant_id, teacher_id if teacher_id else None)
            except ValueError:
                return {'success': False, 'error': 'Invalid academic year or teacher.'}

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
        if grade_level is not _MISSING:
            cls.grade_level = grade_level
        if grade_id is not None:
            cls.grade_id = grade_id or None
        if programme_id is not None:
            cls.programme_id = programme_id or None
        if school_unit_id is not None:
            cls.school_unit_id = school_unit_id or None
        if medium_id is not None:
            cls.medium_id = medium_id or None
        if stream is not None:
            cls.stream = stream if stream else None
        if department_id is not None:
            cls.department_id = resolved_department_id

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
        logger.exception(
            "update_class: IntegrityError orig=%r",
            str(e.orig) if hasattr(e, 'orig') and e.orig else None,
        )
        return {'success': False, 'error': 'Could not update the class because it conflicts with existing data.'}
    except DataError as e:
        db.session.rollback()
        logger.exception("update_class: DataError orig=%r", getattr(e, 'orig', None))
        return {'success': False, 'error': 'One or more fields are too long. Section must be 10 characters or fewer.'}
    except Exception as e:
        db.session.rollback()
        logger.exception("update_class: Exception %s", str(e))
        return {'success': False, 'error': 'Could not update the class. Please check the details and try again.'}


def copy_classes_between_years(from_year_id: str, to_year_id: str) -> Dict:
    """
    Copy all classes from from_year_id to to_year_id (same name, section, grade_level, dates).
    Does not copy class teacher (teacher_id=None) to avoid uq_classes_teacher_id_tenant conflicts.

    If a matching (name, section, tenant, to_year) row already exists, it is reused in the mapping
    (idempotent).
    """
    try:
        tenant_id = get_tenant_id()
        if not tenant_id:
            return {"success": False, "error": "Tenant context is required"}
        if not from_year_id or not to_year_id:
            return {"success": False, "error": "from_year_id and to_year_id are required"}
        if from_year_id == to_year_id:
            return {"success": False, "error": "from_year_id and to_year_id must differ"}

        from modules.academics.academic_year.models import AcademicYear

        ay_from = AcademicYear.query.filter_by(id=from_year_id, tenant_id=tenant_id).first()
        ay_to = AcademicYear.query.filter_by(id=to_year_id, tenant_id=tenant_id).first()
        if not ay_from:
            return {"success": False, "error": "from_year_id not found for this tenant"}
        if not ay_to:
            return {"success": False, "error": "to_year_id not found for this tenant"}

        sources = (
            Class.query.filter_by(tenant_id=tenant_id, academic_year_id=from_year_id)
            .order_by(Class.name.asc(), Class.section.asc())
            .all()
        )

        class_mapping: Dict[str, str] = {}
        created = 0
        reused = 0

        for src in sources:
            existing = Class.query.filter_by(
                tenant_id=tenant_id,
                academic_year_id=to_year_id,
                name=src.name.strip(),
                section=src.section.strip(),
            ).first()
            if existing:
                class_mapping[src.id] = existing.id
                reused += 1
                continue

            new_row = Class(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                name=src.name.strip(),
                section=src.section.strip(),
                academic_year_id=to_year_id,
                teacher_id=None,
                start_date=src.start_date,
                end_date=src.end_date,
                grade_level=src.grade_level,
            )
            db.session.add(new_row)
            db.session.flush()
            class_mapping[src.id] = new_row.id
            created += 1

        db.session.commit()
        return {
            "success": True,
            "class_mapping": class_mapping,
            "from_year_id": from_year_id,
            "to_year_id": to_year_id,
            "source_class_count": len(sources),
            "created": created,
            "reused_existing": reused,
        }
    except IntegrityError as e:
        db.session.rollback()
        logger.exception("copy_classes_between_years IntegrityError: %s", e)
        return {
            "success": False,
            "error": "Could not copy classes (database constraint).",
        }
    except Exception as e:
        db.session.rollback()
        logger.exception("copy_classes_between_years failed: %s", e)
        return {"success": False, "error": safe_error(e)}


def delete_class(class_id: str) -> Dict:
    """Delete a class (and its subject offerings via DB-level CASCADE)."""
    tenant_id = None
    try:
        cls = Class.query.get(class_id)
        if not cls:
            return {'success': False, 'error': 'Class not found'}

        tenant_id = cls.tenant_id
        db.session.delete(cls)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return {
            'success': False,
            'error': (
                'Class cannot be deleted because data is still attached '
                '(students, attendance, fees, etc.). Remove or reassign that data first.'
            ),
        }
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': safe_error(e, "Failed to delete class")}

    if tenant_id:
        try:
            from modules.school_setup.services import recompute_setup_complete
            recompute_setup_complete(tenant_id)
        except Exception:
            pass
    return {'success': True, 'message': 'Class deleted'}


# ── Assignment Management ─────────────────────────────────────

def assign_student_to_class(class_id: str, student_id: str) -> Dict:
    """Assign a student to a class (delegates to StudentClassEnrollment)."""
    try:
        cls = Class.query.get(class_id)
        if not cls:
            return {'success': False, 'error': 'Class not found'}

        from modules.students.models import Student
        from modules.students.class_enrollment_service import assign_student_to_class as set_placement

        student = Student.query.get(student_id)
        if not student:
            return {'success': False, 'error': 'Student not found'}

        res = set_placement(student_id, class_id, cls.academic_year_id, commit=True)
        if not res.get('success'):
            return {'success': False, 'error': res.get('error', 'Assignment failed')}

        try:
            from modules.finance.services import student_fee_service

            student_fee_service.auto_assign_fees_for_student(student.id)
        except Exception:
            logger.exception('auto_assign_fees_for_student failed after class assignment')

        return {'success': True, 'message': 'Student assigned to class'}
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': safe_error(e)}


def remove_student_from_class(class_id: str, student_id: str) -> Dict:
    """Remove a student from a class (closes current enrollment; keeps academic_year_id)."""
    try:
        from modules.students.models import Student
        from modules.students.class_enrollment_service import assign_student_to_class as set_placement

        student = Student.query.get(student_id)
        if not student:
            return {'success': False, 'error': 'Student not found'}
        if student.class_id != class_id:
            return {'success': False, 'error': 'Student is not in this class'}

        res = set_placement(student_id, None, student.academic_year_id, commit=True)
        if not res.get('success'):
            return {'success': False, 'error': res.get('error', 'Remove failed')}
        return {'success': True, 'message': 'Student removed from class'}
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': safe_error(e)}


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
        from modules.teachers.models import Teacher
        from modules.subjects.models import Subject

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
        return {'success': False, 'error': safe_error(e)}


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
        return {'success': False, 'error': safe_error(e)}


def get_unassigned_students(class_id: str) -> List[Dict]:
    """Get students not assigned to any class (for assignment picker)."""
    from core.branch_scope import get_allowed_unit_ids
    # Classless students belong to no branch, so a branch-restricted sub-admin
    # must see none (graceful empty picker, not a 403). A restricted admin can't
    # assign a classless student anyway (assert_student_allowed denies classless).
    if get_allowed_unit_ids() is not None:
        return []

    from modules.students.models import Student
    students = Student.query.filter(
        db.or_(Student.class_id.is_(None), Student.class_id == '')
    ).all()
    return [s.to_dict() for s in students]


def get_unassigned_teachers(class_id: str) -> List[Dict]:
    """Get teachers not yet assigned to this class."""
    from modules.teachers.models import Teacher
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

    from modules.teachers.models import Teacher

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
