import logging
from flask import g, request
from modules.classes import classes_bp
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
    validation_error_response,
)
from core.branch_scope import (
    assert_class_allowed,
    assert_unit_allowed,
)
from . import services

logger = logging.getLogger(__name__)

# Permissions
PERM_READ = 'class.read'
PERM_CREATE = 'class.create'
PERM_UPDATE = 'class.update'
PERM_DELETE = 'class.delete'
PERM_CS_MANAGE = 'class_subject.manage'


@classes_bp.route('/', methods=['GET'])
@tenant_required
@auth_required
@require_feature('class_management')
@require_permission(PERM_READ)
def get_classes():
    """List classes with optional structural filters.

    Query params:
        academic_year_id, school_unit_id, programme_id, grade_id
    """
    school_unit_id = request.args.get('school_unit_id')
    # Branch scope: a restricted sub-admin may not query a unit outside their
    # branches (403). No-op for unrestricted users. The service applies the
    # branch backstop filter regardless of this param.
    if school_unit_id:
        assert_unit_allowed(school_unit_id)
    classes = services.get_all_classes(
        academic_year_id=request.args.get('academic_year_id'),
        school_unit_id=school_unit_id,
        programme_id=request.args.get('programme_id'),
        grade_id=request.args.get('grade_id'),
    )
    return success_response(data=classes)


@classes_bp.route('/', methods=['POST'])
@tenant_required
@auth_required
@require_feature('class_management')
@require_setup_complete
@require_active_subscription
@require_permission(PERM_CREATE)
def create_class():
    """Create a new class"""
    data = request.get_json() or {}
    logger.warning("[classes] POST /api/classes/ request data: %r", data)

    if not data.get('section'):
        return validation_error_response({'message': 'section is required'})
    if not data.get('academic_year_id'):
        return validation_error_response({'message': 'academic_year_id is required'})

    # Branch scope: a restricted sub-admin can only create a class in an
    # allowed branch. No-op for unrestricted users.
    school_unit_id = data.get('school_unit_id') or None
    if school_unit_id:
        assert_unit_allowed(school_unit_id)

    grade_raw = data.get('grade_level')
    if grade_raw is not None and grade_raw != '':
        try:
            gl = int(grade_raw)
        except (TypeError, ValueError):
            return validation_error_response({'message': 'grade_level must be an integer'})
        display_name = f'Grade {gl}'
    else:
        gl = None
        display_name = data.get('name')
        if not display_name or not str(display_name).strip():
            return validation_error_response({'message': 'name is required unless grade_level is set'})

    result = services.create_class(
        name=str(display_name).strip(),
        section=str(data['section']).strip(),
        academic_year_id=data['academic_year_id'],
        teacher_id=data.get('teacher_id'),
        start_date=data.get('start_date'),
        end_date=data.get('end_date'),
        grade_level=gl,
        grade_id=data.get('grade_id') or None,
        programme_id=data.get('programme_id') or None,
        school_unit_id=school_unit_id,
        medium_id=data.get('medium_id') or None,
        stream=data.get('stream') or None,
    )

    if result['success']:
        return success_response(data=result['class'], message='Class created successfully', status_code=201)
    logger.warning("[classes] create_class failed: %r", result.get('error'))
    details = {'raw': result.get('raw_error')} if result.get('raw_error') else None
    return error_response('CreationError', result['error'], 400, details=details)


@classes_bp.route('/subjects/by-grade', methods=['POST'])
@tenant_required
@auth_required
@require_feature('class_management')
@require_any_permission(PERM_CS_MANAGE, 'class.manage')
def apply_subject_by_grade():
    """
    Add a subject offering to every class section that shares the same grade (standard)
    within an academic year. Requires subject catalog entry + grade_level on classes.
    """
    from modules.academics.services.grade_subjects import apply_subject_to_grade

    data = request.get_json() or {}
    ay = data.get('academic_year_id')
    subj = data.get('subject_id')
    try:
        wl = int(data.get('weekly_periods'))
    except (TypeError, ValueError):
        return validation_error_response({'message': 'weekly_periods is required as a positive integer'})
    try:
        gl = int(data.get('grade_level'))
    except (TypeError, ValueError):
        return validation_error_response({'message': 'grade_level is required as an integer'})

    if not ay or not subj or wl <= 0:
        return validation_error_response(
            {'message': 'academic_year_id, subject_id, grade_level, and weekly_periods are required'}
        )

    r = apply_subject_to_grade(g.tenant_id, ay, gl, subj, wl, data)
    if not r['success']:
        return error_response('Error', r['error'], 400)
    return success_response(data=r, message='Subject applied to grade sections', status_code=201)


@classes_bp.route('/meta/available-class-teachers', methods=['GET'])
@tenant_required
@auth_required
@require_feature('class_management')
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


@classes_bp.route("/copy", methods=["POST"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("class_management")
@require_permission(PERM_CREATE)
def copy_classes_across_years():
    """
    Copy all classes from one academic year to another.

    Body: { "from_year_id": "...", "to_year_id": "..." }
    Returns: { class_mapping: { old_class_id: new_class_id }, created, reused_existing, ... }
    """
    data = request.get_json() or {}
    from_year_id = (data.get("from_year_id") or "").strip()
    to_year_id = (data.get("to_year_id") or "").strip()
    if not from_year_id or not to_year_id:
        return validation_error_response({"message": "from_year_id and to_year_id are required"})

    result = services.copy_classes_between_years(from_year_id, to_year_id)
    if not result.get("success"):
        return error_response("CopyError", result.get("error", "Copy failed"), 400)
    payload = {k: v for k, v in result.items() if k != "success"}
    return success_response(data=payload, message="Classes copied", status_code=201)


@classes_bp.route('/<class_id>', methods=['GET'])
@tenant_required
@auth_required
@require_feature('class_management')
@require_permission(PERM_READ)
def get_class(class_id):
    """Get class details with students and teachers."""
    assert_class_allowed(class_id)  # branch scope (no-op if unrestricted)
    cls = services.get_class_detail(class_id)
    if cls:
        return success_response(data=cls)
    return not_found_response('Class')


@classes_bp.route('/<class_id>', methods=['PUT'])
@tenant_required
@auth_required
@require_feature('class_management')
@require_permission(PERM_UPDATE)
def update_class(class_id):
    """Update class details"""
    assert_class_allowed(class_id)  # branch scope (no-op if unrestricted)
    data = request.get_json() or {}
    kw = dict(
        name=data.get('name'),
        section=data.get('section'),
        academic_year_id=data.get('academic_year_id'),
        teacher_id=data.get('teacher_id'),
        start_date=data.get('start_date'),
        end_date=data.get('end_date'),
    )
    if 'grade_level' in data:
        gv = data.get('grade_level')
        if gv is None or gv == '':
            kw['grade_level'] = None
        else:
            try:
                kw['grade_level'] = int(gv)
            except (TypeError, ValueError):
                return validation_error_response({'message': 'grade_level must be an integer'})
    # Structural fields (optional)
    for field in ('grade_id', 'programme_id', 'school_unit_id', 'medium_id', 'stream'):
        if field in data:
            kw[field] = data.get(field) or None

    # Branch scope: a restricted sub-admin cannot move a class into a branch
    # outside their scope. No-op for unrestricted users.
    if kw.get('school_unit_id'):
        assert_unit_allowed(kw['school_unit_id'])

    result = services.update_class(class_id, **kw)

    if result['success']:
        return success_response(data=result['class'], message='Class updated successfully')
    return error_response('UpdateError', result['error'], 400)


@classes_bp.route('/<class_id>', methods=['DELETE'])
@tenant_required
@auth_required
@require_feature('class_management')
@require_permission(PERM_DELETE)
def delete_class(class_id):
    """Delete a class"""
    assert_class_allowed(class_id)  # branch scope (no-op if unrestricted)
    result = services.delete_class(class_id)
    if result['success']:
        return success_response(message='Class deleted successfully')
    return error_response('DeletionError', result['error'], 400)


# ── Assignment Endpoints ──────────────────────────────────────

@classes_bp.route('/<class_id>/students', methods=['POST'])
@tenant_required
@auth_required
@require_feature('class_management')
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
@require_feature('class_management')
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
@require_feature('class_management')
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
@require_feature('class_management')
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
@require_feature('class_management')
@require_permission(PERM_READ)
def get_unassigned_students(class_id):
    """Get students not assigned to any class."""
    students = services.get_unassigned_students(class_id)
    return success_response(data=students)


@classes_bp.route('/<class_id>/unassigned-teachers', methods=['GET'])
@tenant_required
@auth_required
@require_feature('class_management')
@require_permission(PERM_READ)
def get_unassigned_teachers(class_id):
    """Get teachers not yet assigned to this class."""
    teachers = services.get_unassigned_teachers(class_id)
    return success_response(data=teachers)
