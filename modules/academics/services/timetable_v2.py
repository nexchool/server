"""Timetable versions and entries (weekly recurring)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.exc import IntegrityError

from backend.core.database import db
from backend.modules.academics.backbone.models import ClassSubjectTeacher, TimetableEntry, TimetableVersion
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


def _serialize_entry(e: TimetableEntry, bell_labels: Optional[Dict[int, Dict[str, Any]]] = None) -> Dict[str, Any]:
    cs = e.class_subject
    subj = cs.subject_ref if cs else None
    t = e.teacher
    out = {
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
    }
    if bell_labels and e.period_number in bell_labels:
        out["period_label"] = bell_labels[e.period_number].get("label")
        out["starts_at"] = bell_labels[e.period_number].get("starts_at")
        out["ends_at"] = bell_labels[e.period_number].get("ends_at")
    return out


def list_versions(tenant_id: str, class_id: str) -> Dict[str, Any]:
    cls = get_class_for_tenant(class_id, tenant_id)
    if not cls:
        return {"success": False, "error": "Class not found"}
    rows = (
        TimetableVersion.query.filter_by(tenant_id=tenant_id, class_id=class_id)
        .order_by(TimetableVersion.created_at.desc())
        .all()
    )
    return {"success": True, "items": [_serialize_version(r) for r in rows]}


def create_version(tenant_id: str, class_id: str, data: Dict[str, Any], user_id: Optional[str]) -> Dict[str, Any]:
    cls = get_class_for_tenant(class_id, tenant_id)
    if not cls:
        return {"success": False, "error": "Class not found"}

    v = TimetableVersion(
        tenant_id=tenant_id,
        class_id=class_id,
        bell_schedule_id=data.get("bell_schedule_id"),
        label=data.get("label"),
        status=(data.get("status") or "draft").strip(),
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


def _pd(val: Any) -> Optional[date]:
    if val is None or val == "":
        return None
    if isinstance(val, date):
        return val
    return date.fromisoformat(str(val)[:10])


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


def list_entries_for_active_or_draft(
    tenant_id: str, class_id: str, version_id: Optional[str] = None
) -> Dict[str, Any]:
    cls = get_class_for_tenant(class_id, tenant_id)
    if not cls:
        return {"success": False, "error": "Class not found"}

    if version_id:
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
        return {"success": True, "timetable_version": None, "items": []}

    bell_map = _bell_period_map(tenant_id, v.bell_schedule_id)
    rows = (
        TimetableEntry.query.filter_by(tenant_id=tenant_id, timetable_version_id=v.id)
        .order_by(TimetableEntry.day_of_week, TimetableEntry.period_number)
        .all()
    )
    return {
        "success": True,
        "timetable_version": _serialize_version(v),
        "items": [_serialize_entry(r, bell_map) for r in rows],
    }


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


def _teacher_conflict_elsewhere(
    tenant_id: str,
    teacher_id: str,
    day_of_week: int,
    period_number: int,
    exclude_entry_id: Optional[str],
) -> bool:
    q = (
        db.session.query(TimetableEntry)
        .filter(
            TimetableEntry.tenant_id == tenant_id,
            TimetableEntry.teacher_id == teacher_id,
            TimetableEntry.day_of_week == day_of_week,
            TimetableEntry.period_number == period_number,
            TimetableEntry.entry_status == "active",
        )
        .join(TimetableVersion, TimetableEntry.timetable_version_id == TimetableVersion.id)
        .filter(TimetableVersion.status == "active")
    )
    if exclude_entry_id:
        q = q.filter(TimetableEntry.id != exclude_entry_id)
    return q.first() is not None


def create_entry(tenant_id: str, class_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    version_id = data.get("timetable_version_id")
    if not version_id:
        return {"success": False, "error": "timetable_version_id is required"}

    v = TimetableVersion.query.filter_by(
        id=version_id, tenant_id=tenant_id, class_id=class_id
    ).first()
    if not v:
        return {"success": False, "error": "Timetable version not found for this class"}

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

    if _teacher_conflict_elsewhere(tenant_id, teacher_id, day, period, None):
        return {"success": False, "error": "Teacher already has an active slot at this day/period"}

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
        return {"success": False, "error": "Duplicate day/period for this timetable version"}
    bell_map = _bell_period_map(tenant_id, v.bell_schedule_id)
    return {"success": True, "entry": _serialize_entry(e, bell_map)}


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

    if _teacher_conflict_elsewhere(tenant_id, teacher_id, day, period, e.id):
        return {"success": False, "error": "Teacher already has an active slot at this day/period"}

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
        return {"success": False, "error": "Duplicate day/period for this timetable version"}

    bell_map = _bell_period_map(tenant_id, v.bell_schedule_id)
    return {"success": True, "entry": _serialize_entry(e, bell_map)}


def delete_entry(tenant_id: str, class_id: str, entry_id: str) -> Dict[str, Any]:
    e = TimetableEntry.query.filter_by(id=entry_id, tenant_id=tenant_id).first()
    if not e:
        return {"success": False, "error": "Entry not found"}

    v = TimetableVersion.query.filter_by(
        id=e.timetable_version_id, tenant_id=tenant_id, class_id=class_id
    ).first()
    if not v:
        return {"success": False, "error": "Entry does not belong to this class"}

    db.session.delete(e)
    db.session.commit()
    return {"success": True, "message": "Entry deleted"}


def generate_draft(
    tenant_id: str, class_id: str, user_id: Optional[str]
) -> Dict[str, Any]:
    """
    Greedy placement: fill lesson periods only, Mon–Fri, using primary class_subject_teacher.
    """
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

    bell_id = default_bell
    gr = get_schedule(tenant_id, bell_id, include_periods=True) if bell_id else {"success": False}
    if not gr.get("success"):
        return {"success": False, "error": "Set a default bell schedule in academic settings first"}

    lesson_periods: List[int] = []
    for p in sorted(gr["bell_schedule"]["periods"], key=lambda x: (x["sort_order"], x["period_number"])):
        if p.get("period_kind") == "lesson":
            lesson_periods.append(int(p["period_number"]))

    if not lesson_periods:
        return {"success": False, "error": "Bell schedule has no lesson periods"}

    # Build work items: (class_subject_id, teacher_id) repeated weekly_periods times
    work: List[Tuple[str, str]] = []
    warnings: List[str] = []

    for cs in offerings:
        primary = (
            ClassSubjectTeacher.query.filter(
                ClassSubjectTeacher.class_subject_id == cs.id,
                ClassSubjectTeacher.tenant_id == tenant_id,
                ClassSubjectTeacher.role == "primary",
                ClassSubjectTeacher.is_active.is_(True),
                ClassSubjectTeacher.deleted_at.is_(None),
            ).first()
        )
        if not primary:
            warnings.append(f"No primary teacher for subject {cs.subject_ref.name if cs.subject_ref else cs.id}")
            continue
        for _ in range(int(cs.weekly_periods or 0)):
            work.append((cs.id, primary.teacher_id))

    if not work:
        return {"success": False, "error": "No schedulable subjects (assign primary teachers)", "warnings": warnings}

    v = TimetableVersion(
        tenant_id=tenant_id,
        class_id=class_id,
        bell_schedule_id=bell_id,
        label="Generated draft",
        status="draft",
        created_by=user_id,
    )
    db.session.add(v)
    db.session.flush()

    # Grid: day 1-5, period from lesson_periods
    slots: List[Tuple[int, int]] = [(d, p) for d in range(1, 6) for p in lesson_periods]
    used_teacher: Set[Tuple[str, int, int]] = set()
    used_class: Set[Tuple[int, int]] = set()
    slot_idx = 0
    placed = 0

    for cs_id, tid in work:
        placed_flag = False
        attempts = 0
        while attempts < len(slots) and not placed_flag:
            if slot_idx >= len(slots):
                slot_idx = 0
            day, period = slots[slot_idx]
            slot_idx += 1
            attempts += 1

            if (day, period) in used_class:
                continue
            key = (tid, day, period)
            if key in used_teacher:
                continue

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
            used_teacher.add(key)
            placed += 1
            placed_flag = True

        if not placed_flag:
            subj = ClassSubject.query.filter_by(id=cs_id, tenant_id=tenant_id).first()
            name = subj.subject_ref.name if subj and subj.subject_ref else cs_id
            warnings.append(f"Could not place all periods for {name} — grid full or teacher conflicts")

    try:
        db.session.commit()
    except IntegrityError as err:
        db.session.rollback()
        return {"success": False, "error": str(err), "warnings": warnings}

    return {
        "success": True,
        "timetable_version": _serialize_version(v),
        "entries_placed": placed,
        "total_required": len(work),
        "warnings": warnings,
    }
