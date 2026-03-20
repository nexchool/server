"""
Teacher Constraint Services

Business logic for teacher management constraint features:
  - Subject Expertise
  - Availability Slots
  - Leave Planner (with balance enforcement)
  - Workload Rules
  - Leave Policy management
  - Teacher Leave Balance management
"""

from typing import Dict, List, Optional
from datetime import datetime, date

from sqlalchemy.exc import IntegrityError

from backend.core.database import db
from backend.core.tenant import get_tenant_id
from .models import (
    Teacher,
    TeacherSubject,
    TeacherAvailability,
    TeacherLeave,
    TeacherWorkloadRule,
    LeavePolicy,
    TeacherLeaveBalance,
    LEAVE_TYPES,
    DEFAULT_POLICY_SETTINGS,
)
from backend.modules.subjects.models import Subject
from backend.modules.holidays.services import get_working_days_info_for_range


# ---------------------------------------------------------------------------
# Teacher Subject Expertise
# ---------------------------------------------------------------------------

def get_teacher_subjects(teacher_id: str) -> List[Dict]:
    """Return all subjects linked to a teacher."""
    tenant_id = get_tenant_id()
    items = TeacherSubject.query.filter_by(teacher_id=teacher_id, tenant_id=tenant_id).all()
    return [i.to_dict() for i in items]


def add_teacher_subject(teacher_id: str, subject_id: str) -> Dict:
    """Assign a subject to a teacher (idempotent)."""
    try:
        tenant_id = get_tenant_id()

        teacher = Teacher.query.filter_by(id=teacher_id, tenant_id=tenant_id).first()
        if not teacher:
            return {"success": False, "error": "Teacher not found"}

        subject = Subject.query.filter_by(id=subject_id, tenant_id=tenant_id).first()
        if not subject:
            return {"success": False, "error": "Subject not found"}

        existing = TeacherSubject.query.filter_by(
            teacher_id=teacher_id, subject_id=subject_id, tenant_id=tenant_id
        ).first()
        if existing:
            return {"success": True, "teacher_subject": existing.to_dict()}

        ts = TeacherSubject(
            tenant_id=tenant_id,
            teacher_id=teacher_id,
            subject_id=subject_id,
        )
        ts.save()
        return {"success": True, "teacher_subject": ts.to_dict()}

    except IntegrityError:
        db.session.rollback()
        return {"success": False, "error": "Subject already assigned to teacher"}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": f"Failed to assign subject: {str(e)}"}


def remove_teacher_subject(teacher_id: str, subject_id: str) -> Dict:
    """Remove a subject from a teacher."""
    try:
        tenant_id = get_tenant_id()
        ts = TeacherSubject.query.filter_by(
            teacher_id=teacher_id, subject_id=subject_id, tenant_id=tenant_id
        ).first()
        if not ts:
            return {"success": False, "error": "Teacher-subject link not found"}
        ts.delete()
        return {"success": True}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": f"Failed to remove subject: {str(e)}"}


# ---------------------------------------------------------------------------
# Teacher Availability
# ---------------------------------------------------------------------------

def get_teacher_availability(teacher_id: str) -> List[Dict]:
    """Return all availability records for a teacher."""
    tenant_id = get_tenant_id()
    items = TeacherAvailability.query.filter_by(teacher_id=teacher_id, tenant_id=tenant_id).order_by(
        TeacherAvailability.day_of_week, TeacherAvailability.period_number
    ).all()
    return [i.to_dict() for i in items]


def create_availability(teacher_id: str, day_of_week: int, period_number: int, available: bool) -> Dict:
    """Create an availability record."""
    try:
        tenant_id = get_tenant_id()

        teacher = Teacher.query.filter_by(id=teacher_id, tenant_id=tenant_id).first()
        if not teacher:
            return {"success": False, "error": "Teacher not found"}

        if not 1 <= day_of_week <= 7:
            return {"success": False, "error": "day_of_week must be between 1 and 7"}
        if period_number < 1:
            return {"success": False, "error": "period_number must be >= 1"}

        slot = TeacherAvailability(
            tenant_id=tenant_id,
            teacher_id=teacher_id,
            day_of_week=day_of_week,
            period_number=period_number,
            available=available,
        )
        slot.save()
        return {"success": True, "availability": slot.to_dict()}

    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": f"Failed to create availability: {str(e)}"}


def update_availability(availability_id: str, available: bool) -> Dict:
    """Update an availability record."""
    try:
        tenant_id = get_tenant_id()
        slot = TeacherAvailability.query.filter_by(id=availability_id, tenant_id=tenant_id).first()
        if not slot:
            return {"success": False, "error": "Availability record not found"}
        slot.available = available
        slot.save()
        return {"success": True, "availability": slot.to_dict()}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": f"Failed to update availability: {str(e)}"}


def delete_availability(availability_id: str) -> Dict:
    """Delete an availability record."""
    try:
        tenant_id = get_tenant_id()
        slot = TeacherAvailability.query.filter_by(id=availability_id, tenant_id=tenant_id).first()
        if not slot:
            return {"success": False, "error": "Availability record not found"}
        slot.delete()
        return {"success": True}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": f"Failed to delete availability: {str(e)}"}


# ---------------------------------------------------------------------------
# Academic Year Helper
# ---------------------------------------------------------------------------

def get_current_academic_year() -> str:
    """
    Return current academic year string using April–March cycle.
    e.g. Apr 2025 – Mar 2026 → "2025-26"
    """
    today = date.today()
    if today.month >= 4:
        return f"{today.year}-{str(today.year + 1)[2:]}"
    return f"{today.year - 1}-{str(today.year)[2:]}"


# ---------------------------------------------------------------------------
# Leave Policy Helpers
# ---------------------------------------------------------------------------

def _get_or_create_policy(tenant_id: str, leave_type: str) -> LeavePolicy:
    """Return the leave policy for a type, creating from defaults if absent (no commit)."""
    policy = LeavePolicy.query.filter_by(tenant_id=tenant_id, leave_type=leave_type).first()
    if not policy:
        defaults = DEFAULT_POLICY_SETTINGS.get(leave_type, DEFAULT_POLICY_SETTINGS["other"])
        policy = LeavePolicy(tenant_id=tenant_id, leave_type=leave_type, **defaults)
        db.session.add(policy)
        db.session.flush()
    return policy


def get_all_policies() -> List[Dict]:
    """Get leave policies for all leave types, initializing defaults as needed."""
    tenant_id = get_tenant_id()
    result = []
    try:
        for lt in LEAVE_TYPES:
            policy = _get_or_create_policy(tenant_id, lt)
            result.append(policy.to_dict())
        db.session.commit()
    except Exception:
        db.session.rollback()
    return result


def upsert_leave_policy(
    leave_type: str,
    total_days: Optional[int] = None,
    is_unlimited: Optional[bool] = None,
    is_carry_forward_allowed: Optional[bool] = None,
    max_carry_forward_days: Optional[int] = None,
    allow_negative: Optional[bool] = None,
    requires_reason: Optional[bool] = None,
) -> Dict:
    """Admin: create or update a leave type policy."""
    try:
        tenant_id = get_tenant_id()
        if leave_type not in LEAVE_TYPES:
            return {"success": False, "error": f"Invalid leave type. Must be one of: {', '.join(LEAVE_TYPES)}"}

        policy = _get_or_create_policy(tenant_id, leave_type)

        if total_days is not None:
            if total_days < 0:
                return {"success": False, "error": "total_days must be >= 0"}
            policy.total_days = total_days
        if is_unlimited is not None:
            policy.is_unlimited = is_unlimited
        if is_carry_forward_allowed is not None:
            policy.is_carry_forward_allowed = is_carry_forward_allowed
        if max_carry_forward_days is not None:
            if max_carry_forward_days < 0:
                return {"success": False, "error": "max_carry_forward_days must be >= 0"}
            policy.max_carry_forward_days = max_carry_forward_days
        if allow_negative is not None:
            policy.allow_negative = allow_negative
        if requires_reason is not None:
            policy.requires_reason = requires_reason

        db.session.commit()
        return {"success": True, "policy": policy.to_dict()}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": f"Failed to update policy: {str(e)}"}


# ---------------------------------------------------------------------------
# Leave Balance Helpers
# ---------------------------------------------------------------------------

def _get_or_init_balance(
    teacher_id: str, leave_type: str, academic_year: str, tenant_id: str
) -> TeacherLeaveBalance:
    """
    Return the balance record for teacher/type/year, creating it from the policy
    if it does not exist (with carry-forward calculation). Does NOT commit.
    """
    balance = TeacherLeaveBalance.query.filter_by(
        teacher_id=teacher_id,
        leave_type=leave_type,
        academic_year=academic_year,
        tenant_id=tenant_id,
    ).first()
    if balance:
        return balance

    policy = _get_or_create_policy(tenant_id, leave_type)

    # Compute carry-forward from previous academic year
    carried_forward = 0
    if policy.is_carry_forward_allowed:
        parts = academic_year.split("-")
        prev_start = int(parts[0]) - 1
        prev_year = f"{prev_start}-{str(prev_start + 1)[2:]}"
        prev_balance = TeacherLeaveBalance.query.filter_by(
            teacher_id=teacher_id,
            leave_type=leave_type,
            academic_year=prev_year,
            tenant_id=tenant_id,
        ).first()
        if prev_balance and prev_balance.available_days > 0:
            avail = prev_balance.available_days
            if policy.max_carry_forward_days > 0:
                carried_forward = min(int(avail), policy.max_carry_forward_days)
            else:
                carried_forward = int(avail)

    balance = TeacherLeaveBalance(
        tenant_id=tenant_id,
        teacher_id=teacher_id,
        leave_type=leave_type,
        academic_year=academic_year,
        allocated_days=policy.total_days,
        used_days=0.0,
        pending_days=0.0,
        carried_forward_days=carried_forward,
    )
    db.session.add(balance)
    db.session.flush()
    return balance


def get_teacher_leave_balances(teacher_id: str, academic_year: Optional[str] = None) -> List[Dict]:
    """
    Get all leave type balances for a teacher for the given year (default: current),
    auto-initialising from policy for any missing leave types.
    """
    try:
        tenant_id = get_tenant_id()
        teacher = Teacher.query.filter_by(id=teacher_id, tenant_id=tenant_id).first()
        if not teacher:
            return []

        year = academic_year or get_current_academic_year()
        results = []
        for lt in LEAVE_TYPES:
            balance = _get_or_init_balance(teacher_id, lt, year, tenant_id)
            policy = _get_or_create_policy(tenant_id, lt)
            data = balance.to_dict()
            data["is_unlimited"] = policy.is_unlimited
            data["allow_negative"] = policy.allow_negative
            data["requires_reason"] = policy.requires_reason
            results.append(data)
        db.session.commit()
        return results
    except Exception:
        db.session.rollback()
        return []


def adjust_teacher_leave_balance(
    teacher_id: str,
    leave_type: str,
    allocated_days: int,
    notes: Optional[str],
    adjusted_by_user_id: str,
    academic_year: Optional[str] = None,
) -> Dict:
    """Admin: override the allocated_days for a teacher's leave type balance."""
    try:
        tenant_id = get_tenant_id()
        if leave_type not in LEAVE_TYPES:
            return {"success": False, "error": f"Invalid leave type. Must be one of: {', '.join(LEAVE_TYPES)}"}
        if allocated_days < 0:
            return {"success": False, "error": "allocated_days must be >= 0"}

        teacher = Teacher.query.filter_by(id=teacher_id, tenant_id=tenant_id).first()
        if not teacher:
            return {"success": False, "error": "Teacher not found"}

        year = academic_year or get_current_academic_year()
        balance = _get_or_init_balance(teacher_id, leave_type, year, tenant_id)
        balance.allocated_days = allocated_days
        if notes:
            balance.notes = notes
        balance.last_adjusted_by = adjusted_by_user_id
        balance.last_adjusted_at = datetime.utcnow()

        policy = _get_or_create_policy(tenant_id, leave_type)
        db.session.commit()

        result = balance.to_dict()
        result["is_unlimited"] = policy.is_unlimited
        result["allow_negative"] = policy.allow_negative
        return {"success": True, "balance": result}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": f"Failed to adjust balance: {str(e)}"}


# ---------------------------------------------------------------------------
# Teacher Leaves
# ---------------------------------------------------------------------------

def create_leave(
    teacher_id: str, start_date: str, end_date: str, leave_type: str, reason: Optional[str]
) -> Dict:
    """
    Create a leave request with full validation:
      1. Date format & range checks
      2. Leave type validation
      3. Holiday-only period block
      4. Overlapping active leave check
      5. Balance sufficiency check (with pending reservation)
    """
    try:
        tenant_id = get_tenant_id()

        teacher = Teacher.query.filter_by(id=teacher_id, tenant_id=tenant_id).first()
        if not teacher:
            return {"success": False, "error": "Teacher not found"}

        # -- Date validation --
        try:
            sd = datetime.strptime(start_date, "%Y-%m-%d").date()
            ed = datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError:
            return {"success": False, "error": "Dates must be in YYYY-MM-DD format"}

        if ed < sd:
            return {"success": False, "error": "end_date must be >= start_date"}

        if sd < date.today():
            return {"success": False, "error": "Cannot apply for leave with a past start date"}

        # -- Leave type validation --
        if leave_type not in LEAVE_TYPES:
            return {"success": False, "error": f"Invalid leave type. Must be one of: {', '.join(LEAVE_TYPES)}"}

        # -- Holiday overlap check --
        total_days, working_days, holiday_occurrences = get_working_days_info_for_range(sd, ed, tenant_id)
        if working_days == 0:
            holiday_names = list({o.get("name") or "Weekly Off" for o in holiday_occurrences})
            names_str = ", ".join(holiday_names[:3])
            return {
                "success": False,
                "error": (
                    f"The selected leave period consists entirely of holidays/weekly-off days "
                    f"({names_str}). No leave application is needed for this period."
                ),
                "is_holiday_conflict": True,
                "holiday_occurrences": holiday_occurrences,
            }

        # -- Overlapping active leave check --
        overlap = (
            TeacherLeave.query
            .filter_by(teacher_id=teacher_id, tenant_id=tenant_id)
            .filter(TeacherLeave.status.in_([TeacherLeave.STATUS_PENDING, TeacherLeave.STATUS_APPROVED]))
            .filter(TeacherLeave.start_date <= ed, TeacherLeave.end_date >= sd)
            .first()
        )
        if overlap:
            return {
                "success": False,
                "error": (
                    f"You already have a {overlap.status} leave request "
                    f"({overlap.start_date} → {overlap.end_date}) that overlaps with this period."
                ),
                "is_overlap_conflict": True,
                "conflicting_leave_id": overlap.id,
            }

        # -- Balance check & reservation --
        year = get_current_academic_year()
        policy = _get_or_create_policy(tenant_id, leave_type)

        if not policy.is_unlimited:
            balance = _get_or_init_balance(teacher_id, leave_type, year, tenant_id)
            if not policy.allow_negative:
                available = balance.available_days
                if available < working_days:
                    db.session.rollback()
                    return {
                        "success": False,
                        "error": (
                            f"Insufficient {leave_type} leave balance. "
                            f"Available: {available:.1f} day(s), Requested: {working_days} working day(s)."
                        ),
                        "is_balance_insufficient": True,
                        "available_days": round(available, 2),
                        "requested_days": working_days,
                    }
            # Reserve days in pending
            balance.pending_days += working_days

        leave = TeacherLeave(
            tenant_id=tenant_id,
            teacher_id=teacher_id,
            start_date=sd,
            end_date=ed,
            leave_type=leave_type,
            reason=reason,
            status=TeacherLeave.STATUS_PENDING,
            working_days=float(working_days),
            academic_year=year,
        )
        db.session.add(leave)
        db.session.commit()

        result = leave.to_dict()
        holiday_days = total_days - working_days
        if holiday_days > 0:
            holiday_names = list({o.get("name") or "Weekly Off" for o in holiday_occurrences})
            names_str = ", ".join(holiday_names[:3])
            result["warning"] = (
                f"Note: {holiday_days} day(s) in your leave range fall on holidays/weekly-offs "
                f"({names_str}). Only {working_days} working day(s) will be counted."
            )
            result["holiday_days"] = holiday_days
            result["working_days"] = working_days
        return {"success": True, "leave": result}

    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": f"Failed to create leave: {str(e)}"}


def list_leaves(teacher_id: Optional[str] = None, status: Optional[str] = None) -> List[Dict]:
    """List leave requests. Optionally filter by teacher or status."""
    tenant_id = get_tenant_id()
    query = TeacherLeave.query.filter_by(tenant_id=tenant_id)
    if teacher_id:
        query = query.filter_by(teacher_id=teacher_id)
    if status:
        query = query.filter_by(status=status)
    query = query.order_by(TeacherLeave.created_at.desc())
    return [l.to_dict() for l in query.all()]


def approve_leave(leave_id: str) -> Dict:
    """Approve a leave request and move pending days to used."""
    try:
        tenant_id = get_tenant_id()
        leave = TeacherLeave.query.filter_by(id=leave_id, tenant_id=tenant_id).first()
        if not leave:
            return {"success": False, "error": "Leave request not found"}
        if leave.status != TeacherLeave.STATUS_PENDING:
            return {"success": False, "error": f"Only pending leaves can be approved (current status: {leave.status})"}

        # Move pending → used in balance
        if leave.working_days:
            year = leave.academic_year or get_current_academic_year()
            policy = _get_or_create_policy(tenant_id, leave.leave_type)
            if not policy.is_unlimited:
                balance = TeacherLeaveBalance.query.filter_by(
                    teacher_id=leave.teacher_id,
                    leave_type=leave.leave_type,
                    academic_year=year,
                    tenant_id=tenant_id,
                ).first()
                if balance:
                    balance.pending_days = max(0.0, balance.pending_days - leave.working_days)
                    balance.used_days += leave.working_days

        leave.status = TeacherLeave.STATUS_APPROVED
        db.session.commit()
        return {"success": True, "leave": leave.to_dict()}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": f"Failed to approve leave: {str(e)}"}


def reject_leave(leave_id: str) -> Dict:
    """Reject a leave request and release the reserved pending days."""
    try:
        tenant_id = get_tenant_id()
        leave = TeacherLeave.query.filter_by(id=leave_id, tenant_id=tenant_id).first()
        if not leave:
            return {"success": False, "error": "Leave request not found"}
        if leave.status != TeacherLeave.STATUS_PENDING:
            return {"success": False, "error": f"Only pending leaves can be rejected (current status: {leave.status})"}

        # Release pending days
        if leave.working_days:
            year = leave.academic_year or get_current_academic_year()
            policy = _get_or_create_policy(tenant_id, leave.leave_type)
            if not policy.is_unlimited:
                balance = TeacherLeaveBalance.query.filter_by(
                    teacher_id=leave.teacher_id,
                    leave_type=leave.leave_type,
                    academic_year=year,
                    tenant_id=tenant_id,
                ).first()
                if balance:
                    balance.pending_days = max(0.0, balance.pending_days - leave.working_days)

        leave.status = TeacherLeave.STATUS_REJECTED
        db.session.commit()
        return {"success": True, "leave": leave.to_dict()}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": f"Failed to reject leave: {str(e)}"}


def cancel_leave(leave_id: str, teacher_id: str) -> Dict:
    """
    Cancel a pending leave request (teacher cancels their own).
    Releases the reserved pending days back to available balance.
    """
    try:
        tenant_id = get_tenant_id()
        leave = TeacherLeave.query.filter_by(id=leave_id, tenant_id=tenant_id).first()
        if not leave:
            return {"success": False, "error": "Leave request not found"}
        if leave.teacher_id != teacher_id:
            return {"success": False, "error": "You can only cancel your own leave requests"}
        if leave.status != TeacherLeave.STATUS_PENDING:
            return {"success": False, "error": "Only pending leave requests can be cancelled"}

        # Release pending days
        if leave.working_days:
            year = leave.academic_year or get_current_academic_year()
            policy = _get_or_create_policy(tenant_id, leave.leave_type)
            if not policy.is_unlimited:
                balance = TeacherLeaveBalance.query.filter_by(
                    teacher_id=teacher_id,
                    leave_type=leave.leave_type,
                    academic_year=year,
                    tenant_id=tenant_id,
                ).first()
                if balance:
                    balance.pending_days = max(0.0, balance.pending_days - leave.working_days)

        leave.status = "cancelled"
        db.session.commit()
        return {"success": True, "leave": leave.to_dict()}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": f"Failed to cancel leave: {str(e)}"}


# ---------------------------------------------------------------------------
# Teacher Workload Rules
# ---------------------------------------------------------------------------

def get_workload_rule(teacher_id: str) -> Optional[Dict]:
    """Return workload rule for a teacher."""
    tenant_id = get_tenant_id()
    rule = TeacherWorkloadRule.query.filter_by(teacher_id=teacher_id, tenant_id=tenant_id).first()
    return rule.to_dict() if rule else None


def create_workload_rule(teacher_id: str, max_periods_per_day: int, max_periods_per_week: int) -> Dict:
    """Create workload rule for a teacher."""
    try:
        tenant_id = get_tenant_id()

        teacher = Teacher.query.filter_by(id=teacher_id, tenant_id=tenant_id).first()
        if not teacher:
            return {"success": False, "error": "Teacher not found"}

        existing = TeacherWorkloadRule.query.filter_by(teacher_id=teacher_id, tenant_id=tenant_id).first()
        if existing:
            return {"success": False, "error": "Workload rule already exists. Use PUT to update."}

        if max_periods_per_day < 1 or max_periods_per_week < 1:
            return {"success": False, "error": "Period counts must be >= 1"}

        rule = TeacherWorkloadRule(
            tenant_id=tenant_id,
            teacher_id=teacher_id,
            max_periods_per_day=max_periods_per_day,
            max_periods_per_week=max_periods_per_week,
        )
        rule.save()
        return {"success": True, "workload": rule.to_dict()}

    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": f"Failed to create workload rule: {str(e)}"}


def update_workload_rule(
    teacher_id: str, max_periods_per_day: Optional[int], max_periods_per_week: Optional[int]
) -> Dict:
    """Update workload rule for a teacher. Creates one if it doesn't exist."""
    try:
        tenant_id = get_tenant_id()

        teacher = Teacher.query.filter_by(id=teacher_id, tenant_id=tenant_id).first()
        if not teacher:
            return {"success": False, "error": "Teacher not found"}

        rule = TeacherWorkloadRule.query.filter_by(teacher_id=teacher_id, tenant_id=tenant_id).first()
        if not rule:
            rule = TeacherWorkloadRule(
                tenant_id=tenant_id,
                teacher_id=teacher_id,
                max_periods_per_day=max_periods_per_day or 6,
                max_periods_per_week=max_periods_per_week or 30,
            )
        else:
            if max_periods_per_day is not None:
                if max_periods_per_day < 1:
                    return {"success": False, "error": "max_periods_per_day must be >= 1"}
                rule.max_periods_per_day = max_periods_per_day
            if max_periods_per_week is not None:
                if max_periods_per_week < 1:
                    return {"success": False, "error": "max_periods_per_week must be >= 1"}
                rule.max_periods_per_week = max_periods_per_week

        rule.save()
        return {"success": True, "workload": rule.to_dict()}

    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": f"Failed to update workload rule: {str(e)}"}
