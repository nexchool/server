"""
Academic Term Routes

REST API for AcademicTerm CRUD. Mounted under the academics blueprint at
/api/academics/terms. The model already exists in
modules.academics.backbone.models.AcademicTerm; this module just exposes it.
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from flask import g, request
from sqlalchemy.exc import IntegrityError

from core.database import db
from core.decorators import (
    auth_required,
    tenant_required,
    require_feature,
    require_permission,
    require_any_permission,
)
from shared.helpers import (
    error_response,
    not_found_response,
    success_response,
    validation_error_response,
)

from modules.academics import academics_bp
from modules.academics.backbone.models import AcademicTerm


PERM_READ = "academic_term.read"
PERM_MANAGE = "academic_term.manage"


def _clean(value):
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip()
        return v or None
    return value


def _parse_date(value: Any) -> Optional[date]:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _term_to_dict(term: AcademicTerm) -> Dict[str, Any]:
    return {
        "id": term.id,
        "academic_year_id": term.academic_year_id,
        "name": term.name,
        "code": term.code,
        "sequence": term.sequence,
        "start_date": term.start_date.isoformat() if term.start_date else None,
        "end_date": term.end_date.isoformat() if term.end_date else None,
        "is_active": term.is_active,
        "created_at": term.created_at.isoformat() if term.created_at else None,
        "updated_at": term.updated_at.isoformat() if term.updated_at else None,
    }


def _list_terms(tenant_id: str, academic_year_id: Optional[str]) -> List[Dict]:
    q = AcademicTerm.query.filter(
        AcademicTerm.tenant_id == tenant_id,
        AcademicTerm.deleted_at.is_(None),
    )
    if academic_year_id:
        q = q.filter(AcademicTerm.academic_year_id == academic_year_id)
    rows = q.order_by(AcademicTerm.sequence.asc(), AcademicTerm.name.asc()).all()
    return [_term_to_dict(t) for t in rows]


@academics_bp.route("/terms", methods=["GET"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("academics_advanced")
@require_any_permission(PERM_READ, PERM_MANAGE)
def list_academic_terms():
    return success_response(
        data=_list_terms(g.tenant_id, request.args.get("academic_year_id")),
    )


@academics_bp.route("/terms", methods=["POST"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("academics_advanced")
@require_permission(PERM_MANAGE)
def create_academic_term():
    data = request.get_json() or {}

    name = _clean(data.get("name"))
    academic_year_id = _clean(data.get("academic_year_id"))
    start = _parse_date(data.get("start_date"))
    end = _parse_date(data.get("end_date"))

    if not name:
        return validation_error_response({"message": "name is required"})
    if not academic_year_id:
        return validation_error_response({"message": "academic_year_id is required"})
    if not start:
        return validation_error_response({"message": "start_date (YYYY-MM-DD) is required"})
    if not end:
        return validation_error_response({"message": "end_date (YYYY-MM-DD) is required"})
    if end < start:
        return validation_error_response({"message": "end_date must be on or after start_date"})

    sequence = data.get("sequence")
    try:
        sequence = int(sequence) if sequence is not None else 1
    except (TypeError, ValueError):
        return validation_error_response({"message": "sequence must be an integer"})

    try:
        term = AcademicTerm(
            tenant_id=g.tenant_id,
            academic_year_id=academic_year_id,
            name=name,
            code=_clean(data.get("code")),
            sequence=sequence,
            start_date=start,
            end_date=end,
            is_active=bool(data.get("is_active", True)),
        )
        db.session.add(term)
        db.session.commit()
        return success_response(
            data=_term_to_dict(term),
            message="Term created successfully",
            status_code=201,
        )
    except IntegrityError as e:
        db.session.rollback()
        msg = str(getattr(e, "orig", e)).lower()
        if "uq_academic_terms_year_name" in msg:
            return error_response(
                "CreationError",
                "A term with this name already exists in this academic year.",
                400,
            )
        if "uq_academic_terms_year_code" in msg:
            return error_response(
                "CreationError",
                "A term with this code already exists in this academic year.",
                400,
            )
        return error_response("CreationError", "Database constraint violation", 400)
    except Exception as e:
        db.session.rollback()
        return error_response("CreationError", str(e), 400)


@academics_bp.route("/terms/<term_id>", methods=["GET"])
@tenant_required
@auth_required
@require_feature("academics_advanced")
@require_any_permission(PERM_READ, PERM_MANAGE)
def get_academic_term(term_id):
    term = AcademicTerm.query.filter(
        AcademicTerm.id == term_id,
        AcademicTerm.tenant_id == g.tenant_id,
        AcademicTerm.deleted_at.is_(None),
    ).first()
    if not term:
        return not_found_response("Term")
    return success_response(data=_term_to_dict(term))


@academics_bp.route("/terms/<term_id>", methods=["PATCH", "PUT"])
@tenant_required
@auth_required
@require_feature("academics_advanced")
@require_permission(PERM_MANAGE)
def update_academic_term(term_id):
    data = request.get_json() or {}
    term = AcademicTerm.query.filter(
        AcademicTerm.id == term_id,
        AcademicTerm.tenant_id == g.tenant_id,
        AcademicTerm.deleted_at.is_(None),
    ).first()
    if not term:
        return not_found_response("Term")

    if "name" in data:
        name = _clean(data["name"])
        if not name:
            return validation_error_response({"message": "name cannot be empty"})
        term.name = name
    if "code" in data:
        term.code = _clean(data["code"])
    if "academic_year_id" in data:
        ay = _clean(data["academic_year_id"])
        if not ay:
            return validation_error_response({"message": "academic_year_id cannot be empty"})
        term.academic_year_id = ay
    if "sequence" in data and data["sequence"] is not None:
        try:
            term.sequence = int(data["sequence"])
        except (TypeError, ValueError):
            return validation_error_response({"message": "sequence must be an integer"})
    if "start_date" in data:
        d = _parse_date(data["start_date"])
        if not d:
            return validation_error_response({"message": "start_date must be YYYY-MM-DD"})
        term.start_date = d
    if "end_date" in data:
        d = _parse_date(data["end_date"])
        if not d:
            return validation_error_response({"message": "end_date must be YYYY-MM-DD"})
        term.end_date = d
    if term.end_date < term.start_date:
        return validation_error_response({"message": "end_date must be on or after start_date"})
    if "is_active" in data and data["is_active"] is not None:
        term.is_active = bool(data["is_active"])

    try:
        db.session.commit()
        return success_response(
            data=_term_to_dict(term),
            message="Term updated successfully",
        )
    except IntegrityError as e:
        db.session.rollback()
        msg = str(getattr(e, "orig", e)).lower()
        if "uq_academic_terms_year_name" in msg:
            return error_response(
                "UpdateError",
                "A term with this name already exists in this academic year.",
                400,
            )
        if "uq_academic_terms_year_code" in msg:
            return error_response(
                "UpdateError",
                "A term with this code already exists in this academic year.",
                400,
            )
        return error_response("UpdateError", "Database constraint violation", 400)
    except Exception as e:
        db.session.rollback()
        return error_response("UpdateError", str(e), 400)


@academics_bp.route("/terms/<term_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_feature("academics_advanced")
@require_permission(PERM_MANAGE)
def delete_academic_term(term_id):
    term = AcademicTerm.query.filter(
        AcademicTerm.id == term_id,
        AcademicTerm.tenant_id == g.tenant_id,
        AcademicTerm.deleted_at.is_(None),
    ).first()
    if not term:
        return not_found_response("Term")

    try:
        # Soft-delete to keep historical references intact (mirrors the
        # `deleted_at` partial-unique pattern used elsewhere in academics).
        term.deleted_at = db.func.now()
        term.is_active = False
        db.session.commit()
        return success_response(message="Term deleted successfully")
    except Exception as e:
        db.session.rollback()
        return error_response("DeleteError", str(e), 400)

