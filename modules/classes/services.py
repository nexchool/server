from shared.safe_error import safe_error
import logging
import uuid
from typing import List, Dict, Optional
from sqlalchemy import distinct, func, or_
from sqlalchemy.exc import IntegrityError, DataError
from sqlalchemy.orm import joinedload
from datetime import date, datetime

from core.database import db
from core.tenant import get_tenant_id
from modules.academics.backbone.models import (
    ClassSubjectTeacher,
    ClassTeacherAssignment,
)
from .models import Class, ClassSubject
from core.school_time import school_today

logger = logging.getLogger(__name__)

_MISSING = object()

def _resolve_class_teacher_id(tenant_id: str, teacher_id: str | None) -> str | None:
    """
    `classes.teacher_id` caches the class teacher as a `teachers.id`
    (migration 095). Clients historically sent either id, so both are accepted:
    - a `teachers.id` — what every teacher picker returns
    - a `users.id` — legacy mobile payloads, mapped to the teacher behind it

    Returns the `teachers.id` to store, or None. Raises ValueError when the id
    names nobody who teaches in this tenant — a class teacher must be a
    teacher, not merely an account.
    """
    if not teacher_id:
        return None

    from modules.teachers.models import Teacher

    teacher = Teacher.query.filter_by(id=teacher_id, tenant_id=tenant_id).first()
    if teacher is None:
        teacher = Teacher.query.filter_by(
            user_id=teacher_id, tenant_id=tenant_id
        ).first()
    if teacher:
        return teacher.id

    raise ValueError("Invalid teacher.")


def _resolve_department_id(
    department_id: Optional[str],
    tenant_id: str,
    current_department_id: Optional[str] = None,
) -> tuple:
    """Validate a department_id belongs to this tenant and is assignable.

    `classes.department_id` has no tenant component in its FK, so without this
    explicit lookup a department id belonging to another tenant would be
    accepted by Postgres. Mirrors `modules.teachers.services._resolve_department`,
    minus the legacy name-resolution branch — classes have no free-text
    department field to fall back to.

    An **inactive** department cannot be newly assigned, matching the UI, which
    already hides inactive divisions from its picker. `current_department_id` is
    what this class is already assigned to: re-sending it is retention, not
    assignment, and stays legal — the edit form seeds the field with the
    record's current value and resends it on save, so rejecting it outright
    would make a class whose division was archived impossible to edit.
    Existing rows are never rewritten as a side effect.

    A falsy `department_id` means "no department" and clears the assignment.

    Returns (department_id_or_None, error_message_or_None).
    """
    if not department_id:
        return None, None

    from modules.departments.models import DEPARTMENT_STATUS_ACTIVE, Department

    existing = Department.query.filter_by(
        id=department_id, tenant_id=tenant_id, deleted_at=None
    ).first()
    if not existing:
        return None, "Department not found"
    if (
        existing.status != DEPARTMENT_STATUS_ACTIVE
        and department_id != current_department_id
    ):
        return None, (
            f"'{existing.name}' is inactive and cannot be assigned. "
            "Reactivate it under Departments, or choose an active one."
        )
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
            teacher_id = _resolve_class_teacher_id(tenant_id, teacher_id)
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
        if teacher_id:
            # The cache was written by the constructor; the RESPONSIBILITY
            # belongs to class_teacher_assignments (ADR-014). For years this
            # path wrote only the cache, leaving class teachers the owner
            # table knew nothing about.
            _name_the_class_teacher(new_class, teacher_id)
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


def _name_the_class_teacher(cls, teacher_id):
    """Record who is responsible for this class, and refresh the cache.

    The responsibility belongs to `class_teacher_assignments` (ADR-014), so it
    is written there first and the cache is set from it. A class form that
    wrote only the cache is how the concept came to have two homes.

    `teacher_id` is a `teachers.id` (resolve with _resolve_class_teacher_id).
    """
    from modules.academics.backbone.models import ClassTeacherAssignment
    from modules.teachers.models import Teacher

    for held in ClassTeacherAssignment.query.filter_by(
        tenant_id=cls.tenant_id, class_id=cls.id, role="primary", is_active=True
    ).all():
        held.is_active = False
        db.session.add(held)
    db.session.flush()

    if not teacher_id:
        cls.teacher_id = None
        return

    teacher = Teacher.query.filter_by(tenant_id=cls.tenant_id, id=teacher_id).first()
    if teacher is None:
        cls.teacher_id = None
        return

    db.session.add(
        ClassTeacherAssignment(
            tenant_id=cls.tenant_id,
            class_id=cls.id,
            teacher_id=teacher.id,
            role="primary",
            is_active=True,
        )
    )
    cls.teacher_id = teacher.id


def _teacher_links(tenant_id: str):
    """(class_id, teacher_id) for everyone currently teaching a class.

    Asks Teaching Assignment rather than joining tables here, so this module
    does not need to know that teaching is expressed by two of them (ADR-014).

    Counted in teacher-id space now, not user-id. The previous version unioned
    `classes.teacher_id`, which is a cache — nothing may decide anything from
    it — and normalising on user_id only existed to make that union possible.
    """
    from modules.academics.teaching_assignment import current_teaching_links

    return current_teaching_links(tenant_id)


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
            func.count(distinct(links.c.teacher_id)).label("count"),
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


def _class_list_query(
    *,
    academic_year_id: Optional[str] = None,
    school_unit_id: Optional[str] = None,
    programme_id: Optional[str] = None,
    grade_id: Optional[str] = None,
    department_id: Optional[str] = None,
    search: Optional[str] = None,
    search_field: str = "all",
    include_merged: bool = False,
):
    """The one query every class list is built from.

    Both transports go through here. A filter added to one list and not the
    other is drift nobody sees until a school asks why the spreadsheet and the
    screen disagree.

    Merged-away sections are left out unless asked for. A section that was
    merged into another takes no more students — placing one there is refused
    at the primitive — so offering it in a picker is offering a choice the
    system will reject. `include_merged=True` is for the views that exist to
    explain the past: a class list someone is auditing, and the record of the
    merge itself.

    Returns (query, student_col, teacher_col). The query selects
    (Class, student_count, teacher_count, academic_year.is_active) and carries
    no ordering, no paging and no eager loads — a count should pay for none of
    those.
    """
    from core.branch_scope import assert_unit_allowed, filter_classes_by_branch
    from modules.academic_programmes.models import AcademicProgramme
    from modules.academics.academic_year.models import AcademicYear
    from modules.grades.models import Grade
    from modules.school_units.models import SchoolUnit

    # Branch scope: naming a branch outside this person's scope is a refusal,
    # not an empty list. Here rather than in a route so it holds however the
    # list is reached. No-op for unrestricted users.
    if school_unit_id:
        assert_unit_allowed(school_unit_id)

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
    if not include_merged:
        query = query.filter(Class.merged_into_class_id.is_(None))

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

    return query, student_col, teacher_col


def _with_list_relationships(query):
    """Eager-load what a rendered class row reads.

    Without this each row lazy-loads seven relationships and we are back to the
    N+1 the grouped counts exist to kill.
    """
    from modules.people.employment import Staff
    from modules.teachers.models import Teacher

    return query.options(
        joinedload(Class.school_unit),
        joinedload(Class.programme),
        joinedload(Class.grade),
        joinedload(Class.medium),
        joinedload(Class.academic_year_ref),
        # The class teacher's name reads Teacher -> Staff -> Person (ADR-001).
        joinedload(Class.teacher).joinedload(Teacher.staff).joinedload(Staff.person),
        joinedload(Class.department_ref),
    )


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
    include_merged: bool = False,
) -> Dict:
    """List classes for the current tenant with filters, search, sort, paging.

    Returns an envelope: {items, total, page, per_page, total_pages}. When
    `page`/`per_page` are omitted every matching row is returned with
    total_pages = 1.

    Each item carries `student_count`, `teacher_count` and a derived `status`
    ("active" when the class sits in the tenant's active academic year, else
    "archived" — `classes` has no status column of its own).

    This is what the CSV export renders. Screens read `classes_page`, which
    walks the same query without building every row it skips.
    """
    query, student_col, teacher_col = _class_list_query(
        academic_year_id=academic_year_id,
        school_unit_id=school_unit_id,
        programme_id=programme_id,
        grade_id=grade_id,
        department_id=department_id,
        search=search,
        search_field=search_field,
        include_merged=include_merged,
    )

    total = query.count()

    query = _with_list_relationships(query).order_by(
        *_build_sort_order(sort_by, sort_dir, student_col, teacher_col)
    )

    if page and per_page:
        query = query.limit(per_page).offset((page - 1) * per_page)
        total_pages = (total + per_page - 1) // per_page if per_page else 1
    else:
        total_pages = 1

    items = [row_to_dict(row) for row in query.all()]

    return {
        "items": items,
        "total": total,
        "page": page or 1,
        "per_page": per_page or total,
        "total_pages": total_pages,
    }


def row_to_dict(row) -> Dict:
    """One list row as the REST export renders it."""
    cls, student_count, teacher_count, year_is_active = row
    data = cls.to_dict()
    data["student_count"] = student_count or 0
    data["teacher_count"] = teacher_count or 0
    data["status"] = "active" if year_is_active else "archived"
    return data


def classes_page(
    *,
    first: int = 25,
    offset: Optional[int] = None,
    sort_by: str = "grade",
    sort_dir: str = "asc",
    **filters,
):
    """One page of classes, and whether another follows.

    Paged by offset rather than by cursor, deliberately. A cursor is only sound
    over a key that cannot be null and does not change, and a class list has
    none: every order it offers is either nullable (a class may have no grade),
    mutable (grade order, a name), or a count that changes as children are
    admitted. Offering a cursor over those would not error — it would quietly
    skip classes.

    The cost is one a class list can carry. Unlike students, a school's classes
    are bounded by its own structure: twenty campuses of forty sections is
    eight hundred rows, not fifteen thousand.

    Returns (rows, has_more). One row more than asked for is fetched, and that
    extra row *is* `hasNextPage` — no second query.
    """
    first = max(1, min(int(first), MAX_PER_PAGE))

    query, student_col, teacher_col = _class_list_query(**filters)
    query = _with_list_relationships(query).order_by(
        *_build_sort_order(sort_by, sort_dir, student_col, teacher_col)
    )

    if offset:
        query = query.offset(max(0, int(offset)))

    rows = query.limit(first + 1).all()
    return rows[:first], len(rows) > first


def classes_matching_count(**filters) -> int:
    """How many classes the same filters match, ignoring paging.

    Separate from the page so a caller that shows no total does not pay for
    one. Sorting cannot change a count, so it is not accepted here.
    """
    query, _student_col, _teacher_col = _class_list_query(**filters)
    return query.count()


def get_classes_stats(
    academic_year_id: Optional[str] = None,
    school_unit_id: Optional[str] = None,
    programme_id: Optional[str] = None,
    grade_id: Optional[str] = None,
    department_id: Optional[str] = None,
) -> Dict:
    """Aggregate totals for the classes overview header.

    Honours the same structural filters and branch scope as `get_all_classes`
    so the header always describes the list under it. Computed in one grouped
    pass rather than by summing the current page.

    `total_teachers` counts *distinct* teachers across the matching classes —
    one teacher taking four classes is one teacher, not four.
    """
    from core.branch_scope import assert_unit_allowed, filter_classes_by_branch
    from modules.students.models import Student

    # Same refusal the list makes: a branch outside this person's scope is a
    # "no", not a zero. No-op for unrestricted users.
    if school_unit_id:
        assert_unit_allowed(school_unit_id)

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
    if department_id:
        scoped = scoped.filter(Class.department_id == department_id)

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

    # A teacher who is both class teacher and subject teacher is counted once.
    links = _teacher_links(tenant_id).subquery()
    total_teachers = (
        db.session.query(func.count(distinct(links.c.teacher_id)))
        .filter(links.c.class_id.in_(class_ids))
        .scalar()
    ) or 0

    return {
        "total_classes": total_classes,
        "total_students": total_students,
        "total_teachers": total_teachers,
        "average_class_size": round(total_students / total_classes, 1),
    }


def class_detail(class_id: str) -> Optional[Dict]:
    """One class, the children placed in it and everyone teaching it.

    Returns rows rather than serialized dicts: the transport builds the shape
    a client renders, and a serializer that carries every column is what the
    REST payload already was.

    Branch scope is asserted here rather than by a caller, so it holds however
    this is reached — a class in a branch outside the reader's scope is a
    refusal, not an empty page.
    """
    from core.branch_scope import assert_class_allowed

    assert_class_allowed(class_id)  # no-op for unrestricted users

    cls = _with_list_relationships(Class.query).filter(Class.id == class_id).first()
    if not cls:
        return None

    from modules.students.models import Student

    students = (
        Student.query.options(joinedload(Student.person))
        .filter(Student.class_id == class_id)
        .all()
    )

    return {
        "class": cls,
        "status": (
            "active"
            if cls.academic_year_ref and cls.academic_year_ref.is_active
            else "archived"
        ),
        "students": students,
        "teachers": _teaching_this_class(class_id),
    }


def legacy_detail_payload(detail: Dict) -> Dict:
    """`class_detail` in the keys the Expo client already reads.

    ⚠️ Exists for `GET /api/classes/<id>` only; admin-web reads the GraphQL
    `class` field. Deliberately a second *shape*, never a second *reader* —
    the previous version of this was a second reader, and the two drifted.
    Delete with the Expo release that moves the mobile app.
    """
    cls = detail["class"]
    students = detail["students"]
    data = cls.to_dict()
    data["status"] = detail["status"]
    data["students"] = [student.to_dict() for student in students]
    data["teachers"] = [
        {
            "teacher_id": held["teacher_id"],
            "teacher_name": held["teacher_name"],
            "subject_id": held["subject_id"],
            "role": held["role"],
            "is_class_teacher": held["is_class_teacher"],
        }
        for held in detail["teachers"]
    ]
    data["student_count"] = len(students)
    data["teacher_count"] = len(data["teachers"])
    return data


def _teaching_this_class(class_id: str) -> List[Dict]:
    """Everyone teaching a class, whatever their responsibility.

    Asks Teaching Assignment for the responsibilities (ADR-014), then names
    them once: the teacher through Staff -> Person (ADR-001), their employee
    number from the employment that holds it, and the subject from the
    catalogue. Naming them here rather than per row is what keeps the detail
    page at three queries instead of one per teacher.
    """
    from modules.academics.teaching_assignment import (
        class_teachers_for,
        subject_teachers_for,
    )
    from modules.people.employment import Staff
    from modules.subjects.models import Subject
    from modules.teachers.models import Teacher

    holding = list(class_teachers_for([class_id]).get(class_id, []))
    for subject_held in subject_teachers_for([class_id]).values():
        holding.extend(subject_held)
    if not holding:
        return []

    teachers = {
        teacher.id: teacher
        for teacher in Teacher.query.options(
            joinedload(Teacher.staff).joinedload(Staff.person)
        )
        .filter(Teacher.id.in_({held.teacher_id for held in holding}))
        .all()
    }
    wanted_subjects = {held.subject_id for held in holding if held.subject_id}
    subjects = (
        {
            subject.id: subject
            for subject in Subject.query.filter(Subject.id.in_(wanted_subjects)).all()
        }
        if wanted_subjects
        else {}
    )

    named = []
    for held in holding:
        teacher = teachers.get(held.teacher_id)
        employment = teacher.staff if teacher else None
        subject = subjects.get(held.subject_id) if held.subject_id else None
        named.append(
            {
                "teacher_id": held.teacher_id,
                "teacher_name": (
                    employment.person.full_name
                    if employment and employment.person
                    else None
                ),
                "employee_number": employment.employee_number if employment else None,
                "subject_id": held.subject_id,
                "subject_name": subject.name if subject else None,
                "role": held.role,
                "is_class_teacher": held.subject_id is None,
            }
        )
    return named


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
    department_id=_MISSING,
) -> Dict:
    """Update class details.

    `department_id` defaults to the `_MISSING` sentinel (the same one
    `grade_level` already uses above) rather than `None`, so the three
    states a department picker needs stay distinguishable: key omitted
    (leave the class's department alone), key explicitly null (unassign
    it), key set to a real id (reassign it, once verified to belong to
    this tenant). A plain `None` default would make "omitted" and
    "explicitly cleared" the same value and silently prevent ever
    unassigning a department once set — see
    `modules.teachers.services.update_teacher` for the same fix applied
    to `teachers.department_id`.
    """
    try:
        tenant_id = get_tenant_id()
        # Explicit tenant filter — defense in depth even though
        # TenantBaseModel scopes queries automatically.
        cls = Class.query.filter_by(id=class_id, tenant_id=tenant_id).first()
        if not cls:
            return {'success': False, 'error': 'Class not found'}

        resolved_department_id = _MISSING
        if department_id is not _MISSING:
            resolved_department_id, department_error = _resolve_department_id(
                department_id, tenant_id, current_department_id=cls.department_id
            )
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
                teacher_id = _resolve_class_teacher_id(tenant_id, teacher_id if teacher_id else None)
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
            # The class form names a class teacher by their login. Record the
            # responsibility where it is owned, then let the cache follow —
            # writing only the cache is what let this concept have two homes.
            _name_the_class_teacher(cls, teacher_id or None)
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
        if department_id is not _MISSING:
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

        from modules.academics.teaching_assignment import teaches_anything_in

        if teaches_anything_in(teacher_id, class_id):
            return {'success': False, 'error': 'Teacher already assigned to this class'}

        if is_class_teacher:
            # One teacher can only be class teacher of one class
            existing_as_ct_via_class = Class.query.filter(
                Class.tenant_id == cls.tenant_id,
                Class.teacher_id == teacher.id,
                Class.id != class_id,
            ).first()
            if existing_as_ct_via_class:
                return {
                    'success': False,
                    'error': 'This teacher is already the class teacher of another class. A teacher can only be class teacher of one class.',
                }

            elsewhere = ClassTeacherAssignment.query.filter(
                ClassTeacherAssignment.tenant_id == cls.tenant_id,
                ClassTeacherAssignment.teacher_id == teacher_id,
                ClassTeacherAssignment.role == "primary",
                ClassTeacherAssignment.is_active.is_(True),
                ClassTeacherAssignment.deleted_at.is_(None),
                ClassTeacherAssignment.class_id != class_id,
            ).first()
            if elsewhere:
                return {
                    'success': False,
                    'error': 'This teacher is already the class teacher of another class. A teacher can only be class teacher of one class.',
                }

            # Only one class teacher per class: stand down whoever held it.
            for held in ClassTeacherAssignment.query.filter_by(
                tenant_id=cls.tenant_id, class_id=class_id, role="primary", is_active=True
            ).all():
                held.is_active = False
                db.session.add(held)
            db.session.flush()

            db.session.add(
                ClassTeacherAssignment(
                    tenant_id=cls.tenant_id,
                    class_id=class_id,
                    teacher_id=teacher_id,
                    role="primary",
                    is_active=True,
                )
            )
            # The cache follows the owner; nothing decides from it (ADR-014).
            cls.teacher_id = teacher.id
            db.session.add(cls)

        if subject_id_val:
            offered = ClassSubject.query.filter_by(
                tenant_id=cls.tenant_id, class_id=class_id, subject_id=subject_id_val
            ).first()
            if offered is None:
                return {
                    'success': False,
                    'error': (
                        'This class does not offer that subject yet. Add it to the '
                        "class's subjects first, then assign a teacher to it."
                    ),
                }

            already = ClassSubjectTeacher.query.filter_by(
                tenant_id=cls.tenant_id,
                class_subject_id=offered.id,
                teacher_id=teacher_id,
            ).first()
            if already is None:
                db.session.add(
                    ClassSubjectTeacher(
                        tenant_id=cls.tenant_id,
                        class_subject_id=offered.id,
                        teacher_id=teacher_id,
                        role="primary",
                        is_active=True,
                    )
                )
            else:
                already.is_active = True
                db.session.add(already)

        db.session.commit()
        return {
            'success': True,
            'assignment': {
                'class_id': class_id,
                'teacher_id': teacher_id,
                'subject_id': subject_id_val,
                'is_class_teacher': is_class_teacher,
            },
            'message': 'Teacher assigned to class',
        }
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': safe_error(e)}


def remove_teacher_from_class(class_id: str, teacher_id: str) -> Dict:
    """Stand this teacher's responsibilities for the class down.

    Ended rather than deleted: a teacher who taught this class until today did
    teach it, and marks and attendance already attributed to them must keep
    resolving to them when asked about a date in the past (ADR-014).
    """
    try:
        from modules.academics.backbone.models import (
            ClassSubjectTeacher,
            ClassTeacherAssignment,
        )
        from modules.academics.teaching_assignment import teaches_anything_in
        from modules.teachers.models import Teacher

        if not teaches_anything_in(teacher_id, class_id):
            return {'success': False, 'error': 'Teacher is not assigned to this class'}

        ended_on = school_today()
        for held in ClassTeacherAssignment.query.filter_by(
            tenant_id=get_tenant_id(), class_id=class_id,
            teacher_id=teacher_id, is_active=True,
        ).all():
            held.is_active = False
            held.effective_to = held.effective_to or ended_on
            db.session.add(held)

        offered_here = db.session.query(ClassSubject.id).filter(
            ClassSubject.tenant_id == get_tenant_id(),
            ClassSubject.class_id == class_id,
        )
        for held in ClassSubjectTeacher.query.filter(
            ClassSubjectTeacher.tenant_id == get_tenant_id(),
            ClassSubjectTeacher.teacher_id == teacher_id,
            ClassSubjectTeacher.class_subject_id.in_(offered_here),
            ClassSubjectTeacher.is_active.is_(True),
        ).all():
            held.is_active = False
            held.effective_to = held.effective_to or ended_on
            db.session.add(held)

        cls = Class.query.filter_by(id=class_id, tenant_id=get_tenant_id()).first()
        teacher = Teacher.query.filter_by(id=teacher_id).first()
        if cls and teacher and cls.teacher_id == teacher.id:
            cls.teacher_id = None
            db.session.add(cls)

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


def _currently_teaching():
    """Teachers the school can still assign: those whose employment is current.

    Whether someone still works here is the employment's answer (ADR-005), not
    a flag on the teaching record — otherwise a teacher who has left keeps
    turning up in pickers.
    """
    from modules.people.employment import EMPLOYED_STATUSES, Staff
    from modules.teachers.models import Teacher

    return Teacher.query.join(Staff, Teacher.staff_id == Staff.id).filter(
        Staff.employment_status.in_(EMPLOYED_STATUSES)
    )


def get_unassigned_teachers(class_id: str) -> List[Dict]:
    """Get teachers not yet assigned to this class."""
    from modules.teachers.models import Teacher
    from modules.academics.teaching_assignment import teacher_ids_teaching_in

    assigned_ids = list(teacher_ids_teaching_in([class_id]))
    query = _currently_teaching()
    if assigned_ids:
        query = query.filter(~Teacher.id.in_(assigned_ids))
    return [t.to_dict() for t in query.all()]


def get_available_class_teachers(class_id: str = None) -> List[Dict]:
    """
    Get teachers who can be selected as class teacher.
    Excludes teachers who are already class teachers of another class.
    If class_id is given (e.g. when editing), includes the current class's teacher.
    A teacher is a class teacher if class_teacher_assignments says so (ADR-014).
    """
    tenant_id = get_tenant_id()
    if not tenant_id:
        return []

    from modules.teachers.models import Teacher

    # Teacher ids already cached as class teacher (exclude class_id if editing).
    # The cache keys on teachers.id since migration 095, so this set and the
    # owner-table set below live in the same id space.
    class_filter = Class.query.filter(
        Class.tenant_id == tenant_id,
        Class.teacher_id.isnot(None),
    )
    if class_id:
        class_filter = class_filter.filter(Class.id != class_id)
    cached_class_teacher_ids = {c.teacher_id for c in class_filter.all()}

    # Teachers already responsible for another class, per the owner table.
    ct_filter = ClassTeacherAssignment.query.filter(
        ClassTeacherAssignment.tenant_id == tenant_id,
        ClassTeacherAssignment.role == "primary",
        ClassTeacherAssignment.is_active.is_(True),
        ClassTeacherAssignment.deleted_at.is_(None),
    )
    if class_id:
        ct_filter = ct_filter.filter(ClassTeacherAssignment.class_id != class_id)
    ct_class_teacher_ids = {held.teacher_id for held in ct_filter.all()}

    query = _currently_teaching()
    already_holding = cached_class_teacher_ids | ct_class_teacher_ids
    if already_holding:
        query = query.filter(~Teacher.id.in_(already_holding))

    return [t.to_dict() for t in query.all()]
