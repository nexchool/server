"""
Subject Load Services

Business logic for managing subject weekly period loads per class.
These are used by the timetable generator as scheduling constraints.
"""

from typing import Dict, List, Optional
from sqlalchemy.exc import IntegrityError

from backend.core.database import db
from backend.core.tenant import get_tenant_id
from backend.modules.subjects.models import Subject
from .models import Class, SubjectLoad


def get_subject_loads(class_id: str) -> List[Dict]:
    """Return all subject load records for a class."""
    tenant_id = get_tenant_id()
    items = SubjectLoad.query.filter_by(class_id=class_id, tenant_id=tenant_id).order_by(
        SubjectLoad.created_at
    ).all()
    return [i.to_dict() for i in items]


def create_subject_load(class_id: str, subject_id: str, weekly_periods: int) -> Dict:
    """Create a subject load record for a class."""
    try:
        tenant_id = get_tenant_id()

        cls = Class.query.filter_by(id=class_id, tenant_id=tenant_id).first()
        if not cls:
            return {"success": False, "error": "Class not found"}

        subject = Subject.query.filter_by(id=subject_id, tenant_id=tenant_id).first()
        if not subject:
            return {"success": False, "error": "Subject not found"}

        if weekly_periods < 1:
            return {"success": False, "error": "weekly_periods must be >= 1"}

        existing = SubjectLoad.query.filter_by(
            class_id=class_id, subject_id=subject_id, tenant_id=tenant_id
        ).first()
        if existing:
            return {"success": False, "error": "Subject load already exists for this class. Use PUT to update."}

        load = SubjectLoad(
            tenant_id=tenant_id,
            class_id=class_id,
            subject_id=subject_id,
            weekly_periods=weekly_periods,
        )
        load.save()
        return {"success": True, "subject_load": load.to_dict()}

    except IntegrityError:
        db.session.rollback()
        return {"success": False, "error": "Subject load already exists for this class"}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": f"Failed to create subject load: {str(e)}"}


def update_subject_load(load_id: str, weekly_periods: int) -> Dict:
    """Update weekly_periods for an existing subject load record."""
    try:
        tenant_id = get_tenant_id()
        load = SubjectLoad.query.filter_by(id=load_id, tenant_id=tenant_id).first()
        if not load:
            return {"success": False, "error": "Subject load record not found"}
        if weekly_periods < 1:
            return {"success": False, "error": "weekly_periods must be >= 1"}
        load.weekly_periods = weekly_periods
        load.save()
        return {"success": True, "subject_load": load.to_dict()}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": f"Failed to update subject load: {str(e)}"}


def delete_subject_load(load_id: str) -> Dict:
    """Delete a subject load record."""
    try:
        tenant_id = get_tenant_id()
        load = SubjectLoad.query.filter_by(id=load_id, tenant_id=tenant_id).first()
        if not load:
            return {"success": False, "error": "Subject load record not found"}
        load.delete()
        return {"success": True}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": f"Failed to delete subject load: {str(e)}"}
