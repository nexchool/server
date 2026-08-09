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
