"""
Finance API Routes

All routes require tenant_id, RBAC, and write audit logs via services.
"""

from flask import request, g

from backend.modules.finance import finance_bp
from backend.core.decorators import (
    require_permission,
    auth_required,
    tenant_required,
    require_plan_feature,
)
from backend.core.decorators.rbac import require_any_permission
from backend.shared.helpers import (
    success_response,
    error_response,
    not_found_response,
    validation_error_response,
)

# Permissions
PERM_READ = "finance.read"
PERM_COLLECT = "finance.collect"
PERM_REFUND = "finance.refund"
PERM_MANAGE = "finance.manage"

from . import services
from .services import payment_service
from .services.payment_service import list_recent_payments


# ---------- Fee Structures ----------

@finance_bp.route("/structures/available-classes", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("fees_management")
@require_any_permission(PERM_READ, PERM_MANAGE)
def get_available_classes_for_structure():
    """GET /api/finance/structures/available-classes - Classes not yet in another fee structure."""
    academic_year_id = request.args.get("academic_year_id")
    exclude_structure_id = request.args.get("exclude_structure_id")
    if not academic_year_id:
        return validation_error_response({"academic_year_id": "Required"})
    data = services.structure_service.list_available_classes_for_structure(
        academic_year_id=academic_year_id,
        exclude_structure_id=exclude_structure_id or None,
    )
    return success_response(data={"classes": data})


@finance_bp.route("/structures", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("fees_management")
@require_any_permission(PERM_READ, PERM_MANAGE)
def list_structures():
    """GET /api/finance/structures"""
    academic_year_id = request.args.get("academic_year_id")
    class_id = request.args.get("class_id")
    data = services.structure_service.list_fee_structures(
        academic_year_id=academic_year_id,
        class_id=class_id,
    )
    return success_response(data={"fee_structures": data})


@finance_bp.route("/structures", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("fees_management")
@require_permission(PERM_MANAGE)
def create_structure():
    """POST /api/finance/structures"""
    data = request.get_json() or {}
    name = data.get("name")
    academic_year_id = data.get("academic_year_id")
    due_date = data.get("due_date")
    raw_class_ids = data.get("class_ids")
    class_id = data.get("class_id")

    # Normalise class selection: allow either class_id or class_ids.
    # Empty / omitted means "all classes in this academic year".
    if isinstance(raw_class_ids, list):
        class_ids = [c for c in raw_class_ids if c]
    elif raw_class_ids:
        class_ids = [raw_class_ids]
    elif class_id:
        class_ids = [class_id]
    else:
        class_ids = []

    if not name or not academic_year_id or not due_date:
        return validation_error_response({
            "name": "Required",
            "academic_year_id": "Required",
            "due_date": "Required",
        })

    result = services.structure_service.create_fee_structure(
        academic_year_id=academic_year_id,
        name=name,
        due_date=due_date,
        class_ids=class_ids,
        components=data.get("components", []),
        user_id=g.current_user.id if g.current_user else None,
    )
    if result["success"]:
        # Auto-assign the newly created structure to all relevant students
        fee_structure = result.get("fee_structure") or {}
        structure_id = fee_structure.get("id")
        if structure_id:
            assign_result = services.student_fee_service.assign_student_fees_for_structure(
                fee_structure_id=structure_id,
                student_ids=None,
                user_id=g.current_user.id if g.current_user else None,
            )
            # Attach assignment summary but don't fail creation if assignment has an issue
            result["auto_assign"] = {
                "success": bool(assign_result.get("success")),
                "created_count": assign_result.get("created_count", 0),
                "error": assign_result.get("error"),
            }
        return success_response(data=result, message="Fee structure created", status_code=201)
    return error_response("FinanceError", result["error"], 400)


@finance_bp.route("/structures/<structure_id>", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("fees_management")
@require_any_permission(PERM_READ, PERM_MANAGE)
def get_structure(structure_id):
    """GET /api/finance/structures/<id>"""
    data = services.structure_service.get_fee_structure(structure_id)
    if not data:
        return not_found_response("Fee structure")
    return success_response(data=data)


@finance_bp.route("/structures/<structure_id>", methods=["PUT"])
@tenant_required
@auth_required
@require_plan_feature("fees_management")
@require_permission(PERM_MANAGE)
def update_structure(structure_id):
    """PUT /api/finance/structures/<id>"""
    data = request.get_json() or {}
    class_ids = data.get("class_ids")
    if isinstance(class_ids, list):
        class_ids = [c for c in class_ids if c]
    elif data.get("class_id") is not None:
        class_ids = [data["class_id"]] if data["class_id"] else []
    else:
        class_ids = None

    components = data.get("components")
    if isinstance(components, list):
        components = [
            {
                "name": str(c.get("name", "")).strip(),
                "amount": float(c.get("amount", 0)),
                "is_optional": bool(c.get("is_optional", False)),
            }
            for c in components
            if c is not None
        ]

    result = services.structure_service.update_fee_structure(
        structure_id=structure_id,
        name=data.get("name"),
        due_date=data.get("due_date"),
        class_ids=class_ids,
        components=components if isinstance(components, list) else None,
        user_id=g.current_user.id if g.current_user else None,
    )
    if result["success"]:
        if class_ids is not None:
            user_id = g.current_user.id if g.current_user else None
            removed_class_ids = result.get("removed_class_ids") or []
            if removed_class_ids:
                unassign_result = services.student_fee_service.unassign_fees_for_removed_classes(
                    fee_structure_id=structure_id,
                    class_ids=removed_class_ids,
                    user_id=user_id,
                )
                result["auto_unassign"] = {
                    "success": bool(unassign_result.get("success")),
                    "removed_count": unassign_result.get("removed_count", 0),
                }
            assign_result = services.student_fee_service.assign_student_fees_for_structure(
                fee_structure_id=structure_id,
                student_ids=None,
                user_id=user_id,
            )
            result["auto_assign"] = {
                "success": bool(assign_result.get("success")),
                "created_count": assign_result.get("created_count", 0),
            }
        return success_response(data=result)
    if "not found" in result.get("error", "").lower():
        return not_found_response("Fee structure")
    return error_response("FinanceError", result["error"], 400)


@finance_bp.route("/structures/<structure_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_plan_feature("fees_management")
@require_permission(PERM_MANAGE)
def delete_structure(structure_id):
    """DELETE /api/finance/structures/<id>"""
    result = services.structure_service.delete_fee_structure(
        structure_id=structure_id,
        user_id=g.current_user.id if g.current_user else None,
    )
    if result["success"]:
        return success_response(data=result)
    if "not found" in result.get("error", "").lower():
        return not_found_response("Fee structure")
    return error_response("FinanceError", result["error"], 400)


@finance_bp.route("/structures/<structure_id>/assign", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("fees_management")
@require_permission(PERM_MANAGE)
def assign_structure(structure_id):
    """POST /api/finance/structures/<id>/assign - Assign fee structure to students."""
    data = request.get_json() or {}
    result = services.student_fee_service.assign_student_fees_for_structure(
        fee_structure_id=structure_id,
        student_ids=data.get("student_ids"),
        user_id=g.current_user.id if g.current_user else None,
    )
    if result["success"]:
        return success_response(data=result)
    return error_response("FinanceError", result["error"], 400)


# ---------- Student Fees ----------

@finance_bp.route("/student-fees", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("fees_management")
@require_any_permission(PERM_READ, PERM_MANAGE, PERM_COLLECT)
def list_student_fees():
    """GET /api/finance/student-fees"""
    student_id = request.args.get("student_id")
    fee_structure_id = request.args.get("fee_structure_id")
    status = request.args.get("status")
    academic_year_id = request.args.get("academic_year_id")
    class_id = request.args.get("class_id")
    search = request.args.get("search")
    data = services.student_fee_service.list_student_fees(
        student_id=student_id,
        fee_structure_id=fee_structure_id,
        status=status,
        academic_year_id=academic_year_id,
        class_id=class_id,
        search=search,
    )
    return success_response(data={"student_fees": data})


@finance_bp.route("/recent-payments", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("fees_management")
@require_any_permission(PERM_READ, PERM_MANAGE, PERM_COLLECT)
def get_recent_payments():
    """GET /api/finance/recent-payments - Last 10 payments for dashboard."""
    limit = min(int(request.args.get("limit", 10)), 50)
    data = list_recent_payments(limit=limit)
    return success_response(data={"recent_payments": data})


@finance_bp.route("/student-fees/<fee_id>", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("fees_management")
@require_any_permission(PERM_READ, PERM_MANAGE, PERM_COLLECT)
def get_student_fee(fee_id):
    """GET /api/finance/student-fees/<id>"""
    data = services.student_fee_service.get_student_fee(fee_id)
    if not data:
        return not_found_response("Student fee")
    return success_response(data=data)


@finance_bp.route("/student-fees/<fee_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_plan_feature("fees_management")
@require_permission(PERM_MANAGE)
def delete_student_fee(fee_id):
    """DELETE /api/finance/student-fees/<id> - Remove a student's fee assignment if no payments."""
    from backend.modules.finance.models import StudentFee

    sf = StudentFee.query.filter_by(id=fee_id).first()
    if not sf:
        return not_found_response("Student fee")

    result = services.student_fee_service.remove_student_fee_for_structure(
        fee_structure_id=sf.fee_structure_id,
        student_id=sf.student_id,
    )
    if result["success"]:
        return success_response(data=result)
    return error_response("StudentFeeError", result["error"], 400)


# ---------- Payments ----------

@finance_bp.route("/payments", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("fees_management")
@require_any_permission(PERM_COLLECT, PERM_MANAGE)
def create_payment():
    """POST /api/finance/payments"""
    data = request.get_json() or {}
    student_fee_id = data.get("student_fee_id")
    amount = data.get("amount")
    method = data.get("method", "cash")
    allocations = data.get("allocations")  # Optional: [{item_id, amount}, ...]
    if not student_fee_id or not amount:
        return validation_error_response({"student_fee_id": "Required", "amount": "Required"})
    result = payment_service.create_payment(
        student_fee_id=student_fee_id,
        amount=amount,
        method=method,
        created_by=g.current_user.id if g.current_user else None,
        reference_number=data.get("reference_number"),
        notes=data.get("notes"),
        allocations=allocations,
    )
    if result["success"]:
        return success_response(data=result, message="Payment recorded", status_code=201)
    return error_response("PaymentError", result["error"], 400)


@finance_bp.route("/payments/<payment_id>/refund", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("fees_management")
@require_permission(PERM_REFUND)
def refund_payment(payment_id):
    """POST /api/finance/payments/<id>/refund"""
    data = request.get_json() or {}
    result = payment_service.refund_payment(
        payment_id=payment_id,
        created_by=g.current_user.id if g.current_user else None,
        notes=data.get("notes"),
    )
    if result["success"]:
        return success_response(data=result)
    if "not found" in result.get("error", "").lower():
        return not_found_response("Payment")
    return error_response("RefundError", result["error"], 400)
