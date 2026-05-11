"""Hostel API routes.

All routes:
- Tenant-scoped via `@tenant_required` (g.tenant_id).
- Authenticated via `@auth_required` (g.current_user).
- Gated by `@require_feature("hostel")` so super-admin can toggle the
  module per tenant.
- RBAC-gated by permissions defined in `modules.hostel.permissions`.

Mounted at `/api/hostel` (see app.register_blueprints).
"""

from __future__ import annotations

from datetime import datetime

from flask import g, request

from core.database import db
from core.decorators import auth_required, require_feature, tenant_required
from core.decorators.rbac import require_any_permission, require_permission
from modules.hostel import hostel_bp
from modules.hostel.models import (
    Hostel,
    HostelAllocation,
    HostelBed,
    HostelRoom,
)
from modules.hostel.permissions import (
    HOSTEL_ALLOC_MANAGE,
    HOSTEL_ALLOC_READ,
    HOSTEL_MANAGE,
    HOSTEL_READ,
)
from modules.hostel.services import AllocationService
from shared.helpers import (
    error_response,
    not_found_response,
    success_response,
    validation_error_response,
)


# ============================================================================
# Helpers
# ============================================================================

def _tenant_id() -> str:
    return g.tenant_id


def _parse_datetime(value, field_name: str) -> datetime:
    """Parse ISO-8601 datetime string. Raises ValueError on bad input."""
    if isinstance(value, datetime):
        return value
    if not value or not isinstance(value, str):
        raise ValueError(f"{field_name} is required (ISO 8601 datetime)")
    # Accept "...Z" by converting to "+00:00"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid ISO 8601 datetime") from exc


# ============================================================================
# HOSTELS
# ============================================================================

@hostel_bp.route("/hostels", methods=["GET"])
@tenant_required
@auth_required
@require_feature("hostel")
@require_any_permission(HOSTEL_READ, HOSTEL_MANAGE)
def list_hostels():
    """GET /api/hostel/hostels — list active hostels in the tenant."""
    rows = (
        db.session.query(Hostel)
        .filter(Hostel.tenant_id == _tenant_id(), Hostel.deleted_at.is_(None))
        .order_by(Hostel.name)
        .all()
    )
    return success_response(data={"hostels": [h.to_dict() for h in rows]})


@hostel_bp.route("/hostels/<string:hostel_id>", methods=["GET"])
@tenant_required
@auth_required
@require_feature("hostel")
@require_any_permission(HOSTEL_READ, HOSTEL_MANAGE)
def get_hostel(hostel_id: str):
    """GET /api/hostel/hostels/:id"""
    hostel = (
        db.session.query(Hostel)
        .filter(
            Hostel.id == hostel_id,
            Hostel.tenant_id == _tenant_id(),
            Hostel.deleted_at.is_(None),
        )
        .first()
    )
    if hostel is None:
        return not_found_response("Hostel")
    return success_response(data={"hostel": hostel.to_dict()})


@hostel_bp.route("/hostels", methods=["POST"])
@tenant_required
@auth_required
@require_feature("hostel")
@require_permission(HOSTEL_MANAGE)
def create_hostel():
    """POST /api/hostel/hostels"""
    payload = request.get_json() or {}
    name = (payload.get("name") or "").strip()
    capacity = payload.get("capacity")

    errors = {}
    if not name:
        errors["name"] = "Required"
    if not isinstance(capacity, int) or capacity <= 0:
        errors["capacity"] = "Must be a positive integer"
    if errors:
        return validation_error_response(errors)

    hostel = Hostel(
        tenant_id=_tenant_id(),
        name=name,
        warden_name=payload.get("warden_name"),
        warden_phone=payload.get("warden_phone"),
        address=payload.get("address"),
        capacity=capacity,
        status=payload.get("status", "active"),
    )
    db.session.add(hostel)
    db.session.commit()
    return success_response(data={"hostel": hostel.to_dict()}, status_code=201)


@hostel_bp.route("/hostels/<string:hostel_id>", methods=["PATCH"])
@tenant_required
@auth_required
@require_feature("hostel")
@require_permission(HOSTEL_MANAGE)
def update_hostel(hostel_id: str):
    """PATCH /api/hostel/hostels/:id — partial update."""
    hostel = (
        db.session.query(Hostel)
        .filter(
            Hostel.id == hostel_id,
            Hostel.tenant_id == _tenant_id(),
            Hostel.deleted_at.is_(None),
        )
        .first()
    )
    if hostel is None:
        return not_found_response("Hostel")

    payload = request.get_json() or {}
    for field in ("name", "warden_name", "warden_phone", "address", "status"):
        if field in payload:
            setattr(hostel, field, payload[field])
    if "capacity" in payload:
        capacity = payload["capacity"]
        if not isinstance(capacity, int) or capacity <= 0:
            return validation_error_response({"capacity": "Must be a positive integer"})
        hostel.capacity = capacity

    db.session.commit()
    return success_response(data={"hostel": hostel.to_dict()})


@hostel_bp.route("/hostels/<string:hostel_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_feature("hostel")
@require_permission(HOSTEL_MANAGE)
def delete_hostel(hostel_id: str):
    """DELETE /api/hostel/hostels/:id — soft delete."""
    hostel = (
        db.session.query(Hostel)
        .filter(
            Hostel.id == hostel_id,
            Hostel.tenant_id == _tenant_id(),
            Hostel.deleted_at.is_(None),
        )
        .first()
    )
    if hostel is None:
        return not_found_response("Hostel")
    hostel.deleted_at = datetime.utcnow()
    db.session.commit()
    return success_response(data=None, status_code=204)


# ============================================================================
# ROOMS
# ============================================================================

@hostel_bp.route("/hostels/<string:hostel_id>/rooms", methods=["GET"])
@tenant_required
@auth_required
@require_feature("hostel")
@require_any_permission(HOSTEL_READ, HOSTEL_MANAGE)
def list_rooms(hostel_id: str):
    """GET /api/hostel/hostels/:id/rooms"""
    rows = (
        db.session.query(HostelRoom)
        .filter(
            HostelRoom.tenant_id == _tenant_id(),
            HostelRoom.hostel_id == hostel_id,
            HostelRoom.deleted_at.is_(None),
        )
        .order_by(HostelRoom.room_number)
        .all()
    )
    return success_response(data={"rooms": [r.to_dict() for r in rows]})


@hostel_bp.route("/rooms/<string:room_id>", methods=["GET"])
@tenant_required
@auth_required
@require_feature("hostel")
@require_any_permission(HOSTEL_READ, HOSTEL_MANAGE)
def get_room(room_id: str):
    """GET /api/hostel/rooms/:id — includes beds and current occupants."""
    room = (
        db.session.query(HostelRoom)
        .filter(
            HostelRoom.id == room_id,
            HostelRoom.tenant_id == _tenant_id(),
            HostelRoom.deleted_at.is_(None),
        )
        .first()
    )
    if room is None:
        return not_found_response("Room")

    beds = (
        db.session.query(HostelBed)
        .filter(HostelBed.room_id == room.id, HostelBed.deleted_at.is_(None))
        .order_by(HostelBed.bed_number)
        .all()
    )

    return success_response(
        data={
            "room": room.to_dict(),
            "beds": [b.to_dict() for b in beds],
        }
    )


@hostel_bp.route("/rooms", methods=["POST"])
@tenant_required
@auth_required
@require_feature("hostel")
@require_permission(HOSTEL_MANAGE)
def create_room():
    """POST /api/hostel/rooms"""
    payload = request.get_json() or {}
    hostel_id = payload.get("hostel_id")
    room_number = (payload.get("room_number") or "").strip()
    capacity = payload.get("capacity")

    errors = {}
    if not hostel_id:
        errors["hostel_id"] = "Required"
    if not room_number:
        errors["room_number"] = "Required"
    if not isinstance(capacity, int) or capacity <= 0:
        errors["capacity"] = "Must be a positive integer"
    if errors:
        return validation_error_response(errors)

    # Hostel must exist in this tenant
    parent = (
        db.session.query(Hostel)
        .filter(
            Hostel.id == hostel_id,
            Hostel.tenant_id == _tenant_id(),
            Hostel.deleted_at.is_(None),
        )
        .first()
    )
    if parent is None:
        return not_found_response("Hostel")

    room = HostelRoom(
        tenant_id=_tenant_id(),
        hostel_id=hostel_id,
        room_number=room_number,
        capacity=capacity,
        status=payload.get("status", "active"),
    )
    db.session.add(room)
    db.session.commit()
    return success_response(data={"room": room.to_dict()}, status_code=201)


@hostel_bp.route("/rooms/<string:room_id>", methods=["PATCH"])
@tenant_required
@auth_required
@require_feature("hostel")
@require_permission(HOSTEL_MANAGE)
def update_room(room_id: str):
    """PATCH /api/hostel/rooms/:id"""
    room = (
        db.session.query(HostelRoom)
        .filter(
            HostelRoom.id == room_id,
            HostelRoom.tenant_id == _tenant_id(),
            HostelRoom.deleted_at.is_(None),
        )
        .first()
    )
    if room is None:
        return not_found_response("Room")

    payload = request.get_json() or {}
    if "room_number" in payload:
        room.room_number = payload["room_number"]
    if "status" in payload:
        room.status = payload["status"]
    if "capacity" in payload:
        capacity = payload["capacity"]
        if not isinstance(capacity, int) or capacity <= 0:
            return validation_error_response({"capacity": "Must be a positive integer"})
        room.capacity = capacity

    db.session.commit()
    return success_response(data={"room": room.to_dict()})


@hostel_bp.route("/rooms/<string:room_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_feature("hostel")
@require_permission(HOSTEL_MANAGE)
def delete_room(room_id: str):
    """DELETE /api/hostel/rooms/:id — soft delete."""
    room = (
        db.session.query(HostelRoom)
        .filter(
            HostelRoom.id == room_id,
            HostelRoom.tenant_id == _tenant_id(),
            HostelRoom.deleted_at.is_(None),
        )
        .first()
    )
    if room is None:
        return not_found_response("Room")
    room.deleted_at = datetime.utcnow()
    db.session.commit()
    return success_response(data=None, status_code=204)


# ============================================================================
# BEDS
# ============================================================================

@hostel_bp.route("/beds", methods=["POST"])
@tenant_required
@auth_required
@require_feature("hostel")
@require_permission(HOSTEL_MANAGE)
def create_bed():
    """POST /api/hostel/beds"""
    payload = request.get_json() or {}
    room_id = payload.get("room_id")
    bed_number = (payload.get("bed_number") or "").strip()

    errors = {}
    if not room_id:
        errors["room_id"] = "Required"
    if not bed_number:
        errors["bed_number"] = "Required"
    if errors:
        return validation_error_response(errors)

    parent_room = (
        db.session.query(HostelRoom)
        .filter(
            HostelRoom.id == room_id,
            HostelRoom.tenant_id == _tenant_id(),
            HostelRoom.deleted_at.is_(None),
        )
        .first()
    )
    if parent_room is None:
        return not_found_response("Room")

    bed = HostelBed(
        tenant_id=_tenant_id(),
        room_id=room_id,
        bed_number=bed_number,
        status=payload.get("status", "active"),
    )
    db.session.add(bed)
    db.session.commit()
    return success_response(data={"bed": bed.to_dict()}, status_code=201)


@hostel_bp.route("/beds/<string:bed_id>", methods=["PATCH"])
@tenant_required
@auth_required
@require_feature("hostel")
@require_permission(HOSTEL_MANAGE)
def update_bed(bed_id: str):
    """PATCH /api/hostel/beds/:id — bed_number, status."""
    bed = (
        db.session.query(HostelBed)
        .filter(
            HostelBed.id == bed_id,
            HostelBed.tenant_id == _tenant_id(),
        )
        .first()
    )
    if bed is None:
        return not_found_response("Bed")

    payload = request.get_json() or {}
    if "bed_number" in payload:
        bed.bed_number = payload["bed_number"]
    if "status" in payload:
        bed.status = payload["status"]

    db.session.commit()
    return success_response(data={"bed": bed.to_dict()})


@hostel_bp.route("/beds/<string:bed_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_feature("hostel")
@require_permission(HOSTEL_MANAGE)
def delete_bed(bed_id: str):
    """DELETE /api/hostel/beds/:id — sets status=removed (no soft delete column)."""
    bed = (
        db.session.query(HostelBed)
        .filter(
            HostelBed.id == bed_id,
            HostelBed.tenant_id == _tenant_id(),
        )
        .first()
    )
    if bed is None:
        return not_found_response("Bed")

    if bed.is_allocated:
        return error_response(
            error="BedInUse",
            message="Cannot delete a bed that is currently allocated. Check out the student first.",
            status_code=409,
        )

    bed.status = "removed"
    db.session.commit()
    return success_response(data=None, status_code=204)


# ============================================================================
# ALLOCATIONS
# ============================================================================

@hostel_bp.route("/allocations", methods=["GET"])
@tenant_required
@auth_required
@require_feature("hostel")
@require_any_permission(HOSTEL_ALLOC_READ, HOSTEL_ALLOC_MANAGE)
def list_allocations():
    """GET /api/hostel/allocations — filters: hostel_id, room_id, student_id,
    status, academic_year_id."""
    service = AllocationService(db.session)
    rows = service.list_allocations(
        tenant_id=_tenant_id(),
        hostel_id=request.args.get("hostel_id") or None,
        room_id=request.args.get("room_id") or None,
        student_id=request.args.get("student_id") or None,
        status=request.args.get("status") or None,
        academic_year_id=request.args.get("academic_year_id") or None,
    )
    return success_response(data={"allocations": [a.to_dict() for a in rows]})


@hostel_bp.route("/students/<string:student_id>/allocation", methods=["GET"])
@tenant_required
@auth_required
@require_feature("hostel")
@require_any_permission(HOSTEL_ALLOC_READ, HOSTEL_ALLOC_MANAGE)
def get_student_allocation(student_id: str):
    """GET /api/hostel/students/:id/allocation — current active allocation for student."""
    service = AllocationService(db.session)
    allocation = service.get_allocation_by_student(
        tenant_id=_tenant_id(), student_id=student_id
    )
    if allocation is None:
        return not_found_response("Active allocation")
    return success_response(data={"allocation": allocation.to_dict()})


@hostel_bp.route("/allocations", methods=["POST"])
@tenant_required
@auth_required
@require_feature("hostel")
@require_permission(HOSTEL_ALLOC_MANAGE)
def create_allocation():
    """POST /api/hostel/allocations — allocate a student to a bed."""
    payload = request.get_json() or {}
    student_id = payload.get("student_id")
    hostel_id = payload.get("hostel_id")
    room_id = payload.get("room_id")
    bed_id = payload.get("bed_id")
    raw_check_in = payload.get("check_in_at")

    errors = {}
    if not student_id:
        errors["student_id"] = "Required"
    if not hostel_id:
        errors["hostel_id"] = "Required"
    if not room_id:
        errors["room_id"] = "Required"
    if not bed_id:
        errors["bed_id"] = "Required"
    if not raw_check_in:
        errors["check_in_at"] = "Required (ISO 8601 datetime)"
    if errors:
        return validation_error_response(errors)

    try:
        check_in_at = _parse_datetime(raw_check_in, "check_in_at")
    except ValueError as exc:
        return validation_error_response({"check_in_at": str(exc)})

    service = AllocationService(db.session)
    try:
        allocation = service.create_allocation(
            tenant_id=_tenant_id(),
            student_id=student_id,
            hostel_id=hostel_id,
            room_id=room_id,
            bed_id=bed_id,
            check_in_at=check_in_at,
            academic_year_id=payload.get("academic_year_id"),
            notes=payload.get("notes"),
        )
    except ValueError as exc:
        return error_response(
            error="ValidationError", message=str(exc), status_code=400
        )

    db.session.commit()
    return success_response(
        data={"allocation": allocation.to_dict()}, status_code=201
    )


@hostel_bp.route("/allocations/<string:allocation_id>/checkout", methods=["PATCH"])
@tenant_required
@auth_required
@require_feature("hostel")
@require_permission(HOSTEL_ALLOC_MANAGE)
def checkout_allocation(allocation_id: str):
    """PATCH /api/hostel/allocations/:id/checkout"""
    # Tenant guard: ensure the allocation belongs to this tenant before
    # delegating to the service (the service doesn't re-check tenancy on
    # checkout because allocation_id is an opaque GUID).
    allocation = (
        db.session.query(HostelAllocation)
        .filter(
            HostelAllocation.id == allocation_id,
            HostelAllocation.tenant_id == _tenant_id(),
        )
        .first()
    )
    if allocation is None:
        return not_found_response("Allocation")

    service = AllocationService(db.session)
    try:
        closed = service.checkout_allocation(allocation_id)
    except ValueError as exc:
        return error_response(
            error="ValidationError", message=str(exc), status_code=400
        )

    db.session.commit()
    return success_response(data={"allocation": closed.to_dict()})
