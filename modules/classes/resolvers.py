"""GraphQL fields for the classes a school is arranged into.

Three reads, one authority. Unlike the academic structure — where campuses,
programmes, grades and mediums answer to four different permissions — the
list, its totals and one class's detail are all the same Business Action, read
from the routes they replace: `class.read`, with `class.manage` implying it.

No feature gate. Classes are a CORE feature: a school cannot switch them off,
so a gate on them is machinery that never fires.
"""

from __future__ import annotations

import enum
from typing import Any, Dict, List, Optional

import strawberry

from graphql_api.errors import ValidationError
from graphql_api.permissions import IsAuthenticated, RequiresTenant, requires

from .graphql.types import (
    ClassDetail,
    ClassPage,
    ClassStats,
    class_detail_to_graphql,
    classes_to_graphql,
)

# `class.manage` implies every action on a class, so naming the read is the
# whole rule rather than half of it.
PERM_READ = "class.read"


@strawberry.enum(description="What a list of classes is ordered by.")
class ClassOrder(enum.Enum):
    GRADE = "grade"
    NAME = "name"
    PROGRAMME = "programme"
    BRANCH = "branch"
    STUDENT_COUNT = "student_count"
    TEACHER_COUNT = "teacher_count"


@strawberry.enum
class ClassOrderDirection(enum.Enum):
    ASC = "asc"
    DESC = "desc"


@strawberry.enum(description="Which field a search term is matched against.")
class ClassSearchField(enum.Enum):
    ALL = "all"
    NAME = "name"
    SECTION = "section"
    GRADE = "grade"
    PROGRAMME = "programme"
    BRANCH = "branch"


@strawberry.input(description="Which classes to include.")
class ClassFilter:
    search: Optional[str] = None
    search_field: Optional[ClassSearchField] = None
    academic_year_id: Optional[strawberry.ID] = None
    school_unit_id: Optional[strawberry.ID] = None
    programme_id: Optional[strawberry.ID] = None
    grade_id: Optional[strawberry.ID] = None
    department_id: Optional[strawberry.ID] = None


def _filters_from(where: Optional[ClassFilter]) -> Dict[str, Any]:
    """The filter input as the service's keyword arguments.

    Always every key, even when nothing was filtered on: the totals resolver
    reads them by name, and a missing key there is a 500 rather than a total
    over everything.
    """
    if where is None:
        where = ClassFilter()
    return {
        "search": where.search,
        "search_field": (
            where.search_field.value if where.search_field else "all"
        ),
        "academic_year_id": _text(where.academic_year_id),
        "school_unit_id": _text(where.school_unit_id),
        "programme_id": _text(where.programme_id),
        "grade_id": _text(where.grade_id),
        "department_id": _text(where.department_id),
    }


def _text(value: Optional[strawberry.ID]) -> Optional[str]:
    return str(value) if value else None


@strawberry.type
class ClassesQuery:
    @strawberry.field(
        permission_classes=[IsAuthenticated, RequiresTenant, requires(PERM_READ)],
        description=(
            "The classes this school teaches. Page with `first` and `offset`; "
            "a picker that needs them all reads on until `hasNextPage` is "
            "false. Ordered by grade unless told otherwise."
        ),
    )
    def classes(
        self,
        info: strawberry.Info,
        first: int = 25,
        offset: Optional[int] = None,
        order_by: ClassOrder = ClassOrder.GRADE,
        direction: ClassOrderDirection = ClassOrderDirection.ASC,
        where: Optional[ClassFilter] = None,
    ) -> ClassPage:
        from .services import classes_page

        if offset is not None and offset < 0:
            raise ValidationError("`offset` cannot be negative.")

        filters = _filters_from(where)
        rows, has_more = classes_page(
            first=first,
            offset=offset,
            sort_by=order_by.value,
            sort_dir=direction.value,
            **filters,
        )
        return ClassPage(
            nodes=classes_to_graphql(rows),
            has_next_page=has_more,
            filters=filters,
        )

    @strawberry.field(
        permission_classes=[IsAuthenticated, RequiresTenant, requires(PERM_READ)],
        description=(
            "Totals over the same classes `classes` would list, so a header "
            "always describes the list beneath it. Search is not applied: the "
            "totals describe the school's structure, not a lookup in it."
        ),
    )
    def class_stats(
        self, info: strawberry.Info, where: Optional[ClassFilter] = None
    ) -> ClassStats:
        from .services import get_classes_stats

        filters = _filters_from(where)
        stats = get_classes_stats(
            academic_year_id=filters["academic_year_id"],
            school_unit_id=filters["school_unit_id"],
            programme_id=filters["programme_id"],
            grade_id=filters["grade_id"],
            department_id=filters["department_id"],
        )
        return ClassStats(
            total_classes=stats["total_classes"],
            total_students=stats["total_students"],
            total_teachers=stats["total_teachers"],
            average_class_size=stats["average_class_size"],
        )

    @strawberry.field(
        name="class",
        permission_classes=[IsAuthenticated, RequiresTenant, requires(PERM_READ)],
        description=(
            "One class, with the children placed in it and everyone teaching "
            "it."
        ),
    )
    def school_class(
        self, info: strawberry.Info, id: strawberry.ID
    ) -> Optional[ClassDetail]:
        from .services import class_detail

        detail = class_detail(str(id))
        return class_detail_to_graphql(detail) if detail else None
