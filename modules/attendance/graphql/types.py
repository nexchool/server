"""What a client sees of a correction to settled attendance.

A correction is not an edit. It carries what the register said, what it
should say, why, who asked and who decided — because the point of the
workflow is that a changed mark can be accounted for afterwards.
"""

from __future__ import annotations

import datetime
from typing import List, Optional

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
    requested_at: Optional[datetime.datetime] = None
    decided_at: Optional[datetime.datetime] = None
    decision_note: Optional[str] = None

    # Who and when this is about. A queue of ids is not something a person can
    # decide on — the reviewer needs the child, the class and the day.
    student_id: Optional[strawberry.ID] = None
    student_name: Optional[str] = None
    class_name: Optional[str] = None
    session_date: Optional[datetime.date] = None
    requested_by_name: Optional[str] = None
    decided_by_name: Optional[str] = None


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


def correction_to_graphql(row, context=None) -> AttendanceCorrection:
    """One correction, with the people and the day it is about.

    `context` comes from `correction_service.context_for`, which fetches it
    for a whole batch. Passing nothing yields the correction alone — fine for
    a single row, wrong for a queue.
    """
    about = (context or {}).get(row.id, {})
    return AttendanceCorrection(
        id=strawberry.ID(row.id),
        attendance_record_id=strawberry.ID(row.attendance_record_id),
        from_status=row.from_status,
        to_status=row.to_status,
        reason=row.reason,
        status=row.status,
        requested_at=row.requested_at,
        decided_at=row.decided_at,
        decision_note=row.decision_note,
        student_id=(
            strawberry.ID(about["student_id"]) if about.get("student_id") else None
        ),
        student_name=about.get("student_name"),
        class_name=about.get("class_name"),
        session_date=about.get("session_date"),
        requested_by_name=about.get("requested_by_name"),
        decided_by_name=about.get("decided_by_name"),
    )


@strawberry.type(description="One day of a student's attendance.")
class AttendanceDay:
    date: datetime.date
    status: str
    remarks: Optional[str] = None
    session_id: Optional[strawberry.ID] = None


@strawberry.type(
    description=(
        "A student's attendance over a month, or over their whole time at the "
        "school when no month is named."
    )
)
class StudentAttendance:
    student_id: strawberry.ID
    total_days: int = strawberry.field(description="Days the register was taken.")
    present: int
    absent: int
    late: int
    percentage: float
    days: List[AttendanceDay]


def student_attendance_to_graphql(data) -> StudentAttendance:
    return StudentAttendance(
        student_id=strawberry.ID(data["student_id"]),
        total_days=data["total_days"],
        present=data["present"],
        absent=data["absent"],
        late=data["late"],
        percentage=data["percentage"],
        days=[
            AttendanceDay(
                date=datetime.date.fromisoformat(record["date"]),
                status=record["status"],
                remarks=record.get("remarks"),
                session_id=(
                    strawberry.ID(record["session_id"])
                    if record.get("session_id")
                    else None
                ),
            )
            for record in data["records"]
        ],
    )
