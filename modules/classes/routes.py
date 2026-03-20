import logging
from flask import request
from backend.modules.classes import classes_bp
from backend.core.decorators import require_permission, auth_required, tenant_required, require_plan_feature
from backend.shared.helpers import (
    success_response,
    error_response,
    not_found_response,
    validation_error_response,
)
from . import services

logger = logging.getLogger(__name__)

# Permissions
PERM_READ = 'class.read'
PERM_CREATE = 'class.create'
PERM_UPDATE = 'class.update'
PERM_DELETE = 'class.delete'


@classes_bp.route('/', methods=['GET'])
@tenant_required
@auth_required
@require_plan_feature('class_management')
@require_permission(PERM_READ)
def get_classes():
    """List all classes"""
    academic_year_id = request.args.get('academic_year_id')
    classes = services.get_all_classes(academic_year_id=academic_year_id)
    return success_response(data=classes)


@classes_bp.route('/', methods=['POST'])
@tenant_required
@auth_required
@require_plan_feature('class_management')
@require_permission(PERM_CREATE)
def create_class():
    """Create a new class"""
    data = request.get_json() or {}
    logger.warning("[classes] POST /api/classes/ request data: %r", data)

    if not all(k in data for k in ('name', 'section')):
        return validation_error_response({'message': 'Missing required fields: name, section'})
    if not data.get('academic_year_id'):
        return validation_error_response({'message': 'academic_year_id is required'})

    result = services.create_class(
        name=data['name'],
        section=data['section'],
        academic_year_id=data['academic_year_id'],
        teacher_id=data.get('teacher_id'),
        start_date=data.get('start_date'),
        end_date=data.get('end_date'),
    )

    if result['success']:
        return success_response(data=result['class'], message='Class created successfully', status_code=201)
    logger.warning("[classes] create_class failed: %r", result.get('error'))
    details = {'raw': result.get('raw_error')} if result.get('raw_error') else None
    return error_response('CreationError', result['error'], 400, details=details)


@classes_bp.route('/meta/available-class-teachers', methods=['GET'])
@tenant_required
@auth_required
@require_plan_feature('class_management')
@require_permission(PERM_READ)
def get_available_class_teachers():
    """
    Get teachers who can be selected as class teacher (excludes those already
    class teacher of another class). Pass class_id when editing to include the
    current class's teacher in the list.
    """
    class_id = request.args.get('class_id')
    teachers = services.get_available_class_teachers(class_id=class_id)
    return success_response(data=teachers)


@classes_bp.route('/<class_id>', methods=['GET'])
@tenant_required
@auth_required
@require_plan_feature('class_management')
@require_permission(PERM_READ)
def get_class(class_id):
    """Get class details with students and teachers."""
    cls = services.get_class_detail(class_id)
    if cls:
        return success_response(data=cls)
    return not_found_response('Class')


@classes_bp.route('/<class_id>', methods=['PUT'])
@tenant_required
@auth_required
@require_plan_feature('class_management')
@require_permission(PERM_UPDATE)
def update_class(class_id):
    """Update class details"""
    data = request.get_json()
    result = services.update_class(
        class_id,
        name=data.get('name'),
        section=data.get('section'),
        academic_year_id=data.get('academic_year_id'),
        teacher_id=data.get('teacher_id'),
        start_date=data.get('start_date'),
        end_date=data.get('end_date'),
    )

    if result['success']:
        return success_response(data=result['class'], message='Class updated successfully')
    return error_response('UpdateError', result['error'], 400)


@classes_bp.route('/<class_id>', methods=['DELETE'])
@tenant_required
@auth_required
@require_plan_feature('class_management')
@require_permission(PERM_DELETE)
def delete_class(class_id):
    """Delete a class"""
    result = services.delete_class(class_id)
    if result['success']:
        return success_response(message='Class deleted successfully')
    return error_response('DeletionError', result['error'], 400)


# ── Assignment Endpoints ──────────────────────────────────────

@classes_bp.route('/<class_id>/students', methods=['POST'])
@tenant_required
@auth_required
@require_plan_feature('class_management')
@require_permission(PERM_UPDATE)
def assign_student(class_id):
    """Assign a student to a class."""
    data = request.get_json()
    student_id = data.get('student_id')
    if not student_id:
        return validation_error_response('student_id is required')

    result = services.assign_student_to_class(class_id, student_id)
    if result['success']:
        return success_response(message=result['message'])
    return error_response('AssignmentError', result['error'], 400)


@classes_bp.route('/<class_id>/students/<student_id>', methods=['DELETE'])
@tenant_required
@auth_required
@require_plan_feature('class_management')
@require_permission(PERM_UPDATE)
def remove_student(class_id, student_id):
    """Remove a student from a class."""
    result = services.remove_student_from_class(class_id, student_id)
    if result['success']:
        return success_response(message=result['message'])
    return error_response('AssignmentError', result['error'], 400)


@classes_bp.route('/<class_id>/teachers', methods=['POST'])
@tenant_required
@auth_required
@require_plan_feature('class_management')
@require_permission(PERM_UPDATE)
def assign_teacher(class_id):
    """
    Assign a teacher to a class.

    Body: { teacher_id, subject_id, is_class_teacher }
    """
    data = request.get_json() or {}
    teacher_id = data.get('teacher_id')
    subject_id = data.get('subject_id')
    is_class_teacher = data.get('is_class_teacher', False)

    if not teacher_id:
        return validation_error_response('teacher_id is required')
    if not subject_id:
        return validation_error_response('subject_id is required')

    result = services.assign_teacher_to_class(
        class_id,
        teacher_id,
        subject_id=subject_id,
        is_class_teacher=is_class_teacher,
    )
    if result['success']:
        return success_response(data=result.get('assignment'), message=result['message'])
    return error_response('AssignmentError', result['error'], 400)


@classes_bp.route('/<class_id>/teachers/<teacher_id>', methods=['DELETE'])
@tenant_required
@auth_required
@require_plan_feature('class_management')
@require_permission(PERM_UPDATE)
def remove_teacher(class_id, teacher_id):
    """Remove a teacher from a class."""
    result = services.remove_teacher_from_class(class_id, teacher_id)
    if result['success']:
        return success_response(message=result['message'])
    return error_response('AssignmentError', result['error'], 400)


@classes_bp.route('/<class_id>/unassigned-students', methods=['GET'])
@tenant_required
@auth_required
@require_plan_feature('class_management')
@require_permission(PERM_READ)
def get_unassigned_students(class_id):
    """Get students not assigned to any class."""
    students = services.get_unassigned_students(class_id)
    return success_response(data=students)


@classes_bp.route('/<class_id>/unassigned-teachers', methods=['GET'])
@tenant_required
@auth_required
@require_plan_feature('class_management')
@require_permission(PERM_READ)
def get_unassigned_teachers(class_id):
    """Get teachers not yet assigned to this class."""
    teachers = services.get_unassigned_teachers(class_id)
    return success_response(data=teachers)
