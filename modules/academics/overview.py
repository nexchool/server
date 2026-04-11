"""Academics overview API - GET /api/academics/overview."""

from modules.academics import academics_bp
from core.decorators import auth_required, tenant_required, require_plan_feature, require_permission
from core.tenant import get_tenant_id
from modules.classes.models import Class
from modules.subjects.models import Subject
from shared.helpers import success_response


@academics_bp.route("/overview", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("class_management")
@require_permission("class.read")
def get_academics_overview():
    """GET /api/academics/overview - Returns total_classes and total_subjects."""
    tenant_id = get_tenant_id()
    if not tenant_id:
        return success_response(data={"total_classes": 0, "total_subjects": 0})

    total_classes = Class.query.filter_by(tenant_id=tenant_id).count()
    total_subjects = Subject.query.filter_by(tenant_id=tenant_id).count()

    return success_response(data={"total_classes": total_classes, "total_subjects": total_subjects})
