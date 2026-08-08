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
import datetime
from typing import Any, Dict, Optional

import strawberry

from graphql_api.errors import (
    ConflictError,
    NotFoundError,
    TenantRequiredError,
    ValidationError,
)
from graphql_api.permissions import (
    IsAuthenticated,
    RequiresTenant,
    SetupComplete,
    requires,
)

from .graphql.types import (
    PageInfo,
    Student,
    StudentConnection,
    StudentEdge,
    student_to_graphql,
)

PERM_READ = "student.read.all"
PERM_UPDATE = "student.update"

# Changing where a student stands with the school is one authority, whichever
# of the workflows does it — the REST routes these replace all ask for the
# same key.
WRITES = [IsAuthenticated, RequiresTenant, SetupComplete, requires(PERM_UPDATE)]

# What kind of "no" each refusal is. Anything absent is a state conflict:
# the request was well formed and the school is real, the student is simply
# not in a position for this to happen.
_REFUSALS = {
    "TENANT_REQUIRED": TenantRequiredError,
    "NOT_FOUND": NotFoundError,
    "CLASS_NOT_FOUND": NotFoundError,
    "WRONG_YEAR": ValidationError,
    "PLACEMENT_FAILED": ValidationError,
}


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


def _completed(outcome: Dict[str, Any], student_id: str) -> Student:
    """The student the workflow just changed, or the reason it did not.

    A workflow answers with a dict because REST asked first and reads it that
    way. GraphQL has an error contract instead, so a refusal is raised with
    the code the service gave it — never inferred from the message, which is
    written for a person and will be reworded.
    """
    if not outcome.get("success"):
        refusal = _REFUSALS.get(outcome.get("code"), ConflictError)
        raise refusal(outcome.get("error") or "The workflow could not be completed")

    from .services import get_student_row

    row = get_student_row(student_id)
    if row is None:
        raise NotFoundError("Student not found")
    return student_to_graphql(row)


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


@strawberry.type
class StudentMutation:
    """What a school does to a student, named as the school names it.

    Each of these is a workflow, not a field assignment: a date, a reason, the
    end or start of a place in a class, and a record that it happened. None of
    them sets `status` — that is the point of them existing. A mutation called
    `updateStudentStatus` would put the school's history back in the hands of
    whoever remembered to write the rest of it.
    """

    @strawberry.mutation(
        permission_classes=WRITES,
        description=(
            "A student leaves before completing their education. Their place "
            "in a class ends; nothing about them is deleted, so a child who "
            "comes back is the same child."
        ),
    )
    def withdraw_student(
        self,
        info: strawberry.Info,
        id: strawberry.ID,
        reason: Optional[str] = None,
        occurred_on: Optional[datetime.date] = None,
    ) -> Student:
        from . import lifecycle_service

        return _completed(
            lifecycle_service.withdraw_student(
                str(id),
                reason=reason,
                occurred_on=occurred_on,
                recorded_by_user_id=info.context.current_user.id,
            ),
            str(id),
        )

    @strawberry.mutation(
        permission_classes=WRITES,
        description="A student completes their education and leaves finished.",
    )
    def graduate_student(
        self,
        info: strawberry.Info,
        id: strawberry.ID,
        reason: Optional[str] = None,
        occurred_on: Optional[datetime.date] = None,
    ) -> Student:
        from . import lifecycle_service

        return _completed(
            lifecycle_service.graduate_student(
                str(id),
                reason=reason,
                occurred_on=occurred_on,
                recorded_by_user_id=info.context.current_user.id,
            ),
            str(id),
        )

    @strawberry.mutation(
        permission_classes=WRITES,
        description=(
            "A student who left comes back. Not a re-admission: the same "
            "person, the same admission number, a new placement."
        ),
    )
    def re_enroll_student(
        self,
        info: strawberry.Info,
        id: strawberry.ID,
        class_id: strawberry.ID,
        academic_year_id: Optional[strawberry.ID] = None,
        reason: Optional[str] = None,
        occurred_on: Optional[datetime.date] = None,
    ) -> Student:
        from . import lifecycle_service

        return _completed(
            lifecycle_service.reenroll_student(
                str(id),
                class_id=str(class_id),
                academic_year_id=str(academic_year_id) if academic_year_id else None,
                reason=reason,
                occurred_on=occurred_on,
                recorded_by_user_id=info.context.current_user.id,
            ),
            str(id),
        )

    @strawberry.mutation(
        permission_classes=WRITES,
        description=(
            "A student moves to another section of the same year — 8A to 8B. "
            "Still an active student: moving rooms is not leaving."
        ),
    )
    def transfer_student_to_section(
        self,
        info: strawberry.Info,
        id: strawberry.ID,
        to_class_id: strawberry.ID,
        reason: Optional[str] = None,
        occurred_on: Optional[datetime.date] = None,
    ) -> Student:
        from . import lifecycle_service

        return _completed(
            lifecycle_service.transfer_section(
                str(id),
                to_class_id=str(to_class_id),
                reason=reason,
                occurred_on=occurred_on,
                recorded_by_user_id=info.context.current_user.id,
            ),
            str(id),
        )

    @strawberry.mutation(
        permission_classes=WRITES,
        description=(
            "A student leaves this school for another one. Kept apart from "
            "withdrawal because a school issues a transfer certificate for "
            "this and wants to find it again."
        ),
    )
    def transfer_student_out(
        self,
        info: strawberry.Info,
        id: strawberry.ID,
        destination_school: Optional[str] = None,
        reason: Optional[str] = None,
        occurred_on: Optional[datetime.date] = None,
    ) -> Student:
        from . import lifecycle_service

        return _completed(
            lifecycle_service.transfer_out(
                str(id),
                destination_school=destination_school,
                reason=reason,
                occurred_on=occurred_on,
                recorded_by_user_id=info.context.current_user.id,
            ),
            str(id),
        )
