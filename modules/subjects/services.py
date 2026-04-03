"""
Subject Services

Business logic for subject CRUD operations. All operations are tenant-scoped.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy.exc import IntegrityError

from backend.core.database import db
from backend.core.tenant import get_tenant_id

from .models import Subject


def create_subject(data: Dict, tenant_id: str) -> Dict:
    """
    Create a new subject (tenant-scoped).

    Args:
        data: Dict with name (required), code (optional), description (optional)
        tenant_id: Tenant ID for scoping

    Returns:
        Dict with success status and subject data or error
    """
    try:
        if not tenant_id:
            return {"success": False, "error": "Tenant context is required"}

        name = (data.get("name") or "").strip()
        if not name:
            return {"success": False, "error": "name is required"}

        existing = Subject.query.filter(
            Subject.tenant_id == tenant_id,
            Subject.name == name,
            Subject.deleted_at.is_(None),
        ).first()
        if existing:
            return {"success": False, "error": "Subject with this name already exists"}

        code = (data.get("code") or "").strip() or None
        if code:
            dup = Subject.query.filter(
                Subject.tenant_id == tenant_id,
                Subject.code == code,
                Subject.deleted_at.is_(None),
            ).first()
            if dup:
                return {"success": False, "error": "Subject with this code already exists"}

        subject_type = (data.get("subject_type") or "core").strip()
        if subject_type not in ("core", "elective", "activity", "other"):
            subject_type = "core"

        subject = Subject(
            tenant_id=tenant_id,
            name=name,
            code=code,
            description=(data.get("description") or "").strip() or None,
            subject_type=subject_type,
            is_active=bool(data.get("is_active", True)),
        )
        subject.save()

        return {"success": True, "subject": subject.to_dict()}
    except IntegrityError as e:
        db.session.rollback()
        error_msg = str(e.orig) if hasattr(e, "orig") else str(e)
        if "uq_subjects_name_tenant" in error_msg or "unique" in error_msg.lower():
            return {"success": False, "error": "Subject with this name already exists"}
        return {"success": False, "error": "Database constraint violation"}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}


def get_subjects(tenant_id: str, include_inactive: bool = False) -> List[Dict]:
    """Get subjects for a tenant (excludes soft-deleted)."""
    q = Subject.query.filter_by(tenant_id=tenant_id).filter(Subject.deleted_at.is_(None))
    if not include_inactive:
        q = q.filter(Subject.is_active.is_(True))
    subjects = q.order_by(Subject.name).all()
    return [s.to_dict() for s in subjects]


def list_subjects_filtered(tenant_id: str, include_inactive: bool = False) -> List[Dict]:
    """List subjects without Flask request; optional inactive rows."""
    q = Subject.query.filter_by(tenant_id=tenant_id).filter(Subject.deleted_at.is_(None))
    if not include_inactive:
        q = q.filter(Subject.is_active.is_(True))
    subjects = q.order_by(Subject.name).all()
    return [s.to_dict() for s in subjects]


def get_subject_by_id(subject_id: str, tenant_id: str) -> Optional[Dict]:
    """
    Get a subject by ID (tenant-scoped).

    Args:
        subject_id: Subject UUID
        tenant_id: Tenant ID for scoping

    Returns:
        Subject dict or None if not found
    """
    subject = Subject.query.filter_by(id=subject_id, tenant_id=tenant_id).filter(
        Subject.deleted_at.is_(None)
    ).first()
    return subject.to_dict() if subject else None


def update_subject(subject_id: str, data: Dict, tenant_id: str) -> Dict:
    """
    Update a subject (tenant-scoped).

    Args:
        subject_id: Subject UUID
        data: Dict with optional name, code, description
        tenant_id: Tenant ID for scoping

    Returns:
        Dict with success status and updated subject data or error
    """
    try:
        subject = Subject.query.filter_by(id=subject_id, tenant_id=tenant_id).filter(
            Subject.deleted_at.is_(None)
        ).first()
        if not subject:
            return {"success": False, "error": "Subject not found"}

        if "name" in data and data["name"] is not None:
            name = (data["name"] or "").strip()
            if not name:
                return {"success": False, "error": "name cannot be empty"}
            # Check unique when changing name
            existing = Subject.query.filter(
                Subject.tenant_id == tenant_id,
                Subject.name == name,
                Subject.id != subject_id,
                Subject.deleted_at.is_(None),
            ).first()
            if existing:
                return {"success": False, "error": "Subject with this name already exists"}
            subject.name = name

        if "code" in data:
            code = (data["code"] or "").strip() or None
            if code:
                dup = Subject.query.filter(
                    Subject.tenant_id == tenant_id,
                    Subject.code == code,
                    Subject.id != subject_id,
                    Subject.deleted_at.is_(None),
                ).first()
                if dup:
                    return {"success": False, "error": "Subject with this code already exists"}
            subject.code = code
        if "description" in data:
            subject.description = (data["description"] or "").strip() or None
        if "subject_type" in data and data["subject_type"] is not None:
            st = str(data["subject_type"]).strip()
            if st in ("core", "elective", "activity", "other"):
                subject.subject_type = st
        if "is_active" in data and data["is_active"] is not None:
            subject.is_active = bool(data["is_active"])

        subject.updated_at = datetime.utcnow()
        subject.save()
        return {"success": True, "subject": subject.to_dict()}
    except IntegrityError as e:
        db.session.rollback()
        error_msg = str(e.orig) if hasattr(e, "orig") else str(e)
        if "uq_subjects_name_tenant" in error_msg or "unique" in error_msg.lower():
            return {"success": False, "error": "Subject with this name already exists"}
        return {"success": False, "error": "Database constraint violation"}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}


def delete_subject(subject_id: str, tenant_id: str) -> Dict:
    """
    Soft-archive a subject. Hard delete is not used when the subject is referenced.
    """
    try:
        from backend.modules.classes.models import ClassSubject

        subject = Subject.query.filter_by(id=subject_id, tenant_id=tenant_id).filter(
            Subject.deleted_at.is_(None)
        ).first()
        if not subject:
            return {"success": False, "error": "Subject not found"}

        ref = ClassSubject.query.filter(
            ClassSubject.tenant_id == tenant_id,
            ClassSubject.subject_id == subject_id,
            ClassSubject.deleted_at.is_(None),
        ).first()
        if ref:
            return {
                "success": False,
                "error": "Subject is assigned to a class; archive it instead of deleting.",
            }

        subject.is_active = False
        subject.deleted_at = datetime.now(timezone.utc)
        db.session.add(subject)
        db.session.commit()
        return {"success": True, "message": "Subject archived successfully"}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}
