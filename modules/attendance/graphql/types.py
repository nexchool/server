"""What a client sees of a correction to settled attendance.

A correction is not an edit. It carries what the register said, what it
should say, why, who asked and who decided — because the point of the
workflow is that a changed mark can be accounted for afterwards.
"""

from __future__ import annotations

import datetime
from typing import Optional

import strawberry


@strawberry.type(description="A request to change settled attendance.")
class AttendanceCorrection:
    id: strawberry.ID
    attendance_record_id: strawberry.ID
    from_status: str = strawberry.field(description="What the register said.")
    to_status: str = strawberry.field(description="What it should say.")
    reason: str = strawberry.field(
        description="Why. Required — a correction without one is an edit."
    )
    status: str = strawberry.field(
        description="requested, approved or rejected."
    )
    requested_by_user_id: Optional[strawberry.ID] = None
    requested_at: Optional[datetime.datetime] = None
    decided_by_user_id: Optional[strawberry.ID] = None
    decided_at: Optional[datetime.datetime] = None
    decision_note: Optional[str] = None


@strawberry.type(description="A correction, and whether it took effect at once.")
class CorrectionOutcome:
    correction: AttendanceCorrection
    applied: bool = strawberry.field(
        description=(
            "True when the register already reflects the change — either the "
            "school does not require review, or the person asking could have "
            "approved it themselves."
        )
    )


def correction_to_graphql(row) -> AttendanceCorrection:
    return AttendanceCorrection(
        id=strawberry.ID(row.id),
        attendance_record_id=strawberry.ID(row.attendance_record_id),
        from_status=row.from_status,
        to_status=row.to_status,
        reason=row.reason,
        status=row.status,
        requested_by_user_id=(
            strawberry.ID(row.requested_by_user_id)
            if row.requested_by_user_id
            else None
        ),
        requested_at=row.requested_at,
        decided_by_user_id=(
            strawberry.ID(row.decided_by_user_id) if row.decided_by_user_id else None
        ),
        decided_at=row.decided_at,
        decision_note=row.decision_note,
    )
