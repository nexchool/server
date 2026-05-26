"""
Timetable rollover: clone active TimetableVersion + TimetableEntry rows from
old classes to mapped new classes.

Input: class_mapping = { old_class_id: new_class_id }

For each old class that has an active TimetableVersion:
  - if the target class already has any non-deleted TimetableVersion: skip (do
    not overwrite admin-managed work);
  - otherwise create a new draft TimetableVersion on the target class and copy
    every TimetableEntry, remapping `class_subject_id` from the old class's
    ClassSubject (subject_id) to the new class's matching ClassSubject.

Entries that cannot be remapped (no matching subject offering on the target
class) are skipped and counted. The whole batch runs in one transaction.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from core.database import db
from core.tenant import get_tenant_id
from modules.academics.backbone.models import TimetableEntry, TimetableVersion
from modules.classes.models import Class, ClassSubject

logger = logging.getLogger(__name__)

# Sentinel used by the promotion wizard to mark graduating cohorts. The
# rollover services here only care about class→class moves, so any such
# entry is filtered out before validation runs.
_GRADUATED = "GRADUATED"


def _normalize_mapping(raw: Any) -> Dict[str, str]:
    if not isinstance(raw, dict):
        raise ValueError("class_mapping must be an object")
    out: Dict[str, str] = {}
    for k, v in raw.items():
        key = str(k).strip() if k is not None else ""
        val = str(v).strip() if v is not None else ""
        if not key or not val or key == val:
            continue
        if val == _GRADUATED:
            continue
        out[key] = val
    return out


def _validate_classes(
    tenant_id: str, mapping: Dict[str, str]
) -> Optional[str]:
    old_ids = list(mapping.keys())
    new_ids = list({v for v in mapping.values()})
    if not old_ids:
        return None

    found_old = {
        c.id
        for c in Class.query.filter(
            Class.tenant_id == tenant_id, Class.id.in_(old_ids)
        ).all()
    }
    missing_old = [cid for cid in old_ids if cid not in found_old]
    if missing_old:
        return f"Unknown source class_id(s): {', '.join(missing_old)}"

    found_new = {
        c.id
        for c in Class.query.filter(
            Class.tenant_id == tenant_id, Class.id.in_(new_ids)
        ).all()
    }
    missing_new = [cid for cid in new_ids if cid not in found_new]
    if missing_new:
        return f"Unknown target class_id(s): {', '.join(missing_new)}"
    return None


def _build_class_subject_lookup(
    tenant_id: str, class_ids: List[str]
) -> Dict[Tuple[str, str], str]:
    """Returns { (class_id, subject_id): class_subject_id } for active offerings."""
    if not class_ids:
        return {}
    rows = ClassSubject.query.filter(
        ClassSubject.tenant_id == tenant_id,
        ClassSubject.class_id.in_(class_ids),
        ClassSubject.status == "active",
        ClassSubject.deleted_at.is_(None),
    ).all()
    return {(r.class_id, r.subject_id): r.id for r in rows}


def rollover_timetables(
    class_mapping: Any,
    *,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Returns:
        {
            "success": True,
            "versions_created": int,
            "entries_created": int,
            "skipped": {
                "classes_no_source": int,
                "classes_target_has_version": int,
                "entries_no_class_subject": int,
            },
        }
    """
    tenant_id = get_tenant_id()
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}

    try:
        mapping = _normalize_mapping(class_mapping)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    if not mapping:
        return {
            "success": True,
            "versions_created": 0,
            "entries_created": 0,
            "skipped": {
                "classes_no_source": 0,
                "classes_target_has_version": 0,
                "entries_no_class_subject": 0,
            },
        }

    err = _validate_classes(tenant_id, mapping)
    if err:
        return {"success": False, "error": err}

    old_class_ids = list(mapping.keys())
    new_class_ids = list({v for v in mapping.values()})

    source_versions: List[TimetableVersion] = (
        TimetableVersion.query.filter(
            TimetableVersion.tenant_id == tenant_id,
            TimetableVersion.class_id.in_(old_class_ids),
            TimetableVersion.status == "active",
        ).all()
    )
    by_source_class: Dict[str, TimetableVersion] = {
        v.class_id: v for v in source_versions
    }

    existing_target_versions = (
        TimetableVersion.query.filter(
            TimetableVersion.tenant_id == tenant_id,
            TimetableVersion.class_id.in_(new_class_ids),
        ).all()
        if new_class_ids
        else []
    )
    target_classes_with_version = {v.class_id for v in existing_target_versions}

    # Build a (class_id, subject_id) → class_subject_id lookup for both sides so
    # we can remap entry.class_subject_id to the target year's offering.
    old_cs_lookup_by_id: Dict[str, ClassSubject] = {
        r.id: r
        for r in (
            ClassSubject.query.filter(
                ClassSubject.tenant_id == tenant_id,
                ClassSubject.class_id.in_(old_class_ids),
                ClassSubject.deleted_at.is_(None),
            ).all()
            if old_class_ids
            else []
        )
    }
    new_cs_lookup = _build_class_subject_lookup(tenant_id, new_class_ids)

    versions_created = 0
    entries_created = 0
    skipped_no_source = 0
    skipped_target_has_version = 0
    skipped_no_cs = 0

    try:
        for old_class_id, new_class_id in mapping.items():
            src_version = by_source_class.get(old_class_id)
            if not src_version:
                skipped_no_source += 1
                continue
            if new_class_id in target_classes_with_version:
                skipped_target_has_version += 1
                continue

            new_version_id = str(uuid.uuid4())
            new_version = TimetableVersion(
                id=new_version_id,
                tenant_id=tenant_id,
                class_id=new_class_id,
                bell_schedule_id=src_version.bell_schedule_id,
                label=src_version.label,
                status="draft",
                effective_from=None,
                effective_to=None,
                created_by=user_id,
            )
            db.session.add(new_version)
            target_classes_with_version.add(new_class_id)
            versions_created += 1

            entries: List[TimetableEntry] = (
                TimetableEntry.query.filter(
                    TimetableEntry.tenant_id == tenant_id,
                    TimetableEntry.timetable_version_id == src_version.id,
                ).all()
            )
            for entry in entries:
                src_cs = old_cs_lookup_by_id.get(entry.class_subject_id)
                if not src_cs:
                    skipped_no_cs += 1
                    continue
                new_cs_id = new_cs_lookup.get((new_class_id, src_cs.subject_id))
                if not new_cs_id:
                    skipped_no_cs += 1
                    continue
                db.session.add(
                    TimetableEntry(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        timetable_version_id=new_version_id,
                        class_subject_id=new_cs_id,
                        teacher_id=entry.teacher_id,
                        day_of_week=entry.day_of_week,
                        period_number=entry.period_number,
                        room=entry.room,
                        notes=entry.notes,
                        entry_status=entry.entry_status,
                    )
                )
                entries_created += 1

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.exception("timetable rollover failed: %s", e)
        return {"success": False, "error": str(e)}

    return {
        "success": True,
        "versions_created": versions_created,
        "entries_created": entries_created,
        "skipped": {
            "classes_no_source": skipped_no_source,
            "classes_target_has_version": skipped_target_has_version,
            "entries_no_class_subject": skipped_no_cs,
        },
    }
