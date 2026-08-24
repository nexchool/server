"""
Subject Services

Business logic for subject CRUD operations. All operations are tenant-scoped.
"""
from shared.safe_error import safe_error

from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from core.database import db
from core.tenant import get_tenant_id

from .models import Subject
from core.school_time import utc_now

# Keep in sync with seed_service (mts.yaml uses language / co_curricular) and
# admin-web src/types/subject.ts.
SUBJECT_TYPES = ("core", "elective", "language", "activity", "co_curricular", "other")


def create_subject(data: Dict, tenant_id: str) -> Dict:
    """
    Create a new subject (tenant-scoped).

    Args:
        data: Dict with name (required), code (optional), description (optional),
            subject_type (optional), class_ids (optional — assign the new subject
            to these classes atomically), weekly_periods (optional, with class_ids)
        tenant_id: Tenant ID for scoping

    Returns:
        Dict with success status and subject data or error. When class_ids were
        given, includes "assignment": {created_count, skipped_count}.
    """
    try:
        if not tenant_id:
            return {"success": False, "error": "Tenant context is required"}

        name = (data.get("name") or "").strip()
        if not name:
            return {"success": False, "error": "name is required"}

        class_ids = data.get("class_ids") or []
        if not isinstance(class_ids, list):
            return {"success": False, "error": "class_ids must be a list"}
        class_ids = [c for c in class_ids if c]

        code = (data.get("code") or "").strip() or None
        if code:
            dup = Subject.query.filter(
                Subject.tenant_id == tenant_id,
                Subject.code == code,
                Subject.deleted_at.is_(None),
            ).first()
            if dup:
                return {"success": False, "error": "Subject with this code already exists"}

        subject_type = (data.get("subject_type") or "core").strip()
        if subject_type not in SUBJECT_TYPES:
            return {
                "success": False,
                "error": f"subject_type must be one of: {', '.join(SUBJECT_TYPES)}",
            }

        subject = Subject(
            tenant_id=tenant_id,
            name=name,
            code=code,
            description=(data.get("description") or "").strip() or None,
            subject_type=subject_type,
            is_active=bool(data.get("is_active", True)),
        )

        if not class_ids:
            subject.save()
            return {"success": True, "subject": subject.to_dict()}

        # Atomic create + assign: flush the subject (visible to the bulk-assign
        # validation via autoflush) and let bulk_assign_class_subjects run its
        # own class/weekly_periods validation. Its final commit persists both;
        # any validation error rolls the pending subject back too.
        from modules.classes.bulk_services import bulk_assign_class_subjects

        db.session.add(subject)
        db.session.flush()
        assignment = bulk_assign_class_subjects(
            {
                "class_ids": class_ids,
                "subject_ids": [subject.id],
                "weekly_periods": data.get("weekly_periods", 1),
            },
            tenant_id,
        )
        if not assignment.get("success"):
            db.session.rollback()
            return {"success": False, "error": assignment.get("error", "Class assignment failed")}

        return {
            "success": True,
            "subject": subject.to_dict(),
            "assignment": {
                "created_count": assignment.get("created_count", 0),
                "skipped_count": assignment.get("skipped_count", 0),
            },
        }
    except IntegrityError as e:
        db.session.rollback()
        error_msg = str(getattr(e, "orig", None) or e)
        if (
            "uq_subjects_tenant_code_active" in error_msg
            or "uq_subjects_code_tenant" in error_msg
            or "subjects" in error_msg.lower()
            and "code" in error_msg.lower()
            and "unique" in error_msg.lower()
        ):
            return {"success": False, "error": "Subject with this code already exists"}
        return {"success": False, "error": "Database constraint violation"}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": safe_error(e)}


def list_subjects_filtered(tenant_id: str, include_inactive: bool = False) -> List[Dict]:
    """List subjects without Flask request; optional inactive rows."""
    q = Subject.query.filter_by(tenant_id=tenant_id).filter(Subject.deleted_at.is_(None))
    if not include_inactive:
        q = q.filter(Subject.is_active.is_(True))
    subjects = q.order_by(Subject.name).all()
    return [s.to_dict() for s in subjects]


LIST_SORT_FIELDS = {
    "name": Subject.name,
    "code": Subject.code,
    "subject_type": Subject.subject_type,
    "created_at": Subject.created_at,
    "updated_at": Subject.updated_at,
}

MAX_PER_PAGE = 100
DEFAULT_PER_PAGE = 20


def _subject_catalogue_query(
    tenant_id: str,
    *,
    search: Optional[str] = None,
    subject_type: Optional[str] = None,
    include_inactive: bool = False,
):
    """The one query the subject catalogue is read through.

    Search is a case-insensitive contains-match on name / code / description.
    Carries no ordering and no paging — a count should pay for neither.
    """
    q = Subject.query.filter(
        Subject.tenant_id == tenant_id, Subject.deleted_at.is_(None)
    )
    if not include_inactive:
        q = q.filter(Subject.is_active.is_(True))
    if subject_type in SUBJECT_TYPES:
        q = q.filter(Subject.subject_type == subject_type)

    term = (search or "").strip()
    if term:
        like = f"%{term}%"
        q = q.filter(
            or_(
                Subject.name.ilike(like),
                Subject.code.ilike(like),
                Subject.description.ilike(like),
            )
        )
    return q


def subjects_page(
    tenant_id: str,
    *,
    first: int = DEFAULT_PER_PAGE,
    offset: Optional[int] = None,
    sort_by: str = "name",
    sort_dir: str = "asc",
    **filters,
):
    """One page of the subject catalogue, and whether another follows.

    Each item carries its active class assignments (`classes`) and the distinct
    programmes derived from them (`programmes`) — the catalogue answers "where
    is this taught", which is the question the screen exists for.

    Paged by offset rather than by cursor, for the reason the class list is
    (see `graphql-conventions.md` §3): no order this offers has a key that is
    both unique and unchanging — a code may be empty, a name may be corrected —
    and a cursor over such a key does not fail, it skips rows. A school's
    catalogue is dozens of subjects, so offset costs nothing here.

    Returns (items, has_more). One row more than asked for is fetched, and that
    extra row *is* `hasNextPage` — no second query.
    """
    first = min(max(int(first), 1), MAX_PER_PAGE)

    sort_col = LIST_SORT_FIELDS.get(sort_by, Subject.name)
    ordered = sort_col.desc() if sort_dir == "desc" else sort_col.asc()
    # Name then id break the tie: neither the sort key nor the name is unique,
    # and without a final unique key a page boundary can repeat or skip a row.
    query = _subject_catalogue_query(tenant_id, **filters).order_by(
        ordered, Subject.name.asc(), Subject.id.asc()
    )

    if offset:
        query = query.offset(max(0, int(offset)))

    rows = query.limit(first + 1).all()
    return _serialize_catalogue(tenant_id, rows[:first]), len(rows) > first


def subjects_matching_count(tenant_id: str, **filters) -> int:
    """How many subjects the same filters match, ignoring paging.

    Separate from the page so a caller that shows no total does not pay for
    one; sorting cannot change a count, so it is not accepted here.
    """
    return _subject_catalogue_query(tenant_id, **filters).count()


def _serialize_catalogue(tenant_id: str, subjects: List) -> List[Dict]:
    """to_dict() + active class assignments + derived programmes, without N+1.

    One grouped ClassSubject query for the whole page; programme/grade come in
    via joinedload on the class relationship.
    """
    from modules.classes.models import Class, ClassSubject

    subject_ids = [s.id for s in subjects]
    class_subjects = []
    if subject_ids:
        class_subjects = (
            ClassSubject.query.options(
                joinedload(ClassSubject.class_ref).joinedload(Class.programme),
                joinedload(ClassSubject.class_ref).joinedload(Class.grade),
            )
            .filter(
                ClassSubject.tenant_id == tenant_id,
                ClassSubject.subject_id.in_(subject_ids),
                ClassSubject.deleted_at.is_(None),
                ClassSubject.status == "active",
            )
            .all()
        )

    classes_by_subject: Dict[str, List[Dict]] = {}
    for cs in class_subjects:
        klass = cs.class_ref
        programme = klass.programme if klass is not None else None
        grade = klass.grade if klass is not None else None
        classes_by_subject.setdefault(cs.subject_id, []).append(
            {
                "class_subject_id": cs.id,
                "class_id": cs.class_id,
                "class_name": _class_label(klass),
                "grade_name": grade.name if grade is not None else None,
                "programme_id": programme.id if programme is not None else None,
                "programme_name": programme.name if programme is not None else None,
                "weekly_periods": cs.weekly_periods,
                "is_mandatory": cs.is_mandatory,
            }
        )

    items: List[Dict] = []
    for subject in subjects:
        row = subject.to_dict()
        classes = sorted(
            classes_by_subject.get(subject.id, []),
            key=lambda c: (c["class_name"] or ""),
        )
        programmes: Dict[str, Dict] = {}
        for c in classes:
            if c["programme_id"] and c["programme_id"] not in programmes:
                programmes[c["programme_id"]] = {
                    "id": c["programme_id"],
                    "name": c["programme_name"],
                }
        row["classes"] = classes
        row["programmes"] = sorted(
            programmes.values(), key=lambda p: (p["name"] or "")
        )
        items.append(row)
    return items


def get_subject_by_id(subject_id: str, tenant_id: str) -> Optional[Dict]:
    """
    Get a subject by ID (tenant-scoped).

    Args:
        subject_id: Subject UUID
        tenant_id: Tenant ID for scoping

    Returns:
        Subject dict or None if not found
    """
    subject = Subject.query.filter_by(id=subject_id, tenant_id=tenant_id).filter(
        Subject.deleted_at.is_(None)
    ).first()
    return subject.to_dict() if subject else None


def update_subject(subject_id: str, data: Dict, tenant_id: str) -> Dict:
    """
    Update a subject (tenant-scoped).

    Args:
        subject_id: Subject UUID
        data: Dict with optional name, code, description
        tenant_id: Tenant ID for scoping

    Returns:
        Dict with success status and updated subject data or error
    """
    try:
        subject = Subject.query.filter_by(id=subject_id, tenant_id=tenant_id).filter(
            Subject.deleted_at.is_(None)
        ).first()
        if not subject:
            return {"success": False, "error": "Subject not found"}

        if "name" in data and data["name"] is not None:
            name = (data["name"] or "").strip()
            if not name:
                return {"success": False, "error": "name cannot be empty"}
            subject.name = name

        if "code" in data:
            code = (data["code"] or "").strip() or None
            if code:
                dup = Subject.query.filter(
                    Subject.tenant_id == tenant_id,
                    Subject.code == code,
                    Subject.id != subject_id,
                    Subject.deleted_at.is_(None),
                ).first()
                if dup:
                    return {"success": False, "error": "Subject with this code already exists"}
            subject.code = code
        if "description" in data:
            subject.description = (data["description"] or "").strip() or None
        if "subject_type" in data and data["subject_type"] is not None:
            st = str(data["subject_type"]).strip()
            if st not in SUBJECT_TYPES:
                return {
                    "success": False,
                    "error": f"subject_type must be one of: {', '.join(SUBJECT_TYPES)}",
                }
            subject.subject_type = st
        if "is_active" in data and data["is_active"] is not None:
            subject.is_active = bool(data["is_active"])

        subject.updated_at = utc_now()
        subject.save()
        return {"success": True, "subject": subject.to_dict()}
    except IntegrityError as e:
        db.session.rollback()
        error_msg = str(getattr(e, "orig", None) or e)
        if (
            "uq_subjects_tenant_code_active" in error_msg
            or "uq_subjects_code_tenant" in error_msg
            or "subjects" in error_msg.lower()
            and "code" in error_msg.lower()
            and "unique" in error_msg.lower()
        ):
            return {"success": False, "error": "Subject with this code already exists"}
        return {"success": False, "error": "Database constraint violation"}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": safe_error(e)}


def delete_subject(subject_id: str, tenant_id: str) -> Dict:
    """
    Soft-archive a subject. Hard delete is not used when the subject is referenced.
    """
    try:
        from modules.classes.models import ClassSubject

        subject = Subject.query.filter_by(id=subject_id, tenant_id=tenant_id).filter(
            Subject.deleted_at.is_(None)
        ).first()
        if not subject:
            return {"success": False, "error": "Subject not found"}

        ref = ClassSubject.query.filter(
            ClassSubject.tenant_id == tenant_id,
            ClassSubject.subject_id == subject_id,
            ClassSubject.deleted_at.is_(None),
        ).first()
        if ref:
            return {
                "success": False,
                "error": "Subject is referenced by one or more classes. Remove it from those classes first to delete it.",
            }

        subject.is_active = False
        subject.deleted_at = datetime.now(timezone.utc)
        db.session.add(subject)
        db.session.commit()
        return {"success": True, "message": "Subject archived successfully"}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": safe_error(e)}


# ---------------------------------------------------------------------------
# Role-scoped subjects: GET /api/subjects/mine
#
# Scoping happens server-side because students/parents do not hold
# subject.read / class_subject.read permissions, so client-side filtering is
# impossible (and against the project's security rules).
# ---------------------------------------------------------------------------

ROLE_ADMIN_PERMISSION = "subject.manage"


def _teacher_display_name(teacher) -> Optional[str]:
    """Teacher has no name column; the name belongs to the person (ADR-001)."""
    if teacher is None:
        return None
    employment = teacher.staff
    person = employment.person if employment else None
    name = person.full_name if person else None
    return name or (employment.employee_number if employment else None)


def _class_label(klass) -> Optional[str]:
    """What the school calls the class, from the class itself.

    Composing it here is what named every class "A": `Class.name` is empty for
    every class the structured form creates, and the section alone repeats
    across grades, programmes and campuses.
    """
    return klass.display_name if klass is not None else None


def _active_class_subjects_query(tenant_id: str):
    """Active, non-deleted class_subjects for a tenant, with class + subject
    eagerly loaded to avoid N+1."""
    from modules.classes.models import ClassSubject

    return (
        ClassSubject.query.options(
            joinedload(ClassSubject.subject_ref),
            joinedload(ClassSubject.class_ref),
        )
        .filter(
            ClassSubject.tenant_id == tenant_id,
            ClassSubject.deleted_at.is_(None),
            ClassSubject.status == "active",
        )
    )


def _teachers_for_class_subjects(tenant_id: str, class_subject_ids: List[str]) -> Dict[str, List[Dict]]:
    """Map class_subject_id -> list of {teacher_id, teacher_name, role}.

    Single query for all class_subjects to avoid N+1.
    """
    from modules.academics.backbone.models import ClassSubjectTeacher

    grouped: Dict[str, List[Dict]] = {}
    if not class_subject_ids:
        return grouped

    rows = (
        ClassSubjectTeacher.query.options(joinedload(ClassSubjectTeacher.teacher))
        .filter(
            ClassSubjectTeacher.tenant_id == tenant_id,
            ClassSubjectTeacher.class_subject_id.in_(class_subject_ids),
            ClassSubjectTeacher.is_active.is_(True),
            ClassSubjectTeacher.deleted_at.is_(None),
        )
        .all()
    )
    for cst in rows:
        grouped.setdefault(cst.class_subject_id, []).append(
            {
                "teacher_id": cst.teacher_id,
                "teacher_name": _teacher_display_name(cst.teacher),
                "role": cst.role,
            }
        )
    return grouped


def _serialize_grouped(tenant_id: str, subjects: List, class_subjects: List) -> List[Dict]:
    """Group class_subjects under their subjects and serialize.

    Args:
        subjects: Subject rows to include (order is preserved).
        class_subjects: ClassSubject rows that belong to those subjects.
    """
    teachers_by_cs = _teachers_for_class_subjects(
        tenant_id, [cs.id for cs in class_subjects]
    )

    classes_by_subject: Dict[str, List[Dict]] = {}
    for cs in class_subjects:
        classes_by_subject.setdefault(cs.subject_id, []).append(
            {
                "class_id": cs.class_id,
                "class_name": _class_label(cs.class_ref),
                "is_mandatory": cs.is_mandatory,
                "weekly_periods": cs.weekly_periods,
                "teachers": teachers_by_cs.get(cs.id, []),
            }
        )

    result: List[Dict] = []
    for subject in subjects:
        result.append(
            {
                "id": subject.id,
                "name": subject.name,
                "code": subject.code,
                "subject_type": subject.subject_type,
                "description": subject.description,
                "classes": classes_by_subject.get(subject.id, []),
            }
        )
    return result


def _subjects_for_admin(tenant_id: str) -> List[Dict]:
    from modules.classes.models import ClassSubject

    subjects = (
        Subject.query.filter(
            Subject.tenant_id == tenant_id,
            Subject.deleted_at.is_(None),
            Subject.is_active.is_(True),
        )
        .order_by(Subject.name)
        .all()
    )
    subject_ids = [s.id for s in subjects]
    class_subjects = (
        _active_class_subjects_query(tenant_id)
        .filter(ClassSubject.subject_id.in_(subject_ids))
        .all()
        if subject_ids
        else []
    )
    return _serialize_grouped(tenant_id, subjects, class_subjects)


def _subjects_for_class_subject_rows(tenant_id: str, class_subjects: List) -> List[Dict]:
    """Build the response from a set of class_subject rows (teacher/student paths).

    Subjects with no class_subjects naturally do not appear.
    """
    # Filter to active, non-deleted subjects and preserve a stable name order.
    active_subjects: Dict[str, object] = {}
    for cs in class_subjects:
        subject = cs.subject_ref
        if subject is None or subject.deleted_at is not None or not subject.is_active:
            continue
        active_subjects.setdefault(subject.id, subject)

    kept_class_subjects = [
        cs for cs in class_subjects if cs.subject_id in active_subjects
    ]
    subjects = sorted(active_subjects.values(), key=lambda s: (s.name or "").lower())
    return _serialize_grouped(tenant_id, subjects, kept_class_subjects)


def _subjects_for_teacher(tenant_id: str, teacher_id: str) -> List[Dict]:
    from modules.academics.backbone.models import ClassSubjectTeacher
    from modules.classes.models import ClassSubject

    taught_cs_ids = [
        row.class_subject_id
        for row in ClassSubjectTeacher.query.filter(
            ClassSubjectTeacher.tenant_id == tenant_id,
            ClassSubjectTeacher.teacher_id == teacher_id,
            ClassSubjectTeacher.is_active.is_(True),
            ClassSubjectTeacher.deleted_at.is_(None),
        ).all()
    ]
    if not taught_cs_ids:
        return []

    class_subjects = (
        _active_class_subjects_query(tenant_id)
        .filter(ClassSubject.id.in_(taught_cs_ids))
        .all()
    )
    return _subjects_for_class_subject_rows(tenant_id, class_subjects)


def _subjects_for_student(
    tenant_id: str, class_id: str, enrollment_id: Optional[str] = None
) -> List[Dict]:
    from modules.classes.models import ClassSubject

    if not class_id:
        return []

    class_subjects = (
        _active_class_subjects_query(tenant_id)
        .filter(ClassSubject.class_id == class_id)
        .all()
    )

    # A student studies what their class offers, minus what they dropped or
    # were excused from, plus the electives they chose. `effective_class_subjects`
    # is the one place that rule lives — this reads it rather than repeating it,
    # which is what stops the timetable, attendance and examinations each
    # arriving at a slightly different subject list.
    if enrollment_id:
        from modules.students.election_service import effective_class_subjects

        allowed = {
            cs.id for cs in effective_class_subjects(enrollment_id, tenant_id)
        }
        class_subjects = [cs for cs in class_subjects if cs.id in allowed]

    return _subjects_for_class_subject_rows(tenant_id, class_subjects)


def get_subjects_for_user(tenant_id: str, user) -> List[Dict]:
    """Return subjects scoped to the authenticated user's role.

    - admin (holds subject.manage) → all active tenant subjects
    - teacher → subjects in classes they teach
    - student → subjects in their own class
    - anyone else → []

    Every query is filtered by tenant_id to prevent cross-tenant leakage.
    """
    if not tenant_id or user is None:
        return []

    from modules.rbac.services import has_permission

    if has_permission(user.id, ROLE_ADMIN_PERMISSION):
        return _subjects_for_admin(tenant_id)

    from modules.teachers.services import teacher_for_user

    teacher = teacher_for_user(user.id, tenant_id)
    if teacher is not None:
        return _subjects_for_teacher(tenant_id, teacher.id)

    from modules.students.services import student_for_user

    student = student_for_user(user.id, tenant_id)
    if student is not None:
        from modules.academics.backbone.models import (
            ENROLLMENT_TYPE_PRIMARY,
            StudentClassEnrollment,
        )

        placement = StudentClassEnrollment.query.filter_by(
            tenant_id=tenant_id,
            student_id=student.id,
            is_current=True,
            enrollment_type=ENROLLMENT_TYPE_PRIMARY,
        ).first()
        return _subjects_for_student(
            tenant_id,
            student.class_id,
            enrollment_id=placement.id if placement else None,
        )

    return []
