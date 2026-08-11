from datetime import date as _date

from flask import request, g, Response
from werkzeug.utils import secure_filename
from modules.students import students_bp
from core.decorators import (
    require_permission,
    require_any_permission,
    auth_required,
    tenant_required,
    require_feature,
    require_setup_complete,
    require_active_subscription,
)
from shared.helpers import (
    success_response,
    error_response,
    not_found_response,
    unauthorized_response,
    validation_error_response,
    forbidden_response,
)
from core.branch_scope import (
    BranchForbidden,
    assert_class_allowed,
    assert_student_allowed,
    assert_unit_allowed,
    get_allowed_unit_ids,
)
from . import services
from .document_schemas import validate_document_type
from .student_schemas import validate_student_payload
from core.school_time import utc_now

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
@require_feature('timetable')
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


@students_bp.route('/', methods=['POST'], strict_slashes=False)
@tenant_required
@auth_required
@require_feature('student_management')
@require_setup_complete
@require_active_subscription
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

    # Branch scope: a restricted sub-admin can only create a student inside an
    # allowed branch. A classless student has no branch and would be invisible
    # to them, so fail closed (422). No-op for unrestricted users (classless
    # create stays allowed).
    class_id = data.get('class_id')
    if class_id:
        assert_class_allowed(class_id)
    elif get_allowed_unit_ids() is not None:
        return error_response(
            'UnprocessableEntity',
            "Branch-restricted admins must assign the student to a class in "
            "one of their branches.",
            422,
        )

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


@students_bp.route("/promotion/preview", methods=["POST"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("student_management")
@require_permission(PERM_UPDATE)
def promotion_preview():
    """
    Preview academic-year promotion: counts promoted, repeated, skipped, graduated, unmapped, blocked.
    Body: {
      from_year_id, to_year_id,
      class_mapping: { [class_id]: next_class_id | "GRADUATED" },
      exclude_leaving?: bool (default false),
      include_failed?: bool (default true; when false, skip students with academic_result fail)
    }
    """
    # Branch scope: tenant-wide promotion preview spans all branches; a
    # branch-restricted sub-admin may not run it. Fail closed. No-op for
    # unrestricted users.
    if get_allowed_unit_ids() is not None:
        raise BranchForbidden(
            "Branch-restricted admins cannot run tenant-wide promotion preview; "
            "contact a full admin."
        )

    data = request.get_json() or {}
    from_year_id = (data.get("from_year_id") or "").strip()
    to_year_id = (data.get("to_year_id") or "").strip()
    class_mapping = data.get("class_mapping")
    if not from_year_id or not to_year_id:
        return validation_error_response("from_year_id and to_year_id are required")
    if not isinstance(class_mapping, dict):
        return validation_error_response("class_mapping must be an object")

    from . import promotion_service

    ex_leave, inc_fail = promotion_service.parse_promotion_filters(data)
    result = promotion_service.preview_promotion(
        from_year_id,
        to_year_id,
        class_mapping,
        exclude_leaving=ex_leave,
        include_failed=inc_fail,
    )
    if not result.get("success"):
        return error_response("PromotionPreviewError", result.get("error", "Preview failed"), 400)
    payload = {k: v for k, v in result.items() if k != "success"}
    return success_response(data=payload)


@students_bp.route("/promote", methods=["POST"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("student_management")
@require_setup_complete
@require_active_subscription
@require_permission(PERM_UPDATE)
def promotion_execute():
    """
    Execute promotion in one transaction. Returns promotion_batch_id for audit logs.
    Optional body: exclude_leaving, include_failed (same as preview).
    """
    # Branch scope: tenant-wide promotion spans all branches; a branch-restricted
    # sub-admin may not run it. Fail closed. No-op for unrestricted users.
    if get_allowed_unit_ids() is not None:
        raise BranchForbidden(
            "Branch-restricted admins cannot run tenant-wide promotion; "
            "contact a full admin."
        )

    data = request.get_json() or {}
    from_year_id = (data.get("from_year_id") or "").strip()
    to_year_id = (data.get("to_year_id") or "").strip()
    class_mapping = data.get("class_mapping")
    if not from_year_id or not to_year_id:
        return validation_error_response("from_year_id and to_year_id are required")
    if not isinstance(class_mapping, dict):
        return validation_error_response("class_mapping must be an object")

    from . import promotion_service

    ex_leave, inc_fail = promotion_service.parse_promotion_filters(data)
    result = promotion_service.execute_promotion(
        from_year_id,
        to_year_id,
        class_mapping,
        user_id=g.current_user.id,
        exclude_leaving=ex_leave,
        include_failed=inc_fail,
    )
    if not result.get("success"):
        err_details = None
        if result.get("promotion_batch_id") or result.get("summary"):
            err_details = {
                "promotion_batch_id": result.get("promotion_batch_id"),
                "summary": result.get("summary"),
                "filters": result.get("filters"),
            }
        return error_response(
            "PromotionError",
            result.get("error", "Promotion failed"),
            400,
            details=err_details,
        )
    return success_response(
        data={
            "promotion_batch_id": result["promotion_batch_id"],
            "summary": result["summary"],
            "batch": result.get("batch"),
            "filters": result.get("filters"),
        },
        message="Promotion completed",
    )


@students_bp.route("/promotion/history", methods=["GET"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("student_management")
@require_any_permission(PERM_READ_ALL, PERM_UPDATE, PERM_MANAGE)
def promotion_history():
    """Paginated list of past StudentPromotionBatch rows for the tenant."""
    # Branch scope: promotion history is tenant-wide; a branch-restricted
    # sub-admin may not view it. Fail closed. No-op for unrestricted users.
    if get_allowed_unit_ids() is not None:
        raise BranchForbidden(
            "Branch-restricted admins cannot view tenant-wide promotion history; "
            "contact a full admin."
        )

    from .models import StudentPromotionBatch
    from modules.academics.academic_year.models import AcademicYear

    try:
        page = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = max(1, min(100, int(request.args.get("page_size", 20))))
    except (TypeError, ValueError):
        page_size = 20

    q = StudentPromotionBatch.query.filter_by(tenant_id=g.tenant_id)
    from_filter = (request.args.get("from_year_id") or "").strip()
    to_filter = (request.args.get("to_year_id") or "").strip()
    if from_filter:
        q = q.filter(StudentPromotionBatch.from_academic_year_id == from_filter)
    if to_filter:
        q = q.filter(StudentPromotionBatch.to_academic_year_id == to_filter)

    total = q.count()
    rows = (
        q.order_by(StudentPromotionBatch.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    year_ids = {r.from_academic_year_id for r in rows} | {
        r.to_academic_year_id for r in rows
    }
    year_ids.discard(None)
    name_by_year = {}
    if year_ids:
        for ay in AcademicYear.query.filter(
            AcademicYear.tenant_id == g.tenant_id,
            AcademicYear.id.in_(list(year_ids)),
        ).all():
            name_by_year[ay.id] = ay.name

    items = []
    for r in rows:
        items.append(
            {
                "id": r.id,
                "from_academic_year_id": r.from_academic_year_id,
                "from_academic_year_name": name_by_year.get(r.from_academic_year_id),
                "to_academic_year_id": r.to_academic_year_id,
                "to_academic_year_name": name_by_year.get(r.to_academic_year_id),
                "status": r.status,
                "summary": r.summary,
                "created_by_user_id": r.created_by_user_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )

    return success_response(
        data={
            "items": items,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": (total + page_size - 1) // page_size if total else 0,
            },
        }
    )


@students_bp.route('/bulk-delete', methods=['POST'], strict_slashes=False)
@tenant_required
@auth_required
@require_feature('student_management')
@require_setup_complete
@require_active_subscription
@require_permission(PERM_DELETE)
def bulk_delete_students():
    """
    Delete many students at once.

    Body: { student_ids: [str] }

    POST rather than DELETE: this is an action over a collection carrying a
    body, matching the existing /bulk-status endpoint.
    """
    data = request.get_json() or {}
    student_ids = data.get('student_ids')

    if not isinstance(student_ids, list) or not student_ids:
        return validation_error_response({'student_ids': 'a non-empty list is required'})

    # Branch scope: reject if any target student is outside a restricted
    # sub-admin's branches (403). No-op for unrestricted users.
    for sid in student_ids:
        assert_student_allowed(sid)

    result = services.bulk_delete_students(student_ids)
    if not result.get('success'):
        return error_response('BulkDeleteError', result.get('error', 'Failed'), 400)
    return success_response(
        data={'deleted': result['deleted'], 'missing': result.get('missing', [])},
        message=f"Deleted {result['deleted']} student(s)",
    )


@students_bp.route('/bulk-status', methods=['POST'], strict_slashes=False)
@tenant_required
@auth_required
@require_feature('student_management')
@require_setup_complete
@require_active_subscription
@require_permission(PERM_UPDATE)
def bulk_update_student_status():
    """
    Set student_status for many students at once.

    Body: { student_ids: [str], student_status: str }
    """
    from .student_schemas import STUDENT_STATUS_VALUES

    data = request.get_json() or {}
    student_ids = data.get('student_ids')
    student_status = (data.get('student_status') or '').strip()

    if not isinstance(student_ids, list) or not student_ids:
        return validation_error_response({'student_ids': 'a non-empty list is required'})
    if student_status not in STUDENT_STATUS_VALUES:
        return validation_error_response({
            'student_status': f"must be one of: {', '.join(STUDENT_STATUS_VALUES)}"
        })

    # Branch scope: reject if any target student is outside a restricted
    # sub-admin's branches (403). No-op for unrestricted users.
    for sid in student_ids:
        assert_student_allowed(sid)

    result = services.bulk_update_status(student_ids, student_status)
    if not result.get('success'):
        return error_response('BulkStatusError', result.get('error', 'Failed'), 400)
    return success_response(
        data={'updated': result['updated'], 'missing': result.get('missing', [])},
        message=f"Updated {result['updated']} student(s)",
    )


# ---------------------------------------------------------------------------
# Admission — asking to join, and the school's answer
# ---------------------------------------------------------------------------

def _parse_occurred_on(raw):
    """A school records these after the fact — a decision taken last week."""
    if not raw:
        return None, None
    try:
        return _date.fromisoformat(str(raw)), None
    except ValueError:
        return None, validation_error_response(
            {'occurred_on': 'must be an ISO date (YYYY-MM-DD)'}
        )


@students_bp.route('/admissions', methods=['POST'], strict_slashes=False)
@tenant_required
@auth_required
@require_feature('student_management')
@require_setup_complete
@require_active_subscription
@require_permission(PERM_CREATE)
def submit_admission_application():
    """Record an application. Creates no student — approval does that."""
    from . import admission_service

    try:
        result = admission_service.submit_application(request.get_json() or {})
    except ValueError:
        return validation_error_response({'date_of_birth': 'must be an ISO date (YYYY-MM-DD)'})
    if not result.get('success'):
        return error_response('AdmissionError', result.get('error', 'Failed'), 400)
    return success_response(data=result['application'], message='Application submitted', status_code=201)


@students_bp.route('/admissions', methods=['GET'], strict_slashes=False)
@tenant_required
@auth_required
@require_feature('student_management')
@require_any_permission(PERM_READ_ALL, PERM_MANAGE, PERM_CREATE)
def list_admission_applications():
    """Applications, decided ones included — the history the canon asks for."""
    from . import admission_service

    result = admission_service.list_applications(
        status=request.args.get('status'),
        academic_year_id=request.args.get('academic_year_id'),
        search=request.args.get('search'),
        page=request.args.get('page', 1, type=int),
        per_page=request.args.get('per_page', 20, type=int),
    )
    return success_response(data=result)


@students_bp.route('/admissions/<application_id>', methods=['GET'], strict_slashes=False)
@tenant_required
@auth_required
@require_feature('student_management')
@require_any_permission(PERM_READ_ALL, PERM_MANAGE, PERM_CREATE)
def get_admission_application(application_id):
    from . import admission_service

    result = admission_service.get_application(application_id)
    if not result.get('success'):
        return not_found_response('Application')
    return success_response(data=result['application'])


@students_bp.route('/admissions/<application_id>/review', methods=['POST'], strict_slashes=False)
@tenant_required
@auth_required
@require_feature('student_management')
@require_permission(PERM_UPDATE)
def review_admission_application(application_id):
    """The school has started checking this application."""
    from . import admission_service

    result = admission_service.start_review(application_id)
    if not result.get('success'):
        return error_response('AdmissionError', result.get('error', 'Failed'), 400)
    return success_response(data=result['application'], message='Application under review')


@students_bp.route('/admissions/<application_id>/approve', methods=['POST'], strict_slashes=False)
@tenant_required
@auth_required
@require_feature('student_management')
@require_setup_complete
@require_active_subscription
@require_permission(PERM_CREATE)
def approve_admission_application(application_id):
    """Say yes: the applicant becomes a student. Body: { class_id?, reason? }"""
    from . import admission_service

    data = request.get_json() or {}
    occurred_on, err = _parse_occurred_on(data.get('decided_on'))
    if err:
        return err

    result = admission_service.approve(
        application_id,
        class_id=(data.get('class_id') or None),
        reason=(data.get('reason') or None),
        decided_on=occurred_on,
        decided_by_user_id=g.current_user.id,
    )
    if not result.get('success'):
        return error_response('AdmissionError', result.get('error', 'Failed'), 400)
    return success_response(
        data={
            'application': result['application'],
            'student': result['student'],
            'credentials': result.get('credentials'),
        },
        message='Applicant admitted',
        status_code=201,
    )


@students_bp.route('/admissions/<application_id>/reject', methods=['POST'], strict_slashes=False)
@tenant_required
@auth_required
@require_feature('student_management')
@require_permission(PERM_UPDATE)
def reject_admission_application(application_id):
    """The school declines. Body: { reason?, decided_on? }"""
    from . import admission_service

    data = request.get_json() or {}
    occurred_on, err = _parse_occurred_on(data.get('decided_on'))
    if err:
        return err

    result = admission_service.reject(
        application_id,
        reason=(data.get('reason') or None),
        decided_on=occurred_on,
        decided_by_user_id=g.current_user.id,
    )
    if not result.get('success'):
        return error_response('AdmissionError', result.get('error', 'Failed'), 400)
    return success_response(data=result['application'], message='Application rejected')


@students_bp.route('/admissions/<application_id>/withdraw', methods=['POST'], strict_slashes=False)
@tenant_required
@auth_required
@require_feature('student_management')
@require_permission(PERM_UPDATE)
def withdraw_admission_application(application_id):
    """The family withdraws. Body: { reason?, decided_on? }"""
    from . import admission_service

    data = request.get_json() or {}
    occurred_on, err = _parse_occurred_on(data.get('decided_on'))
    if err:
        return err

    result = admission_service.withdraw(
        application_id,
        reason=(data.get('reason') or None),
        decided_on=occurred_on,
        decided_by_user_id=g.current_user.id,
    )
    if not result.get('success'):
        return error_response('AdmissionError', result.get('error', 'Failed'), 400)
    return success_response(data=result['application'], message='Application withdrawn')


# ---------------------------------------------------------------------------
# Lifecycle — the things that happen to a student, as workflows
#
# The acts themselves (withdraw, graduate, re-enroll, transfer to a section,
# transfer out) are GraphQL mutations — see `modules/students/resolvers.py`.
# Reading a student's history is still here because nothing reads it over
# GraphQL yet. A business operation lives on exactly one transport.
# ---------------------------------------------------------------------------

@students_bp.route('/<student_id>/timeline', methods=['GET'], strict_slashes=False)
@tenant_required
@auth_required
@require_feature('student_management')
@require_any_permission(PERM_READ_ALL, PERM_READ_CLASS, PERM_MANAGE)
def student_timeline_route(student_id):
    """The student's history, oldest first."""
    from . import lifecycle_service

    assert_student_allowed(student_id)
    events = lifecycle_service.timeline_for(student_id)
    return success_response(data=[event.to_dict() for event in events])


def _list_arguments_from_request(*, paginate):
    """Filter/search/sort parsing shared by the student list and its export.

    Returns (kwargs, error_response); `error_response` is non-None when a
    param failed validation. Branch scope is asserted here — naming a class or
    a campus outside a restricted sub-admin's branches is a refusal, not an
    empty page.
    """
    class_ids_param = request.args.get('class_ids')
    class_ids = (
        [c.strip() for c in class_ids_param.split(',') if c.strip()]
        if class_ids_param
        else None
    )
    class_id = request.args.get('class_id')

    search_field = request.args.get('search_field', 'all')
    if search_field not in services.SEARCH_FIELDS:
        return None, validation_error_response({
            'search_field': f"must be one of: {', '.join(sorted(services.SEARCH_FIELDS))}"
        })
    sort_by = request.args.get('sort_by', 'admission_number')
    if sort_by not in services.SORTABLE_COLUMNS:
        sort_by = 'admission_number'
    sort_dir = request.args.get('sort_dir', 'asc')
    if sort_dir not in ('asc', 'desc'):
        sort_dir = 'asc'

    school_unit_id = request.args.get('school_unit_id') or None
    if school_unit_id:
        assert_unit_allowed(school_unit_id)
    if class_id:
        assert_class_allowed(class_id)
    if class_ids:
        for cid in class_ids:
            assert_class_allowed(cid)

    return dict(
        class_id=class_id if not class_ids else None,
        class_ids=class_ids,
        academic_year_id=request.args.get('academic_year_id'),
        search=request.args.get('search'),
        search_field=search_field,
        gender=request.args.get('gender'),
        student_status=request.args.get('student_status'),
        is_transport_opted=_parse_bool_param(request.args.get('is_transport_opted')),
        admission_date_from=request.args.get('admission_date_from'),
        admission_date_to=request.args.get('admission_date_to'),
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=(
            _parse_int_param(request.args.get('page'), default=None, minimum=1)
            if paginate else None
        ),
        per_page=(
            _parse_int_param(
                request.args.get('per_page'), default=None, minimum=1, maximum=100
            )
            if paginate else None
        ),
        school_unit_id=school_unit_id,
        programme_id=request.args.get('programme_id') or None,
        grade_id=request.args.get('grade_id') or None,
    ), None


def _listed_students(*, paginate):
    """The students this caller may see, with the filters they asked for.

    A head teacher holds `student.read.all` and reads the school; a class
    teacher holds `student.read.class` and reads their own classes. Both reach
    the same list — what differs is how much of it, which is this function's
    job rather than the guard's.

    Returns (envelope, error_response).
    """
    from modules.rbac.services import has_permission

    kwargs, err = _list_arguments_from_request(paginate=paginate)
    if err:
        return None, err

    user_id = g.current_user.id
    if has_permission(user_id, PERM_READ_ALL):
        return services.list_students(**kwargs), None
    if has_permission(user_id, PERM_READ_CLASS):
        from modules.attendance.services import get_teacher_class_ids

        return services.list_students(
            _restrict_class_ids=get_teacher_class_ids(user_id), **kwargs
        ), None
    return None, unauthorized_response()


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
@require_feature('student_management')
@require_any_permission(PERM_READ_ALL, PERM_READ_CLASS)
def list_students():
    """Paginated, filterable, sortable list of students.

    ⚠️ **Kept for the Expo client only** (`client/modules/students/services/
    studentService.ts`). admin-web reads the `students` field on GraphQL, and
    both go through `_student_list_query`, so the two cannot drift.

    This route was deleted in 92ed1cf on the claim that "nothing calls
    `GET /api/students/` any more" — the mobile app did, and had done all
    along. Delete it with the Expo release that moves the app, not before.

    Returns an envelope: { items, total, page, per_page, total_pages }.
    """
    listed, err = _listed_students(paginate=True)
    if err:
        return err
    return success_response(data=listed)


@students_bp.route('/export', methods=['GET'], strict_slashes=False)
@tenant_required
@auth_required
@require_feature('student_management')
@require_any_permission(PERM_READ_ALL, PERM_READ_CLASS)
def export_students():
    """
    Export the filtered student list as CSV. Accepts the same filter/search
    query params as the list endpoint (pagination is ignored — all matching
    rows are returned).
    """
    import csv
    from io import StringIO

    listed, err = _listed_students(paginate=False)
    if err:
        return err
    result = listed

    columns = [
        ('admission_number', 'Admission Number'),
        ('name', 'Name'),
        ('email', 'Email'),
        ('class_name', 'Class'),
        ('programme_name', 'Programme'),
        ('roll_number', 'Roll Number'),
        ('gender', 'Gender'),
        ('student_status', 'Status'),
        ('guardian_name', 'Guardian Name'),
        ('guardian_phone', 'Guardian Phone'),
        ('admission_date', 'Admission Date'),
    ]
    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow([label for _, label in columns])
    for item in result.get('items', []):
        writer.writerow(['' if item.get(k) is None else item.get(k) for k, _ in columns])

    csv_text = buf.getvalue()
    filename = f"students_{utc_now().strftime('%Y%m%d')}.csv"
    return Response(
        csv_text,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


# --- Document routes: more specific paths, register before /<student_id> ---

@students_bp.route('/<student_id>/documents', methods=['GET'], strict_slashes=False)
@tenant_required
@auth_required
@require_feature('student_management')
def list_student_documents(student_id):
    """List all documents for a student. Uses same permission logic as get_student."""
    user_id = g.current_user.id
    from modules.rbac.services import has_permission

    student = services.get_student_by_id(student_id)
    if not student:
        return not_found_response('Student')

    # Branch scope: a restricted sub-admin cannot reach a student's documents
    # outside their branches (403). No-op for unrestricted users.
    assert_student_allowed(student_id)

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
@require_feature('student_management')
@require_permission(PERM_MANAGE)
def create_student_document(student_id):
    """Upload a document for a student. multipart/form-data: file, document_type."""
    student = services.get_student_by_id(student_id)
    if not student:
        return not_found_response('Student')

    # Branch scope: a restricted sub-admin cannot upload to a student outside
    # their branches (403). No-op for unrestricted users.
    assert_student_allowed(student_id)

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
@require_feature('student_management')
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

    # Branch scope: a restricted sub-admin cannot download a student's document
    # file outside their branches (403). No-op for unrestricted users.
    assert_student_allowed(student_id)

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
@require_feature('student_management')
@require_permission(PERM_MANAGE)
def delete_student_document(student_id, document_id):
    """Delete a document for a student."""
    student = services.get_student_by_id(student_id)
    if not student:
        return not_found_response('Student')

    # Branch scope: a restricted sub-admin cannot delete a document of a student
    # outside their branches (403). No-op for unrestricted users.
    assert_student_allowed(student_id)

    result = services.delete_student_document(document_id, student_id)
    if result.get('success'):
        return success_response(message='Document deleted successfully')
    return not_found_response('Document')


@students_bp.route('/<student_id>', methods=['GET'])
@tenant_required
@auth_required
@require_feature('student_management')
def get_student(student_id):
    """Get student details"""
    user_id = g.current_user.id
    from modules.rbac.services import has_permission
    
    student = services.get_student_by_id(student_id)
    if not student:
        return not_found_response('Student')

    # Branch scope: a restricted sub-admin cannot view a student outside their
    # branches (403). No-op for unrestricted users.
    assert_student_allowed(student_id)

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
@require_feature('student_management')
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
@require_feature('student_management')
@require_setup_complete
@require_active_subscription
@require_permission(PERM_UPDATE)
def update_student(student_id):
    """
    Update student details.
    
    Only updates fields that are provided in the request.
    """
    user_id = g.current_user.id
    from modules.rbac.services import has_permission as _has_perm

    data = request.get_json() or {}

    # Branch scope: a restricted sub-admin cannot update a student outside
    # their branches (403). No-op for unrestricted users.
    assert_student_allowed(student_id)

    # A restricted sub-admin cannot move a student into a class outside their
    # branches, nor un-class a student into a branch-invisible state.
    allowed_units = get_allowed_unit_ids()
    if allowed_units is not None and 'class_id' in data:
        target_class_id = data.get('class_id')
        if target_class_id:
            assert_class_allowed(target_class_id)
        else:
            return validation_error_response(
                "Branch-restricted admins must keep the student assigned to a "
                "class in one of their branches."
            )

    # If teacher (not admin), verify student is in their class
    if not _has_perm(user_id, PERM_READ_ALL):
        student = services.get_student_by_id(student_id)
        if not student:
            return not_found_response('Student')
        from modules.attendance.services import get_teacher_class_ids
        teacher_class_ids = get_teacher_class_ids(user_id)
        if student.get('class_id') not in teacher_class_ids:
            return unauthorized_response()

    err = validate_student_payload(data, is_update=True)
    if err:
        return validation_error_response(err)
    
    result = services.update_student(
        student_id,
        # The household as the form submitted it, whole. Absent means the
        # client did not edit the family; an empty list means it emptied it.
        family=data.get('family'),
        name=data.get('name'),
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
        academic_result=data.get("academic_result"),
        class_id=data["class_id"] if "class_id" in data else services.PLACEMENT_UNSET,
        academic_year_id=(
            data["academic_year_id"] if "academic_year_id" in data else services.PLACEMENT_UNSET
        ),
    )
    
    if result['success']:
        return success_response(data=result['student'], message='Student updated successfully')
    return error_response('UpdateError', result['error'], 400)

@students_bp.route('/<student_id>', methods=['DELETE'])
@tenant_required
@auth_required
@require_feature('student_management')
@require_setup_complete
@require_active_subscription
@require_permission(PERM_DELETE)
def delete_student(student_id):
    """Delete student"""
    assert_student_allowed(student_id)  # branch scope (no-op if unrestricted)
    result = services.delete_student(student_id)
    if result['success']:
        return success_response(message='Student deleted successfully')
    return error_response('DeleteError', result['error'], 400)