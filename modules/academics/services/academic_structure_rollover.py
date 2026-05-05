"""
Academic structure rollover: copy class_subjects, class_subject_teachers, and
class_teacher_assignments from old classes to new classes using a class mapping.

Input: class_mapping = { old_class_id: new_class_id }

Only active rows are copied; inactive teachers are skipped; duplicates on the
target are skipped. The whole batch runs inside a single DB transaction.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from core.database import db
from core.tenant import get_tenant_id
from modules.academics.backbone.models import (
    ClassSubjectTeacher,
    ClassTeacherAssignment,
)
from modules.classes.models import Class, ClassSubject
from modules.teachers.models import Teacher

logger = logging.getLogger(__name__)


def _normalize_mapping(raw: Any) -> Dict[str, str]:
    if not isinstance(raw, dict):
        raise ValueError("class_mapping must be an object")
    out: Dict[str, str] = {}
    for k, v in raw.items():
        key = str(k).strip() if k is not None else ""
        val = str(v).strip() if v is not None else ""
        if not key or not val:
            raise ValueError("class_mapping keys and values must be non-empty class IDs")
        out[key] = val
    return out


def _validate_classes(
    tenant_id: str, mapping: Dict[str, str]
) -> Tuple[Dict[str, Class], Dict[str, Class], Optional[str]]:
    old_ids = list(mapping.keys())
    new_ids = list({v for v in mapping.values()})

    old_rows = (
        Class.query.filter(Class.tenant_id == tenant_id, Class.id.in_(old_ids)).all()
        if old_ids
        else []
    )
    new_rows = (
        Class.query.filter(Class.tenant_id == tenant_id, Class.id.in_(new_ids)).all()
        if new_ids
        else []
    )

    old_map = {c.id: c for c in old_rows}
    new_map = {c.id: c for c in new_rows}

    missing_old = [cid for cid in old_ids if cid not in old_map]
    if missing_old:
        return old_map, new_map, f"Unknown source class_id(s): {', '.join(missing_old)}"

    missing_new = [cid for cid in new_ids if cid not in new_map]
    if missing_new:
        return old_map, new_map, f"Unknown target class_id(s): {', '.join(missing_new)}"

    return old_map, new_map, None


def _active_teacher_ids(tenant_id: str, teacher_ids: List[str]) -> set:
    if not teacher_ids:
        return set()
    rows = Teacher.query.filter(
        Teacher.tenant_id == tenant_id,
        Teacher.id.in_(list(set(teacher_ids))),
        Teacher.status == "active",
    ).all()
    return {t.id for t in rows}


def _copy_class_subjects(
    tenant_id: str, mapping: Dict[str, str]
) -> Tuple[Dict[str, str], int, int]:
    """
    Returns (old_cs_id -> new_cs_id, created_count, skipped_count).
    """
    old_class_ids = list(mapping.keys())
    new_class_ids = list({v for v in mapping.values()})

    source_rows: List[ClassSubject] = (
        ClassSubject.query.filter(
            ClassSubject.tenant_id == tenant_id,
            ClassSubject.class_id.in_(old_class_ids),
            ClassSubject.status == "active",
            ClassSubject.deleted_at.is_(None),
        ).all()
    )

    # Existing active offerings on target classes keyed by (class_id, subject_id).
    existing_rows: List[ClassSubject] = (
        ClassSubject.query.filter(
            ClassSubject.tenant_id == tenant_id,
            ClassSubject.class_id.in_(new_class_ids),
            ClassSubject.status == "active",
            ClassSubject.deleted_at.is_(None),
        ).all()
        if new_class_ids
        else []
    )
    existing_by_key: Dict[Tuple[str, str], str] = {
        (r.class_id, r.subject_id): r.id for r in existing_rows
    }

    id_map: Dict[str, str] = {}
    created = 0
    skipped = 0

    # Guard against duplicates introduced within this batch.
    batch_seen: Dict[Tuple[str, str], str] = {}

    for src in source_rows:
        new_class_id = mapping.get(src.class_id)
        if not new_class_id:
            skipped += 1
            continue

        key = (new_class_id, src.subject_id)
        if key in existing_by_key:
            id_map[src.id] = existing_by_key[key]
            skipped += 1
            continue
        if key in batch_seen:
            id_map[src.id] = batch_seen[key]
            skipped += 1
            continue

        new_id = str(uuid.uuid4())
        new_row = ClassSubject(
            id=new_id,
            tenant_id=tenant_id,
            class_id=new_class_id,
            subject_id=src.subject_id,
            weekly_periods=src.weekly_periods,
            is_mandatory=src.is_mandatory,
            is_elective_bucket=src.is_elective_bucket,
            sort_order=src.sort_order,
            academic_term_id=None,
            status="active",
        )
        db.session.add(new_row)

        id_map[src.id] = new_id
        batch_seen[key] = new_id
        created += 1

    # Flush so subsequent inserts can reference new class_subject ids safely.
    db.session.flush()
    return id_map, created, skipped


def _copy_class_subject_teachers(
    tenant_id: str,
    cs_id_map: Dict[str, str],
    user_id: Optional[str],
) -> Tuple[int, int]:
    if not cs_id_map:
        return 0, 0

    source_rows: List[ClassSubjectTeacher] = (
        ClassSubjectTeacher.query.filter(
            ClassSubjectTeacher.tenant_id == tenant_id,
            ClassSubjectTeacher.class_subject_id.in_(list(cs_id_map.keys())),
            ClassSubjectTeacher.is_active.is_(True),
            ClassSubjectTeacher.deleted_at.is_(None),
        ).all()
    )
    if not source_rows:
        return 0, 0

    active_teacher_ids = _active_teacher_ids(
        tenant_id, [r.teacher_id for r in source_rows]
    )

    new_cs_ids = list({v for v in cs_id_map.values()})
    existing_rows: List[ClassSubjectTeacher] = (
        ClassSubjectTeacher.query.filter(
            ClassSubjectTeacher.tenant_id == tenant_id,
            ClassSubjectTeacher.class_subject_id.in_(new_cs_ids),
            ClassSubjectTeacher.is_active.is_(True),
            ClassSubjectTeacher.deleted_at.is_(None),
        ).all()
        if new_cs_ids
        else []
    )
    existing_keys: set = {
        (r.class_subject_id, r.teacher_id, r.role) for r in existing_rows
    }
    existing_primary: set = {
        r.class_subject_id for r in existing_rows if r.role == "primary"
    }

    created = 0
    skipped = 0
    batch_seen: set = set()
    batch_primary: set = set()

    for src in source_rows:
        if src.teacher_id not in active_teacher_ids:
            skipped += 1
            continue

        new_cs_id = cs_id_map.get(src.class_subject_id)
        if not new_cs_id:
            skipped += 1
            continue

        key = (new_cs_id, src.teacher_id, src.role)
        if key in existing_keys or key in batch_seen:
            skipped += 1
            continue

        # Partial unique index enforces one active primary per class_subject.
        if src.role == "primary" and (
            new_cs_id in existing_primary or new_cs_id in batch_primary
        ):
            skipped += 1
            continue

        db.session.add(
            ClassSubjectTeacher(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                class_subject_id=new_cs_id,
                teacher_id=src.teacher_id,
                role=src.role,
                is_active=True,
                created_by=user_id,
                updated_by=user_id,
            )
        )
        batch_seen.add(key)
        if src.role == "primary":
            batch_primary.add(new_cs_id)
        created += 1

    return created, skipped


def _copy_class_teacher_assignments(
    tenant_id: str,
    mapping: Dict[str, str],
    user_id: Optional[str],
) -> Tuple[int, int]:
    old_class_ids = list(mapping.keys())
    if not old_class_ids:
        return 0, 0

    source_rows: List[ClassTeacherAssignment] = (
        ClassTeacherAssignment.query.filter(
            ClassTeacherAssignment.tenant_id == tenant_id,
            ClassTeacherAssignment.class_id.in_(old_class_ids),
            ClassTeacherAssignment.is_active.is_(True),
            ClassTeacherAssignment.deleted_at.is_(None),
        ).all()
    )
    if not source_rows:
        return 0, 0

    active_teacher_ids = _active_teacher_ids(
        tenant_id, [r.teacher_id for r in source_rows]
    )

    new_class_ids = list({v for v in mapping.values()})
    existing_rows: List[ClassTeacherAssignment] = (
        ClassTeacherAssignment.query.filter(
            ClassTeacherAssignment.tenant_id == tenant_id,
            ClassTeacherAssignment.class_id.in_(new_class_ids),
            ClassTeacherAssignment.is_active.is_(True),
            ClassTeacherAssignment.deleted_at.is_(None),
        ).all()
        if new_class_ids
        else []
    )
    existing_keys: set = {(r.class_id, r.teacher_id, r.role) for r in existing_rows}
    existing_primary: set = {r.class_id for r in existing_rows if r.role == "primary"}

    created = 0
    skipped = 0
    batch_seen: set = set()
    batch_primary: set = set()

    for src in source_rows:
        if src.teacher_id not in active_teacher_ids:
            skipped += 1
            continue

        new_class_id = mapping.get(src.class_id)
        if not new_class_id:
            skipped += 1
            continue

        key = (new_class_id, src.teacher_id, src.role)
        if key in existing_keys or key in batch_seen:
            skipped += 1
            continue

        if src.role == "primary" and (
            new_class_id in existing_primary or new_class_id in batch_primary
        ):
            skipped += 1
            continue

        db.session.add(
            ClassTeacherAssignment(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                class_id=new_class_id,
                teacher_id=src.teacher_id,
                role=src.role,
                allow_attendance_marking=src.allow_attendance_marking,
                is_active=True,
                created_by=user_id,
                updated_by=user_id,
            )
        )
        batch_seen.add(key)
        if src.role == "primary":
            batch_primary.add(new_class_id)
        created += 1

    return created, skipped


def rollover_academic_structure(
    class_mapping: Any,
    *,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Copy academic structure for the classes described by class_mapping.

    Returns:
        {
            "success": True,
            "class_subjects_created": int,
            "subject_teachers_created": int,
            "class_teachers_created": int,
            "skipped": {
                "class_subjects": int,
                "subject_teachers": int,
                "class_teachers": int,
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
            "class_subjects_created": 0,
            "subject_teachers_created": 0,
            "class_teachers_created": 0,
            "skipped": {
                "class_subjects": 0,
                "subject_teachers": 0,
                "class_teachers": 0,
            },
        }

    self_mapped = [k for k, v in mapping.items() if k == v]
    if self_mapped:
        return {
            "success": False,
            "error": f"class_mapping cannot map a class to itself: {', '.join(self_mapped)}",
        }

    _, _, err = _validate_classes(tenant_id, mapping)
    if err:
        return {"success": False, "error": err}

    try:
        cs_id_map, cs_created, cs_skipped = _copy_class_subjects(tenant_id, mapping)
        st_created, st_skipped = _copy_class_subject_teachers(
            tenant_id, cs_id_map, user_id
        )
        ct_created, ct_skipped = _copy_class_teacher_assignments(
            tenant_id, mapping, user_id
        )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.exception("academic structure rollover failed: %s", e)
        return {"success": False, "error": str(e)}

    return {
        "success": True,
        "class_subjects_created": cs_created,
        "subject_teachers_created": st_created,
        "class_teachers_created": ct_created,
        "skipped": {
            "class_subjects": cs_skipped,
            "subject_teachers": st_skipped,
            "class_teachers": ct_skipped,
        },
    }
