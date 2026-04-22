from typing import List, Dict, Optional, Any
from sqlalchemy.exc import IntegrityError
from datetime import datetime
import secrets

from core.database import db
from core.tenant import get_tenant_id
from core.models import Tenant
from modules.auth.models import User
from modules.rbac.services import assign_role_to_user_by_email
from modules.rbac.role_seeder import seed_roles_for_tenant
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


def generate_employee_id() -> str:
    """
    Generate a unique employee ID for a teacher.

    Format: TCH{YEAR}{SEQUENCE}
    Example: TCH2026001, TCH2026002
    """
    current_year = datetime.utcnow().year
    prefix = f"TCH{current_year}"

    latest = Teacher.query.filter(
        Teacher.employee_id.like(f"{prefix}%")
    ).order_by(Teacher.employee_id.desc()).first()

    if latest:
        try:
            last_seq = int(latest.employee_id[len(prefix):])
            new_seq = last_seq + 1
        except ValueError:
            new_seq = 1
    else:
        new_seq = 1

    return f"{prefix}{new_seq:03d}"


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


def create_teacher(
    name: str,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    designation: Optional[str] = None,
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
        employee_id = generate_employee_id()

        # Generate email if not provided (use employee_id based)
        actual_email = email if email else f"{employee_id.lower()}@teacher.school"
        temp_password = generate_teacher_password(name)

        tenant_id = get_tenant_id()
        if not tenant_id:
            return {'success': False, 'error': 'Tenant context is required'}

        # Plan enforcement: do not allow creating teachers beyond plan limit
        allowed, limit_msg = _check_teacher_plan_limit(tenant_id)
        if not allowed:
            return {'success': False, 'error': limit_msg}

        # Check email uniqueness (tenant-scoped)
        existing_user = User.get_user_by_email(actual_email, tenant_id=tenant_id)
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
            department=department,
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
        error_msg = str(e.orig) if hasattr(e, 'orig') else str(e)
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
        return {'success': False, 'error': f'Failed to create teacher: {str(e)}'}


def list_teachers(
    search: Optional[str] = None,
    search_field: str = "all",
    status: Optional[str] = None,
    department: Optional[str] = None,
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
    query = Teacher.query.join(User)

    if status:
        query = query.filter(
            db.func.lower(Teacher.status) == status.strip().lower()
        )

    if department:
        query = query.filter(Teacher.department.ilike(f"%{department.strip()}%"))

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
                        Teacher.department.ilike(pattern),
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
        order_cols = [_ordered(Teacher.department, nulls_last=True)]
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

    # Unique, sorted department / designation values across ALL tenant teachers
    # (not the filtered subset) so filter dropdowns are always fully populated.
    from sqlalchemy import distinct as _distinct

    all_departments = [
        r[0]
        for r in Teacher.query.with_entities(_distinct(Teacher.department))
        .filter(Teacher.department.isnot(None), Teacher.department != "")
        .order_by(Teacher.department)
        .all()
    ]
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
    department: Optional[str] = None,
    qualification: Optional[str] = None,
    specialization: Optional[str] = None,
    experience_years: Optional[int] = None,
    address: Optional[str] = None,
    date_of_joining: Optional[str] = None,
    status: Optional[str] = None,
) -> Dict:
    """Update teacher details. Only updates provided fields."""
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
        if department is not None:
            teacher.department = department
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
        return {'success': False, 'error': f'Failed to update teacher: {str(e)}'}


def delete_teacher(teacher_id: str) -> Dict:
    """Delete teacher."""
    try:
        teacher = Teacher.query.get(teacher_id)
        if not teacher:
            return {'success': False, 'error': 'Teacher not found'}

        # class_teachers has no ON DELETE CASCADE on its FK, so SQLAlchemy would
        # try to SET teacher_id = NULL (NOT NULL column) and raise a violation.
        # Explicitly remove those rows before deleting the teacher.
        from modules.classes.models import ClassTeacher
        ClassTeacher.query.filter_by(teacher_id=teacher_id).delete(synchronize_session=False)
        db.session.flush()

        teacher.delete()
        return {'success': True, 'message': 'Teacher deleted successfully'}
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': f'Failed to delete teacher: {str(e)}'}
