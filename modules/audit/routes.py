"""Audit log REST API for admin-web.

  GET  /api/audit-logs/        — paginated list with filters
  GET  /api/audit-logs/export  — xlsx download (up to 10 000 rows)
"""
from datetime import datetime, timedelta, timezone
from io import BytesIO

from flask import Blueprint, request, g, send_file

from core.decorators import (
    auth_required,
    tenant_required,
    require_permission,
)
from shared.helpers import success_response

from modules.audit.models import TenantAuditLog


audit_bp = Blueprint("audit", __name__, url_prefix="/api/audit-logs")


def _parse_int(v, default):
    try:
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _build_query(tenant_id, args):
    query = TenantAuditLog.query.filter_by(tenant_id=tenant_id)

    date_from = args.get("date_from")
    date_to = args.get("date_to")
    if date_from:
        query = query.filter(TenantAuditLog.created_at >= date_from)
    elif not date_to:
        query = query.filter(
            TenantAuditLog.created_at
            >= datetime.now(timezone.utc) - timedelta(days=30)
        )
    if date_to:
        query = query.filter(TenantAuditLog.created_at <= date_to)

    modules = args.getlist("module") if hasattr(args, "getlist") else (
        [args.get("module")] if args.get("module") else []
    )
    if modules:
        query = query.filter(TenantAuditLog.module.in_(modules))

    actions = args.getlist("action") if hasattr(args, "getlist") else (
        [args.get("action")] if args.get("action") else []
    )
    if actions:
        query = query.filter(TenantAuditLog.action.in_(actions))

    user_id = args.get("user_id")
    if user_id:
        query = query.filter(TenantAuditLog.actor_user_id == user_id)

    unit_id = args.get("unit_id")
    if unit_id:
        query = query.filter(TenantAuditLog.unit_id == unit_id)

    return query


@audit_bp.route("/", methods=["GET"], strict_slashes=False)
@tenant_required
@auth_required
@require_permission("audit_log.view")
def list_audit_logs():
    """Return paginated audit log rows for the current tenant."""
    page = max(1, _parse_int(request.args.get("page"), 1))
    page_size = min(100, max(1, _parse_int(request.args.get("page_size"), 20)))

    query = _build_query(g.tenant_id, request.args)
    total = query.count()
    rows = (
        query.order_by(TenantAuditLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    data = [
        {
            "id": r.id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "actor_user_id": r.actor_user_id,
            "actor_name": r.actor_name,
            "actor_role": r.actor_role,
            "module": r.module,
            "action": r.action,
            "resource_type": r.resource_type,
            "resource_id": r.resource_id,
            "description": r.description,
            "unit_id": r.unit_id,
            "meta": r.meta,
        }
        for r in rows
    ]

    pagination = {
        "page": page,
        "page_size": page_size,
        "total_items": total,
        "total_pages": (total + page_size - 1) // page_size if page_size else 0,
    }
    return success_response(data={"items": data, "pagination": pagination})


@audit_bp.route("/export", methods=["GET"], strict_slashes=False)
@tenant_required
@auth_required
@require_permission("audit_log.view")
def export_audit_logs():
    """Stream an xlsx file containing up to 10 000 audit log rows."""
    from openpyxl import Workbook

    query = _build_query(g.tenant_id, request.args)
    rows = (
        query.order_by(TenantAuditLog.created_at.desc())
        .limit(10_000)
        .all()
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "Audit Log"
    ws.append([
        "Timestamp",
        "User",
        "Role",
        "Module",
        "Action",
        "Resource Type",
        "Resource ID",
        "Description",
        "Unit ID",
    ])
    for r in rows:
        ws.append([
            r.created_at.isoformat() if r.created_at else "",
            r.actor_name,
            r.actor_role,
            r.module,
            r.action,
            r.resource_type,
            r.resource_id or "",
            r.description,
            r.unit_id or "",
        ])

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    return send_file(
        bio,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="audit-log.xlsx",
    )
