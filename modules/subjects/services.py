"""
Subject Services

Business logic for subject CRUD operations. All operations are tenant-scoped.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from core.database import db
from core.tenant import get_tenant_id

from .models import Subject


def create_subject(data: Dict, tenant_id: str) -> Dict:
    """
    Create a new subject (tenant-scoped).

    Args:
        data: Dict with name (required), code (optional), description (optional)
        tenant_id: Tenant ID for scoping

    Returns:
        Dict with success status and subject data or error
    """
    try:
        if not tenant_id:
            return {"success": False, "error": "Tenant context is required"}

        name = (data.get("name") or "").strip()
        if not name:
            return {"success": False, "error": "name is required"}

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
        if subject_type not in ("core", "elective", "activity", "other"):
            subject_type = "core"

        subject = Subject(
            tenant_id=tenant_id,
            name=name,
            code=code,
            description=(data.get("description") or "").strip() or None,
            subject_type=subject_type,
            is_active=bool(data.get("is_active", True)),
        )
        subject.save()

        return {"success": True, "subject": subject.to_dict()}
    except IntegrityError as e:
        db.session.rollback()
        error_msg = str(e.orig) if hasattr(e, "orig") else str(e)
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
        return {"success": False, "error": str(e)}


def get_subjects(tenant_id: str, include_inactive: bool = False) -> List[Dict]:
    """Get subjects for a tenant (excludes soft-deleted)."""
    q = Subject.query.filter_by(tenant_id=tenant_id).filter(Subject.deleted_at.is_(None))
    if not include_inactive:
        q = q.filter(Subject.is_active.is_(True))
    subjects = q.order_by(Subject.name).all()
    return [s.to_dict() for s in subjects]


def list_subjects_filtered(tenant_id: str, include_inactive: bool = False) -> List[Dict]:
    """List subjects without Flask request; optional inactive rows."""
    q = Subject.query.filter_by(tenant_id=tenant_id).filter(Subject.deleted_at.is_(None))
    if not include_inactive:
        q = q.filter(Subject.is_active.is_(True))
    subjects = q.order_by(Subject.name).all()
    return [s.to_dict() for s in subjects]


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
            if st in ("core", "elective", "activity", "other"):
                subject.subject_type = st
        if "is_active" in data and data["is_active"] is not None:
            subject.is_active = bool(data["is_active"])

        subject.updated_at = datetime.utcnow()
        subject.save()
        return {"success": True, "subject": subject.to_dict()}
    except IntegrityError as e:
        db.session.rollback()
        error_msg = str(e.orig) if hasattr(e, "orig") else str(e)
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
        return {"success": False, "error": str(e)}


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
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Role-scoped subjects: GET /api/subjects/mine
#
# Scoping happens server-side because students/parents do not hold
# subject.read / class_subject.read permissions, so client-side filtering is
# impossible (and against the project's security rules).
# ---------------------------------------------------------------------------

ROLE_ADMIN_PERMISSION = "subject.manage"


def _teacher_display_name(teacher) -> Optional[str]:
    """Teacher has no name column; the name lives on the linked User."""
    if teacher is None:
        return None
    name = teacher.user.name if teacher.user else None
    return name or teacher.employee_id


def _class_label(klass) -> Optional[str]:
    """Class.name is nullable; section is not. Use name or section as label."""
    if klass is None:
        return None
    return klass.name or klass.section


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


def _subjects_for_student(tenant_id: str, class_id: str) -> List[Dict]:
    from modules.classes.models import ClassSubject

    if not class_id:
        return []

    class_subjects = (
        _active_class_subjects_query(tenant_id)
        .filter(ClassSubject.class_id == class_id)
        .all()
    )
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

    from modules.teachers.models import Teacher

    teacher = Teacher.query.filter_by(user_id=user.id, tenant_id=tenant_id).first()
    if teacher is not None:
        return _subjects_for_teacher(tenant_id, teacher.id)

    from modules.students.models import Student

    student = Student.query.filter_by(user_id=user.id, tenant_id=tenant_id).first()
    if student is not None:
        return _subjects_for_student(tenant_id, student.class_id)

    return []
