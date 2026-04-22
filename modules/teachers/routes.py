from flask import request, g
from modules.teachers import teachers_bp
from core.decorators import require_permission, auth_required, tenant_required, require_plan_feature
from shared.helpers import (
    success_response,
    error_response,
    not_found_response,
    validation_error_response,
    forbidden_response,
)
from . import services

# Permissions
PERM_CREATE = 'teacher.create'
PERM_READ = 'teacher.read'
PERM_UPDATE = 'teacher.update'
PERM_DELETE = 'teacher.delete'


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
@require_plan_feature('teacher_management')
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
    department = request.args.get('department')
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
        department=department,
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
@require_plan_feature('teacher_management')
@require_permission(PERM_CREATE)
def create_teacher():
    """
    Create a new teacher (admin only).

    Required: name
    Optional: email, phone, designation, department, qualification,
              specialization, experience_years, address, date_of_joining
    """
    data = request.get_json()

    if not data.get('name'):
        return validation_error_response('Name is required')

    result = services.create_teacher(
        name=data['name'],
        email=data.get('email'),
        phone=data.get('phone'),
        designation=data.get('designation'),
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
@require_plan_feature('timetable')
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
@require_plan_feature('teacher_management')
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
@require_plan_feature('teacher_management')
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
@require_plan_feature('teacher_management')
@require_permission(PERM_UPDATE)
def update_teacher(teacher_id):
    """Update teacher details."""
    data = request.get_json()

    result = services.update_teacher(
        teacher_id,
        name=data.get('name'),
        phone=data.get('phone'),
        designation=data.get('designation'),
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


@teachers_bp.route('/<teacher_id>', methods=['DELETE'])
@tenant_required
@auth_required
@require_plan_feature('teacher_management')
@require_permission(PERM_DELETE)
def delete_teacher(teacher_id):
    """Delete teacher."""
    result = services.delete_teacher(teacher_id)
    if result['success']:
        return success_response(message='Teacher deleted successfully')
    return error_response('DeleteError', result['error'], 400)
