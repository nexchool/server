from flask import request, g
from backend.modules.attendance import attendance_bp
from backend.core.decorators import require_permission, auth_required, tenant_required, require_plan_feature
from backend.core.decorators.rbac import require_any_permission
from backend.shared.helpers import (
    success_response,
    error_response,
    not_found_response,
    validation_error_response,
)
from . import services

# Permissions
PERM_MARK = 'attendance.mark'
PERM_READ_SELF = 'attendance.read.self'
PERM_READ_CLASS = 'attendance.read.class'
PERM_READ_ALL = 'attendance.read.all'


@attendance_bp.route('/my-classes', methods=['GET'])
@tenant_required
@auth_required
@require_plan_feature('attendance')
@require_permission(PERM_MARK)
def get_my_classes():
    """Get classes assigned to the current teacher for attendance."""
    user_id = g.current_user.id
    classes = services.get_my_classes(user_id)
    return success_response(data=classes)


@attendance_bp.route('/mark', methods=['POST'])
@tenant_required
@auth_required
@require_plan_feature('attendance')
@require_permission(PERM_MARK)
def mark_attendance():
    """
    Mark attendance for a class on a date.

    Body:
        class_id: str
        date: str (YYYY-MM-DD)
        records: [{student_id, status, remarks?}]
    """
    data = request.get_json()

    class_id = data.get('class_id')
    date_str = data.get('date')
    records = data.get('records', [])

    if not class_id or not date_str:
        return validation_error_response('class_id and date are required')

    if not records:
        return validation_error_response('At least one attendance record is required')

    # Verify teacher is assigned to this class
    user_id = g.current_user.id
    from backend.modules.rbac.services import has_permission
    if not has_permission(user_id, 'attendance.manage'):
        allowed_class_ids = services.get_teacher_class_ids(user_id)
        if class_id not in allowed_class_ids:
            return error_response('Forbidden', 'You are not assigned to this class', 403)

    result = services.mark_attendance(
        class_id=class_id,
        date_str=date_str,
        records=records,
        marked_by_user_id=user_id,
    )

    if result['success']:
        return success_response(data=result, message=result['message'])
    return error_response('AttendanceError', result['error'], 400)


@attendance_bp.route('/class/<class_id>', methods=['GET'])
@tenant_required
@auth_required
@require_plan_feature('attendance')
@require_any_permission(PERM_READ_CLASS, PERM_READ_ALL, PERM_MARK)
def get_class_attendance(class_id):
    """
    Get attendance for a class on a specific date.

    Query: date=YYYY-MM-DD
    """
    date_str = request.args.get('date')
    if not date_str:
        return validation_error_response('date query parameter is required (YYYY-MM-DD)')

    result = services.get_attendance_by_class_date(class_id, date_str)
    if result['success']:
        return success_response(data=result['data'])
    return error_response('FetchError', result['error'], 400)


@attendance_bp.route('/student/<student_id>', methods=['GET'])
@tenant_required
@auth_required
@require_plan_feature('attendance')
@require_any_permission(PERM_READ_SELF, PERM_READ_CLASS, PERM_READ_ALL)
def get_student_attendance(student_id):
    """
    Get attendance for a student.

    Query: month=YYYY-MM (optional)
    """
    user_id = g.current_user.id
    from backend.modules.rbac.services import has_permission

    # If student reading self, verify it's their own record
    if has_permission(user_id, PERM_READ_SELF) and not has_permission(user_id, PERM_READ_ALL):
        from backend.modules.students.models import Student
        student = Student.query.get(student_id)
        if not student or student.user_id != user_id:
            if not has_permission(user_id, PERM_READ_CLASS):
                return error_response('Forbidden', 'You can only view your own attendance', 403)

    month = request.args.get('month')
    result = services.get_student_attendance(student_id, month)
    if result['success']:
        return success_response(data=result['data'])
    return error_response('FetchError', result['error'], 400)


@attendance_bp.route('/me', methods=['GET'])
@tenant_required
@auth_required
@require_plan_feature('attendance')
@require_permission(PERM_READ_SELF)
def get_my_attendance():
    """Get current user's attendance (for students)."""
    user_id = g.current_user.id
    from backend.modules.students.models import Student
    student = Student.query.filter_by(user_id=user_id).first()
    if not student:
        return not_found_response('Student profile')

    month = request.args.get('month')
    result = services.get_student_attendance(student.id, month)
    if result['success']:
        return success_response(data=result['data'])
    return error_response('FetchError', result['error'], 400)
