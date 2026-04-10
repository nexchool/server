"""Transport HTTP API."""

from datetime import date

from flask import Response, request

from backend.core.decorators import (
    auth_required,
    require_any_permission,
    require_permission,
    tenant_required,
    require_plan_feature,
)
from backend.shared.helpers import (
    error_response,
    not_found_response,
    success_response,
    validation_error_response,
)

from . import schemas
from . import services
from .permissions import (
    TRANSPORT_ASSIGNMENTS_CREATE,
    TRANSPORT_ASSIGNMENTS_DELETE,
    TRANSPORT_ASSIGNMENTS_READ,
    TRANSPORT_ASSIGNMENTS_UPDATE,
    TRANSPORT_BUSES_CREATE,
    TRANSPORT_BUSES_DELETE,
    TRANSPORT_BUSES_READ,
    TRANSPORT_BUSES_UPDATE,
    TRANSPORT_DASHBOARD_READ,
    TRANSPORT_DRIVERS_CREATE,
    TRANSPORT_DRIVERS_DELETE,
    TRANSPORT_DRIVERS_READ,
    TRANSPORT_DRIVERS_UPDATE,
    TRANSPORT_ENROLLMENT_CREATE,
    TRANSPORT_ENROLLMENT_DELETE,
    TRANSPORT_ENROLLMENT_READ,
    TRANSPORT_ENROLLMENT_UPDATE,
    TRANSPORT_EXPORTS_READ,
    TRANSPORT_FEE_PLANS_MANAGE,
    TRANSPORT_FEE_PLANS_READ,
    TRANSPORT_ROUTES_CREATE,
    TRANSPORT_ROUTES_DELETE,
    TRANSPORT_ROUTES_READ,
    TRANSPORT_ROUTES_UPDATE,
    TRANSPORT_STOPS_CREATE,
    TRANSPORT_STOPS_DELETE,
    TRANSPORT_STOPS_READ,
    TRANSPORT_STOPS_UPDATE,
)
from . import transport_bp


def _err(msg: str, code: int = 400):
    return error_response("TransportError", msg, code)


def _validation_err(err):
    if err is None:
        return None
    if isinstance(err, dict):
        return _validation_err(err)
    return validation_error_response({"message": err})


def _csv_response(csv_text: str, filename: str):
    return Response(
        csv_text,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Buses
# ---------------------------------------------------------------------------


@transport_bp.route("/buses", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_any_permission(
    TRANSPORT_BUSES_READ,
    TRANSPORT_ENROLLMENT_READ,
    TRANSPORT_DASHBOARD_READ,
    TRANSPORT_ENROLLMENT_CREATE,
    TRANSPORT_ENROLLMENT_UPDATE,
    TRANSPORT_ASSIGNMENTS_READ,
)
def list_buses():
    ay = request.args.get("academic_year_id") or None
    return success_response(data=services.list_buses(academic_year_id=ay))


@transport_bp.route("/buses/<bus_id>", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_any_permission(
    TRANSPORT_BUSES_READ,
    TRANSPORT_ENROLLMENT_READ,
    TRANSPORT_DASHBOARD_READ,
)
def get_bus(bus_id):
    d = services.get_bus(bus_id)
    if not d:
        return not_found_response("Bus")
    return success_response(data=d)


@transport_bp.route("/buses/<bus_id>/details", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_any_permission(
    TRANSPORT_BUSES_READ,
    TRANSPORT_ENROLLMENT_READ,
    TRANSPORT_DASHBOARD_READ,
)
def get_bus_details(bus_id):
    ay = request.args.get("academic_year_id") or None
    dr = request.args.get("date") or None
    timeline_date = None
    if dr:
        try:
            timeline_date = date.fromisoformat(dr.strip())
        except ValueError:
            return validation_error_response({"date": "date must be YYYY-MM-DD"})
    data, err = services.get_bus_details(
        bus_id, academic_year_id=ay, timeline_date=timeline_date
    )
    if err:
        return _err(err, 404)
    return success_response(data=data)


@transport_bp.route("/buses/<bus_id>/export/students", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_EXPORTS_READ)
def export_bus_students(bus_id):
    ay = request.args.get("academic_year_id") or None
    csv_text, err = services.export_bus_students_csv(bus_id, academic_year_id=ay)
    if err:
        return _err(err, 404)
    return _csv_response(csv_text, f"transport-bus-{bus_id}-students.csv")


@transport_bp.route("/buses", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_BUSES_CREATE)
def create_bus():
    payload, err = schemas.validate_bus_payload(request.get_json() or {}, is_update=False)
    if err:
        return _validation_err(err)
    data, err = services.create_bus(payload)
    if err:
        return _err(err)
    return success_response(data=data, message="Bus created", status_code=201)


@transport_bp.route("/buses/<bus_id>", methods=["PUT"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_BUSES_UPDATE)
def update_bus(bus_id):
    raw = request.get_json() or {}
    payload, err = schemas.validate_bus_payload(raw, is_update=True)
    if err:
        return _validation_err(err)
    slim = {k: v for k, v in payload.items() if k in raw}
    data, err = services.update_bus(bus_id, slim)
    if err:
        return _err(err, 404 if "not found" in err.lower() else 400)
    return success_response(data=data)


@transport_bp.route("/buses/<bus_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_BUSES_DELETE)
def delete_bus(bus_id):
    ok, err = services.delete_bus(bus_id)
    if not ok:
        return _err(err or "Delete failed", 400)
    return success_response(message="Bus deleted")


# ---------------------------------------------------------------------------
# Drivers (legacy table)
# ---------------------------------------------------------------------------


@transport_bp.route("/drivers", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_any_permission(
    TRANSPORT_DRIVERS_READ,
    TRANSPORT_ENROLLMENT_READ,
    TRANSPORT_ASSIGNMENTS_READ,
    TRANSPORT_ASSIGNMENTS_CREATE,
)
def list_drivers():
    return success_response(data=services.list_drivers())


@transport_bp.route("/drivers/<driver_id>", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_any_permission(TRANSPORT_DRIVERS_READ, TRANSPORT_ASSIGNMENTS_READ)
def get_driver(driver_id):
    d = services.driver_crud_get(driver_id)
    if not d:
        return not_found_response("Driver")
    return success_response(data=d)


@transport_bp.route("/drivers", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_DRIVERS_CREATE)
def create_driver():
    payload, err = schemas.validate_driver_payload(request.get_json() or {}, is_update=False)
    if err:
        return _validation_err(err)
    data, err = services.create_driver(payload)
    if err:
        return _err(err)
    return success_response(data=data, message="Driver created", status_code=201)


@transport_bp.route("/drivers/<driver_id>", methods=["PUT"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_DRIVERS_UPDATE)
def update_driver(driver_id):
    raw = request.get_json() or {}
    payload, err = schemas.validate_driver_payload(raw, is_update=True)
    if err:
        return _validation_err(err)
    slim = {k: v for k, v in payload.items() if k in raw}
    data, err = services.update_driver(driver_id, slim)
    if err:
        return _err(err, 404)
    return success_response(data=data)


@transport_bp.route("/drivers/<driver_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_DRIVERS_DELETE)
def delete_driver(driver_id):
    ok, err = services.delete_driver(driver_id)
    if not ok:
        return _err(err or "Delete failed", 400)
    return success_response(message="Driver deleted")


# ---------------------------------------------------------------------------
# Transport staff (helpers / attendants)
# ---------------------------------------------------------------------------


@transport_bp.route("/staff", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_any_permission(
    TRANSPORT_DRIVERS_READ,
    TRANSPORT_ASSIGNMENTS_READ,
    TRANSPORT_ENROLLMENT_READ,
)
def list_transport_staff():
    role = request.args.get("role")
    return success_response(data=services.list_staff(role=role))


@transport_bp.route("/staff", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_DRIVERS_CREATE)
def create_transport_staff():
    payload, err = schemas.validate_staff_payload(request.get_json() or {}, is_update=False)
    if err:
        return _validation_err(err)
    data, err = services.create_staff_member(payload)
    if err:
        return _err(err)
    return success_response(data=data, message="Staff created", status_code=201)


@transport_bp.route("/staff/<staff_id>", methods=["PUT"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_DRIVERS_UPDATE)
def update_transport_staff(staff_id):
    raw = request.get_json() or {}
    payload, err = schemas.validate_staff_payload(raw, is_update=True)
    if err:
        return _validation_err(err)
    slim = {k: v for k, v in payload.items() if k in raw}
    data, err = services.update_staff_member(staff_id, slim)
    if err:
        return _err(err, 404)
    return success_response(data=data)


@transport_bp.route("/staff/<staff_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_DRIVERS_DELETE)
def delete_transport_staff(staff_id):
    ok, err = services.deactivate_staff_member(staff_id)
    if not ok:
        return _err(err or "Failed", 400)
    return success_response(message="Staff deactivated")


@transport_bp.route("/staff/<staff_id>/workload", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_any_permission(
    TRANSPORT_ASSIGNMENTS_READ,
    TRANSPORT_ENROLLMENT_READ,
    TRANSPORT_ROUTES_READ,
)
def get_transport_staff_workload(staff_id):
    from datetime import date as date_cls

    ds = request.args.get("date")
    on_date = None
    if ds:
        try:
            on_date = date_cls.fromisoformat(str(ds).strip())
        except ValueError:
            return validation_error_response({"date": "date must be YYYY-MM-DD"})
    ay = request.args.get("academic_year_id")
    data, err = services.get_driver_workload(
        staff_id, on_date=on_date, academic_year_id=ay
    )
    if err:
        return _err(err, 404 if "not found" in err.lower() else 400)
    return success_response(data=data)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@transport_bp.route("/routes", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_any_permission(
    TRANSPORT_ROUTES_READ,
    TRANSPORT_ENROLLMENT_READ,
    TRANSPORT_ENROLLMENT_CREATE,
    TRANSPORT_ASSIGNMENTS_READ,
)
def list_routes():
    return success_response(data=services.list_routes())


@transport_bp.route("/routes/<route_id>", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_any_permission(
    TRANSPORT_ROUTES_READ,
    TRANSPORT_ENROLLMENT_READ,
    TRANSPORT_ASSIGNMENTS_READ,
)
def get_route(route_id):
    include_stops = request.args.get("include_stops", "true").lower() in ("1", "true", "yes")
    r = services.get_route(route_id, include_stops=include_stops)
    if not r:
        return not_found_response("Route")
    return success_response(data=r)


@transport_bp.route("/routes/<route_id>/buses", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_any_permission(TRANSPORT_ROUTES_READ, TRANSPORT_ENROLLMENT_READ, TRANSPORT_ENROLLMENT_CREATE)
def list_buses_for_route(route_id):
    on = request.args.get("on_date")
    ay = request.args.get("academic_year_id") or None
    d = None
    if on:
        from datetime import date as date_cls

        try:
            d = date_cls.fromisoformat(on)
        except ValueError:
            return validation_error_response({"on_date": "on_date must be YYYY-MM-DD"})
    return success_response(data=services.buses_for_route(route_id, on_date=d, academic_year_id=ay))


# ---------------------------------------------------------------------------
# Stops
# ---------------------------------------------------------------------------


@transport_bp.route("/stops", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_any_permission(
    TRANSPORT_STOPS_READ,
    TRANSPORT_ROUTES_READ,
    TRANSPORT_ENROLLMENT_READ,
    TRANSPORT_ENROLLMENT_CREATE,
)
def list_global_stops():
    search = request.args.get("search") or None
    area = request.args.get("area") or None
    inc = request.args.get("include_inactive", "false").lower() in ("1", "true", "yes")
    with_u = request.args.get("with_usage", "true").lower() in ("1", "true", "yes")
    return success_response(
        data=services.list_global_stops(
            search=search,
            area=area,
            include_inactive=inc,
            with_usage=with_u,
        )
    )


@transport_bp.route("/stops", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_STOPS_CREATE)
def create_global_stop():
    raw = request.get_json() or {}
    payload, err = schemas.validate_global_stop_payload(raw, is_update=False)
    if err:
        return _validation_err(err)
    data, serr = services.create_global_stop(payload)
    if serr == "DUPLICATE_STOP_NAME":
        return error_response(
            "DuplicateStopName",
            f"A stop named '{payload.get('name', '')}' already exists",
            400,
        )
    if serr:
        return _err(serr, 400)
    return success_response(data=data, message="Stop created", status_code=201)


@transport_bp.route("/stops/<stop_id>", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_any_permission(
    TRANSPORT_STOPS_READ,
    TRANSPORT_ROUTES_READ,
    TRANSPORT_ENROLLMENT_READ,
    TRANSPORT_ENROLLMENT_CREATE,
)
def get_global_stop(stop_id):
    d = services.get_global_stop(stop_id)
    if not d:
        return not_found_response("Stop")
    return success_response(data=d)


@transport_bp.route("/routes/<route_id>/stops", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_any_permission(
    TRANSPORT_STOPS_READ,
    TRANSPORT_ROUTES_READ,
    TRANSPORT_ENROLLMENT_READ,
    TRANSPORT_ENROLLMENT_CREATE,
)
def list_route_stops(route_id):
    inc = request.args.get("include_inactive", "false").lower() in ("1", "true", "yes")
    return success_response(data=services.list_stops_for_route(route_id, include_inactive=inc))


@transport_bp.route("/routes/<route_id>/stops", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_STOPS_CREATE)
def create_route_stop(route_id):
    payload, err = schemas.validate_stop_payload(request.get_json() or {}, is_update=False)
    if err:
        return _validation_err(err)
    data, err = services.create_stop(route_id, payload)
    if err:
        return _err(err, 404 if "not found" in (err or "").lower() else 400)
    return success_response(data=data, message="Stop created", status_code=201)


@transport_bp.route("/stops/<stop_id>", methods=["PUT"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_STOPS_UPDATE)
def update_route_stop(stop_id):
    raw = request.get_json() or {}
    payload, err = schemas.validate_global_stop_payload(raw, is_update=True)
    if err:
        return _validation_err(err)
    slim = {k: v for k, v in payload.items() if k in raw}
    data, serr = services.update_global_stop(stop_id, slim)
    if serr == "DUPLICATE_STOP_NAME":
        return error_response(
            "DuplicateStopName",
            "A stop with this name already exists",
            400,
        )
    if serr:
        return _err(serr, 404)
    return success_response(data=data)


@transport_bp.route("/stops/<stop_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_STOPS_DELETE)
def delete_transport_stop(stop_id):
    ok, err = services.delete_global_stop(stop_id)
    if err == "STOP_IN_USE":
        return error_response(
            "StopInUse",
            "Stop is used by one or more routes and cannot be deleted. Remove it from routes first.",
            409,
        )
    if err:
        return _err(err, 404 if "not found" in (err or "").lower() else 400)
    return success_response(message="Stop deleted")


@transport_bp.route("/routes/<route_id>/stops/reorder", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_STOPS_UPDATE)
def reorder_route_stops(route_id):
    body = request.get_json() or {}
    ids = body.get("stop_ids") or body.get("order")
    if not isinstance(ids, list) or not ids:
        return validation_error_response(
            {"stop_ids": "stop_ids must be a non-empty list of stop IDs in order"}
        )
    ok, err = services.reorder_stops(route_id, [str(x) for x in ids])
    if not ok:
        return _err(err or "Reorder failed", 400)
    return success_response(data=services.list_stops_for_route(route_id, include_inactive=True))


@transport_bp.route("/routes/<route_id>/stops/sync", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_STOPS_UPDATE)
def sync_route_stops_route(route_id):
    rows, err = schemas.validate_sync_route_stops_payload(request.get_json() or {})
    if err:
        return validation_error_response({"stops": err})
    data, serr = services.sync_route_stops(route_id, rows or [])
    if serr:
        return _err(serr, 404 if "not found" in (serr or "").lower() else 400)
    return success_response(data=data, message="Stops updated")


@transport_bp.route("/routes", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_ROUTES_CREATE)
def create_route():
    payload, err = schemas.validate_route_payload(request.get_json() or {}, is_update=False)
    if err:
        return _validation_err(err)
    data, err = services.create_route(payload)
    if err:
        return _err(err)
    return success_response(data=data, message="Route created", status_code=201)


@transport_bp.route("/routes/<route_id>", methods=["PUT"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_ROUTES_UPDATE)
def update_route(route_id):
    raw = request.get_json() or {}
    payload, err = schemas.validate_route_payload(raw, is_update=True)
    if err:
        return _validation_err(err)
    slim = {k: v for k, v in payload.items() if k in raw}
    data, err = services.update_route(route_id, slim)
    if err:
        return _err(err, 404)
    return success_response(data=data)


@transport_bp.route("/routes/<route_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_ROUTES_DELETE)
def delete_route(route_id):
    ok, err, details = services.delete_route(route_id)
    if not ok:
        code = 404 if err == "Route not found" else 409
        return error_response(
            "TransportError",
            err or "Delete failed",
            status_code=code,
            details=details,
        )
    return success_response(message="Route deleted")


@transport_bp.route("/routes/<route_id>/export/students", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_EXPORTS_READ)
def export_route_students(route_id):
    ay = request.args.get("academic_year_id") or None
    csv_text, err = services.export_route_students_csv(route_id, academic_year_id=ay)
    if err:
        return _err(err, 404)
    return _csv_response(csv_text, f"transport-route-{route_id}-students.csv")


# ---------------------------------------------------------------------------
# Route schedules
# ---------------------------------------------------------------------------


@transport_bp.route("/schedules", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_any_permission(
    TRANSPORT_ASSIGNMENTS_READ,
    TRANSPORT_ENROLLMENT_READ,
    TRANSPORT_ROUTES_READ,
)
def list_schedules_route():
    ay = request.args.get("academic_year_id")
    if not ay:
        return validation_error_response({"academic_year_id": "academic_year_id is required"})
    route_id = request.args.get("route_id") or None
    bus_id = request.args.get("bus_id") or None
    driver_id = request.args.get("driver_id") or None
    shift_type = request.args.get("shift_type") or None
    is_act = request.args.get("is_active")
    is_active = None if is_act is None else is_act.lower() in ("1", "true", "yes")
    data = services.list_schedules(
        ay.strip(),
        route_id=route_id.strip() if route_id else None,
        bus_id=bus_id.strip() if bus_id else None,
        driver_id=driver_id.strip() if driver_id else None,
        shift_type=shift_type.strip() if shift_type else None,
        is_active=is_active if is_act is not None else True,
    )
    return success_response(data=data)


@transport_bp.route("/schedules/exceptions", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_any_permission(
    TRANSPORT_ASSIGNMENTS_READ,
    TRANSPORT_ENROLLMENT_READ,
    TRANSPORT_ROUTES_READ,
)
def list_schedule_exceptions_route():
    ay = request.args.get("academic_year_id")
    if not ay:
        return validation_error_response({"academic_year_id": "academic_year_id is required"})
    ed_raw = request.args.get("exception_date") or None
    exception_date = None
    if ed_raw:
        try:
            exception_date = date.fromisoformat(ed_raw.strip())
        except ValueError:
            return validation_error_response({"exception_date": "exception_date must be YYYY-MM-DD"})
    et = (request.args.get("exception_type") or "").strip().lower() or None
    if et and et not in ("override", "cancellation"):
        return validation_error_response({"exception_type": "exception_type must be override or cancellation"})
    data = services.list_schedule_exceptions(
        ay.strip(),
        exception_date=exception_date,
        exception_type=et,
    )
    return success_response(data=data)


@transport_bp.route("/schedules/exceptions", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_ASSIGNMENTS_CREATE)
def create_schedule_exception_route():
    payload, err = schemas.validate_exception_payload(request.get_json() or {})
    if err:
        return _validation_err(err)
    data, serr = services.create_schedule_exception(payload)
    if serr:
        if isinstance(serr, tuple) and len(serr) == 2:
            return error_response(serr[0], serr[1], 409)
        return _err(serr)
    return success_response(data=data, message="Exception created", status_code=201)


@transport_bp.route("/schedules/exceptions/<exception_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_ASSIGNMENTS_DELETE)
def delete_schedule_exception_route(exception_id):
    ok, serr = services.delete_schedule_exception(exception_id)
    if not ok:
        return _err(serr or "Failed", 404 if serr == "Exception not found" else 400)
    return success_response(message="Exception deleted")


@transport_bp.route("/schedules/conflict-check", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_any_permission(
    TRANSPORT_ASSIGNMENTS_READ,
    TRANSPORT_ENROLLMENT_READ,
)
def schedule_conflict_check():
    payload, err = schemas.validate_schedule_payload(request.get_json() or {}, is_update=False)
    if err:
        return _validation_err(err)
    data, serr = services.check_schedule_conflicts(payload)
    if serr:
        return _err(serr)
    return success_response(data=data)


@transport_bp.route("/schedules", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_ASSIGNMENTS_CREATE)
def create_schedule_route():
    payload, err = schemas.validate_schedule_payload(request.get_json() or {}, is_update=False)
    if err:
        return _validation_err(err)
    data, serr = services.create_schedule(payload)
    if serr:
        if isinstance(serr, tuple) and len(serr) == 2:
            return error_response(serr[0], serr[1], 409)
        return _err(serr)
    return success_response(data=data, message="Schedule created", status_code=201)


@transport_bp.route("/schedules/<schedule_id>", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_any_permission(
    TRANSPORT_ASSIGNMENTS_READ,
    TRANSPORT_ENROLLMENT_READ,
    TRANSPORT_ROUTES_READ,
)
def get_schedule_route(schedule_id):
    data = services.get_schedule(schedule_id)
    if not data:
        return not_found_response("Schedule")
    return success_response(data=data)


@transport_bp.route("/schedules/<schedule_id>", methods=["PUT"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_ASSIGNMENTS_UPDATE)
def update_schedule_route(schedule_id):
    raw = request.get_json() or {}
    payload, err = schemas.validate_schedule_payload(raw, is_update=True)
    if err:
        return _validation_err(err)
    slim = {k: v for k, v in payload.items() if k in raw}
    data, serr = services.update_schedule(schedule_id, slim)
    if serr:
        if isinstance(serr, tuple) and len(serr) == 2:
            return error_response(serr[0], serr[1], 409)
        return _err(serr, 404 if "not found" in str(serr).lower() else 400)
    return success_response(data=data)


@transport_bp.route("/schedules/<schedule_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_ASSIGNMENTS_DELETE)
def delete_schedule_route(schedule_id):
    ok, serr = services.deactivate_schedule(schedule_id)
    if not ok:
        return _err(serr or "Failed", 404 if serr and "not found" in serr.lower() else 400)
    return success_response(message="Schedule deactivated")


# ---------------------------------------------------------------------------
# Assignments
# ---------------------------------------------------------------------------


@transport_bp.route("/bus-assignments", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_any_permission(
    TRANSPORT_ASSIGNMENTS_READ,
    TRANSPORT_ENROLLMENT_READ,
    TRANSPORT_DASHBOARD_READ,
)
def list_assignments():
    return success_response(data=services.list_assignments())


@transport_bp.route("/bus-assignments", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_ASSIGNMENTS_CREATE)
def create_assignment():
    payload, err = schemas.validate_assignment_payload(request.get_json() or {})
    if err:
        return _validation_err(err)
    data, err = services.create_assignment(payload)
    if err:
        return _err(err)
    return success_response(data=data, message="Assignment created", status_code=201)


# ---------------------------------------------------------------------------
# Enrollments
# ---------------------------------------------------------------------------


@transport_bp.route("/enrollments", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_ENROLLMENT_READ)
def list_enrollments():
    ay = request.args.get("academic_year_id") or None
    return success_response(data=services.list_enrollments(academic_year_id=ay))


@transport_bp.route("/enroll", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_ENROLLMENT_CREATE)
def enroll():
    payload, err = schemas.validate_enroll_payload(request.get_json() or {}, is_update=False)
    if err:
        return _validation_err(err)
    data, err = services.create_enrollment(payload)
    if err:
        return _err(err)
    return success_response(data=data, message="Enrolled", status_code=201)


@transport_bp.route("/enroll/<enrollment_id>", methods=["PUT"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_ENROLLMENT_UPDATE)
def update_enroll(enrollment_id):
    raw = request.get_json() or {}
    payload, err = schemas.validate_enroll_payload(raw, is_update=True)
    if err:
        return _validation_err(err)
    slim = {k: v for k, v in payload.items() if k in raw}
    data, err = services.update_enrollment(enrollment_id, slim)
    if err:
        return _err(err, 404)
    return success_response(data=data)


@transport_bp.route("/enroll/<enrollment_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_ENROLLMENT_DELETE)
def delete_enroll(enrollment_id):
    ok, err = services.deactivate_enrollment(enrollment_id)
    if not ok:
        return _err(err or "Failed", 400)
    return success_response(message="Enrollment deactivated")


# ---------------------------------------------------------------------------
# Dashboard & fee plans & global export
# ---------------------------------------------------------------------------


@transport_bp.route("/dashboard", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_DASHBOARD_READ)
def dashboard():
    ay = request.args.get("academic_year_id") or None
    return success_response(data=services.dashboard_stats(academic_year_id=ay))


@transport_bp.route("/fee-plans", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_any_permission(
    TRANSPORT_FEE_PLANS_READ,
    TRANSPORT_FEE_PLANS_MANAGE,
    TRANSPORT_ENROLLMENT_CREATE,
    TRANSPORT_ENROLLMENT_UPDATE,
)
def list_fee_plans():
    ay = request.args.get("academic_year_id") or None
    return success_response(data=services.list_fee_plans(academic_year_id=ay))


@transport_bp.route("/fee-plans", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_FEE_PLANS_MANAGE)
def create_fee_plan():
    payload, err = schemas.validate_fee_plan_payload(request.get_json() or {})
    if err:
        return _validation_err(err)
    data, err = services.upsert_fee_plan(
        payload["route_id"],
        payload["amount"],
        academic_year_id=payload.get("academic_year_id"),
    )
    if err:
        return _err(err)
    return success_response(data=data, status_code=201)


@transport_bp.route("/export/contact-sheet", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("transport")
@require_permission(TRANSPORT_EXPORTS_READ)
def export_contact_sheet():
    ay = request.args.get("academic_year_id") or None
    csv_text, err = services.export_contact_sheet_csv(academic_year_id=ay)
    if err:
        return _err(err or "Export failed", 400)
    return _csv_response(csv_text, "transport-contact-sheet.csv")
