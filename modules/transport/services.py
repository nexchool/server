"""Transport business logic: capacity, assignments, enrollment lifecycle, fee sync."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple, Union

from sqlalchemy import func, or_, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from core.database import db
from core.tenant import get_tenant_id
from modules.academics.academic_year.models import AcademicYear
from modules.finance.models import FeeComponent, FeeStructure, StudentFee, StudentFeeItem
from modules.finance.services.student_fee_service import (
    assign_student_fees_for_structure,
    remove_student_fee_for_structure,
)
from modules.rbac.services import has_permission
from modules.students.models import Student

from .models import (
    TransportBus,
    TransportBusAssignment,
    TransportDriver,
    TransportEnrollment,
    TransportFeePlan,
    TransportRoute,
    TransportRouteSchedule,
    TransportRouteStop,
    TransportScheduleException,
    TransportStaff,
    TransportStop,
)

TRANSPORT_FS_NAME = "Transport (monthly)"
TRANSPORT_COMPONENT_NAME = "Transport Fee"

HELPER_ROLES = frozenset({"helper", "attendant"})

# Route lifecycle — keep messages stable for API clients and UI.
INACTIVE_ROUTE_OPERATION_MSG = "Route is inactive and cannot be used"
CANNOT_DELETE_ROUTE_IN_USE_MSG = "Cannot delete route. It is currently used in the system."

# Enrollment derived transport health (list/detail APIs)
TRANSPORT_STATUS_ACTIVE = "active"
TRANSPORT_STATUS_ROUTE_INACTIVE = "route_inactive"
TRANSPORT_STATUS_SCHEDULE_MISSING = "schedule_missing"


def route_usage_breakdown(route_id: str, tenant_id: str) -> Dict[str, int]:
    """Counts blocking dependencies for hard-deleting a route."""
    return {
        "schedules": TransportRouteSchedule.query.filter_by(
            tenant_id=tenant_id, route_id=route_id
        ).count(),
        "enrollments": TransportEnrollment.query.filter_by(
            tenant_id=tenant_id, route_id=route_id
        ).count(),
        "fee_plans": TransportFeePlan.query.filter_by(tenant_id=tenant_id, route_id=route_id).count(),
        "assignments": TransportBusAssignment.query.filter_by(
            tenant_id=tenant_id, route_id=route_id
        ).count(),
        "schedule_exceptions": TransportScheduleException.query.filter_by(
            tenant_id=tenant_id, route_id=route_id
        ).count(),
    }


def _deactivate_future_schedules_for_inactive_route(route_id: str, tenant_id: str) -> int:
    """
    For today's calendar day: set is_active=False on schedules whose daily window has not
    started yet (start_time > now). Leaves in-progress windows (start <= now <= end) unchanged
    so the current run can finish. Does not change rows for windows already completed today.
    """
    now_t = datetime.now().time()
    rows = TransportRouteSchedule.query.filter_by(
        tenant_id=tenant_id, route_id=route_id, is_active=True
    ).all()
    deactivated = 0
    for s in rows:
        if s.start_time <= now_t <= s.end_time:
            continue
        if s.start_time > now_t:
            s.is_active = False
            deactivated += 1
    return deactivated


def _count_active_pickup_schedules_for_bus_route(
    tenant_id: str, bus_id: str, route_id: str, academic_year_id: str
) -> int:
    return (
        TransportRouteSchedule.query.filter(
            TransportRouteSchedule.tenant_id == tenant_id,
            TransportRouteSchedule.bus_id == bus_id,
            TransportRouteSchedule.route_id == route_id,
            TransportRouteSchedule.academic_year_id == academic_year_id,
            TransportRouteSchedule.is_active.is_(True),
            TransportRouteSchedule.shift_type == "pickup",
        ).count()
    )


def compute_enrollment_transport_status(
    en: TransportEnrollment,
    *,
    on_date: date,
) -> str:
    """
    Derived status for admin visibility — does not mutate enrollment rows.
    """
    tenant_id = en.tenant_id
    route = TransportRoute.query.filter_by(id=en.route_id, tenant_id=tenant_id).first()
    if not route or route.status != "active":
        return TRANSPORT_STATUS_ROUTE_INACTIVE
    if not en.bus_id or not en.academic_year_id:
        return TRANSPORT_STATUS_SCHEDULE_MISSING
    n = _count_active_pickup_schedules_for_bus_route(
        tenant_id, en.bus_id, en.route_id, en.academic_year_id
    )
    if n == 0:
        return TRANSPORT_STATUS_SCHEDULE_MISSING
    return TRANSPORT_STATUS_ACTIVE


def _bus_operational_warning(
    tenant_id: str,
    bus_id: str,
    academic_year_id: Optional[str],
    on_date: date,
) -> Dict[str, Any]:
    """
    Derived warning for fleet UI when assignment/route/schedules are inconsistent.
    """
    ay = academic_year_id or resolve_default_academic_year_id()
    out: Dict[str, Any] = {
        "code": "ok",
        "message": None,
        "derived_state": None,
    }
    assigns = (
        TransportBusAssignment.query.options(joinedload(TransportBusAssignment.route))
        .filter_by(tenant_id=tenant_id, bus_id=bus_id, status="active")
        .all()
    )
    active_a = next((x for x in assigns if assignment_active_on(x, on_date)), None)
    if not active_a or not active_a.route_id:
        out["code"] = "no_active_route"
        out["message"] = "This bus has no active route assigned."
        out["derived_state"] = "no_active_route"
        return out
    rte = active_a.route
    if rte.status != "active":
        out["code"] = "no_active_route"
        out["message"] = "Assigned route is inactive. This bus has no active route for new operations."
        out["derived_state"] = "no_active_route"
        return out
    if ay:
        sc = TransportRouteSchedule.query.filter(
            TransportRouteSchedule.tenant_id == tenant_id,
            TransportRouteSchedule.bus_id == bus_id,
            TransportRouteSchedule.route_id == rte.id,
            TransportRouteSchedule.academic_year_id == ay,
            TransportRouteSchedule.is_active.is_(True),
        ).count()
        if sc == 0:
            out["code"] = "no_active_schedules"
            out["message"] = "This bus has no active schedules for the current academic year."
            out["derived_state"] = "no_active_route"
            return out
    return out


def _stop_active_on_route(tenant_id: str, route_id: str, stop_id: str) -> bool:
    """True if stop is linked to the route via junction and the stop is active."""
    return (
        TransportRouteStop.query.filter_by(
            tenant_id=tenant_id, route_id=route_id, stop_id=stop_id
        )
        .join(TransportStop, TransportRouteStop.stop_id == TransportStop.id)
        .filter(TransportStop.is_active.is_(True))
        .first()
        is not None
    )


def occupancy_health_label(used: int, capacity: int) -> str:
    """Derived load health: normal | high | full | invalid."""
    if capacity <= 0:
        return "invalid"
    pct = 100.0 * used / capacity
    if pct > 100:
        return "invalid"
    if pct > 90:
        return "full"
    if pct > 70:
        return "high"
    return "normal"


def resolve_default_academic_year_id() -> Optional[str]:
    """Prefer active academic year for tenant; else latest by start_date."""
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None
    ay = (
        AcademicYear.query.filter_by(tenant_id=tenant_id, is_active=True)
        .order_by(AcademicYear.start_date.desc())
        .first()
    )
    if ay:
        return ay.id
    ay = (
        AcademicYear.query.filter_by(tenant_id=tenant_id)
        .order_by(AcademicYear.start_date.desc())
        .first()
    )
    return ay.id if ay else None


# ---------------------------------------------------------------------------
# Dates & assignment resolution
# ---------------------------------------------------------------------------


def _today() -> date:
    return date.today()


def assignment_active_on(a: TransportBusAssignment, on_date: date) -> bool:
    if a.status != "active":
        return False
    if a.effective_from > on_date:
        return False
    if a.effective_to is not None and a.effective_to < on_date:
        return False
    return True


def enrollment_active_on(en: TransportEnrollment, on_date: date) -> bool:
    if en.status != "active":
        return False
    if en.start_date > on_date:
        return False
    if en.end_date is not None and en.end_date < on_date:
        return False
    return True


def get_active_assignment_for_bus_route(
    bus_id: str,
    route_id: str,
    on_date: date,
) -> Optional[TransportBusAssignment]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None
    q = TransportBusAssignment.query.filter_by(
        tenant_id=tenant_id,
        bus_id=bus_id,
        route_id=route_id,
    )
    for a in q.all():
        if assignment_active_on(a, on_date):
            return a
    return None


def count_enrollment_seats_on_bus(
    bus_id: str,
    on_date: date,
    academic_year_id: Optional[str] = None,
    exclude_enrollment_id: Optional[str] = None,
) -> int:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return 0
    q = TransportEnrollment.query.filter_by(tenant_id=tenant_id, bus_id=bus_id, status="active")
    if academic_year_id:
        q = q.filter(TransportEnrollment.academic_year_id == academic_year_id)
    n = 0
    for en in q.all():
        if exclude_enrollment_id and en.id == exclude_enrollment_id:
            continue
        if enrollment_active_on(en, on_date):
            n += 1
    return n


def assert_bus_has_capacity(
    bus: TransportBus,
    on_date: date,
    academic_year_id: Optional[str] = None,
    exclude_enrollment_id: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    used = count_enrollment_seats_on_bus(
        bus.id,
        on_date,
        academic_year_id=academic_year_id,
        exclude_enrollment_id=exclude_enrollment_id,
    )
    if used >= bus.capacity:
        return False, "Bus is at full capacity for this period"
    return True, None


# ---------------------------------------------------------------------------
# Fee structure (per academic year, transport-only shell)
# ---------------------------------------------------------------------------


def get_or_create_transport_fee_structure(academic_year_id: str) -> FeeStructure:
    tenant_id = get_tenant_id()
    if not tenant_id:
        raise ValueError("Tenant context is required")

    fs = FeeStructure.query.filter_by(
        tenant_id=tenant_id,
        academic_year_id=academic_year_id,
        is_transport_only=True,
    ).first()
    if fs:
        return fs

    ay = AcademicYear.query.filter_by(id=academic_year_id, tenant_id=tenant_id).first()
    due = ay.end_date if ay else _today()

    fs = FeeStructure(
        tenant_id=tenant_id,
        academic_year_id=academic_year_id,
        name=TRANSPORT_FS_NAME,
        is_transport_only=True,
        due_date=due,
    )
    db.session.add(fs)
    db.session.flush()

    comp = FeeComponent(
        tenant_id=tenant_id,
        fee_structure_id=fs.id,
        name=TRANSPORT_COMPONENT_NAME,
        amount=Decimal("0"),
        is_optional=True,
        sort_order=9999,
    )
    db.session.add(comp)
    db.session.flush()
    return fs


def _sync_student_transport_fee_amounts(student_fee: StudentFee, monthly_fee: Decimal) -> None:
    total = Decimal("0")
    for item in student_fee.items:
        if item.fee_component and item.fee_component.name == TRANSPORT_COMPONENT_NAME:
            item.amount = monthly_fee
        total += item.amount or Decimal("0")
    student_fee.total_amount = total
    student_fee.updated_at = datetime.utcnow()


def sync_transport_fee_for_enrollment(enrollment: TransportEnrollment, monthly_fee: Decimal) -> Tuple[bool, Optional[str]]:
    """Create or update finance StudentFee line for transport."""
    tenant_id = get_tenant_id()
    if not tenant_id:
        return False, "Tenant context is required"

    student = Student.query.filter_by(id=enrollment.student_id, tenant_id=tenant_id).first()
    if not student:
        return False, "Student not found"
    ay_id = enrollment.academic_year_id
    if not ay_id:
        return False, "Enrollment academic year is required for transport billing"
    if student.academic_year_id and student.academic_year_id != ay_id:
        return False, "Student academic year must match transport enrollment academic year"

    fs = get_or_create_transport_fee_structure(ay_id)

    if enrollment.student_fee_id:
        sf = StudentFee.query.filter_by(id=enrollment.student_fee_id, tenant_id=tenant_id).first()
        if sf:
            _sync_student_transport_fee_amounts(sf, monthly_fee)
            return True, None

    eid = enrollment.id
    res = assign_student_fees_for_structure(fs.id, student_ids=[student.id], user_id=None)
    if not res.get("success"):
        return False, res.get("error", "Failed to assign transport fee structure")

    enrollment = TransportEnrollment.query.filter_by(id=eid, tenant_id=tenant_id).first() if eid else enrollment

    sf = StudentFee.query.filter_by(
        student_id=student.id,
        fee_structure_id=fs.id,
        tenant_id=tenant_id,
    ).first()
    if not sf:
        return False, "Transport student fee record not found after assignment"

    _sync_student_transport_fee_amounts(sf, monthly_fee)
    if enrollment:
        enrollment.student_fee_id = sf.id
    return True, None


def remove_transport_fee_for_enrollment(enrollment: TransportEnrollment) -> Tuple[bool, Optional[str]]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return False, "Tenant context is required"
    if not enrollment.student_fee_id:
        return True, None
    sf = StudentFee.query.filter_by(id=enrollment.student_fee_id, tenant_id=tenant_id).first()
    if not sf:
        enrollment.student_fee_id = None
        return True, None
    res = remove_student_fee_for_structure(sf.fee_structure_id, enrollment.student_id)
    if not res.get("success"):
        return False, res.get("error", "Could not remove transport fee (payments may exist)")
    enrollment.student_fee_id = None
    return True, None


# ---------------------------------------------------------------------------
# RBAC: who can see transport block on a student
# ---------------------------------------------------------------------------


def viewer_can_see_student_transport(viewer_user_id: str, student_dict: Dict[str, Any]) -> bool:
    if has_permission(viewer_user_id, "transport.enrollment.read"):
        return True
    if has_permission(viewer_user_id, "student.read.all"):
        return True
    if has_permission(viewer_user_id, "transport.info.read.self") or has_permission(
        viewer_user_id, "transport.student.read_own"
    ):
        if student_dict.get("user_id") == viewer_user_id:
            return True
    if has_permission(viewer_user_id, "transport.info.read.class"):
        from modules.attendance.services import get_teacher_class_ids

        cid = student_dict.get("class_id")
        if cid and cid in get_teacher_class_ids(viewer_user_id):
            return True
    return False


def _pickup_drop_labels(en: TransportEnrollment) -> Tuple[Optional[str], Optional[str]]:
    pu = en.pickup_point
    dr = en.drop_point
    if en.pickup_stop_id and en.pickup_stop:
        pu = en.pickup_stop.name
    if en.drop_stop_id and en.drop_stop:
        dr = en.drop_stop.name
    return pu, dr


def build_student_transport_block(student_id: str, viewer_user_id: str) -> Optional[Dict[str, Any]]:
    """Serialized transport summary for student detail APIs; None if hidden or no active enrollment."""
    from core.plan_features import is_plan_feature_enabled

    tenant_id = get_tenant_id()
    if not tenant_id:
        return None
    if not is_plan_feature_enabled(tenant_id, "transport"):
        return None

    st = Student.query.filter_by(id=student_id, tenant_id=tenant_id).first()
    if not st:
        return None
    base = st.to_dict()
    if not viewer_can_see_student_transport(viewer_user_id, base):
        return None

    on = _today()
    ay_id = st.academic_year_id
    q = TransportEnrollment.query.options(
        joinedload(TransportEnrollment.pickup_stop),
        joinedload(TransportEnrollment.drop_stop),
    ).filter_by(tenant_id=tenant_id, student_id=student_id, status="active")
    if ay_id:
        q = q.filter(TransportEnrollment.academic_year_id == ay_id)
    en_rows = q.order_by(TransportEnrollment.start_date.desc()).all()
    active_en: Optional[TransportEnrollment] = None
    for e in en_rows:
        if enrollment_active_on(e, on):
            active_en = e
            break
    if not active_en:
        return None

    bus = TransportBus.query.filter_by(id=active_en.bus_id, tenant_id=tenant_id).first()
    route = TransportRoute.query.filter_by(id=active_en.route_id, tenant_id=tenant_id).first()
    assign = get_active_assignment_for_bus_route(active_en.bus_id, active_en.route_id, on)
    driver = None
    helper = None
    if assign:
        driver = TransportDriver.query.filter_by(id=assign.driver_id, tenant_id=tenant_id).first()
        if assign.helper_staff_id:
            helper = TransportStaff.query.filter_by(id=assign.helper_staff_id, tenant_id=tenant_id).first()

    pu, dr = _pickup_drop_labels(active_en)

    return {
        "status": active_en.status,
        "bus": bus.to_dict() if bus else None,
        "driver": driver.to_dict() if driver else None,
        "helper": helper.to_dict() if helper else None,
        "route": route.to_dict() if route else None,
        "pickup_point": pu,
        "drop_point": dr,
        "pickup_stop": active_en.pickup_stop.to_dict() if active_en.pickup_stop else None,
        "drop_stop": active_en.drop_stop.to_dict() if active_en.drop_stop else None,
        "monthly_fee": float(active_en.monthly_fee) if active_en.monthly_fee is not None else None,
        "start_date": active_en.start_date.isoformat() if active_en.start_date else None,
        "end_date": active_en.end_date.isoformat() if active_en.end_date else None,
        "academic_year_id": active_en.academic_year_id,
    }


def transport_summaries_for_students(
    student_rows: List[Dict[str, Any]],
    academic_year_id: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Batch summary fields for student list: is_transport_opted, transport_bus_number, transport_route_name.
    Uses one query for active enrollments matching (student_id, academic_year_id) pairs.
    """
    tenant_id = get_tenant_id()
    if not tenant_id or not student_rows:
        return {}

    on = _today()
    pairs = []
    for s in student_rows:
        sid = s.get("id")
        ay = academic_year_id or s.get("academic_year_id")
        if sid and ay:
            pairs.append((sid, ay))
    if not pairs:
        return {}

    q = (
        TransportEnrollment.query.filter_by(tenant_id=tenant_id, status="active")
        .filter(tuple_(TransportEnrollment.student_id, TransportEnrollment.academic_year_id).in_(pairs))
        .options(joinedload(TransportEnrollment.bus), joinedload(TransportEnrollment.route))
    )
    out: Dict[str, Dict[str, Any]] = {}
    for en in q.all():
        if not enrollment_active_on(en, on):
            continue
        key = en.student_id
        bus_name = en.bus.bus_number if en.bus else None
        route_name = en.route.name if en.route else None
        out[key] = {
            "is_transport_opted": True,
            "transport_bus_number": bus_name,
            "transport_route_name": route_name,
        }
    # Students without active enrollment this year
    for s in student_rows:
        sid = s.get("id")
        if sid and sid not in out:
            out[sid] = {
                "is_transport_opted": bool(s.get("is_transport_opted")),
                "transport_bus_number": None,
                "transport_route_name": None,
            }
    return out


# ---------------------------------------------------------------------------
# Buses
# ---------------------------------------------------------------------------


def list_buses(
    include_occupancy: bool = True,
    academic_year_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return []
    ay = academic_year_id or resolve_default_academic_year_id()
    buses = TransportBus.query.filter_by(tenant_id=tenant_id).order_by(TransportBus.bus_number).all()
    on = _today()
    out = []
    for b in buses:
        d = b.to_dict()
        if include_occupancy:
            used = count_enrollment_seats_on_bus(b.id, on, academic_year_id=ay)
            cap = b.capacity or 1
            d["occupancy_count"] = used
            d["occupancy_percent"] = round(100.0 * used / cap, 2)
            d["occupancy_health"] = occupancy_health_label(used, cap)
        assign = (
            TransportBusAssignment.query.options(
                joinedload(TransportBusAssignment.driver),
                joinedload(TransportBusAssignment.helper),
                joinedload(TransportBusAssignment.route),
            )
            .filter_by(tenant_id=tenant_id, bus_id=b.id, status="active")
            .all()
        )
        active_a = next((x for x in assign if assignment_active_on(x, on)), None)
        if active_a and active_a.driver:
            d["assigned_driver"] = active_a.driver.to_dict()
        else:
            d["assigned_driver"] = None
        if active_a and active_a.helper:
            d["assigned_helper"] = active_a.helper.to_dict()
        else:
            d["assigned_helper"] = None
        if active_a and active_a.route:
            d["assigned_route"] = {"id": active_a.route.id, "name": active_a.route.name}
        else:
            d["assigned_route"] = None
        warn = _bus_operational_warning(tenant_id, b.id, ay, on)
        d["transport_operational"] = warn
        out.append(d)
    return out


def get_bus(bus_id: str) -> Optional[Dict[str, Any]]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None
    b = TransportBus.query.filter_by(id=bus_id, tenant_id=tenant_id).first()
    return b.to_dict() if b else None


def create_bus(payload: Dict[str, Any]) -> Tuple[Optional[Dict], Optional[str]]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None, "Tenant context is required"
    b = TransportBus(
        tenant_id=tenant_id,
        bus_number=payload["bus_number"],
        vehicle_number=payload.get("vehicle_number"),
        capacity=payload["capacity"],
        status=payload.get("status", "active"),
    )
    db.session.add(b)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return None, "Bus number must be unique for this school"
    return b.to_dict(), None


def update_bus(bus_id: str, payload: Dict[str, Any]) -> Tuple[Optional[Dict], Optional[str]]:
    tenant_id = get_tenant_id()
    b = TransportBus.query.filter_by(id=bus_id, tenant_id=tenant_id).first()
    if not b:
        return None, "Bus not found"
    if payload.get("bus_number") is not None:
        b.bus_number = payload["bus_number"]
    if payload.get("vehicle_number") is not None:
        b.vehicle_number = payload.get("vehicle_number")
    if payload.get("capacity") is not None:
        new_cap = payload["capacity"]
        used = count_enrollment_seats_on_bus(b.id, _today())
        if new_cap < used:
            return None, f"Capacity cannot be below current occupancy ({used})"
        b.capacity = new_cap
    if payload.get("status") is not None:
        b.status = payload["status"]
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return None, "Bus number must be unique for this school"
    return b.to_dict(), None


def delete_bus(bus_id: str) -> Tuple[bool, Optional[str]]:
    """Deactivate bus (preserve history). Fails if current enrollments exist."""
    tenant_id = get_tenant_id()
    b = TransportBus.query.filter_by(id=bus_id, tenant_id=tenant_id).first()
    if not b:
        return False, "Bus not found"
    on = _today()
    if count_enrollment_seats_on_bus(bus_id, on) > 0:
        return False, "Cannot deactivate bus while students are actively enrolled"
    b.status = "inactive"
    for a in TransportBusAssignment.query.filter_by(tenant_id=tenant_id, bus_id=bus_id, status="active").all():
        a.status = "inactive"
    db.session.commit()
    return True, None


# ---------------------------------------------------------------------------
# Drivers & routes
# ---------------------------------------------------------------------------


def list_drivers() -> List[Dict]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return []
    return [d.to_dict() for d in TransportDriver.query.filter_by(tenant_id=tenant_id).order_by(TransportDriver.name).all()]


def driver_crud_get(driver_id: str) -> Optional[Dict]:
    tenant_id = get_tenant_id()
    d = TransportDriver.query.filter_by(id=driver_id, tenant_id=tenant_id).first()
    return d.to_dict() if d else None


def create_driver(payload: Dict) -> Tuple[Optional[Dict], Optional[str]]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None, "Tenant context is required"
    d = TransportDriver(
        tenant_id=tenant_id,
        name=payload["name"],
        phone=payload.get("phone"),
        alternate_phone=payload.get("alternate_phone"),
        license_number=payload.get("license_number"),
        address=payload.get("address"),
        status=payload.get("status", "active"),
    )
    db.session.add(d)
    db.session.commit()
    return d.to_dict(), None


def update_driver(driver_id: str, payload: Dict) -> Tuple[Optional[Dict], Optional[str]]:
    tenant_id = get_tenant_id()
    d = TransportDriver.query.filter_by(id=driver_id, tenant_id=tenant_id).first()
    if not d:
        return None, "Driver not found"
    for k in ("name", "phone", "alternate_phone", "license_number", "address", "status"):
        if k in payload and payload[k] is not None:
            setattr(d, k, payload[k])
    db.session.commit()
    return d.to_dict(), None


def delete_driver(driver_id: str) -> Tuple[bool, Optional[str]]:
    """Deactivate driver (preserve history)."""
    tenant_id = get_tenant_id()
    d = TransportDriver.query.filter_by(id=driver_id, tenant_id=tenant_id).first()
    if not d:
        return False, "Driver not found"
    if TransportBusAssignment.query.filter_by(tenant_id=tenant_id, driver_id=driver_id, status="active").count():
        return False, "Cannot deactivate driver while assigned to an active bus assignment"
    if TransportRouteSchedule.query.filter_by(
        tenant_id=tenant_id, driver_id=driver_id, is_active=True
    ).count():
        return False, "Cannot deactivate driver while assigned to an active route schedule"
    d.status = "inactive"
    db.session.commit()
    return True, None


def list_routes() -> List[Dict]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return []
    rows = TransportRoute.query.filter_by(tenant_id=tenant_id).order_by(TransportRoute.name).all()
    out: List[Dict] = []
    for r in rows:
        d = r.to_dict()
        d["stops_count"] = TransportRouteStop.query.filter_by(
            tenant_id=tenant_id, route_id=r.id
        ).count()
        d["schedules_count"] = TransportRouteSchedule.query.filter_by(
            tenant_id=tenant_id, route_id=r.id, is_active=True
        ).count()
        out.append(d)
    return out


def get_route(route_id: str, include_stops: bool = True) -> Optional[Dict]:
    tenant_id = get_tenant_id()
    r = TransportRoute.query.filter_by(id=route_id, tenant_id=tenant_id).first()
    if not r:
        return None
    d = r.to_dict()
    if include_stops:
        d["stops"] = list_stops_for_route(route_id, include_inactive=True)
        d["stops_count"] = len(d["stops"])
    else:
        d["stops_count"] = TransportRouteStop.query.filter_by(
            tenant_id=tenant_id, route_id=route_id
        ).count()
    d["schedules_count"] = TransportRouteSchedule.query.filter_by(
        tenant_id=tenant_id, route_id=route_id, is_active=True
    ).count()
    return d


def create_route(payload: Dict) -> Tuple[Optional[Dict], Optional[str]]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None, "Tenant context is required"
    r = TransportRoute(
        tenant_id=tenant_id,
        name=payload["name"],
        start_point=payload.get("start_point"),
        end_point=payload.get("end_point"),
        approx_stops=payload.get("approx_stops"),
        pickup_time=payload.get("pickup_time"),
        drop_time=payload.get("drop_time"),
        status=payload.get("status", "active"),
        default_fee=payload.get("default_fee"),
        fee_cycle=payload.get("fee_cycle") or "monthly",
        is_reverse_enabled=bool(payload.get("is_reverse_enabled", False)),
        approx_stops_needs_review=bool(payload.get("approx_stops_needs_review", False)),
    )
    db.session.add(r)
    db.session.commit()
    d = r.to_dict()
    d["stops_count"] = 0
    d["schedules_count"] = 0
    return d, None


def update_route(route_id: str, payload: Dict) -> Tuple[Optional[Dict], Optional[str]]:
    tenant_id = get_tenant_id()
    r = TransportRoute.query.filter_by(id=route_id, tenant_id=tenant_id).first()
    if not r:
        return None, "Route not found"
    prev_status = r.status
    for k in (
        "name",
        "start_point",
        "end_point",
        "approx_stops",
        "pickup_time",
        "drop_time",
        "status",
        "default_fee",
        "fee_cycle",
        "is_reverse_enabled",
        "approx_stops_needs_review",
    ):
        if k in payload:
            setattr(r, k, payload[k])

    schedules_deactivated = 0
    if (
        payload.get("status") == "inactive"
        and prev_status != "inactive"
        and r.status == "inactive"
    ):
        schedules_deactivated = _deactivate_future_schedules_for_inactive_route(route_id, tenant_id)

    db.session.commit()
    d = get_route(route_id, include_stops=False)
    if not d:
        return None, "Route not found"
    # Warnings when newly inactive — enrollments unchanged; future-today schedules were deactivated.
    if (
        payload.get("status") == "inactive"
        and prev_status != "inactive"
        and (d.get("status") or r.status) == "inactive"
    ):
        active_enr = TransportEnrollment.query.filter_by(
            tenant_id=tenant_id, route_id=route_id, status="active"
        ).count()
        active_sched = TransportRouteSchedule.query.filter_by(
            tenant_id=tenant_id, route_id=route_id, is_active=True
        ).count()
        if active_enr or active_sched or schedules_deactivated:
            d["deactivate_warnings"] = {
                "active_enrollments": active_enr,
                "active_schedules_remaining": active_sched,
                "schedules_deactivated_future_windows": schedules_deactivated,
            }
    return d, None


def delete_route(route_id: str) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """
    Hard-delete a route only when it has no schedules, enrollments, fee plans, assignments,
    or schedule exceptions. Otherwise returns usage breakdown in details.
    """
    tenant_id = get_tenant_id()
    r = TransportRoute.query.filter_by(id=route_id, tenant_id=tenant_id).first()
    if not r:
        return False, "Route not found", None
    usage = route_usage_breakdown(route_id, tenant_id)
    if any(usage.values()):
        return (
            False,
            CANNOT_DELETE_ROUTE_IN_USE_MSG,
            {"usage": usage},
        )
    try:
        db.session.delete(r)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        u2 = route_usage_breakdown(route_id, tenant_id)
        return (
            False,
            CANNOT_DELETE_ROUTE_IN_USE_MSG,
            {"usage": u2},
        )
    return True, None, None


# ---------------------------------------------------------------------------
# Assignments
# ---------------------------------------------------------------------------


def list_assignments() -> List[Dict]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return []
    rows = TransportBusAssignment.query.filter_by(tenant_id=tenant_id).order_by(
        TransportBusAssignment.effective_from.desc()
    ).all()
    return [a.to_dict(include_nested=True) for a in rows]


def create_assignment(payload: Dict) -> Tuple[Optional[Dict], Optional[str]]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None, "Tenant context is required"

    bus = TransportBus.query.filter_by(id=payload["bus_id"], tenant_id=tenant_id).first()
    if not bus:
        return None, "Bus not found"
    drv = TransportDriver.query.filter_by(id=payload["driver_id"], tenant_id=tenant_id).first()
    if not drv:
        return None, "Driver not found"
    if drv.status != "active":
        return None, "Driver is inactive"
    rte = TransportRoute.query.filter_by(id=payload["route_id"], tenant_id=tenant_id).first()
    if not rte:
        return None, "Route not found"
    if rte.status != "active":
        return None, INACTIVE_ROUTE_OPERATION_MSG

    helper_id = payload.get("helper_staff_id")
    if helper_id:
        h = TransportStaff.query.filter_by(id=helper_id, tenant_id=tenant_id).first()
        if not h or h.status != "active":
            return None, "Helper staff not found or inactive"
        if h.role not in HELPER_ROLES:
            return None, "Selected staff must have role helper or attendant"

    a = TransportBusAssignment(
        tenant_id=tenant_id,
        bus_id=payload["bus_id"],
        driver_id=payload["driver_id"],
        route_id=payload["route_id"],
        helper_staff_id=helper_id,
        effective_from=payload["effective_from"],
        effective_to=payload.get("effective_to"),
        status=payload.get("status", "active"),
    )
    db.session.add(a)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return None, "Only one active assignment is allowed per bus"
    return a.to_dict(include_nested=True), None


def buses_for_route(
    route_id: str,
    on_date: Optional[date] = None,
    academic_year_id: Optional[str] = None,
) -> List[Dict]:
    """Buses that have an active assignment to the route on the given date."""
    tenant_id = get_tenant_id()
    if not tenant_id:
        return []
    on = on_date or _today()
    ay = academic_year_id or resolve_default_academic_year_id()
    bids = set()
    for a in TransportBusAssignment.query.filter_by(tenant_id=tenant_id, route_id=route_id).all():
        if assignment_active_on(a, on):
            bids.add(a.bus_id)
    out = []
    for bid in sorted(bids):
        b = TransportBus.query.filter_by(id=bid, tenant_id=tenant_id).first()
        if b and b.status == "active":
            d = b.to_dict()
            used = count_enrollment_seats_on_bus(b.id, on, academic_year_id=ay)
            cap = b.capacity or 1
            d["occupancy_count"] = used
            d["occupancy_percent"] = round(100.0 * used / cap, 2)
            d["occupancy_health"] = occupancy_health_label(used, cap)
            out.append(d)
    return out


# ---------------------------------------------------------------------------
# Enrollments
# ---------------------------------------------------------------------------


def validate_transport_enrollment_prereqs(
    *,
    tenant_id: str,
    student: Student,
    bus_id: str,
    route_id: str,
    start_date: date,
    academic_year_id: str,
    exclude_enrollment_id: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """Strict checks before create/update enrollment."""
    bus = TransportBus.query.filter_by(id=bus_id, tenant_id=tenant_id).first()
    if not bus:
        return False, "Bus not found"
    if bus.status != "active":
        return False, "Bus is not active"
    route = TransportRoute.query.filter_by(id=route_id, tenant_id=tenant_id).first()
    if not route:
        return False, "Route not found"
    if route.status != "active":
        return False, INACTIVE_ROUTE_OPERATION_MSG
    assign = get_active_assignment_for_bus_route(bus_id, route_id, start_date)
    if not assign:
        return False, "No active bus assignment for this bus and route on the selected date"
    drv = TransportDriver.query.filter_by(id=assign.driver_id, tenant_id=tenant_id).first()
    if not drv or drv.status != "active":
        return False, "Assigned driver is missing or inactive"
    if assign.helper_staff_id:
        h = TransportStaff.query.filter_by(id=assign.helper_staff_id, tenant_id=tenant_id).first()
        if not h or h.status != "active":
            return False, "Assigned helper is missing or inactive"
    if not student.academic_year_id:
        return False, "Student must have an academic year before transport enrollment"
    if student.academic_year_id != academic_year_id:
        return False, "Enrollment academic year must match the student's current academic year"
    ok, err = assert_bus_has_capacity(
        bus,
        start_date,
        academic_year_id=academic_year_id,
        exclude_enrollment_id=exclude_enrollment_id,
    )
    if not ok:
        return False, err
    return True, None


def _enrollment_transport_hints(en: TransportEnrollment) -> Dict[str, Any]:
    """Junction stop times + pickup schedule windows for API consumers (US5)."""
    tenant_id = en.tenant_id
    hints: Dict[str, Any] = {
        "junction_pickup_time": None,
        "junction_drop_time": None,
        "schedule_pickup_windows": [],
        "pickup_time_display": None,
    }
    if en.pickup_stop_id and en.route_id:
        rs = TransportRouteStop.query.filter_by(
            tenant_id=tenant_id, route_id=en.route_id, stop_id=en.pickup_stop_id
        ).first()
        if rs:
            if rs.pickup_time:
                hints["junction_pickup_time"] = rs.pickup_time.strftime("%H:%M")
            if rs.drop_time:
                hints["junction_drop_time"] = rs.drop_time.strftime("%H:%M")

    if en.route_id and en.bus_id and en.academic_year_id:
        pickups = (
            TransportRouteSchedule.query.join(
                TransportRoute, TransportRouteSchedule.route_id == TransportRoute.id
            )
            .filter(
                TransportRouteSchedule.tenant_id == tenant_id,
                TransportRoute.tenant_id == tenant_id,
                TransportRoute.status == "active",
                TransportRouteSchedule.route_id == en.route_id,
                TransportRouteSchedule.bus_id == en.bus_id,
                TransportRouteSchedule.academic_year_id == en.academic_year_id,
                TransportRouteSchedule.is_active.is_(True),
                TransportRouteSchedule.shift_type == "pickup",
            )
            .order_by(TransportRouteSchedule.start_time)
            .all()
        )
        for s in pickups:
            hints["schedule_pickup_windows"].append(
                {
                    "start_time": s.start_time.strftime("%H:%M"),
                    "end_time": s.end_time.strftime("%H:%M"),
                }
            )

    if hints["junction_pickup_time"]:
        hints["pickup_time_display"] = hints["junction_pickup_time"]
    elif hints["schedule_pickup_windows"]:
        w = hints["schedule_pickup_windows"][0]
        hints["pickup_time_display"] = f"{w['start_time']}–{w['end_time']}"
    return hints


def list_enrollments(academic_year_id: Optional[str] = None) -> List[Dict]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return []
    q = TransportEnrollment.query.options(
        joinedload(TransportEnrollment.bus),
        joinedload(TransportEnrollment.route),
        joinedload(TransportEnrollment.pickup_stop),
        joinedload(TransportEnrollment.drop_stop),
    ).filter_by(tenant_id=tenant_id)
    if academic_year_id:
        q = q.filter(TransportEnrollment.academic_year_id == academic_year_id)
    rows = q.order_by(TransportEnrollment.created_at.desc()).all()
    result = []
    on = _today()
    for en in rows:
        d = en.to_dict(include_nested=True)
        d["transport_hints"] = _enrollment_transport_hints(en)
        if en.status == "active":
            d["transport_status"] = compute_enrollment_transport_status(en, on_date=on)
        else:
            d["transport_status"] = None
        st = en.student
        if st and st.user:
            d["student_name"] = st.user.name
            d["admission_number"] = st.admission_number
        result.append(d)
    return result


def create_enrollment(payload: Dict) -> Tuple[Optional[Dict], Optional[str]]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None, "Tenant context is required"

    student = Student.query.filter_by(id=payload["student_id"], tenant_id=tenant_id).first()
    if not student:
        return None, "Student not found"

    academic_year_id = payload.get("academic_year_id") or student.academic_year_id
    if not academic_year_id:
        return None, "academic_year_id is required (set on student or in request)"

    start_d = payload["start_date"]
    bus_id = payload["bus_id"]
    route_id = payload["route_id"]

    ok, err = validate_transport_enrollment_prereqs(
        tenant_id=tenant_id,
        student=student,
        bus_id=bus_id,
        route_id=route_id,
        start_date=start_d,
        academic_year_id=academic_year_id,
    )
    if not ok:
        return None, err

    pickup_stop_id = payload.get("pickup_stop_id")
    drop_stop_id = payload.get("drop_stop_id")
    rte = TransportRoute.query.filter_by(id=route_id, tenant_id=tenant_id).first()
    fee_cycle = payload.get("fee_cycle")
    if fee_cycle is None or fee_cycle == "":
        fee_cycle = (rte.fee_cycle if rte else None) or "monthly"

    if pickup_stop_id and not _stop_active_on_route(tenant_id, route_id, pickup_stop_id):
        return None, "Invalid or inactive pickup stop for this route"
    if drop_stop_id and not _stop_active_on_route(tenant_id, route_id, drop_stop_id):
        return None, "Invalid or inactive drop stop for this route"

    on = _today()
    for ex in TransportEnrollment.query.filter_by(
        tenant_id=tenant_id, student_id=student.id, status="active"
    ).all():
        if ex.end_date is not None and ex.end_date < on:
            ex.status = "inactive"
    db.session.flush()

    existing_active = TransportEnrollment.query.filter_by(
        tenant_id=tenant_id,
        student_id=student.id,
        status="active",
        academic_year_id=academic_year_id,
    ).all()
    for ex in existing_active:
        if enrollment_active_on(ex, start_d):
            return None, "Student already has an active transport enrollment for this academic year"

    monthly_fee: Decimal = payload["monthly_fee"]
    en = TransportEnrollment(
        tenant_id=tenant_id,
        student_id=student.id,
        academic_year_id=academic_year_id,
        bus_id=bus_id,
        route_id=route_id,
        pickup_point=payload.get("pickup_point"),
        drop_point=payload.get("drop_point"),
        pickup_stop_id=pickup_stop_id,
        drop_stop_id=drop_stop_id,
        monthly_fee=monthly_fee,
        fee_cycle=fee_cycle,
        status="active",
        start_date=start_d,
        end_date=payload.get("end_date"),
    )
    db.session.add(en)
    db.session.flush()

    ok, err = sync_transport_fee_for_enrollment(en, monthly_fee)
    if not ok:
        db.session.rollback()
        return None, err or "Fee sync failed"

    student.is_transport_opted = True
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return None, "Enrollment violates uniqueness (duplicate active enrollment)"

    db.session.refresh(en)
    d = en.to_dict(include_nested=True)
    d["transport_hints"] = _enrollment_transport_hints(en)
    d["transport_status"] = (
        compute_enrollment_transport_status(en, on_date=_today()) if en.status == "active" else None
    )
    return d, None


def update_enrollment(enrollment_id: str, payload: Dict) -> Tuple[Optional[Dict], Optional[str]]:
    tenant_id = get_tenant_id()
    en = TransportEnrollment.query.filter_by(id=enrollment_id, tenant_id=tenant_id).first()
    if not en:
        return None, "Enrollment not found"

    if payload.get("academic_year_id") and payload.get("academic_year_id") != en.academic_year_id:
        return None, "Changing academic year is not supported; deactivate and create a new enrollment"

    st = Student.query.get(en.student_id)
    if not st:
        return None, "Student not found"

    if payload.get("bus_id"):
        en.bus_id = payload["bus_id"]
    if payload.get("route_id"):
        en.route_id = payload["route_id"]
    start_d = payload.get("start_date") or en.start_date

    ok, err = validate_transport_enrollment_prereqs(
        tenant_id=tenant_id,
        student=st,
        bus_id=en.bus_id,
        route_id=en.route_id,
        start_date=start_d,
        academic_year_id=en.academic_year_id,
        exclude_enrollment_id=en.id,
    )
    if not ok:
        return None, err

    if payload.get("pickup_point") is not None:
        en.pickup_point = payload.get("pickup_point")
    if payload.get("drop_point") is not None:
        en.drop_point = payload.get("drop_point")
    if "pickup_stop_id" in payload:
        psid = payload.get("pickup_stop_id")
        if psid and not _stop_active_on_route(tenant_id, en.route_id, psid):
            return None, "Invalid or inactive pickup stop for this route"
        en.pickup_stop_id = psid
    if "drop_stop_id" in payload:
        dsid = payload.get("drop_stop_id")
        if dsid and not _stop_active_on_route(tenant_id, en.route_id, dsid):
            return None, "Invalid or inactive drop stop for this route"
        en.drop_stop_id = dsid
    if "fee_cycle" in payload:
        en.fee_cycle = payload.get("fee_cycle")
    if payload.get("end_date") is not None:
        en.end_date = payload.get("end_date")
    if payload.get("start_date") is not None:
        en.start_date = payload["start_date"]
    if "status" in payload and payload.get("status") is not None:
        en.status = payload["status"]

    if payload.get("monthly_fee") is not None:
        en.monthly_fee = payload["monthly_fee"]

    mf = Decimal(en.monthly_fee)
    ok, err = sync_transport_fee_for_enrollment(en, mf)
    if not ok:
        return None, err or "Fee sync failed"

    st2 = Student.query.get(en.student_id)
    if st2:
        st2.is_transport_opted = en.status == "active" and enrollment_active_on(en, _today())

    db.session.commit()
    db.session.refresh(en)
    d = en.to_dict(include_nested=True)
    d["transport_hints"] = _enrollment_transport_hints(en)
    d["transport_status"] = (
        compute_enrollment_transport_status(en, on_date=_today()) if en.status == "active" else None
    )
    return d, None


def deactivate_enrollment(enrollment_id: str) -> Tuple[bool, Optional[str]]:
    tenant_id = get_tenant_id()
    en = TransportEnrollment.query.filter_by(id=enrollment_id, tenant_id=tenant_id).first()
    if not en:
        return False, "Enrollment not found"

    en.status = "inactive"
    en.end_date = _today()

    ok, err = remove_transport_fee_for_enrollment(en)
    if not ok:
        return False, err

    st = Student.query.get(en.student_id)
    if st:
        other = (
            TransportEnrollment.query.filter(
                TransportEnrollment.tenant_id == tenant_id,
                TransportEnrollment.student_id == st.id,
                TransportEnrollment.status == "active",
                TransportEnrollment.id != en.id,
            ).first()
        )
        st.is_transport_opted = other is not None

    db.session.commit()
    return True, None


# ---------------------------------------------------------------------------
# Bus detail & dashboard
# ---------------------------------------------------------------------------


def get_bus_details(
    bus_id: str,
    academic_year_id: Optional[str] = None,
    timeline_date: Optional[date] = None,
) -> Tuple[Optional[Dict], Optional[str]]:
    tenant_id = get_tenant_id()
    bus = TransportBus.query.filter_by(id=bus_id, tenant_id=tenant_id).first()
    if not bus:
        return None, "Bus not found"
    on = _today()
    ay = academic_year_id or resolve_default_academic_year_id()
    used = count_enrollment_seats_on_bus(bus_id, on, academic_year_id=ay)
    cap = bus.capacity or 1
    assign = None
    for a in TransportBusAssignment.query.options(
        joinedload(TransportBusAssignment.driver),
        joinedload(TransportBusAssignment.helper),
        joinedload(TransportBusAssignment.route),
    ).filter_by(tenant_id=tenant_id, bus_id=bus_id).all():
        if assignment_active_on(a, on):
            assign = a
            break
    route = assign.route if assign else None
    driver = assign.driver if assign else None
    helper = assign.helper if assign else None

    students: List[Dict[str, Any]] = []
    qen = TransportEnrollment.query.options(
        joinedload(TransportEnrollment.pickup_stop),
        joinedload(TransportEnrollment.drop_stop),
    ).filter_by(tenant_id=tenant_id, bus_id=bus_id, status="active")
    if ay:
        qen = qen.filter(TransportEnrollment.academic_year_id == ay)
    for en in qen.all():
        if not enrollment_active_on(en, on):
            continue
        st = en.student
        pu, dr = _pickup_drop_labels(en)
        students.append(
            {
                "enrollment_id": en.id,
                "student_id": en.student_id,
                "student_name": st.user.name if st and st.user else None,
                "admission_number": st.admission_number if st else None,
                "pickup_point": pu,
                "drop_point": dr,
            }
        )

    tl_day = timeline_date if timeline_date is not None else on
    schedule_timeline: List[Dict[str, Any]] = []
    is_timeline_holiday = False
    if ay:
        schedule_timeline, is_timeline_holiday = _schedule_timeline_for_bus(
            tenant_id, bus_id, ay, tl_day
        )

    top_warn = _bus_operational_warning(tenant_id, bus_id, ay, on)

    return {
        "bus": bus.to_dict(),
        "driver": driver.to_dict() if driver else None,
        "helper": helper.to_dict() if helper else None,
        "route": route.to_dict() if route else None,
        "capacity": bus.capacity,
        "occupancy": used,
        "occupancy_percent": round(100.0 * used / cap, 2),
        "occupancy_health": occupancy_health_label(used, cap),
        "students": students,
        "schedule_timeline": schedule_timeline,
        "timeline_date": tl_day.isoformat() if ay else None,
        "is_timeline_holiday": is_timeline_holiday if ay else False,
        "transport_operational": top_warn,
    }, None


def dashboard_stats(academic_year_id: Optional[str] = None) -> Dict[str, Any]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return {}
    on = _today()
    ay = academic_year_id or resolve_default_academic_year_id()
    buses = TransportBus.query.filter_by(tenant_id=tenant_id).all()
    active_buses = [b for b in buses if b.status == "active"]
    total_buses = len(buses)
    active_bus_count = len(active_buses)
    students_using = 0
    per_bus = []
    buses_high_or_full = 0
    for b in buses:
        used = count_enrollment_seats_on_bus(b.id, on, academic_year_id=ay)
        students_using += used
        cap = b.capacity or 1
        pct = round(100.0 * used / cap, 2)
        health = occupancy_health_label(used, cap)
        if health in ("high", "full"):
            buses_high_or_full += 1
        per_bus.append(
            {
                "bus_id": b.id,
                "bus_number": b.bus_number,
                "status": b.status,
                "capacity": b.capacity,
                "occupancy": used,
                "occupancy_percent": pct,
                "occupancy_health": health,
            }
        )

    route_dist: Dict[str, int] = {}
    qen = TransportEnrollment.query.filter_by(tenant_id=tenant_id, status="active")
    if ay:
        qen = qen.filter(TransportEnrollment.academic_year_id == ay)
    for en in qen.all():
        if not enrollment_active_on(en, on):
            continue
        route_dist[en.route_id] = route_dist.get(en.route_id, 0) + 1

    route_labels = []
    for rid, cnt in route_dist.items():
        r = TransportRoute.query.filter_by(id=rid, tenant_id=tenant_id).first()
        route_labels.append(
            {"route_id": rid, "route_name": r.name if r else rid, "students": cnt}
        )

    students_on_inactive_routes = 0
    qen2 = TransportEnrollment.query.filter_by(tenant_id=tenant_id, status="active")
    if ay:
        qen2 = qen2.filter(TransportEnrollment.academic_year_id == ay)
    for en in qen2.all():
        if not enrollment_active_on(en, on):
            continue
        rte = TransportRoute.query.filter_by(id=en.route_id, tenant_id=tenant_id).first()
        if rte and rte.status != "active":
            students_on_inactive_routes += 1

    buses_without_active_routes = 0
    for b in active_buses:
        w = _bus_operational_warning(tenant_id, b.id, ay, on)
        if w.get("code") != "ok":
            buses_without_active_routes += 1

    drivers_without_schedules = 0
    if ay:
        active_drivers = TransportDriver.query.filter_by(tenant_id=tenant_id, status="active").all()
        scheduled_driver_ids = (
            db.session.query(TransportRouteSchedule.driver_id)
            .join(TransportRoute, TransportRouteSchedule.route_id == TransportRoute.id)
            .filter(
                TransportRouteSchedule.tenant_id == tenant_id,
                TransportRoute.tenant_id == tenant_id,
                TransportRoute.status == "active",
                TransportRouteSchedule.academic_year_id == ay,
                TransportRouteSchedule.is_active.is_(True),
            )
            .distinct()
            .all()
        )
        sched_set = {r[0] for r in scheduled_driver_ids if r[0]}
        drivers_without_schedules = len([x for x in active_drivers if x.id not in sched_set])

    return {
        "academic_year_id": ay,
        "total_buses": total_buses,
        "active_buses": active_bus_count,
        "total_students_on_transport": students_using,
        "buses_near_capacity_count": buses_high_or_full,
        "occupancy_per_bus": per_bus,
        "route_distribution": route_labels,
        "students_on_inactive_routes": students_on_inactive_routes,
        "buses_without_active_routes": buses_without_active_routes,
        "drivers_without_schedules": drivers_without_schedules,
    }


# ---------------------------------------------------------------------------
# Fee plans (optional defaults per route)
# ---------------------------------------------------------------------------


def upsert_fee_plan(
    route_id: str,
    amount: Decimal,
    academic_year_id: Optional[str] = None,
) -> Tuple[Optional[Dict], Optional[str]]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None, "Tenant context is required"
    rte = TransportRoute.query.filter_by(id=route_id, tenant_id=tenant_id).first()
    if not rte:
        return None, "Route not found"
    if rte.status != "active":
        return None, INACTIVE_ROUTE_OPERATION_MSG
    ay = academic_year_id or resolve_default_academic_year_id()
    if not ay:
        return None, "No academic year available for fee plan"
    fp = TransportFeePlan.query.filter_by(
        tenant_id=tenant_id, route_id=route_id, academic_year_id=ay
    ).first()
    if fp:
        fp.amount = amount
    else:
        fp = TransportFeePlan(
            tenant_id=tenant_id,
            route_id=route_id,
            academic_year_id=ay,
            amount=amount,
        )
        db.session.add(fp)
    db.session.commit()
    return fp.to_dict(), None


def list_fee_plans(academic_year_id: Optional[str] = None) -> List[Dict]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return []
    q = TransportFeePlan.query.filter_by(tenant_id=tenant_id)
    if academic_year_id:
        q = q.filter(TransportFeePlan.academic_year_id == academic_year_id)
    return [f.to_dict() for f in q.all()]


# ---------------------------------------------------------------------------
# Stops
# ---------------------------------------------------------------------------


def list_stops_for_route(route_id: str, include_inactive: bool = False) -> List[Dict]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return []
    q = (
        TransportRouteStop.query.filter_by(tenant_id=tenant_id, route_id=route_id)
        .join(TransportStop, TransportRouteStop.stop_id == TransportStop.id)
        .order_by(TransportRouteStop.sequence_order, TransportStop.name)
    )
    if not include_inactive:
        q = q.filter(TransportStop.is_active.is_(True))
    rows = q.all()
    out: List[Dict] = []
    for link in rows:
        s = link.stop
        d = s.to_dict()
        d["sequence_order"] = link.sequence_order
        pt = link.pickup_time or s.pickup_time
        dt = link.drop_time or s.drop_time
        d["pickup_time"] = pt.isoformat() if pt else None
        d["drop_time"] = dt.isoformat() if dt else None
        d["route_stop_id"] = link.id
        d["route_id"] = route_id
        out.append(d)
    return out


def create_stop(route_id: str, payload: Dict) -> Tuple[Optional[Dict], Optional[str]]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None, "Tenant context is required"
    route = TransportRoute.query.filter_by(id=route_id, tenant_id=tenant_id).first()
    if not route:
        return None, "Route not found"
    existing_max = (
        db.session.query(func.max(TransportRouteStop.sequence_order))
        .filter_by(tenant_id=tenant_id, route_id=route_id)
        .scalar()
    )
    seq = int(payload.get("sequence_order") or (existing_max or 0) + 1)
    s = TransportStop(
        tenant_id=tenant_id,
        route_id=None,
        name=payload["name"],
        area=payload.get("area"),
        landmark=payload.get("landmark"),
        latitude=payload.get("latitude"),
        longitude=payload.get("longitude"),
        sequence_order=0,
        pickup_time=None,
        drop_time=None,
        is_active=payload.get("is_active", True),
    )
    db.session.add(s)
    db.session.flush()
    link = TransportRouteStop(
        tenant_id=tenant_id,
        route_id=route_id,
        stop_id=s.id,
        sequence_order=seq,
        pickup_time=payload.get("pickup_time"),
        drop_time=payload.get("drop_time"),
    )
    db.session.add(link)
    db.session.commit()
    for row in list_stops_for_route(route_id, include_inactive=True):
        if row.get("id") == s.id:
            return row, None
    return s.to_dict(), None


def update_stop(stop_id: str, payload: Dict) -> Tuple[Optional[Dict], Optional[str]]:
    tenant_id = get_tenant_id()
    s = TransportStop.query.filter_by(id=stop_id, tenant_id=tenant_id).first()
    if not s:
        return None, "Stop not found"
    for k in (
        "name",
        "pickup_time",
        "drop_time",
        "is_active",
        "sequence_order",
        "area",
        "landmark",
        "latitude",
        "longitude",
    ):
        if k in payload:
            setattr(s, k, payload[k])
    db.session.commit()
    return s.to_dict(), None


def reorder_stops(route_id: str, stop_ids_in_order: List[str]) -> Tuple[bool, Optional[str]]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return False, "Tenant context is required"
    for i, sid in enumerate(stop_ids_in_order):
        link = TransportRouteStop.query.filter_by(
            tenant_id=tenant_id, route_id=route_id, stop_id=sid
        ).first()
        if not link:
            return False, f"Stop {sid} not found on route"
        link.sequence_order = i + 1
    db.session.commit()
    return True, None


def _stop_duplicate_name(
    tenant_id: str, name: str, exclude_stop_id: Optional[str] = None
) -> bool:
    q = TransportStop.query.filter(
        TransportStop.tenant_id == tenant_id,
        func.lower(TransportStop.name) == name.strip().lower(),
    )
    if exclude_stop_id:
        q = q.filter(TransportStop.id != exclude_stop_id)
    return q.first() is not None


def list_global_stops(
    *,
    search: Optional[str] = None,
    area: Optional[str] = None,
    include_inactive: bool = False,
    with_usage: bool = True,
) -> List[Dict]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return []
    q = TransportStop.query.filter_by(tenant_id=tenant_id)
    if not include_inactive:
        q = q.filter(TransportStop.is_active.is_(True))
    if area:
        q = q.filter(TransportStop.area == area)
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.filter(
            or_(
                TransportStop.name.ilike(term),
                TransportStop.landmark.ilike(term),
                TransportStop.area.ilike(term),
            )
        )
    rows = q.order_by(TransportStop.name).all()
    out: List[Dict] = []
    for s in rows:
        d = s.to_dict()
        if with_usage:
            d["usage_count"] = TransportRouteStop.query.filter_by(
                tenant_id=tenant_id, stop_id=s.id
            ).count()
        out.append(d)
    return out


def get_global_stop(stop_id: str) -> Optional[Dict]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None
    s = TransportStop.query.filter_by(id=stop_id, tenant_id=tenant_id).first()
    if not s:
        return None
    d = s.to_dict()
    d["usage_count"] = TransportRouteStop.query.filter_by(
        tenant_id=tenant_id, stop_id=s.id
    ).count()
    link_rows = (
        db.session.query(TransportRouteStop, TransportRoute.name)
        .join(TransportRoute, TransportRouteStop.route_id == TransportRoute.id)
        .filter(
            TransportRouteStop.tenant_id == tenant_id,
            TransportRouteStop.stop_id == s.id,
        )
        .order_by(TransportRoute.name)
        .all()
    )
    d["used_in_routes"] = [
        {"id": link.route_id, "name": rname, "sequence_order": link.sequence_order}
        for link, rname in link_rows
    ]
    return d


def create_global_stop(payload: Dict) -> Tuple[Optional[Dict], Optional[str]]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None, "Tenant context is required"
    name = payload["name"]
    if _stop_duplicate_name(tenant_id, name):
        return None, "DUPLICATE_STOP_NAME"
    s = TransportStop(
        tenant_id=tenant_id,
        route_id=None,
        name=name,
        area=payload.get("area"),
        landmark=payload.get("landmark"),
        latitude=payload.get("latitude"),
        longitude=payload.get("longitude"),
        sequence_order=0,
        pickup_time=None,
        drop_time=None,
        is_active=payload.get("is_active", True),
    )
    db.session.add(s)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return None, "DUPLICATE_STOP_NAME"
    return get_global_stop(s.id), None


def update_global_stop(stop_id: str, payload: Dict) -> Tuple[Optional[Dict], Optional[str]]:
    tenant_id = get_tenant_id()
    s = TransportStop.query.filter_by(id=stop_id, tenant_id=tenant_id).first()
    if not s:
        return None, "Stop not found"
    if payload.get("name") and _stop_duplicate_name(tenant_id, payload["name"], exclude_stop_id=stop_id):
        return None, "DUPLICATE_STOP_NAME"
    for k in ("name", "area", "landmark", "latitude", "longitude", "is_active"):
        if k in payload:
            setattr(s, k, payload[k])
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return None, "DUPLICATE_STOP_NAME"
    return get_global_stop(s.id), None


def delete_global_stop(stop_id: str) -> Tuple[bool, Optional[str]]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return False, "Tenant context is required"
    s = TransportStop.query.filter_by(id=stop_id, tenant_id=tenant_id).first()
    if not s:
        return False, "Stop not found"
    n = TransportRouteStop.query.filter_by(tenant_id=tenant_id, stop_id=stop_id).count()
    if n > 0:
        return False, "STOP_IN_USE"
    db.session.delete(s)
    db.session.commit()
    return True, None


def sync_route_stops(
    route_id: str, rows: List[Dict[str, Any]]
) -> Tuple[Optional[Dict], Optional[str]]:
    """Replace all route–stop junction rows for a route (atomic)."""
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None, "Tenant context is required"
    route = TransportRoute.query.filter_by(id=route_id, tenant_id=tenant_id).first()
    if not route:
        return None, "Route not found"
    for row in rows:
        s = TransportStop.query.filter_by(id=row["stop_id"], tenant_id=tenant_id).first()
        if not s:
            return None, f"Stop {row['stop_id']} not found"
        if not s.is_active:
            return None, f"Stop {row['stop_id']} is inactive"

    TransportRouteStop.query.filter_by(tenant_id=tenant_id, route_id=route_id).delete(
        synchronize_session=False
    )
    db.session.flush()
    for row in rows:
        db.session.add(
            TransportRouteStop(
                tenant_id=tenant_id,
                route_id=route_id,
                stop_id=row["stop_id"],
                sequence_order=row["sequence_order"],
                pickup_time=row.get("pickup_time"),
                drop_time=row.get("drop_time"),
            )
        )
    db.session.commit()
    return {"stops": list_stops_for_route(route_id, include_inactive=True)}, None


# ---------------------------------------------------------------------------
# Route schedules (recurring time-of-day)
# ---------------------------------------------------------------------------


def _fmt_hhmm(t: Optional[time]) -> str:
    if t is None:
        return ""
    return t.strftime("%H:%M")


def _parse_hhmm(s: str) -> Optional[time]:
    if not s:
        return None
    raw = str(s).strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(raw, fmt).time()
        except ValueError:
            continue
    return None


def _opposite_shift(shift: str) -> str:
    return "drop" if shift == "pickup" else "pickup"


def _infer_reverse_times_from_junction(tenant_id: str, route_id: str) -> Tuple[Optional[time], Optional[time]]:
    rows = (
        TransportRouteStop.query.filter_by(tenant_id=tenant_id, route_id=route_id)
        .order_by(TransportRouteStop.sequence_order)
        .all()
    )
    drops = [r.drop_time for r in rows if r.drop_time is not None]
    if len(drops) >= 2:
        lo, hi = min(drops), max(drops)
        if lo < hi:
            return lo, hi
    return None, None


def _schedule_to_dict(s: TransportRouteSchedule) -> Dict[str, Any]:
    route_min = {"id": s.route.id, "name": s.route.name} if s.route else None
    bus_min = {"id": s.bus.id, "bus_number": s.bus.bus_number} if s.bus else None
    driver_min = (
        {"id": s.driver.id, "name": s.driver.name, "phone": s.driver.phone}
        if s.driver
        else None
    )
    helper_min = (
        {"id": s.helper.id, "name": s.helper.name, "phone": s.helper.phone}
        if s.helper
        else None
    )
    return {
        "id": s.id,
        "route": route_min,
        "bus": bus_min,
        "driver": driver_min,
        "helper": helper_min,
        "shift_type": s.shift_type,
        "start_time": _fmt_hhmm(s.start_time),
        "end_time": _fmt_hhmm(s.end_time),
        "academic_year_id": s.academic_year_id,
        "is_reverse_enabled": s.is_reverse_enabled,
        "reverse_of_schedule_id": s.reverse_of_schedule_id,
        "is_active": s.is_active,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def _first_overlapping_schedule(
    tenant_id: str,
    academic_year_id: str,
    *,
    driver_id: Optional[str] = None,
    bus_id: Optional[str] = None,
    start_t: time,
    end_t: time,
    exclude_schedule_id: Optional[str] = None,
) -> Optional[TransportRouteSchedule]:
    q = TransportRouteSchedule.query.filter(
        TransportRouteSchedule.tenant_id == tenant_id,
        TransportRouteSchedule.academic_year_id == academic_year_id,
        TransportRouteSchedule.is_active.is_(True),
        TransportRouteSchedule.start_time < end_t,
        TransportRouteSchedule.end_time > start_t,
    )
    if driver_id:
        q = q.filter(TransportRouteSchedule.driver_id == driver_id)
    if bus_id:
        q = q.filter(TransportRouteSchedule.bus_id == bus_id)
    if exclude_schedule_id:
        q = q.filter(TransportRouteSchedule.id != exclude_schedule_id)
    return q.first()


def _driver_conflict_payload(
    row: TransportRouteSchedule, new_start: time, new_end: time
) -> Dict[str, Any]:
    rte = TransportRoute.query.filter_by(id=row.route_id).first()
    rname = rte.name if rte else "another route"
    ov_s = max(new_start, row.start_time)
    ov_e = min(new_end, row.end_time)
    return {
        "conflicting_schedule_id": row.id,
        "route_name": rname,
        "overlap_start": _fmt_hhmm(ov_s),
        "overlap_end": _fmt_hhmm(ov_e),
    }


def _bus_conflict_payload(
    row: TransportRouteSchedule, new_start: time, new_end: time
) -> Dict[str, Any]:
    rte = TransportRoute.query.filter_by(id=row.route_id).first()
    rname = rte.name if rte else "another route"
    ov_s = max(new_start, row.start_time)
    ov_e = min(new_end, row.end_time)
    return {
        "conflicting_schedule_id": row.id,
        "route_name": rname,
        "overlap_start": _fmt_hhmm(ov_s),
        "overlap_end": _fmt_hhmm(ov_e),
    }


ScheduleError = Union[str, Tuple[str, str]]


def check_schedule_conflicts(
    payload: Dict[str, Any],
    *,
    exclude_schedule_id: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], ScheduleError]:
    """Dry-run overlap detection for driver and bus (primary window; reverse pair if requested)."""
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None, "Tenant context is required"
    rte_chk = TransportRoute.query.filter_by(id=payload["route_id"], tenant_id=tenant_id).first()
    if not rte_chk:
        return None, "Route not found"
    if rte_chk.status != "active":
        return None, INACTIVE_ROUTE_OPERATION_MSG
    st = payload["start_time"]
    et = payload["end_time"]
    ay = payload["academic_year_id"]
    driver_id = payload["driver_id"]
    bus_id = payload["bus_id"]

    def _check_window(w_start: time, w_end: time) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        d_row = _first_overlapping_schedule(
            tenant_id,
            ay,
            driver_id=driver_id,
            start_t=w_start,
            end_t=w_end,
            exclude_schedule_id=exclude_schedule_id,
        )
        b_row = _first_overlapping_schedule(
            tenant_id,
            ay,
            bus_id=bus_id,
            start_t=w_start,
            end_t=w_end,
            exclude_schedule_id=exclude_schedule_id,
        )
        dc = _driver_conflict_payload(d_row, w_start, w_end) if d_row else None
        bc = _bus_conflict_payload(b_row, w_start, w_end) if b_row else None
        return dc, bc

    dc, bc = _check_window(st, et)
    if payload.get("pair_reverse"):
        route = TransportRoute.query.filter_by(id=payload["route_id"], tenant_id=tenant_id).first()
        rev_s = payload.get("reverse_start_time")
        rev_e = payload.get("reverse_end_time")
        if route and route.is_reverse_enabled and (rev_s is None or rev_e is None):
            inf_s, inf_e = _infer_reverse_times_from_junction(tenant_id, route.id)
            if inf_s is not None and inf_e is not None:
                rev_s, rev_e = inf_s, inf_e
        if rev_s is not None and rev_e is not None and rev_s < rev_e:
            d2, b2 = _check_window(rev_s, rev_e)
            dc = dc or d2
            bc = bc or b2

    if not dc and not bc:
        return {"has_conflict": False}, None

    out: Dict[str, Any] = {"has_conflict": True, "driver_conflict": dc, "bus_conflict": bc}
    return out, None


def list_schedules(
    academic_year_id: str,
    *,
    route_id: Optional[str] = None,
    bus_id: Optional[str] = None,
    driver_id: Optional[str] = None,
    shift_type: Optional[str] = None,
    is_active: Optional[bool] = True,
) -> List[Dict[str, Any]]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return []
    q = TransportRouteSchedule.query.filter_by(
        tenant_id=tenant_id, academic_year_id=academic_year_id
    )
    if route_id:
        q = q.filter_by(route_id=route_id)
    if bus_id:
        q = q.filter_by(bus_id=bus_id)
    if driver_id:
        q = q.filter_by(driver_id=driver_id)
    if shift_type:
        q = q.filter_by(shift_type=shift_type)
    if is_active is not None:
        q = q.filter_by(is_active=is_active)
    rows = (
        q.options(
            joinedload(TransportRouteSchedule.route),
            joinedload(TransportRouteSchedule.bus),
            joinedload(TransportRouteSchedule.driver),
            joinedload(TransportRouteSchedule.helper),
        )
        .order_by(TransportRouteSchedule.start_time, TransportRouteSchedule.id)
        .all()
    )
    return [_schedule_to_dict(x) for x in rows]


def get_schedule(schedule_id: str) -> Optional[Dict[str, Any]]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None
    s = (
        TransportRouteSchedule.query.filter_by(id=schedule_id, tenant_id=tenant_id)
        .options(
            joinedload(TransportRouteSchedule.route),
            joinedload(TransportRouteSchedule.bus),
            joinedload(TransportRouteSchedule.driver),
            joinedload(TransportRouteSchedule.helper),
        )
        .first()
    )
    if not s:
        return None
    return _schedule_to_dict(s)


def create_schedule(payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], ScheduleError]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None, "Tenant context is required"

    route = TransportRoute.query.filter_by(id=payload["route_id"], tenant_id=tenant_id).first()
    if not route:
        return None, "Route not found"
    if route.status != "active":
        return None, INACTIVE_ROUTE_OPERATION_MSG
    bus = TransportBus.query.filter_by(id=payload["bus_id"], tenant_id=tenant_id).first()
    if not bus or bus.status != "active":
        return None, "Bus not found or inactive"
    driver = TransportDriver.query.filter_by(id=payload["driver_id"], tenant_id=tenant_id).first()
    if not driver or driver.status != "active":
        return None, "Driver not found or inactive"
    ay = AcademicYear.query.filter_by(id=payload["academic_year_id"], tenant_id=tenant_id).first()
    if not ay:
        return None, "Academic year not found"

    helper_id = payload.get("helper_id")
    if helper_id:
        h = TransportStaff.query.filter_by(id=helper_id, tenant_id=tenant_id).first()
        if not h or h.status != "active":
            return None, "Helper staff not found or inactive"
        if h.role not in HELPER_ROLES:
            return None, "Helper must have role helper or attendant"

    pair_reverse = bool(payload.get("pair_reverse"))
    rev_start = payload.get("reverse_start_time")
    rev_end = payload.get("reverse_end_time")

    if pair_reverse:
        if not route.is_reverse_enabled:
            return None, "Route does not have reverse scheduling enabled"
        if rev_start is None or rev_end is None:
            inf_s, inf_e = _infer_reverse_times_from_junction(tenant_id, route.id)
            if inf_s is not None and inf_e is not None:
                rev_start, rev_end = inf_s, inf_e
            else:
                return None, "reverse_start_time and reverse_end_time are required when junction drop times cannot be inferred"

    st = payload["start_time"]
    et = payload["end_time"]

    d_row = _first_overlapping_schedule(
        tenant_id, payload["academic_year_id"], driver_id=payload["driver_id"], start_t=st, end_t=et
    )
    if d_row:
        rte = TransportRoute.query.filter_by(id=d_row.route_id).first()
        rname = rte.name if rte else "another route"
        msg = (
            f"{driver.name} is already assigned to '{rname}' "
            f"({_fmt_hhmm(d_row.start_time)}–{_fmt_hhmm(d_row.end_time)}). "
            "Choose a different time or driver."
        )
        return None, ("DriverScheduleConflict", msg)

    b_row = _first_overlapping_schedule(
        tenant_id, payload["academic_year_id"], bus_id=payload["bus_id"], start_t=st, end_t=et
    )
    if b_row:
        rte = TransportRoute.query.filter_by(id=b_row.route_id).first()
        rname = rte.name if rte else "another route"
        msg = (
            f"Bus {bus.bus_number} is already assigned to '{rname}' "
            f"({_fmt_hhmm(b_row.start_time)}–{_fmt_hhmm(b_row.end_time)}). "
            "Choose a different time or bus."
        )
        return None, ("BusScheduleConflict", msg)

    if pair_reverse and rev_start is not None and rev_end is not None:
        if rev_start >= rev_end:
            return None, "reverse_end_time must be after reverse_start_time"
        d2 = _first_overlapping_schedule(
            tenant_id,
            payload["academic_year_id"],
            driver_id=payload["driver_id"],
            start_t=rev_start,
            end_t=rev_end,
        )
        if d2:
            rte = TransportRoute.query.filter_by(id=d2.route_id).first()
            rname = rte.name if rte else "another route"
            msg = (
                f"{driver.name} is already assigned to '{rname}' "
                f"({_fmt_hhmm(d2.start_time)}–{_fmt_hhmm(d2.end_time)}) for the reverse window."
            )
            return None, ("DriverScheduleConflict", msg)
        b2 = _first_overlapping_schedule(
            tenant_id,
            payload["academic_year_id"],
            bus_id=payload["bus_id"],
            start_t=rev_start,
            end_t=rev_end,
        )
        if b2:
            rte = TransportRoute.query.filter_by(id=b2.route_id).first()
            rname = rte.name if rte else "another route"
            msg = (
                f"Bus {bus.bus_number} is already assigned to '{rname}' "
                f"({_fmt_hhmm(b2.start_time)}–{_fmt_hhmm(b2.end_time)}) for the reverse window."
            )
            return None, ("BusScheduleConflict", msg)

    primary = TransportRouteSchedule(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        route_id=payload["route_id"],
        bus_id=payload["bus_id"],
        driver_id=payload["driver_id"],
        helper_id=helper_id,
        shift_type=payload["shift_type"],
        start_time=st,
        end_time=et,
        academic_year_id=payload["academic_year_id"],
        is_reverse_enabled=pair_reverse,
        reverse_of_schedule_id=None,
        is_active=True,
    )
    db.session.add(primary)
    db.session.flush()

    reverse_sched = None
    if pair_reverse and rev_start is not None and rev_end is not None:
        reverse_sched = TransportRouteSchedule(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            route_id=payload["route_id"],
            bus_id=payload["bus_id"],
            driver_id=payload["driver_id"],
            helper_id=helper_id,
            shift_type=_opposite_shift(payload["shift_type"]),
            start_time=rev_start,
            end_time=rev_end,
            academic_year_id=payload["academic_year_id"],
            is_reverse_enabled=False,
            reverse_of_schedule_id=primary.id,
            is_active=True,
        )
        db.session.add(reverse_sched)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return None, "Could not save schedule"

    db.session.refresh(primary)
    out: Dict[str, Any] = {"schedule": get_schedule(primary.id)}
    if reverse_sched:
        db.session.refresh(reverse_sched)
        out["reverse_schedule"] = get_schedule(reverse_sched.id)
    return out, None


def update_schedule(schedule_id: str, payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], ScheduleError]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None, "Tenant context is required"
    s = TransportRouteSchedule.query.filter_by(id=schedule_id, tenant_id=tenant_id).first()
    if not s:
        return None, "Schedule not found"

    route_id = payload.get("route_id", s.route_id)
    bus_id = payload.get("bus_id", s.bus_id)
    driver_id = payload.get("driver_id", s.driver_id)
    ay_id = payload.get("academic_year_id", s.academic_year_id)
    st = payload.get("start_time", s.start_time)
    et = payload.get("end_time", s.end_time)

    if "route_id" in payload:
        rte = TransportRoute.query.filter_by(id=route_id, tenant_id=tenant_id).first()
        if not rte:
            return None, "Route not found"
        if rte.status != "active":
            return None, INACTIVE_ROUTE_OPERATION_MSG
    if "bus_id" in payload:
        bus = TransportBus.query.filter_by(id=bus_id, tenant_id=tenant_id).first()
        if not bus or bus.status != "active":
            return None, "Bus not found or inactive"
    if "driver_id" in payload:
        drv = TransportDriver.query.filter_by(id=driver_id, tenant_id=tenant_id).first()
        if not drv or drv.status != "active":
            return None, "Driver not found or inactive"
    if "helper_id" in payload:
        hid = (payload.get("helper_id") or "").strip() or None
        if hid:
            h = TransportStaff.query.filter_by(id=hid, tenant_id=tenant_id).first()
            if not h or h.status != "active" or h.role not in HELPER_ROLES:
                return None, "Helper staff not found, inactive, or invalid role"
        s.helper_id = hid
    if "academic_year_id" in payload:
        ay = AcademicYear.query.filter_by(id=ay_id, tenant_id=tenant_id).first()
        if not ay:
            return None, "Academic year not found"

    if "shift_type" in payload:
        s.shift_type = payload["shift_type"]
    if "route_id" in payload:
        s.route_id = route_id
    if "bus_id" in payload:
        s.bus_id = bus_id
    if "driver_id" in payload:
        s.driver_id = driver_id
    if "academic_year_id" in payload:
        s.academic_year_id = ay_id
    if "start_time" in payload:
        s.start_time = st
    if "end_time" in payload:
        s.end_time = et

    d_row = _first_overlapping_schedule(
        tenant_id,
        s.academic_year_id,
        driver_id=s.driver_id,
        start_t=s.start_time,
        end_t=s.end_time,
        exclude_schedule_id=s.id,
    )
    if d_row:
        drv = TransportDriver.query.filter_by(id=s.driver_id, tenant_id=tenant_id).first()
        dname = drv.name if drv else "Driver"
        rte = TransportRoute.query.filter_by(id=d_row.route_id).first()
        rname = rte.name if rte else "another route"
        msg = (
            f"{dname} is already assigned to '{rname}' "
            f"({_fmt_hhmm(d_row.start_time)}–{_fmt_hhmm(d_row.end_time)})."
        )
        return None, ("DriverScheduleConflict", msg)

    b_row = _first_overlapping_schedule(
        tenant_id,
        s.academic_year_id,
        bus_id=s.bus_id,
        start_t=s.start_time,
        end_t=s.end_time,
        exclude_schedule_id=s.id,
    )
    if b_row:
        bus = TransportBus.query.filter_by(id=s.bus_id).first()
        bnum = bus.bus_number if bus else "Bus"
        rte = TransportRoute.query.filter_by(id=b_row.route_id).first()
        rname = rte.name if rte else "another route"
        msg = (
            f"{bnum} is already assigned to '{rname}' "
            f"({_fmt_hhmm(b_row.start_time)}–{_fmt_hhmm(b_row.end_time)})."
        )
        return None, ("BusScheduleConflict", msg)

    db.session.commit()
    return get_schedule(schedule_id), None


def deactivate_schedule(schedule_id: str) -> Tuple[bool, ScheduleError]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return False, "Tenant context is required"
    s = TransportRouteSchedule.query.filter_by(id=schedule_id, tenant_id=tenant_id).first()
    if not s:
        return False, "Schedule not found"

    ids = {s.id}
    if s.reverse_of_schedule_id:
        ids.add(s.reverse_of_schedule_id)
    for ch in TransportRouteSchedule.query.filter_by(
        tenant_id=tenant_id, reverse_of_schedule_id=s.id
    ).all():
        ids.add(ch.id)

    for sid in ids:
        row = TransportRouteSchedule.query.filter_by(id=sid, tenant_id=tenant_id).first()
        if row:
            row.is_active = False
    db.session.commit()
    return True, None


def _exception_to_dict(ex: TransportScheduleException) -> Dict[str, Any]:
    route_min = {"id": ex.route.id, "name": ex.route.name} if ex.route else None
    bus_min = {"id": ex.bus.id, "bus_number": ex.bus.bus_number} if ex.bus else None
    driver_min = {"id": ex.driver.id, "name": ex.driver.name} if ex.driver else None
    helper_min = {"id": ex.helper.id, "name": ex.helper.name} if ex.helper else None
    sched_min = None
    if ex.target_schedule:
        tr = ex.target_schedule.route
        route_s = {"id": tr.id, "name": tr.name} if tr else None
        sched_min = {
            "id": ex.target_schedule.id,
            "route": route_s,
            "shift_type": ex.target_schedule.shift_type,
            "start_time": _fmt_hhmm(ex.target_schedule.start_time),
            "end_time": _fmt_hhmm(ex.target_schedule.end_time),
        }
    return {
        "id": ex.id,
        "academic_year_id": ex.academic_year_id,
        "exception_date": ex.exception_date.isoformat(),
        "exception_type": ex.exception_type,
        "route": route_min,
        "bus": bus_min,
        "driver": driver_min,
        "helper": helper_min,
        "shift_type": ex.shift_type,
        "start_time": _fmt_hhmm(ex.start_time) if ex.start_time else None,
        "end_time": _fmt_hhmm(ex.end_time) if ex.end_time else None,
        "reason": ex.reason,
        "schedule_id": ex.schedule_id,
        "schedule": sched_min,
        "created_at": ex.created_at.isoformat() if ex.created_at else None,
    }


def _existing_exception_for_route_shift(
    tenant_id: str,
    academic_year_id: str,
    exception_date: date,
    route_id: str,
    shift_type: Optional[str],
    *,
    exclude_exception_id: Optional[str] = None,
) -> Optional[TransportScheduleException]:
    if not route_id or not shift_type:
        return None
    q = TransportScheduleException.query.filter_by(
        tenant_id=tenant_id,
        academic_year_id=academic_year_id,
        exception_date=exception_date,
        route_id=route_id,
        shift_type=shift_type,
    )
    if exclude_exception_id:
        q = q.filter(TransportScheduleException.id != exclude_exception_id)
    return q.first()


def _first_overlapping_exception_for_driver(
    tenant_id: str,
    academic_year_id: str,
    exception_date: date,
    driver_id: str,
    start_t: time,
    end_t: time,
    *,
    exclude_exception_id: Optional[str] = None,
) -> Optional[TransportScheduleException]:
    q = TransportScheduleException.query.filter(
        TransportScheduleException.tenant_id == tenant_id,
        TransportScheduleException.academic_year_id == academic_year_id,
        TransportScheduleException.exception_date == exception_date,
        TransportScheduleException.exception_type == "override",
        TransportScheduleException.driver_id == driver_id,
        TransportScheduleException.start_time.isnot(None),
        TransportScheduleException.end_time.isnot(None),
        TransportScheduleException.start_time < end_t,
        TransportScheduleException.end_time > start_t,
    )
    if exclude_exception_id:
        q = q.filter(TransportScheduleException.id != exclude_exception_id)
    return q.first()


def _first_overlapping_exception_for_bus(
    tenant_id: str,
    academic_year_id: str,
    exception_date: date,
    bus_id: str,
    start_t: time,
    end_t: time,
    *,
    exclude_exception_id: Optional[str] = None,
) -> Optional[TransportScheduleException]:
    q = TransportScheduleException.query.filter(
        TransportScheduleException.tenant_id == tenant_id,
        TransportScheduleException.academic_year_id == academic_year_id,
        TransportScheduleException.exception_date == exception_date,
        TransportScheduleException.exception_type == "override",
        TransportScheduleException.bus_id == bus_id,
        TransportScheduleException.start_time.isnot(None),
        TransportScheduleException.end_time.isnot(None),
        TransportScheduleException.start_time < end_t,
        TransportScheduleException.end_time > start_t,
    )
    if exclude_exception_id:
        q = q.filter(TransportScheduleException.id != exclude_exception_id)
    return q.first()


def list_schedule_exceptions(
    academic_year_id: str,
    *,
    exception_date: Optional[date] = None,
    exception_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return []
    q = TransportScheduleException.query.filter_by(
        tenant_id=tenant_id, academic_year_id=academic_year_id
    )
    if exception_date:
        q = q.filter_by(exception_date=exception_date)
    if exception_type:
        q = q.filter_by(exception_type=exception_type)
    rows = (
        q.options(
            joinedload(TransportScheduleException.route),
            joinedload(TransportScheduleException.bus),
            joinedload(TransportScheduleException.driver),
            joinedload(TransportScheduleException.helper),
            joinedload(TransportScheduleException.target_schedule).joinedload(
                TransportRouteSchedule.route
            ),
        )
        .order_by(
            TransportScheduleException.exception_date.desc(),
            TransportScheduleException.created_at.desc(),
        )
        .all()
    )
    return [_exception_to_dict(x) for x in rows]


def create_schedule_exception(payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], ScheduleError]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None, "Tenant context is required"

    ay = AcademicYear.query.filter_by(id=payload["academic_year_id"], tenant_id=tenant_id).first()
    if not ay:
        return None, "Academic year not found"

    if payload["exception_type"] == "cancellation":
        sched = TransportRouteSchedule.query.filter_by(
            id=payload["schedule_id"], tenant_id=tenant_id
        ).first()
        if not sched or not sched.is_active:
            return None, "Schedule not found or inactive"
        if sched.academic_year_id != payload["academic_year_id"]:
            return None, "Schedule does not belong to this academic year"

        if _existing_exception_for_route_shift(
            tenant_id,
            payload["academic_year_id"],
            payload["exception_date"],
            sched.route_id,
            sched.shift_type,
        ):
            return None, "An exception already exists for this route and shift on this date"

        ex = TransportScheduleException(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            academic_year_id=payload["academic_year_id"],
            exception_date=payload["exception_date"],
            exception_type="cancellation",
            route_id=sched.route_id,
            bus_id=None,
            driver_id=None,
            helper_id=None,
            shift_type=sched.shift_type,
            start_time=None,
            end_time=None,
            schedule_id=sched.id,
            reason=payload.get("reason"),
        )
        db.session.add(ex)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return None, "Could not save exception"
        db.session.refresh(ex)
        ex2 = (
            TransportScheduleException.query.filter_by(id=ex.id, tenant_id=tenant_id)
            .options(
                joinedload(TransportScheduleException.route),
                joinedload(TransportScheduleException.bus),
                joinedload(TransportScheduleException.driver),
                joinedload(TransportScheduleException.helper),
                joinedload(TransportScheduleException.target_schedule).joinedload(
                    TransportRouteSchedule.route
                ),
            )
            .first()
        )
        return _exception_to_dict(ex2) if ex2 else _exception_to_dict(ex), None

    route = TransportRoute.query.filter_by(id=payload["route_id"], tenant_id=tenant_id).first()
    if not route:
        return None, "Route not found"
    if route.status != "active":
        return None, INACTIVE_ROUTE_OPERATION_MSG
    bus = TransportBus.query.filter_by(id=payload["bus_id"], tenant_id=tenant_id).first()
    if not bus or bus.status != "active":
        return None, "Bus not found or inactive"
    driver = TransportDriver.query.filter_by(id=payload["driver_id"], tenant_id=tenant_id).first()
    if not driver or driver.status != "active":
        return None, "Driver not found or inactive"

    helper_id = payload.get("helper_id")
    if helper_id:
        h = TransportStaff.query.filter_by(id=helper_id, tenant_id=tenant_id).first()
        if not h or h.status != "active":
            return None, "Helper staff not found or inactive"
        if h.role not in HELPER_ROLES:
            return None, "Helper must have role helper or attendant"

    if _existing_exception_for_route_shift(
        tenant_id,
        payload["academic_year_id"],
        payload["exception_date"],
        payload["route_id"],
        payload["shift_type"],
    ):
        return None, "An exception already exists for this route and shift on this date"

    st = payload["start_time"]
    et = payload["end_time"]

    d_row = _first_overlapping_schedule(
        tenant_id,
        payload["academic_year_id"],
        driver_id=payload["driver_id"],
        start_t=st,
        end_t=et,
    )
    if d_row:
        rte = TransportRoute.query.filter_by(id=d_row.route_id).first()
        rname = rte.name if rte else "another route"
        msg = (
            f"{driver.name} is already assigned to '{rname}' "
            f"({_fmt_hhmm(d_row.start_time)}–{_fmt_hhmm(d_row.end_time)}). "
            "Choose a different time or driver."
        )
        return None, ("DriverScheduleConflict", msg)

    b_row = _first_overlapping_schedule(
        tenant_id,
        payload["academic_year_id"],
        bus_id=payload["bus_id"],
        start_t=st,
        end_t=et,
    )
    if b_row:
        rte = TransportRoute.query.filter_by(id=b_row.route_id).first()
        rname = rte.name if rte else "another route"
        msg = (
            f"Bus {bus.bus_number} is already assigned to '{rname}' "
            f"({_fmt_hhmm(b_row.start_time)}–{_fmt_hhmm(b_row.end_time)}). "
            "Choose a different time or bus."
        )
        return None, ("BusScheduleConflict", msg)

    ex_d = _first_overlapping_exception_for_driver(
        tenant_id,
        payload["academic_year_id"],
        payload["exception_date"],
        payload["driver_id"],
        st,
        et,
    )
    if ex_d:
        rte = TransportRoute.query.filter_by(id=ex_d.route_id).first() if ex_d.route_id else None
        rname = rte.name if rte else "another route"
        msg = (
            f"{driver.name} already has another override on this date "
            f"({_fmt_hhmm(ex_d.start_time)}–{_fmt_hhmm(ex_d.end_time)}) for '{rname}'."
        )
        return None, ("DriverScheduleConflict", msg)

    ex_b = _first_overlapping_exception_for_bus(
        tenant_id,
        payload["academic_year_id"],
        payload["exception_date"],
        payload["bus_id"],
        st,
        et,
    )
    if ex_b:
        rte = TransportRoute.query.filter_by(id=ex_b.route_id).first() if ex_b.route_id else None
        rname = rte.name if rte else "another route"
        msg = (
            f"Bus {bus.bus_number} already has another override on this date "
            f"({_fmt_hhmm(ex_b.start_time)}–{_fmt_hhmm(ex_b.end_time)}) for '{rname}'."
        )
        return None, ("BusScheduleConflict", msg)

    ex = TransportScheduleException(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        academic_year_id=payload["academic_year_id"],
        exception_date=payload["exception_date"],
        exception_type="override",
        route_id=payload["route_id"],
        bus_id=payload["bus_id"],
        driver_id=payload["driver_id"],
        helper_id=helper_id,
        shift_type=payload["shift_type"],
        start_time=st,
        end_time=et,
        schedule_id=None,
        reason=payload.get("reason"),
    )
    db.session.add(ex)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return None, "Could not save exception"
    db.session.refresh(ex)
    ex2 = (
        TransportScheduleException.query.filter_by(id=ex.id, tenant_id=tenant_id)
        .options(
            joinedload(TransportScheduleException.route),
            joinedload(TransportScheduleException.bus),
            joinedload(TransportScheduleException.driver),
            joinedload(TransportScheduleException.helper),
            joinedload(TransportScheduleException.target_schedule).joinedload(
                TransportRouteSchedule.route
            ),
        )
        .first()
    )
    return _exception_to_dict(ex2) if ex2 else _exception_to_dict(ex), None


def delete_schedule_exception(exception_id: str) -> Tuple[bool, ScheduleError]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return False, "Tenant context is required"
    ex = TransportScheduleException.query.filter_by(id=exception_id, tenant_id=tenant_id).first()
    if not ex:
        return False, "Exception not found"
    db.session.delete(ex)
    db.session.commit()
    return True, None


def _minutes_span(st: time, et: time) -> int:
    a = datetime.combine(date.today(), st)
    b = datetime.combine(date.today(), et)
    return max(0, int((b - a).total_seconds() // 60))


def _duty_display(total_minutes: int) -> str:
    if total_minutes <= 0:
        return "0m"
    h, m = divmod(total_minutes, 60)
    if h and m:
        return f"{h}h {m}m"
    if h:
        return f"{h}h"
    return f"{m}m"


def _is_calendar_holiday(tenant_id: str, d: date, academic_year_id: str) -> bool:
    """True if tenant has a holiday that applies to this calendar date."""
    try:
        from modules.holidays.models import Holiday
    except ImportError:
        return False

    rows = Holiday.query.filter_by(tenant_id=tenant_id).filter(
        or_(Holiday.academic_year_id == academic_year_id, Holiday.academic_year_id.is_(None))
    ).all()
    wd = d.weekday()  # Mon=0 … Sun=6 — matches Holiday.recurring_day_of_week
    for h in rows:
        if h.is_recurring and h.recurring_day_of_week is not None:
            if wd == h.recurring_day_of_week:
                return True
            continue
        if h.start_date:
            hend = h.end_date or h.start_date
            if h.start_date <= d <= hend:
                return True
    return False


def _cancellation_schedule_ids_for_date(
    tenant_id: str, academic_year_id: str, on_date: date
) -> set:
    rows = TransportScheduleException.query.filter_by(
        tenant_id=tenant_id,
        academic_year_id=academic_year_id,
        exception_date=on_date,
        exception_type="cancellation",
    ).all()
    return {r.schedule_id for r in rows if r.schedule_id}


def _schedule_timeline_for_bus(
    tenant_id: str,
    bus_id: str,
    academic_year_id: str,
    on_date: date,
) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Effective segments for this bus on a calendar day: recurring schedules minus
    cancellation exceptions; recurring suppressed on calendar holidays; override
    exceptions always included when they target this bus.
    """
    calendar_holiday = _is_calendar_holiday(tenant_id, on_date, academic_year_id)
    cancelled_ids = _cancellation_schedule_ids_for_date(tenant_id, academic_year_id, on_date)

    recurring_segments: List[Dict[str, Any]] = []
    if not calendar_holiday:
        rows = (
            TransportRouteSchedule.query.filter(
                TransportRouteSchedule.tenant_id == tenant_id,
                TransportRouteSchedule.bus_id == bus_id,
                TransportRouteSchedule.academic_year_id == academic_year_id,
                TransportRouteSchedule.is_active.is_(True),
            )
            .options(
                joinedload(TransportRouteSchedule.route),
                joinedload(TransportRouteSchedule.driver),
            )
            .order_by(TransportRouteSchedule.start_time, TransportRouteSchedule.id)
            .all()
        )
        for row in rows:
            if row.id in cancelled_ids:
                continue
            rte = row.route
            if not rte or rte.status != "active":
                continue
            drv = row.driver
            recurring_segments.append(
                {
                    "schedule_id": row.id,
                    "exception_id": None,
                    "route": {"id": rte.id, "name": rte.name} if rte else None,
                    "driver": {"id": drv.id, "name": drv.name} if drv else None,
                    "shift_type": row.shift_type,
                    "start_time": _fmt_hhmm(row.start_time),
                    "end_time": _fmt_hhmm(row.end_time),
                    "is_exception": False,
                }
            )

    override_segments: List[Dict[str, Any]] = []
    ovr = (
        TransportScheduleException.query.filter(
            TransportScheduleException.tenant_id == tenant_id,
            TransportScheduleException.academic_year_id == academic_year_id,
            TransportScheduleException.exception_date == on_date,
            TransportScheduleException.exception_type == "override",
            TransportScheduleException.bus_id == bus_id,
        )
        .options(
            joinedload(TransportScheduleException.route),
            joinedload(TransportScheduleException.driver),
        )
        .order_by(
            TransportScheduleException.start_time,
            TransportScheduleException.id,
        )
        .all()
    )
    for ex in ovr:
        if not ex.start_time or not ex.end_time or not ex.shift_type:
            continue
        rte = ex.route
        if rte and rte.status != "active":
            continue
        drv = ex.driver
        override_segments.append(
            {
                "schedule_id": None,
                "exception_id": ex.id,
                "route": {"id": rte.id, "name": rte.name} if rte else None,
                "driver": {"id": drv.id, "name": drv.name} if drv else None,
                "shift_type": ex.shift_type,
                "start_time": _fmt_hhmm(ex.start_time),
                "end_time": _fmt_hhmm(ex.end_time),
                "is_exception": True,
            }
        )

    merged = recurring_segments + override_segments
    merged.sort(
        key=lambda s: (s["start_time"], s.get("schedule_id") or "", s.get("exception_id") or "")
    )
    return merged, calendar_holiday


def get_driver_workload(
    staff_id: str,
    *,
    on_date: Optional[date] = None,
    academic_year_id: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Aggregates effective route segments for transport staff (driver or helper) on a date:
    recurring schedules (minus per-day cancellations), suppressed on calendar holidays,
    plus override exceptions where this staff is driver or helper.
    """
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None, "Tenant context is required"
    if not academic_year_id or not str(academic_year_id).strip():
        return None, "academic_year_id is required"

    legacy_driver = TransportDriver.query.filter_by(id=staff_id, tenant_id=tenant_id).first()
    staff = TransportStaff.query.filter_by(id=staff_id, tenant_id=tenant_id).first()
    if legacy_driver:
        staff_payload: Dict[str, Any] = {**legacy_driver.to_dict(), "role": "driver"}
    elif staff:
        staff_payload = staff.to_dict()
    else:
        return None, "Staff not found"

    d = on_date or date.today()
    ay_id = str(academic_year_id).strip()
    ay = AcademicYear.query.filter_by(id=ay_id, tenant_id=tenant_id).first()
    if not ay:
        return None, "Academic year not found"

    is_holiday = _is_calendar_holiday(tenant_id, d, ay_id)
    cancelled_ids = _cancellation_schedule_ids_for_date(tenant_id, ay_id, d)

    sched_rows = (
        TransportRouteSchedule.query.filter(
            TransportRouteSchedule.tenant_id == tenant_id,
            TransportRouteSchedule.academic_year_id == ay_id,
            TransportRouteSchedule.is_active.is_(True),
            or_(
                TransportRouteSchedule.driver_id == staff_id,
                TransportRouteSchedule.helper_id == staff_id,
            ),
        )
        .options(
            joinedload(TransportRouteSchedule.route),
            joinedload(TransportRouteSchedule.bus),
        )
        .order_by(TransportRouteSchedule.start_time, TransportRouteSchedule.id)
        .all()
    )

    recurring_segments: List[Dict[str, Any]] = []
    if not is_holiday:
        for row in sched_rows:
            if row.id in cancelled_ids:
                continue
            rte = row.route
            if not rte or rte.status != "active":
                continue
            bus = row.bus
            recurring_segments.append(
                {
                    "schedule_id": row.id,
                    "exception_id": None,
                    "route": {"id": rte.id, "name": rte.name} if rte else None,
                    "bus": {"id": bus.id, "bus_number": bus.bus_number} if bus else None,
                    "shift_type": row.shift_type,
                    "start_time": _fmt_hhmm(row.start_time),
                    "end_time": _fmt_hhmm(row.end_time),
                    "is_exception": False,
                }
            )

    override_segments: List[Dict[str, Any]] = []
    ovr_rows = (
        TransportScheduleException.query.filter(
            TransportScheduleException.tenant_id == tenant_id,
            TransportScheduleException.academic_year_id == ay_id,
            TransportScheduleException.exception_date == d,
            TransportScheduleException.exception_type == "override",
            or_(
                TransportScheduleException.driver_id == staff_id,
                TransportScheduleException.helper_id == staff_id,
            ),
        )
        .options(
            joinedload(TransportScheduleException.route),
            joinedload(TransportScheduleException.bus),
        )
        .order_by(
            TransportScheduleException.start_time,
            TransportScheduleException.id,
        )
        .all()
    )
    for ex in ovr_rows:
        if not ex.start_time or not ex.end_time or not ex.shift_type:
            continue
        rte = ex.route
        if rte and rte.status != "active":
            continue
        bus = ex.bus
        override_segments.append(
            {
                "schedule_id": None,
                "exception_id": ex.id,
                "route": {"id": rte.id, "name": rte.name} if rte else None,
                "bus": {"id": bus.id, "bus_number": bus.bus_number} if bus else None,
                "shift_type": ex.shift_type,
                "start_time": _fmt_hhmm(ex.start_time),
                "end_time": _fmt_hhmm(ex.end_time),
                "is_exception": True,
            }
        )

    schedules_today = recurring_segments + override_segments
    schedules_today.sort(
        key=lambda s: (s["start_time"], s.get("schedule_id") or "", s.get("exception_id") or "")
    )

    bus_ids: set[str] = set()
    route_ids: set[str] = set()
    total_minutes = 0
    now_t = datetime.now().time()
    upcoming_count = 0
    for seg in schedules_today:
        stp = _parse_hhmm(seg["start_time"])
        etp = _parse_hhmm(seg["end_time"])
        if stp and etp:
            total_minutes += _minutes_span(stp, etp)
            if stp > now_t:
                upcoming_count += 1
        r = seg.get("route")
        if r and r.get("id"):
            route_ids.add(r["id"])
        b = seg.get("bus")
        if b and b.get("id"):
            bus_ids.add(b["id"])

    buses_assigned: List[Dict[str, Any]] = []
    if bus_ids:
        for bid in sorted(bus_ids):
            b = TransportBus.query.filter_by(id=bid, tenant_id=tenant_id).first()
            if b:
                buses_assigned.append(
                    {"id": b.id, "bus_number": b.bus_number, "capacity": b.capacity}
                )

    is_idle = len(schedules_today) == 0 and not is_holiday

    out = {
        "staff": staff_payload,
        "workload": {
            "date": d.isoformat(),
            "assigned_routes_today": len(route_ids),
            "total_duty_minutes": total_minutes,
            "total_duty_display": _duty_display(total_minutes),
            "is_holiday": is_holiday,
            "is_idle": is_idle,
            "upcoming_duty_count": upcoming_count,
        },
        "schedules_today": schedules_today,
        "buses_assigned": buses_assigned,
    }
    return out, None


# ---------------------------------------------------------------------------
# Staff (helpers / attendants)
# ---------------------------------------------------------------------------


def list_staff(role: Optional[str] = None) -> List[Dict]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return []
    q = TransportStaff.query.filter_by(tenant_id=tenant_id)
    if role:
        q = q.filter_by(role=role)
    return [x.to_dict() for x in q.order_by(TransportStaff.name).all()]


def create_staff_member(payload: Dict) -> Tuple[Optional[Dict], Optional[str]]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None, "Tenant context is required"
    role = payload.get("role", "helper")
    if role not in HELPER_ROLES and role != "driver":
        return None, "role must be driver, helper, or attendant"
    s = TransportStaff(
        tenant_id=tenant_id,
        name=payload["name"],
        phone=payload.get("phone"),
        alternate_phone=payload.get("alternate_phone"),
        role=role,
        license_number=payload.get("license_number"),
        address=payload.get("address"),
        status=payload.get("status", "active"),
    )
    db.session.add(s)
    db.session.commit()
    return s.to_dict(), None


def update_staff_member(staff_id: str, payload: Dict) -> Tuple[Optional[Dict], Optional[str]]:
    tenant_id = get_tenant_id()
    s = TransportStaff.query.filter_by(id=staff_id, tenant_id=tenant_id).first()
    if not s:
        return None, "Staff not found"
    for k in ("name", "phone", "alternate_phone", "license_number", "address", "status", "role"):
        if k in payload and payload[k] is not None:
            setattr(s, k, payload[k])
    db.session.commit()
    return s.to_dict(), None


def deactivate_staff_member(staff_id: str) -> Tuple[bool, Optional[str]]:
    tenant_id = get_tenant_id()
    s = TransportStaff.query.filter_by(id=staff_id, tenant_id=tenant_id).first()
    if not s:
        return False, "Staff not found"
    if TransportBusAssignment.query.filter_by(
        tenant_id=tenant_id, helper_staff_id=staff_id, status="active"
    ).count():
        return False, "Cannot deactivate staff while assigned as helper on an active assignment"
    s.status = "inactive"
    db.session.commit()
    return True, None


# ---------------------------------------------------------------------------
# CSV exports
# ---------------------------------------------------------------------------


def _csv_row(cells: List[str]) -> str:
    def esc(x: str) -> str:
        x = x.replace('"', '""')
        if "," in x or "\n" in x or '"' in x:
            return f'"{x}"'
        return x

    return ",".join(esc(str(c or "")) for c in cells) + "\n"


def export_bus_students_csv(bus_id: str, academic_year_id: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None, "Tenant context is required"
    bus = TransportBus.query.filter_by(id=bus_id, tenant_id=tenant_id).first()
    if not bus:
        return None, "Bus not found"
    ay = academic_year_id or resolve_default_academic_year_id()
    on = _today()
    lines = [_csv_row(["admission_number", "student_name", "class", "route", "pickup", "drop", "guardian_name", "guardian_phone", "driver_phone", "helper_phone"])]
    assign = None
    for a in TransportBusAssignment.query.filter_by(tenant_id=tenant_id, bus_id=bus_id).all():
        if assignment_active_on(a, on):
            assign = a
            break
    drv_phone = assign.driver.phone if assign and assign.driver else ""
    hlp_phone = assign.helper.phone if assign and assign.helper else ""
    q = TransportEnrollment.query.options(
        joinedload(TransportEnrollment.route),
        joinedload(TransportEnrollment.pickup_stop),
        joinedload(TransportEnrollment.drop_stop),
        joinedload(TransportEnrollment.student).joinedload(Student.current_class),
        joinedload(TransportEnrollment.student).joinedload(Student.user),
    ).filter_by(tenant_id=tenant_id, bus_id=bus_id, status="active")
    if ay:
        q = q.filter(TransportEnrollment.academic_year_id == ay)
    for en in q.all():
        if not enrollment_active_on(en, on):
            continue
        st = en.student
        pu, dr = _pickup_drop_labels(en)
        cls_nm = ""
        if st and st.current_class:
            cls_nm = f"{st.current_class.name}-{st.current_class.section}"
        lines.append(
            _csv_row(
                [
                    st.admission_number if st else "",
                    st.user.name if st and st.user else "",
                    cls_nm,
                    en.route.name if en.route else "",
                    pu or "",
                    dr or "",
                    st.guardian_name if st else "",
                    st.guardian_phone if st else "",
                    drv_phone,
                    hlp_phone,
                ]
            )
        )
    return "".join(lines), None


def export_route_students_csv(route_id: str, academic_year_id: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None, "Tenant context is required"
    route = TransportRoute.query.filter_by(id=route_id, tenant_id=tenant_id).first()
    if not route:
        return None, "Route not found"
    ay = academic_year_id or resolve_default_academic_year_id()
    on = _today()
    lines = [_csv_row(["admission_number", "student_name", "class", "bus_number", "pickup", "drop", "guardian_name", "guardian_phone", "driver_phone", "helper_phone"])]
    q = TransportEnrollment.query.options(
        joinedload(TransportEnrollment.bus),
        joinedload(TransportEnrollment.pickup_stop),
        joinedload(TransportEnrollment.drop_stop),
        joinedload(TransportEnrollment.student).joinedload(Student.current_class),
        joinedload(TransportEnrollment.student).joinedload(Student.user),
    ).filter_by(tenant_id=tenant_id, route_id=route_id, status="active")
    if ay:
        q = q.filter(TransportEnrollment.academic_year_id == ay)
    for en in q.all():
        if not enrollment_active_on(en, on):
            continue
        st = en.student
        pu, dr = _pickup_drop_labels(en)
        cls_nm = ""
        if st and st.current_class:
            cls_nm = f"{st.current_class.name}-{st.current_class.section}"
        assign = get_active_assignment_for_bus_route(en.bus_id, route_id, on)
        drv_phone = assign.driver.phone if assign and assign.driver else ""
        hlp_phone = assign.helper.phone if assign and assign.helper else ""
        lines.append(
            _csv_row(
                [
                    st.admission_number if st else "",
                    st.user.name if st and st.user else "",
                    cls_nm,
                    en.bus.bus_number if en.bus else "",
                    pu or "",
                    dr or "",
                    st.guardian_name if st else "",
                    st.guardian_phone if st else "",
                    drv_phone,
                    hlp_phone,
                ]
            )
        )
    return "".join(lines), None


def export_contact_sheet_csv(academic_year_id: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """All active assignments with driver/helper phones."""
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None, "Tenant context is required"
    on = _today()
    lines = [_csv_row(["bus_number", "route", "driver_name", "driver_phone", "helper_name", "helper_phone"])]
    for a in TransportBusAssignment.query.options(
        joinedload(TransportBusAssignment.bus),
        joinedload(TransportBusAssignment.driver),
        joinedload(TransportBusAssignment.helper),
        joinedload(TransportBusAssignment.route),
    ).filter_by(tenant_id=tenant_id, status="active").all():
        if not assignment_active_on(a, on):
            continue
        lines.append(
            _csv_row(
                [
                    a.bus.bus_number if a.bus else "",
                    a.route.name if a.route else "",
                    a.driver.name if a.driver else "",
                    a.driver.phone if a.driver else "",
                    a.helper.name if a.helper else "",
                    a.helper.phone if a.helper else "",
                ]
            )
        )
    return "".join(lines), None


def get_route_with_stops(route_id: str) -> Tuple[Optional[Dict], Optional[str]]:
    tenant_id = get_tenant_id()
    r = TransportRoute.query.filter_by(id=route_id, tenant_id=tenant_id).first()
    if not r:
        return None, "Route not found"
    d = r.to_dict()
    d["stops"] = list_stops_for_route(route_id, include_inactive=True)
    return d, None
