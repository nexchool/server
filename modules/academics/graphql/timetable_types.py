"""What a client sees of a class's week.

A timetable is a version — a school drafts one, activates it, and keeps the
old one — so nothing here is "the timetable" without saying which version.

The bundle is one answer rather than four calls because a grid cannot be
drawn from any part of it alone: the entries say what is taught, the bell
schedule says when the periods are, and the working days say which columns
exist. Splitting them would make three round-trips to draw one table.
"""

from __future__ import annotations

import datetime
from typing import List, Optional

import strawberry


def _date(value) -> Optional[datetime.date]:
    if not value:
        return None
    if isinstance(value, datetime.date):
        return value
    return datetime.date.fromisoformat(str(value)[:10])


@strawberry.type(description="One drafted or published timetable for a class.")
class TimetableVersion:
    id: strawberry.ID
    class_id: strawberry.ID
    label: Optional[str] = None
    status: str = strawberry.field(description="draft, active or archived.")
    bell_schedule_id: Optional[strawberry.ID] = None
    effective_from: Optional[datetime.date] = None
    effective_to: Optional[datetime.date] = None


@strawberry.type(description="One period in the school's daily rhythm.")
class LessonPeriod:
    id: strawberry.ID
    bell_schedule_id: Optional[strawberry.ID] = None
    period_number: Optional[int] = None
    period_kind: Optional[str] = strawberry.field(
        default=None, description="A lesson, a break, an assembly."
    )
    label: Optional[str] = None
    starts_at: Optional[str] = None
    ends_at: Optional[str] = None
    sort_order: Optional[int] = None


@strawberry.type(description="The clock a school teaches to.")
class BellSchedule:
    id: strawberry.ID
    name: Optional[str] = None
    lesson_periods: List[LessonPeriod] = strawberry.field(default_factory=list)


@strawberry.type(description="One lesson in the week — a subject, a slot, a teacher.")
class TimetableEntry:
    id: strawberry.ID
    timetable_version_id: Optional[strawberry.ID] = None
    day_of_week: int = 0
    period_number: Optional[int] = None
    period_label: Optional[str] = None
    period_name: Optional[str] = None
    starts_at: Optional[str] = None
    ends_at: Optional[str] = None
    class_subject_id: Optional[strawberry.ID] = None
    class_subject_teacher_id: Optional[strawberry.ID] = None
    subject_name: Optional[str] = None
    teacher_id: Optional[strawberry.ID] = None
    teacher_name: Optional[str] = None
    room: Optional[str] = None
    entry_status: Optional[str] = None
    editable: bool = False
    notes: Optional[str] = None
    conflict_flags: List[str] = strawberry.field(
        default_factory=list,
        description="Why this slot is unhappy — a teacher in two rooms at once.",
    )


@strawberry.type(
    description=(
        "Everything needed to draw one class's week: the version, the clock, "
        "the days the school opens, and the lessons."
    )
)
class Timetable:
    version: Optional[TimetableVersion] = None
    bell_schedule: Optional[BellSchedule] = None
    working_days: List[int] = strawberry.field(
        default_factory=list, description="Days the school opens (0 = Monday)."
    )
    editable: bool = False
    entries: List[TimetableEntry] = strawberry.field(default_factory=list)


def _id(value) -> Optional[strawberry.ID]:
    return strawberry.ID(value) if value else None


def version_to_graphql(row: dict) -> TimetableVersion:
    return TimetableVersion(
        id=strawberry.ID(row["id"]),
        class_id=strawberry.ID(row["class_id"]),
        label=row.get("label"),
        status=row.get("status") or "draft",
        bell_schedule_id=(
            strawberry.ID(row["bell_schedule_id"]) if row.get("bell_schedule_id") else None
        ),
        effective_from=_date(row.get("effective_from")),
        effective_to=_date(row.get("effective_to")),
    )


def entry_to_graphql(row: dict) -> TimetableEntry:
    return TimetableEntry(
        id=strawberry.ID(row["id"]),
        timetable_version_id=_id(row.get("timetable_version_id")),
        day_of_week=int(row.get("day_of_week") or 0),
        period_number=row.get("period_number"),
        period_label=row.get("period_label"),
        period_name=row.get("period_name"),
        room=row.get("room"),
        editable=bool(row.get("editable")),
        teacher_id=_id(row.get("teacher_id")),
        starts_at=row.get("starts_at"),
        ends_at=row.get("ends_at"),
        class_subject_id=(
            strawberry.ID(row["class_subject_id"]) if row.get("class_subject_id") else None
        ),
        class_subject_teacher_id=(
            strawberry.ID(row["class_subject_teacher_id"])
            if row.get("class_subject_teacher_id")
            else None
        ),
        subject_name=row.get("subject_name"),
        teacher_name=row.get("teacher_name"),
        entry_status=row.get("entry_status"),
        notes=row.get("notes"),
        conflict_flags=list(row.get("conflict_flags") or []),
    )


def bell_to_graphql(row: Optional[dict]) -> Optional[BellSchedule]:
    if not row:
        return None
    return BellSchedule(
        id=strawberry.ID(row["id"]),
        name=row.get("name"),
        lesson_periods=[
            LessonPeriod(
                id=strawberry.ID(period["id"]),
                bell_schedule_id=_id(period.get("bell_schedule_id")),
                period_number=period.get("period_number"),
                period_kind=period.get("period_kind"),
                label=period.get("label"),
                starts_at=period.get("starts_at"),
                ends_at=period.get("ends_at"),
                sort_order=period.get("sort_order"),
            )
            for period in (row.get("lesson_periods") or [])
        ],
    )


def bundle_to_graphql(bundle: dict) -> Timetable:
    version = bundle.get("timetable_version")
    return Timetable(
        version=version_to_graphql(version) if version else None,
        bell_schedule=bell_to_graphql(bundle.get("bell_schedule")),
        working_days=list(bundle.get("working_days") or []),
        editable=bool(bundle.get("editable")),
        entries=[entry_to_graphql(row) for row in (bundle.get("items") or [])],
    )
