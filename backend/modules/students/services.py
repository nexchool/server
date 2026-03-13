from typing import List, Dict, Optional
from sqlalchemy.exc import IntegrityError
from datetime import datetime
import logging
import secrets
import string
import uuid

from backend.core.database import db
from backend.core.tenant import get_tenant_id
from backend.core.models import Tenant
from backend.modules.auth.models import User
from backend.modules.rbac.services import assign_role_to_user_by_email
from backend.modules.rbac.role_seeder import seed_roles_for_tenant
from backend.modules.classes.models import Class
from backend.shared.cloudinary_utils import destroy_cloudinary_asset, upload_to_cloudinary
from .models import Student, StudentDocument, DocumentType
from .document_schemas import validate_document_type

logger = logging.getLogger(__name__)


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
    guardian_email: Optional[str] = None
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
            guardian_email=guardian_email
        )
        student.save()

        # Auto-assign any applicable fee structures for this student's class/year
        try:
            from backend.modules.finance.services import student_fee_service

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

def list_students(
    class_id: str = None,
    class_ids: List[str] = None,
    academic_year_id: str = None,
    search: str = None,
) -> List[Dict]:
    """List students with optional filters."""
    query = Student.query.join(User)

    if class_ids:
        query = query.filter(Student.class_id.in_(class_ids))
    elif class_id:
        query = query.filter(Student.class_id == class_id)
    if academic_year_id:
        query = query.filter(Student.academic_year_id == academic_year_id)

    if search:
        search_pattern = f'%{search}%'
        query = query.filter(
            db.or_(
                User.name.ilike(search_pattern),
                User.email.ilike(search_pattern),
                Student.admission_number.ilike(search_pattern)
            )
        )
        
    # Order by class, then name
    query = query.order_by(Student.class_id, User.name)
    
    students = query.all()
    return [s.to_dict() for s in students]

def list_students_by_class_ids(
    class_ids: List[str],
    academic_year_id: str = None,
    search: str = None,
) -> List[Dict]:
    """List students filtered to specific class IDs (for teacher scoping)."""
    if not class_ids:
        return []

    query = Student.query.join(User).filter(Student.class_id.in_(class_ids))
    if academic_year_id:
        query = query.filter(Student.academic_year_id == academic_year_id)

    if search:
        search_pattern = f'%{search}%'
        query = query.filter(
            db.or_(
                User.name.ilike(search_pattern),
                User.email.ilike(search_pattern),
                Student.admission_number.ilike(search_pattern)
            )
        )

    query = query.order_by(Student.class_id, User.name)
    students = query.all()
    return [s.to_dict() for s in students]


def get_student_by_id(student_id: str) -> Optional[Dict]:
    """Get student details by ID"""
    student = Student.query.get(student_id)
    return student.to_dict() if student else None

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
    guardian_email: Optional[str] = None
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
            
        student.save()
        return {'success': True, 'student': student.to_dict()}
    except ValueError as e:
        db.session.rollback()
        return {'success': False, 'error': f'Invalid data format: {str(e)}'}
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': f'Failed to update student: {str(e)}'}

def delete_student(student_id: str) -> Dict:
    """Delete student"""
    try:
        student = Student.query.get(student_id)
        if not student:
            return {'success': False, 'error': 'Student not found'}
        student.delete()
        return {'success': True, 'message': 'Student deleted successfully'}
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': f'Failed to delete student: {str(e)}'}


# ---------------------------------------------------------------------------
# Student Documents (Cloudinary)
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
    Validate file, upload to Cloudinary, save StudentDocument. Returns doc dict or error.
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
            folder = f"school_erp/{tenant_id}/students/{student_id}/documents"
            public_id = f"{document_type}_{uuid.uuid4().hex[:12]}"
            secure_url, public_id = upload_to_cloudinary(
                stream, folder=folder, public_id=public_id
            )
        except Exception as e:
            logger.exception("Cloudinary upload failed: %s", e)
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
            cloudinary_url=secure_url,
            cloudinary_public_id=public_id,
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


def delete_student_document(document_id: str, student_id: str) -> Dict:
    """Delete document from DB and Cloudinary."""
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
            destroy_cloudinary_asset(doc.cloudinary_public_id)
        except Exception:
            pass

        db.session.delete(doc)
        db.session.commit()
        return {"success": True}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}