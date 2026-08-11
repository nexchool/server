"""GraphQL fields for the days a school is closed.

The calendar is an optional module — a school may not have bought it — so
unlike classes and subjects these fields carry `requires_feature`. That gate
is the same per-tenant switch the REST routes read; without it a school that
turned the calendar off could still be asked about its holidays.

The REST routes stay for the Expo client, which reads all three of these
(`client/modules/holidays/services/holidayService.ts`). Both transports call
the same services, so they cannot drift.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

import strawberry

from graphql_api.errors import ValidationError
from graphql_api.permissions import (
    IsAuthenticated,
    RequiresTenant,
    requires_any,
    requires_feature,
)

from .graphql.types import (
    AcademicCalendar,
    CalendarDay,
    CalendarSummary,
    ExamWindow,
    Holiday,
    HolidayPage,
    SchoolEvent,
    calendar_to_graphql,
    day_to_graphql,
    event_to_graphql,
    exam_window_to_graphql,
    holidays_to_graphql,
    summary_to_graphql,
)

PERM_READ = "holiday.read"
PERM_MANAGE = "holiday.manage"

# The calendar document answers to its own keys, NOT the holiday ones. Both
# live in this module and both sit behind the same feature, which is exactly
# why reusing one constant for the other was easy — and would have demanded a
# holiday permission to read a calendar. A test caught it.
PERM_CALENDAR_READ = "academic_calendar.read"
PERM_CALENDAR_MANAGE = "academic_calendar.manage"

# Read off the routes, not inferred: every holiday read answers to
# `holiday.read` or `holiday.manage`, and all of them sit behind the
# academic_calendar feature.
READS = [
    IsAuthenticated,
    RequiresTenant,
    requires_feature("academic_calendar"),
    requires_any(PERM_READ, PERM_MANAGE),
]

CALENDAR_READS = [
    IsAuthenticated,
    RequiresTenant,
    requires_feature("academic_calendar"),
    requires_any(PERM_CALENDAR_READ, PERM_CALENDAR_MANAGE),
]

MAX_PAGE_SIZE = 100


@strawberry.input(description="Which holidays to include.")
class HolidayFilter:
    academic_year_id: Optional[strawberry.ID] = None
    holiday_type: Optional[str] = None
    starts_on_or_after: Optional[datetime.date] = None
    ends_on_or_before: Optional[datetime.date] = None
    search: Optional[str] = strawberry.field(
        default=None, description="Matched against name and description."
    )
    include_recurring: bool = strawberry.field(
        default=True,
        description="Weekly closures are included unless you say otherwise.",
    )


def _filters_from(where: Optional[HolidayFilter]) -> Dict[str, Any]:
    if where is None:
        where = HolidayFilter()
    return {
        "academic_year_id": str(where.academic_year_id) if where.academic_year_id else None,
        "holiday_type": where.holiday_type,
        "start_date": (
            where.starts_on_or_after.isoformat() if where.starts_on_or_after else None
        ),
        "end_date": (
            where.ends_on_or_before.isoformat() if where.ends_on_or_before else None
        ),
        "search": where.search,
        "include_recurring": where.include_recurring,
    }


def _computed(services, calendar) -> Dict[str, Any]:
    """The summary, or the reason it cannot be computed.

    `compute_summary` raises when the calendar is inconsistent — a term that
    runs past the year, say. REST turns that into a 400; the transport needs
    the same answer with a code rather than an unexpected error.
    """
    from .services import CalendarValidationError

    try:
        return services.compute_summary(calendar)
    except CalendarValidationError as invalid:
        raise ValidationError(str(getattr(invalid, "errors", invalid)))


def _answered(result: Dict[str, Any]) -> Any:
    """A service says no with a message; the transport needs a code."""
    if not result.get("success"):
        raise ValidationError(result.get("error") or "Could not read the calendar")
    return result


@strawberry.type
class CalendarQuery:
    @strawberry.field(
        permission_classes=READS,
        description=(
            "The days this school is closed. Recurring weekly closures come "
            "last, then by date. Page with `first` and `offset`."
        ),
    )
    def holidays(
        self,
        info: strawberry.Info,
        first: int = 50,
        offset: Optional[int] = None,
        where: Optional[HolidayFilter] = None,
    ) -> HolidayPage:
        from . import holiday_services as services

        if offset is not None and offset < 0:
            raise ValidationError("`offset` cannot be negative.")

        limit = min(max(int(first), 1), MAX_PAGE_SIZE)
        result = _answered(
            services.list_holidays(
                tenant_id=info.context.tenant_id,
                limit=limit,
                offset=offset or 0,
                **_filters_from(where),
            )
        )
        total = result.get("total", 0)
        return HolidayPage(
            nodes=holidays_to_graphql(result["data"]),
            total_count=total,
            has_next_page=(offset or 0) + len(result["data"]) < total,
        )

    @strawberry.field(
        permission_classes=READS,
        description=(
            "The next closures from today, for a dashboard. Dated ones only — "
            "'every Sunday' is not news."
        ),
    )
    def upcoming_holidays(
        self, info: strawberry.Info, limit: int = 10
    ) -> List[Holiday]:
        from . import holiday_services as services

        result = _answered(
            services.get_upcoming_holidays(
                tenant_id=info.context.tenant_id, limit=min(max(int(limit), 1), 50)
            )
        )
        return holidays_to_graphql(result["data"])

    @strawberry.field(
        permission_classes=READS,
        description="The weekly closures — the days this school never opens.",
    )
    def recurring_holidays(self, info: strawberry.Info) -> List[Holiday]:
        from . import holiday_services as services

        result = _answered(
            services.get_recurring_holidays(tenant_id=info.context.tenant_id)
        )
        return holidays_to_graphql(result["data"])

    @strawberry.field(
        permission_classes=CALENDAR_READS,
        description=(
            "The calendar this school is working on for a year, or null if it "
            "has not started one. The document, not the days — ask "
            "`calendarDays` for those."
        ),
    )
    def academic_calendar(
        self, info: strawberry.Info, academic_year_id: strawberry.ID
    ) -> Optional[AcademicCalendar]:
        from . import services

        calendar = services.get_calendar_for_year(str(academic_year_id))
        return calendar_to_graphql(calendar.to_dict()) if calendar else None

    @strawberry.field(
        permission_classes=CALENDAR_READS,
        description=(
            "What the year adds up to — working days against everything that "
            "is not one. The numbers a school checks before publishing."
        ),
    )
    def calendar_summary(
        self, info: strawberry.Info, calendar_id: strawberry.ID
    ) -> Optional[CalendarSummary]:
        from . import services

        calendar = services.get_calendar(str(calendar_id))
        if calendar is None:
            return None
        return summary_to_graphql(_computed(services, calendar))

    @strawberry.field(
        permission_classes=CALENDAR_READS,
        description=(
            "Every day of the year and what the school is doing on it — what "
            "a calendar grid draws. A whole year in one answer: the grid needs "
            "all of it, so there is nothing to page."
        ),
    )
    def calendar_days(
        self, info: strawberry.Info, calendar_id: strawberry.ID
    ) -> List[CalendarDay]:
        from . import services

        calendar = services.get_calendar(str(calendar_id))
        if calendar is None:
            return []
        return [day_to_graphql(day) for day in services.get_days_feed(calendar)]

    @strawberry.field(
        permission_classes=CALENDAR_READS,
        description="What the school has planned this year, beyond teaching.",
    )
    def calendar_events(
        self, info: strawberry.Info, academic_year_id: strawberry.ID
    ) -> List[SchoolEvent]:
        from . import services

        return [
            event_to_graphql(row.to_dict())
            for row in services.list_school_events(str(academic_year_id))
        ]

    @strawberry.field(
        permission_classes=CALENDAR_READS,
        description="The stretches of the year given over to examinations.",
    )
    def exam_windows(
        self, info: strawberry.Info, academic_year_id: strawberry.ID
    ) -> List[ExamWindow]:
        from . import services

        return [
            exam_window_to_graphql(row.to_dict())
            for row in services.list_exam_windows(str(academic_year_id))
        ]
