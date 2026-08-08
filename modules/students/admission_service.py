"""Becoming a student of the school.

Admission is a decision a school makes, and decisions have losers. Most of
what this module protects is the record of the child who applied and did not
join: the family who withdrew, the papers that never came, the offer that
went elsewhere. `create_student` alone could not hold any of that, because a
rejected applicant has no student row to hold it in.

So an application lives on its own until it is approved, and approval is the
only path from applicant to student. Nothing here half-creates anybody: no
Person, no admission number, no place in a class until the school says yes.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, Optional

from core.branch_scope import assert_class_allowed
from core.database import db
from core.school_time import school_today
from core.tenant import get_tenant_id

from .models import (
    ADMISSION_APPROVED,
    ADMISSION_OPEN_STATUSES,
    ADMISSION_REJECTED,
    ADMISSION_SUBMITTED,
    ADMISSION_UNDER_REVIEW,
    ADMISSION_WITHDRAWN,
    EVENT_ADMITTED,
    AdmissionApplication,
    Student,
)

_REQUIRED = ("applicant_name", "guardian_name", "guardian_relationship", "guardian_phone")


def _application(application_id: str):
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None, {"success": False, "error": "Tenant context is required"}
    application = AdmissionApplication.query.filter_by(
        id=application_id, tenant_id=tenant_id
    ).first()
    if not application:
        return None, {"success": False, "error": "Application not found"}
    return application, None


def submit_application(data: Dict[str, Any]) -> Dict[str, Any]:
    """Record that someone has asked to join.

    Guardian details are required at this point, not at approval: an
    application nobody can be contacted about is one the school could never
    act on, and finding that out at the decision is too late.
    """
    tenant_id = get_tenant_id()
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}

    missing = [field for field in _REQUIRED if not (data.get(field) or "").strip()]
    if missing:
        return {
            "success": False,
            "error": f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} required",
        }

    academic_year_id = (data.get("academic_year_id") or "").strip()
    if not academic_year_id:
        return {"success": False, "error": "academic_year_id is required"}

    desired_class_id = (data.get("desired_class_id") or "").strip() or None
    if desired_class_id:
        # A branch-restricted admin may only take applications for their campus.
        assert_class_allowed(desired_class_id)

    application = AdmissionApplication(
        tenant_id=tenant_id,
        applicant_name=data["applicant_name"].strip(),
        date_of_birth=_as_date(data.get("date_of_birth")),
        gender=(data.get("gender") or None),
        phone=(data.get("phone") or None),
        email=(data.get("email") or None),
        address=(data.get("address") or None),
        guardian_name=data["guardian_name"].strip(),
        guardian_relationship=data["guardian_relationship"].strip(),
        guardian_phone=data["guardian_phone"].strip(),
        guardian_email=(data.get("guardian_email") or None),
        academic_year_id=academic_year_id,
        desired_class_id=desired_class_id,
        status=ADMISSION_SUBMITTED,
        submitted_on=_as_date(data.get("submitted_on")) or school_today(),
        notes=(data.get("notes") or None),
    )
    db.session.add(application)
    db.session.commit()
    return {"success": True, "application": application.to_dict()}


def _as_date(raw) -> Optional[datetime.date]:
    if not raw:
        return None
    if isinstance(raw, datetime.date):
        return raw
    return datetime.date.fromisoformat(str(raw))


def start_review(application_id: str) -> Dict[str, Any]:
    """The school has begun checking the application."""
    application, refusal = _application(application_id)
    if refusal:
        return refusal
    if application.status != ADMISSION_SUBMITTED:
        return {
            "success": False,
            "error": f"Only a submitted application can be reviewed (this one is {application.status})",
        }
    application.status = ADMISSION_UNDER_REVIEW
    db.session.commit()
    return {"success": True, "application": application.to_dict()}


def approve(
    application_id: str,
    *,
    class_id: Optional[str] = None,
    decided_by_user_id: Optional[str] = None,
    decided_on: Optional[datetime.date] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Say yes, and let the applicant become a student.

    This is the only place an application turns into a student, and it does
    so through the ordinary admission path — the same Person recording,
    admission number and household that any other admission gets. Approving
    twice is refused rather than admitting the same child again.
    """
    from .services import create_student

    application, refusal = _application(application_id)
    if refusal:
        return refusal
    if application.status not in ADMISSION_OPEN_STATUSES:
        return {
            "success": False,
            "error": f"This application is already {application.status}",
        }

    placement_class_id = class_id or application.desired_class_id
    if placement_class_id:
        assert_class_allowed(placement_class_id)

    created = create_student(
        name=application.applicant_name,
        academic_year_id=application.academic_year_id,
        class_id=placement_class_id,
        guardian_name=application.guardian_name,
        guardian_relationship=application.guardian_relationship,
        guardian_phone=application.guardian_phone,
        guardian_email=application.guardian_email,
        email=application.email,
        phone=application.phone,
        date_of_birth=(
            application.date_of_birth.isoformat() if application.date_of_birth else None
        ),
        gender=application.gender,
        address=application.address,
    )
    if not created.get("success"):
        # The application stays open: the school said yes, the admission
        # could not be completed, and someone has to see why.
        return {"success": False, "error": created.get("error", "Could not admit the applicant")}

    student_id = created["student"]["id"]
    application.status = ADMISSION_APPROVED
    application.decided_on = decided_on or school_today()
    application.decided_by_user_id = decided_by_user_id
    application.decision_reason = reason
    application.student_id = student_id

    student = Student.query.filter_by(id=student_id).first()
    if student is not None:
        from .lifecycle_service import record_event

        record_event(
            student,
            EVENT_ADMITTED,
            occurred_on=application.decided_on,
            reason=reason,
            details={"application_id": application.id},
            recorded_by_user_id=decided_by_user_id,
        )
    db.session.commit()

    return {
        "success": True,
        "application": application.to_dict(),
        "student": created["student"],
        # Only present when the school issued a login, and only this once.
        "credentials": created.get("credentials"),
    }


def _close(application_id, status, *, reason, decided_by_user_id, decided_on):
    application, refusal = _application(application_id)
    if refusal:
        return refusal
    if application.status not in ADMISSION_OPEN_STATUSES:
        return {
            "success": False,
            "error": f"This application is already {application.status}",
        }
    application.status = status
    application.decided_on = decided_on or school_today()
    application.decided_by_user_id = decided_by_user_id
    application.decision_reason = reason
    db.session.commit()
    return {"success": True, "application": application.to_dict()}


def reject(
    application_id: str,
    *,
    reason: Optional[str] = None,
    decided_by_user_id: Optional[str] = None,
    decided_on: Optional[datetime.date] = None,
) -> Dict[str, Any]:
    """The school declines. The record stays; no student is created."""
    return _close(
        application_id,
        ADMISSION_REJECTED,
        reason=reason,
        decided_by_user_id=decided_by_user_id,
        decided_on=decided_on,
    )


def withdraw(
    application_id: str,
    *,
    reason: Optional[str] = None,
    decided_by_user_id: Optional[str] = None,
    decided_on: Optional[datetime.date] = None,
) -> Dict[str, Any]:
    """The family withdraws — they moved, or chose another school.

    Kept apart from rejection because who ended it is the useful part when
    the same family applies again next year.
    """
    return _close(
        application_id,
        ADMISSION_WITHDRAWN,
        reason=reason,
        decided_by_user_id=decided_by_user_id,
        decided_on=decided_on,
    )


def list_applications(
    *,
    status: Optional[str] = None,
    academic_year_id: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    per_page: int = 20,
) -> Dict[str, Any]:
    """Applications for this school, newest first.

    Decided applications are returned alongside open ones — a school is
    asked "did we ever hear from that family?" more often than it is asked
    who is pending.
    """
    tenant_id = get_tenant_id()
    if not tenant_id:
        return {"items": [], "total": 0, "page": 1, "per_page": 0, "total_pages": 1}

    query = AdmissionApplication.query.filter_by(tenant_id=tenant_id)
    if status:
        query = query.filter(AdmissionApplication.status == status)
    if academic_year_id:
        query = query.filter(
            AdmissionApplication.academic_year_id == academic_year_id
        )
    if search:
        pattern = f"%{search.strip()}%"
        query = query.filter(
            db.or_(
                AdmissionApplication.applicant_name.ilike(pattern),
                AdmissionApplication.guardian_name.ilike(pattern),
                AdmissionApplication.guardian_phone.ilike(pattern),
            )
        )

    total = query.count()
    page = max(1, int(page))
    per_page = max(1, min(int(per_page), 100))
    rows = (
        query.order_by(
            AdmissionApplication.submitted_on.desc(),
            AdmissionApplication.created_at.desc(),
        )
        .limit(per_page)
        .offset((page - 1) * per_page)
        .all()
    )
    return {
        "items": [row.to_dict() for row in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
    }


def get_application(application_id: str) -> Dict[str, Any]:
    application, refusal = _application(application_id)
    if refusal:
        return refusal
    return {"success": True, "application": application.to_dict()}
