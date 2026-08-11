"""
Resolve target users for bulk notifications.

All functions take explicit tenant_id (required in Celery workers without request context).
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import load_only

from core.database import db
from modules.auth.models import User
from modules.rbac.models import Role
from modules.students.models import Student
from modules.teachers.models import Teacher


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
    """Everyone this Authority Profile describes, as an audience.

    Audience follows the same two sources as authorization (ADR-013): profiles
    held through employment, and profiles a business relationship implies. So
    "the teachers" means the people currently employed to teach, and stops
    meaning someone the day they leave — rather than depending on whether an
    assignment was tidied up.
    """
    from modules.rbac.authority_service import user_ids_holding_profiles

    holder_ids = user_ids_holding_profiles(tenant_id, (role_name,))
    if not holder_ids:
        return []

    return (
        User.query.filter(User.tenant_id == tenant_id, User.id.in_(holder_ids))
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
    """Login users for the teachers who currently teach this class.

    Asks Teaching Assignment rather than a table, so a notification reaches
    whoever teaches the class today — the class teacher and every subject
    teacher alike, since both have a reason to hear about it.
    """
    from modules.academics.teaching_assignment import teacher_ids_teaching_in

    teaching_here = teacher_ids_teaching_in([class_id])
    if not teaching_here:
        return []

    return (
        db.session.query(User)
        .join(Teacher, Teacher.user_id == User.id)
        .filter(
            Teacher.tenant_id == tenant_id,
            Teacher.id.in_(teaching_here),
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


def get_leave_manager_user_ids(tenant_id: str) -> List[str]:
    """
    Return user IDs of all users in the tenant who hold the
    'teacher.leave.manage' permission (i.e. admin / leave managers).
    """
    from modules.people.employment import AUTHORITY_BEARING_STATUSES, Staff
    from modules.rbac.models import Permission, RolePermission, StaffAuthority

    perm = Permission.query.filter_by(name="teacher.leave.manage").first()
    if not perm:
        return []

    role_id_select = select(RolePermission.role_id).where(
        RolePermission.permission_id == perm.id,
        RolePermission.tenant_id == tenant_id,
    )

    # Asking someone to approve leave they no longer have the authority to
    # approve is worse than not asking: suspended and departed staff are not
    # notified, on the same rule that decides whether they may act at all.
    rows = (
        db.session.query(User.id)
        .join(Staff, Staff.person_id == User.person_id)
        .join(StaffAuthority, StaffAuthority.staff_id == Staff.id)
        .filter(
            User.tenant_id == tenant_id,
            Staff.tenant_id == tenant_id,
            StaffAuthority.role_id.in_(role_id_select),
            Staff.employment_status.in_(list(AUTHORITY_BEARING_STATUSES)),
        )
        .all()
    )
    return list(dict.fromkeys(uid for (uid,) in rows if uid))


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
