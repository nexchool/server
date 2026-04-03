"""Class subject (offering) CRUD — class_subjects table."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import IntegrityError

from backend.core.database import db
from backend.modules.academics.backbone.models import AcademicTerm
from backend.modules.classes.models import ClassSubject
from backend.modules.subjects.models import Subject

from .common import get_class_for_tenant


def _serialize(cs: ClassSubject) -> Dict[str, Any]:
    subj = cs.subject_ref
    term = None
    if cs.academic_term_id:
        term = AcademicTerm.query.filter_by(id=cs.academic_term_id).first()
    return {
        "id": cs.id,
        "class_id": cs.class_id,
        "subject_id": cs.subject_id,
        "subject_name": subj.name if subj else None,
        "subject_code": subj.code if subj else None,
        "weekly_periods": cs.weekly_periods,
        "is_mandatory": cs.is_mandatory,
        "is_elective_bucket": cs.is_elective_bucket,
        "sort_order": cs.sort_order,
        "academic_term_id": cs.academic_term_id,
        "academic_term_name": term.name if term else None,
        "status": cs.status,
        "created_at": cs.created_at.isoformat() if cs.created_at else None,
        "updated_at": cs.updated_at.isoformat() if cs.updated_at else None,
    }


def list_for_class(tenant_id: str, class_id: str) -> Dict[str, Any]:
    cls = get_class_for_tenant(class_id, tenant_id)
    if not cls:
        return {"success": False, "error": "Class not found"}
    rows = (
        ClassSubject.query.filter_by(tenant_id=tenant_id, class_id=class_id)
        .filter(ClassSubject.deleted_at.is_(None))
        .order_by(ClassSubject.sort_order.nulls_last(), ClassSubject.id)
        .all()
    )
    return {"success": True, "items": [_serialize(r) for r in rows]}


def create_offering(tenant_id: str, class_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    cls = get_class_for_tenant(class_id, tenant_id)
    if not cls:
        return {"success": False, "error": "Class not found"}

    subject_id = data.get("subject_id")
    if not subject_id:
        return {"success": False, "error": "subject_id is required"}

    subj = Subject.query.filter_by(id=subject_id, tenant_id=tenant_id).filter(
        Subject.deleted_at.is_(None)
    ).first()
    if not subj:
        return {"success": False, "error": "Subject not found"}
    if not subj.is_active:
        return {"success": False, "error": "Subject is inactive"}

    try:
        weekly = int(data.get("weekly_periods"))
    except (TypeError, ValueError):
        return {"success": False, "error": "weekly_periods must be a positive integer"}
    if weekly <= 0:
        return {"success": False, "error": "weekly_periods must be greater than 0"}

    term_id = data.get("academic_term_id")
    if term_id:
        term = AcademicTerm.query.filter_by(id=term_id, tenant_id=tenant_id).first()
        if not term or term.academic_year_id != cls.academic_year_id:
            return {"success": False, "error": "Invalid academic_term_id for this class"}

    dup = ClassSubject.query.filter(
        ClassSubject.tenant_id == tenant_id,
        ClassSubject.class_id == class_id,
        ClassSubject.subject_id == subject_id,
        ClassSubject.deleted_at.is_(None),
        ClassSubject.status == "active",
    ).first()
    if dup:
        return {"success": False, "error": "This subject is already assigned to the class (active)"}

    cs = ClassSubject(
        tenant_id=tenant_id,
        class_id=class_id,
        subject_id=subject_id,
        weekly_periods=weekly,
        is_mandatory=bool(data.get("is_mandatory", True)),
        is_elective_bucket=bool(data.get("is_elective_bucket", False)),
        sort_order=data.get("sort_order"),
        academic_term_id=term_id,
        status=(data.get("status") or "active").strip() or "active",
    )
    try:
        db.session.add(cs)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return {"success": False, "error": "Could not create class subject (duplicate or constraint)"}
    return {"success": True, "class_subject": _serialize(cs)}


def update_offering(
    tenant_id: str, class_id: str, class_subject_id: str, data: Dict[str, Any]
) -> Dict[str, Any]:
    cls = get_class_for_tenant(class_id, tenant_id)
    if not cls:
        return {"success": False, "error": "Class not found"}

    cs = ClassSubject.query.filter_by(
        id=class_subject_id, tenant_id=tenant_id, class_id=class_id
    ).filter(ClassSubject.deleted_at.is_(None)).first()
    if not cs:
        return {"success": False, "error": "Class subject not found"}

    if "weekly_periods" in data and data["weekly_periods"] is not None:
        try:
            w = int(data["weekly_periods"])
        except (TypeError, ValueError):
            return {"success": False, "error": "weekly_periods must be a positive integer"}
        if w <= 0:
            return {"success": False, "error": "weekly_periods must be greater than 0"}
        cs.weekly_periods = w

    if "is_mandatory" in data:
        cs.is_mandatory = bool(data["is_mandatory"])
    if "is_elective_bucket" in data:
        cs.is_elective_bucket = bool(data["is_elective_bucket"])
    if "sort_order" in data:
        cs.sort_order = data["sort_order"]
    if "academic_term_id" in data:
        term_id = data["academic_term_id"]
        if term_id:
            term = AcademicTerm.query.filter_by(id=term_id, tenant_id=tenant_id).first()
            if not term or term.academic_year_id != cls.academic_year_id:
                return {"success": False, "error": "Invalid academic_term_id for this class"}
        cs.academic_term_id = term_id
    if "status" in data and data["status"] is not None:
        cs.status = str(data["status"]).strip() or cs.status

    cs.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return {"success": True, "class_subject": _serialize(cs)}


def delete_offering(tenant_id: str, class_id: str, class_subject_id: str) -> Dict[str, Any]:
    cls = get_class_for_tenant(class_id, tenant_id)
    if not cls:
        return {"success": False, "error": "Class not found"}

    cs = ClassSubject.query.filter_by(
        id=class_subject_id, tenant_id=tenant_id, class_id=class_id
    ).filter(ClassSubject.deleted_at.is_(None)).first()
    if not cs:
        return {"success": False, "error": "Class subject not found"}

    cs.status = "inactive"
    cs.deleted_at = datetime.now(timezone.utc)
    cs.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return {"success": True, "message": "Class subject removed"}
