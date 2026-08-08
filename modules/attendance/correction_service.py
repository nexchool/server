"""Changing attendance that has already been settled.

Attendance is evidence. Marking a register is one thing; altering it a week
later is another, and the difference is what a school needs when it is asked
why a child was recorded absent on a particular day.

So there are two ways in, and they are not the same. While a session is open,
a teacher corrects their own mistake by marking again. Once it is settled —
finalised, or past the hour the school stops accepting changes — a change
becomes a correction: it states what it is changing, carries a reason, names
who asked, and where the school requires it, waits for somebody to agree.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

from core.database import db
from core.school_time import school_today, utc_now
from modules.academics.backbone.models import AttendanceRecord, AttendanceSession

from .models import (
    CORRECTION_APPROVED,
    CORRECTION_REJECTED,
    CORRECTION_REQUESTED,
    AttendanceCorrection,
)

VALID_STATUSES = ("present", "absent", "late", "excused")


def _settings(tenant_id: str):
    from modules.academics.backbone.models import AcademicSettings

    return AcademicSettings.query.filter_by(tenant_id=tenant_id).first()


def corrections_need_approval(tenant_id: str) -> bool:
    """Whether a school reviews corrections before they take effect.

    Configurable because schools genuinely differ: a small primary trusts its
    teachers to fix their own registers, a large secondary wants the head of
    year to see every change.
    """
    settings = _settings(tenant_id)
    return bool(getattr(settings, "attendance_corrections_require_approval", False))


def lock_after_hours(tenant_id: str) -> Optional[int]:
    """Hours after the attendance day when the register stops accepting marks.

    None means only finalising locks it — the school closes its own registers
    rather than the clock doing it for them.
    """
    settings = _settings(tenant_id)
    return getattr(settings, "attendance_lock_after_hours", None)


def is_locked(session: AttendanceSession) -> bool:
    """Has this register stopped accepting ordinary marking?

    Two ways: somebody finalised it, or the school's own deadline passed. The
    second is what stops a register being quietly filled in at the end of
    term for a day nobody remembers.
    """
    if session is None:
        return False
    if session.status == "finalized":
        return True

    window = lock_after_hours(session.tenant_id)
    if not window:
        return False
    deadline = datetime.datetime.combine(
        session.session_date, datetime.time.min
    ) + datetime.timedelta(hours=int(window))
    return utc_now().replace(tzinfo=None) > deadline


def request_correction(
    tenant_id: str,
    record_id: str,
    *,
    to_status: str,
    reason: str,
    requested_by_user_id: str,
    may_decide: bool = False,
) -> Dict[str, Any]:
    """Ask for settled attendance to be changed.

    Applied at once where the school does not require review, or where the
    person asking is also somebody who could approve it — asking yourself for
    permission is a step, not a control. Either way the request is written
    down first, so the change is never the only evidence of itself.
    """
    to_status = (to_status or "").strip()
    if to_status not in VALID_STATUSES:
        return {"success": False, "error": f"status must be one of {', '.join(VALID_STATUSES)}"}
    if not (reason or "").strip():
        return {
            "success": False,
            "error": "A reason is required — a correction without one is an edit",
        }

    record = AttendanceRecord.query.filter_by(id=record_id, tenant_id=tenant_id).first()
    if record is None:
        return {"success": False, "error": "Attendance record not found"}
    if record.status == to_status:
        return {"success": False, "error": f"This is already recorded as {to_status}"}

    correction = AttendanceCorrection(
        tenant_id=tenant_id,
        attendance_record_id=record.id,
        from_status=record.status,
        to_status=to_status,
        reason=reason.strip(),
        status=CORRECTION_REQUESTED,
        requested_by_user_id=requested_by_user_id,
    )
    db.session.add(correction)

    applied = False
    if may_decide or not corrections_need_approval(tenant_id):
        _apply(correction, record, decided_by_user_id=requested_by_user_id)
        applied = True

    db.session.commit()
    return {"success": True, "correction": correction.to_dict(), "applied": applied}


def _apply(correction: AttendanceCorrection, record: AttendanceRecord, *, decided_by_user_id):
    record.status = correction.to_status
    record.updated_by_user_id = decided_by_user_id
    record.updated_at = utc_now()
    correction.status = CORRECTION_APPROVED
    correction.decided_by_user_id = decided_by_user_id
    correction.decided_at = utc_now()


def approve_correction(
    tenant_id: str, correction_id: str, *, decided_by_user_id: str, note: Optional[str] = None
) -> Dict[str, Any]:
    """Agree to the change, and make it."""
    correction = AttendanceCorrection.query.filter_by(
        id=correction_id, tenant_id=tenant_id
    ).first()
    if correction is None:
        return {"success": False, "error": "Correction not found"}
    if correction.status != CORRECTION_REQUESTED:
        return {"success": False, "error": f"This correction is already {correction.status}"}

    record = AttendanceRecord.query.filter_by(
        id=correction.attendance_record_id, tenant_id=tenant_id
    ).first()
    if record is None:
        return {"success": False, "error": "Attendance record not found"}

    _apply(correction, record, decided_by_user_id=decided_by_user_id)
    correction.decision_note = note
    db.session.commit()
    return {"success": True, "correction": correction.to_dict()}


def reject_correction(
    tenant_id: str, correction_id: str, *, decided_by_user_id: str, note: Optional[str] = None
) -> Dict[str, Any]:
    """Decline the change. The record stands, and the request is kept."""
    correction = AttendanceCorrection.query.filter_by(
        id=correction_id, tenant_id=tenant_id
    ).first()
    if correction is None:
        return {"success": False, "error": "Correction not found"}
    if correction.status != CORRECTION_REQUESTED:
        return {"success": False, "error": f"This correction is already {correction.status}"}

    correction.status = CORRECTION_REJECTED
    correction.decided_by_user_id = decided_by_user_id
    correction.decided_at = utc_now()
    correction.decision_note = note
    db.session.commit()
    return {"success": True, "correction": correction.to_dict()}


def corrections_for_record(tenant_id: str, record_id: str) -> List[AttendanceCorrection]:
    """Every change ever asked for on one register entry, oldest first."""
    return (
        AttendanceCorrection.query.filter_by(
            tenant_id=tenant_id, attendance_record_id=record_id
        )
        .order_by(AttendanceCorrection.requested_at.asc())
        .all()
    )


def pending_corrections(tenant_id: str) -> List[AttendanceCorrection]:
    """What is waiting for somebody to decide."""
    return (
        AttendanceCorrection.query.filter_by(
            tenant_id=tenant_id, status=CORRECTION_REQUESTED
        )
        .order_by(AttendanceCorrection.requested_at.asc())
        .all()
    )
