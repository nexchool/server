from flask import request, g, Response
from werkzeug.utils import secure_filename
from modules.students import students_bp
from core.decorators import (
    require_permission,
    require_any_permission,
    auth_required,
    tenant_required,
    require_plan_feature,
)
from shared.helpers import (
    success_response,
    error_response,
    not_found_response,
    unauthorized_response,
    validation_error_response,
    forbidden_response,
)
from . import services
from .document_schemas import validate_document_type
from .student_schemas import validate_student_payload

# Permissions
PERM_CREATE = 'student.create'
PERM_READ_ALL = 'student.read.all'
PERM_READ_CLASS = 'student.read.class'
PERM_READ_SELF = 'student.read.self'
PERM_UPDATE = 'student.update'
PERM_DELETE = 'student.delete'
PERM_MANAGE = 'student.manage'


@students_bp.route('/me/dashboard', methods=['GET'])
@tenant_required
@auth_required
@require_plan_feature('timetable')
@require_any_permission(PERM_READ_SELF, PERM_MANAGE, 'academics.read')
def student_me_dashboard():
    """Student home: today's slots, weekly preview, attendance summary (v2 sessions)."""
    from modules.academics.services.dashboards import student_dashboard

    r = student_dashboard(g.tenant_id, g.current_user.id)
    if not r['success']:
        return error_response('Error', r.get('error', 'Failed'), 400)
    return success_response(data=r)


_TRUTHY = ('1', 'true', 'yes', 'on')
_FALSY = ('0', 'false', 'no', 'off')


def _parse_bool_param(raw):
    if raw is None:
        return None
    v = raw.strip().lower()
    if v in _TRUTHY:
        return True
    if v in _FALSY:
        return False
    return None


def _parse_int_param(raw, default=None, minimum=None, maximum=None):
    if raw is None or raw == '':
        return default
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return default
    if minimum is not None and val < minimum:
        val = minimum
    if maximum is not None and val > maximum:
        val = maximum
    return val


@students_bp.route('/', methods=['GET'], strict_slashes=False)
@tenant_required
@auth_required
@require_plan_feature('student_management')
def list_students():
    """
    Paginated, filterable, sortable list of students.

    Returns an envelope: { items, total, page, per_page, total_pages }.
    """
    user_id = g.current_user.id
    from modules.rbac.services import has_permission

    # Filters
    class_id = request.args.get('class_id')
    class_ids_param = request.args.get('class_ids')
    class_ids = (
        [c.strip() for c in class_ids_param.split(',') if c.strip()]
        if class_ids_param
        else None
    )
    academic_year_id = request.args.get('academic_year_id')
    gender = request.args.get('gender')
    student_status = request.args.get('student_status')
    is_transport_opted = _parse_bool_param(request.args.get('is_transport_opted'))
    admission_date_from = request.args.get('admission_date_from')
    admission_date_to = request.args.get('admission_date_to')

    # Search
    search = request.args.get('search')
    search_field = request.args.get('search_field', 'all')
    if search_field not in services.SEARCH_FIELDS:
        return validation_error_response({
            'search_field': f"must be one of: {', '.join(sorted(services.SEARCH_FIELDS))}"
        })

    # Sorting
    sort_by = request.args.get('sort_by', 'admission_number')
    sort_dir = request.args.get('sort_dir', 'asc')
    if sort_by not in services.SORTABLE_COLUMNS:
        return validation_error_response({
            'sort_by': f"must be one of: {', '.join(sorted(services.SORTABLE_COLUMNS))}"
        })
    if sort_dir not in ('asc', 'desc'):
        return validation_error_response({'sort_dir': "must be 'asc' or 'desc'"})

    # Pagination
    page = _parse_int_param(request.args.get('page'), default=None, minimum=1)
    per_page = _parse_int_param(
        request.args.get('per_page'), default=None, minimum=1, maximum=100
    )

    include_transport_summary = request.args.get('include_transport_summary', '').lower() in _TRUTHY

    common_kwargs = dict(
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
        page=page,
        per_page=per_page,
        include_transport_summary=include_transport_summary,
    )

    if has_permission(user_id, PERM_READ_ALL):
        result = services.list_students(
            class_id=class_id if not class_ids else None,
            class_ids=class_ids,
            **common_kwargs,
        )
        return success_response(data=result)

    if has_permission(user_id, PERM_READ_CLASS):
        from modules.attendance.services import get_teacher_class_ids
        teacher_class_ids = get_teacher_class_ids(user_id)
        result = services.list_students(
            class_id=class_id if not class_ids else None,
            class_ids=class_ids,
            _restrict_class_ids=teacher_class_ids,
            **common_kwargs,
        )
        return success_response(data=result)

    return unauthorized_response()

@students_bp.route('/', methods=['POST'], strict_slashes=False)
@tenant_required
@auth_required
@require_plan_feature('student_management')
@require_permission(PERM_CREATE)
def create_student():
    """
    Create a new student.
    
    Required fields:
        - name: Full name
        - academic_year: Academic year (e.g., "2025-2026")
        - guardian_name: Guardian's full name
        - guardian_relationship: Relationship to student
        - guardian_phone: Guardian's phone number
        
    Optional fields:
        - email: Student's email (creates login credentials if provided)
        - phone: Student's phone number
        - date_of_birth: Date in YYYY-MM-DD format
        - gender: Gender (Male/Female/Other)
        - class_id: Class UUID
        - roll_number: Roll number in class
        - address: Physical address
        - guardian_email: Guardian's email
        
    Returns:
        201: Student created with credentials if email provided
        400: Validation error
    """
    data = request.get_json() or {}

    err = validate_student_payload(data, is_update=False)
    if err:
        return validation_error_response(err)
    
    # Validate required fields (academic_year_id or class_id - academic year derived from class)
    required = ['name', 'guardian_name', 'guardian_relationship', 'guardian_phone']
    missing = [field for field in required if not data.get(field)]
    if missing:
        return validation_error_response(f"Missing required fields: {', '.join(missing)}")
    if not data.get('academic_year_id') and not data.get('class_id'):
        return validation_error_response("academic_year_id or class_id is required")

    # Call service
    result = services.create_student(
        name=data['name'],
        academic_year_id=data.get('academic_year_id'),
        guardian_name=data['guardian_name'],
        guardian_relationship=data['guardian_relationship'],
        guardian_phone=data['guardian_phone'],
        email=data.get('email'),
        phone=data.get('phone'),
        date_of_birth=data.get('date_of_birth'),
        gender=data.get('gender'),
        class_id=data.get('class_id'),
        roll_number=data.get('roll_number'),
        address=data.get('address'),
        guardian_email=data.get('guardian_email'),
        # Extended fields
        blood_group=data.get("blood_group"),
        height_cm=data.get("height_cm"),
        weight_kg=data.get("weight_kg"),
        medical_allergies=data.get("medical_allergies"),
        medical_conditions=data.get("medical_conditions"),
        disability_details=data.get("disability_details"),
        identification_marks=data.get("identification_marks"),

        father_name=data.get("father_name"),
        father_phone=data.get("father_phone"),
        father_email=data.get("father_email"),
        father_occupation=data.get("father_occupation"),
        father_annual_income=data.get("father_annual_income"),

        mother_name=data.get("mother_name"),
        mother_phone=data.get("mother_phone"),
        mother_email=data.get("mother_email"),
        mother_occupation=data.get("mother_occupation"),
        mother_annual_income=data.get("mother_annual_income"),

        guardian_address=data.get("guardian_address"),
        guardian_occupation=data.get("guardian_occupation"),
        guardian_aadhar_number=data.get("guardian_aadhar_number"),

        aadhar_number=data.get("aadhar_number"),
        apaar_id=data.get("apaar_id"),
        emis_number=data.get("emis_number"),
        udise_student_id=data.get("udise_student_id"),
        religion=data.get("religion"),
        category=data.get("category"),
        caste=data.get("caste"),
        nationality=data.get("nationality"),
        mother_tongue=data.get("mother_tongue"),
        place_of_birth=data.get("place_of_birth"),

        current_address=data.get("current_address"),
        current_city=data.get("current_city"),
        current_state=data.get("current_state"),
        current_pincode=data.get("current_pincode"),

        permanent_address=data.get("permanent_address"),
        permanent_city=data.get("permanent_city"),
        permanent_state=data.get("permanent_state"),
        permanent_pincode=data.get("permanent_pincode"),

        is_same_as_permanent_address=data.get("is_same_as_permanent_address"),
        is_commuting_from_outstation=data.get("is_commuting_from_outstation"),
        commute_location=data.get("commute_location"),
        commute_notes=data.get("commute_notes"),

        emergency_contact_name=data.get("emergency_contact_name"),
        emergency_contact_relationship=data.get("emergency_contact_relationship"),
        emergency_contact_phone=data.get("emergency_contact_phone"),
        emergency_contact_alt_phone=data.get("emergency_contact_alt_phone"),

        admission_date=data.get("admission_date"),
        previous_school_name=data.get("previous_school_name"),
        previous_school_class=data.get("previous_school_class"),
        last_school_board=data.get("last_school_board"),
        tc_number=data.get("tc_number"),
        house_name=data.get("house_name"),
        student_status=data.get("student_status"),
    )

    if result['success']:
        response_data = {
            'student': result['student']
        }

        response_data['credentials'] = result.get('credentials', {})
        # Send credentials email via notification dispatcher (only when email/credentials were created)
        user_id = result.get('student', {}).get('user_id')
        if user_id and result.get('credentials'):
            from modules.notifications.services import notification_dispatcher
            from modules.notifications.enums import NotificationChannel

            notification_dispatcher.dispatch(
                user_id=user_id,
                tenant_id=g.tenant_id,
                notification_type="STUDENT_CREDENTIALS",
                channels=[
                    NotificationChannel.EMAIL.value,
                    NotificationChannel.PUSH.value,
                ],
                title="Welcome to the school",
                body=None,
                extra_data={
                    "username": result.get('credentials', {}).get('username', ''),
                    "password": result.get('credentials', {}).get('password', ''),
                    "admission_number": result.get('student', {}).get('admission_number', ''),
                },
            )
        
        return success_response(
            data=response_data,
            message='Student created successfully',
            status_code=201
        )

    # Plan limit enforcement returns 403
    if "limit" in result.get("error", "").lower():
        return forbidden_response(result["error"])
    return error_response('CreationError', result['error'], 400)

# --- Document routes: more specific paths, register before /<student_id> ---

@students_bp.route('/<student_id>/documents', methods=['GET'], strict_slashes=False)
@tenant_required
@auth_required
@require_plan_feature('student_management')
def list_student_documents(student_id):
    """List all documents for a student. Uses same permission logic as get_student."""
    user_id = g.current_user.id
    from modules.rbac.services import has_permission

    student = services.get_student_by_id(student_id)
    if not student:
        return not_found_response('Student')

    # RBAC: same as get_student
    if has_permission(user_id, PERM_READ_ALL):
        result = services.list_student_documents(student_id)
        if not result.get("success"):
            return not_found_response("Student")
        return success_response(data=result["documents"])
    if has_permission(user_id, PERM_READ_SELF) and student.get("user_id") == user_id:
        result = services.list_student_documents(student_id)
        if not result.get("success"):
            return not_found_response("Student")
        return success_response(data=result["documents"])
    if has_permission(user_id, PERM_READ_CLASS):
        from modules.attendance.services import get_teacher_class_ids
        teacher_class_ids = get_teacher_class_ids(user_id)
        if student.get("class_id") in teacher_class_ids:
            result = services.list_student_documents(student_id)
            if not result.get("success"):
                return not_found_response("Student")
            return success_response(data=result["documents"])

    return unauthorized_response()


@students_bp.route('/<student_id>/documents', methods=['POST'], strict_slashes=False)
@tenant_required
@auth_required
@require_plan_feature('student_management')
@require_permission(PERM_MANAGE)
def create_student_document(student_id):
    """Upload a document for a student. multipart/form-data: file, document_type."""
    student = services.get_student_by_id(student_id)
    if not student:
        return not_found_response('Student')

    file = request.files.get('file') or request.files.get('document')
    document_type_str = request.form.get('document_type')

    if not file or file.filename == '':
        return error_response('ValidationError', 'File is required', 400)
    err = validate_document_type(document_type_str)
    if err:
        return error_response('ValidationError', err, 400)

    # Normalize to enum value (lowercase) so DB receives "aadhar_card" not "AADHAR_CARD"
    document_type_normalized = document_type_str.strip().lower()

    result = services.create_student_document(
        student_id=student_id,
        file_obj=file,
        filename=file.filename or "document",
        document_type=document_type_normalized,
        user_id=g.current_user.id,
    )
    if result['success']:
        return success_response(
            data=result['document'],
            message='Document uploaded successfully',
            status_code=201,
        )
    # Map service error_code to API contract
    err_code = result.get('error_code', 'ValidationError')
    err_msg = result.get('error', 'Upload failed')
    if err_code == 'FileTooLarge':
        return error_response('FileTooLarge', err_msg, 400)
    if err_code == 'UnsupportedFileType':
        return error_response('UnsupportedFileType', err_msg, 400)
    if err_code == 'StorageError':
        return error_response('StorageError', err_msg, 503)
    return error_response(err_code, err_msg, 400)


@students_bp.route(
    '/<student_id>/documents/<document_id>/file',
    methods=['GET'],
    strict_slashes=False,
)
@tenant_required
@auth_required
@require_plan_feature('student_management')
def get_student_document_file(student_id, document_id):
    """
    Stream document bytes from S3. Requires same read access as listing documents.
    Not a shareable URL — must send Authorization (and tenant) like other API calls.
    """
    user_id = g.current_user.id
    from modules.rbac.services import has_permission

    student = services.get_student_by_id(student_id)
    if not student:
        return not_found_response('Student')

    allowed = False
    if has_permission(user_id, PERM_READ_ALL):
        allowed = True
    elif has_permission(user_id, PERM_READ_SELF) and student.get("user_id") == user_id:
        allowed = True
    elif has_permission(user_id, PERM_READ_CLASS):
        from modules.attendance.services import get_teacher_class_ids
        teacher_class_ids = get_teacher_class_ids(user_id)
        if student.get("class_id") in teacher_class_ids:
            allowed = True

    if not allowed:
        return unauthorized_response()

    result = services.get_student_document_file_content(document_id, student_id)
    if not result.get("success"):
        return not_found_response('Document')

    data = result["data"]
    mime = result["mime_type"]
    filename = result["filename"]
    safe = secure_filename(filename) or "document"

    return Response(
        data,
        mimetype=mime,
        headers={
            "Content-Disposition": f'inline; filename="{safe}"',
            "Cache-Control": "private, no-store, max-age=0",
            "X-Content-Type-Options": "nosniff",
        },
    )


@students_bp.route('/<student_id>/documents/<document_id>', methods=['DELETE'], strict_slashes=False)
@tenant_required
@auth_required
@require_plan_feature('student_management')
@require_permission(PERM_MANAGE)
def delete_student_document(student_id, document_id):
    """Delete a document for a student."""
    student = services.get_student_by_id(student_id)
    if not student:
        return not_found_response('Student')
    result = services.delete_student_document(document_id, student_id)
    if result.get('success'):
        return success_response(message='Document deleted successfully')
    return not_found_response('Document')


@students_bp.route('/<student_id>', methods=['GET'])
@tenant_required
@auth_required
@require_plan_feature('student_management')
def get_student(student_id):
    """Get student details"""
    user_id = g.current_user.id
    from modules.rbac.services import has_permission
    
    student = services.get_student_by_id(student_id)
    if not student:
        return not_found_response('Student')
        
    # RBAC Checks
    # 1. Admin/Staff
    if has_permission(user_id, PERM_READ_ALL):
        services.attach_transport_to_student_dict(student, student_id, user_id)
        return success_response(data=student)
        
    # 2. Self (Student)
    if has_permission(user_id, PERM_READ_SELF):
        # Check if the requested student is the current user
        if student['user_id'] == user_id:
            services.attach_transport_to_student_dict(student, student_id, user_id)
            return success_response(data=student)
            
    # 3. Teacher (Class) — only if student is in one of teacher's assigned classes
    if has_permission(user_id, PERM_READ_CLASS):
        from modules.attendance.services import get_teacher_class_ids
        teacher_class_ids = get_teacher_class_ids(user_id)
        if student.get('class_id') in teacher_class_ids:
            services.attach_transport_to_student_dict(student, student_id, user_id)
            return success_response(data=student)
        
    return unauthorized_response()

@students_bp.route('/me', methods=['GET'])
@tenant_required
@auth_required
@require_plan_feature('student_management')
def get_my_student_profile():
    """Get current user's student profile"""
    user_id = g.current_user.id
    student = services.get_student_by_user_id(user_id)
    
    if student:
        services.attach_transport_to_student_dict(student, student["id"], user_id)
        return success_response(data=student)
    return not_found_response('Student profile')

@students_bp.route('/<student_id>', methods=['PUT'])
@tenant_required
@auth_required
@require_plan_feature('student_management')
@require_permission(PERM_UPDATE)
def update_student(student_id):
    """
    Update student details.
    
    Only updates fields that are provided in the request.
    """
    user_id = g.current_user.id
    from modules.rbac.services import has_permission as _has_perm

    # If teacher (not admin), verify student is in their class
    if not _has_perm(user_id, PERM_READ_ALL):
        student = services.get_student_by_id(student_id)
        if not student:
            return not_found_response('Student')
        from modules.attendance.services import get_teacher_class_ids
        teacher_class_ids = get_teacher_class_ids(user_id)
        if student.get('class_id') not in teacher_class_ids:
            return unauthorized_response()

    data = request.get_json() or {}

    err = validate_student_payload(data, is_update=True)
    if err:
        return validation_error_response(err)
    
    result = services.update_student(
        student_id,
        name=data.get('name'),
        academic_year_id=data.get('academic_year_id'),
        class_id=data.get('class_id'),
        roll_number=data.get('roll_number'),
        date_of_birth=data.get('date_of_birth'),
        gender=data.get('gender'),
        phone=data.get('phone'),
        address=data.get('address'),
        guardian_name=data.get('guardian_name'),
        guardian_relationship=data.get('guardian_relationship'),
        guardian_phone=data.get('guardian_phone'),
        guardian_email=data.get('guardian_email'),
        # Extended fields
        blood_group=data.get("blood_group"),
        height_cm=data.get("height_cm"),
        weight_kg=data.get("weight_kg"),
        medical_allergies=data.get("medical_allergies"),
        medical_conditions=data.get("medical_conditions"),
        disability_details=data.get("disability_details"),
        identification_marks=data.get("identification_marks"),

        father_name=data.get("father_name"),
        father_phone=data.get("father_phone"),
        father_email=data.get("father_email"),
        father_occupation=data.get("father_occupation"),
        father_annual_income=data.get("father_annual_income"),

        mother_name=data.get("mother_name"),
        mother_phone=data.get("mother_phone"),
        mother_email=data.get("mother_email"),
        mother_occupation=data.get("mother_occupation"),
        mother_annual_income=data.get("mother_annual_income"),

        guardian_address=data.get("guardian_address"),
        guardian_occupation=data.get("guardian_occupation"),
        guardian_aadhar_number=data.get("guardian_aadhar_number"),

        aadhar_number=data.get("aadhar_number"),
        apaar_id=data.get("apaar_id"),
        emis_number=data.get("emis_number"),
        udise_student_id=data.get("udise_student_id"),
        religion=data.get("religion"),
        category=data.get("category"),
        caste=data.get("caste"),
        nationality=data.get("nationality"),
        mother_tongue=data.get("mother_tongue"),
        place_of_birth=data.get("place_of_birth"),

        current_address=data.get("current_address"),
        current_city=data.get("current_city"),
        current_state=data.get("current_state"),
        current_pincode=data.get("current_pincode"),

        permanent_address=data.get("permanent_address"),
        permanent_city=data.get("permanent_city"),
        permanent_state=data.get("permanent_state"),
        permanent_pincode=data.get("permanent_pincode"),

        is_same_as_permanent_address=data.get("is_same_as_permanent_address"),
        is_commuting_from_outstation=data.get("is_commuting_from_outstation"),
        commute_location=data.get("commute_location"),
        commute_notes=data.get("commute_notes"),

        emergency_contact_name=data.get("emergency_contact_name"),
        emergency_contact_relationship=data.get("emergency_contact_relationship"),
        emergency_contact_phone=data.get("emergency_contact_phone"),
        emergency_contact_alt_phone=data.get("emergency_contact_alt_phone"),

        admission_date=data.get("admission_date"),
        previous_school_name=data.get("previous_school_name"),
        previous_school_class=data.get("previous_school_class"),
        last_school_board=data.get("last_school_board"),
        tc_number=data.get("tc_number"),
        house_name=data.get("house_name"),
        student_status=data.get("student_status"),
    )
    
    if result['success']:
        return success_response(data=result['student'], message='Student updated successfully')
    return error_response('UpdateError', result['error'], 400)

@students_bp.route('/<student_id>', methods=['DELETE'])
@tenant_required
@auth_required
@require_plan_feature('student_management')
@require_permission(PERM_DELETE)
def delete_student(student_id):
    """Delete student"""
    result = services.delete_student(student_id)
    if result['success']:
        return success_response(message='Student deleted successfully')
    return error_response('DeleteError', result['error'], 400)