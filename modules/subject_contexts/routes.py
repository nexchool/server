"""REST API for subject contexts — /api/subject-contexts."""

from flask import g, request

from core.decorators import (
    auth_required,
    tenant_required,
    require_feature,
    require_any_permission,
)
from shared.helpers import (
    error_response,
    not_found_response,
    success_response,
    validation_error_response,
)

from . import services, subject_contexts_bp


PERM_READ = "school_setup.read"
PERM_SETUP_MANAGE = "school_setup.manage"
PERM_CS = "class_subject.manage"


def _actor_id():
    user = getattr(g, "current_user", None)
    return getattr(user, "id", None) if user is not None else None


@subject_contexts_bp.route("/", methods=["GET"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("class_management")
@require_any_permission(PERM_READ, PERM_SETUP_MANAGE, PERM_CS)
def list_contexts():
    return success_response(
        data=services.list_contexts(
            g.tenant_id,
            programme_id=request.args.get("programme_id"),
            grade_id=request.args.get("grade_id"),
            include_inactive=request.args.get("include_inactive", "").lower()
            in ("1", "true", "yes"),
        )
    )


@subject_contexts_bp.route("/<context_id>", methods=["GET"])
@tenant_required
@auth_required
@require_feature("class_management")
@require_any_permission(PERM_READ, PERM_SETUP_MANAGE, PERM_CS)
def get_context(context_id):
    row = services.get_context(context_id, g.tenant_id)
    if not row:
        return not_found_response("Subject context")
    return success_response(data=row)


@subject_contexts_bp.route("/", methods=["POST"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("class_management")
@require_any_permission(PERM_SETUP_MANAGE, PERM_CS)
def create_context():
    data = request.get_json() or {}
    result = services.create_context(g.tenant_id, data, actor_user_id=_actor_id())
    if result["success"]:
        return success_response(
            data=result["context"],
            message="Subject context created",
            status_code=201,
        )
    return error_response("SubjectContextError", result["error"], 400)


@subject_contexts_bp.route(
    "/<context_id>", methods=["PATCH"], strict_slashes=False
)
@tenant_required
@auth_required
@require_feature("class_management")
@require_any_permission(PERM_SETUP_MANAGE, PERM_CS)
def update_context(context_id):
    data = request.get_json() or {}
    result = services.update_context(
        context_id, g.tenant_id, data, actor_user_id=_actor_id()
    )
    if result["success"]:
        return success_response(
            data=result["context"], message="Subject context updated"
        )
    if result.get("error") == "Subject context not found":
        return not_found_response("Subject context")
    return error_response("SubjectContextError", result["error"], 400)


@subject_contexts_bp.route(
    "/<context_id>", methods=["DELETE"], strict_slashes=False
)
@tenant_required
@auth_required
@require_feature("class_management")
@require_any_permission(PERM_SETUP_MANAGE, PERM_CS)
def delete_context(context_id):
    result = services.delete_context(context_id, g.tenant_id)
    if result["success"]:
        return success_response(data={}, message="Subject context deleted")
    if result.get("error") == "Subject context not found":
        return not_found_response("Subject context")
    return error_response("SubjectContextError", result["error"], 400)


@subject_contexts_bp.route(
    "/bulk-upsert", methods=["POST"], strict_slashes=False
)
@tenant_required
@auth_required
@require_feature("class_management")
@require_any_permission(PERM_SETUP_MANAGE, PERM_CS)
def bulk_upsert():
    """Replace the offering set for one (programme, grade) atomically."""
    data = request.get_json() or {}
    programme_id = data.get("programme_id")
    grade_id = data.get("grade_id")
    contexts = data.get("contexts")
    if not programme_id or not grade_id:
        return validation_error_response(
            {"message": "programme_id and grade_id are required"}
        )
    if not isinstance(contexts, list):
        return validation_error_response(
            {"message": "contexts must be an array"}
        )

    delete_missing = bool(data.get("delete_missing", True))
    result = services.bulk_upsert_contexts(
        g.tenant_id,
        programme_id,
        grade_id,
        contexts,
        delete_missing=delete_missing,
        actor_user_id=_actor_id(),
    )
    if result["success"]:
        return success_response(
            data={"contexts": result["contexts"]},
            message="Subject contexts saved",
        )
    return error_response("SubjectContextError", result["error"], 400)


@subject_contexts_bp.route("/preview", methods=["GET"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("class_management")
@require_any_permission(PERM_READ, PERM_SETUP_MANAGE, PERM_CS)
def preview():
    programme_id = request.args.get("programme_id")
    grade_id = request.args.get("grade_id")
    if not programme_id or not grade_id:
        return validation_error_response(
            {"message": "programme_id and grade_id are required"}
        )
    result = services.preview_for_grade(g.tenant_id, programme_id, grade_id)
    if result["success"]:
        return success_response(
            data={
                "class_count": result["class_count"],
                "subject_count": result["subject_count"],
                "contexts": result["contexts"],
            }
        )
    return error_response("PreviewError", result["error"], 400)


@subject_contexts_bp.route("/apply", methods=["POST"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("class_management")
@require_any_permission(PERM_SETUP_MANAGE, PERM_CS)
def apply_to_classes():
    data = request.get_json() or {}
    programme_id = data.get("programme_id")
    grade_id = data.get("grade_id")
    if not programme_id or not grade_id:
        return validation_error_response(
            {"message": "programme_id and grade_id are required"}
        )
    result = services.apply_for_grade(g.tenant_id, programme_id, grade_id)
    if result["success"]:
        return success_response(
            data={
                "created_count": result["created_count"],
                "skipped_count": result["skipped_count"],
                "classes_matched": result["classes_matched"],
            },
            message=result.get("message")
            or "Subject contexts applied to classes",
        )
    return error_response("ApplyError", result["error"], 400)
