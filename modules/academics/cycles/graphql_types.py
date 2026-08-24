"""GraphQL shape of an academic cycle."""

from __future__ import annotations

import datetime as dt
from typing import Optional

import strawberry


@strawberry.type(
    description=(
        "A dated period an academic year is actually operated in. A school "
        "has one until it runs two boards on different calendars, or opens a "
        "vacation batch."
    )
)
class AcademicCycle:
    id: strawberry.ID
    academic_year_id: strawberry.ID
    name: str
    start_date: dt.date
    end_date: dt.date
    cycle_kind: str


def cycle_to_graphql(row) -> AcademicCycle:
    return AcademicCycle(
        id=strawberry.ID(row.id),
        academic_year_id=strawberry.ID(row.academic_year_id),
        name=row.name,
        start_date=row.start_date,
        end_date=row.end_date,
        cycle_kind=row.cycle_kind,
    )
