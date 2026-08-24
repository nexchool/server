from datetime import date as _date

from flask import request, g
from modules.teachers import teachers_bp
from core.decorators import (
    require_permission,
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
    validation_error_response,
    forbidden_response,
)
from . import services
from modules.documents import rest as document_rest
from .teacher_schemas import validate_teacher_payload

# Permissions
PERM_CREATE = 'teacher.create'
PERM_READ = 'teacher.read'
PERM_UPDATE = 'teacher.update'
PERM_DELETE = 'teacher.delete'
# Filing a teacher's papers is managing the teacher, and mirrors what the
# student side asks for. Already in the RBAC catalogue.
PERM_MANAGE = 'teacher.manage'


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


@teachers_bp.route('/', methods=['GET'], strict_slashes=False)
@tenant_required
@auth_required
@require_feature('teacher_management')
@require_permission(PERM_READ)
def list_teachers():
    """
    Paginated, filterable, sortable list of teachers.

    Returns an envelope: { items, total, page, per_page, total_pages }.
    """
    # Search
    search = request.args.get('search')
    search_field = request.args.get('search_field', 'all')
    if search_field not in services.SEARCH_FIELDS:
        return validation_error_response({
            'search_field': f"must be one of: {', '.join(sorted(services.SEARCH_FIELDS))}"
        })

    # Filters
    status = request.args.get('status')
    department_id = request.args.get('department_id')
    designation = request.args.get('designation')
    date_of_joining_from = request.args.get('date_of_joining_from')
    date_of_joining_to = request.args.get('date_of_joining_to')

    # Sorting
    sort_by = request.args.get('sort_by', 'employee_id')
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

    result = services.list_teachers(
        search=search,
        search_field=search_field,
        status=status,
        department_id=department_id,
        designation=designation,
        date_of_joining_from=date_of_joining_from,
        date_of_joining_to=date_of_joining_to,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        per_page=per_page,
    )
    return success_response(data=result)


@teachers_bp.route('/', methods=['POST'], strict_slashes=False)
@tenant_required
@auth_required
@require_feature('teacher_management')
@require_setup_complete
@require_active_subscription
@require_permission(PERM_CREATE)
def create_teacher():
    """
    Create a new teacher (admin only).

    Required: name
    Optional: email, phone, designation, department_id, department (legacy
              free-text name, resolved case-insensitively; department_id
              wins if both are given), qualification, specialization,
              experience_years, address, date_of_joining
    """
    data = request.get_json() or {}

    errors = validate_teacher_payload(data, is_update=False)
    if errors:
        return validation_error_response(errors)

    result = services.create_teacher(
        name=data['name'],
        email=data.get('email'),
        phone=data.get('phone'),
        designation=data.get('designation'),
        department_id=data.get('department_id'),
        department=data.get('department'),
        qualification=data.get('qualification'),
        specialization=data.get('specialization'),
        experience_years=data.get('experience_years'),
        address=data.get('address'),
        date_of_joining=data.get('date_of_joining'),
    )

    if result['success']:
        response_data = {'teacher': result['teacher']}
        if result.get('credentials'):
            response_data['credentials'] = result['credentials']
        return success_response(data=response_data, message='Teacher created successfully', status_code=201)

    # Plan limit enforcement returns 403
    if "limit" in result.get("error", "").lower():
        return forbidden_response(result["error"])
    return error_response('CreationError', result['error'], 400)


@teachers_bp.route('/me/today-schedule', methods=['GET'])
@tenant_required
@auth_required
@require_feature('timetable')
@require_permission('timetable.read')
def get_my_today_schedule():
    """Today's teaching slots from active timetable entries (v2)."""
    from modules.academics.services.dashboards import teacher_today_schedule

    r = teacher_today_schedule(g.tenant_id, g.current_user.id)
    if not r['success']:
        return error_response('Error', r.get('error', 'Failed'), 400)
    return success_response(data=r)


@teachers_bp.route('/<teacher_id>', methods=['GET'])
@tenant_required
@auth_required
@require_feature('teacher_management')
@require_permission(PERM_READ)
def get_teacher(teacher_id):
    """Get teacher details."""
    teacher = services.get_teacher_by_id(teacher_id)
    if teacher:
        return success_response(data=teacher)
    return not_found_response('Teacher')


@teachers_bp.route('/me', methods=['GET'])
@tenant_required
@auth_required
@require_feature('teacher_management')
def get_my_teacher_profile():
    """Get current user's teacher profile."""
    user_id = g.current_user.id
    teacher = services.get_teacher_by_user_id(user_id)
    if teacher:
        return success_response(data=teacher)
    return not_found_response('Teacher profile')


@teachers_bp.route('/<teacher_id>', methods=['PUT'])
@tenant_required
@auth_required
@require_feature('teacher_management')
@require_permission(PERM_UPDATE)
def update_teacher(teacher_id):
    """Update teacher details."""
    data = request.get_json() or {}

    errors = validate_teacher_payload(data, is_update=True)
    if errors:
        return validation_error_response(errors)

    result = services.update_teacher(
        teacher_id,
        name=data.get('name'),
        phone=data.get('phone'),
        designation=data.get('designation'),
        # `data.get('department_id', services.NOT_PROVIDED)` — not
        # `data.get('department_id')` — so an omitted key (leave department
        # unchanged) stays distinguishable from an explicit `null` (clear
        # it); both collapse to plain `None` under a two-argument `.get()`.
        department_id=data.get('department_id', services.NOT_PROVIDED),
        department=data.get('department'),
        qualification=data.get('qualification'),
        specialization=data.get('specialization'),
        experience_years=data.get('experience_years'),
        address=data.get('address'),
        date_of_joining=data.get('date_of_joining'),
        status=data.get('status'),
    )

    if result['success']:
        return success_response(data=result['teacher'], message='Teacher updated successfully')
    return error_response('UpdateError', result['error'], 400)


@teachers_bp.route('/bulk-status', methods=['POST'], strict_slashes=False)
@tenant_required
@auth_required
@require_feature('teacher_management')
@require_permission(PERM_UPDATE)
def bulk_update_teacher_status():
    """
    Set status for many teachers at once.

    Body: { teacher_ids: [str], status: str }
    """
    from .teacher_schemas import TEACHER_STATUS_VALUES

    data = request.get_json() or {}
    teacher_ids = data.get('teacher_ids')
    status = (data.get('status') or '').strip()

    if not isinstance(teacher_ids, list) or not teacher_ids:
        return validation_error_response({'teacher_ids': 'a non-empty list is required'})
    if status not in TEACHER_STATUS_VALUES:
        return validation_error_response({
            'status': f"must be one of: {', '.join(TEACHER_STATUS_VALUES)}"
        })

    result = services.bulk_update_teacher_status(teacher_ids, status)
    if not result.get('success'):
        return error_response('BulkStatusError', result.get('error', 'Failed'), 400)
    return success_response(
        data={'updated': result['updated'], 'missing': result.get('missing', [])},
        message=f"Updated {result['updated']} teacher(s)",
    )


@teachers_bp.route('/bulk-delete', methods=['POST'], strict_slashes=False)
@tenant_required
@auth_required
@require_feature('teacher_management')
@require_permission(PERM_DELETE)
def bulk_delete_teachers():
    """
    Delete many teachers at once.

    Body: { teacher_ids: [str] }

    POST rather than DELETE: the action carries a body, matching /bulk-status
    and the students module.
    """
    data = request.get_json() or {}
    teacher_ids = data.get('teacher_ids')

    if not isinstance(teacher_ids, list) or not teacher_ids:
        return validation_error_response({'teacher_ids': 'a non-empty list is required'})

    result = services.bulk_delete_teachers(teacher_ids)
    if not result.get('success'):
        return error_response('BulkDeleteError', result.get('error', 'Failed'), 400)
    return success_response(
        data={'deleted': result['deleted'], 'missing': result.get('missing', [])},
        message=f"Deleted {result['deleted']} teacher(s)",
    )


@teachers_bp.route('/<teacher_id>', methods=['DELETE'])
@tenant_required
@auth_required
@require_feature('teacher_management')
@require_permission(PERM_DELETE)
def delete_teacher(teacher_id):
    """Delete teacher."""
    result = services.delete_teacher(teacher_id)
    if result['success']:
        return success_response(message='Teacher deleted successfully')
    return error_response('DeleteError', result['error'], 400)


# ---------------------------------------------------------------------------
# Employment lifecycle — a teacher is an employed person (ADR-005)
# ---------------------------------------------------------------------------

def _teacher_employment(teacher_id):
    """The employment behind a teacher, or an error response."""
    from .models import Teacher

    teacher = Teacher.query.filter_by(id=teacher_id).first()
    if teacher is None or teacher.staff_id is None:
        return None, not_found_response('Teacher')
    return teacher.staff_id, None


def _parse_day(raw):
    if not raw:
        return None, None
    try:
        return _date.fromisoformat(str(raw)), None
    except ValueError:
        return None, validation_error_response(
            {'last_working_day': 'must be an ISO date (YYYY-MM-DD)'}
        )


def _separation_route(teacher_id, action, message):
    from modules.people import separation

    staff_id, err = _teacher_employment(teacher_id)
    if err:
        return err

    data = request.get_json() or {}
    last_day, parse_err = _parse_day(data.get('last_working_day'))
    if parse_err:
        return parse_err

    result = getattr(separation, action)(
        staff_id,
        last_working_day=last_day,
        reason=(data.get('reason') or None),
        recorded_by_user_id=g.current_user.id,
    )
    if not result.get('success'):
        return error_response('EmploymentError', result.get('error', 'Failed'), 400)
    return success_response(data=result, message=message)


@teachers_bp.route('/<teacher_id>/resign', methods=['POST'], strict_slashes=False)
@tenant_required
@auth_required
@require_feature('teacher_management')
@require_permission(PERM_UPDATE)
def resign_teacher(teacher_id):
    """They leave of their own accord. Body: { last_working_day?, reason? }"""
    return _separation_route(teacher_id, 'resign', 'Resignation recorded')


@teachers_bp.route('/<teacher_id>/retire', methods=['POST'], strict_slashes=False)
@tenant_required
@auth_required
@require_feature('teacher_management')
@require_permission(PERM_UPDATE)
def retire_teacher(teacher_id):
    """A career here ends. Body: { last_working_day?, reason? }"""
    return _separation_route(teacher_id, 'retire', 'Retirement recorded')


@teachers_bp.route('/<teacher_id>/terminate', methods=['POST'], strict_slashes=False)
@tenant_required
@auth_required
@require_feature('teacher_management')
@require_permission(PERM_UPDATE)
def terminate_teacher(teacher_id):
    """The organization ends the employment. Body: { last_working_day?, reason? }"""
    return _separation_route(teacher_id, 'terminate', 'Termination recorded')


@teachers_bp.route('/<teacher_id>/rejoin', methods=['POST'], strict_slashes=False)
@tenant_required
@auth_required
@require_feature('teacher_management')
@require_permission(PERM_UPDATE)
def rejoin_teacher(teacher_id):
    """A former colleague returns — a new period, the same employee."""
    from modules.people import separation

    staff_id, err = _teacher_employment(teacher_id)
    if err:
        return err

    data = request.get_json() or {}
    joined_on, parse_err = _parse_day(data.get('joined_on'))
    if parse_err:
        return parse_err

    result = separation.rejoin(
        staff_id,
        joined_on=joined_on,
        designation=(data.get('designation') or None),
        department_id=(data.get('department_id') or None),
        reason=(data.get('reason') or None),
        recorded_by_user_id=g.current_user.id,
    )
    if not result.get('success'):
        return error_response('EmploymentError', result.get('error', 'Failed'), 400)
    return success_response(data=result, message='Rejoining recorded')


@teachers_bp.route('/<teacher_id>/employment-timeline', methods=['GET'], strict_slashes=False)
@tenant_required
@auth_required
@require_feature('teacher_management')
@require_permission(PERM_READ)
def teacher_employment_timeline(teacher_id):
    """Their employment history, oldest first."""
    from modules.people import separation

    staff_id, err = _teacher_employment(teacher_id)
    if err:
        return err
    events = separation.employment_timeline(staff_id)
    return success_response(data=[event.to_dict() for event in events])


# ---------------------------------------------------------------------------
# Documents — bytes only. Listing, the type catalogue and deletion are GraphQL
# (ADR-015); what is left here is a multipart upload and an authenticated
# download, which are infrastructure.
# ---------------------------------------------------------------------------

@teachers_bp.route('/<teacher_id>/documents', methods=['POST'], strict_slashes=False)
@tenant_required
@auth_required
@require_feature('teacher_management')
@require_permission(PERM_MANAGE)
def upload_teacher_document(teacher_id):
    """Upload a document for a teacher. multipart/form-data: file, document_type."""
    person_id = services.person_id_for_teacher(teacher_id)
    if not person_id:
        return not_found_response('Teacher')

    body, status = document_rest.upload_for_person(person_id)
    return body, status


@teachers_bp.route(
    '/<teacher_id>/documents/<document_id>/file',
    methods=['GET'],
    strict_slashes=False,
)
@tenant_required
@auth_required
@require_feature('teacher_management')
@require_permission(PERM_READ)
def get_teacher_document_file(teacher_id, document_id):
    """Stream a document's bytes. Not a shareable URL — needs the usual headers."""
    person_id = services.person_id_for_teacher(teacher_id)
    if not person_id:
        return not_found_response('Teacher')

    return document_rest.stream_document(person_id, document_id)
