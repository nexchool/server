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
import enum
import json
from typing import Any, Dict, List, Optional

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
    requires_any,
)

from .graphql.types import (
    PageInfo,
    Student,
    StudentConnection,
    StudentEdge,
    student_to_graphql,
)

PERM_READ = "student.read.all"
# A class teacher reads the same field, but only the classes they teach.
PERM_READ_CLASS = "student.read.class"
PERM_UPDATE = "student.update"


@strawberry.enum(description="What a list of students is ordered by.")
class StudentOrder(enum.Enum):
    ADMISSION_NUMBER = "admission_number"
    NAME = "name"
    CLASS = "class"
    PROGRAMME = "programme"
    ROLL_NUMBER = "roll_number"


@strawberry.enum
class OrderDirection(enum.Enum):
    ASC = "asc"
    DESC = "desc"


@strawberry.input(description="Which students to include.")
class StudentFilter:
    search: Optional[str] = None
    search_field: Optional[str] = strawberry.field(
        default=None,
        description="Which field to search: name, admission_number, email, guardian_phone, programme. Omit to search all of them.",
    )
    class_id: Optional[strawberry.ID] = None
    class_ids: Optional[List[strawberry.ID]] = None
    academic_year_id: Optional[strawberry.ID] = None
    school_unit_id: Optional[strawberry.ID] = None
    programme_id: Optional[strawberry.ID] = None
    grade_id: Optional[strawberry.ID] = None
    grade: Optional[str] = None
    status: Optional[str] = None
    gender: Optional[str] = None
    is_transport_opted: Optional[bool] = None
    admitted_from: Optional[datetime.date] = None
    admitted_to: Optional[datetime.date] = None

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


def _encode(values: List[Any]) -> str:
    """Cursors are opaque so clients cannot build one and page from nowhere.

    What is inside is the sort key and its tie-breaker; what a client sees is
    a string it got from us and hands back unchanged.
    """
    return base64.urlsafe_b64encode(json.dumps(values).encode()).decode()


def _decode(cursor: Optional[str]) -> Optional[List[Any]]:
    if not cursor:
        return None
    try:
        values = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    except Exception:
        raise ValidationError("That cursor is not one this server issued.")
    if not isinstance(values, list) or not values:
        raise ValidationError("That cursor is not one this server issued.")
    return values


def _filters_from(where: Optional["StudentFilter"]) -> Dict[str, Any]:
    """The filter input as the service's keyword arguments."""
    if where is None:
        return {}
    return {
        "search": where.search,
        "search_field": where.search_field or "all",
        "class_id": str(where.class_id) if where.class_id else None,
        "class_ids": [str(c) for c in where.class_ids] if where.class_ids else None,
        "academic_year_id": (
            str(where.academic_year_id) if where.academic_year_id else None
        ),
        "school_unit_id": str(where.school_unit_id) if where.school_unit_id else None,
        "programme_id": str(where.programme_id) if where.programme_id else None,
        "grade_id": str(where.grade_id) if where.grade_id else None,
        "student_status": where.status,
        "gender": where.gender,
        "is_transport_opted": where.is_transport_opted,
        "admission_date_from": (
            where.admitted_from.isoformat() if where.admitted_from else None
        ),
        "admission_date_to": (
            where.admitted_to.isoformat() if where.admitted_to else None
        ),
    }


def _class_ceiling(info: strawberry.Info) -> Optional[List[str]]:
    """The classes this caller may see at all, or None for the whole school.

    A class teacher holds `student.read.class`, not `student.read.all`: the
    same field, a smaller school. Returning an empty list is meaningful — a
    teacher who teaches nothing sees nobody, which is not the same as no
    filter at all.
    """
    from modules.rbac.services import has_permission

    user = info.context.current_user
    if has_permission(user.id, PERM_READ):
        return None

    from modules.attendance.services import get_teacher_class_ids

    return get_teacher_class_ids(user.id)


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
        permission_classes=[
            IsAuthenticated,
            RequiresTenant,
            requires_any(PERM_READ, PERM_READ_CLASS),
        ],
        description=(
            "Students of this school. Page with `first` and the previous "
            "page's `endCursor` as `after`; use `offset` only when a "
            "page-number control has to jump, which a cursor cannot express. "
            "A class teacher sees the classes they teach."
        ),
    )
    def students(
        self,
        info: strawberry.Info,
        first: int = 25,
        after: Optional[str] = None,
        offset: Optional[int] = None,
        order_by: StudentOrder = StudentOrder.ADMISSION_NUMBER,
        direction: OrderDirection = OrderDirection.ASC,
        where: Optional[StudentFilter] = None,
    ) -> StudentConnection:
        from .services import CURSORABLE_COLUMNS, cursor_values, students_page

        if after and offset:
            # They answer the same question differently; honouring one would
            # silently ignore the other.
            raise ValidationError(
                "Give either `after` or `offset`, not both."
            )
        if offset is not None and offset < 0:
            raise ValidationError("`offset` cannot be negative.")

        sort_key = order_by.value
        if after and sort_key not in CURSORABLE_COLUMNS:
            raise ValidationError(
                f"Ordering by {sort_key} cannot be paged with a cursor, because "
                "the value may be empty and may change while somebody reads. "
                "Use `offset` with this order."
            )

        filters = _filters_from(where)
        ceiling = _class_ceiling(info)
        rows, has_more = students_page(
            after=_decode(after),
            offset=offset,
            first=first,
            sort_by=sort_key,
            sort_dir=direction.value,
            restrict_class_ids=ceiling,
            **filters,
        )

        # Fetch every class this page mentions before anything asks for
        # one. This is the batching an async DataLoader would do on a tick;
        # the transport is synchronous, so the page does it itself.
        info.context.loaders.classes.prime(row.class_id for row in rows)

        edges = [
            StudentEdge(
                node=student_to_graphql(row),
                cursor=_encode(cursor_values(row, sort_key)),
            )
            for row in rows
        ]
        return StudentConnection(
            edges=edges,
            page_info=PageInfo(
                has_next_page=has_more,
                end_cursor=edges[-1].cursor if edges else None,
            ),
            filters={**filters, "restrict_class_ids": ceiling},
        )

    @strawberry.field(
        permission_classes=[
            IsAuthenticated,
            RequiresTenant,
            requires_any(PERM_READ, PERM_READ_CLASS),
        ],
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
