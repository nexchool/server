"""My weekly timetable — a read view over the timetable a school publishes.

This module owns no timetable data. The timetable is `TimetableVersion` +
`TimetableEntry` (migration 023, ADR-014's neighbourhood); the parallel
`timetable_slots` table this module used to own was deleted in migration 096
along with its second generator, editor and config.

What is left is the one thing that surface had which the class-centric API
does not: a signed-in teacher or student asking for *their own* week. A class
timetable is read per class; a person's week is assembled across classes and
resolved through the bell schedule that gives each period its clock time.
"""

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import joinedload

from core.database import db
from core.school_time import school_today
from modules.academics.backbone.models import (
    BellSchedulePeriod,
    TimetableEntry,
    TimetableVersion,
)


class TimetableNotFoundError(Exception):
    """No published timetable exists for the requested academic year."""


class StudentNotEnrolledError(Exception):
    """The student holds no class for the requested academic year."""


# The weekly payload speaks 0=Monday..6=Sunday; timetable entries are stored
# ISO (1=Monday..7=Sunday). One place converts, so no caller has to know.
def _iso_to_payload_day(day_of_week: int) -> int:
    return day_of_week - 1


def _normalize_to_iso_monday(d: date) -> date:
    """Return the ISO Monday of the week containing `d`."""
    return d - timedelta(days=d.isoweekday() - 1)


def _resolve_teacher_for_user(tenant_id: str, user_id: Any):
    """Return the Teacher row for the given user, or None if not a teacher."""
    from modules.teachers.models import Teacher

    return Teacher.query.filter_by(tenant_id=tenant_id, user_id=user_id).first()


def _resolve_student_for_user(tenant_id: str, user_id: Any):
    """Return the Student row for the given user, or None if not a student."""
    from modules.students.models import Student

    return Student.query.filter_by(tenant_id=tenant_id, user_id=user_id).first()


def _resolve_academic_year(tenant_id: str, academic_year_id: Optional[str]):
    """Return the AcademicYear for the tenant (explicit ID or active one)."""
    from modules.academics.academic_year.models import AcademicYear

    if academic_year_id:
        return AcademicYear.query.filter_by(
            tenant_id=tenant_id, id=academic_year_id
        ).first()
    return (
        AcademicYear.query
        .filter_by(tenant_id=tenant_id, is_active=True)
        .order_by(AcademicYear.start_date.desc())
        .first()
    )


def _active_versions_for_year(tenant_id: str, academic_year_id: str):
    """The published timetable of every class in this academic year.

    Only active versions: a draft is what a school is still working on, and
    nobody's personal week should show it.
    """
    from modules.classes.models import Class

    return (
        db.session.query(TimetableVersion, Class)
        .join(Class, Class.id == TimetableVersion.class_id)
        .filter(
            TimetableVersion.tenant_id == tenant_id,
            TimetableVersion.status == "active",
            Class.academic_year_id == academic_year_id,
        )
        .all()
    )


def _entries_for_versions(version_ids: List[str]) -> List[TimetableEntry]:
    if not version_ids:
        return []
    from modules.teachers.models import Teacher
    from modules.classes.models import ClassSubject
    from modules.people.employment import Staff

    return (
        TimetableEntry.query
        .options(
            joinedload(TimetableEntry.class_subject).joinedload(ClassSubject.subject_ref),
            joinedload(TimetableEntry.teacher)
            .joinedload(Teacher.staff)
            .joinedload(Staff.person),
        )
        .filter(TimetableEntry.timetable_version_id.in_(version_ids))
        .order_by(TimetableEntry.day_of_week, TimetableEntry.period_number)
        .all()
    )


def _period_times_by_schedule(bell_schedule_ids: List[str]) -> Dict[tuple, Any]:
    """(bell_schedule_id, period_number) -> the period, read in one query.

    A person's week can span classes on different bell schedules, so the
    times cannot come from a single schedule.
    """
    ids = [b for b in set(bell_schedule_ids) if b]
    if not ids:
        return {}
    rows = (
        BellSchedulePeriod.query
        .filter(BellSchedulePeriod.bell_schedule_id.in_(ids))
        .all()
    )
    return {(r.bell_schedule_id, r.period_number): r for r in rows}


def _teacher_display_name(teacher_row) -> Optional[str]:
    """The teacher's name, from the Person (ADR-001) — not their login."""
    if teacher_row is None:
        return None
    staff = getattr(teacher_row, "staff", None)
    person = getattr(staff, "person", None) if staff is not None else None
    return getattr(person, "full_name", None) if person is not None else None


def _fmt(t) -> Optional[str]:
    return t.strftime("%H:%M") if t is not None else None


def _build_weekly_response(
    ay,
    week_start: date,
    week_end: date,
    rows: List[tuple],
) -> Dict:
    """Bucket periods into 7 days (0..6, 0=Monday). Each day carries its date.

    ``rows`` is (entry, class, period) — the period may be None when the
    class's bell schedule does not describe that period number, which is
    exactly the state the class timetable flags as a conflict.
    """
    days_by_dow: Dict[int, List[Dict]] = {dow: [] for dow in range(0, 7)}

    for entry, cls, period in rows:
        dow = _iso_to_payload_day(entry.day_of_week)
        if dow < 0 or dow > 6:
            continue
        class_subject = entry.class_subject
        subject = class_subject.subject_ref if class_subject else None
        teacher = entry.teacher
        days_by_dow[dow].append({
            "id": str(entry.id),
            "period_number": entry.period_number,
            "start_time": _fmt(period.starts_at) if period else None,
            "end_time": _fmt(period.ends_at) if period else None,
            "subject": (
                {"id": str(subject.id), "name": subject.name}
                if subject is not None else None
            ),
            "class": (
                {"id": str(cls.id), "name": getattr(cls, "name", None)}
                if cls is not None else None
            ),
            "teacher": (
                {"id": str(teacher.id), "name": _teacher_display_name(teacher)}
                if teacher is not None else None
            ),
            "room": entry.room,
        })

    days = []
    for dow in range(0, 7):
        day_date = week_start + timedelta(days=dow)
        days.append({
            "day_of_week": dow,
            "date": day_date.isoformat(),
            "periods": sorted(
                days_by_dow[dow],
                key=lambda x: (x["start_time"] or "", x.get("period_number") or 0),
            ),
        })

    return {
        "academic_year": {"id": str(ay.id), "name": ay.name},
        "week_start_date": week_start.isoformat(),
        "week_end_date": week_end.isoformat(),
        "days": days,
    }


def _week_rows(
    tenant_id: str,
    academic_year_id: str,
    *,
    teacher_id: Optional[str] = None,
    class_id: Optional[str] = None,
) -> tuple:
    """(rows, published) for one person's week.

    ``published`` distinguishes "the school has published nothing for this
    year" from "there is a timetable and this person simply has no periods
    in it" — the mobile client renders those differently.
    """
    versions = _active_versions_for_year(tenant_id, academic_year_id)
    if class_id is not None:
        versions = [(v, c) for v, c in versions if v.class_id == class_id]
    published = bool(_active_versions_for_year(tenant_id, academic_year_id))

    class_by_version = {v.id: c for v, c in versions}
    schedule_by_version = {v.id: v.bell_schedule_id for v, _ in versions}

    entries = _entries_for_versions(list(class_by_version.keys()))
    if teacher_id is not None:
        entries = [e for e in entries if e.teacher_id == teacher_id]

    periods = _period_times_by_schedule(list(schedule_by_version.values()))

    rows = []
    for entry in entries:
        version_id = entry.timetable_version_id
        bell_schedule_id = schedule_by_version.get(version_id)
        rows.append((
            entry,
            class_by_version.get(version_id),
            periods.get((bell_schedule_id, entry.period_number)),
        ))
    return rows, published


def get_teacher_weekly_timetable(
    *,
    tenant_id: str,
    teacher_user_id: Any,
    week_start_date: Optional[date] = None,
    academic_year_id: Optional[str] = None,
) -> Optional[Dict]:
    """Return the weekly timetable for the authenticated teacher.

    Returns None when the caller's user has no Teacher row (route → 403).
    Raises TimetableNotFoundError when no published timetable exists for the AY.
    """
    teacher = _resolve_teacher_for_user(tenant_id, teacher_user_id)
    if teacher is None:
        return None

    ay = _resolve_academic_year(tenant_id, academic_year_id)
    if ay is None:
        raise TimetableNotFoundError("No active academic year")

    week_start = _normalize_to_iso_monday(week_start_date or school_today())
    week_end = week_start + timedelta(days=6)

    rows, published = _week_rows(tenant_id, ay.id, teacher_id=teacher.id)
    if not rows and not published:
        raise TimetableNotFoundError(
            "No published timetable for this academic year"
        )

    return _build_weekly_response(ay, week_start, week_end, rows)


def get_student_weekly_timetable(
    *,
    tenant_id: str,
    student_user_id: Any,
    week_start_date: Optional[date] = None,
    academic_year_id: Optional[str] = None,
) -> Optional[Dict]:
    """Return the weekly timetable for the authenticated student.

    Returns None when the caller's user has no Student row (route → 403).
    Raises TimetableNotFoundError when no published timetable exists.
    """
    student = _resolve_student_for_user(tenant_id, student_user_id)
    if student is None:
        return None

    ay = _resolve_academic_year(tenant_id, academic_year_id)
    if ay is None:
        raise TimetableNotFoundError("No active academic year")

    week_start = _normalize_to_iso_monday(week_start_date or school_today())
    week_end = week_start + timedelta(days=6)

    class_id = getattr(student, "class_id", None)
    if class_id is None:
        # Distinguish "student isn't enrolled in a class for this AY" from
        # "no timetable exists" — the mobile client renders different states.
        raise StudentNotEnrolledError(
            "Student is not enrolled in a class for this academic year"
        )

    rows, published = _week_rows(tenant_id, ay.id, class_id=class_id)
    if not rows and not published:
        raise TimetableNotFoundError(
            "No published timetable for this academic year"
        )

    return _build_weekly_response(ay, week_start, week_end, rows)
