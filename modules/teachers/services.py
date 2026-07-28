from shared.safe_error import safe_error
from typing import List, Dict, Optional, Any, Set
from sqlalchemy.exc import IntegrityError
from datetime import datetime
import secrets

from core.database import db
from core.tenant import get_tenant_id
from core.models import Tenant
from modules.auth.models import User
from modules.rbac.services import (
    assign_role_to_user_by_email,
    remove_login_for_deleted_profile,
)
from modules.rbac.role_seeder import seed_roles_for_tenant
from modules.departments.models import Department
from .models import Teacher

# Columns the client may sort by.
SORTABLE_COLUMNS = {"employee_id", "name", "designation", "department", "date_of_joining"}

# Fields the client may pick in the "search within" dropdown.
SEARCH_FIELDS = {"all", "name", "employee_id", "email", "phone"}


def _parse_date(value: Optional[str]) -> Optional[Any]:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _check_teacher_plan_limit(tenant_id: str) -> tuple:
    """
    Enforce plan max_teachers. Returns (True, None) if allowed, (False, message) if limit exceeded.
    If tenant has no plan, allow (no limit).
    """
    tenant = Tenant.query.get(tenant_id)
    if not tenant or not tenant.plan_id:
        return True, None
    plan = tenant.plan
    if not plan:
        return True, None
    current = Teacher.query.filter_by(tenant_id=tenant_id).count()
    if current >= plan.max_teachers:
        return False, f"Teacher limit reached for your plan (max {plan.max_teachers}). Contact support to upgrade."
    return True, None


def generate_employee_id(
    tenant_id: Optional[str] = None, *, reserved: Optional[Set[str]] = None
) -> str:
    """
    Allocate the next unique employee id for a teacher (tenant pattern or TCH{YEAR}{SEQ:3}).
    """
    from shared.id_pattern import (
        MAX_TEACHER_ID_LEN,
        allocate_next_id,
        get_teacher_employee_pattern,
    )

    tid = tenant_id or get_tenant_id()
    if not tid:
        raise ValueError("Tenant context is required to generate a teacher id")
    pattern = get_teacher_employee_pattern(tid)
    return allocate_next_id(
        tenant_id=tid,
        model=Teacher,
        col_name="employee_id",
        pattern=pattern,
        reserved=reserved,
        max_len=MAX_TEACHER_ID_LEN,
    )


def generate_teacher_password(name: str) -> str:
    """
    Generate a temporary password for a teacher.

    Format: First 3 letters of name (uppercase) + random 4 digits
    Example: Name "John" -> "JOH4821"
    """
    name_part = ''.join(filter(str.isalpha, name))[:3].upper()
    if len(name_part) < 3:
        name_part = name_part.ljust(3, 'X')

    import random
    digits = ''.join([str(random.randint(0, 9)) for _ in range(4)])
    return f"{name_part}{digits}"


# Sentinel distinguishing "the update payload didn't mention department_id at
# all" from "department_id was explicitly sent as null" — both collapse to
# Python None through `data.get('department_id')`, but they mean different
# things: the former leaves the teacher's department untouched, the latter
# clears it. Used only by update_teacher; create_teacher has no existing
# value to leave alone, so a plain None default is unambiguous there.
NOT_PROVIDED = object()


def _resolve_department(
    department_id: Optional[str], department_name: Optional[str], tenant_id: str
) -> tuple:
    """Resolve the department_id to assign to a teacher.

    `department_id` wins when supplied — but it must belong to this tenant;
    the FK itself doesn't enforce that, so an unscoped id would otherwise
    attach an invisible cross-tenant reference. The legacy free-text
    `department_name` resolves case-insensitively against the tenant's
    catalogue; an unrecognised name is rejected rather than silently dropped
    or auto-created (see resolve_department_name). A blank/whitespace-only
    name is treated the same as "no name given" (returns no department, no
    error) rather than as an unrecognised name — pre-migration, an empty
    free-text `department` cleared the field, and a client that clears the
    field but still sends `department: ""` should get that same behaviour,
    not a confusing "Unknown department ''" error.

    Returns (department_id_or_None, error_message_or_None).
    """
    if department_id is not None:
        exists = Department.query.filter_by(
            id=department_id, tenant_id=tenant_id, deleted_at=None
        ).first()
        if not exists:
            return None, "Department not found"
        return department_id, None

    cleaned_name = department_name.strip() if isinstance(department_name, str) else department_name
    if cleaned_name:
        from modules.departments.services import resolve_department_name

        resolved = resolve_department_name(cleaned_name, tenant_id)
        if resolved is None:
            return None, (
                f"Unknown department '{department_name}'. Create it under "
                "Academics → Departments first."
            )
        return resolved, None

    return None, None


def create_teacher(
    name: str,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    designation: Optional[str] = None,
    department_id: Optional[str] = None,
    department: Optional[str] = None,
    qualification: Optional[str] = None,
    specialization: Optional[str] = None,
    experience_years: Optional[int] = None,
    address: Optional[str] = None,
    date_of_joining: Optional[str] = None,
) -> Dict:
    """
    Create a new teacher with a linked user account.

    Workflow:
    1. Auto-generate employee ID
    2. Create User account with auto-generated credentials
    3. Assign Teacher role
    4. Create Teacher profile

    Returns:
        Dict with success, teacher data, and login credentials
    """
    try:
        tenant_id = get_tenant_id()
        if not tenant_id:
            return {'success': False, 'error': 'Tenant context is required'}

        resolved_department_id, department_error = _resolve_department(
            department_id, department, tenant_id
        )
        if department_error:
            return {'success': False, 'error': department_error}

        try:
            employee_id = generate_employee_id(tenant_id)
        except (RuntimeError, ValueError) as e:
            return {"success": False, "error": str(e)}

        # Generate email if not provided (use employee_id based)
        actual_email = email if email else f"{employee_id.lower()}@teacher.school"
        temp_password = generate_teacher_password(name)

        # Plan enforcement: do not allow creating teachers beyond plan limit
        allowed, limit_msg = _check_teacher_plan_limit(tenant_id)
        if not allowed:
            return {'success': False, 'error': limit_msg}

        # Check email uniqueness (tenant-scoped). Include soft-deleted rows: the
        # (email, tenant_id) unique constraint is not scoped to deleted_at, so a
        # soft-deleted email must be caught here to avoid an IntegrityError on insert.
        existing_user = User.get_user_by_email(actual_email, tenant_id=tenant_id, include_deleted=True)
        if existing_user:
            if Teacher.query.filter_by(user_id=existing_user.id).first():
                return {'success': False, 'error': 'Email already linked to another teacher'}
            user = existing_user
        else:
            user = User()
            user.tenant_id = tenant_id
            user.email = actual_email
            user.name = name
            user.set_password(temp_password)
            user.email_verified = True
            user.force_password_reset = True
            user.save()

        # Ensure Teacher role exists and has all its permissions for this tenant.
        # This is a no-op if everything is already correct (idempotent).
        seed_roles_for_tenant(tenant_id)

        # Assign Teacher role (for both new and existing users)
        role_result = assign_role_to_user_by_email(actual_email, 'Teacher', tenant_id=tenant_id)
        if not role_result['success']:
            db.session.rollback()
            return {'success': False, 'error': f"Could not assign Teacher role: {role_result.get('error')}"}

        teacher = Teacher(
            tenant_id=tenant_id,
            user_id=user.id,
            employee_id=employee_id,
            designation=designation,
            department_id=resolved_department_id,
            qualification=qualification,
            specialization=specialization,
            experience_years=experience_years,
            phone=phone,
            address=address,
            date_of_joining=datetime.strptime(date_of_joining, '%Y-%m-%d').date() if date_of_joining else None,
            status='active',
        )
        teacher.save()

        result = {
            'success': True,
            'teacher': teacher.to_dict(),
        }

        if email and not existing_user:
            result['credentials'] = {
                'email': actual_email,
                'employee_id': employee_id,
                'password': temp_password,
                'must_reset': True,
            }

        return result

    except IntegrityError as e:
        db.session.rollback()
        error_msg = str(getattr(e, "orig", None) or e)
        if 'employee_id' in error_msg:
            return {'success': False, 'error': 'Employee ID already exists'}
        if 'email' in error_msg:
            return {'success': False, 'error': 'Email already exists'}
        return {'success': False, 'error': 'Database constraint violation'}
    except ValueError as e:
        db.session.rollback()
        return {'success': False, 'error': f'Invalid data format: {str(e)}'}
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': safe_error(e, "Failed to create teacher")}


def list_teachers(
    search: Optional[str] = None,
    search_field: str = "all",
    status: Optional[str] = None,
    department_id: Optional[str] = None,
    designation: Optional[str] = None,
    date_of_joining_from: Optional[str] = None,
    date_of_joining_to: Optional[str] = None,
    sort_by: str = "employee_id",
    sort_dir: str = "asc",
    page: Optional[int] = None,
    per_page: Optional[int] = None,
) -> Dict[str, Any]:
    """
    List teachers with filtering, searching, sorting and pagination.

    Returns an envelope: {items, total, page, per_page, total_pages}.
    When `page` and `per_page` are not provided all matching rows are returned
    (total_pages = 1) so callers that don't paginate still work.
    """
    # Outer join: department_id replaced the free-text department column
    # (migration 077). Outer so teachers with no department are still
    # returned when the department filter/search below isn't in play.
    query = Teacher.query.join(User).outerjoin(
        Department, Teacher.department_id == Department.id
    )

    if status:
        query = query.filter(
            db.func.lower(Teacher.status) == status.strip().lower()
        )

    if department_id:
        query = query.filter(Teacher.department_id == department_id)

    if designation:
        query = query.filter(Teacher.designation.ilike(f"%{designation.strip()}%"))

    date_from = _parse_date(date_of_joining_from)
    if date_from:
        query = query.filter(Teacher.date_of_joining >= date_from)
    date_to = _parse_date(date_of_joining_to)
    if date_to:
        query = query.filter(Teacher.date_of_joining <= date_to)

    if search:
        term = search.strip()
        if term:
            pattern = f"%{term}%"
            field = search_field if search_field in SEARCH_FIELDS else "all"
            if field == "name":
                query = query.filter(User.name.ilike(pattern))
            elif field == "employee_id":
                query = query.filter(Teacher.employee_id.ilike(pattern))
            elif field == "email":
                query = query.filter(User.email.ilike(pattern))
            elif field == "phone":
                query = query.filter(Teacher.phone.ilike(pattern))
            else:
                query = query.filter(
                    db.or_(
                        User.name.ilike(pattern),
                        User.email.ilike(pattern),
                        Teacher.employee_id.ilike(pattern),
                        Department.name.ilike(pattern),
                        Teacher.phone.ilike(pattern),
                    )
                )

    sort_key = sort_by if sort_by in SORTABLE_COLUMNS else "employee_id"
    is_desc = str(sort_dir).lower() == "desc"

    def _ordered(col, nulls_last: bool = False):
        expr = col.desc() if is_desc else col.asc()
        return expr.nulls_last() if nulls_last else expr

    if sort_key == "name":
        order_cols = [_ordered(User.name)]
    elif sort_key == "designation":
        order_cols = [_ordered(Teacher.designation, nulls_last=True)]
    elif sort_key == "department":
        order_cols = [_ordered(Department.name, nulls_last=True)]
    elif sort_key == "date_of_joining":
        order_cols = [_ordered(Teacher.date_of_joining, nulls_last=True)]
    else:  # employee_id (default)
        order_cols = [_ordered(Teacher.employee_id)]

    if sort_key != "employee_id":
        order_cols.append(Teacher.employee_id.asc())

    query = query.order_by(*order_cols)

    total = query.count()
    if page is not None and per_page is not None and per_page > 0:
        page = max(1, int(page))
        per_page = max(1, min(int(per_page), 100))
        teachers = query.limit(per_page).offset((page - 1) * per_page).all()
        total_pages = max(1, (total + per_page - 1) // per_page)
    else:
        teachers = query.all()
        page = 1
        per_page = len(teachers) or 0
        total_pages = 1

    # Departments facet: the full active catalogue for this tenant, not just
    # names in use — so a brand-new department appears in the filter dropdown
    # before anyone is assigned to it. Designations have no such catalogue, so
    # that facet stays derived from distinct values across ALL tenant teachers
    # (not the filtered subset) so its dropdown is always fully populated.
    from sqlalchemy import distinct as _distinct

    from modules.departments.services import list_active_departments

    all_departments = list_active_departments(get_tenant_id())
    all_designations = [
        r[0]
        for r in Teacher.query.with_entities(_distinct(Teacher.designation))
        .filter(Teacher.designation.isnot(None), Teacher.designation != "")
        .order_by(Teacher.designation)
        .all()
    ]

    return {
        "items": [t.to_dict(include_profile_picture=False) for t in teachers],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "departments": all_departments,
        "designations": all_designations,
    }


def get_teacher_by_id(teacher_id: str) -> Optional[Dict]:
    """Get teacher details by ID, including subject expertise."""
    teacher = Teacher.query.get(teacher_id)
    return teacher.to_dict(include_subjects=True) if teacher else None


def get_teacher_by_user_id(user_id: str) -> Optional[Dict]:
    """Get teacher details by User ID."""
    teacher = Teacher.query.filter_by(user_id=user_id).first()
    return teacher.to_dict() if teacher else None


def update_teacher(
    teacher_id: str,
    name: Optional[str] = None,
    phone: Optional[str] = None,
    designation: Optional[str] = None,
    department_id: Optional[str] = NOT_PROVIDED,
    department: Optional[str] = None,
    qualification: Optional[str] = None,
    specialization: Optional[str] = None,
    experience_years: Optional[int] = None,
    address: Optional[str] = None,
    date_of_joining: Optional[str] = None,
    status: Optional[str] = None,
) -> Dict:
    """Update teacher details. Only updates provided fields.

    `department_id` defaults to the `NOT_PROVIDED` sentinel rather than
    `None` so the three states the department picker needs are all
    distinguishable: key omitted (leave the teacher's department alone),
    key explicitly null (unassign it), key set to a real id (reassign it,
    once verified to belong to this tenant). `department` (the legacy
    free-text path) only has two states that matter — blank clears, a name
    resolves — because a caller that cares about "unchanged" already has
    `department_id` for that; `department_id` wins whenever it was part of
    the request at all, even as null.
    """
    try:
        teacher = Teacher.query.get(teacher_id)
        if not teacher:
            return {'success': False, 'error': 'Teacher not found'}

        if name is not None:
            teacher.user.name = name
            teacher.user.save()
        if phone is not None:
            teacher.phone = phone
        if designation is not None:
            teacher.designation = designation
        if department_id is not NOT_PROVIDED:
            resolved_department_id, department_error = _resolve_department(
                department_id, None, teacher.tenant_id
            )
            if department_error:
                return {'success': False, 'error': department_error}
            teacher.department_id = resolved_department_id
        elif department is not None:
            resolved_department_id, department_error = _resolve_department(
                None, department, teacher.tenant_id
            )
            if department_error:
                return {'success': False, 'error': department_error}
            teacher.department_id = resolved_department_id
        if qualification is not None:
            teacher.qualification = qualification
        if specialization is not None:
            teacher.specialization = specialization
        if experience_years is not None:
            teacher.experience_years = experience_years
        if address is not None:
            teacher.address = address
        if date_of_joining is not None:
            teacher.date_of_joining = datetime.strptime(date_of_joining, '%Y-%m-%d').date()
        if status is not None:
            teacher.status = status

        teacher.save()
        return {'success': True, 'teacher': teacher.to_dict()}
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': safe_error(e, "Failed to update teacher")}


# Matches students' bulk cap: one request should not queue unbounded work, and
# the UI pages at 100.
MAX_BULK_TEACHERS = 500


def bulk_update_teacher_status(teacher_ids: List[str], status: str) -> Dict:
    """Set `status` for many teachers in one tenant-scoped transaction.

    Returns {success, updated, missing}.
    """
    from .teacher_schemas import TEACHER_STATUS_VALUES

    tenant_id = get_tenant_id()
    if not tenant_id:
        return {"success": False, "error": "Tenant context required"}

    ids = [s for s in {str(i).strip() for i in (teacher_ids or [])} if s]
    if not ids:
        return {"success": False, "error": "No teachers selected"}
    if status not in TEACHER_STATUS_VALUES:
        return {
            "success": False,
            "error": f"Invalid status. Allowed: {', '.join(TEACHER_STATUS_VALUES)}",
        }

    try:
        teachers = Teacher.query.filter(
            Teacher.tenant_id == tenant_id, Teacher.id.in_(ids)
        ).all()
        found_ids = {t.id for t in teachers}
        for teacher in teachers:
            teacher.status = status
        db.session.commit()
        return {
            "success": True,
            "updated": len(teachers),
            "missing": [i for i in ids if i not in found_ids],
        }
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": safe_error(e, "Failed to update teachers")}


def bulk_delete_teachers(teacher_ids: List[str]) -> Dict:
    """Delete many teachers in one tenant-scoped transaction.

    Same teardown as `delete_teacher`, set-based: detach class-teacher rows and
    the legacy homeroom pointer first (neither FK cascades, so SQLAlchemy would
    otherwise null a NOT NULL column), then the teacher rows, then soft-
    deactivate the backing logins.

    Returns {success, deleted, missing}.
    """
    tenant_id = get_tenant_id()
    if not tenant_id:
        return {"success": False, "error": "Tenant context required"}

    ids = [s for s in {str(i).strip() for i in (teacher_ids or [])} if s]
    if not ids:
        return {"success": False, "error": "No teachers selected"}
    if len(ids) > MAX_BULK_TEACHERS:
        return {
            "success": False,
            "error": (
                f"Cannot delete more than {MAX_BULK_TEACHERS} teachers in one request "
                f"({len(ids)} requested)"
            ),
        }

    try:
        teachers = Teacher.query.filter(
            Teacher.tenant_id == tenant_id, Teacher.id.in_(ids)
        ).all()
        if not teachers:
            return {"success": True, "deleted": 0, "missing": ids}

        found_ids = [t.id for t in teachers]
        user_ids = [t.user_id for t in teachers if t.user_id]

        from modules.classes.models import ClassTeacher, Class

        ClassTeacher.query.filter(ClassTeacher.teacher_id.in_(found_ids)).delete(
            synchronize_session=False
        )
        if user_ids:
            Class.query.filter(
                Class.tenant_id == tenant_id, Class.teacher_id.in_(user_ids)
            ).update({Class.teacher_id: None}, synchronize_session=False)

        for teacher in teachers:
            db.session.delete(teacher)
        db.session.flush()  # clear teachers.user_id before touching the users

        for user_id in user_ids:
            # hard=False: a teacher's user is referenced by NOT NULL / NO ACTION
            # FKs (attendance.marked_by, classes.teacher_id) — see delete_teacher.
            remove_login_for_deleted_profile(user_id, tenant_id, "Teacher", hard=False)

        db.session.commit()
        return {
            "success": True,
            "deleted": len(found_ids),
            "missing": [i for i in ids if i not in set(found_ids)],
        }
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": safe_error(e, "Failed to delete teachers")}


def delete_teacher(teacher_id: str) -> Dict:
    """Delete teacher and deactivate its backing user.

    Mirrors delete_student so no orphaned, login-capable user is left behind. The
    user is SOFT-deactivated (deleted_at) rather than hard-deleted: a teacher's
    user is referenced by NOT NULL / NO ACTION FKs (attendance.marked_by,
    classes.teacher_id), so soft delete preserves that history while blocking
    login. A user who also holds another role keeps their login (only the Teacher
    role is detached).
    """
    try:
        teacher = Teacher.query.get(teacher_id)
        if not teacher:
            return {'success': False, 'error': 'Teacher not found'}

        tenant_id = teacher.tenant_id
        user_id = teacher.user_id

        # class_teachers has no ON DELETE CASCADE on its FK, so SQLAlchemy would
        # try to SET teacher_id = NULL (NOT NULL column) and raise a violation.
        # Explicitly remove those rows before deleting the teacher.
        from modules.classes.models import ClassTeacher, Class
        ClassTeacher.query.filter_by(teacher_id=teacher_id).delete(synchronize_session=False)
        # Clear the legacy homeroom pointer (classes.teacher_id -> users.id) so no
        # class still lists this departed teacher as its class teacher.
        Class.query.filter_by(tenant_id=tenant_id, teacher_id=user_id).update(
            {Class.teacher_id: None}, synchronize_session=False
        )

        db.session.delete(teacher)
        db.session.flush()  # clear teachers.user_id before touching the user

        # Soft-deactivate the backing login (hard=False) — see docstring.
        remove_login_for_deleted_profile(user_id, tenant_id, "Teacher", hard=False)

        db.session.commit()
        return {'success': True, 'message': 'Teacher deleted successfully'}
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': safe_error(e, "Failed to delete teacher")}
