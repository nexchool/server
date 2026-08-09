"""GraphQL fields for the people a school employs to teach.

`teacher_management` is a CORE feature, so — like classes and students —
these carry no feature gate: a school cannot switch teachers off, and a gate
that never fires is machinery somebody will one day believe.

The REST routes stay: the Expo client reads both of these
(`client/modules/teachers/services/teacherService.ts`). Both transports call
`services.list_teachers` and `services.get_teacher_by_id`, so there is one
reader and the two shapes cannot drift.
"""

from __future__ import annotations

import datetime
import enum
from typing import Any, Dict, List, Optional

import strawberry

from graphql_api.errors import ValidationError
from graphql_api.permissions import (
    IsAuthenticated,
    RequiresTenant,
    requires,
    requires_feature,
)

from .graphql.types import (
    DepartmentOption,
    TeacherAvailability,
    TeacherLeave,
    TeacherSubjectAssignment,
    TeacherWorkload,
    availability_to_graphql,
    leave_to_graphql,
    teacher_subject_to_graphql,
    workload_to_graphql,
    Teacher,
    TeacherDetail,
    TeacherPage,
    teacher_detail_to_graphql,
    teachers_to_graphql,
)

# `teacher.manage` implies every teacher action, so naming the read is the
# whole rule. Read off the route.
PERM_READ = "teacher.read"

# The sub-surfaces are stricter than the list, and they do not agree with each
# other. Read off each route rather than assumed from the module:
#   subjects     teacher.manage         + teacher_management (CORE, no gate)
#   availability teacher.manage         + timetable (OPTIONAL, gated)
#   workload     teacher.manage         + timetable (OPTIONAL, gated)
#   leaves       teacher.leave.manage   + teacher_management (CORE, no gate)
# Bundling these behind one guard would hand somebody a screen they may not
# open, or take away one they may.
PERM_MANAGE = "teacher.manage"
PERM_LEAVE_MANAGE = "teacher.leave.manage"

TIMETABLE_READS = [
    IsAuthenticated,
    RequiresTenant,
    requires_feature("timetable"),
    requires(PERM_MANAGE),
]

MAX_PAGE_SIZE = 100


@strawberry.enum(description="What a list of teachers is ordered by.")
class TeacherOrder(enum.Enum):
    EMPLOYEE_ID = "employee_id"
    NAME = "name"
    DESIGNATION = "designation"
    DEPARTMENT = "department"
    DATE_OF_JOINING = "date_of_joining"


@strawberry.enum
class TeacherOrderDirection(enum.Enum):
    ASC = "asc"
    DESC = "desc"


@strawberry.enum(description="Which field a search term is matched against.")
class TeacherSearchField(enum.Enum):
    ALL = "all"
    NAME = "name"
    EMPLOYEE_ID = "employee_id"
    EMAIL = "email"
    PHONE = "phone"


@strawberry.input(description="Which teachers to include.")
class TeacherFilter:
    search: Optional[str] = None
    search_field: Optional[TeacherSearchField] = None
    status: Optional[str] = strawberry.field(
        default=None,
        description=(
            "active or inactive. Derived from employment — a teacher whose "
            "employment has ended reads as inactive."
        ),
    )
    department_id: Optional[strawberry.ID] = None
    designation: Optional[str] = None
    joined_on_or_after: Optional[datetime.date] = None
    joined_on_or_before: Optional[datetime.date] = None


def _filters_from(where: Optional[TeacherFilter]) -> Dict[str, Any]:
    if where is None:
        where = TeacherFilter()
    return {
        "search": where.search,
        "search_field": where.search_field.value if where.search_field else "all",
        "status": where.status,
        "department_id": str(where.department_id) if where.department_id else None,
        "designation": where.designation,
        "date_of_joining_from": (
            where.joined_on_or_after.isoformat() if where.joined_on_or_after else None
        ),
        "date_of_joining_to": (
            where.joined_on_or_before.isoformat() if where.joined_on_or_before else None
        ),
    }


@strawberry.type
class TeacherQuery:
    @strawberry.field(
        permission_classes=[IsAuthenticated, RequiresTenant, requires(PERM_READ)],
        description=(
            "The people this school employs to teach. Paged by offset — no "
            "order here has a key that is both unique and unchanging, and a "
            "cursor over such a key skips rows rather than failing."
        ),
    )
    def teachers(
        self,
        info: strawberry.Info,
        first: int = 25,
        offset: Optional[int] = None,
        order_by: TeacherOrder = TeacherOrder.EMPLOYEE_ID,
        direction: TeacherOrderDirection = TeacherOrderDirection.ASC,
        where: Optional[TeacherFilter] = None,
    ) -> TeacherPage:
        from . import services

        if offset is not None and offset < 0:
            raise ValidationError("`offset` cannot be negative.")

        per_page = min(max(int(first), 1), MAX_PAGE_SIZE)
        start = offset or 0
        # The service pages by page number; a page boundary is the only offset
        # it can express, so an offset that does not land on one is refused
        # rather than quietly rounded to the page that contains it.
        if start % per_page:
            raise ValidationError(
                "`offset` must be a multiple of `first` for this list."
            )

        result = services.list_teachers(
            page=(start // per_page) + 1,
            per_page=per_page,
            sort_by=order_by.value,
            sort_dir=direction.value,
            **_filters_from(where),
        )
        total = result.get("total", 0)
        items = result.get("items", [])
        return TeacherPage(
            nodes=teachers_to_graphql(items),
            total_count=total,
            has_next_page=start + len(items) < total,
            departments=[
                DepartmentOption(
                    id=strawberry.ID(row["id"]), name=row.get("name") or ""
                )
                for row in (result.get("departments") or [])
            ],
            designations=[d for d in (result.get("designations") or []) if d],
        )

    @strawberry.field(
        permission_classes=[IsAuthenticated, RequiresTenant, requires(PERM_READ)],
        description="One teacher, with the subjects they are assigned to teach.",
    )
    def teacher(
        self, info: strawberry.Info, id: strawberry.ID
    ) -> Optional[TeacherDetail]:
        from . import services

        row = services.get_teacher_by_id(str(id))
        return teacher_detail_to_graphql(row) if row else None

    @strawberry.field(
        permission_classes=[IsAuthenticated, RequiresTenant, requires(PERM_MANAGE)],
        description="The subjects a teacher is assigned to teach.",
    )
    def teacher_subjects(
        self, info: strawberry.Info, teacher_id: strawberry.ID
    ) -> List[TeacherSubjectAssignment]:
        from . import constraint_services

        return [
            teacher_subject_to_graphql(row)
            for row in constraint_services.get_teacher_subjects(str(teacher_id))
        ]

    @strawberry.field(
        permission_classes=TIMETABLE_READS,
        description=(
            "When a teacher is free. Rows exist only where the school has "
            "said something — no rows means no constraint, not no availability."
        ),
    )
    def teacher_availability(
        self, info: strawberry.Info, teacher_id: strawberry.ID
    ) -> List[TeacherAvailability]:
        from . import constraint_services

        return [
            availability_to_graphql(row)
            for row in constraint_services.get_teacher_availability(str(teacher_id))
        ]

    @strawberry.field(
        permission_classes=TIMETABLE_READS,
        description=(
            "How much this teacher may be asked to teach. Every ceiling is "
            "null when the school has set none for them."
        ),
    )
    def teacher_workload(
        self, info: strawberry.Info, teacher_id: strawberry.ID
    ) -> TeacherWorkload:
        from . import constraint_services

        return workload_to_graphql(
            constraint_services.get_workload_rule(str(teacher_id))
        )

    @strawberry.field(
        permission_classes=[
            IsAuthenticated,
            RequiresTenant,
            requires(PERM_LEAVE_MANAGE),
        ],
        description=(
            "Leave requests across the school, for whoever decides them. A "
            "teacher's own requests are a different question and a different "
            "authority."
        ),
    )
    def teacher_leaves(
        self,
        info: strawberry.Info,
        status: Optional[str] = None,
        teacher_id: Optional[strawberry.ID] = None,
    ) -> List[TeacherLeave]:
        from . import constraint_services

        return [
            leave_to_graphql(row)
            for row in constraint_services.list_leaves(
                status=status,
                teacher_id=str(teacher_id) if teacher_id else None,
            )
        ]
