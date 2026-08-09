import logging
from datetime import datetime
from flask import g, request, Response
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
    BranchForbidden,
    assert_class_allowed,
    assert_student_allowed,
    assert_unit_allowed,
    get_allowed_unit_ids,
)
from . import services
from .class_schemas import validate_class_payload
from core.school_time import utc_now

logger = logging.getLogger(__name__)

# Permissions
PERM_READ = 'class.read'
PERM_CREATE = 'class.create'
PERM_UPDATE = 'class.update'
PERM_DELETE = 'class.delete'
PERM_CS_MANAGE = 'class_subject.manage'


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


@classes_bp.route('/', methods=['GET'])
@tenant_required
@auth_required
@require_feature('class_management')
@require_permission(PERM_READ)
def get_classes():
    """Filterable, searchable, sortable, paginated list of classes.

    ⚠️ **Kept for the Expo client only** — admin-web reads the `classes` field
    on GraphQL, and the two must not drift, which is why both go through
    `services.get_all_classes` and its one query builder.

    `client/modules/classes/services/classService.ts` and
    `client/modules/finance/services/classService.ts` both call this. Delete
    it with the Expo release that moves them, not before: it was deleted once
    on the strength of a grep that searched `client/src`, a directory this
    repo does not have.

    Returns an envelope: { items, total, page, per_page, total_pages }.
    """
    filters, err = _list_filters_from_request()
    if err:
        return err

    result = services.get_all_classes(
        page=_parse_int_param(request.args.get('page'), default=None, minimum=1),
        per_page=_parse_int_param(
            request.args.get('per_page'), default=None, minimum=1,
            maximum=services.MAX_PER_PAGE,
        ),
        **filters,
    )
    return success_response(data=result)


@classes_bp.route('/<class_id>', methods=['GET'])
@tenant_required
@auth_required
@require_feature('class_management')
@require_permission(PERM_READ)
def get_class(class_id):
    """One class with its students and teachers.

    ⚠️ **Kept for the Expo client only** (`classService.getClassDetail`) —
    admin-web reads the `class` field on GraphQL. Both read
    `services.class_detail`, so there is one reader; only the shape differs,
    and this one exists to keep a shipped app's keys.
    """
    detail = services.class_detail(class_id)
    if detail is None:
        return not_found_response('Class')
    return success_response(data=services.legacy_detail_payload(detail))


def _list_filters_from_request():
    """Filter/search/sort parsing for the class list and the CSV export.

    Returns (kwargs, error_response). `error_response` is non-None when a param
    failed validation and the caller should return it as-is.

    Branch scope is not checked here: the service refuses a unit outside the
    caller's branches however it is reached, which is what lets the same rule
    hold for the GraphQL reads that replaced this endpoint's siblings.
    """
    search_field = request.args.get('search_field', 'all')
    if search_field not in services.SEARCH_FIELDS:
        return None, validation_error_response({
            'search_field': f"must be one of: {', '.join(sorted(services.SEARCH_FIELDS))}"
        })

    sort_by = request.args.get('sort_by', 'grade')
    if sort_by not in services.SORTABLE_COLUMNS:
        return None, validation_error_response({
            'sort_by': f"must be one of: {', '.join(sorted(services.SORTABLE_COLUMNS))}"
        })

    sort_dir = request.args.get('sort_dir', 'asc')
    if sort_dir not in ('asc', 'desc'):
        return None, validation_error_response({'sort_dir': "must be 'asc' or 'desc'"})

    return dict(
        academic_year_id=request.args.get('academic_year_id') or None,
        school_unit_id=request.args.get('school_unit_id') or None,
        programme_id=request.args.get('programme_id') or None,
        grade_id=request.args.get('grade_id') or None,
        department_id=request.args.get('department_id') or None,
        search=request.args.get('search') or None,
        search_field=search_field,
        sort_by=sort_by,
        sort_dir=sort_dir,
    ), None


@classes_bp.route('/export', methods=['GET'])
@tenant_required
@auth_required
@require_feature('class_management')
@require_permission(PERM_READ)
def export_classes():
    """Export the filtered class list as CSV.

    Accepts the same filter/search/sort params as the list endpoint;
    pagination is ignored so every matching row is exported.
    """
    import csv
    from io import StringIO

    filters, err = _list_filters_from_request()
    if err:
        return err

    result = services.get_all_classes(page=None, per_page=None, **filters)

    columns = [
        ('grade_name', 'Grade'),
        ('section', 'Section'),
        ('programme_name', 'Programme'),
        ('school_unit_name', 'Branch'),
        ('medium_name', 'Medium'),
        ('department_name', 'Department'),
        ('stream', 'Stream'),
        ('teacher_name', 'Class Teacher'),
        ('student_count', 'Students'),
        ('teacher_count', 'Teachers'),
        ('academic_year', 'Academic Year'),
        ('status', 'Status'),
    ]
    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow([label for _, label in columns])
    for item in result.get('items', []):
        writer.writerow(['' if item.get(k) is None else item.get(k) for k, _ in columns])

    filename = f"classes_{utc_now().strftime('%Y%m%d')}.csv"
    return Response(
        buf.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


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

    errors = validate_class_payload(data, is_update=False)
    if errors:
        return validation_error_response(errors)

    # Branch scope: a restricted sub-admin can only create a class in an
    # allowed branch. No-op for unrestricted users.
    school_unit_id = data.get('school_unit_id') or None
    if school_unit_id:
        assert_unit_allowed(school_unit_id)

    # What this section is called, when anything calls it anything.
    #
    # `name` is a nullable legacy label; a section is named by its grade and
    # letter, which `Class.display_name` composes. Three ways in, in order of
    # how much they know:
    #
    #   grade_id     — the structured form. The grade record holds the name, so
    #                  leave `name` empty and let the label be composed.
    #   grade_level  — the older integer form, which can only say "Grade 7".
    #   name         — no grade at all, so the caller has to say something.
    #
    # Only the last requires a name. Demanding one whenever `grade_level` was
    # absent — as this did — refused every section the structured form creates,
    # which is why admin-web could not open one.
    grade_raw = data.get('grade_level')
    grade_id = data.get('grade_id') or None
    if grade_raw is not None and grade_raw != '':
        try:
            gl = int(grade_raw)
        except (TypeError, ValueError):
            return validation_error_response({'message': 'grade_level must be an integer'})
        display_name = f'Grade {gl}'
    elif grade_id:
        gl = None
        display_name = data.get('name') or ''
    else:
        gl = None
        display_name = data.get('name')
        if not display_name or not str(display_name).strip():
            return validation_error_response(
                {'message': 'name is required unless the section has a grade'}
            )

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
        department_id=data.get('department_id') or None,
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

    # Branch scope: this fans a subject offering across every section of a grade
    # tenant-wide (all branches); a branch-restricted sub-admin may not run it.
    # Fail closed. No-op for unrestricted users.
    if get_allowed_unit_ids() is not None:
        raise BranchForbidden(
            "Branch-restricted admins cannot run tenant-wide apply-subject-by-grade; "
            "contact a full admin."
        )

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
    # Branch scope: copying classes spans the whole tenant (all branches); a
    # branch-restricted sub-admin may not run it. Fail closed. No-op for
    # unrestricted users.
    if get_allowed_unit_ids() is not None:
        raise BranchForbidden(
            "Branch-restricted admins cannot run tenant-wide copy-classes; "
            "contact a full admin."
        )

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


@classes_bp.route('/<class_id>', methods=['PUT'])
@tenant_required
@auth_required
@require_feature('class_management')
@require_permission(PERM_UPDATE)
def update_class(class_id):
    """Update class details"""
    assert_class_allowed(class_id)  # branch scope (no-op if unrestricted)
    data = request.get_json() or {}

    errors = validate_class_payload(data, is_update=True)
    if errors:
        return validation_error_response(errors)

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
    for field in ('grade_id', 'programme_id', 'school_unit_id', 'medium_id', 'stream', 'department_id'):
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

    # Branch scope: a restricted sub-admin cannot touch a class outside their
    # branches, nor pull a student from another branch into a class. No-op for
    # unrestricted users.
    assert_class_allowed(class_id)
    assert_student_allowed(student_id)

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
    # Branch scope: a restricted sub-admin cannot mutate a class or student
    # outside their branches. No-op for unrestricted users.
    assert_class_allowed(class_id)
    assert_student_allowed(student_id)

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

    # Branch scope: a restricted sub-admin cannot assign a teacher to a class
    # outside their branches. No-op for unrestricted users.
    assert_class_allowed(class_id)

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
    # Branch scope: a restricted sub-admin cannot mutate a class outside their
    # branches. No-op for unrestricted users.
    assert_class_allowed(class_id)

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
