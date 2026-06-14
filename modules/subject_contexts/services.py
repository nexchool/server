"""Subject-context services: CRUD, bulk-upsert, preview, apply.

The application's source of truth for what subjects a (programme, grade)
offers. Replaces subject_template_items.

Apply semantics (idempotent, non-destructive):
  - For each class matching (programme, grade), and each context for that
    grade, insert a class_subjects row if (class_id, subject_id) does not
    already exist (active, not soft-deleted). If it exists, SKIP — never
    overwrite weekly_periods or per-class overrides set by the user.
  - Returns counts: {created_count, skipped_count, classes_matched}.
"""

from __future__ import annotations
from shared.safe_error import safe_error

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.exc import IntegrityError

from core.database import db
from modules.academic_programmes.models import AcademicProgramme
from modules.classes.models import Class, ClassSubject
from modules.grades.models import Grade
from modules.mediums.models import Medium
from modules.subjects.models import Subject

from .models import CONTEXT_ROLES, CONTEXT_TYPES, SubjectContext


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_programme_grade(
    tenant_id: str, programme_id: str, grade_id: str
) -> Optional[str]:
    if not (
        AcademicProgramme.query.filter_by(id=programme_id, tenant_id=tenant_id)
        .filter(AcademicProgramme.deleted_at.is_(None))
        .first()
    ):
        return "programme_id not found for this tenant"
    if not (
        Grade.query.filter_by(id=grade_id, tenant_id=tenant_id)
        .filter(Grade.deleted_at.is_(None))
        .first()
    ):
        return "grade_id not found for this tenant"
    return None


def _validate_subject(tenant_id: str, subject_id: str) -> Optional[str]:
    s = Subject.query.filter(
        Subject.id == subject_id,
        Subject.tenant_id == tenant_id,
        Subject.deleted_at.is_(None),
        Subject.is_active.is_(True),
    ).first()
    return None if s else f"subject_id {subject_id} not found or inactive"


def _validate_medium(tenant_id: str, medium_id: Optional[str]) -> Optional[str]:
    if not medium_id:
        return None
    m = Medium.query.filter(
        Medium.id == medium_id,
        Medium.tenant_id == tenant_id,
        Medium.deleted_at.is_(None),
    ).first()
    return None if m else f"medium_id {medium_id} not found"


def _coerce_periods(value: Any) -> Tuple[Optional[int], Optional[str]]:
    if value is None:
        return 5, None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None, "default_weekly_periods must be an integer"
    if n < 1 or n > 40:
        return None, "default_weekly_periods must be between 1 and 40"
    return n, None


def _validate_type(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if value not in CONTEXT_TYPES:
        return f"type must be one of {CONTEXT_TYPES}"
    return None


def _validate_role(value: Optional[str]) -> Optional[str]:
    if value is None or value == "":
        return None
    if value not in CONTEXT_ROLES:
        return f"role must be one of {CONTEXT_ROLES}"
    return None


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def list_contexts(
    tenant_id: str,
    programme_id: Optional[str] = None,
    grade_id: Optional[str] = None,
    include_inactive: bool = False,
) -> List[Dict[str, Any]]:
    q = SubjectContext.query.filter(
        SubjectContext.tenant_id == tenant_id,
        SubjectContext.deleted_at.is_(None),
    )
    if programme_id:
        q = q.filter(SubjectContext.programme_id == programme_id)
    if grade_id:
        q = q.filter(SubjectContext.grade_id == grade_id)
    if not include_inactive:
        q = q.filter(SubjectContext.is_active.is_(True))
    rows = q.order_by(
        SubjectContext.sort_order.asc(), SubjectContext.created_at.asc()
    ).all()
    return [r.to_dict() for r in rows]


def get_context(context_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
    c = SubjectContext.query.filter_by(id=context_id, tenant_id=tenant_id).first()
    if not c or c.deleted_at is not None:
        return None
    return c.to_dict()


# ---------------------------------------------------------------------------
# Write — single
# ---------------------------------------------------------------------------


def _build_context(
    tenant_id: str,
    payload: Dict[str, Any],
    actor_user_id: Optional[str],
) -> Tuple[Optional[SubjectContext], Optional[str]]:
    programme_id = payload.get("programme_id")
    grade_id = payload.get("grade_id")
    subject_id = payload.get("subject_id")

    if not (programme_id and grade_id and subject_id):
        return None, "programme_id, grade_id and subject_id are required"

    err = _validate_programme_grade(tenant_id, programme_id, grade_id)
    if err:
        return None, err
    err = _validate_subject(tenant_id, subject_id)
    if err:
        return None, err

    medium_id = payload.get("medium_id") or None
    err = _validate_medium(tenant_id, medium_id)
    if err:
        return None, err

    role = payload.get("role") or None
    err = _validate_role(role)
    if err:
        return None, err

    type_ = payload.get("type") or "mandatory"
    err = _validate_type(type_)
    if err:
        return None, err

    periods, err = _coerce_periods(payload.get("default_weekly_periods"))
    if err:
        return None, err

    variant_of = payload.get("variant_of_context_id") or None
    if variant_of:
        ref = SubjectContext.query.filter_by(
            id=variant_of, tenant_id=tenant_id
        ).first()
        if not ref or ref.deleted_at is not None:
            return None, "variant_of_context_id not found"

    sort_order = payload.get("sort_order")
    try:
        sort_order = int(sort_order) if sort_order is not None else 0
    except (TypeError, ValueError):
        return None, "sort_order must be an integer"

    return (
        SubjectContext(
            tenant_id=tenant_id,
            programme_id=programme_id,
            grade_id=grade_id,
            subject_id=subject_id,
            display_name=(payload.get("display_name") or "").strip() or None,
            short_code=(payload.get("short_code") or "").strip() or None,
            type=type_,
            role=role,
            medium_id=medium_id,
            variant_of_context_id=variant_of,
            elective_group_key=(payload.get("elective_group_key") or "").strip()
            or None,
            default_weekly_periods=periods or 5,
            sort_order=sort_order,
            is_active=bool(payload.get("is_active", True)),
            created_by=actor_user_id,
            updated_by=actor_user_id,
        ),
        None,
    )


def create_context(
    tenant_id: str,
    payload: Dict[str, Any],
    actor_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}
    ctx, err = _build_context(tenant_id, payload, actor_user_id)
    if err:
        return {"success": False, "error": err}
    db.session.add(ctx)
    try:
        db.session.commit()
        return {"success": True, "context": ctx.to_dict()}
    except IntegrityError as e:
        db.session.rollback()
        raw = str(getattr(e, "orig", None) or e)
        if "uq_subject_contexts_offering_active" in raw:
            return {
                "success": False,
                "error": "This subject is already assigned to that grade with the same medium and role",
            }
        return {"success": False, "error": safe_error(e)}


def update_context(
    context_id: str,
    tenant_id: str,
    payload: Dict[str, Any],
    actor_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    c = SubjectContext.query.filter_by(id=context_id, tenant_id=tenant_id).first()
    if not c or c.deleted_at is not None:
        return {"success": False, "error": "Subject context not found"}

    if "display_name" in payload:
        c.display_name = (payload.get("display_name") or "").strip() or None
    if "short_code" in payload:
        c.short_code = (payload.get("short_code") or "").strip() or None
    if "type" in payload:
        err = _validate_type(payload["type"])
        if err:
            return {"success": False, "error": err}
        c.type = payload["type"]
    if "role" in payload:
        role = payload.get("role") or None
        err = _validate_role(role)
        if err:
            return {"success": False, "error": err}
        c.role = role
    if "medium_id" in payload:
        medium_id = payload.get("medium_id") or None
        err = _validate_medium(tenant_id, medium_id)
        if err:
            return {"success": False, "error": err}
        c.medium_id = medium_id
    if "variant_of_context_id" in payload:
        v = payload.get("variant_of_context_id") or None
        if v == c.id:
            return {"success": False, "error": "variant_of_context_id must differ from id"}
        if v:
            ref = SubjectContext.query.filter_by(id=v, tenant_id=tenant_id).first()
            if not ref or ref.deleted_at is not None:
                return {"success": False, "error": "variant_of_context_id not found"}
        c.variant_of_context_id = v
    if "elective_group_key" in payload:
        c.elective_group_key = (
            (payload.get("elective_group_key") or "").strip() or None
        )
    if "default_weekly_periods" in payload:
        periods, err = _coerce_periods(payload["default_weekly_periods"])
        if err:
            return {"success": False, "error": err}
        c.default_weekly_periods = periods
    if "sort_order" in payload:
        try:
            c.sort_order = int(payload["sort_order"])
        except (TypeError, ValueError):
            return {"success": False, "error": "sort_order must be an integer"}
    if "is_active" in payload:
        c.is_active = bool(payload["is_active"])

    c.updated_by = actor_user_id
    c.updated_at = datetime.now(timezone.utc)

    try:
        db.session.commit()
        return {"success": True, "context": c.to_dict()}
    except IntegrityError as e:
        db.session.rollback()
        raw = str(getattr(e, "orig", None) or e)
        if "uq_subject_contexts_offering_active" in raw:
            return {
                "success": False,
                "error": "Another offering with this subject, medium and role already exists",
            }
        return {"success": False, "error": safe_error(e)}


def delete_context(context_id: str, tenant_id: str) -> Dict[str, Any]:
    c = SubjectContext.query.filter_by(id=context_id, tenant_id=tenant_id).first()
    if not c or c.deleted_at is not None:
        return {"success": False, "error": "Subject context not found"}
    c.deleted_at = datetime.now(timezone.utc)
    c.is_active = False
    db.session.commit()
    try:
        from modules.school_setup.services import recompute_setup_complete
        recompute_setup_complete(tenant_id)
    except Exception:
        pass
    return {"success": True}


# ---------------------------------------------------------------------------
# Bulk upsert: replace the offering set for a (programme, grade)
# ---------------------------------------------------------------------------


def _context_signature(payload: Dict[str, Any]) -> Tuple:
    """The natural key used by the unique index, for client-side conflict checks."""
    return (
        payload.get("subject_id"),
        payload.get("medium_id") or "",
        payload.get("role") or "",
    )


def bulk_upsert_contexts(
    tenant_id: str,
    programme_id: str,
    grade_id: str,
    contexts: List[Dict[str, Any]],
    *,
    delete_missing: bool = True,
    actor_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Replace the set of contexts for one (programme, grade) atomically.

    If `delete_missing` is True, contexts not in the payload (matched by id,
    or by the natural signature) are soft-deleted. Existing rows are
    updated in place (their ids preserved so class_subjects.subject_context_id
    stays valid).
    """
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}
    err = _validate_programme_grade(tenant_id, programme_id, grade_id)
    if err:
        return {"success": False, "error": err}
    if not isinstance(contexts, list):
        return {"success": False, "error": "contexts must be a list"}

    # 1. Validate each payload item up front; abort on first error.
    seen_signatures: Set[Tuple] = set()
    for idx, item in enumerate(contexts):
        if not isinstance(item, dict):
            return {"success": False, "error": f"contexts[{idx}] must be an object"}
        item_payload = dict(item)
        item_payload["programme_id"] = programme_id
        item_payload["grade_id"] = grade_id
        sig = _context_signature(item_payload)
        if not sig[0]:
            return {"success": False, "error": f"contexts[{idx}].subject_id is required"}
        if sig in seen_signatures:
            return {
                "success": False,
                "error": (
                    f"contexts[{idx}] duplicates an earlier entry "
                    "(same subject + medium + role)"
                ),
            }
        seen_signatures.add(sig)
        # Validate referenced foreign keys / enums.
        for validator in (
            lambda: _validate_subject(tenant_id, sig[0]),
            lambda: _validate_medium(tenant_id, item_payload.get("medium_id")),
            lambda: _validate_role(item_payload.get("role")),
            lambda: _validate_type(item_payload.get("type")),
        ):
            err = validator()
            if err:
                return {"success": False, "error": f"contexts[{idx}]: {err}"}
        _, periods_err = _coerce_periods(item_payload.get("default_weekly_periods"))
        if periods_err:
            return {"success": False, "error": f"contexts[{idx}]: {periods_err}"}

    # 2. Load current contexts for this (programme, grade).
    current = (
        SubjectContext.query.filter(
            SubjectContext.tenant_id == tenant_id,
            SubjectContext.programme_id == programme_id,
            SubjectContext.grade_id == grade_id,
            SubjectContext.deleted_at.is_(None),
        )
        .all()
    )
    by_id = {c.id: c for c in current}
    by_sig = {
        (c.subject_id, c.medium_id or "", c.role or ""): c for c in current
    }

    now = datetime.now(timezone.utc)
    written: List[SubjectContext] = []
    matched_ids: Set[str] = set()

    try:
        for item in contexts:
            payload = dict(item)
            payload["programme_id"] = programme_id
            payload["grade_id"] = grade_id

            target: Optional[SubjectContext] = None
            if payload.get("id") and payload["id"] in by_id:
                target = by_id[payload["id"]]
            else:
                sig = _context_signature(payload)
                target = by_sig.get(sig)

            if target is None:
                ctx, err = _build_context(tenant_id, payload, actor_user_id)
                if err:
                    db.session.rollback()
                    return {"success": False, "error": err}
                db.session.add(ctx)
                written.append(ctx)
            else:
                # Update existing in place.
                _apply_payload_to_context(target, payload, actor_user_id, now)
                matched_ids.add(target.id)
                written.append(target)

        if delete_missing:
            for c in current:
                if c.id not in matched_ids and c not in written:
                    c.deleted_at = now
                    c.is_active = False
                    c.updated_by = actor_user_id

        db.session.commit()
    except IntegrityError as e:
        db.session.rollback()
        raw = str(getattr(e, "orig", None) or e)
        if "uq_subject_contexts_offering_active" in raw:
            return {
                "success": False,
                "error": "Two entries collide on (subject, medium, role).",
            }
        return {"success": False, "error": safe_error(e)}

    return {
        "success": True,
        "contexts": [c.to_dict() for c in written],
    }


def _apply_payload_to_context(
    ctx: SubjectContext,
    payload: Dict[str, Any],
    actor_user_id: Optional[str],
    now: datetime,
) -> None:
    if "subject_id" in payload:
        ctx.subject_id = payload["subject_id"]
    if "display_name" in payload:
        ctx.display_name = (payload.get("display_name") or "").strip() or None
    if "short_code" in payload:
        ctx.short_code = (payload.get("short_code") or "").strip() or None
    if "type" in payload:
        ctx.type = payload.get("type") or "mandatory"
    if "role" in payload:
        ctx.role = payload.get("role") or None
    if "medium_id" in payload:
        ctx.medium_id = payload.get("medium_id") or None
    if "variant_of_context_id" in payload:
        v = payload.get("variant_of_context_id") or None
        ctx.variant_of_context_id = v if v != ctx.id else None
    if "elective_group_key" in payload:
        ctx.elective_group_key = (
            (payload.get("elective_group_key") or "").strip() or None
        )
    if "default_weekly_periods" in payload:
        n, _ = _coerce_periods(payload["default_weekly_periods"])
        if n is not None:
            ctx.default_weekly_periods = n
    if "sort_order" in payload:
        try:
            ctx.sort_order = int(payload["sort_order"])
        except (TypeError, ValueError):
            pass
    if "is_active" in payload:
        ctx.is_active = bool(payload["is_active"])
    ctx.updated_by = actor_user_id
    ctx.updated_at = now


# ---------------------------------------------------------------------------
# Preview & apply
# ---------------------------------------------------------------------------


def preview_for_grade(
    tenant_id: str, programme_id: str, grade_id: str
) -> Dict[str, Any]:
    err = _validate_programme_grade(tenant_id, programme_id, grade_id)
    if err:
        return {"success": False, "error": err}
    classes_count = Class.query.filter(
        Class.tenant_id == tenant_id,
        Class.programme_id == programme_id,
        Class.grade_id == grade_id,
    ).count()
    contexts = list_contexts(tenant_id, programme_id, grade_id)
    return {
        "success": True,
        "class_count": classes_count,
        "subject_count": len(contexts),
        "contexts": contexts,
    }


def apply_for_grade(
    tenant_id: str, programme_id: str, grade_id: str
) -> Dict[str, Any]:
    """Create class_subjects rows for every (class, context) pair that doesn't
    already have one. Skip duplicates (active, not soft-deleted)."""
    err = _validate_programme_grade(tenant_id, programme_id, grade_id)
    if err:
        return {"success": False, "error": err}

    contexts = (
        SubjectContext.query.filter(
            SubjectContext.tenant_id == tenant_id,
            SubjectContext.programme_id == programme_id,
            SubjectContext.grade_id == grade_id,
            SubjectContext.deleted_at.is_(None),
            SubjectContext.is_active.is_(True),
        )
        .all()
    )
    if not contexts:
        return {
            "success": True,
            "created_count": 0,
            "skipped_count": 0,
            "classes_matched": 0,
            "message": "No subject contexts defined for this grade.",
        }

    classes = Class.query.filter(
        Class.tenant_id == tenant_id,
        Class.programme_id == programme_id,
        Class.grade_id == grade_id,
    ).all()
    class_ids = [c.id for c in classes]
    if not class_ids:
        return {
            "success": True,
            "created_count": 0,
            "skipped_count": 0,
            "classes_matched": 0,
            "message": "No classes match this programme and grade yet.",
        }

    subject_ids = [c.subject_id for c in contexts]

    existing_pairs: Set[Tuple[str, str]] = set()
    rows = ClassSubject.query.filter(
        ClassSubject.tenant_id == tenant_id,
        ClassSubject.class_id.in_(class_ids),
        ClassSubject.subject_id.in_(subject_ids),
        ClassSubject.deleted_at.is_(None),
        ClassSubject.status == "active",
    ).all()
    for cs in rows:
        existing_pairs.add((cs.class_id, cs.subject_id))

    now = datetime.now(timezone.utc)
    mappings: List[Dict[str, Any]] = []
    skipped = 0
    for cid in class_ids:
        for ctx in contexts:
            if (cid, ctx.subject_id) in existing_pairs:
                skipped += 1
                continue
            mappings.append(
                {
                    "id": str(uuid.uuid4()),
                    "tenant_id": tenant_id,
                    "class_id": cid,
                    "subject_id": ctx.subject_id,
                    "subject_context_id": ctx.id,
                    "weekly_periods": ctx.default_weekly_periods,
                    "is_mandatory": ctx.type == "mandatory",
                    "is_elective_bucket": ctx.type == "elective"
                    and bool(ctx.elective_group_key),
                    "sort_order": ctx.sort_order,
                    "academic_term_id": None,
                    "status": "active",
                    "created_at": now,
                    "updated_at": now,
                    "deleted_at": None,
                }
            )

    try:
        if mappings:
            db.session.bulk_insert_mappings(ClassSubject, mappings)
        db.session.commit()
    except IntegrityError as e:
        db.session.rollback()
        return {
            "success": False,
            "error": safe_error(e),
        }
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": safe_error(e)}

    try:
        from modules.school_setup.services import recompute_setup_complete
        recompute_setup_complete(tenant_id)
    except Exception:
        pass

    return {
        "success": True,
        "created_count": len(mappings),
        "skipped_count": skipped,
        "classes_matched": len(class_ids),
    }
