"""Timetable versions and entries (weekly recurring) — academic backbone only."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.exc import IntegrityError

from backend.core.database import db
from backend.modules.academics.backbone.models import (
    AcademicSettings,
    ClassSubjectTeacher,
    TimetableEntry,
    TimetableVersion,
)
from backend.modules.classes.models import ClassSubject

from .bell_schedules import get_academic_settings, get_schedule
from .common import get_class_for_tenant


def _serialize_version(v: TimetableVersion) -> Dict[str, Any]:
    return {
        "id": v.id,
        "class_id": v.class_id,
        "bell_schedule_id": v.bell_schedule_id,
        "label": v.label,
        "status": v.status,
        "effective_from": v.effective_from.isoformat() if v.effective_from else None,
        "effective_to": v.effective_to.isoformat() if v.effective_to else None,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "updated_at": v.updated_at.isoformat() if v.updated_at else None,
    }


def _cst_id_for(tenant_id: str, class_subject_id: str, teacher_id: str) -> Optional[str]:
    row = ClassSubjectTeacher.query.filter(
        ClassSubjectTeacher.tenant_id == tenant_id,
        ClassSubjectTeacher.class_subject_id == class_subject_id,
        ClassSubjectTeacher.teacher_id == teacher_id,
        ClassSubjectTeacher.is_active.is_(True),
        ClassSubjectTeacher.deleted_at.is_(None),
    ).first()
    return str(row.id) if row else None


def _serialize_entry(
    e: TimetableEntry,
    bell_labels: Optional[Dict[int, Dict[str, Any]]] = None,
    *,
    tenant_id: Optional[str] = None,
    editable: bool = True,
    conflict_flags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    cs = e.class_subject
    subj = cs.subject_ref if cs else None
    t = e.teacher
    out: Dict[str, Any] = {
        "id": e.id,
        "timetable_version_id": e.timetable_version_id,
        "class_subject_id": e.class_subject_id,
        "subject_name": subj.name if subj else None,
        "teacher_id": e.teacher_id,
        "teacher_name": t.user.name if t and t.user else None,
        "day_of_week": e.day_of_week,
        "period_number": e.period_number,
        "room": e.room,
        "notes": e.notes,
        "entry_status": e.entry_status,
        "editable": editable,
        "conflict_flags": conflict_flags or [],
    }
    if tenant_id and e.teacher_id:
        out["class_subject_teacher_id"] = _cst_id_for(tenant_id, e.class_subject_id, str(e.teacher_id))
    if bell_labels and e.period_number in bell_labels:
        bl = bell_labels[e.period_number]
        out["period_name"] = bl.get("label")
        out["period_label"] = bl.get("label")
        out["starts_at"] = bl.get("starts_at")
        out["ends_at"] = bl.get("ends_at")
    return out


def _pd(val: Any) -> Optional[date]:
    if val is None or val == "":
        return None
    if isinstance(val, date):
        return val
    return date.fromisoformat(str(val)[:10])


def _working_weekdays(tenant_id: str) -> List[int]:
    row = AcademicSettings.query.filter_by(tenant_id=tenant_id).first()
    raw = row.default_working_days_json if row else None
    if isinstance(raw, list) and raw:
        days = [int(x) for x in raw if 1 <= int(x) <= 7]
        return sorted(set(days)) if days else [1, 2, 3, 4, 5]
    if isinstance(raw, dict):
        iso_map = {
            "monday": 1,
            "tuesday": 2,
            "wednesday": 3,
            "thursday": 4,
            "friday": 5,
            "saturday": 6,
            "sunday": 7,
        }
        days = [iso_map[k] for k, v in raw.items() if k in iso_map and v]
        return sorted(set(days)) if days else [1, 2, 3, 4, 5]
    return [1, 2, 3, 4, 5]


def _bell_period_map(tenant_id: str, bell_schedule_id: Optional[str]) -> Dict[int, Dict[str, Any]]:
    if not bell_schedule_id:
        return {}
    gr = get_schedule(tenant_id, bell_schedule_id, include_periods=True)
    if not gr["success"]:
        return {}
    m: Dict[int, Dict[str, Any]] = {}
    for p in gr["bell_schedule"].get("periods") or []:
        m[int(p["period_number"])] = p
    return m


def _lesson_period_numbers(tenant_id: str, bell_schedule_id: Optional[str]) -> List[int]:
    m = _bell_period_map(tenant_id, bell_schedule_id)
    nums: List[int] = []
    for pnum, p in sorted(m.items(), key=lambda x: (x[1].get("sort_order") or 0, x[0])):
        if p.get("period_kind") == "lesson":
            nums.append(pnum)
    return nums


def _bell_schedule_envelope(tenant_id: str, bell_schedule_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not bell_schedule_id:
        return None
    gr = get_schedule(tenant_id, bell_schedule_id, include_periods=True)
    if not gr["success"]:
        return None
    bs = gr["bell_schedule"]
    lesson_periods = []
    for p in sorted(bs.get("periods") or [], key=lambda x: (x.get("sort_order") or 0, x["period_number"])):
        if p.get("period_kind") == "lesson":
            lesson_periods.append(p)
    return {
        "id": bs["id"],
        "name": bs["name"],
        "lesson_periods": lesson_periods,
    }


def list_versions(tenant_id: str, class_id: str, *, include_drafts: bool = True) -> Dict[str, Any]:
    cls = get_class_for_tenant(class_id, tenant_id)
    if not cls:
        return {"success": False, "error": "Class not found"}
    q = TimetableVersion.query.filter_by(tenant_id=tenant_id, class_id=class_id)
    if not include_drafts:
        q = q.filter(TimetableVersion.status == "active")
    rows = q.order_by(TimetableVersion.created_at.desc()).all()
    return {"success": True, "items": [_serialize_version(r) for r in rows]}


def create_version(tenant_id: str, class_id: str, data: Dict[str, Any], user_id: Optional[str]) -> Dict[str, Any]:
    cls = get_class_for_tenant(class_id, tenant_id)
    if not cls:
        return {"success": False, "error": "Class not found"}

    settings = get_academic_settings(tenant_id)
    default_bell = settings["settings"].get("default_bell_schedule_id")

    v = TimetableVersion(
        tenant_id=tenant_id,
        class_id=class_id,
        bell_schedule_id=data.get("bell_schedule_id", default_bell),
        label=data.get("label"),
        status=str(data.get("status") or "draft").strip(),
        effective_from=_pd(data.get("effective_from")),
        effective_to=_pd(data.get("effective_to")),
        created_by=user_id,
    )
    db.session.add(v)
    try:
        db.session.commit()
    except IntegrityError as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}
    return {"success": True, "version": _serialize_version(v)}


def update_version(
    tenant_id: str, class_id: str, version_id: str, data: Dict[str, Any]
) -> Dict[str, Any]:
    v = TimetableVersion.query.filter_by(
        id=version_id, tenant_id=tenant_id, class_id=class_id
    ).first()
    if not v:
        return {"success": False, "error": "Timetable version not found"}

    if "bell_schedule_id" in data:
        v.bell_schedule_id = data.get("bell_schedule_id")
    if "label" in data:
        v.label = data.get("label")
    if "status" in data and data["status"]:
        v.status = str(data["status"]).strip()
    if "effective_from" in data:
        v.effective_from = _pd(data.get("effective_from"))
    if "effective_to" in data:
        v.effective_to = _pd(data.get("effective_to"))

    v.updated_at = datetime.now(timezone.utc)
    try:
        db.session.commit()
    except IntegrityError as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}
    return {"success": True, "version": _serialize_version(v)}


def activate_version(tenant_id: str, class_id: str, version_id: str) -> Dict[str, Any]:
    cls = get_class_for_tenant(class_id, tenant_id)
    if not cls:
        return {"success": False, "error": "Class not found"}

    target = TimetableVersion.query.filter_by(
        id=version_id, tenant_id=tenant_id, class_id=class_id
    ).first()
    if not target:
        return {"success": False, "error": "Timetable version not found"}

    others = TimetableVersion.query.filter_by(tenant_id=tenant_id, class_id=class_id).filter(
        TimetableVersion.id != version_id,
        TimetableVersion.status == "active",
    ).all()
    for o in others:
        o.status = "archived"
        o.updated_at = datetime.now(timezone.utc)

    target.status = "active"
    target.updated_at = datetime.now(timezone.utc)
    try:
        db.session.commit()
    except IntegrityError as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}
    return {"success": True, "version": _serialize_version(target)}


def delete_version(tenant_id: str, class_id: str, version_id: str) -> Dict[str, Any]:
    v = TimetableVersion.query.filter_by(
        id=version_id, tenant_id=tenant_id, class_id=class_id
    ).first()
    if not v:
        return {"success": False, "error": "Timetable version not found"}
    if v.status != "draft":
        return {"success": False, "error": "Only draft versions can be deleted"}
    db.session.delete(v)
    try:
        db.session.commit()
    except IntegrityError as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}
    return {"success": True, "message": "Draft version deleted"}


def clone_active_to_draft(
    tenant_id: str, class_id: str, user_id: Optional[str], data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    data = data or {}
    cls = get_class_for_tenant(class_id, tenant_id)
    if not cls:
        return {"success": False, "error": "Class not found"}

    active = (
        TimetableVersion.query.filter_by(tenant_id=tenant_id, class_id=class_id)
        .filter(TimetableVersion.status == "active")
        .order_by(TimetableVersion.created_at.desc())
        .first()
    )
    if not active:
        return {"success": False, "error": "No active timetable to clone"}

    label = (data.get("label") or "").strip() or f"Copy of {active.label or 'active'}"

    new_v = TimetableVersion(
        tenant_id=tenant_id,
        class_id=class_id,
        bell_schedule_id=active.bell_schedule_id,
        label=label,
        status="draft",
        created_by=user_id,
    )
    db.session.add(new_v)
    db.session.flush()

    for e in active.entries:
        copy_e = TimetableEntry(
            tenant_id=tenant_id,
            timetable_version_id=new_v.id,
            class_subject_id=e.class_subject_id,
            teacher_id=e.teacher_id,
            day_of_week=e.day_of_week,
            period_number=e.period_number,
            room=e.room,
            notes=e.notes,
            entry_status=e.entry_status or "active",
        )
        db.session.add(copy_e)

    try:
        db.session.commit()
    except IntegrityError as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}
    return {"success": True, "version": _serialize_version(new_v)}


def _teacher_slots_occupied(
    tenant_id: str, exclude_entry_id: Optional[str] = None
) -> Set[Tuple[str, int, int]]:
    q = (
        db.session.query(
            TimetableEntry.teacher_id,
            TimetableEntry.day_of_week,
            TimetableEntry.period_number,
        )
        .join(TimetableVersion, TimetableEntry.timetable_version_id == TimetableVersion.id)
        .filter(
            TimetableEntry.tenant_id == tenant_id,
            TimetableEntry.entry_status == "active",
            TimetableVersion.status.in_(["active", "draft"]),
            TimetableEntry.teacher_id.isnot(None),
        )
    )
    if exclude_entry_id:
        q = q.filter(TimetableEntry.id != exclude_entry_id)
    rows = q.all()
    return {(str(r[0]), int(r[1]), int(r[2])) for r in rows}


def _teacher_conflict(
    tenant_id: str,
    teacher_id: str,
    day_of_week: int,
    period_number: int,
    exclude_entry_id: Optional[str],
) -> bool:
    tid = str(teacher_id)
    return (tid, day_of_week, period_number) in _teacher_slots_occupied(tenant_id, exclude_entry_id)


def _ensure_draft(v: TimetableVersion) -> Optional[str]:
    if v.status != "draft":
        return "Only draft timetable versions can be edited. Clone the active version or create a draft."
    return None


def _valid_lesson_period(tenant_id: str, bell_schedule_id: Optional[str], period_number: int) -> bool:
    if not bell_schedule_id:
        return False
    return period_number in _lesson_period_numbers(tenant_id, bell_schedule_id)


def _valid_teacher_for_class_subject(
    tenant_id: str, class_subject_id: str, teacher_id: str
) -> bool:
    q = ClassSubjectTeacher.query.filter(
        ClassSubjectTeacher.tenant_id == tenant_id,
        ClassSubjectTeacher.class_subject_id == class_subject_id,
        ClassSubjectTeacher.teacher_id == teacher_id,
        ClassSubjectTeacher.is_active.is_(True),
        ClassSubjectTeacher.deleted_at.is_(None),
    ).first()
    return q is not None


def _entry_conflict_flags(
    tenant_id: str,
    entry: TimetableEntry,
    bell_schedule_id: Optional[str],
    exclude_self: bool = True,
) -> List[str]:
    flags: List[str] = []
    if not entry.teacher_id:
        return ["missing_teacher"]
    ex = entry.id if exclude_self else None
    if _teacher_conflict(tenant_id, str(entry.teacher_id), entry.day_of_week, entry.period_number, ex):
        flags.append("teacher_double_booked")
    if not _valid_lesson_period(tenant_id, bell_schedule_id, entry.period_number):
        flags.append("period_not_in_bell_schedule")
    return flags


def list_entries_for_active_or_draft(
    tenant_id: str,
    class_id: str,
    version_id: Optional[str] = None,
    *,
    reader_mode: bool = False,
) -> Dict[str, Any]:
    cls = get_class_for_tenant(class_id, tenant_id)
    if not cls:
        return {"success": False, "error": "Class not found"}

    if reader_mode:
        # Non-admins: only the published (active) timetable — never drafts or archived.
        v = (
            TimetableVersion.query.filter_by(tenant_id=tenant_id, class_id=class_id)
            .filter(TimetableVersion.status == "active")
            .order_by(TimetableVersion.created_at.desc())
            .first()
        )
    elif version_id:
        v = TimetableVersion.query.filter_by(
            id=version_id, tenant_id=tenant_id, class_id=class_id
        ).first()
    else:
        v = (
            TimetableVersion.query.filter_by(tenant_id=tenant_id, class_id=class_id)
            .filter(TimetableVersion.status == "active")
            .order_by(TimetableVersion.created_at.desc())
            .first()
        )
        if not v:
            v = (
                TimetableVersion.query.filter_by(tenant_id=tenant_id, class_id=class_id)
                .filter(TimetableVersion.status == "draft")
                .order_by(TimetableVersion.created_at.desc())
                .first()
            )

    if not v:
        return {
            "success": True,
            "timetable_version": None,
            "items": [],
            "bell_schedule": None,
            "working_days": _working_weekdays(tenant_id),
            "editable": False,
        }

    bell_map = _bell_period_map(tenant_id, v.bell_schedule_id)
    rows = (
        TimetableEntry.query.filter_by(tenant_id=tenant_id, timetable_version_id=v.id)
        .order_by(TimetableEntry.day_of_week, TimetableEntry.period_number)
        .all()
    )
    editable = v.status == "draft"
    items: List[Dict[str, Any]] = []
    for r in rows:
        flags = _entry_conflict_flags(tenant_id, r, v.bell_schedule_id, exclude_self=True)
        items.append(
            _serialize_entry(
                r,
                bell_map,
                tenant_id=tenant_id,
                editable=editable,
                conflict_flags=flags,
            )
        )

    return {
        "success": True,
        "timetable_version": _serialize_version(v),
        "items": items,
        "bell_schedule": _bell_schedule_envelope(tenant_id, v.bell_schedule_id),
        "working_days": _working_weekdays(tenant_id),
        "editable": editable,
    }


def create_entry(tenant_id: str, class_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    version_id = data.get("timetable_version_id")
    if not version_id:
        return {"success": False, "error": "timetable_version_id is required"}

    v = TimetableVersion.query.filter_by(
        id=version_id, tenant_id=tenant_id, class_id=class_id
    ).first()
    if not v:
        return {"success": False, "error": "Timetable version not found for this class"}

    err = _ensure_draft(v)
    if err:
        return {"success": False, "error": err}

    cs = ClassSubject.query.filter_by(
        id=data.get("class_subject_id"), tenant_id=tenant_id, class_id=class_id
    ).filter(ClassSubject.deleted_at.is_(None)).first()
    if not cs or cs.status != "active":
        return {"success": False, "error": "class_subject_id invalid or inactive"}

    teacher_id = data.get("teacher_id")
    if not teacher_id:
        return {"success": False, "error": "teacher_id is required"}
    if not _valid_teacher_for_class_subject(tenant_id, cs.id, teacher_id):
        return {"success": False, "error": "Teacher is not assigned to this class subject"}

    try:
        day = int(data["day_of_week"])
        period = int(data["period_number"])
    except (KeyError, TypeError, ValueError):
        return {"success": False, "error": "day_of_week and period_number are required integers"}

    if day not in _working_weekdays(tenant_id):
        return {"success": False, "error": "day_of_week is not a working day for this school"}
    if not _valid_lesson_period(tenant_id, v.bell_schedule_id, period):
        return {
            "success": False,
            "error": "period_number must match a lesson period in this version's bell schedule",
        }

    if _teacher_conflict(tenant_id, teacher_id, day, period, None):
        return {
            "success": False,
            "error": "Teacher is already scheduled in another class at this day and period",
        }

    e = TimetableEntry(
        tenant_id=tenant_id,
        timetable_version_id=version_id,
        class_subject_id=cs.id,
        teacher_id=teacher_id,
        day_of_week=day,
        period_number=period,
        room=data.get("room"),
        notes=data.get("notes"),
        entry_status=(data.get("entry_status") or "active").strip() or "active",
    )
    db.session.add(e)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return {"success": False, "error": "This class already has a subject in this day/period slot"}
    bell_map = _bell_period_map(tenant_id, v.bell_schedule_id)
    flags = _entry_conflict_flags(tenant_id, e, v.bell_schedule_id, exclude_self=True)
    return {
        "success": True,
        "entry": _serialize_entry(
            e, bell_map, tenant_id=tenant_id, editable=True, conflict_flags=flags
        ),
    }


def update_entry(
    tenant_id: str, class_id: str, entry_id: str, data: Dict[str, Any]
) -> Dict[str, Any]:
    e = TimetableEntry.query.filter_by(id=entry_id, tenant_id=tenant_id).first()
    if not e:
        return {"success": False, "error": "Entry not found"}

    v = TimetableVersion.query.filter_by(
        id=e.timetable_version_id, tenant_id=tenant_id, class_id=class_id
    ).first()
    if not v:
        return {"success": False, "error": "Entry does not belong to this class"}

    err = _ensure_draft(v)
    if err:
        return {"success": False, "error": err}

    cs = ClassSubject.query.filter_by(id=e.class_subject_id, tenant_id=tenant_id, class_id=class_id).first()
    if not cs:
        return {"success": False, "error": "Invalid class subject"}

    teacher_id = data.get("teacher_id", e.teacher_id)
    class_subject_id = data.get("class_subject_id", e.class_subject_id)

    cs_target = ClassSubject.query.filter_by(
        id=class_subject_id, tenant_id=tenant_id, class_id=class_id
    ).filter(ClassSubject.deleted_at.is_(None)).first()
    if not cs_target or cs_target.status != "active":
        return {"success": False, "error": "class_subject_id invalid or inactive"}

    if not _valid_teacher_for_class_subject(tenant_id, cs_target.id, teacher_id):
        return {"success": False, "error": "Teacher is not assigned to this class subject"}

    day = int(data.get("day_of_week", e.day_of_week))
    period = int(data.get("period_number", e.period_number))

    if day not in _working_weekdays(tenant_id):
        return {"success": False, "error": "day_of_week is not a working day for this school"}
    if not _valid_lesson_period(tenant_id, v.bell_schedule_id, period):
        return {
            "success": False,
            "error": "period_number must match a lesson period in this version's bell schedule",
        }

    if _teacher_conflict(tenant_id, str(teacher_id), day, period, e.id):
        return {
            "success": False,
            "error": "Teacher is already scheduled in another class at this day and period",
        }

    e.class_subject_id = cs_target.id
    e.teacher_id = teacher_id
    e.day_of_week = day
    e.period_number = period
    if "room" in data:
        e.room = data.get("room")
    if "notes" in data:
        e.notes = data.get("notes")
    if "entry_status" in data and data["entry_status"]:
        e.entry_status = str(data["entry_status"]).strip()

    e.updated_at = datetime.now(timezone.utc)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return {"success": False, "error": "This class already has a subject in this day/period slot"}

    bell_map = _bell_period_map(tenant_id, v.bell_schedule_id)
    db.session.refresh(e)
    flags = _entry_conflict_flags(tenant_id, e, v.bell_schedule_id, exclude_self=True)
    return {
        "success": True,
        "entry": _serialize_entry(
            e, bell_map, tenant_id=tenant_id, editable=True, conflict_flags=flags
        ),
    }


def delete_entry(tenant_id: str, class_id: str, entry_id: str) -> Dict[str, Any]:
    e = TimetableEntry.query.filter_by(id=entry_id, tenant_id=tenant_id).first()
    if not e:
        return {"success": False, "error": "Entry not found"}

    v = TimetableVersion.query.filter_by(
        id=e.timetable_version_id, tenant_id=tenant_id, class_id=class_id
    ).first()
    if not v:
        return {"success": False, "error": "Entry does not belong to this class"}

    err = _ensure_draft(v)
    if err:
        return {"success": False, "error": err}

    db.session.delete(e)
    db.session.commit()
    return {"success": True, "message": "Entry deleted"}


def move_entry(
    tenant_id: str, class_id: str, entry_id: str, data: Dict[str, Any]
) -> Dict[str, Any]:
    try:
        day = int(data["day_of_week"])
        period = int(data["period_number"])
    except (KeyError, TypeError, ValueError):
        return {"success": False, "error": "day_of_week and period_number are required integers"}
    return update_entry(
        tenant_id,
        class_id,
        entry_id,
        {"day_of_week": day, "period_number": period},
    )


def swap_entries(tenant_id: str, class_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    a_id = data.get("entry_a_id")
    b_id = data.get("entry_b_id")
    if not a_id or not b_id or a_id == b_id:
        return {"success": False, "error": "entry_a_id and entry_b_id are required"}

    ea = TimetableEntry.query.filter_by(id=a_id, tenant_id=tenant_id).first()
    eb = TimetableEntry.query.filter_by(id=b_id, tenant_id=tenant_id).first()
    if not ea or not eb:
        return {"success": False, "error": "One or both entries not found"}
    if ea.timetable_version_id != eb.timetable_version_id:
        return {"success": False, "error": "Entries must belong to the same timetable version"}

    v = TimetableVersion.query.filter_by(
        id=ea.timetable_version_id, tenant_id=tenant_id, class_id=class_id
    ).first()
    if not v:
        return {"success": False, "error": "Entry does not belong to this class"}

    err = _ensure_draft(v)
    if err:
        return {"success": False, "error": err}

    da, pa = ea.day_of_week, ea.period_number
    db, pb = eb.day_of_week, eb.period_number

    if _teacher_conflict(tenant_id, str(ea.teacher_id), db, pb, ea.id):
        return {"success": False, "error": "Cannot swap: teacher would conflict at the target slot"}
    if _teacher_conflict(tenant_id, str(eb.teacher_id), da, pa, eb.id):
        return {"success": False, "error": "Cannot swap: teacher would conflict at the target slot"}

    ea.day_of_week, ea.period_number = db, pb
    eb.day_of_week, eb.period_number = da, pa
    ea.updated_at = datetime.now(timezone.utc)
    eb.updated_at = datetime.now(timezone.utc)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return {"success": False, "error": "Swap would create a duplicate slot"}

    bell_map = _bell_period_map(tenant_id, v.bell_schedule_id)
    db.session.refresh(ea)
    db.session.refresh(eb)
    return {
        "success": True,
        "entry_a": _serialize_entry(
            ea,
            bell_map,
            tenant_id=tenant_id,
            editable=True,
            conflict_flags=_entry_conflict_flags(tenant_id, ea, v.bell_schedule_id, exclude_self=True),
        ),
        "entry_b": _serialize_entry(
            eb,
            bell_map,
            tenant_id=tenant_id,
            editable=True,
            conflict_flags=_entry_conflict_flags(tenant_id, eb, v.bell_schedule_id, exclude_self=True),
        ),
    }


def _primary_teacher_id(tenant_id: str, cs: ClassSubject) -> Optional[str]:
    primary = (
        ClassSubjectTeacher.query.filter(
            ClassSubjectTeacher.class_subject_id == cs.id,
            ClassSubjectTeacher.tenant_id == tenant_id,
            ClassSubjectTeacher.role == "primary",
            ClassSubjectTeacher.is_active.is_(True),
            ClassSubjectTeacher.deleted_at.is_(None),
        ).first()
    )
    if primary:
        return str(primary.teacher_id)
    fallback = (
        ClassSubjectTeacher.query.filter(
            ClassSubjectTeacher.class_subject_id == cs.id,
            ClassSubjectTeacher.tenant_id == tenant_id,
            ClassSubjectTeacher.is_active.is_(True),
            ClassSubjectTeacher.deleted_at.is_(None),
        )
        .order_by(ClassSubjectTeacher.role)
        .first()
    )
    return str(fallback.teacher_id) if fallback else None


def generate_draft(
    tenant_id: str, class_id: str, user_id: Optional[str], data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    data = data or {}
    cls = get_class_for_tenant(class_id, tenant_id)
    if not cls:
        return {"success": False, "error": "Class not found"}

    settings = get_academic_settings(tenant_id)
    default_bell = settings["settings"].get("default_bell_schedule_id")

    offerings = (
        ClassSubject.query.filter_by(tenant_id=tenant_id, class_id=class_id)
        .filter(ClassSubject.deleted_at.is_(None), ClassSubject.status == "active")
        .all()
    )
    if not offerings:
        return {"success": False, "error": "No active class subjects to schedule"}

    working_days = _working_weekdays(tenant_id)
    target_vid = data.get("timetable_version_id")

    v: Optional[TimetableVersion] = None
    if target_vid:
        v = TimetableVersion.query.filter_by(
            id=target_vid, tenant_id=tenant_id, class_id=class_id
        ).first()
        if not v:
            return {"success": False, "error": "Timetable version not found for this class"}
        if v.status != "draft":
            return {"success": False, "error": "Generation is only allowed for draft versions"}
        TimetableEntry.query.filter_by(timetable_version_id=v.id).delete()
        db.session.flush()
    else:
        bell_for_new = data.get("bell_schedule_id") or default_bell
        v = TimetableVersion(
            tenant_id=tenant_id,
            class_id=class_id,
            bell_schedule_id=bell_for_new,
            label=data.get("label") or "Generated draft",
            status="draft",
            created_by=user_id,
        )
        db.session.add(v)
        db.session.flush()

    assert v is not None
    bell_id = v.bell_schedule_id or default_bell
    if not bell_id:
        db.session.rollback()
        return {"success": False, "error": "Set a default bell schedule in academic settings or pick one for this version"}

    if not v.bell_schedule_id:
        v.bell_schedule_id = bell_id

    gr = get_schedule(tenant_id, bell_id, include_periods=True)
    if not gr.get("success"):
        db.session.rollback()
        return {"success": False, "error": "Bell schedule not found"}

    lesson_periods = _lesson_period_numbers(tenant_id, bell_id)
    if not lesson_periods:
        db.session.rollback()
        return {"success": False, "error": "Bell schedule has no lesson periods"}

    work: List[Tuple[str, str]] = []
    warnings: List[str] = []

    for cs in offerings:
        tid = _primary_teacher_id(tenant_id, cs)
        if not tid:
            warnings.append(
                f"No teacher assigned for subject {cs.subject_ref.name if cs.subject_ref else cs.id}"
            )
            continue
        for _ in range(int(cs.weekly_periods or 0)):
            work.append((cs.id, tid))

    if not work:
        db.session.rollback()
        return {
            "success": False,
            "error": "No schedulable subjects (assign teachers to class subjects)",
            "warnings": warnings,
        }

    # Stable order: group periods of the same subject together, then fill days in calendar order
    # using the earliest free lesson slot each time — keeps lessons contiguous within each day when possible.
    work.sort(key=lambda x: x[0])
    slots_ordered: List[Tuple[int, int]] = [
        (d, p) for d in sorted(working_days) for p in sorted(lesson_periods)
    ]

    used_teacher: Set[Tuple[str, int, int]] = set(_teacher_slots_occupied(tenant_id))
    used_class: Set[Tuple[int, int]] = set()

    placed = 0
    for cs_id, tid in work:
        chosen: Optional[Tuple[int, int]] = None
        for day, period in slots_ordered:
            if (day, period) in used_class:
                continue
            key = (str(tid), day, period)
            if key in used_teacher:
                continue
            chosen = (day, period)
            break

        if chosen is None:
            subj = ClassSubject.query.filter_by(id=cs_id, tenant_id=tenant_id).first()
            name = subj.subject_ref.name if subj and subj.subject_ref else cs_id
            warnings.append(f"Could not place all periods for {name} — grid full or teacher conflicts")
            continue

        day, period = chosen
        e = TimetableEntry(
            tenant_id=tenant_id,
            timetable_version_id=v.id,
            class_subject_id=cs_id,
            teacher_id=tid,
            day_of_week=day,
            period_number=period,
            entry_status="active",
        )
        db.session.add(e)
        used_class.add((day, period))
        used_teacher.add((str(tid), day, period))
        placed += 1

    try:
        db.session.commit()
    except IntegrityError as err:
        db.session.rollback()
        return {"success": False, "error": str(err), "warnings": warnings}

    unplaced = len(work) - placed
    return {
        "success": True,
        "timetable_version": _serialize_version(v),
        "entries_placed": placed,
        "total_required": len(work),
        "unplaced_periods": unplaced,
        "warnings": warnings,
        "conflicts": [w for w in warnings if "conflict" in w.lower() or "Could not place" in w],
    }
