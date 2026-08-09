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

from .graphql.types import Holiday, HolidayPage, holidays_to_graphql

PERM_READ = "holiday.read"
PERM_MANAGE = "holiday.manage"

# Read off the routes, not inferred: every holiday read answers to
# `holiday.read` or `holiday.manage`, and all of them sit behind the
# academic_calendar feature.
READS = [
    IsAuthenticated,
    RequiresTenant,
    requires_feature("academic_calendar"),
    requires_any(PERM_READ, PERM_MANAGE),
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
