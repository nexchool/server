"""Leaving the school, and coming back to it.

Employment ends in ways a school distinguishes and a status column cannot:
somebody resigns, somebody retires after thirty years, somebody is
dismissed. All three end a period; only the record says which, and a service
letter is written from that record.

Returning is the case this module exists to get right. A teacher who comes
back after two years is not a new employee — the canon is exact: "No new
Person is created. No new Staff relationship is created. Only a new
Employment Period begins." Their first period stays as it was, so the school
can still answer what they did the first time.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

from core.database import db
from core.school_time import school_today
from core.tenant import get_tenant_id

from .employment import (
    EMPLOYMENT_STATUS_NOTICE_PERIOD,
    EMPLOYMENT_STATUS_RESIGNED,
    EMPLOYMENT_STATUS_RETIRED,
    EMPLOYMENT_STATUS_TERMINATED,
    EMPLOYMENT_STATUS_WORKING,
    STAFF_EVENT_REJOINED,
    STAFF_EVENT_RESIGNED,
    STAFF_EVENT_RETIRED,
    STAFF_EVENT_TERMINATED,
    Staff,
    StaffEmploymentPeriod,
    StaffLifecycleEvent,
)

# How a period ended, and the status it leaves the person in. Kept together
# so the two cannot drift: a period that ended in retirement must not leave
# somebody reading as resigned.
_SEPARATIONS = {
    "resigned": (EMPLOYMENT_STATUS_RESIGNED, STAFF_EVENT_RESIGNED),
    "retired": (EMPLOYMENT_STATUS_RETIRED, STAFF_EVENT_RETIRED),
    "terminated": (EMPLOYMENT_STATUS_TERMINATED, STAFF_EVENT_TERMINATED),
}


def record_staff_event(
    staff: Staff,
    event: str,
    *,
    occurred_on: Optional[datetime.date] = None,
    period: Optional[StaffEmploymentPeriod] = None,
    reason: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    recorded_by_user_id: Optional[str] = None,
) -> StaffLifecycleEvent:
    """Write one milestone to the employment record.

    Added to the session, not committed — it belongs to the transaction of
    whatever is happening, so it cannot survive work that was rolled back.
    """
    entry = StaffLifecycleEvent(
        tenant_id=staff.tenant_id,
        staff_id=staff.id,
        employment_period_id=period.id if period is not None else None,
        event=event,
        occurred_on=occurred_on or school_today(),
        reason=reason,
        details=details,
        recorded_by_user_id=recorded_by_user_id,
    )
    db.session.add(entry)
    return entry


def employment_timeline(staff_id: str) -> List[StaffLifecycleEvent]:
    """One person's employment history, oldest first."""
    return (
        StaffLifecycleEvent.query.filter_by(staff_id=staff_id)
        .order_by(
            StaffLifecycleEvent.occurred_on.asc(),
            StaffLifecycleEvent.created_at.asc(),
        )
        .all()
    )


def _staff_for_workflow(staff_id: str):
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None, {"success": False, "error": "Tenant context is required"}
    staff = Staff.query.filter_by(id=staff_id, tenant_id=tenant_id).first()
    if not staff:
        return None, {"success": False, "error": "Staff member not found"}
    return staff, None


def _open_period(staff: Staff) -> Optional[StaffEmploymentPeriod]:
    for period in sorted(
        staff.periods, key=lambda p: (p.joined_on or datetime.date.min), reverse=True
    ):
        if period.is_open:
            return period
    return None


_WHEN_EMPLOYMENT_ENDS = []


def when_employment_ends(handler) -> None:
    """Register something that must happen when a period closes.

    People announces; it does not reach. Ending someone's teaching is a fact
    about teaching, so the Academic domain owns that rule and registers it
    here — the same inversion that keeps the account-to-person rule in
    Identity. Registered explicitly in `app.py`, because a guarantee that
    depends on import order is not a guarantee.
    """
    _WHEN_EMPLOYMENT_ENDS.append(handler)


def _announce_employment_ended(staff: Staff, on_date: datetime.date) -> Dict[str, Any]:
    """Tell whoever is listening, and collect what they did."""
    done: Dict[str, Any] = {}
    for handler in _WHEN_EMPLOYMENT_ENDS:
        outcome = handler(staff, on_date) or {}
        done.update(outcome)
    return done


def _separate(
    staff_id: str,
    kind: str,
    *,
    last_working_day: Optional[datetime.date],
    reason: Optional[str],
    recorded_by_user_id: Optional[str],
) -> Dict[str, Any]:
    staff, refusal = _staff_for_workflow(staff_id)
    if refusal:
        return refusal

    period = _open_period(staff)
    if period is None:
        return {
            "success": False,
            "error": f"This person is not currently employed here (they are {staff.employment_status})",
        }

    status, event = _SEPARATIONS[kind]
    left_on = last_working_day or school_today()

    period.left_on = left_on
    period.end_reason = kind
    staff.employment_status = status

    ended = _announce_employment_ended(staff, left_on)
    record_staff_event(
        staff,
        event,
        occurred_on=left_on,
        period=period,
        reason=reason,
        details={"on_leaving": ended} if ended else None,
        recorded_by_user_id=recorded_by_user_id,
    )
    db.session.commit()

    return {
        "success": True,
        "staff_id": staff.id,
        "employment_status": staff.employment_status,
        "last_working_day": left_on.isoformat(),
        "on_leaving": ended,
    }


def resign(
    staff_id: str,
    *,
    last_working_day: Optional[datetime.date] = None,
    reason: Optional[str] = None,
    recorded_by_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Somebody leaves of their own accord."""
    return _separate(
        staff_id,
        "resigned",
        last_working_day=last_working_day,
        reason=reason,
        recorded_by_user_id=recorded_by_user_id,
    )


def retire(
    staff_id: str,
    *,
    last_working_day: Optional[datetime.date] = None,
    reason: Optional[str] = None,
    recorded_by_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """A career here ends. Distinct from resignation because a school's
    records, references and pensions all treat it differently."""
    return _separate(
        staff_id,
        "retired",
        last_working_day=last_working_day,
        reason=reason,
        recorded_by_user_id=recorded_by_user_id,
    )


def terminate(
    staff_id: str,
    *,
    last_working_day: Optional[datetime.date] = None,
    reason: Optional[str] = None,
    recorded_by_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """The organization ends the employment."""
    return _separate(
        staff_id,
        "terminated",
        last_working_day=last_working_day,
        reason=reason,
        recorded_by_user_id=recorded_by_user_id,
    )


def give_notice(
    staff_id: str,
    *,
    last_working_day: datetime.date,
    reason: Optional[str] = None,
    recorded_by_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Somebody has resigned but is still working out their notice.

    The canon draws resignation as two steps, and a school needs the middle
    one: during notice the person is still employed, still teaching, still
    paid — but everyone knows they are going. Complete it with `resign()` on
    the last working day.
    """
    staff, refusal = _staff_for_workflow(staff_id)
    if refusal:
        return refusal
    if _open_period(staff) is None:
        return {"success": False, "error": "This person is not currently employed here"}

    staff.employment_status = EMPLOYMENT_STATUS_NOTICE_PERIOD
    record_staff_event(
        staff,
        STAFF_EVENT_RESIGNED,
        occurred_on=school_today(),
        period=_open_period(staff),
        reason=reason,
        details={"notice_given": True, "last_working_day": last_working_day.isoformat()},
        recorded_by_user_id=recorded_by_user_id,
    )
    db.session.commit()
    return {
        "success": True,
        "staff_id": staff.id,
        "employment_status": staff.employment_status,
        "last_working_day": last_working_day.isoformat(),
    }


def rejoin(
    staff_id: str,
    *,
    joined_on: Optional[datetime.date] = None,
    designation: Optional[str] = None,
    department_id: Optional[str] = None,
    reason: Optional[str] = None,
    recorded_by_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """A former staff member returns.

    Their first period stays exactly as it was — this opens a second one, so
    the record reads as two spells rather than one long one interrupted by
    nothing. No new Person, no second Staff relationship: they are the same
    employee, which is what makes their earlier service still theirs.
    """
    staff, refusal = _staff_for_workflow(staff_id)
    if refusal:
        return refusal

    if _open_period(staff) is not None:
        return {
            "success": False,
            "error": "This person is already employed here",
        }

    started = joined_on or school_today()
    period = StaffEmploymentPeriod(
        tenant_id=staff.tenant_id, staff_id=staff.id, joined_on=started
    )
    db.session.add(period)
    db.session.flush()

    staff.employment_status = EMPLOYMENT_STATUS_WORKING
    if designation:
        staff.designation = designation
    if department_id:
        staff.department_id = department_id

    record_staff_event(
        staff,
        STAFF_EVENT_REJOINED,
        occurred_on=started,
        period=period,
        reason=reason,
        details={"designation": staff.designation} if staff.designation else None,
        recorded_by_user_id=recorded_by_user_id,
    )
    db.session.commit()

    return {
        "success": True,
        "staff_id": staff.id,
        "employment_status": staff.employment_status,
        "employment_period_id": period.id,
        "joined_on": started.isoformat(),
    }
