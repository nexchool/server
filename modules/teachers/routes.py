from flask import request, g
from backend.modules.teachers import teachers_bp
from backend.core.decorators import require_permission, auth_required, tenant_required, require_plan_feature
from backend.shared.helpers import (
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


@teachers_bp.route('/', methods=['GET'], strict_slashes=False)
@tenant_required
@auth_required
@require_plan_feature('teacher_management')
@require_permission(PERM_READ)
def list_teachers():
    """List all teachers with optional search/filter."""
    search = request.args.get('search')
    status = request.args.get('status')
    teachers = services.list_teachers(search=search, status=status)
    return success_response(data=teachers)


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
