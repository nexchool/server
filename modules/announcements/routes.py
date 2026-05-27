"""HTTP routes for /api/announcements/*."""

from __future__ import annotations

from flask import g, request

from core.decorators import auth_required, require_permission
from core.tenant import tenant_required
from modules.announcements import announcements_bp, services
from modules.announcements.permissions import (
    PERM_ANNOUNCEMENT_CREATE,
    PERM_ANNOUNCEMENT_READ_ALL,
    PERM_ANNOUNCEMENT_READ_OWN,
    PERM_ANNOUNCEMENT_RECALL,
    PERM_ANNOUNCEMENT_UPDATE,
)
from shared.helpers import (
    error_response,
    success_response,
    validation_error_response,
)


# --- Mutations ---------------------------------------------------------------

@announcements_bp.route("", methods=["POST"])
@tenant_required
@auth_required
@require_permission(PERM_ANNOUNCEMENT_CREATE)
def create_announcement():
    payload = request.get_json() or {}
    try:
        a = services.create_draft(
            title=payload.get("title", ""),
            body_markdown=payload.get("body_markdown", ""),
            audience_json=payload.get("audience_json") or {},
            actor_user_id=g.current_user.id,
        )
    except services.ValidationError as e:
        return validation_error_response({"detail": str(e)})
    return success_response(data=a.to_dict(include_attachments=True), status_code=201)


@announcements_bp.route("/<announcement_id>", methods=["PATCH"])
@tenant_required
@auth_required
@require_permission(PERM_ANNOUNCEMENT_UPDATE)
def update_announcement_route(announcement_id):
    payload = request.get_json() or {}
    try:
        a = services.update_announcement(
            announcement_id,
            actor_user_id=g.current_user.id,
            title=payload.get("title"),
            body_markdown=payload.get("body_markdown"),
            audience_json=payload.get("audience_json"),
            edit_note=payload.get("edit_note"),
        )
    except services.ValidationError as e:
        return validation_error_response({"detail": str(e)})
    except services.StateError as e:
        return error_response("StateError", str(e), 409)
    return success_response(data=a.to_dict(include_attachments=True))


@announcements_bp.route("/<announcement_id>/publish", methods=["POST"])
@tenant_required
@auth_required
@require_permission(PERM_ANNOUNCEMENT_UPDATE)
def publish_route(announcement_id):
    try:
        a = services.publish(announcement_id, actor_user_id=g.current_user.id)
    except services.ValidationError as e:
        return validation_error_response({"detail": str(e)})
    except services.StateError as e:
        return error_response("StateError", str(e), 409)
    return success_response(data=a.to_dict())


@announcements_bp.route("/<announcement_id>/schedule", methods=["POST"])
@tenant_required
@auth_required
@require_permission(PERM_ANNOUNCEMENT_UPDATE)
def schedule_route(announcement_id):
    payload = request.get_json() or {}
    try:
        a = services.schedule(
            announcement_id,
            actor_user_id=g.current_user.id,
            scheduled_at=payload.get("scheduled_at", ""),
        )
    except services.ValidationError as e:
        return validation_error_response({"detail": str(e)})
    except services.StateError as e:
        return error_response("StateError", str(e), 409)
    return success_response(data=a.to_dict())


@announcements_bp.route("/<announcement_id>/unschedule", methods=["POST"])
@tenant_required
@auth_required
@require_permission(PERM_ANNOUNCEMENT_UPDATE)
def unschedule_route(announcement_id):
    try:
        a = services.unschedule(announcement_id, actor_user_id=g.current_user.id)
    except services.StateError as e:
        return error_response("StateError", str(e), 409)
    return success_response(data=a.to_dict())


@announcements_bp.route("/<announcement_id>/recall", methods=["POST"])
@tenant_required
@auth_required
@require_permission(PERM_ANNOUNCEMENT_RECALL)
def recall_route(announcement_id):
    payload = request.get_json() or {}
    try:
        a = services.recall(
            announcement_id,
            actor_user_id=g.current_user.id,
            reason=payload.get("reason", ""),
        )
    except services.StateError as e:
        return error_response("StateError", str(e), 409)
    return success_response(data=a.to_dict())


# --- Queries -----------------------------------------------------------------
# IMPORTANT: register static-path queue routes BEFORE `/<announcement_id>` to avoid
# Flask matching `inbox`, `templates`, `attachments` as announcement ids.

@announcements_bp.route("/inbox", methods=["GET"])
@tenant_required
@auth_required
@require_permission(PERM_ANNOUNCEMENT_READ_OWN)
def inbox_route():
    rows = services.inbox_for_user(g.current_user.id)
    return success_response(data=[r.to_dict() for r in rows])


@announcements_bp.route("/templates", methods=["GET"])
@tenant_required
@auth_required
@require_permission(PERM_ANNOUNCEMENT_CREATE)
def templates_route():
    return success_response(data=services.list_templates())


@announcements_bp.route("", methods=["GET"])
@tenant_required
@auth_required
@require_permission(PERM_ANNOUNCEMENT_READ_ALL)
def list_route():
    rows = services.list_for_admin(
        status=request.args.get("status"),
        search=request.args.get("search"),
    )
    return success_response(data=[r.to_dict() for r in rows])


@announcements_bp.route("/<announcement_id>", methods=["GET"])
@tenant_required
@auth_required
def get_route(announcement_id):
    try:
        a = services.get_for_user(announcement_id, g.current_user)
    except services.AuthorizationError as e:
        return error_response("AuthorizationError", str(e), 403)
    except services.ValidationError as e:
        return validation_error_response({"detail": str(e)})
    return success_response(data=a.to_dict(include_attachments=True))


@announcements_bp.route("/<announcement_id>/revisions", methods=["GET"])
@tenant_required
@auth_required
@require_permission(PERM_ANNOUNCEMENT_READ_ALL)
def revisions_route(announcement_id):
    try:
        rows = services.list_revisions(announcement_id)
    except services.ValidationError as e:
        return validation_error_response({"detail": str(e)})
    return success_response(data=rows)


@announcements_bp.route("/<announcement_id>/recipients", methods=["GET"])
@tenant_required
@auth_required
@require_permission(PERM_ANNOUNCEMENT_READ_ALL)
def recipients_route(announcement_id):
    try:
        rows = services.list_recipients(announcement_id)
    except services.ValidationError as e:
        return validation_error_response({"detail": str(e)})
    return success_response(data=rows)


# --- Attachments -------------------------------------------------------------

@announcements_bp.route("/attachments", methods=["POST"])
@tenant_required
@auth_required
@require_permission(PERM_ANNOUNCEMENT_CREATE)
def upload_attachment():
    file = request.files.get("file")
    if not file:
        return validation_error_response({"file": "Required"})
    announcement_id = request.form.get("announcement_id") or None
    try:
        att = services.create_attachment(
            actor_user_id=g.current_user.id,
            file_stream=file.stream,
            filename=file.filename or "file",
            content_type=file.content_type or "application/octet-stream",
            size_bytes=file.content_length or 0,
            announcement_id=announcement_id,
        )
    except services.ValidationError as e:
        return validation_error_response({"detail": str(e)})
    return success_response(data=att.to_dict(), status_code=201)


@announcements_bp.route("/attachments/<attachment_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_permission(PERM_ANNOUNCEMENT_UPDATE)
def delete_attachment_route(attachment_id):
    try:
        services.delete_attachment(attachment_id, actor_user_id=g.current_user.id)
    except services.ValidationError as e:
        return validation_error_response({"detail": str(e)})
    except services.AuthorizationError as e:
        return error_response("AuthorizationError", str(e), 403)
    return success_response(data=None)


@announcements_bp.route("/attachments/<attachment_id>/download", methods=["GET"])
@tenant_required
@auth_required
def download_attachment(attachment_id):
    try:
        url = services.attachment_download_url(attachment_id, g.current_user)
    except services.ValidationError as e:
        return validation_error_response({"detail": str(e)})
    except services.AuthorizationError as e:
        return error_response("AuthorizationError", str(e), 403)
    return success_response(data={"url": url})
