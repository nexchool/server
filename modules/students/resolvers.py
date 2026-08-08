"""GraphQL fields for the Students module — the shape other modules copy.

Three things here are the pattern rather than the feature:

Paging walks by key, not by offset, because a fifteen-thousand-student trust
is the product's stated scale and OFFSET gets slower the further you read.

The class each student sits in is fetched by a loader, so a page of a
hundred costs one query for the classes rather than a hundred.

Every field states what it requires — signed in, a school resolved, and the
Business Action it performs. With no tenant resolved the ORM scope is inert,
so a field that forgets is a field that reads every school.
"""

from __future__ import annotations

import base64
from typing import Optional

import strawberry

from graphql_api.permissions import IsAuthenticated, RequiresTenant, requires

from .graphql.types import (
    PageInfo,
    Student,
    StudentConnection,
    StudentEdge,
    student_to_graphql,
)

PERM_READ = "student.read.all"


def _encode(admission_number: str) -> str:
    """Cursors are opaque so clients cannot build one and page from nowhere."""
    return base64.urlsafe_b64encode(admission_number.encode()).decode()


def _decode(cursor: Optional[str]) -> Optional[str]:
    if not cursor:
        return None
    try:
        return base64.urlsafe_b64decode(cursor.encode()).decode()
    except Exception:
        return None


@strawberry.type
class StudentQuery:
    @strawberry.field(
        permission_classes=[IsAuthenticated, RequiresTenant, requires(PERM_READ)],
        description=(
            "Students of this school, in admission-number order. Page with "
            "`first` and the previous page's `endCursor` as `after`."
        ),
    )
    def students(
        self,
        info: strawberry.Info,
        first: int = 25,
        after: Optional[str] = None,
        search: Optional[str] = None,
        class_id: Optional[strawberry.ID] = None,
        academic_year_id: Optional[strawberry.ID] = None,
        status: Optional[str] = None,
    ) -> StudentConnection:
        from .services import students_page

        filters = {
            "search": search,
            "class_id": str(class_id) if class_id else None,
            "academic_year_id": str(academic_year_id) if academic_year_id else None,
            "student_status": status,
        }
        rows, has_more = students_page(
            after=_decode(after), first=first, **filters
        )

        # Fetch every class this page mentions before anything asks for
        # one. This is the batching an async DataLoader would do on a tick;
        # the transport is synchronous, so the page does it itself.
        info.context.loaders.classes.prime(row.class_id for row in rows)

        edges = [
            StudentEdge(
                node=student_to_graphql(row), cursor=_encode(row.admission_number)
            )
            for row in rows
        ]
        return StudentConnection(
            edges=edges,
            page_info=PageInfo(
                has_next_page=has_more,
                end_cursor=edges[-1].cursor if edges else None,
            ),
            filters=filters,
        )

    @strawberry.field(
        permission_classes=[IsAuthenticated, RequiresTenant, requires(PERM_READ)],
        description="One student of this school.",
    )
    def student(self, info: strawberry.Info, id: strawberry.ID) -> Optional[Student]:
        from .services import get_student_row

        row = get_student_row(str(id))
        return student_to_graphql(row) if row is not None else None
