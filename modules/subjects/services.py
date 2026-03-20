"""
Subject Services

Business logic for subject CRUD operations. All operations are tenant-scoped.
"""

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

        # Check unique (name, tenant_id)
        existing = Subject.query.filter_by(tenant_id=tenant_id, name=name).first()
        if existing:
            return {"success": False, "error": "Subject with this name already exists"}

        subject = Subject(
            tenant_id=tenant_id,
            name=name,
            code=(data.get("code") or "").strip() or None,
            description=(data.get("description") or "").strip() or None,
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


def get_subjects(tenant_id: str) -> List[Dict]:
    """
    Get all subjects for a tenant.

    Args:
        tenant_id: Tenant ID for scoping

    Returns:
        List of subject dicts
    """
    subjects = Subject.query.filter_by(tenant_id=tenant_id).order_by(Subject.name).all()
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
    subject = Subject.query.filter_by(id=subject_id, tenant_id=tenant_id).first()
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
        subject = Subject.query.filter_by(id=subject_id, tenant_id=tenant_id).first()
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
            ).first()
            if existing:
                return {"success": False, "error": "Subject with this name already exists"}
            subject.name = name

        if "code" in data:
            subject.code = (data["code"] or "").strip() or None
        if "description" in data:
            subject.description = (data["description"] or "").strip() or None

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
    Delete a subject (tenant-scoped).

    Args:
        subject_id: Subject UUID
        tenant_id: Tenant ID for scoping

    Returns:
        Dict with success status or error
    """
    try:
        subject = Subject.query.filter_by(id=subject_id, tenant_id=tenant_id).first()
        if not subject:
            return {"success": False, "error": "Subject not found"}

        subject.delete()
        return {"success": True, "message": "Subject deleted successfully"}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}
