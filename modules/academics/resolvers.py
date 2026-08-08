"""GraphQL fields for the structure a school is arranged into.

Each list keeps the authority its REST route carries rather than being
merged into one "scope" query. The five structure reads answer to five
different permissions, and today a person holding some but not others still
gets everything they may see — bundling them would turn one refusal into a
blank screen.

That is a decision about this schema, not a limitation of GraphQL: a client
still asks for several of these in one request, and gets one round-trip,
without the server pretending they are one authority.
"""

from __future__ import annotations

from typing import List, Optional

import strawberry

from graphql_api.permissions import IsAuthenticated, RequiresTenant, requires_any

from .graphql.types import (
    AcademicYear,
    Campus,
    academic_years_to_graphql,
    campuses_to_graphql,
)

# A campus is a `school_unit` in the tables; the keys predate the word.
PERM_CAMPUS_READ = "school_unit.read"
PERM_CAMPUS_MANAGE = "school_unit.manage"

# Academic years answer to the class keys: a year exists to hold classes.
PERM_YEAR_READ = "class.read"
PERM_YEAR_MANAGE = "class.manage"


@strawberry.type
class AcademicsQuery:
    @strawberry.field(
        permission_classes=[
            IsAuthenticated,
            RequiresTenant,
            requires_any(PERM_CAMPUS_READ, PERM_CAMPUS_MANAGE),
        ],
        description=(
            "The sites this school teaches at. Called school units in the "
            "tables and the REST API."
        ),
    )
    def campuses(
        self, info: strawberry.Info, status: Optional[str] = None
    ) -> List[Campus]:
        from modules.school_units import services

        return campuses_to_graphql(
            services.list_school_units(info.context.tenant_id, status=status)
        )

    @strawberry.field(
        permission_classes=[
            IsAuthenticated,
            RequiresTenant,
            requires_any(PERM_YEAR_READ, PERM_YEAR_MANAGE),
        ],
        description=(
            "The years this school teaches through, newest first. Pass "
            "`activeOnly` for the one it is working in."
        ),
    )
    def academic_years(
        self, info: strawberry.Info, active_only: bool = False
    ) -> List[AcademicYear]:
        from modules.academics.academic_year import services

        return academic_years_to_graphql(
            services.list_academic_years(active_only=active_only)
        )
