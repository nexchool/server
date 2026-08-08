"""GraphQL fields for Attendance — starting with corrections.

Marking attendance is a teacher's daily work and already has a surface.
Changing a mark after the register has settled is a different act with a
different authority, and until now it had no surface at all: the workflow
was complete and tested, and unreachable by the people who need it.

Attendance is an optional module — a school may still be on paper — so every
field here states that too. The pilot never needed a feature gate because
students cannot be switched off; this is the first module where forgetting
one would let a school work through a door it had closed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import strawberry

from graphql_api.errors import ConflictError, NotFoundError, ValidationError
from graphql_api.permissions import (
    IsAuthenticated,
    RequiresTenant,
    SetupComplete,
    requires,
    requires_any,
    requires_feature,
)

from .graphql.types import (
    AttendanceCorrection,
    CorrectionOutcome,
    correction_to_graphql,
)

FEATURE = "attendance"

# Marking the register and running it are different jobs. A teacher may ask
# for a mark to be changed; deciding on that request belongs to whoever the
# school has made answerable for the register as a whole.
PERM_MARK = "attendance.mark"
PERM_MANAGE = "attendance.manage"

_ASKS = [
    IsAuthenticated,
    RequiresTenant,
    SetupComplete,
    requires_feature(FEATURE),
    requires_any(PERM_MARK, PERM_MANAGE),
]
_DECIDES = [
    IsAuthenticated,
    RequiresTenant,
    SetupComplete,
    requires_feature(FEATURE),
    requires(PERM_MANAGE),
]
_READS_DECISIONS = [
    IsAuthenticated,
    RequiresTenant,
    requires_feature(FEATURE),
    requires(PERM_MANAGE),
]

_REFUSALS = {
    "NOT_FOUND": NotFoundError,
    "INVALID_STATUS": ValidationError,
    "REASON_REQUIRED": ValidationError,
}


def _completed(outcome: Dict[str, Any]) -> Dict[str, Any]:
    """The outcome, or the reason there isn't one.

    Anything without a code is a state conflict: the request was well formed
    and the correction is real, it is simply not in a position for this.
    """
    if not outcome.get("success"):
        refusal = _REFUSALS.get(outcome.get("code"), ConflictError)
        raise refusal(outcome.get("error") or "The correction could not be recorded")
    return outcome


def _may_decide(info: strawberry.Info) -> bool:
    from modules.rbac.services import has_permission

    return has_permission(info.context.current_user.id, PERM_MANAGE)


@strawberry.type
class AttendanceQuery:
    @strawberry.field(
        permission_classes=_READS_DECISIONS,
        description=(
            "Corrections waiting for somebody to decide on them. The queue of "
            "marks a teacher has asked to change and nobody has answered."
        ),
    )
    def pending_attendance_corrections(
        self, info: strawberry.Info
    ) -> List[AttendanceCorrection]:
        from .correction_service import context_for, pending_corrections

        rows = pending_corrections(info.context.tenant_id)
        about = context_for(rows)
        return [correction_to_graphql(row, about) for row in rows]

    @strawberry.field(
        permission_classes=[
            IsAuthenticated,
            RequiresTenant,
            requires_feature(FEATURE),
            requires_any(PERM_MARK, PERM_MANAGE),
        ],
        description=(
            "Every change ever asked for on one register entry, oldest first "
            "— what a mark's history looks like when somebody queries it."
        ),
    )
    def attendance_record_corrections(
        self, info: strawberry.Info, record_id: strawberry.ID
    ) -> List[AttendanceCorrection]:
        from .correction_service import context_for, corrections_for_record

        rows = corrections_for_record(info.context.tenant_id, str(record_id))
        about = context_for(rows)
        return [correction_to_graphql(row, about) for row in rows]


@strawberry.type
class AttendanceMutation:
    @strawberry.mutation(
        permission_classes=_ASKS,
        description=(
            "Ask for settled attendance to be changed. Applied at once where "
            "the school does not review corrections, or where the person "
            "asking could have approved it anyway — asking yourself for "
            "permission is a step, not a control. The request is written down "
            "either way, so the change is never the only evidence of itself."
        ),
    )
    def request_attendance_correction(
        self,
        info: strawberry.Info,
        record_id: strawberry.ID,
        to_status: str,
        reason: str,
    ) -> CorrectionOutcome:
        from .correction_service import request_correction

        outcome = _completed(
            request_correction(
                info.context.tenant_id,
                str(record_id),
                to_status=to_status,
                reason=reason,
                requested_by_user_id=info.context.current_user.id,
                may_decide=_may_decide(info),
            )
        )
        return CorrectionOutcome(
            correction=_reread(info, str(outcome["correction"]["id"])),
            applied=bool(outcome.get("applied")),
        )

    @strawberry.mutation(
        permission_classes=_DECIDES,
        description="Agree to the change, and make it.",
    )
    def approve_attendance_correction(
        self,
        info: strawberry.Info,
        id: strawberry.ID,
        note: Optional[str] = None,
    ) -> AttendanceCorrection:
        from .correction_service import approve_correction

        _completed(
            approve_correction(
                info.context.tenant_id,
                str(id),
                decided_by_user_id=info.context.current_user.id,
                note=note,
            )
        )
        return _reread(info, str(id))

    @strawberry.mutation(
        permission_classes=_DECIDES,
        description="Decline the change. The record stands, the request is kept.",
    )
    def reject_attendance_correction(
        self,
        info: strawberry.Info,
        id: strawberry.ID,
        note: Optional[str] = None,
    ) -> AttendanceCorrection:
        from .correction_service import reject_correction

        _completed(
            reject_correction(
                info.context.tenant_id,
                str(id),
                decided_by_user_id=info.context.current_user.id,
                note=note,
            )
        )
        return _reread(info, str(id))


def _reread(info: strawberry.Info, correction_id: str) -> AttendanceCorrection:
    """The correction as it now stands.

    Read back through the service rather than mapped from its dict: the dict
    is the shape REST asked for, and a second shape maintained by hand is a
    second thing to keep in step. Asked of the service rather than the model
    so the read is not something only GraphQL can do.
    """
    from .correction_service import context_for, correction_by_id

    row = correction_by_id(info.context.tenant_id, correction_id)
    if row is None:
        raise NotFoundError("Correction not found")
    return correction_to_graphql(row, context_for([row]))
