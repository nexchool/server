"""
Resolve target users for bulk notifications.

All functions take explicit tenant_id (required in Celery workers without request context).
"""

from __future__ import annotations

from typing import List, Sequence

from sqlalchemy.orm import load_only

from backend.core.database import db
from backend.modules.auth.models import User
from backend.modules.classes.models import ClassTeacher
from backend.modules.rbac.models import Role, UserRole
from backend.modules.students.models import Student
from backend.modules.teachers.models import Teacher


def get_users_by_ids(user_ids: Sequence[str], tenant_id: str) -> List[User]:
    """Return User rows for IDs belonging to the tenant (single query, no N+1)."""
    if not user_ids:
        return []
    uid_set = [u for u in dict.fromkeys(user_ids) if u]
    if not uid_set:
        return []
    q = (
        User.query.filter(
            User.tenant_id == tenant_id,
            User.id.in_(uid_set),
        )
        .options(load_only(User.id, User.email, User.name, User.tenant_id))
    )
    return q.all()


def get_users_by_role(role_name: str, tenant_id: str) -> List[User]:
    """Users assigned the given role name within the tenant."""
    role = Role.query.filter_by(name=role_name, tenant_id=tenant_id).first()
    if not role:
        return []
    ur_subq = (
        db.session.query(UserRole.user_id)
        .filter(
            UserRole.tenant_id == tenant_id,
            UserRole.role_id == role.id,
        )
        .subquery()
    )
    return (
        User.query.filter(User.tenant_id == tenant_id, User.id.in_(ur_subq))
        .options(load_only(User.id, User.email, User.name, User.tenant_id))
        .all()
    )


def get_students_by_class(class_id: str, tenant_id: str) -> List[User]:
    """Login users for students assigned to class_id in this tenant."""
    rows = (
        db.session.query(User)
        .join(Student, Student.user_id == User.id)
        .filter(
            Student.tenant_id == tenant_id,
            Student.class_id == class_id,
            User.tenant_id == tenant_id,
        )
        .options(load_only(User.id, User.email, User.name, User.tenant_id))
        .all()
    )
    return rows


def get_teachers_by_class(class_id: str, tenant_id: str) -> List[User]:
    """Login users for teachers assigned to class_id via class_teachers."""
    ct_subq = (
        db.session.query(ClassTeacher.teacher_id)
        .filter(
            ClassTeacher.tenant_id == tenant_id,
            ClassTeacher.class_id == class_id,
        )
        .subquery()
    )
    return (
        db.session.query(User)
        .join(Teacher, Teacher.user_id == User.id)
        .filter(
            Teacher.tenant_id == tenant_id,
            Teacher.id.in_(ct_subq),
            User.tenant_id == tenant_id,
        )
        .options(load_only(User.id, User.email, User.name, User.tenant_id))
        .all()
    )


def get_all_students(tenant_id: str) -> List[User]:
    """All student login users for the tenant."""
    return (
        db.session.query(User)
        .join(Student, Student.user_id == User.id)
        .filter(Student.tenant_id == tenant_id, User.tenant_id == tenant_id)
        .options(load_only(User.id, User.email, User.name, User.tenant_id))
        .all()
    )


def get_all_teachers(tenant_id: str) -> List[User]:
    """All teacher login users for the tenant."""
    return (
        db.session.query(User)
        .join(Teacher, Teacher.user_id == User.id)
        .filter(Teacher.tenant_id == tenant_id, User.tenant_id == tenant_id)
        .options(load_only(User.id, User.email, User.name, User.tenant_id))
        .all()
    )


def user_ids_from_users(users: Sequence[User]) -> List[str]:
    """Stable de-duplicated user ids."""
    return list(dict.fromkeys(u.id for u in users if u and u.id))


class TargetingValidationError(ValueError):
    """Invalid or ambiguous notification targeting payload."""


def collect_user_ids_single_mode(
    tenant_id: str,
    *,
    user_ids: Optional[Sequence[str]] = None,
    role: Optional[str] = None,
    class_id: Optional[str] = None,
    include_teachers_for_class: bool = False,
    all_students: bool = False,
    all_teachers: bool = False,
) -> List[str]:
    """
    Resolve targets for POST /notifications/send: exactly one primary mode.

    Modes:
    - user_ids: explicit list
    - role: role name
    - class_id: students in class; if include_teachers_for_class, union class teachers
    - all_students / all_teachers (mutually exclusive with others except class+teachers flag)
    """
    modes = 0
    if user_ids:
        modes += 1
    if role:
        modes += 1
    if class_id:
        modes += 1
    if all_students:
        modes += 1
    if all_teachers:
        modes += 1
    if modes != 1:
        raise TargetingValidationError(
            "Provide exactly one of: user_ids, role, class_id, all_students, all_teachers"
        )

    if user_ids:
        users = get_users_by_ids(user_ids, tenant_id)
        return user_ids_from_users(users)

    if role:
        return user_ids_from_users(get_users_by_role(role, tenant_id))

    if class_id:
        u = user_ids_from_users(get_students_by_class(class_id, tenant_id))
        if include_teachers_for_class:
            u = list(dict.fromkeys(u + user_ids_from_users(get_teachers_by_class(class_id, tenant_id))))
        return u

    if all_students:
        return user_ids_from_users(get_all_students(tenant_id))

    if all_teachers:
        return user_ids_from_users(get_all_teachers(tenant_id))

    return []


def collect_user_ids_bulk_merge(
    tenant_id: str,
    *,
    user_ids: Optional[Sequence[str]] = None,
    role: Optional[str] = None,
    class_id: Optional[str] = None,
    include_teachers_for_class: bool = False,
    all_students: bool = False,
    all_teachers: bool = False,
) -> List[str]:
    """Union all provided targeting filters (POST /notifications/send-bulk)."""
    out: List[str] = []
    if user_ids:
        out.extend(user_ids_from_users(get_users_by_ids(user_ids, tenant_id)))
    if role:
        out.extend(user_ids_from_users(get_users_by_role(role, tenant_id)))
    if class_id:
        out.extend(user_ids_from_users(get_students_by_class(class_id, tenant_id)))
        if include_teachers_for_class:
            out.extend(user_ids_from_users(get_teachers_by_class(class_id, tenant_id)))
    if all_students:
        out.extend(user_ids_from_users(get_all_students(tenant_id)))
    if all_teachers:
        out.extend(user_ids_from_users(get_all_teachers(tenant_id)))
    return list(dict.fromkeys(out))
