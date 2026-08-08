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
    Grade,
    Medium,
    Programme,
    academic_years_to_graphql,
    campuses_to_graphql,
    grades_to_graphql,
    mediums_to_graphql,
    programmes_to_graphql,
)

# A campus is a `school_unit` in the tables; the keys predate the word.
PERM_CAMPUS_READ = "school_unit.read"
PERM_CAMPUS_MANAGE = "school_unit.manage"

PERM_PROGRAMME_READ = "programme.read"
PERM_PROGRAMME_MANAGE = "programme.manage"

PERM_GRADE_READ = "grade.read"
PERM_GRADE_MANAGE = "grade.manage"

# Mediums are part of how a school is set up rather than a domain of their own.
# Whoever assigns subjects to a class reads them too — a class-subject is
# taught in a medium — so that authority is on the list as well, exactly as
# the REST route has it.
PERM_MEDIUM_READ = "school_setup.read"
PERM_MEDIUM_MANAGE = "school_setup.manage"
PERM_CLASS_SUBJECT_MANAGE = "class_subject.manage"


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
        # Deliberately no business authority, matching the REST route. Which
        # year the school is in is ambient — a student looking at their own
        # attendance and a teacher opening a register both need it, and
        # neither holds a class permission. Gating it would empty the year
        # picker for everyone but administrators.
        permission_classes=[IsAuthenticated, RequiresTenant],
        description=(
            "The years this school teaches through. Pass `activeOnly` for the "
            "one it is working in. Readable by anyone signed in: which year it "
            "is is context, not a privilege."
        ),
    )
    def academic_years(
        self, info: strawberry.Info, active_only: bool = False
    ) -> List[AcademicYear]:
        from modules.academics.academic_year import services

        return academic_years_to_graphql(
            services.list_academic_years(active_only=active_only)
        )

    @strawberry.field(
        permission_classes=[
            IsAuthenticated,
            RequiresTenant,
            requires_any(PERM_PROGRAMME_READ, PERM_PROGRAMME_MANAGE),
        ],
        description=(
            "The courses of education this school offers. A trust running two "
            "boards on one campus has two."
        ),
    )
    def programmes(
        self, info: strawberry.Info, status: Optional[str] = None
    ) -> List[Programme]:
        from modules.academic_programmes import services

        return programmes_to_graphql(
            services.list_programmes(info.context.tenant_id, status=status)
        )

    @strawberry.field(
        permission_classes=[
            IsAuthenticated,
            RequiresTenant,
            requires_any(PERM_GRADE_READ, PERM_GRADE_MANAGE),
        ],
        description="The year-groups this school teaches, in teaching order.",
    )
    def grades(self, info: strawberry.Info) -> List[Grade]:
        from modules.grades import services

        return grades_to_graphql(services.list_grades(info.context.tenant_id))

    @strawberry.field(
        permission_classes=[
            IsAuthenticated,
            RequiresTenant,
            requires_any(
                PERM_MEDIUM_READ, PERM_MEDIUM_MANAGE, PERM_CLASS_SUBJECT_MANAGE
            ),
        ],
        description=(
            "The languages this school teaches in. Pass `includeInactive` to "
            "see ones it has stopped offering."
        ),
    )
    def mediums(
        self, info: strawberry.Info, include_inactive: bool = False
    ) -> List[Medium]:
        from modules.mediums import services

        return mediums_to_graphql(
            services.list_mediums(
                info.context.tenant_id, include_inactive=include_inactive
            )
        )
