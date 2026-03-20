"""
Timetable Services

Business logic for timetable slot CRUD and config. All operations are tenant-scoped.
"""

from datetime import time
from typing import Dict, List, Optional, Tuple

from sqlalchemy.exc import IntegrityError

from backend.core.database import db
from backend.core.tenant import get_tenant_id

from .models import TimetableSlot, TimetableConfig, DEFAULT_BREAKS_JSON


def _parse_time(s: str) -> Optional[time]:
    """Parse 'HH:MM' or 'HH:MM:SS' string to time object."""
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    if not s:
        return None
    parts = s.split(":")
    if len(parts) >= 2:
        try:
            h, m = int(parts[0]), int(parts[1])
            sec = int(parts[2]) if len(parts) >= 3 else 0
            return time(hour=h, minute=m, second=sec)
        except (ValueError, IndexError):
            pass
    return None


def create_slot(data: Dict, tenant_id: str) -> Dict:
    """
    Create a new timetable slot (tenant-scoped).

    Args:
        data: Dict with class_id, subject_id, teacher_id, day_of_week, period_number,
              start_time, end_time, room (optional)
        tenant_id: Tenant ID for scoping

    Returns:
        Dict with success status and slot data or error
    """
    try:
        if not tenant_id:
            return {"success": False, "error": "Tenant context is required"}

        from backend.modules.classes.models import Class
        from backend.modules.subjects.models import Subject
        from backend.modules.teachers.models import Teacher

        class_id = data.get("class_id")
        subject_id = data.get("subject_id")
        teacher_id = data.get("teacher_id")
        try:
            day_of_week = int(data.get("day_of_week")) if data.get("day_of_week") is not None else None
        except (TypeError, ValueError):
            day_of_week = None
        try:
            period_number = int(data.get("period_number")) if data.get("period_number") is not None else None
        except (TypeError, ValueError):
            period_number = None
        start_time_str = data.get("start_time")
        end_time_str = data.get("end_time")

        if not class_id:
            return {"success": False, "error": "class_id is required"}
        if not subject_id:
            return {"success": False, "error": "subject_id is required"}
        if not teacher_id:
            return {"success": False, "error": "teacher_id is required"}
        if day_of_week is None:
            return {"success": False, "error": "day_of_week is required"}
        if period_number is None:
            return {"success": False, "error": "period_number is required"}

        try:
            day_of_week = int(day_of_week)
            period_number = int(period_number)
        except (TypeError, ValueError):
            return {"success": False, "error": "day_of_week and period_number must be integers"}
        try:
            day_of_week = int(day_of_week)
            period_number = int(period_number)
        except (TypeError, ValueError):
            return {"success": False, "error": "day_of_week and period_number must be integers"}
        if not start_time_str:
            return {"success": False, "error": "start_time is required"}
        if not end_time_str:
            return {"success": False, "error": "end_time is required"}

        # Validate class exists
        cls = Class.query.filter_by(id=class_id, tenant_id=tenant_id).first()
        if not cls:
            return {"success": False, "error": "Class not found"}

        # Validate subject exists
        subj = Subject.query.filter_by(id=subject_id, tenant_id=tenant_id).first()
        if not subj:
            return {"success": False, "error": "Subject not found"}

        # Validate teacher exists
        teacher = Teacher.query.filter_by(id=teacher_id, tenant_id=tenant_id).first()
        if not teacher:
            return {"success": False, "error": "Teacher not found"}

        start_t = _parse_time(start_time_str)
        end_t = _parse_time(end_time_str)
        if not start_t:
            return {"success": False, "error": "Invalid start_time format (use HH:MM or HH:MM:SS)"}
        if not end_t:
            return {"success": False, "error": "Invalid end_time format (use HH:MM or HH:MM:SS)"}

        try:
            day_of_week = int(day_of_week)
            period_number = int(period_number)
        except (TypeError, ValueError):
            return {"success": False, "error": "day_of_week and period_number must be integers"}

        try:
            day_of_week = int(day_of_week)
            period_number = int(period_number)
        except (TypeError, ValueError):
            return {"success": False, "error": "day_of_week and period_number must be integers"}

        try:
            day_of_week = int(day_of_week)
            period_number = int(period_number)
        except (TypeError, ValueError):
            return {"success": False, "error": "day_of_week and period_number must be integers"}

        if day_of_week < 0 or day_of_week > 6:
            return {"success": False, "error": "day_of_week must be 0-6 (0=Monday, 6=Sunday)"}
        if period_number < 1:
            return {"success": False, "error": "period_number must be >= 1"}

        # Check unique (class_id, day_of_week, period_number)
        existing = TimetableSlot.query.filter_by(
            tenant_id=tenant_id,
            class_id=class_id,
            day_of_week=day_of_week,
            period_number=period_number,
        ).first()
        if existing:
            return {"success": False, "error": "Slot already exists for this class, day, and period"}

        slot = TimetableSlot(
            tenant_id=tenant_id,
            class_id=class_id,
            subject_id=subject_id,
            teacher_id=teacher_id,
            day_of_week=day_of_week,
            period_number=period_number,
            start_time=start_t,
            end_time=end_t,
            room=(data.get("room") or "").strip() or None,
        )
        slot.save()

        return {"success": True, "slot": slot.to_dict()}
    except IntegrityError as e:
        db.session.rollback()
        error_msg = str(e.orig) if hasattr(e, "orig") else str(e)
        if "uq_timetable_slots" in error_msg or "unique" in error_msg.lower():
            return {"success": False, "error": "Slot already exists for this class, day, and period"}
        return {"success": False, "error": "Database constraint violation"}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}


def get_slots_by_class(class_id: str, tenant_id: str) -> List[Dict]:
    """
    Get all timetable slots for a class.

    Args:
        class_id: Class UUID
        tenant_id: Tenant ID for scoping

    Returns:
        List of slot dicts, ordered by day_of_week, period_number
    """
    slots = (
        TimetableSlot.query.filter_by(tenant_id=tenant_id, class_id=class_id)
        .order_by(TimetableSlot.day_of_week, TimetableSlot.period_number)
        .all()
    )
    return [s.to_dict() for s in slots]


def get_slot_by_id(slot_id: str, tenant_id: str) -> Optional[Dict]:
    """
    Get a timetable slot by ID (tenant-scoped).

    Args:
        slot_id: Slot UUID
        tenant_id: Tenant ID for scoping

    Returns:
        Slot dict or None if not found
    """
    slot = TimetableSlot.query.filter_by(id=slot_id, tenant_id=tenant_id).first()
    return slot.to_dict() if slot else None


def update_slot(slot_id: str, data: Dict, tenant_id: str) -> Dict:
    """
    Update a timetable slot (tenant-scoped).

    Args:
        slot_id: Slot UUID
        data: Dict with optional class_id, subject_id, teacher_id, day_of_week,
              period_number, start_time, end_time, room
        tenant_id: Tenant ID for scoping

    Returns:
        Dict with success status and updated slot data or error
    """
    try:
        slot = TimetableSlot.query.filter_by(id=slot_id, tenant_id=tenant_id).first()
        if not slot:
            return {"success": False, "error": "Timetable slot not found"}

        from backend.modules.classes.models import Class
        from backend.modules.subjects.models import Subject
        from backend.modules.teachers.models import Teacher

        if "class_id" in data and data["class_id"] is not None:
            cls = Class.query.filter_by(id=data["class_id"], tenant_id=tenant_id).first()
            if not cls:
                return {"success": False, "error": "Class not found"}
            slot.class_id = data["class_id"]

        if "subject_id" in data and data["subject_id"] is not None:
            subj = Subject.query.filter_by(id=data["subject_id"], tenant_id=tenant_id).first()
            if not subj:
                return {"success": False, "error": "Subject not found"}
            slot.subject_id = data["subject_id"]

        if "teacher_id" in data and data["teacher_id"] is not None:
            teacher = Teacher.query.filter_by(id=data["teacher_id"], tenant_id=tenant_id).first()
            if not teacher:
                return {"success": False, "error": "Teacher not found"}
            slot.teacher_id = data["teacher_id"]

        if "day_of_week" in data and data["day_of_week"] is not None:
            d = data["day_of_week"]
            if d < 0 or d > 6:
                return {"success": False, "error": "day_of_week must be 0-6"}
            slot.day_of_week = d

        if "period_number" in data and data["period_number"] is not None:
            p = data["period_number"]
            if p < 1:
                return {"success": False, "error": "period_number must be >= 1"}
            slot.period_number = p

        if "start_time" in data and data["start_time"] is not None:
            t = _parse_time(data["start_time"])
            if not t:
                return {"success": False, "error": "Invalid start_time format"}
            slot.start_time = t

        if "end_time" in data and data["end_time"] is not None:
            t = _parse_time(data["end_time"])
            if not t:
                return {"success": False, "error": "Invalid end_time format"}
            slot.end_time = t

        if "room" in data:
            slot.room = (data["room"] or "").strip() or None

        # Check unique when changing class/day/period
        class_id = slot.class_id
        day = slot.day_of_week
        period = slot.period_number
        existing = TimetableSlot.query.filter(
            TimetableSlot.tenant_id == tenant_id,
            TimetableSlot.class_id == class_id,
            TimetableSlot.day_of_week == day,
            TimetableSlot.period_number == period,
            TimetableSlot.id != slot_id,
        ).first()
        if existing:
            return {"success": False, "error": "Slot already exists for this class, day, and period"}

        slot.save()
        return {"success": True, "slot": slot.to_dict()}
    except IntegrityError as e:
        db.session.rollback()
        error_msg = str(e.orig) if hasattr(e, "orig") else str(e)
        if "uq_timetable_slots" in error_msg or "unique" in error_msg.lower():
            return {"success": False, "error": "Slot already exists for this class, day, and period"}
        return {"success": False, "error": "Database constraint violation"}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}


def delete_slot(slot_id: str, tenant_id: str) -> Dict:
    """
    Delete a timetable slot (tenant-scoped).

    Args:
        slot_id: Slot UUID
        tenant_id: Tenant ID for scoping

    Returns:
        Dict with success status or error
    """
    try:
        slot = TimetableSlot.query.filter_by(id=slot_id, tenant_id=tenant_id).first()
        if not slot:
            return {"success": False, "error": "Timetable slot not found"}

        slot.delete()
        return {"success": True, "message": "Timetable slot deleted successfully"}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}


def get_timetable_config(tenant_id: str) -> Dict:
    """Get timetable config for tenant. Creates default if none exists."""
    cfg = TimetableConfig.query.filter_by(tenant_id=tenant_id).first()
    if cfg:
        return {"success": True, "config": cfg.to_dict()}
    # Create default
    cfg = TimetableConfig(
        tenant_id=tenant_id,
        general_class_duration_minutes=45,
        first_class_duration_minutes=50,
        gap_between_classes_minutes=5,
        periods_per_day=8,
        school_start_time=time(8, 0),
        breaks_json=DEFAULT_BREAKS_JSON,
    )
    db.session.add(cfg)
    db.session.commit()
    return {"success": True, "config": cfg.to_dict()}


def upsert_timetable_config(tenant_id: str, data: Dict) -> Dict:
    """Create or update timetable config for tenant."""
    cfg = TimetableConfig.query.filter_by(tenant_id=tenant_id).first()
    if not cfg:
        cfg = TimetableConfig(tenant_id=tenant_id)
        db.session.add(cfg)
        db.session.flush()

    if "general_class_duration_minutes" in data and data["general_class_duration_minutes"] is not None:
        cfg.general_class_duration_minutes = int(data["general_class_duration_minutes"])
    if "first_class_duration_minutes" in data and data["first_class_duration_minutes"] is not None:
        cfg.first_class_duration_minutes = int(data["first_class_duration_minutes"])
    if "gap_between_classes_minutes" in data and data["gap_between_classes_minutes"] is not None:
        cfg.gap_between_classes_minutes = int(data["gap_between_classes_minutes"])
    if "periods_per_day" in data and data["periods_per_day"] is not None:
        cfg.periods_per_day = int(data["periods_per_day"])
    if "school_start_time" in data and data["school_start_time"] is not None:
        cfg.school_start_time = _parse_time(data["school_start_time"]) or time(8, 0)
    if "breaks" in data and data["breaks"] is not None:
        cfg.breaks_json = data["breaks"]

    db.session.commit()
    return {"success": True, "config": cfg.to_dict()}


# ---------------------------------------------------------------------------
# Period-time resolution (reuses generator's schedule logic)
# ---------------------------------------------------------------------------

def _get_period_times(period_number: int, tenant_id: str) -> Tuple[time, time]:
    """Look up (start_time, end_time) for a period from TimetableConfig."""
    from .generator import _compute_period_schedule, _period_times

    config = TimetableConfig.query.filter_by(tenant_id=tenant_id).first()
    schedule, _ppd = _compute_period_schedule(config)
    return _period_times(period_number, schedule)


# ---------------------------------------------------------------------------
# Drag-and-drop editing helpers
# ---------------------------------------------------------------------------

def move_slot(slot_id: str, day: int, period: int, tenant_id: str) -> Dict:
    """
    Move a timetable slot to a new (day, period) position.

    1. Load slot
    2. Run conflict checks at new position (excluding self)
    3. If conflicts → return them without mutating
    4. Update slot and recompute start/end times
    """
    from . import validators

    slot = TimetableSlot.query.filter_by(id=slot_id, tenant_id=tenant_id).first()
    if not slot:
        return {"success": False, "error": "Timetable slot not found"}

    if day < 0 or day > 6:
        return {"success": False, "error": "day must be 0-6 (0=Monday, 6=Sunday)"}
    if period < 1:
        return {"success": False, "error": "period must be >= 1"}

    if slot.day_of_week == day and slot.period_number == period:
        return {"success": True, "slot": slot.to_dict()}

    collision = TimetableSlot.query.filter(
        TimetableSlot.tenant_id == tenant_id,
        TimetableSlot.class_id == slot.class_id,
        TimetableSlot.day_of_week == day,
        TimetableSlot.period_number == period,
        TimetableSlot.id != slot_id,
    ).first()
    if collision:
        return {
            "success": False,
            "conflicts": [{
                "type": "slot_occupied",
                "message": "Another slot already occupies this position in the class timetable",
                "day": day,
                "period": period,
            }],
        }

    check = validators.check_slot_conflicts(
        class_id=slot.class_id,
        teacher_id=slot.teacher_id,
        subject_id=slot.subject_id,
        day=day,
        period=period,
        tenant_id=tenant_id,
        exclude_slot_id=slot_id,
    )
    if check["has_conflict"]:
        return {"success": False, "conflicts": check["conflicts"]}

    start_t, end_t = _get_period_times(period, tenant_id)
    slot.day_of_week = day
    slot.period_number = period
    slot.start_time = start_t
    slot.end_time = end_t

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return {
            "success": False,
            "conflicts": [{
                "type": "slot_occupied",
                "message": "Another slot already occupies this position in the class timetable",
                "day": day,
                "period": period,
            }],
        }

    return {"success": True, "slot": slot.to_dict()}


def swap_slots(slot_a_id: str, slot_b_id: str, tenant_id: str) -> Dict:
    """
    Swap the (day, period) positions of two timetable slots.

    1. Load both slots
    2. Simulate swapped positions
    3. Run conflict checks for both at their new positions
    4. If valid → perform the swap atomically
    """
    from . import validators

    slot_a = TimetableSlot.query.filter_by(id=slot_a_id, tenant_id=tenant_id).first()
    slot_b = TimetableSlot.query.filter_by(id=slot_b_id, tenant_id=tenant_id).first()

    if not slot_a:
        return {"success": False, "error": "Slot A not found"}
    if not slot_b:
        return {"success": False, "error": "Slot B not found"}

    if slot_a_id == slot_b_id:
        return {"success": True, "slot_a": slot_a.to_dict(), "slot_b": slot_b.to_dict()}

    new_a_day, new_a_period = slot_b.day_of_week, slot_b.period_number
    new_b_day, new_b_period = slot_a.day_of_week, slot_a.period_number

    conflicts: List[Dict] = []

    # Validate slot A moving to B's position.
    # Exclude both slots: A is leaving its old position, B is leaving its position too.
    check_a = validators.check_slot_conflicts(
        class_id=slot_a.class_id,
        teacher_id=slot_a.teacher_id,
        subject_id=slot_a.subject_id,
        day=new_a_day,
        period=new_a_period,
        tenant_id=tenant_id,
        exclude_slot_id=slot_a_id,
    )
    # If slots are in different classes, B's old position might collide with
    # another slot in A's class.  For same-class swaps the unique constraint
    # is safe because both slots participate.
    if slot_a.class_id != slot_b.class_id:
        col = TimetableSlot.query.filter(
            TimetableSlot.tenant_id == tenant_id,
            TimetableSlot.class_id == slot_a.class_id,
            TimetableSlot.day_of_week == new_a_day,
            TimetableSlot.period_number == new_a_period,
            TimetableSlot.id != slot_a_id,
        ).first()
        if col:
            check_a["has_conflict"] = True
            check_a["conflicts"].append({
                "type": "slot_occupied",
                "message": "Target position already occupied in slot A's class timetable",
                "day": new_a_day,
                "period": new_a_period,
            })

    if check_a["has_conflict"]:
        for c in check_a["conflicts"]:
            c["slot"] = "A"
        conflicts.extend(check_a["conflicts"])

    check_b = validators.check_slot_conflicts(
        class_id=slot_b.class_id,
        teacher_id=slot_b.teacher_id,
        subject_id=slot_b.subject_id,
        day=new_b_day,
        period=new_b_period,
        tenant_id=tenant_id,
        exclude_slot_id=slot_b_id,
    )
    if slot_a.class_id != slot_b.class_id:
        col = TimetableSlot.query.filter(
            TimetableSlot.tenant_id == tenant_id,
            TimetableSlot.class_id == slot_b.class_id,
            TimetableSlot.day_of_week == new_b_day,
            TimetableSlot.period_number == new_b_period,
            TimetableSlot.id != slot_b_id,
        ).first()
        if col:
            check_b["has_conflict"] = True
            check_b["conflicts"].append({
                "type": "slot_occupied",
                "message": "Target position already occupied in slot B's class timetable",
                "day": new_b_day,
                "period": new_b_period,
            })

    if check_b["has_conflict"]:
        for c in check_b["conflicts"]:
            c["slot"] = "B"
        conflicts.extend(check_b["conflicts"])

    if conflicts:
        return {"success": False, "conflicts": conflicts}

    # Perform the swap — use a sentinel to avoid unique-constraint clash
    # when both slots share the same class_id.
    a_start, a_end = _get_period_times(new_a_period, tenant_id)
    b_start, b_end = _get_period_times(new_b_period, tenant_id)

    if slot_a.class_id == slot_b.class_id:
        # Temporarily move A to an impossible period to avoid the unique
        # constraint (class_id, day_of_week, period_number) mid-swap.
        slot_a.day_of_week = -1
        slot_a.period_number = -1
        db.session.flush()

        slot_b.day_of_week = new_b_day
        slot_b.period_number = new_b_period
        slot_b.start_time = b_start
        slot_b.end_time = b_end
        db.session.flush()

        slot_a.day_of_week = new_a_day
        slot_a.period_number = new_a_period
        slot_a.start_time = a_start
        slot_a.end_time = a_end
    else:
        slot_a.day_of_week = new_a_day
        slot_a.period_number = new_a_period
        slot_a.start_time = a_start
        slot_a.end_time = a_end
        slot_b.day_of_week = new_b_day
        slot_b.period_number = new_b_period
        slot_b.start_time = b_start
        slot_b.end_time = b_end

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return {
            "success": False,
            "conflicts": [{
                "type": "slot_occupied",
                "message": "Swap would violate a unique-slot constraint",
                "day": new_a_day,
                "period": new_a_period,
            }],
        }

    return {
        "success": True,
        "slot_a": slot_a.to_dict(),
        "slot_b": slot_b.to_dict(),
    }
