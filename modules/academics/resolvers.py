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

import enum
from typing import Any, Dict, List, Optional

import strawberry

from graphql_api.errors import ValidationError
from graphql_api.permissions import (
    IsAuthenticated,
    RequiresTenant,
    requires,
    requires_any,
)

from modules.academics.calendar.graphql.types import AcademicTerm
from modules.academics.cycles.graphql_types import AcademicCycle as AcademicCycleType

from .graphql.types import (
    AcademicYear,
    Campus,
    Grade,
    Medium,
    Programme,
    Subject,
    SubjectPage,
    academic_years_to_graphql,
    campuses_to_graphql,
    catalogue_to_graphql,
    grades_to_graphql,
    mediums_to_graphql,
    programmes_to_graphql,
    subjects_to_graphql,
)


@strawberry.enum(description="What a page of the subject catalogue is ordered by.")
class SubjectOrder(enum.Enum):
    NAME = "name"
    CODE = "code"
    SUBJECT_TYPE = "subject_type"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


@strawberry.enum
class SubjectOrderDirection(enum.Enum):
    ASC = "asc"
    DESC = "desc"


@strawberry.enum(description="What kind of thing a subject is.")
class SubjectTypeFilter(enum.Enum):
    CORE = "core"
    ELECTIVE = "elective"
    LANGUAGE = "language"
    ACTIVITY = "activity"
    CO_CURRICULAR = "co_curricular"
    OTHER = "other"


@strawberry.input(description="Which subjects to include.")
class SubjectFilter:
    search: Optional[str] = strawberry.field(
        default=None, description="Matched against name, code and description."
    )
    subject_type: Optional[SubjectTypeFilter] = None
    include_inactive: Optional[bool] = strawberry.field(
        default=False,
        description="Include subjects the school has stopped offering.",
    )

# A campus is a `school_unit` in the tables; the keys predate the word.
PERM_CAMPUS_READ = "school_unit.read"
PERM_CAMPUS_MANAGE = "school_unit.manage"

PERM_PROGRAMME_READ = "programme.read"
PERM_PROGRAMME_MANAGE = "programme.manage"

PERM_GRADE_READ = "grade.read"
PERM_GRADE_MANAGE = "grade.manage"

# `subject.manage` implies `subject.read` in the Authorization Domain — a
# `<resource>.manage` grant covers every action on that resource — so naming
# the read alone is the whole rule, not half of it.
PERM_SUBJECT_READ = "subject.read"

# Mediums are part of how a school is set up rather than a domain of their own.
# Whoever assigns subjects to a class reads them too — a class-subject is
# taught in a medium — so that authority is on the list as well, exactly as
# the REST route has it.
PERM_MEDIUM_READ = "school_setup.read"
PERM_MEDIUM_MANAGE = "school_setup.manage"
PERM_CLASS_SUBJECT_MANAGE = "class_subject.manage"

# The honest authority for reading the list: `class_subject.read`. A teacher
# holds it and no manage key, so without this the only way to let them see the
# mediums was to grant them `school_setup.read` — the school's onboarding
# readiness — which is what the seeds used to do (debt 33).
PERM_CLASS_SUBJECT_READ = "class_subject.read"

# Terms answer to their own authority, not the calendar's — read off the
# route, which asks for `academic_term.*`. The calendar module asks for
# `academic_calendar.*`, and a person may hold one without the other.
PERM_TERM_READ = "academic_term.read"
PERM_TERM_MANAGE = "academic_term.manage"


def _subject_filters_from(where: Optional[SubjectFilter]) -> Dict[str, Any]:
    """The filter input as the service's keyword arguments.

    Always every key: the totals resolver reads them by name, and a missing
    one there is a 500 rather than a total over everything.
    """
    if where is None:
        where = SubjectFilter()
    return {
        "search": where.search,
        "subject_type": (
            where.subject_type.value if where.subject_type else None
        ),
        "include_inactive": bool(where.include_inactive),
    }


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
        # Guarded like `academicYears` and for the same reason: a class picker
        # and a calendar both need to know which cycles exist. Which period the
        # school runs in is context, not a privilege.
        permission_classes=[IsAuthenticated, RequiresTenant],
        description=(
            "The dated periods this academic year is operated in. One for an "
            "ordinary school; several for a trust running two boards on "
            "different calendars, or a vacation batch."
        ),
    )
    def academic_cycles(
        self, info: strawberry.Info, academic_year_id: strawberry.ID
    ) -> List["AcademicCycleType"]:
        from modules.academics.cycles.graphql_types import cycle_to_graphql
        from modules.academics.cycles.services import cycles_for_year

        return [
            cycle_to_graphql(row)
            for row in cycles_for_year(str(academic_year_id), info.context.tenant_id)
        ]

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
                PERM_MEDIUM_READ,
                PERM_MEDIUM_MANAGE,
                PERM_CLASS_SUBJECT_MANAGE,
                PERM_CLASS_SUBJECT_READ,
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

    @strawberry.field(
        permission_classes=[
            IsAuthenticated,
            RequiresTenant,
            requires(PERM_SUBJECT_READ),
        ],
        description=(
            "The subjects this school teaches, by name. The catalogue rather "
            "than any class's timetable. Pass `includeInactive` to see ones it "
            "has stopped offering — old records still name them."
        ),
    )
    def subjects(
        self, info: strawberry.Info, include_inactive: bool = False
    ) -> List[Subject]:
        from modules.subjects import services

        return subjects_to_graphql(
            services.list_subjects_filtered(
                info.context.tenant_id, include_inactive=include_inactive
            )
        )

    @strawberry.field(
        permission_classes=[
            IsAuthenticated,
            RequiresTenant,
            requires(PERM_SUBJECT_READ),
        ],
        description=(
            "The subject catalogue with where each subject is taught — its "
            "live class assignments and the programmes those imply. `subjects` "
            "is the plain list a picker wants; this is the administrator's "
            "view of the same catalogue, paged and searchable."
        ),
    )
    def subject_catalogue(
        self,
        info: strawberry.Info,
        first: int = 20,
        offset: Optional[int] = None,
        order_by: SubjectOrder = SubjectOrder.NAME,
        direction: SubjectOrderDirection = SubjectOrderDirection.ASC,
        where: Optional[SubjectFilter] = None,
    ) -> SubjectPage:
        from modules.subjects import services

        if offset is not None and offset < 0:
            raise ValidationError("`offset` cannot be negative.")

        filters = _subject_filters_from(where)
        rows, has_more = services.subjects_page(
            info.context.tenant_id,
            first=first,
            offset=offset,
            sort_by=order_by.value,
            sort_dir=direction.value,
            **filters,
        )
        return SubjectPage(
            nodes=catalogue_to_graphql(rows),
            has_next_page=has_more,
            filters=filters,
        )

    @strawberry.field(
        permission_classes=[
            IsAuthenticated,
            RequiresTenant,
            requires_any(PERM_TERM_READ, PERM_TERM_MANAGE),
        ],
        description=(
            "How this school divides its year — terms or semesters, in "
            "teaching order. No feature gate: `academics_advanced` is core, "
            "so it can never be switched off."
        ),
    )
    def academic_terms(
        self, info: strawberry.Info, academic_year_id: Optional[strawberry.ID] = None
    ) -> List["AcademicTerm"]:
        from modules.academics.calendar.graphql.types import term_to_graphql
        from modules.academics.term_routes import _list_terms

        return [
            term_to_graphql(row)
            for row in _list_terms(
                info.context.tenant_id,
                str(academic_year_id) if academic_year_id else None,
            )
        ]
