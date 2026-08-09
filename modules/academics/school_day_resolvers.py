"""GraphQL fields for what a class is taught, by whom, and to what clock.

Three fields, three different gates, each read off its own route rather than
assumed from the neighbourhood:

    classSubjects     class_subject.read|manage or class.manage
                      behind class_management (CORE — no gate)
    subjectTeachers   the same authorities
                      behind TIMETABLE (optional — gated)
    bellSchedules     academics.read|manage or timetable.manage
                      behind TIMETABLE (optional — gated)

The first two share their permissions and differ only in feature, which is
exactly the kind of near-miss that a single shared constant would paper over:
a school with no timetable still has subjects on its classes.

The REST routes stay — the Expo client reads all three — and both transports
call the same services, so the shapes cannot drift.
"""

from __future__ import annotations

from typing import List, Optional

import strawberry

from graphql_api.errors import ValidationError
from graphql_api.permissions import (
    IsAuthenticated,
    RequiresTenant,
    requires_any,
    requires_feature,
)

from .graphql.school_day_types import (
    BellSchedule,
    BellScheduleDetail,
    BellScheduleList,
    ClassSubject,
    SubjectTeacher,
    bell_schedule_detail_to_graphql,
    bell_schedule_to_graphql,
    class_subject_to_graphql,
    subject_teacher_to_graphql,
)

PERM_CS_READ = "class_subject.read"
PERM_CS_MANAGE = "class_subject.manage"
PERM_CLASS_MANAGE = "class.manage"
PERM_ACADEMICS_READ = "academics.read"
PERM_ACADEMICS_MANAGE = "academics.manage"
PERM_TIMETABLE_MANAGE = "timetable.manage"

CLASS_SUBJECT_AUTHORITIES = requires_any(
    PERM_CS_READ, PERM_CS_MANAGE, PERM_CLASS_MANAGE
)


def _answered(result: dict, what: str):
    if not result.get("success"):
        raise ValidationError(result.get("error") or f"Could not read {what}")
    return result


@strawberry.type
class SchoolDayQuery:
    @strawberry.field(
        permission_classes=[IsAuthenticated, RequiresTenant, CLASS_SUBJECT_AUTHORITIES],
        description=(
            "The subjects a class is taught, and how much of the week each "
            "gets. No feature gate: a school without a timetable still has "
            "subjects on its classes."
        ),
    )
    def class_subjects(
        self, info: strawberry.Info, class_id: strawberry.ID
    ) -> List[ClassSubject]:
        from modules.academics.services import class_subjects as service

        result = _answered(
            service.list_for_class(info.context.tenant_id, str(class_id)),
            "the class's subjects",
        )
        return [class_subject_to_graphql(row) for row in result.get("items", [])]

    @strawberry.field(
        permission_classes=[
            IsAuthenticated,
            RequiresTenant,
            requires_feature("timetable"),
            CLASS_SUBJECT_AUTHORITIES,
        ],
        description=(
            "Who teaches each of a class's subjects, and from when. Dated, so "
            "a hand-over mid-year leaves the earlier term naming whoever "
            "actually taught it."
        ),
    )
    def subject_teachers(
        self, info: strawberry.Info, class_id: strawberry.ID
    ) -> List[SubjectTeacher]:
        from modules.academics.services import class_subject_teachers as service

        result = _answered(
            service.list_for_class(info.context.tenant_id, str(class_id)),
            "who teaches this class",
        )
        return [subject_teacher_to_graphql(row) for row in result.get("items", [])]

    @strawberry.field(
        permission_classes=[
            IsAuthenticated,
            RequiresTenant,
            requires_feature("timetable"),
            requires_any(
                PERM_ACADEMICS_READ, PERM_ACADEMICS_MANAGE, PERM_TIMETABLE_MANAGE
            ),
        ],
        description=(
            "The clocks this school teaches to, and which one it falls back "
            "to when a class names none."
        ),
    )
    def bell_schedules(self, info: strawberry.Info) -> BellScheduleList:
        from modules.academics.services import bell_schedules as service

        result = _answered(
            service.list_schedules(info.context.tenant_id), "the bell schedules"
        )
        return BellScheduleList(
            items=[bell_schedule_to_graphql(row) for row in result.get("items", [])],
            default_bell_schedule_id=(
                strawberry.ID(result["tenant_default_bell_schedule_id"])
                if result.get("tenant_default_bell_schedule_id")
                else None
            ),
        )

    @strawberry.field(
        permission_classes=[
            IsAuthenticated,
            RequiresTenant,
            requires_feature("timetable"),
            requires_any(
                PERM_ACADEMICS_READ, PERM_ACADEMICS_MANAGE, PERM_TIMETABLE_MANAGE
            ),
        ],
        description=(
            "One clock, with its periods and how many timetables depend on "
            "it — which is what a school breaks by editing it."
        ),
    )
    def bell_schedule(
        self, info: strawberry.Info, id: strawberry.ID
    ) -> Optional[BellScheduleDetail]:
        from modules.academics.services import bell_schedules as service

        result = service.get_schedule(
            info.context.tenant_id, str(id), include_periods=True
        )
        if not result.get("success"):
            return None
        return bell_schedule_detail_to_graphql(result["bell_schedule"])
