"""What a class is taught, by whom, and to what clock.

Three things a timetable is assembled from, and each answers to a different
combination of feature and authority — which is why they are three fields
rather than one convenient bundle.

Typed against real payloads, not field names.
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


def _id(value) -> Optional[strawberry.ID]:
    return strawberry.ID(value) if value else None


@strawberry.type(
    description=(
        "A subject offered to one class, with how much of the week it gets. "
        "The offering, not the subject — the same subject is a different "
        "offering in every class that takes it."
    )
)
class ClassSubject:
    id: strawberry.ID
    class_id: strawberry.ID
    subject_id: strawberry.ID
    subject_name: Optional[str] = None
    subject_code: Optional[str] = None
    weekly_periods: int = 0
    is_mandatory: bool = True
    is_elective_bucket: bool = strawberry.field(
        default=False,
        description="A slot children choose within, rather than a fixed subject.",
    )
    sort_order: Optional[int] = None
    status: Optional[str] = None
    academic_term_id: Optional[strawberry.ID] = None
    academic_term_name: Optional[str] = None


@strawberry.type(
    description=(
        "Somebody teaching one of a class's subjects. Dated, because a "
        "hand-over mid-year must leave the earlier term's register naming who "
        "actually taught it."
    )
)
class SubjectTeacher:
    id: strawberry.ID
    class_subject_id: strawberry.ID
    teacher_id: strawberry.ID
    teacher_name: Optional[str] = None
    employee_id: Optional[str] = None
    role: Optional[str] = strawberry.field(
        default=None, description="primary or assistant."
    )
    is_active: bool = True
    effective_from: Optional[datetime.date] = None
    effective_to: Optional[datetime.date] = None


@strawberry.type(description="One slot in the school's daily clock.")
class BellPeriod:
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


@strawberry.type(
    description=(
        "A school day's shape — when periods start and end. A school may keep "
        "several: a shorter Saturday, a different one per year."
    )
)
class BellSchedule:
    id: strawberry.ID
    name: str
    is_default: bool = False
    day_of_week: Optional[int] = strawberry.field(
        default=None, description="Set when this clock is for one weekday only."
    )
    academic_year_id: Optional[strawberry.ID] = None
    valid_from: Optional[datetime.date] = None
    valid_to: Optional[datetime.date] = None


@strawberry.type(
    name="BellScheduleDetail",
    description="One clock, with its periods and what still depends on it.",
)
class BellScheduleDetail(BellSchedule):
    periods: List[BellPeriod] = strawberry.field(default_factory=list)
    timetable_versions_linked: int = strawberry.field(
        default=0,
        description="How many timetables use it — what a school breaks by editing it.",
    )


@strawberry.type(
    description=(
        "The school's clocks, and which one it falls back to when a class "
        "names none."
    )
)
class BellScheduleList:
    items: List[BellSchedule]
    default_bell_schedule_id: Optional[strawberry.ID] = None


def class_subject_to_graphql(row: dict) -> ClassSubject:
    return ClassSubject(
        id=strawberry.ID(row["id"]),
        class_id=strawberry.ID(row["class_id"]),
        subject_id=strawberry.ID(row["subject_id"]),
        subject_name=row.get("subject_name"),
        subject_code=row.get("subject_code"),
        weekly_periods=int(row.get("weekly_periods") or 0),
        is_mandatory=bool(row.get("is_mandatory", True)),
        is_elective_bucket=bool(row.get("is_elective_bucket")),
        sort_order=row.get("sort_order"),
        status=row.get("status"),
        academic_term_id=_id(row.get("academic_term_id")),
        academic_term_name=row.get("academic_term_name"),
    )


def subject_teacher_to_graphql(row: dict) -> SubjectTeacher:
    return SubjectTeacher(
        id=strawberry.ID(row["id"]),
        class_subject_id=strawberry.ID(row["class_subject_id"]),
        teacher_id=strawberry.ID(row["teacher_id"]),
        teacher_name=row.get("teacher_name"),
        employee_id=row.get("employee_id"),
        role=row.get("role"),
        is_active=bool(row.get("is_active", True)),
        effective_from=_date(row.get("effective_from")),
        effective_to=_date(row.get("effective_to")),
    )


def bell_period_to_graphql(row: dict) -> BellPeriod:
    return BellPeriod(
        id=strawberry.ID(row["id"]),
        bell_schedule_id=_id(row.get("bell_schedule_id")),
        period_number=row.get("period_number"),
        period_kind=row.get("period_kind"),
        label=row.get("label"),
        starts_at=row.get("starts_at"),
        ends_at=row.get("ends_at"),
        sort_order=row.get("sort_order"),
    )


def _bell_fields(row: dict) -> dict:
    return dict(
        id=strawberry.ID(row["id"]),
        name=row.get("name") or "",
        is_default=bool(row.get("is_default")),
        day_of_week=row.get("day_of_week"),
        academic_year_id=_id(row.get("academic_year_id")),
        valid_from=_date(row.get("valid_from")),
        valid_to=_date(row.get("valid_to")),
    )


def bell_schedule_to_graphql(row: dict) -> BellSchedule:
    return BellSchedule(**_bell_fields(row))


def bell_schedule_detail_to_graphql(row: dict) -> BellScheduleDetail:
    return BellScheduleDetail(
        **_bell_fields(row),
        periods=[bell_period_to_graphql(p) for p in (row.get("periods") or [])],
        timetable_versions_linked=int(row.get("timetable_versions_linked") or 0),
    )
