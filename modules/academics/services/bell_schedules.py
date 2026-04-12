"""Bell schedules and periods."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import IntegrityError

from core.database import db
from modules.academics.backbone.models import (
    AcademicSettings,
    BellSchedule,
    BellSchedulePeriod,
    TimetableVersion,
)


def _serialize_schedule(bs: BellSchedule, include_periods: bool = False) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "id": bs.id,
        "name": bs.name,
        "academic_year_id": bs.academic_year_id,
        "day_of_week": bs.day_of_week,
        "is_default": bs.is_default,
        "valid_from": bs.valid_from.isoformat() if bs.valid_from else None,
        "valid_to": bs.valid_to.isoformat() if bs.valid_to else None,
        "created_at": bs.created_at.isoformat() if bs.created_at else None,
        "updated_at": bs.updated_at.isoformat() if bs.updated_at else None,
    }
    if include_periods:
        periods = sorted(bs.periods or [], key=lambda p: (p.sort_order, p.period_number))
        out["periods"] = [_serialize_period(p) for p in periods]
    return out


def _serialize_period(p: BellSchedulePeriod) -> Dict[str, Any]:
    return {
        "id": p.id,
        "bell_schedule_id": p.bell_schedule_id,
        "period_number": p.period_number,
        "period_kind": p.period_kind,
        "starts_at": p.starts_at.isoformat() if p.starts_at else None,
        "ends_at": p.ends_at.isoformat() if p.ends_at else None,
        "label": p.label,
        "sort_order": p.sort_order,
    }


def list_schedules(tenant_id: str) -> Dict[str, Any]:
    rows = (
        BellSchedule.query.filter_by(tenant_id=tenant_id)
        .filter(BellSchedule.deleted_at.is_(None))
        .order_by(BellSchedule.name)
        .all()
    )
    settings = AcademicSettings.query.filter_by(tenant_id=tenant_id).first()
    tenant_default = settings.default_bell_schedule_id if settings else None
    return {
        "success": True,
        "items": [_serialize_schedule(r) for r in rows],
        "tenant_default_bell_schedule_id": tenant_default,
    }


def get_schedule(tenant_id: str, schedule_id: str, include_periods: bool = True) -> Dict[str, Any]:
    bs = BellSchedule.query.filter_by(id=schedule_id, tenant_id=tenant_id).filter(
        BellSchedule.deleted_at.is_(None)
    ).first()
    if not bs:
        return {"success": False, "error": "Bell schedule not found"}
    out = _serialize_schedule(bs, include_periods=include_periods)
    out["timetable_versions_linked"] = (
        TimetableVersion.query.filter_by(tenant_id=tenant_id, bell_schedule_id=bs.id)
        .filter(TimetableVersion.status.in_(["active", "draft"]))
        .count()
    )
    return {"success": True, "bell_schedule": out}


def create_schedule(tenant_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    name = (data.get("name") or "").strip()
    if not name:
        return {"success": False, "error": "name is required"}

    bs = BellSchedule(
        tenant_id=tenant_id,
        name=name,
        academic_year_id=data.get("academic_year_id"),
        day_of_week=data.get("day_of_week"),
        is_default=bool(data.get("is_default", False)),
        valid_from=_parse_date(data.get("valid_from")),
        valid_to=_parse_date(data.get("valid_to")),
    )
    if bs.valid_from and bs.valid_to and bs.valid_from > bs.valid_to:
        return {"success": False, "error": "valid_from must be before valid_to"}

    db.session.add(bs)
    try:
        db.session.commit()
    except IntegrityError as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}
    return {"success": True, "bell_schedule": _serialize_schedule(bs)}


def update_schedule(tenant_id: str, schedule_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    bs = BellSchedule.query.filter_by(id=schedule_id, tenant_id=tenant_id).filter(
        BellSchedule.deleted_at.is_(None)
    ).first()
    if not bs:
        return {"success": False, "error": "Bell schedule not found"}

    if "name" in data and data["name"]:
        bs.name = str(data["name"]).strip()
    if "academic_year_id" in data:
        bs.academic_year_id = data["academic_year_id"]
    if "day_of_week" in data:
        bs.day_of_week = data["day_of_week"]
    if "is_default" in data:
        bs.is_default = bool(data["is_default"])
    if "valid_from" in data:
        bs.valid_from = _parse_date(data.get("valid_from"))
    if "valid_to" in data:
        bs.valid_to = _parse_date(data.get("valid_to"))

    if bs.valid_from and bs.valid_to and bs.valid_from > bs.valid_to:
        return {"success": False, "error": "valid_from must be before valid_to"}

    bs.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return {"success": True, "bell_schedule": _serialize_schedule(bs)}


def delete_schedule(tenant_id: str, schedule_id: str) -> Dict[str, Any]:
    bs = BellSchedule.query.filter_by(id=schedule_id, tenant_id=tenant_id).filter(
        BellSchedule.deleted_at.is_(None)
    ).first()
    if not bs:
        return {"success": False, "error": "Bell schedule not found"}

    settings = AcademicSettings.query.filter_by(tenant_id=tenant_id).first()
    if settings and settings.default_bell_schedule_id == schedule_id:
        return {"success": False, "error": "Unset default bell schedule in academic settings before deleting"}

    bs.deleted_at = datetime.now(timezone.utc)
    bs.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return {"success": True, "message": "Bell schedule deleted"}


def list_periods(tenant_id: str, schedule_id: str) -> Dict[str, Any]:
    gr = get_schedule(tenant_id, schedule_id, include_periods=True)
    if not gr["success"]:
        return gr
    return {"success": True, "items": gr["bell_schedule"]["periods"]}


def _parse_time(val: Any):
    from datetime import time as dtime

    if val is None:
        return None
    if hasattr(val, "hour"):
        return val
    s = str(val)
    parts = s.split(":")
    h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    sec = int(parts[2]) if len(parts) > 2 else 0
    return dtime(h, m, sec)


def _intervals_overlap_clock(start_a: time, end_a: time, start_b: time, end_b: time) -> bool:
    """True if [start_a, end_a) and [start_b, end_b) overlap (touching endpoints are not overlap)."""
    return start_a < end_b and start_b < end_a


def _overlap_error_with_existing(
    tenant_id: str,
    schedule_id: str,
    start: time,
    end: time,
    exclude_period_id: Optional[str] = None,
) -> Optional[str]:
    """Return user-facing error string if [start, end) overlaps any other period in this schedule."""
    q = BellSchedulePeriod.query.filter_by(tenant_id=tenant_id, bell_schedule_id=schedule_id)
    if exclude_period_id:
        q = q.filter(BellSchedulePeriod.id != exclude_period_id)
    for other in q.all():
        if not other.starts_at or not other.ends_at:
            continue
        if _intervals_overlap_clock(start, end, other.starts_at, other.ends_at):
            ostart = other.starts_at.strftime("%H:%M")
            oend = other.ends_at.strftime("%H:%M")
            return (
                f"This time overlaps period {other.period_number} ({ostart}–{oend}). "
                "End each period before the next begins, or adjust the other period."
            )
    return None


def create_period(tenant_id: str, schedule_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    bs = BellSchedule.query.filter_by(id=schedule_id, tenant_id=tenant_id).filter(
        BellSchedule.deleted_at.is_(None)
    ).first()
    if not bs:
        return {"success": False, "error": "Bell schedule not found"}

    try:
        pn = int(data.get("period_number"))
    except (TypeError, ValueError):
        return {"success": False, "error": "period_number is required"}
    starts = _parse_time(data.get("starts_at"))
    ends = _parse_time(data.get("ends_at"))
    if not starts or not ends:
        return {"success": False, "error": "starts_at and ends_at are required (HH:MM or HH:MM:SS)"}
    if starts >= ends:
        return {"success": False, "error": "starts_at must be before ends_at"}

    overlap_err = _overlap_error_with_existing(tenant_id, schedule_id, starts, ends, exclude_period_id=None)
    if overlap_err:
        return {"success": False, "error": overlap_err}

    kind = (data.get("period_kind") or "lesson").strip()
    if kind not in ("lesson", "break", "lunch", "assembly", "other"):
        kind = "lesson"

    sort_order = data.get("sort_order")
    if sort_order is None:
        sort_order = pn

    p = BellSchedulePeriod(
        tenant_id=tenant_id,
        bell_schedule_id=schedule_id,
        period_number=pn,
        period_kind=kind,
        starts_at=starts,
        ends_at=ends,
        label=data.get("label"),
        sort_order=int(sort_order),
    )
    db.session.add(p)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return {"success": False, "error": "Period number must be unique for this schedule"}
    return {"success": True, "period": _serialize_period(p)}


def update_period(
    tenant_id: str, schedule_id: str, period_id: str, data: Dict[str, Any]
) -> Dict[str, Any]:
    p = BellSchedulePeriod.query.filter_by(
        id=period_id, tenant_id=tenant_id, bell_schedule_id=schedule_id
    ).first()
    if not p:
        return {"success": False, "error": "Period not found"}

    new_start = _parse_time(data.get("starts_at")) if "starts_at" in data else p.starts_at
    new_end = _parse_time(data.get("ends_at")) if "ends_at" in data else p.ends_at

    if new_start and new_end and new_start >= new_end:
        return {"success": False, "error": "starts_at must be before ends_at"}

    if new_start and new_end:
        overlap_err = _overlap_error_with_existing(
            tenant_id, schedule_id, new_start, new_end, exclude_period_id=str(p.id)
        )
        if overlap_err:
            return {"success": False, "error": overlap_err}

    if "period_number" in data:
        p.period_number = int(data["period_number"])
    if "period_kind" in data:
        p.period_kind = str(data["period_kind"]).strip()
    if "starts_at" in data:
        p.starts_at = new_start
    if "ends_at" in data:
        p.ends_at = new_end
    if "label" in data:
        p.label = data.get("label")
    if "sort_order" in data:
        p.sort_order = int(data["sort_order"])

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return {"success": False, "error": "Period number must be unique for this schedule"}
    return {"success": True, "period": _serialize_period(p)}


def delete_period(tenant_id: str, schedule_id: str, period_id: str) -> Dict[str, Any]:
    p = BellSchedulePeriod.query.filter_by(
        id=period_id, tenant_id=tenant_id, bell_schedule_id=schedule_id
    ).first()
    if not p:
        return {"success": False, "error": "Period not found"}
    db.session.delete(p)
    db.session.commit()
    return {"success": True, "message": "Period deleted"}


def _parse_date(val: Any) -> Optional[date]:
    if val is None or val == "":
        return None
    if isinstance(val, date):
        return val
    return date.fromisoformat(str(val)[:10])


def get_or_create_academic_settings(tenant_id: str) -> AcademicSettings:
    row = AcademicSettings.query.filter_by(tenant_id=tenant_id).first()
    if row:
        return row
    row = AcademicSettings(tenant_id=tenant_id)
    db.session.add(row)
    db.session.commit()
    return row


def patch_academic_settings(tenant_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    row = get_or_create_academic_settings(tenant_id)
    if "current_academic_year_id" in data:
        row.current_academic_year_id = data.get("current_academic_year_id")
    if "default_bell_schedule_id" in data:
        sid = data.get("default_bell_schedule_id")
        if sid:
            bs = BellSchedule.query.filter_by(id=sid, tenant_id=tenant_id).filter(
                BellSchedule.deleted_at.is_(None)
            ).first()
            if not bs:
                return {"success": False, "error": "Bell schedule not found"}
        row.default_bell_schedule_id = sid
    if "allow_admin_attendance_override" in data:
        row.allow_admin_attendance_override = bool(data["allow_admin_attendance_override"])
    if "default_working_days_json" in data:
        row.default_working_days_json = data.get("default_working_days_json")
    row.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return {
        "success": True,
        "settings": {
            "id": row.id,
            "current_academic_year_id": row.current_academic_year_id,
            "default_bell_schedule_id": row.default_bell_schedule_id,
            "allow_admin_attendance_override": row.allow_admin_attendance_override,
            "default_working_days_json": row.default_working_days_json,
        },
    }


def get_academic_settings(tenant_id: str) -> Dict[str, Any]:
    row = get_or_create_academic_settings(tenant_id)
    return {
        "success": True,
        "settings": {
            "id": row.id,
            "current_academic_year_id": row.current_academic_year_id,
            "default_bell_schedule_id": row.default_bell_schedule_id,
            "allow_admin_attendance_override": row.allow_admin_attendance_override,
            "default_working_days_json": row.default_working_days_json,
        },
    }
