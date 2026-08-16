"""What a client sees of the days a school is closed.

A holiday is one thing said two ways: a dated closure ("Diwali, 1–5 Nov") and
a weekly one ("every Sunday"). They live in one table with `is_recurring`
telling them apart, and the type keeps that rather than splitting them —
a screen showing the year's closures wants both, in one list.
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


def _datetime(value) -> Optional[datetime.datetime]:
    if not value:
        return None
    if isinstance(value, datetime.datetime):
        return value
    return datetime.datetime.fromisoformat(str(value))


@strawberry.type(
    description=(
        "A day, or a run of days, the school is closed. A recurring one has "
        "no dates — it is a day of the week, every week."
    )
)
class Holiday:
    id: strawberry.ID
    name: str
    description: Optional[str] = None
    holiday_type: Optional[str] = strawberry.field(
        default=None,
        description="public, national, school, regional, optional, weekly_off or vacation.",
    )
    applies_to: Optional[str] = None

    start_date: Optional[datetime.date] = None
    end_date: Optional[datetime.date] = None
    is_single_day: bool = True
    duration_days: Optional[int] = None

    is_recurring: bool = strawberry.field(
        default=False,
        description="A weekly closure rather than a dated one; carries no dates.",
    )
    recurring_day_of_week: Optional[int] = None
    recurring_day_name: Optional[str] = None

    falls_on_sunday: bool = strawberry.field(
        default=False,
        description=(
            "Whether this closure lands on a day the school is already shut. "
            "Shown so nobody reports a holiday that changes nothing."
        ),
    )

    academic_year_id: Optional[strawberry.ID] = None
    academic_year_name: Optional[str] = None


@strawberry.type(
    description=(
        "A page of holidays. Paged by offset: the order — recurring last, "
        "then by date — has no key that is both unique and unchanging."
    )
)
class HolidayPage:
    nodes: List[Holiday]
    total_count: int = strawberry.field(
        description="How many holidays match, ignoring paging."
    )
    has_next_page: bool


def holiday_to_graphql(row: dict) -> Holiday:
    return Holiday(
        id=strawberry.ID(row["id"]),
        name=row["name"],
        description=row.get("description"),
        holiday_type=row.get("holiday_type"),
        applies_to=row.get("applies_to"),
        start_date=_date(row.get("start_date")),
        end_date=_date(row.get("end_date")),
        is_single_day=bool(row.get("is_single_day", True)),
        duration_days=row.get("duration_days"),
        is_recurring=bool(row.get("is_recurring")),
        recurring_day_of_week=row.get("recurring_day_of_week"),
        recurring_day_name=row.get("recurring_day_name"),
        falls_on_sunday=bool(row.get("falls_on_sunday")),
        academic_year_id=(
            strawberry.ID(row["academic_year_id"])
            if row.get("academic_year_id")
            else None
        ),
        academic_year_name=row.get("academic_year_name"),
    )


def holidays_to_graphql(rows) -> List[Holiday]:
    return [holiday_to_graphql(row) for row in rows]


@strawberry.type(
    description=(
        "How this school likes its calendar shown. A closed set of choices, "
        "so it is typed rather than handed over as an opaque blob."
    )
)
class CalendarPreferences:
    default_view: str = "month"
    default_month: Optional[str] = None
    week_start: str = "monday"
    date_format: str = "dd_mmm_yyyy"
    time_format: str = "24h"
    default_event_color: str = "amber"


@strawberry.type(
    description=(
        "A school's calendar for one academic year — the working document, "
        "not the days themselves. Drafted, then published, then archivable; "
        "`currentStep` is where the setup wizard got to."
    )
)
class AcademicCalendar:
    id: strawberry.ID
    academic_year_id: strawberry.ID
    academic_year_name: Optional[str] = strawberry.field(
        default=None,
        description=(
            "The year's name. REST nests the whole academic year object here; "
            "a calendar screen shows its name and nothing else."
        ),
    )
    status: str = strawberry.field(description="draft, published or archived.")
    current_step: Optional[int] = None
    total_steps: Optional[int] = None
    published_at: Optional[str] = None
    published_by: Optional[str] = None
    archived_at: Optional[str] = None
    archived_by: Optional[str] = None
    weekly_holidays_config: Optional["WeeklyHolidaysConfig"] = strawberry.field(
        default=None, description="Which days of the week the school is shut."
    )
    preferences: Optional[CalendarPreferences] = strawberry.field(
        default=None,
        description=(
            "How this school likes its calendar shown. The screen reads "
            "`defaultView` as it mounts, so leaving it out is a blank page."
        ),
    )


@strawberry.type(
    description=(
        "Which days of the week a school never opens. Not a plain list of "
        "days: Indian schools commonly take the second and fourth Saturday "
        "and work the rest, so those are their own flags."
    )
)
class WeeklyHolidaysConfig:
    days: List[int] = strawberry.field(
        default_factory=list, description="Weekday numbers, 0 = Monday."
    )
    second_saturday: bool = False
    fourth_saturday: bool = False


@strawberry.type(description="How many events of one kind the year holds.")
class EventTypeCount:
    event_type: str
    count: int


@strawberry.type(
    description=(
        "What a year adds up to — the counts a school checks before it "
        "publishes: how many days it actually teaches on, and where the rest "
        "went."
    )
)
class CalendarSummary:
    academic_year: Optional[str] = None
    total_days: int = 0
    working_days: int = 0
    public_holiday_days: int = 0
    weekly_holiday_days: int = 0
    vacation_days: int = 0
    exam_days: int = 0
    event_count: int = 0
    exam_window_count: int = 0
    semester_count: int = 0
    events_by_type: List[EventTypeCount] = strawberry.field(
        default_factory=list,
        description=(
            "A count per event type — a list, not a map, because the types "
            "are the school's to invent and a schema cannot grow a field for "
            "each one."
        ),
    )
    weekly_holidays_config: Optional[WeeklyHolidaysConfig] = strawberry.field(
        default=None, description="Which days of the week the school is shut."
    )


@strawberry.type(description="A closure falling on a particular day.")
class DayHoliday:
    id: strawberry.ID
    name: str
    holiday_type: Optional[str] = None


@strawberry.type(
    description="One day of the year and what the school is doing on it."
)
class CalendarDay:
    date: datetime.date
    day_type: str = strawberry.field(
        description="working, weekly_holiday, public_holiday, vacation or exam."
    )
    has_event: bool = False
    has_exam: bool = False
    holidays: List[DayHoliday] = strawberry.field(
        default_factory=list, description="Any closures falling on this day."
    )
    semester_start: bool = False
    semester_end: bool = False


@strawberry.type(description="Something the school has planned — a sports day, a concert.")
class SchoolEvent:
    id: strawberry.ID
    name: str
    event_type: Optional[str] = None
    description: Optional[str] = None
    # An event happens on one day. It has no start/end pair — the fields that
    # once claimed otherwise were never populated by the model.
    event_date: Optional[datetime.date] = None
    status: str = "active"
    applies_to: Optional[str] = None
    academic_year_id: Optional[strawberry.ID] = None
    created_at: Optional[datetime.datetime] = None
    updated_at: Optional[datetime.datetime] = None


@strawberry.type(description="A stretch of days given over to examinations.")
class ExamWindow:
    id: strawberry.ID
    name: str
    exam_type: Optional[str] = None
    status: str = "active"
    start_date: Optional[datetime.date] = None
    end_date: Optional[datetime.date] = None
    duration_days: int = 0
    # Empty means the window applies to every class, which is why this is a
    # list and never null — a client counts it to label the window.
    applicable_class_ids: List[strawberry.ID] = strawberry.field(default_factory=list)
    description: Optional[str] = None
    academic_year_id: Optional[strawberry.ID] = None
    created_at: Optional[datetime.datetime] = None
    updated_at: Optional[datetime.datetime] = None


@strawberry.type(
    description=(
        "A division of the academic year — a term or a semester. Ordered by "
        "`sequence`, because names do not order themselves."
    )
)
class AcademicTerm:
    id: strawberry.ID
    name: str
    code: Optional[str] = None
    sequence: int = 0
    start_date: Optional[datetime.date] = None
    end_date: Optional[datetime.date] = None
    is_active: bool = True
    academic_year_id: Optional[strawberry.ID] = None


def _year_name(value) -> Optional[str]:
    """The year's name, however the serializer chose to give it.

    `AcademicCalendar.to_dict` nests the whole year object under
    `academic_year`; `compute_summary` puts a plain name there. Typing it as a
    string and handing it the object is what made the field blow up.
    """
    if isinstance(value, dict):
        return value.get("name")
    return value


def calendar_to_graphql(row: dict) -> AcademicCalendar:
    return AcademicCalendar(
        id=strawberry.ID(row["id"]),
        academic_year_id=strawberry.ID(row["academic_year_id"]),
        academic_year_name=_year_name(row.get("academic_year")),
        status=row.get("status") or "draft",
        current_step=row.get("current_step"),
        total_steps=row.get("total_steps"),
        published_at=row.get("published_at"),
        published_by=row.get("published_by"),
        archived_at=row.get("archived_at"),
        archived_by=row.get("archived_by"),
        weekly_holidays_config=_weekly_config(row.get("weekly_holidays_config")),
        preferences=_preferences(row.get("preferences")),
    )


def summary_to_graphql(row: dict) -> CalendarSummary:
    by_type = row.get("events_by_type") or {}
    return CalendarSummary(
        academic_year=_year_name(row.get("academic_year")),
        total_days=row.get("total_days") or 0,
        working_days=row.get("working_days") or 0,
        public_holiday_days=row.get("public_holiday_days") or 0,
        weekly_holiday_days=row.get("weekly_holiday_days") or 0,
        vacation_days=row.get("vacation_days") or 0,
        exam_days=row.get("exam_days") or 0,
        event_count=row.get("event_count") or 0,
        exam_window_count=row.get("exam_window_count") or 0,
        semester_count=row.get("semester_count") or 0,
        events_by_type=[
            EventTypeCount(event_type=key, count=value)
            for key, value in sorted(by_type.items())
        ],
        weekly_holidays_config=_weekly_config(row.get("weekly_holidays_config")),
    )


def _preferences(value) -> Optional[CalendarPreferences]:
    """The screen reads `preferences.default_view` on mount.

    Dropping this from the mapper is what threw "Cannot read properties of
    undefined (reading 'default_view')" — and a double cast on the client
    stopped the compiler saying so.
    """
    if not isinstance(value, dict):
        return None
    return CalendarPreferences(
        default_view=value.get("default_view") or "month",
        default_month=value.get("default_month"),
        week_start=value.get("week_start") or "monday",
        date_format=value.get("date_format") or "dd_mmm_yyyy",
        time_format=value.get("time_format") or "24h",
        default_event_color=value.get("default_event_color") or "amber",
    )


def _weekly_config(value) -> Optional[WeeklyHolidaysConfig]:
    """`{days: [...], second_saturday: bool, fourth_saturday: bool}`.

    Typed as a bare list of days once, which made the field fail with "Int
    cannot represent 'days'" — the dict's keys, not its days.
    """
    if not isinstance(value, dict):
        return None
    return WeeklyHolidaysConfig(
        days=[int(day) for day in (value.get("days") or [])],
        second_saturday=bool(value.get("second_saturday")),
        fourth_saturday=bool(value.get("fourth_saturday")),
    )


def day_to_graphql(row: dict) -> CalendarDay:
    return CalendarDay(
        date=_date(row["date"]),
        day_type=row.get("day_type") or "working",
        has_event=bool(row.get("has_event")),
        has_exam=bool(row.get("has_exam")),
        holidays=[
            DayHoliday(
                id=strawberry.ID(holiday["id"]),
                name=holiday.get("name") or "",
                holiday_type=holiday.get("holiday_type"),
            )
            for holiday in (row.get("holidays") or [])
            if isinstance(holiday, dict)
        ],
        semester_start=bool(row.get("semester_start")),
        semester_end=bool(row.get("semester_end")),
    )


def event_to_graphql(row: dict) -> SchoolEvent:
    return SchoolEvent(
        id=strawberry.ID(row["id"]),
        name=row["name"],
        event_type=row.get("event_type"),
        description=row.get("description"),
        event_date=_date(row.get("event_date")),
        status=row.get("status") or "active",
        applies_to=row.get("applies_to"),
        academic_year_id=(
            strawberry.ID(row["academic_year_id"]) if row.get("academic_year_id") else None
        ),
        created_at=_datetime(row.get("created_at")),
        updated_at=_datetime(row.get("updated_at")),
    )


def exam_window_to_graphql(row: dict) -> ExamWindow:
    return ExamWindow(
        id=strawberry.ID(row["id"]),
        name=row["name"],
        exam_type=row.get("exam_type"),
        status=row.get("status") or "active",
        start_date=_date(row.get("start_date")),
        end_date=_date(row.get("end_date")),
        duration_days=row.get("duration_days") or 0,
        applicable_class_ids=[
            strawberry.ID(cid) for cid in (row.get("applicable_class_ids") or [])
        ],
        description=row.get("description"),
        academic_year_id=(
            strawberry.ID(row["academic_year_id"]) if row.get("academic_year_id") else None
        ),
        created_at=_datetime(row.get("created_at")),
        updated_at=_datetime(row.get("updated_at")),
    )


def term_to_graphql(row: dict) -> AcademicTerm:
    return AcademicTerm(
        id=strawberry.ID(row["id"]),
        name=row["name"],
        code=row.get("code"),
        sequence=int(row.get("sequence") or 0),
        start_date=_date(row.get("start_date")),
        end_date=_date(row.get("end_date")),
        is_active=bool(row.get("is_active", True)),
        academic_year_id=(
            strawberry.ID(row["academic_year_id"]) if row.get("academic_year_id") else None
        ),
    )
