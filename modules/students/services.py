from typing import List, Dict, Optional, Any
from sqlalchemy.exc import IntegrityError
from datetime import datetime
import logging
import secrets
import string
import uuid
from decimal import Decimal

from core.database import db
from core.tenant import get_tenant_id
from core.models import Tenant
from modules.auth.models import User
from modules.rbac.services import assign_role_to_user_by_email
from modules.rbac.role_seeder import seed_roles_for_tenant
from modules.classes.models import Class
from shared.s3_utils import delete_file, fetch_s3_object_bytes, upload_file
from shared.storage_constants import DOCUMENTS, STUDENTS, TENANTS
from .models import Student, StudentDocument, DocumentType
from .document_schemas import validate_document_type

logger = logging.getLogger(__name__)

def _clean_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip()
        return v if v != "" else None
    return str(value).strip() or None


def _clean_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except Exception:
        return None


def _clean_decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _clean_bool(value: Any) -> Optional[bool]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(int(value))
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "1", "yes", "on"):
            return True
        if v in ("false", "0", "no", "off"):
            return False
    return None


def _resolve_student_academic_year_id(
    academic_year_id: Optional[str] = None,
    class_id: Optional[str] = None,
) -> Optional[str]:
    """Resolve academic_year_id for student. Priority: explicit id, class relationship."""
    if academic_year_id:
        return academic_year_id
    if class_id:
        cls = Class.query.get(class_id)
        if cls and cls.academic_year_id:
            return cls.academic_year_id
    return None


def _check_student_plan_limit(tenant_id: str) -> tuple:
    """
    Enforce plan max_students. Returns (True, None) if allowed, (False, message) if limit exceeded.
    If tenant has no plan, allow (no limit).
    """
    tenant = Tenant.query.get(tenant_id)
    if not tenant or not tenant.plan_id:
        return True, None
    plan = tenant.plan
    if not plan:
        return True, None
    current = Student.query.filter_by(tenant_id=tenant_id).count()
    if current >= plan.max_students:
        return False, f"Student limit reached for your plan (max {plan.max_students}). Contact support to upgrade."
    return True, None


def generate_admission_number() -> str:
    """
    Generate a unique admission number.
    
    Format: ADM{YEAR}{SEQUENCE}
    Example: ADM2026001, ADM2026002, etc.
    
    Returns:
        Generated admission number string
    """
    current_year = datetime.utcnow().year
    
    # Find the latest admission number for this year
    prefix = f"ADM{current_year}"
    latest_student = Student.query.filter(
        Student.admission_number.like(f"{prefix}%")
    ).order_by(Student.admission_number.desc()).first()
    
    if latest_student:
        # Extract sequence number and increment
        try:
            last_sequence = int(latest_student.admission_number[len(prefix):])
            new_sequence = last_sequence + 1
        except ValueError:
            new_sequence = 1
    else:
        new_sequence = 1
    
    # Format with leading zeros (3 digits)
    return f"{prefix}{new_sequence:03d}"


def generate_student_password(name: str, date_of_birth: Optional[str]) -> str:
    """
    Generate student password based on name and birth year.
    
    Format: First 3 letters of name (uppercase) + birth year
    Example: Name "Sahil", DOB "2003-05-15" -> "SAH2003"
    
    If date_of_birth is not provided, uses current year.
    
    Args:
        name: Student's full name
        date_of_birth: Date of birth in YYYY-MM-DD format (optional)
        
    Returns:
        Generated password string
    """
    # Get first 3 letters of name, uppercase
    name_part = ''.join(filter(str.isalpha, name))[:3].upper()
    
    # Pad with 'X' if name is less than 3 letters
    if len(name_part) < 3:
        name_part = name_part.ljust(3, 'X')
    
    # Get birth year or use current year
    if date_of_birth:
        try:
            birth_year = datetime.strptime(date_of_birth, '%Y-%m-%d').year
        except ValueError:
            birth_year = datetime.utcnow().year
    else:
        birth_year = datetime.utcnow().year
    
    return f"{name_part}{birth_year}"


def create_student(
    name: str,
    academic_year_id: Optional[str] = None,
    guardian_name: str = None,
    guardian_relationship: str = None,
    guardian_phone: str = None,
    admission_number: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    gender: Optional[str] = None,
    class_id: Optional[str] = None,
    roll_number: Optional[int] = None,
    address: Optional[str] = None,
    guardian_email: Optional[str] = None,
    # Extended fields (all optional)
    blood_group: Optional[str] = None,
    height_cm: Optional[int] = None,
    weight_kg: Optional[str] = None,
    medical_allergies: Optional[str] = None,
    medical_conditions: Optional[str] = None,
    disability_details: Optional[str] = None,
    identification_marks: Optional[str] = None,

    father_name: Optional[str] = None,
    father_phone: Optional[str] = None,
    father_email: Optional[str] = None,
    father_occupation: Optional[str] = None,
    father_annual_income: Optional[int] = None,

    mother_name: Optional[str] = None,
    mother_phone: Optional[str] = None,
    mother_email: Optional[str] = None,
    mother_occupation: Optional[str] = None,
    mother_annual_income: Optional[int] = None,

    guardian_address: Optional[str] = None,
    guardian_occupation: Optional[str] = None,
    guardian_aadhar_number: Optional[str] = None,

    aadhar_number: Optional[str] = None,
    apaar_id: Optional[str] = None,
    emis_number: Optional[str] = None,
    udise_student_id: Optional[str] = None,
    religion: Optional[str] = None,
    category: Optional[str] = None,
    caste: Optional[str] = None,
    nationality: Optional[str] = None,
    mother_tongue: Optional[str] = None,
    place_of_birth: Optional[str] = None,

    current_address: Optional[str] = None,
    current_city: Optional[str] = None,
    current_state: Optional[str] = None,
    current_pincode: Optional[str] = None,

    permanent_address: Optional[str] = None,
    permanent_city: Optional[str] = None,
    permanent_state: Optional[str] = None,
    permanent_pincode: Optional[str] = None,

    is_same_as_permanent_address: Optional[bool] = None,
    is_commuting_from_outstation: Optional[bool] = None,
    commute_location: Optional[str] = None,
    commute_notes: Optional[str] = None,

    emergency_contact_name: Optional[str] = None,
    emergency_contact_relationship: Optional[str] = None,
    emergency_contact_phone: Optional[str] = None,
    emergency_contact_alt_phone: Optional[str] = None,

    admission_date: Optional[str] = None,
    previous_school_name: Optional[str] = None,
    previous_school_class: Optional[str] = None,
    last_school_board: Optional[str] = None,
    tc_number: Optional[str] = None,
    house_name: Optional[str] = None,
    student_status: Optional[str] = None,
) -> Dict:
    """
    Create a new student with optional login credentials.
    
    Workflow:
    1. Auto-generate admission number if not provided
    2. Validate admission number uniqueness
    3. If email provided: create User with auto-generated credentials
    4. Create Student profile
    5. Assign Student role if User created
    
    Args:
        name: Student's full name (required)
        academic_year: Academic year string (e.g., "2025-2026") - required if academic_year_id not provided
        guardian_name: Guardian's full name (required)
        guardian_relationship: Relationship to student (required)
        guardian_phone: Guardian's phone number (required)
        admission_number: Unique admission number (optional - auto-generated if not provided)
        email: Student's email (optional - creates login credentials if provided)
        phone: Student's phone number (optional)
        date_of_birth: Date of birth in YYYY-MM-DD format (optional)
        gender: Gender (optional)
        class_id: Class ID (optional)
        roll_number: Roll number (optional)
        address: Physical address (optional)
        guardian_email: Guardian's email (optional)
        
    Returns:
        Dict with success status, student data, and credentials if created
        
    Example:
        {
            'success': True,
            'student': {...},
            'credentials': {
                'username': 'ADM2025001',
                'password': 'SAH2003',
                'must_reset': True
            }
        }
    """
    try:
        # Auto-generate admission number if not provided
        if not admission_number:
            admission_number = generate_admission_number()
        
        tenant_id = get_tenant_id()
        if not tenant_id:
            return {'success': False, 'error': 'Tenant context is required'}

        # Plan enforcement: do not allow creating students beyond plan limit
        allowed, limit_msg = _check_student_plan_limit(tenant_id)
        if not allowed:
            return {'success': False, 'error': limit_msg}

        # Validate admission number uniqueness (tenant-scoped; query auto-filtered)
        if Student.query.filter_by(admission_number=admission_number).first():
            return {'success': False, 'error': 'Admission number already exists'}

        # Validate class exists if provided (tenant-scoped)
        if class_id:
            class_obj = Class.query.get(class_id)
            if not class_obj:
                return {'success': False, 'error': 'Class not found'}

        # Resolve academic_year_id (class derives it, or explicit academic_year_id)
        ay_id = _resolve_student_academic_year_id(academic_year_id, class_id)
        if not ay_id:
            return {'success': False, 'error': 'academic_year_id or class_id is required'}
        if not guardian_name or not guardian_relationship or not guardian_phone:
            return {'success': False, 'error': 'guardian_name, guardian_relationship, guardian_phone are required'}

        user = None
        temp_password = None

        # Create User with login credentials if email provided
        if email:
            # Check if email already exists in this tenant
            existing_user = User.get_user_by_email(email, tenant_id=tenant_id)
            if existing_user:
                # Check if already linked to a student in this tenant
                if Student.query.filter_by(user_id=existing_user.id).first():
                    return {'success': False, 'error': 'Email already linked to another student'}
                # Link to existing user
                user = existing_user
            else:
                # Create new user with credentials
                # Password = First 3 letters of name + birth year
                temp_password = generate_student_password(name, date_of_birth)
                user = User()
                user.tenant_id = tenant_id
                user.email = email
                user.name = name
                user.set_password(temp_password)
                user.email_verified = True  # Auto-verify for admin-created students
                user.force_password_reset = True  # Force password change on first login
                user.save()

            # Ensure Student role exists and has all its permissions for this tenant.
            # This is a no-op if everything is already correct (idempotent).
            seed_roles_for_tenant(tenant_id)

            # Assign Student role (for both new and existing users)
            role_result = assign_role_to_user_by_email(email, 'Student', tenant_id=tenant_id)
            if not role_result['success']:
                db.session.rollback()
                return {'success': False, 'error': f"Could not assign Student role: {role_result.get('error')}"}
        
        # Student without email/login credentials - create minimal user placeholder
        if not user:
            # Use admission number as email identifier
            user = User()
            user.tenant_id = tenant_id
            user.email = f"{admission_number.lower()}@student.placeholder"
            user.name = name
            user.set_password(secrets.token_urlsafe(32))  # Random unusable password
            user.email_verified = False
            user.force_password_reset = False
            user.save()

        # Create Student Profile (tenant-scoped)
        student = Student(
            tenant_id=tenant_id,
            user_id=user.id,
            admission_number=admission_number,
            academic_year_id=ay_id,
            roll_number=roll_number,
            class_id=class_id,
            date_of_birth=datetime.strptime(date_of_birth, '%Y-%m-%d').date() if date_of_birth else None,
            gender=gender,
            phone=phone,
            address=address,
            guardian_name=guardian_name,
            guardian_relationship=guardian_relationship,
            guardian_phone=guardian_phone,
            guardian_email=guardian_email,
            # Extended profile fields
            blood_group=_clean_str(blood_group),
            height_cm=_clean_int(height_cm),
            weight_kg=_clean_decimal(weight_kg),
            medical_allergies=_clean_str(medical_allergies),
            medical_conditions=_clean_str(medical_conditions),
            disability_details=_clean_str(disability_details),
            identification_marks=_clean_str(identification_marks),

            father_name=_clean_str(father_name),
            father_phone=_clean_str(father_phone),
            father_email=_clean_str(father_email),
            father_occupation=_clean_str(father_occupation),
            father_annual_income=_clean_int(father_annual_income),

            mother_name=_clean_str(mother_name),
            mother_phone=_clean_str(mother_phone),
            mother_email=_clean_str(mother_email),
            mother_occupation=_clean_str(mother_occupation),
            mother_annual_income=_clean_int(mother_annual_income),

            guardian_address=_clean_str(guardian_address),
            guardian_occupation=_clean_str(guardian_occupation),
            guardian_aadhar_number=_clean_str(guardian_aadhar_number),

            aadhar_number=_clean_str(aadhar_number),
            apaar_id=_clean_str(apaar_id),
            emis_number=_clean_str(emis_number),
            udise_student_id=_clean_str(udise_student_id),
            religion=_clean_str(religion),
            category=_clean_str(category),
            caste=_clean_str(caste),
            nationality=_clean_str(nationality),
            mother_tongue=_clean_str(mother_tongue),
            place_of_birth=_clean_str(place_of_birth),

            current_address=_clean_str(current_address),
            current_city=_clean_str(current_city),
            current_state=_clean_str(current_state),
            current_pincode=_clean_str(current_pincode),

            permanent_address=_clean_str(permanent_address),
            permanent_city=_clean_str(permanent_city),
            permanent_state=_clean_str(permanent_state),
            permanent_pincode=_clean_str(permanent_pincode),

            is_same_as_permanent_address=_clean_bool(is_same_as_permanent_address),
            is_commuting_from_outstation=_clean_bool(is_commuting_from_outstation),
            commute_location=_clean_str(commute_location),
            commute_notes=_clean_str(commute_notes),

            emergency_contact_name=_clean_str(emergency_contact_name),
            emergency_contact_relationship=_clean_str(emergency_contact_relationship),
            emergency_contact_phone=_clean_str(emergency_contact_phone),
            emergency_contact_alt_phone=_clean_str(emergency_contact_alt_phone),

            admission_date=datetime.strptime(admission_date, "%Y-%m-%d").date()
            if admission_date
            else None,
            previous_school_name=_clean_str(previous_school_name),
            previous_school_class=_clean_str(previous_school_class),
            last_school_board=_clean_str(last_school_board),
            tc_number=_clean_str(tc_number),
            house_name=_clean_str(house_name),
            student_status=_clean_str(student_status),
        )
        student.save()

        # Auto-assign any applicable fee structures for this student's class/year
        try:
            from modules.finance.services import student_fee_service

            student_fee_service.auto_assign_fees_for_student(student.id)
        except Exception:
            # Do not fail student creation if finance auto-assignment has issues
            db.session.rollback()

        result = {
            'success': True,
            'student': student.to_dict()
        }
        
        # Include credentials in response if generated
        if email and temp_password:
            result['credentials'] = {
                'username': admission_number,  # Username is admission number
                'password': temp_password,
                'must_reset': True
            }
        
        return result

    except IntegrityError as e:
        db.session.rollback()
        error_msg = str(e.orig) if hasattr(e, 'orig') else str(e)
        if 'admission_number' in error_msg:
            return {'success': False, 'error': 'Admission number already exists'}
        elif 'email' in error_msg:
            return {'success': False, 'error': 'Email already exists'}
        return {'success': False, 'error': 'Database constraint violation'}
    except ValueError as e:
        db.session.rollback()
        return {'success': False, 'error': f'Invalid data format: {str(e)}'}
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': f'Failed to create student: {str(e)}'}

# Columns the client may sort by. The actual ordering expression is built in
# `_build_sort_order` below so `class` can use natural (grade_level) order
# rather than a lexicographic sort on the class name.
SORTABLE_COLUMNS = {"admission_number", "name", "class", "roll_number"}

# Fields the client may pick in the "search within" dropdown.
SEARCH_FIELDS = {"all", "name", "admission_number", "email", "guardian_phone"}


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _attach_transport_summary(rows: List[Dict], academic_year_id: Optional[str]) -> None:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return
    from core.plan_features import is_plan_feature_enabled
    if not is_plan_feature_enabled(tenant_id, "transport"):
        return
    from modules.transport.services import transport_summaries_for_students

    summ = transport_summaries_for_students(rows, academic_year_id=academic_year_id)
    for r in rows:
        extra = summ.get(r.get("id"))
        if extra:
            r.update(extra)


def list_students(
    class_id: str = None,
    class_ids: List[str] = None,
    academic_year_id: str = None,
    search: str = None,
    search_field: str = "all",
    gender: str = None,
    student_status: str = None,
    is_transport_opted: Optional[bool] = None,
    admission_date_from: str = None,
    admission_date_to: str = None,
    sort_by: str = "admission_number",
    sort_dir: str = "asc",
    page: Optional[int] = None,
    per_page: Optional[int] = None,
    include_transport_summary: bool = False,
    _restrict_class_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    List students with filtering, searching, sorting and pagination.

    Returns an envelope: {items, total, page, per_page, total_pages}.
    When `page` and `per_page` are not provided all matching rows are returned
    (total_pages = 1) so callers that don't paginate still work.

    `_restrict_class_ids` is an internal hard-scope used by the teacher code path
    to limit results to classes the teacher owns; it's AND-ed with any client
    class filters.
    """
    query = Student.query.join(User)

    # Teacher scope: hard ceiling on which classes are visible at all.
    if _restrict_class_ids is not None:
        if not _restrict_class_ids:
            return {"items": [], "total": 0, "page": 1, "per_page": 0, "total_pages": 1}
        query = query.filter(Student.class_id.in_(_restrict_class_ids))

    # Client-supplied class scoping (AND-ed with the teacher ceiling above).
    if class_ids:
        query = query.filter(Student.class_id.in_(class_ids))
    elif class_id:
        query = query.filter(Student.class_id == class_id)

    if academic_year_id:
        query = query.filter(Student.academic_year_id == academic_year_id)

    if gender:
        query = query.filter(db.func.lower(Student.gender) == gender.strip().lower())

    if student_status:
        query = query.filter(
            db.func.lower(Student.student_status) == student_status.strip().lower()
        )

    if is_transport_opted is not None:
        query = query.filter(Student.is_transport_opted == bool(is_transport_opted))

    date_from = _parse_date(admission_date_from)
    if date_from:
        query = query.filter(Student.admission_date >= date_from)
    date_to = _parse_date(admission_date_to)
    if date_to:
        query = query.filter(Student.admission_date <= date_to)

    if search:
        term = search.strip()
        if term:
            pattern = f"%{term}%"
            field = search_field if search_field in SEARCH_FIELDS else "all"
            if field == "name":
                query = query.filter(User.name.ilike(pattern))
            elif field == "admission_number":
                query = query.filter(Student.admission_number.ilike(pattern))
            elif field == "email":
                query = query.filter(User.email.ilike(pattern))
            elif field == "guardian_phone":
                query = query.filter(Student.guardian_phone.ilike(pattern))
            else:
                query = query.filter(
                    db.or_(
                        User.name.ilike(pattern),
                        User.email.ilike(pattern),
                        Student.admission_number.ilike(pattern),
                        Student.guardian_phone.ilike(pattern),
                    )
                )

    # Sorting. Class sort uses the natural grade_level order (not a lex sort on
    # name, which would put "10" before "2"). Outer-join so students without a
    # class still appear at the end. Admission_number is always the tie-breaker.
    sort_key = sort_by if sort_by in SORTABLE_COLUMNS else "admission_number"
    is_desc = str(sort_dir).lower() == "desc"

    def _ordered(col, nulls_last: bool = False):
        expr = col.desc() if is_desc else col.asc()
        # NULLS LAST keeps rows with NULL in the sort key at the bottom in both
        # directions (default PG behaviour puts NULLS first in DESC).
        return expr.nulls_last() if nulls_last else expr

    if sort_key == "class":
        query = query.outerjoin(Class, Student.class_id == Class.id)
        order_cols = [
            _ordered(Class.grade_level, nulls_last=True),
            _ordered(Class.name, nulls_last=True),
            _ordered(Class.section, nulls_last=True),
        ]
    elif sort_key == "name":
        order_cols = [_ordered(User.name)]
    elif sort_key == "roll_number":
        order_cols = [_ordered(Student.roll_number, nulls_last=True)]
    else:  # admission_number (default)
        order_cols = [_ordered(Student.admission_number)]

    if sort_key != "admission_number":
        order_cols.append(Student.admission_number.asc())

    query = query.order_by(*order_cols)

    # Pagination. If the caller doesn't ask for a page, return everything
    # (keeps non-paginating callers like the mobile app working).
    total = query.count()
    if page is not None and per_page is not None and per_page > 0:
        page = max(1, int(page))
        per_page = max(1, min(int(per_page), 100))
        students = query.limit(per_page).offset((page - 1) * per_page).all()
        total_pages = max(1, (total + per_page - 1) // per_page)
    else:
        students = query.all()
        page = 1
        per_page = len(students) or 0
        total_pages = 1

    # Skip the profile_picture URL on list responses — each value is a
    # presigned S3 URL and generating hundreds per page is pure overhead.
    items = [s.to_dict(include_profile_picture=False) for s in students]
    if include_transport_summary:
        _attach_transport_summary(items, academic_year_id)

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }


def get_student_by_id(student_id: str) -> Optional[Dict]:
    """Get student details by ID"""
    student = Student.query.get(student_id)
    return student.to_dict() if student else None


def attach_transport_to_student_dict(
    student_dict: Optional[Dict],
    student_id: str,
    viewer_user_id: str,
) -> Optional[Dict]:
    """Adds `transport` key when plan feature + RBAC allow (see transport module)."""
    if not student_dict:
        return student_dict
    from modules.transport.services import build_student_transport_block

    student_dict["transport"] = build_student_transport_block(student_id, viewer_user_id)
    return student_dict


def get_student_by_user_id(user_id: str) -> Optional[Dict]:
    """Get student details by User ID"""
    student = Student.query.filter_by(user_id=user_id).first()
    return student.to_dict() if student else None

def update_student(
    student_id: str,
    name: Optional[str] = None,
    academic_year_id: Optional[str] = None,
    class_id: Optional[str] = None,
    roll_number: Optional[int] = None,
    date_of_birth: Optional[str] = None,
    gender: Optional[str] = None,
    phone: Optional[str] = None,
    address: Optional[str] = None,
    guardian_name: Optional[str] = None,
    guardian_relationship: Optional[str] = None,
    guardian_phone: Optional[str] = None,
    guardian_email: Optional[str] = None,
    # Extended fields (all optional)
    blood_group: Optional[str] = None,
    height_cm: Optional[int] = None,
    weight_kg: Optional[str] = None,
    medical_allergies: Optional[str] = None,
    medical_conditions: Optional[str] = None,
    disability_details: Optional[str] = None,
    identification_marks: Optional[str] = None,

    father_name: Optional[str] = None,
    father_phone: Optional[str] = None,
    father_email: Optional[str] = None,
    father_occupation: Optional[str] = None,
    father_annual_income: Optional[int] = None,

    mother_name: Optional[str] = None,
    mother_phone: Optional[str] = None,
    mother_email: Optional[str] = None,
    mother_occupation: Optional[str] = None,
    mother_annual_income: Optional[int] = None,

    guardian_address: Optional[str] = None,
    guardian_occupation: Optional[str] = None,
    guardian_aadhar_number: Optional[str] = None,

    aadhar_number: Optional[str] = None,
    apaar_id: Optional[str] = None,
    emis_number: Optional[str] = None,
    udise_student_id: Optional[str] = None,
    religion: Optional[str] = None,
    category: Optional[str] = None,
    caste: Optional[str] = None,
    nationality: Optional[str] = None,
    mother_tongue: Optional[str] = None,
    place_of_birth: Optional[str] = None,

    current_address: Optional[str] = None,
    current_city: Optional[str] = None,
    current_state: Optional[str] = None,
    current_pincode: Optional[str] = None,

    permanent_address: Optional[str] = None,
    permanent_city: Optional[str] = None,
    permanent_state: Optional[str] = None,
    permanent_pincode: Optional[str] = None,

    is_same_as_permanent_address: Optional[bool] = None,
    is_commuting_from_outstation: Optional[bool] = None,
    commute_location: Optional[str] = None,
    commute_notes: Optional[str] = None,

    emergency_contact_name: Optional[str] = None,
    emergency_contact_relationship: Optional[str] = None,
    emergency_contact_phone: Optional[str] = None,
    emergency_contact_alt_phone: Optional[str] = None,

    admission_date: Optional[str] = None,
    previous_school_name: Optional[str] = None,
    previous_school_class: Optional[str] = None,
    last_school_board: Optional[str] = None,
    tc_number: Optional[str] = None,
    house_name: Optional[str] = None,
    student_status: Optional[str] = None,
) -> Dict:
    """
    Update student details.
    
    Only updates fields that are explicitly provided (not None).
    Handles both User fields (name) and Student fields.
    
    Args:
        student_id: Student ID to update
        name: Update student name
        academic_year: Update academic year
        Other fields: Optional updates to student profile
        
    Returns:
        Dict with success status and updated student data or error
    """
    try:
        student = Student.query.get(student_id)
        if not student:
            return {'success': False, 'error': 'Student not found'}
            
        # Update User fields
        if name is not None:
            student.user.name = name
            student.user.save()
            
        # Update Student fields (only if provided)
        ay_id = _resolve_student_academic_year_id(academic_year_id, class_id if class_id else student.class_id)
        if ay_id is not None:
            student.academic_year_id = ay_id
        if class_id is not None:
            student.class_id = class_id
        if roll_number is not None:
            student.roll_number = roll_number
        if date_of_birth is not None:
            student.date_of_birth = datetime.strptime(date_of_birth, '%Y-%m-%d').date()
        if gender is not None:
            student.gender = gender
        if phone is not None:
            student.phone = phone
        if address is not None:
            student.address = address
        if guardian_name is not None:
            student.guardian_name = guardian_name
        if guardian_relationship is not None:
            student.guardian_relationship = guardian_relationship
        if guardian_phone is not None:
            student.guardian_phone = guardian_phone
        if guardian_email is not None:
            student.guardian_email = guardian_email

        # Extended fields (only if provided)
        if blood_group is not None:
            student.blood_group = _clean_str(blood_group)
        if height_cm is not None:
            student.height_cm = _clean_int(height_cm)
        if weight_kg is not None:
            student.weight_kg = _clean_decimal(weight_kg)
        if medical_allergies is not None:
            student.medical_allergies = _clean_str(medical_allergies)
        if medical_conditions is not None:
            student.medical_conditions = _clean_str(medical_conditions)
        if disability_details is not None:
            student.disability_details = _clean_str(disability_details)
        if identification_marks is not None:
            student.identification_marks = _clean_str(identification_marks)

        if father_name is not None:
            student.father_name = _clean_str(father_name)
        if father_phone is not None:
            student.father_phone = _clean_str(father_phone)
        if father_email is not None:
            student.father_email = _clean_str(father_email)
        if father_occupation is not None:
            student.father_occupation = _clean_str(father_occupation)
        if father_annual_income is not None:
            student.father_annual_income = _clean_int(father_annual_income)

        if mother_name is not None:
            student.mother_name = _clean_str(mother_name)
        if mother_phone is not None:
            student.mother_phone = _clean_str(mother_phone)
        if mother_email is not None:
            student.mother_email = _clean_str(mother_email)
        if mother_occupation is not None:
            student.mother_occupation = _clean_str(mother_occupation)
        if mother_annual_income is not None:
            student.mother_annual_income = _clean_int(mother_annual_income)

        if guardian_address is not None:
            student.guardian_address = _clean_str(guardian_address)
        if guardian_occupation is not None:
            student.guardian_occupation = _clean_str(guardian_occupation)
        if guardian_aadhar_number is not None:
            student.guardian_aadhar_number = _clean_str(guardian_aadhar_number)

        if aadhar_number is not None:
            student.aadhar_number = _clean_str(aadhar_number)
        if apaar_id is not None:
            student.apaar_id = _clean_str(apaar_id)
        if emis_number is not None:
            student.emis_number = _clean_str(emis_number)
        if udise_student_id is not None:
            student.udise_student_id = _clean_str(udise_student_id)
        if religion is not None:
            student.religion = _clean_str(religion)
        if category is not None:
            student.category = _clean_str(category)
        if caste is not None:
            student.caste = _clean_str(caste)
        if nationality is not None:
            student.nationality = _clean_str(nationality)
        if mother_tongue is not None:
            student.mother_tongue = _clean_str(mother_tongue)
        if place_of_birth is not None:
            student.place_of_birth = _clean_str(place_of_birth)

        if current_address is not None:
            student.current_address = _clean_str(current_address)
        if current_city is not None:
            student.current_city = _clean_str(current_city)
        if current_state is not None:
            student.current_state = _clean_str(current_state)
        if current_pincode is not None:
            student.current_pincode = _clean_str(current_pincode)

        if permanent_address is not None:
            student.permanent_address = _clean_str(permanent_address)
        if permanent_city is not None:
            student.permanent_city = _clean_str(permanent_city)
        if permanent_state is not None:
            student.permanent_state = _clean_str(permanent_state)
        if permanent_pincode is not None:
            student.permanent_pincode = _clean_str(permanent_pincode)

        if is_same_as_permanent_address is not None:
            student.is_same_as_permanent_address = _clean_bool(is_same_as_permanent_address)
        if is_commuting_from_outstation is not None:
            student.is_commuting_from_outstation = _clean_bool(is_commuting_from_outstation)
        if commute_location is not None:
            student.commute_location = _clean_str(commute_location)
        if commute_notes is not None:
            student.commute_notes = _clean_str(commute_notes)

        if emergency_contact_name is not None:
            student.emergency_contact_name = _clean_str(emergency_contact_name)
        if emergency_contact_relationship is not None:
            student.emergency_contact_relationship = _clean_str(emergency_contact_relationship)
        if emergency_contact_phone is not None:
            student.emergency_contact_phone = _clean_str(emergency_contact_phone)
        if emergency_contact_alt_phone is not None:
            student.emergency_contact_alt_phone = _clean_str(emergency_contact_alt_phone)

        if admission_date is not None:
            student.admission_date = (
                datetime.strptime(admission_date, "%Y-%m-%d").date() if admission_date else None
            )
        if previous_school_name is not None:
            student.previous_school_name = _clean_str(previous_school_name)
        if previous_school_class is not None:
            student.previous_school_class = _clean_str(previous_school_class)
        if last_school_board is not None:
            student.last_school_board = _clean_str(last_school_board)
        if tc_number is not None:
            student.tc_number = _clean_str(tc_number)
        if house_name is not None:
            student.house_name = _clean_str(house_name)
        if student_status is not None:
            student.student_status = _clean_str(student_status)
            
        student.save()
        return {'success': True, 'student': student.to_dict()}
    except ValueError as e:
        db.session.rollback()
        return {'success': False, 'error': f'Invalid data format: {str(e)}'}
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': f'Failed to update student: {str(e)}'}

def delete_student(student_id: str) -> Dict:
    """
    Delete student.

    Finance `student_fees` rows (from auto-assign when class/fee structure applies) must be
    removed before the student row: SQLAlchemy otherwise syncs the parent delete by
    UPDATE student_fees SET student_id=NULL, which violates NOT NULL even though the DB
    has ON DELETE CASCADE. Bulk-delete issues DELETE and lets FK cascade to items/payments.
    """
    try:
        tenant_id = get_tenant_id()
        if not tenant_id:
            return {'success': False, 'error': 'Tenant context required'}

        student = Student.query.filter_by(id=student_id, tenant_id=tenant_id).first()
        if not student:
            return {'success': False, 'error': 'Student not found'}

        from modules.finance.models import StudentFee

        StudentFee.query.filter_by(
            student_id=student_id,
            tenant_id=tenant_id,
        ).delete(synchronize_session=False)

        db.session.delete(student)
        db.session.commit()
        return {'success': True, 'message': 'Student deleted successfully'}
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': f'Failed to delete student: {str(e)}'}


# ---------------------------------------------------------------------------
# Student Documents (S3-backed storage)
# ---------------------------------------------------------------------------

MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_MIME_TYPES = {"application/pdf", "image/jpeg", "image/jpg", "image/png"}


def create_student_document(
    student_id: str,
    file_obj,
    filename: str,
    document_type: str,
    user_id: str,
) -> Dict:
    """
    Validate file, upload to S3, save StudentDocument. Returns doc dict or error.
    file_obj: Flask FileStorage with .stream, .content_type, .filename
    """
    try:
        tenant_id = get_tenant_id()
        if not tenant_id:
            return {"success": False, "error": "Tenant context required", "error_code": "ValidationError"}

        student = Student.query.get(student_id)
        if not student:
            return {"success": False, "error": "Student not found", "error_code": "NotFound"}

        if student.tenant_id != tenant_id:
            return {"success": False, "error": "Student not found", "error_code": "NotFound"}

        err = validate_document_type(document_type)
        if err:
            return {"success": False, "error": err, "error_code": "ValidationError"}

        # Normalize to enum value (lowercase) for PostgreSQL enum
        document_type = (document_type or "").strip().lower()

        stream = getattr(file_obj, "stream", file_obj)
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(0)
        if size > MAX_FILE_SIZE_BYTES:
            return {
                "success": False,
                "error": "File too large. Maximum allowed size is 10 MB.",
                "error_code": "FileTooLarge",
            }
        if size == 0:
            return {"success": False, "error": "File is empty.", "error_code": "ValidationError"}

        content_type = getattr(file_obj, "content_type", getattr(stream, "content_type", None)) or ""
        mime = (content_type or "").split(";")[0].strip().lower()
        if mime not in ALLOWED_MIME_TYPES:
            return {
                "success": False,
                "error": "Unsupported file type. Allowed: PDF, JPG, PNG.",
                "error_code": "UnsupportedFileType",
            }

        try:
            folder = f"{TENANTS}/{tenant_id}/{STUDENTS}/{student_id}/{DOCUMENTS}"
            _, object_key = upload_file(
                stream,
                folder=folder,
                original_filename=filename,
                content_type=mime,
            )
        except Exception as e:
            logger.exception("S3 upload failed: %s", e)
            return {
                "success": False,
                "error": "Document storage unavailable. Please try again.",
                "error_code": "StorageError",
            }

        doc = StudentDocument(
            tenant_id=tenant_id,
            student_id=student_id,
            document_type=DocumentType(document_type),
            original_filename=filename,
            cloudinary_url=object_key,
            cloudinary_public_id=object_key,
            mime_type=mime,
            file_size_bytes=size,
            uploaded_by_user_id=user_id,
        )
        db.session.add(doc)
        db.session.commit()

        return {"success": True, "document": doc.to_dict()}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e), "error_code": "InternalError"}


def list_student_documents(student_id: str) -> Dict:
    """List documents for a student. Returns {documents: [...]} or error."""
    try:
        tenant_id = get_tenant_id()
        if not tenant_id:
            return {"success": False, "error": "Tenant context required"}

        student = Student.query.get(student_id)
        if not student:
            return {"success": False, "error": "Student not found"}
        if student.tenant_id != tenant_id:
            return {"success": False, "error": "Student not found"}

        docs = StudentDocument.query.filter_by(student_id=student_id, tenant_id=tenant_id).order_by(
            StudentDocument.created_at.desc()
        ).all()
        return {"success": True, "documents": [d.to_dict() for d in docs]}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_student_document_by_id(document_id: str, student_id: str) -> Optional[Dict]:
    """Get a single document by id, verifying it belongs to student and tenant."""
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None
    doc = StudentDocument.query.filter_by(
        id=document_id, student_id=student_id, tenant_id=tenant_id
    ).first()
    return doc.to_dict() if doc else None


def get_student_document_file_content(document_id: str, student_id: str) -> Dict:
    """
    Load file bytes from S3 for authenticated download proxy.

    Returns:
        {success, data, mime_type, filename} or {success: False, error}
    """
    try:
        tenant_id = get_tenant_id()
        if not tenant_id:
            return {"success": False, "error": "Tenant context required"}

        doc = StudentDocument.query.filter_by(
            id=document_id, student_id=student_id, tenant_id=tenant_id
        ).first()
        if not doc:
            return {"success": False, "error": "Document not found"}

        key = doc.cloudinary_public_id or doc.cloudinary_url
        if not key:
            return {"success": False, "error": "Document has no storage key"}

        try:
            data, ct = fetch_s3_object_bytes(key)
        except FileNotFoundError:
            return {"success": False, "error": "File not found in storage"}
        except Exception as e:
            logger.exception("S3 fetch failed for document %s: %s", document_id, e)
            return {"success": False, "error": "Could not load file from storage"}

        return {
            "success": True,
            "data": data,
            "mime_type": doc.mime_type or ct,
            "filename": doc.original_filename or "document",
        }
    except Exception as e:
        logger.exception("get_student_document_file_content: %s", e)
        return {"success": False, "error": str(e)}


def delete_student_document(document_id: str, student_id: str) -> Dict:
    """Delete document from DB and S3."""
    try:
        tenant_id = get_tenant_id()
        if not tenant_id:
            return {"success": False, "error": "Tenant context required"}

        doc = StudentDocument.query.filter_by(
            id=document_id, student_id=student_id, tenant_id=tenant_id
        ).first()
        if not doc:
            return {"success": False, "error": "Document not found"}

        try:
            delete_file(doc.cloudinary_public_id)
        except Exception:
            pass

        db.session.delete(doc)
        db.session.commit()
        return {"success": True}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}