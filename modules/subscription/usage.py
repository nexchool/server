"""
Tenant usage tracking.

Single entry point: `recompute_tenant_usage(tenant_id)` recounts the
tenant's active students directly from the `students` table and writes
the snapshot to `tenant_usage`. Called from the student service layer
on create / update / delete so billing always reflects the live count.

Inactive statuses match the billing service in modules.platform.services.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.exc import SQLAlchemyError

from core.database import db
from core.models import TenantUsage

logger = logging.getLogger(__name__)


# Mirror modules.platform.services.calculate_tenant_billing so
# active_students_count agrees with what the bill is computed against.
INACTIVE_STUDENT_STATUSES = ("inactive", "withdrawn", "graduated", "transferred")


def _count_active_students(tenant_id: str) -> int:
    # Local import keeps this module light at import time and avoids an
    # import cycle with the students module.
    from modules.students.models import Student

    return (
        db.session.query(Student)
        .filter(Student.tenant_id == tenant_id)
        .filter(
            (Student.student_status.is_(None))
            | (~Student.student_status.in_(INACTIVE_STUDENT_STATUSES))
        )
        .count()
    )


def recompute_tenant_usage(tenant_id: str, *, commit: bool = True) -> Optional[int]:
    """
    Recount active students and persist the snapshot.

    Returns the new count, or None on failure (logged, never raised — a
    usage update must never break a student write).

    Pass `commit=False` to merge writes into the caller's transaction;
    the default `commit=True` matches the existing service-layer pattern
    used elsewhere in the codebase.
    """
    if not tenant_id:
        return None

    try:
        count = _count_active_students(tenant_id)
        row = TenantUsage.query.filter_by(tenant_id=tenant_id).first()
        if row is None:
            row = TenantUsage(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                active_students_count=count,
                last_updated_at=datetime.utcnow(),
            )
            db.session.add(row)
        else:
            row.active_students_count = count
            row.last_updated_at = datetime.utcnow()

        if commit:
            db.session.commit()
        return count
    except SQLAlchemyError as e:
        logger.exception("recompute_tenant_usage failed for tenant=%s: %s", tenant_id, e)
        if commit:
            db.session.rollback()
        return None


def get_tenant_usage(tenant_id: str) -> dict:
    """Read-only snapshot, recomputing if no row exists yet."""
    row = TenantUsage.query.filter_by(tenant_id=tenant_id).first()
    if row is None:
        # First read for this tenant — populate the row lazily.
        recompute_tenant_usage(tenant_id)
        row = TenantUsage.query.filter_by(tenant_id=tenant_id).first()
    if row is None:
        return {"tenant_id": tenant_id, "active_students_count": 0, "last_updated_at": None}
    return {
        "tenant_id": tenant_id,
        "active_students_count": row.active_students_count,
        "last_updated_at": (
            row.last_updated_at.isoformat() if row.last_updated_at else None
        ),
    }
