"""
Academic Calendar Services

Wizard state, exam windows, school events, day classification, working-day
math, and the publish flow. Weekly-holiday weekday selections are synced to
recurring Holiday rows immediately (existing consumers read those); the
second/fourth-Saturday options are materialized as dated rows only at publish.
"""

from calendar import monthrange
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from flask import g

from core.database import db
from modules.academics.academic_year.models import AcademicYear
from modules.academics.backbone.models import AcademicTerm
from modules.holidays.models import Holiday

from .activity import (
    actor_user_id,
    audit_calendar_action,
    notify_calendar_change,
)
from .models import (
    AcademicCalendar,
    EXAM_TYPES,
    EVENT_TYPES,
    APPLIES_TO_VALUES,
    ExamWindow,
    SchoolEvent,
    TOTAL_WIZARD_STEPS,
    default_weekly_holidays_config,
)

SECOND_SATURDAY_NAME = "Second Saturday"
FOURTH_SATURDAY_NAME = "Fourth Saturday"

# Non-recurring holiday types that count as "public holidays" in stats;
# vacation ranges are counted separately.
PUBLIC_HOLIDAY_TYPES = ("public", "national", "school", "regional", "optional")


class CalendarValidationError(Exception):
    """Raised with a dict of field → message for 400 responses."""

    def __init__(self, errors: Dict[str, str]):
        super().__init__(str(errors))
        self.errors = errors


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------

def _get_year(academic_year_id: str) -> AcademicYear:
    year = AcademicYear.query.filter(
        AcademicYear.id == academic_year_id,
        AcademicYear.tenant_id == g.tenant_id,
    ).first()
    if not year:
        raise CalendarValidationError({"academic_year_id": "Academic year not found."})
    return year


def get_calendar(calendar_id: str) -> Optional[AcademicCalendar]:
    return AcademicCalendar.query.filter(
        AcademicCalendar.id == calendar_id,
        AcademicCalendar.tenant_id == g.tenant_id,
    ).first()


def get_calendar_for_year(academic_year_id: str) -> Optional[AcademicCalendar]:
    return AcademicCalendar.query.filter(
        AcademicCalendar.academic_year_id == academic_year_id,
        AcademicCalendar.tenant_id == g.tenant_id,
    ).first()


def get_or_create_calendar(academic_year_id: str) -> AcademicCalendar:
    """Return the calendar row for a year, creating a draft if none exists."""
    _get_year(academic_year_id)
    cal = get_calendar_for_year(academic_year_id)
    if cal:
        return cal
    cal = AcademicCalendar(
        tenant_id=g.tenant_id,
        academic_year_id=academic_year_id,
        status="draft",
        current_step=1,
        weekly_holidays_config=default_weekly_holidays_config(),
    )
    db.session.add(cal)
    db.session.commit()
    return cal


# ---------------------------------------------------------------------------
# Wizard state + weekly holidays
# ---------------------------------------------------------------------------

def update_calendar(cal: AcademicCalendar, data: Dict[str, Any]) -> AcademicCalendar:
    """Update wizard step and/or weekly-holiday config on a calendar row."""
    if "current_step" in data:
        step = data.get("current_step")
        if not isinstance(step, int) or not 1 <= step <= TOTAL_WIZARD_STEPS:
            raise CalendarValidationError(
                {"current_step": f"Must be an integer between 1 and {TOTAL_WIZARD_STEPS}."}
            )
        # The wizard never moves the server-side marker backwards; going back
        # to review an earlier step must not reset resume position.
        cal.current_step = max(cal.current_step, step)

    if "weekly_holidays_config" in data:
        cfg = _validate_weekly_config(data.get("weekly_holidays_config"))
        cal.weekly_holidays_config = cfg
        _sync_weekly_holiday_rows(cal.academic_year_id, cfg["days"])

    db.session.commit()
    return cal


def _validate_weekly_config(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise CalendarValidationError({"weekly_holidays_config": "Must be an object."})
    days = raw.get("days", [])
    if not isinstance(days, list) or any(
        not isinstance(d, int) or not 0 <= d <= 6 for d in days
    ):
        raise CalendarValidationError(
            {"weekly_holidays_config.days": "Must be a list of integers 0 (Mon) … 6 (Sun)."}
        )
    return {
        "days": sorted(set(days)),
        "second_saturday": bool(raw.get("second_saturday", False)),
        "fourth_saturday": bool(raw.get("fourth_saturday", False)),
    }


def _sync_weekly_holiday_rows(academic_year_id: str, days: List[int]) -> None:
    """Upsert recurring weekly_off Holiday rows to match the selected weekdays."""
    from modules.holidays.models import DAY_NAMES

    existing = Holiday.query.filter(
        Holiday.tenant_id == g.tenant_id,
        Holiday.academic_year_id == academic_year_id,
        Holiday.is_recurring.is_(True),
        Holiday.holiday_type == "weekly_off",
    ).all()
    existing_by_day = {h.recurring_day_of_week: h for h in existing}

    for day in days:
        if day not in existing_by_day:
            db.session.add(
                Holiday(
                    tenant_id=g.tenant_id,
                    academic_year_id=academic_year_id,
                    name=f"Weekly Holiday — {DAY_NAMES[day]}",
                    holiday_type="weekly_off",
                    is_recurring=True,
                    recurring_day_of_week=day,
                )
            )
    for day, row in existing_by_day.items():
        if day not in days:
            db.session.delete(row)


# ---------------------------------------------------------------------------
# Exam windows
# ---------------------------------------------------------------------------

def list_exam_windows(academic_year_id: str) -> List[ExamWindow]:
    return (
        ExamWindow.query.filter(
            ExamWindow.tenant_id == g.tenant_id,
            ExamWindow.academic_year_id == academic_year_id,
        )
        .order_by(ExamWindow.start_date)
        .all()
    )


def _validate_exam_payload(
    data: Dict[str, Any], year: AcademicYear, exclude_id: Optional[str] = None
) -> Dict[str, Any]:
    errors: Dict[str, str] = {}
    name = (data.get("name") or "").strip()
    if not name:
        errors["name"] = "Exam name is required."

    exam_type = (data.get("exam_type") or "other").strip()
    if exam_type not in EXAM_TYPES:
        errors["exam_type"] = f"Must be one of: {', '.join(EXAM_TYPES)}."

    start = _parse_date(data.get("start_date"))
    end = _parse_date(data.get("end_date"))
    if not start:
        errors["start_date"] = "Start date (YYYY-MM-DD) is required."
    if not end:
        errors["end_date"] = "End date (YYYY-MM-DD) is required."
    if start and end:
        if end < start:
            errors["end_date"] = "End date cannot be before start date."
        elif not (year.start_date <= start and end <= year.end_date):
            errors["start_date"] = "Exam window must fall within the academic year."

    class_ids = data.get("applicable_class_ids") or []
    if not isinstance(class_ids, list) or any(not isinstance(c, str) for c in class_ids):
        errors["applicable_class_ids"] = "Must be a list of class ids."

    if errors:
        raise CalendarValidationError(errors)

    if start and end:
        _check_exam_overlap(year.id, start, end, class_ids, exclude_id)

    return {
        "name": name,
        "exam_type": exam_type,
        "start_date": start,
        "end_date": end,
        "applicable_class_ids": class_ids,
        "description": (data.get("description") or "").strip() or None,
    }


def _check_exam_overlap(
    academic_year_id: str,
    start: date,
    end: date,
    class_ids: List[str],
    exclude_id: Optional[str],
) -> None:
    """Reject windows whose dates overlap an existing window with a shared
    class scope (an empty scope means the window applies to all classes)."""
    query = ExamWindow.query.filter(
        ExamWindow.tenant_id == g.tenant_id,
        ExamWindow.academic_year_id == academic_year_id,
        ExamWindow.start_date <= end,
        ExamWindow.end_date >= start,
    )
    if exclude_id:
        query = query.filter(ExamWindow.id != exclude_id)
    for other in query.all():
        other_ids = other.applicable_class_ids or []
        scopes_intersect = (
            not class_ids or not other_ids or bool(set(class_ids) & set(other_ids))
        )
        if scopes_intersect:
            raise CalendarValidationError(
                {
                    "start_date": (
                        f"Dates overlap existing exam window '{other.name}' "
                        f"({other.start_date} – {other.end_date})."
                    )
                }
            )


def create_exam_window(academic_year_id: str, data: Dict[str, Any]) -> ExamWindow:
    year = _get_year(academic_year_id)
    payload = _validate_exam_payload(data, year)
    window = ExamWindow(
        tenant_id=g.tenant_id,
        academic_year_id=academic_year_id,
        created_by=actor_user_id(),
        **payload,
    )
    db.session.add(window)
    db.session.flush()
    audit_calendar_action(
        "exam_window_created", "exam_window", window.id,
        f"Exam window '{window.name}' scheduled {window.start_date} – {window.end_date}",
        g.tenant_id,
    )
    notify_calendar_change(
        "Examination scheduled",
        f"{window.name}: {window.start_date} – {window.end_date}",
        g.tenant_id,
        {"exam_window_id": window.id, "academic_year_id": academic_year_id},
    )
    db.session.commit()
    return window


def update_exam_window(window_id: str, data: Dict[str, Any]) -> ExamWindow:
    window = ExamWindow.query.filter(
        ExamWindow.id == window_id, ExamWindow.tenant_id == g.tenant_id
    ).first()
    if not window:
        raise CalendarValidationError({"id": "Exam window not found."})
    year = _get_year(window.academic_year_id)
    merged = {**window.to_dict(), **data}
    payload = _validate_exam_payload(merged, year, exclude_id=window_id)
    for key, value in payload.items():
        setattr(window, key, value)
    window.updated_by = actor_user_id()
    audit_calendar_action(
        "exam_window_updated", "exam_window", window.id,
        f"Exam window '{window.name}' updated ({window.start_date} – {window.end_date})",
        g.tenant_id,
    )
    notify_calendar_change(
        "Examination updated",
        f"{window.name}: {window.start_date} – {window.end_date}",
        g.tenant_id,
        {"exam_window_id": window.id, "academic_year_id": window.academic_year_id},
    )
    db.session.commit()
    return window


def delete_exam_window(window_id: str) -> bool:
    window = ExamWindow.query.filter(
        ExamWindow.id == window_id, ExamWindow.tenant_id == g.tenant_id
    ).first()
    if not window:
        return False
    audit_calendar_action(
        "exam_window_deleted", "exam_window", window.id,
        f"Exam window '{window.name}' removed",
        g.tenant_id,
    )
    notify_calendar_change(
        "Examination removed",
        f"{window.name} ({window.start_date} – {window.end_date}) was removed",
        g.tenant_id,
        {"academic_year_id": window.academic_year_id},
    )
    db.session.delete(window)
    db.session.commit()
    return True


# ---------------------------------------------------------------------------
# School events
# ---------------------------------------------------------------------------

def list_school_events(academic_year_id: str) -> List[SchoolEvent]:
    return (
        SchoolEvent.query.filter(
            SchoolEvent.tenant_id == g.tenant_id,
            SchoolEvent.academic_year_id == academic_year_id,
        )
        .order_by(SchoolEvent.event_date)
        .all()
    )


def _validate_event_payload(
    data: Dict[str, Any], year: AcademicYear, exclude_id: Optional[str] = None
) -> Dict[str, Any]:
    errors: Dict[str, str] = {}
    name = (data.get("name") or "").strip()
    if not name:
        errors["name"] = "Event name is required."

    event_type = (data.get("event_type") or "event").strip()
    if event_type not in EVENT_TYPES:
        errors["event_type"] = f"Must be one of: {', '.join(EVENT_TYPES)}."

    event_date = _parse_date(data.get("event_date"))
    if not event_date:
        errors["event_date"] = "Event date (YYYY-MM-DD) is required."
    elif not (year.start_date <= event_date <= year.end_date):
        errors["event_date"] = "Event date must fall within the academic year."

    applies_to = (data.get("applies_to") or "entire_school").strip()
    if applies_to not in APPLIES_TO_VALUES:
        errors["applies_to"] = f"Must be one of: {', '.join(APPLIES_TO_VALUES)}."

    if errors:
        raise CalendarValidationError(errors)

    dup_query = SchoolEvent.query.filter(
        SchoolEvent.tenant_id == g.tenant_id,
        SchoolEvent.academic_year_id == year.id,
        SchoolEvent.event_date == event_date,
        db.func.lower(SchoolEvent.name) == name.lower(),
    )
    if exclude_id:
        dup_query = dup_query.filter(SchoolEvent.id != exclude_id)
    if dup_query.first():
        raise CalendarValidationError(
            {"name": f"An event named '{name}' already exists on {event_date}."}
        )

    return {
        "name": name,
        "event_type": event_type,
        "event_date": event_date,
        "applies_to": applies_to,
        "description": (data.get("description") or "").strip() or None,
    }


def create_school_event(academic_year_id: str, data: Dict[str, Any]) -> SchoolEvent:
    year = _get_year(academic_year_id)
    payload = _validate_event_payload(data, year)
    event = SchoolEvent(
        tenant_id=g.tenant_id,
        academic_year_id=academic_year_id,
        created_by=actor_user_id(),
        **payload,
    )
    db.session.add(event)
    db.session.flush()
    audit_calendar_action(
        "school_event_created", "school_event", event.id,
        f"School event '{event.name}' added on {event.event_date}",
        g.tenant_id,
    )
    notify_calendar_change(
        "School event added",
        f"{event.name} on {event.event_date}",
        g.tenant_id,
        {"school_event_id": event.id, "academic_year_id": academic_year_id},
    )
    db.session.commit()
    return event


def update_school_event(event_id: str, data: Dict[str, Any]) -> SchoolEvent:
    event = SchoolEvent.query.filter(
        SchoolEvent.id == event_id, SchoolEvent.tenant_id == g.tenant_id
    ).first()
    if not event:
        raise CalendarValidationError({"id": "School event not found."})
    year = _get_year(event.academic_year_id)
    merged = {**event.to_dict(), **data}
    payload = _validate_event_payload(merged, year, exclude_id=event_id)
    for key, value in payload.items():
        setattr(event, key, value)
    event.updated_by = actor_user_id()
    audit_calendar_action(
        "school_event_updated", "school_event", event.id,
        f"School event '{event.name}' updated ({event.event_date})",
        g.tenant_id,
    )
    notify_calendar_change(
        "School event updated",
        f"{event.name} on {event.event_date}",
        g.tenant_id,
        {"school_event_id": event.id, "academic_year_id": event.academic_year_id},
    )
    db.session.commit()
    return event


def delete_school_event(event_id: str) -> bool:
    event = SchoolEvent.query.filter(
        SchoolEvent.id == event_id, SchoolEvent.tenant_id == g.tenant_id
    ).first()
    if not event:
        return False
    audit_calendar_action(
        "school_event_deleted", "school_event", event.id,
        f"School event '{event.name}' ({event.event_date}) removed",
        g.tenant_id,
    )
    notify_calendar_change(
        "School event removed",
        f"{event.name} on {event.event_date} was removed",
        g.tenant_id,
        {"academic_year_id": event.academic_year_id},
    )
    db.session.delete(event)
    db.session.commit()
    return True


# ---------------------------------------------------------------------------
# Date math
# ---------------------------------------------------------------------------

def _parse_date(value: Any) -> Optional[date]:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def _iter_dates(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _nth_saturday(year: int, month: int, nth: int) -> Optional[date]:
    """Date of the nth Saturday of a month, or None if it doesn't exist."""
    count = 0
    for day in range(1, monthrange(year, month)[1] + 1):
        d = date(year, month, day)
        if d.weekday() == 5:
            count += 1
            if count == nth:
                return d
    return None


def _nth_saturdays_in_range(start: date, end: date, nth: int) -> List[date]:
    results: List[date] = []
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        d = _nth_saturday(cursor.year, cursor.month, nth)
        if d and start <= d <= end:
            results.append(d)
        cursor = (
            date(cursor.year + 1, 1, 1)
            if cursor.month == 12
            else date(cursor.year, cursor.month + 1, 1)
        )
    return results


def _collect_day_sets(
    year: AcademicYear, cal: AcademicCalendar
) -> Tuple[Set[date], Dict[date, List[Dict]], Dict[date, List[Dict]], Set[date], Set[date]]:
    """Build the date sets used by both the summary and the days feed.

    Returns (weekly_off_dates, holiday_map, vacation_map, exam_dates, event_dates)
    where the maps carry the row payloads for the feed.
    """
    cfg = cal.weekly_config
    weekly_days = set(cfg["days"])

    weekly_off: Set[date] = {
        d for d in _iter_dates(year.start_date, year.end_date) if d.weekday() in weekly_days
    }
    if cfg["second_saturday"]:
        weekly_off.update(_nth_saturdays_in_range(year.start_date, year.end_date, 2))
    if cfg["fourth_saturday"]:
        weekly_off.update(_nth_saturdays_in_range(year.start_date, year.end_date, 4))

    holidays = Holiday.query.filter(
        Holiday.tenant_id == g.tenant_id,
        Holiday.academic_year_id == year.id,
        Holiday.is_recurring.is_(False),
        Holiday.start_date.isnot(None),
    ).all()

    holiday_map: Dict[date, List[Dict]] = {}
    vacation_map: Dict[date, List[Dict]] = {}
    for h in holidays:
        end = h.end_date or h.start_date
        target = vacation_map if h.holiday_type == "vacation" else holiday_map
        # Materialized 2nd/4th-Saturday rows are weekly offs, not public holidays.
        if h.holiday_type == "weekly_off":
            for d in _iter_dates(h.start_date, end):
                if year.start_date <= d <= year.end_date:
                    weekly_off.add(d)
            continue
        info = {"id": h.id, "name": h.name, "holiday_type": h.holiday_type}
        for d in _iter_dates(h.start_date, end):
            if year.start_date <= d <= year.end_date:
                target.setdefault(d, []).append(info)

    exam_dates: Set[date] = set()
    for w in list_exam_windows(year.id):
        for d in _iter_dates(w.start_date, w.end_date):
            if year.start_date <= d <= year.end_date:
                exam_dates.add(d)

    event_dates: Set[date] = {
        e.event_date
        for e in list_school_events(year.id)
        if year.start_date <= e.event_date <= year.end_date
    }

    return weekly_off, holiday_map, vacation_map, exam_dates, event_dates


def compute_summary(cal: AcademicCalendar) -> Dict[str, Any]:
    """Review-step / dashboard stats. Working days = all days minus weekly
    offs, public holidays, and vacation days (overlaps counted once)."""
    year = _get_year(cal.academic_year_id)
    weekly_off, holiday_map, vacation_map, exam_dates, _ = _collect_day_sets(year, cal)

    total_days = (year.end_date - year.start_date).days + 1
    holiday_dates = set(holiday_map.keys())
    vacation_dates = set(vacation_map.keys())
    non_working = weekly_off | holiday_dates | vacation_dates

    terms = _list_terms(year.id)
    events = list_school_events(year.id)
    exam_windows = list_exam_windows(year.id)

    events_by_type: Dict[str, int] = {}
    for e in events:
        events_by_type[e.event_type] = events_by_type.get(e.event_type, 0) + 1

    return {
        "academic_year": year.to_dict(),
        "total_days": total_days,
        "working_days": total_days - len(non_working),
        "weekly_holiday_days": len(weekly_off),
        "public_holiday_days": len(holiday_dates),
        "vacation_days": len(vacation_dates),
        "exam_days": len(exam_dates),
        "semester_count": len(terms),
        "exam_window_count": len(exam_windows),
        "event_count": len(events),
        "events_by_type": events_by_type,
        "weekly_holidays_config": cal.weekly_config,
    }


def _list_terms(academic_year_id: str) -> List[AcademicTerm]:
    return (
        AcademicTerm.query.filter(
            AcademicTerm.tenant_id == g.tenant_id,
            AcademicTerm.academic_year_id == academic_year_id,
            AcademicTerm.deleted_at.is_(None),
        )
        .order_by(AcademicTerm.sequence)
        .all()
    )


def get_days_feed(cal: AcademicCalendar) -> List[Dict[str, Any]]:
    """Per-day classification for the calendar view, covering the whole year.

    day_type priority: vacation > public_holiday > weekly_holiday > working.
    Exams, events and semester boundaries are markers, not day types (they
    don't stop a day being a working day).
    """
    year = _get_year(cal.academic_year_id)
    weekly_off, holiday_map, vacation_map, exam_dates, event_dates = _collect_day_sets(
        year, cal
    )

    semester_starts: Dict[date, str] = {}
    semester_ends: Dict[date, str] = {}
    for term in _list_terms(year.id):
        semester_starts[term.start_date] = term.name
        semester_ends[term.end_date] = term.name

    feed: List[Dict[str, Any]] = []
    for d in _iter_dates(year.start_date, year.end_date):
        if d in vacation_map:
            day_type = "vacation"
        elif d in holiday_map:
            day_type = "public_holiday"
        elif d in weekly_off:
            day_type = "weekly_holiday"
        else:
            day_type = "working"
        feed.append(
            {
                "date": d.isoformat(),
                "day_type": day_type,
                "has_exam": d in exam_dates,
                "has_event": d in event_dates,
                "semester_start": semester_starts.get(d),
                "semester_end": semester_ends.get(d),
                "holidays": holiday_map.get(d, []) + vacation_map.get(d, []),
            }
        )
    return feed


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------

def _validate_terms_for_publish(year: AcademicYear) -> List[str]:
    problems: List[str] = []
    terms = (
        AcademicTerm.query.filter(
            AcademicTerm.tenant_id == g.tenant_id,
            AcademicTerm.academic_year_id == year.id,
            AcademicTerm.deleted_at.is_(None),
        )
        .order_by(AcademicTerm.start_date)
        .all()
    )
    for term in terms:
        if term.start_date < year.start_date or term.end_date > year.end_date:
            problems.append(
                f"Semester '{term.name}' falls outside the academic year dates."
            )
    for first, second in zip(terms, terms[1:]):
        if second.start_date <= first.end_date:
            problems.append(
                f"Semesters '{first.name}' and '{second.name}' have overlapping dates."
            )
    return problems


def _validate_vacations_for_publish(year: AcademicYear) -> List[str]:
    problems: List[str] = []
    vacations = (
        Holiday.query.filter(
            Holiday.tenant_id == g.tenant_id,
            Holiday.academic_year_id == year.id,
            Holiday.holiday_type == "vacation",
            Holiday.is_recurring.is_(False),
        )
        .order_by(Holiday.start_date)
        .all()
    )
    for v in vacations:
        end = v.end_date or v.start_date
        if v.start_date < year.start_date or end > year.end_date:
            problems.append(f"Vacation '{v.name}' falls outside the academic year dates.")
    for first, second in zip(vacations, vacations[1:]):
        first_end = first.end_date or first.start_date
        if second.start_date <= first_end:
            problems.append(
                f"Vacations '{first.name}' and '{second.name}' have overlapping dates."
            )
    return problems


def _materialize_nth_saturdays(year: AcademicYear, cal: AcademicCalendar) -> None:
    """Create dated weekly_off Holiday rows for 2nd/4th Saturdays so existing
    consumers (attendance, mobile) observe them. Idempotent: previously
    materialized rows for this year are replaced."""
    Holiday.query.filter(
        Holiday.tenant_id == g.tenant_id,
        Holiday.academic_year_id == year.id,
        Holiday.holiday_type == "weekly_off",
        Holiday.is_recurring.is_(False),
        Holiday.name.in_([SECOND_SATURDAY_NAME, FOURTH_SATURDAY_NAME]),
    ).delete(synchronize_session=False)

    cfg = cal.weekly_config
    for flag, nth, name in (
        ("second_saturday", 2, SECOND_SATURDAY_NAME),
        ("fourth_saturday", 4, FOURTH_SATURDAY_NAME),
    ):
        if not cfg[flag]:
            continue
        for d in _nth_saturdays_in_range(year.start_date, year.end_date, nth):
            db.session.add(
                Holiday(
                    tenant_id=g.tenant_id,
                    academic_year_id=year.id,
                    name=name,
                    holiday_type="weekly_off",
                    start_date=d,
                    end_date=d,
                )
            )


def publish_calendar(cal: AcademicCalendar, user_id: Optional[str]) -> Dict[str, Any]:
    """Validate every wizard section, materialize generated rows, snapshot the
    summary, and mark the calendar published."""
    year = _get_year(cal.academic_year_id)

    problems = _validate_terms_for_publish(year) + _validate_vacations_for_publish(year)
    if problems:
        raise CalendarValidationError({"publish": " ".join(problems)})

    _materialize_nth_saturdays(year, cal)

    from datetime import datetime, timezone

    cal.status = "published"
    cal.current_step = TOTAL_WIZARD_STEPS
    cal.published_at = datetime.now(timezone.utc)
    cal.published_by = user_id
    db.session.flush()

    summary = compute_summary(cal)
    cal.published_summary = summary
    audit_calendar_action(
        "calendar_published", "academic_calendar", cal.id,
        f"Academic calendar for {year.name} published "
        f"({summary['working_days']} working days)",
        g.tenant_id,
        meta={"working_days": summary["working_days"]},
    )
    notify_calendar_change(
        "Academic calendar published",
        f"The academic calendar for {year.name} is now active.",
        g.tenant_id,
        {"academic_year_id": year.id},
    )
    db.session.commit()
    return summary
