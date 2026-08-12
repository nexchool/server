from shared.safe_error import safe_error
from typing import List, Dict, Optional, Any, Set
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased, contains_eager, joinedload
from datetime import datetime
import logging
import string
from decimal import Decimal

from core.database import db
from core.tenant import get_tenant_id
from core.models import Tenant
from modules.auth.models import User
from modules.rbac.services import remove_login_for_deleted_profile
from modules.rbac.role_seeder import seed_roles_for_tenant
from modules.academic_programmes.models import AcademicProgramme
from modules.classes.models import Class
from modules.people.models import Person
from shared.s3_utils import delete_file, fetch_s3_object_bytes, upload_file
from shared.storage_constants import DOCUMENTS, STUDENTS, TENANTS
from .models import Student
from .student_schemas import (
    DEFAULT_STUDENT_STATUS,
    STUDENT_STATUS_VALUES,
    WORKFLOW_ONLY_STATUSES,
)
from .class_enrollment_service import (
    assign_student_to_class,
    student_matches_academic_year_filter,
    student_matches_class_filter,
    student_matches_any_class_filter,
)
from core.school_time import utc_now

logger = logging.getLogger(__name__)

# Sentinel: update_student omits class / academic year when not present in the request body
PLACEMENT_UNSET = object()

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


def generate_admission_number(
    tenant_id: Optional[str] = None, *, reserved: Optional[Set[str]] = None
) -> str:
    """
    Allocate the next unique admission number for the tenant.

    Format comes from academic_settings.admission_number_format or the product
    default (ADM{YEAR}{SEQ:3}). See shared.id_pattern.
    """
    from shared.id_pattern import (
        MAX_STUDENT_ID_LEN,
        allocate_next_id,
        get_student_admission_pattern,
    )

    tid = tenant_id or get_tenant_id()
    if not tid:
        raise ValueError("Tenant context is required to generate an admission number")
    pattern = get_student_admission_pattern(tid)
    return allocate_next_id(
        tenant_id=tid,
        model=Student,
        col_name="admission_number",
        pattern=pattern,
        reserved=reserved,
        max_len=MAX_STUDENT_ID_LEN,
    )


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
            birth_year = utc_now().year
    else:
        birth_year = utc_now().year
    
    return f"{name_part}{birth_year}"


def create_student(
    name: str,
    academic_year_id: Optional[str] = None,
    guardian_name: str = None,
    guardian_relationship: str = None,
    guardian_phone: str = None,
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
    1. Auto-generate admission number (not accepted from the client)
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
        tenant_id = get_tenant_id()
        if not tenant_id:
            return {'success': False, 'error': 'Tenant context is required'}

        try:
            admission_number = generate_admission_number(tenant_id)
        except (RuntimeError, ValueError) as e:
            return {'success': False, 'error': str(e)}

        # Plan enforcement: do not allow creating students beyond plan limit
        allowed, limit_msg = _check_student_plan_limit(tenant_id)
        if not allowed:
            return {'success': False, 'error': limit_msg}

        # Validate admission number uniqueness (tenant-scoped; query auto-filtered)
        if Student.query.filter_by(admission_number=admission_number).first():
            return {'success': False, 'error': 'Admission number already exists'}

        # Validate class exists if provided (tenant-scoped). Reject any
        # cross-tenant id; in the structured flow the class carries the
        # programme + school_unit, so they don't need to be resent.
        class_obj = None
        if class_id:
            class_obj = Class.query.filter_by(id=class_id, tenant_id=tenant_id).first()
            if not class_obj:
                return {'success': False, 'error': 'Class not found for this tenant'}

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
            # Check if email already exists in this tenant. Include soft-deleted
            # rows: the (email, tenant_id) unique constraint is not scoped to
            # deleted_at, so a soft-deleted email must be caught here to avoid an
            # IntegrityError on insert.
            existing_user = User.get_user_by_email(email, tenant_id=tenant_id, include_deleted=True)
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

            # Ensure the Student profile exists with its permissions for this
            # tenant (idempotent). It is NOT granted: a student's access is
            # implied by the Student relationship itself (migration 087), and
            # granting would require an employment to hold it (ADR-013) —
            # which is why the old grant call here failed for every
            # admin-created student login after migration 089.
            seed_roles_for_tenant(tenant_id)

        # The student relationship belongs to a human (ADR-001). With an
        # account, that account already carries the Person; without one, the
        # admission itself records the person. No email means no login
        # (ADR-003) — the old placeholder accounts (@student.placeholder,
        # unusable random password) are no longer minted.
        from modules.people.service import (
            fill_blank_identity,
            record_family_member,
            record_person,
        )

        if user is not None:
            person = user.person
        else:
            # record_person constructs without persisting (People takes what
            # it is told); the caller owns attaching it to the session.
            person = record_person(tenant_id, name)
            db.session.add(person)
            db.session.flush()

        parsed_date_of_birth = (
            datetime.strptime(date_of_birth, '%Y-%m-%d').date() if date_of_birth else None
        )
        if person is not None:
            fill_blank_identity(
                person,
                {
                    "date_of_birth": parsed_date_of_birth,
                    "gender": gender,
                    "phone_number": phone,
                    "address": address,
                },
            )

            # Admission is where the school says who is responsible for this
            # child, so the family is recorded now rather than by a later
            # migration. A sibling already enrolled joins the same family.
            # The guardian the admission form names is the adult the school
            # will call, whatever their relationship turns out to be. Recording
            # that as a fact of the household is what lets both parents be kept
            # without the father being stored twice.
            for member_name, member_relationship, member_phone, member_email, member_occupation, is_contact in (
                (guardian_name, guardian_relationship, guardian_phone, guardian_email, guardian_occupation, True),
                (father_name, 'father', father_phone, father_email, father_occupation, False),
                (mother_name, 'mother', mother_phone, mother_email, mother_occupation, False),
            ):
                record_family_member(
                    tenant_id,
                    person.id,
                    name=member_name,
                    relationship=member_relationship,
                    phone=member_phone,
                    email=member_email,
                    occupation=member_occupation,
                    is_primary_contact=is_contact,
                )

        # Create Student Profile (tenant-scoped)
        student = Student(
            tenant_id=tenant_id,
            user_id=user.id if user is not None else None,
            person_id=person.id if person is not None else None,
            admission_number=admission_number,
            academic_year_id=ay_id,
            roll_number=roll_number,
            class_id=class_id,
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
            # New students default to "active"; the status field is not
            # collected on create and is only editable afterwards.
            student_status=_clean_str(student_status) or DEFAULT_STUDENT_STATUS,
        )
        db.session.add(student)
        db.session.flush()
        if class_id:
            enr = assign_student_to_class(
                student.id, class_id, ay_id, commit=False
            )
            if not enr.get("success"):
                db.session.rollback()
                return {
                    "success": False,
                    "error": enr.get("error", "Could not create class enrollment"),
                }
        db.session.commit()

        # Refresh tenant usage so billing reflects the new student. Failures
        # here log but do not break the create — usage is best-effort.
        try:
            from modules.subscription.usage import recompute_tenant_usage

            recompute_tenant_usage(tenant_id)
        except Exception:
            logger.exception("recompute_tenant_usage failed after create_student")

        # Auto-assign any applicable fee structures for this student's class/year.
        # Skipped silently when finance is disabled — student creation still succeeds.
        try:
            from core.feature_flags import is_feature_enabled

            if is_feature_enabled(tenant_id, "fees_management"):
                from modules.finance.services import student_fee_service

                student_fee_service.auto_assign_fees_for_student(student.id)
        except Exception:
            logger.exception("auto_assign_fees_for_student failed after create_student")

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
        error_msg = str(getattr(e, "orig", None) or e)
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
        return {'success': False, 'error': safe_error(e, "Failed to create student")}

# Columns the client may sort by. The actual ordering expression is built in
# `_build_sort_order` below so `class` can use natural (grade_level) order
# rather than a lexicographic sort on the class name.
SORTABLE_COLUMNS = {"admission_number", "name", "class", "roll_number", "programme"}

# Fields the client may pick in the "search within" dropdown.
SEARCH_FIELDS = {"all", "name", "admission_number", "email", "guardian_phone", "programme"}


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
    from core.feature_flags import is_feature_enabled
    if not is_feature_enabled(tenant_id, "transport"):
        return
    from modules.transport.services import transport_summaries_for_students

    summ = transport_summaries_for_students(rows, academic_year_id=academic_year_id)
    for r in rows:
        extra = summ.get(r.get("id"))
        if extra:
            r.update(extra)


# Sorts whose key can never be null, so a cursor over them cannot skip or
# repeat a row. `class`, `programme` and `roll_number` are all nullable and
# mutable — a cursor over those silently loses students, which is worse than
# admitting the sort needs an offset.
CURSORABLE_COLUMNS = {"admission_number", "name"}


def _student_list_query(
    *,
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
    school_unit_id: Optional[str] = None,
    programme_id: Optional[str] = None,
    grade_id: Optional[str] = None,
    restrict_class_ids: Optional[List[str]] = None,
):
    """The filtered, sorted student query — the one both transports run.

    Extracted so REST and GraphQL cannot answer the same question
    differently while both exist. A filter added here reaches both; a filter
    added to only one of them is the drift this is here to prevent.

    Returns ``(query, sort_key, is_desc)``, or ``None`` when the caller is
    scoped to no classes at all — a teacher who teaches nothing matches no
    students, which is not the same as no filter.
    """
    from core.branch_scope import filter_students_by_branch

    # Person is inner-joined: every student relationship belongs to a human
    # (ADR-001), and filtering, searching and sorting must read the same facts
    # the payload shows rather than the columns left over beside them.
    # The account is OUTER-joined: a student may have no login (ADR-003,
    # migration 094), and an inner join would silently drop them from the list.
    query = Student.query.outerjoin(User).join(Person, Student.person_id == Person.id)

    # Branch scope backstop: restrict to students in allowed-branch classes
    # (classless excluded) regardless of client filters. No-op if unrestricted.
    query = filter_students_by_branch(query)

    # Teacher scope: hard ceiling on which classes are visible at all.
    if restrict_class_ids is not None:
        if not restrict_class_ids:
            return None
        query = query.filter(student_matches_any_class_filter(restrict_class_ids))

    # Client-supplied class scoping (AND-ed with the teacher ceiling above).
    if class_ids:
        query = query.filter(student_matches_any_class_filter(class_ids))
    elif class_id:
        query = query.filter(student_matches_class_filter(class_id))

    if academic_year_id:
        query = query.filter(student_matches_academic_year_filter(academic_year_id))

    # Multi-school structural filters: scope through the student's current
    # class. Students with no class_id are excluded when any of these are set.
    # Class is ALIASED here: the outer query may itself join Class (class /
    # programme sort, programme search) and an unaliased correlated subquery
    # would auto-correlate against that join and lose its FROM clause.
    if school_unit_id or programme_id or grade_id:
        ClassScope = aliased(Class)
        class_filter = db.session.query(ClassScope.id).filter(
            ClassScope.tenant_id == Student.tenant_id
        )
        if school_unit_id:
            class_filter = class_filter.filter(ClassScope.school_unit_id == school_unit_id)
        if programme_id:
            class_filter = class_filter.filter(ClassScope.programme_id == programme_id)
        if grade_id:
            class_filter = class_filter.filter(ClassScope.grade_id == grade_id)
        query = query.filter(Student.class_id.in_(class_filter))

    if gender:
        query = query.filter(db.func.lower(Person.gender) == gender.strip().lower())

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

    # Programme search/sort and class sort all reach Class (and programme also
    # AcademicProgramme) through joins; apply each join at most once whichever
    # combination of search + sort needs it.
    sort_key = sort_by if sort_by in SORTABLE_COLUMNS else "admission_number"
    is_desc = str(sort_dir).lower() == "desc"
    term = (search or "").strip()
    field = search_field if search_field in SEARCH_FIELDS else "all"
    programme_needed = sort_key == "programme" or (
        bool(term) and field in ("all", "programme")
    )
    if programme_needed or sort_key == "class":
        query = query.outerjoin(Class, Student.class_id == Class.id)
    if programme_needed:
        query = query.outerjoin(
            AcademicProgramme, Class.programme_id == AcademicProgramme.id
        )

    if term:
        pattern = f"%{term}%"
        if field == "name":
            query = query.filter(Person.full_name.ilike(pattern))
        elif field == "admission_number":
            query = query.filter(Student.admission_number.ilike(pattern))
        elif field == "email":
            query = query.filter(User.email.ilike(pattern))
        elif field == "guardian_phone":
            query = query.filter(Student.guardian_phone.ilike(pattern))
        elif field == "programme":
            query = query.filter(AcademicProgramme.name.ilike(pattern))
        else:
            query = query.filter(
                db.or_(
                    Person.full_name.ilike(pattern),
                    User.email.ilike(pattern),
                    Student.admission_number.ilike(pattern),
                    # Guardian details still live on the student row until the
                    # family read moves with the client (see the debt register).
                    Student.guardian_phone.ilike(pattern),
                    AcademicProgramme.name.ilike(pattern),
                )
            )

    # Sorting. Class sort uses the natural grade_level order (not a lex sort on
    # name, which would put "10" before "2"). Outer-joins keep students without
    # a class at the end. Admission_number is always the tie-breaker.
    def _ordered(col, nulls_last: bool = False):
        expr = col.desc() if is_desc else col.asc()
        # NULLS LAST keeps rows with NULL in the sort key at the bottom in both
        # directions (default PG behaviour puts NULLS first in DESC).
        return expr.nulls_last() if nulls_last else expr

    if sort_key == "class":
        order_cols = [
            _ordered(Class.grade_level, nulls_last=True),
            _ordered(Class.name, nulls_last=True),
            _ordered(Class.section, nulls_last=True),
        ]
    elif sort_key == "programme":
        order_cols = [
            _ordered(AcademicProgramme.name, nulls_last=True),
            _ordered(Class.grade_level, nulls_last=True),
            _ordered(Class.section, nulls_last=True),
        ]
    elif sort_key == "name":
        order_cols = [_ordered(Person.full_name)]
    elif sort_key == "roll_number":
        order_cols = [_ordered(Student.roll_number, nulls_last=True)]
    else:  # admission_number (default)
        order_cols = [_ordered(Student.admission_number)]

    if sort_key != "admission_number":
        order_cols.append(Student.admission_number.asc())

    return query.order_by(*order_cols), sort_key, is_desc


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
    school_unit_id: Optional[str] = None,
    programme_id: Optional[str] = None,
    grade_id: Optional[str] = None,
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
    built = _student_list_query(
        class_id=class_id,
        class_ids=class_ids,
        academic_year_id=academic_year_id,
        search=search,
        search_field=search_field,
        gender=gender,
        student_status=student_status,
        is_transport_opted=is_transport_opted,
        admission_date_from=admission_date_from,
        admission_date_to=admission_date_to,
        sort_by=sort_by,
        sort_dir=sort_dir,
        school_unit_id=school_unit_id,
        programme_id=programme_id,
        grade_id=grade_id,
        restrict_class_ids=_restrict_class_ids,
    )
    if built is None:
        return {"items": [], "total": 0, "page": 1, "per_page": 0, "total_pages": 1}
    query, _sort_key, _is_desc = built

    # Pagination. If the caller doesn't ask for a page, return everything
    # (keeps non-paginating callers like the mobile app working).
    total = query.count()
    # Eager-load the relationships to_dict touches (user, class, programme,
    # grade) so serialization stays at a constant number of queries per page.
    # The account is already outer-joined above — contains_eager reuses that
    # join and leaves user None for account-less students.
    query = query.options(
        contains_eager(Student.user),
        joinedload(Student.person),
        joinedload(Student.current_class).joinedload(Class.programme),
        joinedload(Student.current_class).joinedload(Class.grade),
    )
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
    # The household is not shown in a list, and reading it costs four queries
    # a row. The flat guardian_/father_/mother_ keys still carry the contact
    # details a list needs, and they are plain columns.
    items = [
        s.to_dict(include_profile_picture=False, include_family=False)
        for s in students
    ]
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


def student_for_user(user_id: str, tenant_id: Optional[str] = None):
    """The studentship of whoever is signed in, or None.

    Reached through the Person, not through `students.user_id`. The account is
    optional (ADR-003) and the Person is the identity (ADR-001), so a child
    who has never been given a login is still a student and must still be able
    to be recognised — reading the column found nobody and quietly answered
    "you have no record here".

    Unambiguous under either family-access mode: the Student relationship is
    what carries the Account (ADR-011), so one account resolves to one child.
    Siblings hold their own credentials rather than sharing one.
    """
    from modules.auth.models import User

    account = User.query.filter_by(id=user_id).first()
    if account is None or account.person_id is None:
        return None

    query = Student.query.filter_by(person_id=account.person_id)
    if tenant_id:
        query = query.filter_by(tenant_id=tenant_id)
    return query.first()


def is_own_studentship(student, user) -> bool:
    """Whether this signed-in person is the child whose record this is.

    Compares the Person rather than the account for the same reason
    `student_for_user` looks one up that way.
    """
    if student is None or user is None:
        return False
    return (
        student.person_id is not None and student.person_id == user.person_id
    )


def get_student_by_user_id(user_id: str) -> Optional[Dict]:
    """Get student details for whoever is signed in."""
    student = student_for_user(user_id)
    return student.to_dict() if student else None


def _apply_placement_update(
    student: Student,
    *,
    class_id: Any,
    academic_year_id: Any,
) -> Optional[str]:
    """Returns an error message or None. Session commit is the caller's responsibility."""
    if class_id is PLACEMENT_UNSET and academic_year_id is PLACEMENT_UNSET:
        return None

    if class_id is not PLACEMENT_UNSET and class_id is None:
        ay = academic_year_id if academic_year_id is not PLACEMENT_UNSET else None
        res = assign_student_to_class(student.id, None, ay, commit=False)
        return None if res.get("success") else res.get("error", "Placement update failed")

    if class_id is not PLACEMENT_UNSET and class_id:
        ay = academic_year_id if academic_year_id is not PLACEMENT_UNSET else None
        res = assign_student_to_class(student.id, class_id, ay, commit=False)
        return None if res.get("success") else res.get("error", "Placement update failed")

    res = assign_student_to_class(
        student.id,
        student.class_id,
        academic_year_id,
        commit=False,
    )
    return None if res.get("success") else res.get("error", "Placement update failed")


def update_student(
    student_id: str,
    family=None,
    name: Optional[str] = None,
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
    academic_result: Optional[str] = None,
    *,
    class_id: Any = PLACEMENT_UNSET,
    academic_year_id: Any = PLACEMENT_UNSET,
) -> Dict:
    """
    Update student details.

    Only updates fields that are explicitly provided (not None).
    Handles both User fields (name) and Student fields.

    class_id / academic_year_id use PLACEMENT_UNSET when the client omits the key;
    pass ``None`` only when the key is present with a null value (clear class / year).
    """
    try:
        student = Student.query.get(student_id)
        if not student:
            return {'success': False, 'error': 'Student not found'}
            
        # Update the login's display name too — when there is a login
        # (ADR-003: a student may have none). The person's name is revised
        # below either way.
        if name is not None and student.user is not None:
            student.user.name = name
            student.user.save()
            
        # Update Student fields (only if provided)
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
            # Leaving, finishing and moving school are workflows, not fields:
            # each closes a placement, carries a date and a reason, and is
            # recorded. Setting the word here would leave the rest undone —
            # which is how graduated students went on being billed.
            cleaned_status = _clean_str(student_status)
            if cleaned_status in WORKFLOW_ONLY_STATUSES:
                return {
                    "success": False,
                    "error": (
                        f"'{cleaned_status}' is the outcome of a workflow, not an "
                        "edit. Use the withdraw, graduate or transfer action so "
                        "the placement is closed and the reason recorded."
                    ),
                }
            student.student_status = cleaned_status
        if academic_result is not None:
            student.academic_result = _clean_str(academic_result)

        if family is not None:
            from modules.people.service import record_household

            record_household(student.tenant_id, student.person_id, family)

        # The same edit reaches the human it describes. Until now only
        # admission did this, so a Person recorded at admission stopped
        # agreeing with the student the moment anyone corrected the record.
        _record_edit_against_the_person(
            student,
            name=name,
            date_of_birth=(
                datetime.strptime(date_of_birth, '%Y-%m-%d').date()
                if date_of_birth else None
            ),
            gender=gender,
            phone=phone,
            address=address,
            aadhar_number=aadhar_number,
            father=(father_name, father_phone, father_email, father_occupation),
            mother=(mother_name, mother_phone, mother_email, mother_occupation),
            guardian=(
                guardian_name,
                guardian_relationship or student.guardian_relationship,
                guardian_phone,
                guardian_email,
                guardian_occupation,
            ),
        )

        perr = _apply_placement_update(
            student,
            class_id=class_id,
            academic_year_id=academic_year_id,
        )
        if perr:
            db.session.rollback()
            return {"success": False, "error": perr}

        db.session.add(student)
        db.session.commit()

        # Status transitions (active ↔ withdrawn / graduated / etc.) move
        # the row in or out of the billable count, so refresh usage.
        try:
            from modules.subscription.usage import recompute_tenant_usage

            recompute_tenant_usage(student.tenant_id)
        except Exception:
            logger.exception("recompute_tenant_usage failed after update_student")

        return {'success': True, 'student': student.to_dict()}
    except ValueError as e:
        db.session.rollback()
        return {'success': False, 'error': f'Invalid data format: {str(e)}'}
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': safe_error(e, "Failed to update student")}

def _record_edit_against_the_person(
    student, *, name, date_of_birth, gender, phone, address, aadhar_number,
    father, mother, guardian,
):
    """Send an edit of a student's record to the person and family it describes.

    A student profile carries two different kinds of fact: things true of the
    human (their date of birth, how to reach them, who their parents are) and
    things true of their studentship (roll number, house, previous school).
    Only the first kind belongs to People, and only that is forwarded here.
    """
    from modules.people.service import revise_family_member, revise_identity

    person = student.person
    if person is None:
        return

    revise_identity(
        person,
        {
            "full_name": _clean_str(name),
            "date_of_birth": date_of_birth,
            "gender": _clean_str(gender),
            "phone_number": _clean_str(phone),
            "address": _clean_str(address),
            "aadhaar_number": _clean_str(aadhar_number),
        },
    )

    father_name, father_phone, father_email, father_occupation = father
    mother_name, mother_phone, mother_email, mother_occupation = mother
    (
        guardian_name,
        guardian_relationship,
        guardian_phone,
        guardian_email,
        guardian_occupation,
    ) = guardian

    for member_name, member_relationship, member_phone, member_email, member_occupation in (
        (father_name, "father", father_phone, father_email, father_occupation),
        (mother_name, "mother", mother_phone, mother_email, mother_occupation),
        (
            guardian_name,
            guardian_relationship,
            guardian_phone,
            guardian_email,
            guardian_occupation,
        ),
    ):
        # An edit that names nobody in a role says nothing about that role. The
        # school clearing a father's phone is a correction to the father the
        # household already has, which needs his name to find him.
        if not member_name:
            member_name = _name_on_record(student, member_relationship)
            if not member_name:
                continue

        revise_family_member(
            student.tenant_id,
            student.person_id,
            relationship=member_relationship,
            name=member_name,
            phone=member_phone,
            email=member_email,
            occupation=member_occupation,
        )


def _name_on_record(student, relationship: Optional[str]) -> Optional[str]:
    """The name the student record already carries for this role, if any."""
    from modules.people.service import family_role_for

    return {
        "father": student.father_name,
        "mother": student.mother_name,
        "guardian": student.guardian_name,
    }.get(family_role_for(relationship))


def bulk_update_status(student_ids: List[str], student_status: str) -> Dict:
    """Set student_status for many students in one tenant-scoped transaction.

    Returns {success, updated, missing} where `missing` lists requested ids not
    found in the tenant. Branch-scope enforcement is the caller's responsibility
    (the route validates each id before calling).
    """
    tenant_id = get_tenant_id()
    if not tenant_id:
        return {"success": False, "error": "Tenant context required"}

    ids = [s for s in {str(i).strip() for i in (student_ids or [])} if s]
    if not ids:
        return {"success": False, "error": "No students selected"}
    if student_status not in STUDENT_STATUS_VALUES:
        return {
            "success": False,
            "error": f"Invalid status. Allowed: {', '.join(STUDENT_STATUS_VALUES)}",
        }
    # Marking a cohort as `leaving` at year end is an ordinary thing to do in
    # bulk. Withdrawing, graduating or transferring them is not: each ends a
    # placement and carries a date and a reason per student, so it goes
    # through its workflow one child at a time.
    if student_status in WORKFLOW_ONLY_STATUSES:
        return {
            "success": False,
            "error": (
                f"'{student_status}' is the outcome of a workflow, not a bulk "
                "edit. Withdraw, graduate or transfer each student so the "
                "placement is closed and the reason recorded."
            ),
        }

    try:
        students = Student.query.filter(
            Student.tenant_id == tenant_id, Student.id.in_(ids)
        ).all()
        found_ids = {s.id for s in students}
        for student in students:
            student.student_status = student_status
        db.session.commit()
        return {
            "success": True,
            "updated": len(students),
            "missing": [i for i in ids if i not in found_ids],
        }
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": safe_error(e, "Failed to update students")}


# A single request should not be able to queue unbounded deletion work. The UI
# pages at 100; this leaves generous headroom while keeping one transaction's
# footprint predictable.
MAX_BULK_DELETE = 500


def bulk_delete_students(student_ids: List[str]) -> Dict:
    """Delete many students in one tenant-scoped transaction.

    Same ordering as `delete_student` — fees first, then the student rows, then
    the backing logins — but set-based, so deleting a page of students is one
    round trip instead of one per student.

    Returns {success, deleted, missing}. Branch-scope enforcement is the
    caller's responsibility (the route validates each id before calling).
    """
    tenant_id = get_tenant_id()
    if not tenant_id:
        return {"success": False, "error": "Tenant context required"}

    ids = [s for s in {str(i).strip() for i in (student_ids or [])} if s]
    if not ids:
        return {"success": False, "error": "No students selected"}
    if len(ids) > MAX_BULK_DELETE:
        return {
            "success": False,
            "error": (
                f"Cannot delete more than {MAX_BULK_DELETE} students in one request "
                f"({len(ids)} requested)"
            ),
        }

    try:
        students = Student.query.filter(
            Student.tenant_id == tenant_id, Student.id.in_(ids)
        ).all()
        if not students:
            return {"success": True, "deleted": 0, "missing": ids}

        found_ids = [s.id for s in students]
        # (user_id, person_id) pairs: an account-less student (ADR-003) still
        # needs its person passed so any held authority can be checked.
        teardowns = [(s.user_id, s.person_id) for s in students]

        from modules.finance.models import StudentFee

        # Ahead of the student rows for the same reason as the single delete:
        # SQLAlchemy would otherwise null out student_fees.student_id, which the
        # NOT NULL constraint rejects even though the FK cascades in the DB.
        StudentFee.query.filter(
            StudentFee.tenant_id == tenant_id,
            StudentFee.student_id.in_(found_ids),
        ).delete(synchronize_session=False)

        for student in students:
            db.session.delete(student)
        db.session.flush()  # clear students.user_id before the users go

        for user_id, person_id in teardowns:
            remove_login_for_deleted_profile(
                user_id, tenant_id, "Student", person_id=person_id
            )

        db.session.commit()

        try:
            from modules.subscription.usage import recompute_tenant_usage

            # Once for the whole batch, not per student.
            recompute_tenant_usage(tenant_id)
        except Exception:
            logger.exception(
                "recompute_tenant_usage failed after bulk_delete_students"
            )

        logger.info(
            "bulk_delete_students: deleted %s student(s) for tenant=%s",
            len(found_ids),
            tenant_id,
        )
        return {
            "success": True,
            "deleted": len(found_ids),
            "missing": [i for i in ids if i not in set(found_ids)],
        }
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": safe_error(e, "Failed to delete students")}


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

        user_id = student.user_id
        person_id = student.person_id

        from modules.finance.models import StudentFee

        StudentFee.query.filter_by(
            student_id=student_id,
            tenant_id=tenant_id,
        ).delete(synchronize_session=False)

        db.session.delete(student)
        db.session.flush()  # clear the students.user_id reference before the user

        # A student is a person, not a profile on a shared login: deleting the
        # student must also remove its backing account. Otherwise an active,
        # login-capable user with the Student role but no Student row is left
        # behind (its dashboard 404s) and the email stays reserved. Same txn.
        # person_id is passed explicitly because an account-less student
        # (ADR-003) has no user row to resolve it through.
        remove_login_for_deleted_profile(
            user_id, tenant_id, "Student", person_id=person_id
        )

        db.session.commit()

        try:
            from modules.subscription.usage import recompute_tenant_usage

            recompute_tenant_usage(tenant_id)
        except Exception:
            logger.exception("recompute_tenant_usage failed after delete_student")

        return {'success': True, 'message': 'Student deleted successfully'}
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': safe_error(e, "Failed to delete student")}


# The ceiling a caller's `first` is clamped to. A list endpoint that honours an
# unbounded page size is one request away from reading a whole school.
MAX_PAGE_SIZE = 100


def cursor_values(row, sort_key: str) -> List[Any]:
    """What identifies this row's position in the current order.

    The transport makes these opaque; what they *are* is the sort key plus the
    admission number that breaks its ties, which is the only thing that can
    resume a walk exactly where it stopped.
    """
    if sort_key == "name":
        return [row.person.full_name if row.person else "", row.admission_number]
    return [row.admission_number]


def students_page(
    *,
    after: Optional[List[Any]] = None,
    offset: Optional[int] = None,
    first: int = 25,
    sort_by: str = "admission_number",
    sort_dir: str = "asc",
    restrict_class_ids: Optional[List[str]] = None,
    **filters,
):
    """One page of students, walked by key or skipped to by offset.

    **Prefer `after`.** OFFSET makes the database count past everything it
    skips, so page 300 of a fifteen-thousand-student trust costs three hundred
    times page one — and a student admitted while somebody pages shifts every
    later row, so a child is seen twice or not at all. Walking from the last
    row seen costs the same at any depth and cannot skip anyone.

    `offset` exists because a page-number UI has to be able to jump, which a
    cursor cannot express, and because it is exactly what the REST list this
    replaces already did. It is the caller's choice of a known cost, not a
    default.

    A cursor is only offered for sorts whose key cannot be null
    (`CURSORABLE_COLUMNS`); over a nullable, mutable key it would silently
    lose students.

    Returns (rows, has_more). The caller asks for one more row than it needs;
    that extra row is the whole of `hasNextPage`, with no second query.
    """
    first = max(1, min(int(first), MAX_PAGE_SIZE))

    built = _student_list_query(
        sort_by=sort_by,
        sort_dir=sort_dir,
        restrict_class_ids=restrict_class_ids,
        **filters,
    )
    if built is None:
        return [], False
    query, sort_key, is_desc = built
    query = query.options(joinedload(Student.person))

    if after:
        query = query.filter(_after_predicate(after, sort_key, is_desc))
    elif offset:
        query = query.offset(max(0, int(offset)))

    rows = query.limit(first + 1).all()
    return rows[:first], len(rows) > first


def _after_predicate(after: List[Any], sort_key: str, is_desc: bool):
    """Everything ordered strictly past the row this cursor names."""
    from sqlalchemy import tuple_

    if sort_key not in CURSORABLE_COLUMNS:
        raise ValueError(
            f"Sorting by {sort_key} cannot be paged with a cursor because the "
            "value may be empty and may change. Use offset for this sort."
        )

    if sort_key == "name":
        columns = tuple_(Person.full_name, Student.admission_number)
        # The name sort's tie-breaker is always ascending, so a descending
        # name sort is not a plain row-value comparison: it is "an earlier
        # name, or the same name and a later admission number".
        name, admission_number = after[0], after[1]
        if is_desc:
            return db.or_(
                Person.full_name < name,
                db.and_(
                    Person.full_name == name,
                    Student.admission_number > admission_number,
                ),
            )
        return columns > (name, admission_number)

    value = after[0]
    return (
        Student.admission_number < value
        if is_desc
        else Student.admission_number > value
    )


def students_matching_count(
    *,
    restrict_class_ids: Optional[List[str]] = None,
    **filters,
) -> int:
    """How many students the same filters match.

    Separate from the page on purpose: counting fifteen thousand rows is real
    work, and a client that only renders a list should not pay for a total it
    never shows. Sorting is irrelevant to a count, so it is not passed on.
    """
    built = _student_list_query(restrict_class_ids=restrict_class_ids, **filters)
    if built is None:
        return 0
    query, _sort_key, _is_desc = built
    return query.count()


def classes_by_id(class_ids):
    """Several classes in one query — for the GraphQL class loader."""
    wanted = [cid for cid in set(class_ids) if cid]
    if not wanted:
        return {}
    rows = (
        Class.query.options(joinedload(Class.grade), joinedload(Class.programme))
        .filter(Class.id.in_(wanted))
        .all()
    )
    return {row.id: row for row in rows}


def get_student_row(student_id: str):
    """One student, with the person their name lives on.

    Returns the row rather than a dict: GraphQL builds its own shape, and a
    serializer that carries every column is what the REST payload already is.
    """
    return (
        Student.query.options(joinedload(Student.person))
        .filter_by(id=student_id)
        .first()
    )


def person_id_for_student(student_id: str) -> Optional[str]:
    """The human this student is, or None when there is no such student here.

    Read off the model rather than `get_student_by_id`: the serialized student
    does not carry its own person_id, and widening it to suit one caller would
    put an internal key in every client's payload.
    """
    return (
        db.session.query(Student.person_id).filter(Student.id == student_id).scalar()
    )
