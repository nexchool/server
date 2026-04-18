"""Timetable versions and entries (weekly recurring) — academic backbone only."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.exc import IntegrityError

from core.database import db
from modules.academics.backbone.models import (
    AcademicSettings,
    BellSchedulePeriod,
    ClassSubjectTeacher,
    TimetableEntry,
    TimetableVersion,
)
from modules.classes.models import ClassSubject

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
        return sorted(set(days)) if days else [1, 2, 3, 4, 5, 6]
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
        return sorted(set(days)) if days else [1, 2, 3, 4, 5, 6]
    return [1, 2, 3, 4, 5, 6]


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

    resolved_bell = data.get("bell_schedule_id", default_bell)
    if resolved_bell is None or resolved_bell == "":
        resolved_bell = default_bell
    if not resolved_bell:
        return {
            "success": False,
            "error": "bell_schedule_id is required when no default bell schedule is set in academic settings",
        }

    v = TimetableVersion(
        tenant_id=tenant_id,
        class_id=class_id,
        bell_schedule_id=resolved_bell,
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
    tenant_id: str,
    exclude_entry_id: Optional[str] = None,
    exclude_class_id: Optional[str] = None,
) -> Set[Tuple[str, int, int]]:
    """Return occupied (teacher_id, day, period) tuples for generator slot-avoidance."""
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
    # Exclude all versions (active or draft) for the same class — only one version of a
    # class will ever be live at a time, so none of its versions are real cross-class conflicts.
    if exclude_class_id:
        q = q.filter(TimetableVersion.class_id != exclude_class_id)
    rows = q.all()
    return {(str(r[0]), int(r[1]), int(r[2])) for r in rows}


def _teacher_occupied_with_schedule(
    tenant_id: str,
    exclude_entry_id: Optional[str] = None,
    exclude_class_id: Optional[str] = None,
) -> List[Tuple[str, int, int, Optional[str]]]:
    """Return occupied (teacher_id, day, period_number, bell_schedule_id) rows.

    Used by time-range-aware conflict detection so we can check whether two entries
    from *different* bell schedules actually overlap in clock time.
    """
    q = (
        db.session.query(
            TimetableEntry.teacher_id,
            TimetableEntry.day_of_week,
            TimetableEntry.period_number,
            TimetableVersion.bell_schedule_id,
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
    if exclude_class_id:
        q = q.filter(TimetableVersion.class_id != exclude_class_id)
    return [(str(r[0]), int(r[1]), int(r[2]), r[3]) for r in q.all()]


def _load_period_times(
    tenant_id: str,
    schedule_period_pairs: List[Tuple[Optional[str], int]],
) -> Dict[Tuple[str, int], Tuple]:
    """Batch-load (starts_at, ends_at) for a set of (bell_schedule_id, period_number) pairs."""
    valid_ids = list({s for s, _ in schedule_period_pairs if s})
    if not valid_ids:
        return {}
    rows = BellSchedulePeriod.query.filter(
        BellSchedulePeriod.tenant_id == tenant_id,
        BellSchedulePeriod.bell_schedule_id.in_(valid_ids),
    ).all()
    result: Dict[Tuple[str, int], Tuple] = {}
    for r in rows:
        if r.starts_at and r.ends_at:
            result[(str(r.bell_schedule_id), int(r.period_number))] = (r.starts_at, r.ends_at)
    return result


def _teacher_conflict(
    tenant_id: str,
    teacher_id: str,
    day_of_week: int,
    period_number: int,
    exclude_entry_id: Optional[str],
    exclude_class_id: Optional[str] = None,
    bell_schedule_id: Optional[str] = None,
) -> bool:
    """Check whether a teacher is double-booked at a given day + period.

    When the incoming entry and an existing entry share the same bell schedule, a matching
    period number is an exact conflict.  When they use *different* bell schedules (e.g. a
    teacher covers both a Play School class with its own timing and a Primary class), we
    compare the actual clock-time ranges and flag a conflict only when those ranges overlap.
    If period times are unavailable for either side we fall back conservatively to the
    period-number equality check.
    """
    tid = str(teacher_id)
    occupied = _teacher_occupied_with_schedule(tenant_id, exclude_entry_id, exclude_class_id)

    # Filter to same teacher + same day first to reduce work
    candidates = [
        (occ_pnum, occ_bs)
        for occ_tid, occ_day, occ_pnum, occ_bs in occupied
        if occ_tid == tid and occ_day == day_of_week
    ]
    if not candidates:
        return False

    # If no bell schedule context is available fall back to period-number equality
    if bell_schedule_id is None:
        return any(pnum == period_number for pnum, _ in candidates)

    # Batch-load period times for all relevant (schedule, period) pairs in one query
    pairs: List[Tuple[Optional[str], int]] = [(bell_schedule_id, period_number)]
    pairs += [(bs, pnum) for pnum, bs in candidates if bs]
    time_cache = _load_period_times(tenant_id, pairs)

    new_range = time_cache.get((bell_schedule_id, period_number))

    for occ_pnum, occ_bs in candidates:
        if occ_bs == bell_schedule_id:
            # Same bell schedule — period number equality is exact and cheap
            if occ_pnum == period_number:
                return True
        elif new_range is not None and occ_bs is not None:
            occ_range = time_cache.get((str(occ_bs), occ_pnum))
            if occ_range is not None:
                # Time-range overlap: conflict iff intervals [new_start, new_end) and
                # [occ_start, occ_end) intersect — i.e. new_start < occ_end AND new_end > occ_start
                new_start, new_end = new_range
                occ_start, occ_end = occ_range
                if new_start < occ_end and new_end > occ_start:
                    return True
                # Ranges are disjoint → no conflict; do NOT fall back to period equality
            else:
                # Occupied period has no time data; conservative fallback
                if occ_pnum == period_number:
                    return True
        else:
            # No time data available for either side; conservative fallback
            if occ_pnum == period_number:
                return True

    return False


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
    exclude_class_id: Optional[str] = None,
) -> List[str]:
    flags: List[str] = []
    if not entry.teacher_id:
        return ["missing_teacher"]
    ex = entry.id if exclude_self else None
    if _teacher_conflict(
        tenant_id,
        str(entry.teacher_id),
        entry.day_of_week,
        entry.period_number,
        ex,
        exclude_class_id,
        bell_schedule_id=bell_schedule_id,
    ):
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
    # Always exclude all versions of this class from conflict checks — whether viewing the
    # active or a draft, no other version of the same class is a real cross-class conflict.
    excl_class = str(v.class_id)
    items: List[Dict[str, Any]] = []
    for r in rows:
        flags = _entry_conflict_flags(
            tenant_id, r, v.bell_schedule_id, exclude_self=True, exclude_class_id=excl_class
        )
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

    if _teacher_conflict(tenant_id, teacher_id, day, period, None, class_id, bell_schedule_id=v.bell_schedule_id):
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
    flags = _entry_conflict_flags(tenant_id, e, v.bell_schedule_id, exclude_self=True, exclude_class_id=class_id)
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

    if _teacher_conflict(tenant_id, str(teacher_id), day, period, e.id, class_id, bell_schedule_id=v.bell_schedule_id):
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
    flags = _entry_conflict_flags(tenant_id, e, v.bell_schedule_id, exclude_self=True, exclude_class_id=class_id)
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
    db_, pb = eb.day_of_week, eb.period_number

    if _teacher_conflict(tenant_id, str(ea.teacher_id), db_, pb, ea.id, class_id, bell_schedule_id=v.bell_schedule_id):
        return {"success": False, "error": "Cannot swap: teacher would conflict at the target slot"}
    if _teacher_conflict(tenant_id, str(eb.teacher_id), da, pa, eb.id, class_id, bell_schedule_id=v.bell_schedule_id):
        return {"success": False, "error": "Cannot swap: teacher would conflict at the target slot"}

    ea.day_of_week, ea.period_number = db_, pb
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
            conflict_flags=_entry_conflict_flags(
                tenant_id, ea, v.bell_schedule_id, exclude_self=True, exclude_class_id=class_id
            ),
        ),
        "entry_b": _serialize_entry(
            eb,
            bell_map,
            tenant_id=tenant_id,
            editable=True,
            conflict_flags=_entry_conflict_flags(
                tenant_id, eb, v.bell_schedule_id, exclude_self=True, exclude_class_id=class_id
            ),
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
    """Generate a balanced weekly draft timetable for a class.

    This is the outer "DB layer" — it owns transaction management and the
    :class:`TimetableVersion` / :class:`TimetableEntry` rows.  The actual
    scheduling is delegated to
    :func:`modules.academics.services.timetable_generator.generate_timetable`,
    which implements the constraint-based algorithm.

    ``data`` accepted keys:
        * ``timetable_version_id`` — reuse an existing draft (wipes its entries)
        * ``bell_schedule_id`` — override bell schedule for the version
        * ``label`` — label for a brand-new draft version
        * ``seed`` — deterministic generator seed (useful for tests)
        * ``max_attempts`` — multi-start budget (default 40)
    """
    from .timetable_generator import generate_timetable as _run_generator

    data = data or {}
    cls = get_class_for_tenant(class_id, tenant_id)
    if not cls:
        return {"success": False, "error": "Class not found"}

    settings = get_academic_settings(tenant_id)
    default_bell = settings["settings"].get("default_bell_schedule_id")

    offerings_exist = (
        ClassSubject.query.filter_by(tenant_id=tenant_id, class_id=class_id)
        .filter(ClassSubject.deleted_at.is_(None), ClassSubject.status == "active")
        .first()
    )
    if not offerings_exist:
        return {"success": False, "error": "No active class subjects to schedule"}

    working_days = _working_weekdays(tenant_id)
    target_vid = data.get("timetable_version_id")

    # --- Version handling -------------------------------------------------
    # Either reuse an existing draft (wiping its entries) or create a new
    # draft.  We do NOT commit the version alone — it's only committed once
    # the generated entries are persisted together, so a failed generation
    # never leaves an empty draft behind.
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
        if data.get("bell_schedule_id"):
            v.bell_schedule_id = data["bell_schedule_id"]
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
        return {
            "success": False,
            "error": "Set a default bell schedule in academic settings or pick one for this version",
        }
    if not v.bell_schedule_id:
        v.bell_schedule_id = bell_id

    # --- Run the scheduler ------------------------------------------------
    gen = _run_generator(
        tenant_id,
        class_id,
        bell_schedule_id=bell_id,
        working_days=working_days,
        class_teacher_user_id=str(cls.teacher_id) if cls.teacher_id else None,
        exclude_class_id=class_id,
        seed=data.get("seed"),
        max_attempts=int(data.get("max_attempts") or 40),
    )
    if not gen.get("success"):
        db.session.rollback()
        return {
            "success": False,
            "error": gen.get("error") or "Generation failed",
            "warnings": gen.get("warnings", []),
        }

    # --- Persist placements as TimetableEntry rows ------------------------
    placements = gen["placements"]
    for p in placements:
        entry = TimetableEntry(
            tenant_id=tenant_id,
            timetable_version_id=v.id,
            class_subject_id=p["class_subject_id"],
            teacher_id=p["teacher_id"],
            day_of_week=int(p["day_of_week"]),
            period_number=int(p["period_number"]),
            entry_status="active",
        )
        db.session.add(entry)

    try:
        db.session.commit()
    except IntegrityError as err:
        db.session.rollback()
        return {
            "success": False,
            "error": str(err),
            "warnings": gen.get("warnings", []),
        }

    total_needed = len(placements) + len(gen.get("unplaced", []))
    return {
        "success": True,
        "timetable_version": _serialize_version(v),
        "entries_placed": len(placements),
        "total_required": total_needed,
        "unplaced_periods": len(gen.get("unplaced", [])),
        "warnings": gen.get("warnings", []),
        "conflicts": gen.get("unplaced", []),
        "quality_score": gen.get("quality_score"),
        "draft_quality": gen.get("draft_quality"),
        "timetable": gen.get("timetable", {}),
        "debug": gen.get("debug", []),
    }


# ---------------------------------------------------------------------------
# Today's schedule — read-time overlay of teacher availability / leave
# ---------------------------------------------------------------------------
#
# The weekly generator deliberately ignores ``TeacherAvailability`` and
# approved ``TeacherLeave`` because those states change daily.  Instead,
# they are overlayed at read time: the timetable entry still exists, but
# we annotate it with ``availability_status`` (available | unavailable |
# on_leave) and ``substitute_needed`` so the UI can surface the info.

def get_today_schedule(
    tenant_id: str, class_id: str, on_date: Optional[date] = None
) -> Dict[str, Any]:
    """Return the active timetable for ``class_id`` on ``on_date`` with
    teacher availability overlayed onto each entry.

    Defaults to today (``date.today()``).  If the day is not a working
    day or no active timetable exists, ``items`` is an empty list.
    """
    from .timetable_generator import overlay_daily_schedule

    cls = get_class_for_tenant(class_id, tenant_id)
    if not cls:
        return {"success": False, "error": "Class not found"}

    d = on_date or date.today()
    # ISO 1=Mon … 7=Sun (matches _working_weekdays / TimetableEntry.day_of_week)
    iso_day = d.isoweekday()

    if iso_day not in _working_weekdays(tenant_id):
        return {
            "success": True,
            "timetable_version": None,
            "date": d.isoformat(),
            "day_of_week": iso_day,
            "items": [],
            "bell_schedule": None,
            "message": "Not a working day for this school",
        }

    active = (
        TimetableVersion.query.filter_by(tenant_id=tenant_id, class_id=class_id)
        .filter(TimetableVersion.status == "active")
        .order_by(TimetableVersion.created_at.desc())
        .first()
    )
    if not active:
        return {
            "success": True,
            "timetable_version": None,
            "date": d.isoformat(),
            "day_of_week": iso_day,
            "items": [],
            "bell_schedule": None,
            "message": "No active timetable for this class yet",
        }

    bell_map = _bell_period_map(tenant_id, active.bell_schedule_id)
    rows = (
        TimetableEntry.query.filter_by(
            tenant_id=tenant_id, timetable_version_id=active.id, day_of_week=iso_day
        )
        .order_by(TimetableEntry.period_number)
        .all()
    )
    base_items = [
        _serialize_entry(r, bell_map, tenant_id=tenant_id, editable=False)
        for r in rows
    ]
    # Overlay availability / leave.  Each base item already contains
    # teacher_id and period_number, which overlay_daily_schedule reads.
    enriched = overlay_daily_schedule(tenant_id, base_items, d)

    return {
        "success": True,
        "timetable_version": _serialize_version(active),
        "date": d.isoformat(),
        "day_of_week": iso_day,
        "items": enriched,
        "bell_schedule": _bell_schedule_envelope(tenant_id, active.bell_schedule_id),
    }
