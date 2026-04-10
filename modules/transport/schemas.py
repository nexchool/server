"""Request validation for transport APIs."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple


def _parse_date(s: Optional[str], field: str) -> Tuple[Optional[date], Optional[str]]:
    if s is None or s == "":
        return None, None
    try:
        return date.fromisoformat(str(s).strip()), None
    except ValueError:
        return None, f"{field} must be a valid date (YYYY-MM-DD)"


def _parse_time(s: Optional[str]) -> Tuple[Optional[time], Optional[str]]:
    if s is None or s == "":
        return None, None
    raw = str(s).strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(raw, fmt).time(), None
        except ValueError:
            continue
    return None, "Invalid time (use HH:MM or HH:MM:SS)"


def _decimal(v: Any, field: str) -> Tuple[Optional[Decimal], Optional[str]]:
    if v is None:
        return None, f"{field} is required"
    try:
        d = Decimal(str(v))
        if d < 0:
            return None, f"{field} must be non-negative"
        return d.quantize(Decimal("0.01")), None
    except (InvalidOperation, ValueError):
        return None, f"{field} must be a valid amount"


def validate_bus_payload(data: Dict, is_update: bool = False) -> Tuple[Optional[Dict], Optional[str]]:
    if not is_update:
        if not data.get("bus_number"):
            return None, "bus_number is required"
        if data.get("capacity") is None:
            return None, "capacity is required"
    cap = None
    if data.get("capacity") is not None:
        try:
            cap = int(data["capacity"])
            if cap < 1:
                return None, "capacity must be at least 1"
        except (TypeError, ValueError):
            return None, "capacity must be an integer"
    if is_update:
        status = data.get("status") if "status" in data else None
        if status is not None and status not in ("active", "inactive", "maintenance"):
            return None, "status must be active, inactive, or maintenance"
    else:
        status = data.get("status", "active")
        if status not in ("active", "inactive", "maintenance"):
            return None, "status must be active, inactive, or maintenance"
    out = {
        "bus_number": (data.get("bus_number") or "").strip() if data.get("bus_number") else None,
        "vehicle_number": (data.get("vehicle_number") or "").strip() or None,
        "capacity": cap,
        "status": status,
    }
    return out, None


def validate_driver_payload(data: Dict, is_update: bool = False) -> Tuple[Optional[Dict], Optional[str]]:
    if not is_update and not (data.get("name") or "").strip():
        return None, "name is required"
    status = data.get("status", "active")
    if status not in ("active", "inactive"):
        return None, "status must be active or inactive"
    return {
        "name": (data.get("name") or "").strip() or None,
        "phone": (data.get("phone") or "").strip() or None,
        "alternate_phone": (data.get("alternate_phone") or "").strip() or None,
        "license_number": (data.get("license_number") or "").strip() or None,
        "address": (data.get("address") or "").strip() or None,
        "status": status,
    }, None


FEE_CYCLE_VALUES = frozenset({"monthly", "quarterly", "half_yearly", "yearly"})


def validate_route_payload(data: Dict, is_update: bool = False) -> Tuple[Optional[Dict], Optional[str]]:
    out: Dict[str, Any] = {}

    if not is_update:
        if not (data.get("name") or "").strip():
            return None, "name is required"
        out["name"] = (data.get("name") or "").strip()
    elif "name" in data:
        nm = (data.get("name") or "").strip()
        if not nm:
            return None, "name cannot be empty"
        out["name"] = nm

    if not is_update or "pickup_time" in data:
        pt, err = _parse_time(data.get("pickup_time"))
        if err:
            return None, err
        out["pickup_time"] = pt
    if not is_update or "drop_time" in data:
        dt, err = _parse_time(data.get("drop_time"))
        if err:
            return None, err
        out["drop_time"] = dt

    if not is_update or "approx_stops" in data:
        stops = data.get("approx_stops")
        if stops is not None and not isinstance(stops, (list, dict)):
            return None, "approx_stops must be a JSON array or object"
        if not is_update or "approx_stops" in data:
            out["approx_stops"] = stops

    if not is_update or "start_point" in data:
        out["start_point"] = (data.get("start_point") or "").strip() or None
    if not is_update or "end_point" in data:
        out["end_point"] = (data.get("end_point") or "").strip() or None

    if not is_update:
        status = data.get("status", "active")
        if status not in ("active", "inactive"):
            return None, "status must be active or inactive"
        out["status"] = status
    elif "status" in data:
        status = data.get("status")
        if status is not None and status not in ("active", "inactive"):
            return None, "status must be active or inactive"
        if status is not None:
            out["status"] = status

    if "default_fee" in data:
        v = data.get("default_fee")
        if v is None or v == "":
            out["default_fee"] = None
        else:
            df, err = _decimal(v, "default_fee")
            if err:
                return None, err
            out["default_fee"] = df

    if "fee_cycle" in data:
        fc = (data.get("fee_cycle") or "").strip().lower()
        if fc and fc not in FEE_CYCLE_VALUES:
            return None, "fee_cycle must be monthly, quarterly, half_yearly, or yearly"
        out["fee_cycle"] = fc or None

    if "is_reverse_enabled" in data:
        v = data.get("is_reverse_enabled")
        if not isinstance(v, bool):
            return None, "is_reverse_enabled must be a boolean"
        out["is_reverse_enabled"] = v

    if "approx_stops_needs_review" in data:
        v = data.get("approx_stops_needs_review")
        if not isinstance(v, bool):
            return None, "approx_stops_needs_review must be a boolean"
        out["approx_stops_needs_review"] = v

    return out, None


def validate_sync_route_stops_payload(
    data: Dict,
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    stops = data.get("stops")
    if not isinstance(stops, list) or len(stops) < 1:
        return None, "At least one stop is required"
    out: List[Dict[str, Any]] = []
    for row in stops:
        if not isinstance(row, dict):
            return None, "Each stop must be an object"
        sid = (row.get("stop_id") or "").strip()
        if not sid:
            return None, "stop_id is required for each stop"
        try:
            seq = int(row.get("sequence_order"))
        except (TypeError, ValueError):
            return None, "sequence_order must be an integer"
        pt, err = _parse_time(row.get("pickup_time"))
        if err:
            return None, err
        dt, err = _parse_time(row.get("drop_time"))
        if err:
            return None, err
        out.append(
            {
                "stop_id": sid,
                "sequence_order": seq,
                "pickup_time": pt,
                "drop_time": dt,
            }
        )
    seqs = sorted(x["sequence_order"] for x in out)
    if seqs != list(range(1, len(seqs) + 1)):
        return None, "sequence_order must be sequential from 1 to n"
    seen: set[str] = set()
    for x in out:
        if x["stop_id"] in seen:
            return None, "The same stop cannot appear twice on a route"
        seen.add(x["stop_id"])
    return out, None


def validate_assignment_payload(data: Dict) -> Tuple[Optional[Dict], Optional[str]]:
    for k in ("bus_id", "driver_id", "route_id", "effective_from"):
        if not data.get(k):
            return None, f"{k} is required"
    ef, err = _parse_date(data.get("effective_from"), "effective_from")
    if err:
        return None, err
    et, err = _parse_date(data.get("effective_to"), "effective_to")
    if err:
        return None, err
    if ef and et and et < ef:
        return None, "effective_to must be on or after effective_from"
    status = data.get("status", "active")
    if status not in ("active", "inactive", "ended"):
        return None, "status must be active, inactive, or ended"
    helper_staff_id = (data.get("helper_staff_id") or "").strip() or None
    return {
        "bus_id": data["bus_id"].strip(),
        "driver_id": data["driver_id"].strip(),
        "route_id": data["route_id"].strip(),
        "effective_from": ef,
        "effective_to": et,
        "status": status,
        "helper_staff_id": helper_staff_id,
    }, None


def validate_enroll_payload(data: Dict, is_update: bool = False) -> Tuple[Optional[Dict], Optional[str]]:
    if not is_update:
        for k in ("student_id", "bus_id", "route_id", "start_date"):
            if not data.get(k):
                return None, f"{k} is required"
        if data.get("monthly_fee") is None:
            return None, "monthly_fee is required"
    mf = None
    err = None
    if data.get("monthly_fee") is not None:
        mf, err = _decimal(data.get("monthly_fee"), "monthly_fee")
        if err:
            return None, err
    sd, err = _parse_date(data.get("start_date"), "start_date")
    if err:
        return None, err
    ed, err = _parse_date(data.get("end_date"), "end_date")
    if err:
        return None, err
    if sd and ed and ed < sd:
        return None, "end_date must be on or after start_date"
    if is_update:
        status = data.get("status") if "status" in data else None
    else:
        status = data.get("status", "active")
    if status is not None and status not in ("active", "inactive"):
        return None, "status must be active or inactive"
    ay = (data.get("academic_year_id") or "").strip() or None
    pickup_stop_id = (data.get("pickup_stop_id") or "").strip() or None
    drop_stop_id = (data.get("drop_stop_id") or "").strip() or None
    out: Dict[str, Any] = {
        "student_id": (data.get("student_id") or "").strip() or None,
        "bus_id": (data.get("bus_id") or "").strip() or None,
        "route_id": (data.get("route_id") or "").strip() or None,
        "pickup_point": (data.get("pickup_point") or "").strip() or None,
        "drop_point": (data.get("drop_point") or "").strip() or None,
        "pickup_stop_id": pickup_stop_id,
        "drop_stop_id": drop_stop_id,
        "academic_year_id": ay,
        "monthly_fee": mf,
        "status": status,
        "start_date": sd,
        "end_date": ed,
    }
    if "fee_cycle" in data:
        fc = (data.get("fee_cycle") or "").strip().lower()
        if fc and fc not in FEE_CYCLE_VALUES:
            return None, "fee_cycle must be monthly, quarterly, half_yearly, or yearly"
        out["fee_cycle"] = fc if fc else None
    return out, None


def validate_fee_plan_payload(data: Dict) -> Tuple[Optional[Dict], Optional[str]]:
    if not data.get("route_id"):
        return None, "route_id is required"
    amt, err = _decimal(data.get("amount"), "amount")
    if err:
        return None, err
    ay = (data.get("academic_year_id") or "").strip() or None
    out = {"route_id": data["route_id"].strip(), "amount": amt}
    if ay:
        out["academic_year_id"] = ay
    return out, None


def _optional_lat_lng(data: Dict) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Validate optional latitude/longitude; returns decimals or None."""
    out: Dict[str, Any] = {}
    for key, lo, hi in (
        ("latitude", -90, 90),
        ("longitude", -180, 180),
    ):
        if key not in data or data.get(key) is None or data.get(key) == "":
            continue
        try:
            v = float(data[key])
        except (TypeError, ValueError):
            return None, f"{key} must be a number"
        if v < lo or v > hi:
            return None, f"{key} must be between {lo} and {hi}"
        out[key] = v
    return out, None


def validate_global_stop_payload(
    data: Dict, is_update: bool = False
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Global stop master (no route-scoped times on the stop row)."""
    ll, err = _optional_lat_lng(data)
    if err:
        return None, err
    out: Dict[str, Any] = {}
    if not is_update:
        if not (data.get("name") or "").strip():
            return None, "name is required"
        out["name"] = (data.get("name") or "").strip()
    elif "name" in data:
        nm = (data.get("name") or "").strip()
        if not nm:
            return None, "name cannot be empty"
        out["name"] = nm
    if "area" in data:
        out["area"] = (data.get("area") or "").strip() or None
    if "landmark" in data:
        out["landmark"] = (data.get("landmark") or "").strip() or None
    out.update(ll)
    if "is_active" in data:
        v = data["is_active"]
        if not isinstance(v, bool):
            return None, "is_active must be a boolean"
        out["is_active"] = v
    return out, None


def validate_stop_payload(data: Dict, is_update: bool = False) -> Tuple[Optional[Dict], Optional[str]]:
    if not is_update and not (data.get("name") or "").strip():
        return None, "name is required"
    pt, err = _parse_time(data.get("pickup_time"))
    if err:
        return None, err
    dt, err = _parse_time(data.get("drop_time"))
    if err:
        return None, err
    out: Dict[str, Any] = {
        "name": (data.get("name") or "").strip() or None,
        "pickup_time": pt,
        "drop_time": dt,
    }
    ll, err = _optional_lat_lng(data)
    if err:
        return None, err
    out.update(ll)
    if "area" in data:
        out["area"] = (data.get("area") or "").strip() or None
    if "landmark" in data:
        out["landmark"] = (data.get("landmark") or "").strip() or None
    if "sequence_order" in data and data["sequence_order"] is not None:
        try:
            out["sequence_order"] = int(data["sequence_order"])
        except (TypeError, ValueError):
            return None, "sequence_order must be an integer"
    if "is_active" in data:
        v = data["is_active"]
        if not isinstance(v, bool):
            return None, "is_active must be a boolean"
        out["is_active"] = v
    return out, None


SHIFT_TYPES = frozenset({"pickup", "drop"})


def validate_schedule_payload(data: Dict, is_update: bool = False) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Create / conflict-check payload for route schedules."""
    out: Dict[str, Any] = {}
    if not is_update:
        for k in ("route_id", "bus_id", "driver_id", "shift_type", "academic_year_id"):
            v = data.get(k)
            if v is None or (isinstance(v, str) and not str(v).strip()):
                return None, f"{k} is required"
        out["route_id"] = str(data["route_id"]).strip()
        out["bus_id"] = str(data["bus_id"]).strip()
        out["driver_id"] = str(data["driver_id"]).strip()
        out["academic_year_id"] = str(data["academic_year_id"]).strip()
        stype = str(data["shift_type"]).strip().lower()
        if stype not in SHIFT_TYPES:
            return None, "shift_type must be pickup or drop"
        out["shift_type"] = stype
        s_t, err = _parse_time(data.get("start_time"))
        if err:
            return None, err
        if s_t is None:
            return None, "start_time is required"
        e_t, err = _parse_time(data.get("end_time"))
        if err:
            return None, err
        if e_t is None:
            return None, "end_time is required"
        if s_t >= e_t:
            return None, "end_time must be after start_time"
        out["start_time"] = s_t
        out["end_time"] = e_t
        hid = data.get("helper_id")
        out["helper_id"] = str(hid).strip() if hid else None
        pr = data.get("is_reverse_enabled")
        if pr is not None:
            if not isinstance(pr, bool):
                return None, "is_reverse_enabled must be a boolean"
            out["pair_reverse"] = pr
        else:
            out["pair_reverse"] = False
        rs, err = _parse_time(data.get("reverse_start_time"))
        if err:
            return None, err
        re, err = _parse_time(data.get("reverse_end_time"))
        if err:
            return None, err
        out["reverse_start_time"] = rs
        out["reverse_end_time"] = re
        return out, None

    # update — only keys present in data
    if "route_id" in data:
        out["route_id"] = str(data["route_id"]).strip()
    if "bus_id" in data:
        out["bus_id"] = str(data["bus_id"]).strip()
    if "driver_id" in data:
        out["driver_id"] = str(data["driver_id"]).strip()
    if "helper_id" in data:
        hid = data.get("helper_id")
        out["helper_id"] = str(hid).strip() if hid else None
    if "shift_type" in data:
        stype = str(data["shift_type"]).strip().lower()
        if stype not in SHIFT_TYPES:
            return None, "shift_type must be pickup or drop"
        out["shift_type"] = stype
    if "academic_year_id" in data:
        out["academic_year_id"] = str(data["academic_year_id"]).strip()
    if "start_time" in data or "end_time" in data:
        s_t, err = _parse_time(data.get("start_time"))
        if err:
            return None, err
        e_t, err = _parse_time(data.get("end_time"))
        if err:
            return None, err
        if s_t is None or e_t is None:
            return None, "start_time and end_time are both required when updating times"
        if s_t >= e_t:
            return None, "end_time must be after start_time"
        out["start_time"] = s_t
        out["end_time"] = e_t
    if "is_active" in data:
        if not isinstance(data["is_active"], bool):
            return None, "is_active must be a boolean"
        out["is_active"] = data["is_active"]
    return out, None


EXCEPTION_TYPES = frozenset({"override", "cancellation"})


def validate_exception_payload(data: Dict) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """One-off schedule exception (holiday override or cancellation)."""
    if not data.get("academic_year_id"):
        return None, "academic_year_id is required"
    ay = str(data["academic_year_id"]).strip()
    et = str(data.get("exception_type") or "").strip().lower()
    if et not in EXCEPTION_TYPES:
        return None, "exception_type must be override or cancellation"

    ed, err = _parse_date(data.get("exception_date"), "exception_date")
    if err:
        return None, err
    if ed is None:
        return None, "exception_date is required"

    reason = (data.get("reason") or "").strip() or None

    if et == "override":
        for k in ("route_id", "bus_id", "driver_id", "shift_type"):
            v = data.get(k)
            if v is None or (isinstance(v, str) and not str(v).strip()):
                return None, f"{k} is required for override"
        stype = str(data["shift_type"]).strip().lower()
        if stype not in SHIFT_TYPES:
            return None, "shift_type must be pickup or drop"
        s_t, err = _parse_time(data.get("start_time"))
        if err:
            return None, err
        if s_t is None:
            return None, "start_time is required"
        e_t, err = _parse_time(data.get("end_time"))
        if err:
            return None, err
        if e_t is None:
            return None, "end_time is required"
        if s_t >= e_t:
            return None, "end_time must be after start_time"
        hid = data.get("helper_id")
        return {
            "academic_year_id": ay,
            "exception_date": ed,
            "exception_type": "override",
            "route_id": str(data["route_id"]).strip(),
            "bus_id": str(data["bus_id"]).strip(),
            "driver_id": str(data["driver_id"]).strip(),
            "helper_id": str(hid).strip() if hid else None,
            "shift_type": stype,
            "start_time": s_t,
            "end_time": e_t,
            "reason": reason,
        }, None

    sid = (data.get("schedule_id") or "").strip()
    if not sid:
        return None, "schedule_id is required for cancellation"
    return {
        "academic_year_id": ay,
        "exception_date": ed,
        "exception_type": "cancellation",
        "schedule_id": sid,
        "reason": reason,
    }, None


def validate_staff_payload(data: Dict, is_update: bool = False) -> Tuple[Optional[Dict], Optional[str]]:
    if not is_update and not (data.get("name") or "").strip():
        return None, "name is required"
    role = (data.get("role") or "helper").strip().lower()
    if role not in ("driver", "helper", "attendant"):
        return None, "role must be driver, helper, or attendant"
    status = data.get("status", "active")
    if status not in ("active", "inactive"):
        return None, "status must be active or inactive"
    return {
        "name": (data.get("name") or "").strip() or None,
        "phone": (data.get("phone") or "").strip() or None,
        "alternate_phone": (data.get("alternate_phone") or "").strip() or None,
        "license_number": (data.get("license_number") or "").strip() or None,
        "address": (data.get("address") or "").strip() or None,
        "role": role,
        "status": status,
    }, None
