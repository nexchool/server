"""What a client sees of a teacher.

A teacher is the Academic domain's view of a member of staff (ADR-005):
the person and their employment come from People, and what is added here is
the teaching — what they are qualified in, and what they teach.

Every field below was typed against a real payload rather than guessed from
its name. Four types in the previous slice were typed from the name and three
of them were wrong.
"""

from __future__ import annotations

import datetime
from typing import List, Optional

import strawberry


def _date(value) -> Optional[datetime.date]:
    if not value:
        return None
    if isinstance(value, datetime.date):
        return value
    return datetime.date.fromisoformat(str(value)[:10])


@strawberry.type(description="A subject a teacher is assigned to teach.")
class TeacherSubject:
    id: strawberry.ID
    name: str
    code: Optional[str] = None


@strawberry.type(
    description=(
        "Somebody the school employs to teach. Their name, contact and "
        "employment come from their Person and Staff records; what is theirs "
        "alone is the teaching — qualification, specialisation, experience."
    )
)
class Teacher:
    id: strawberry.ID
    name: Optional[str] = strawberry.field(
        default=None, description="From their Person. May be absent only if unlinked."
    )
    employee_id: Optional[str] = strawberry.field(
        default=None, description="Their employee number, held by the employment."
    )
    email: Optional[str] = strawberry.field(
        default=None,
        description="From their login, if they have one — a teacher need not.",
    )
    phone: Optional[str] = None
    address: Optional[str] = None
    designation: Optional[str] = None
    department: Optional[str] = strawberry.field(
        default=None, description="The department's name."
    )
    department_id: Optional[strawberry.ID] = None
    date_of_joining: Optional[datetime.date] = strawberry.field(
        default=None, description="The start of their earliest employment period."
    )
    status: Optional[str] = strawberry.field(
        default=None,
        description=(
            "active or inactive, derived from whether their employment is "
            "open. A teacher does not carry a status of their own."
        ),
    )
    qualification: Optional[str] = None
    specialization: Optional[str] = None
    experience_years: Optional[int] = None
    profile_picture: Optional[str] = None
    user_id: Optional[strawberry.ID] = strawberry.field(
        default=None,
        description=(
            "Their login, if any. Nothing identifies a teacher by this — the "
            "app resolves them through their Person (ADR-005)."
        ),
    )


@strawberry.type(
    name="TeacherDetail",
    description="One teacher, with the subjects they are assigned to teach.",
)
class TeacherDetail(Teacher):
    subjects: List[TeacherSubject] = strawberry.field(default_factory=list)


@strawberry.type(description="A department, as a filter option.")
class DepartmentOption:
    id: strawberry.ID
    name: str


@strawberry.type(
    description=(
        "A page of teachers, with the catalogues its filters offer. The "
        "departments and designations ride along because the screen's filter "
        "bar needs them and a second round-trip for two short lists is waste."
    )
)
class TeacherPage:
    nodes: List[Teacher]
    total_count: int
    has_next_page: bool
    departments: List[DepartmentOption] = strawberry.field(
        default_factory=list,
        description=(
            "Every active department, not only the ones currently used by a "
            "teacher — a filter that only offers what is already chosen "
            "cannot be used to find what is missing."
        ),
    )
    designations: List[str] = strawberry.field(default_factory=list)


def teacher_to_graphql(row: dict, node_type=Teacher):
    return node_type(
        id=strawberry.ID(row["id"]),
        name=row.get("name"),
        employee_id=row.get("employee_id"),
        email=row.get("email"),
        phone=row.get("phone"),
        address=row.get("address"),
        designation=row.get("designation"),
        department=row.get("department"),
        department_id=(
            strawberry.ID(row["department_id"]) if row.get("department_id") else None
        ),
        date_of_joining=_date(row.get("date_of_joining")),
        status=row.get("status"),
        qualification=row.get("qualification"),
        specialization=row.get("specialization"),
        experience_years=row.get("experience_years"),
        profile_picture=row.get("profile_picture"),
        user_id=strawberry.ID(row["user_id"]) if row.get("user_id") else None,
    )


def teachers_to_graphql(rows) -> List[Teacher]:
    return [teacher_to_graphql(row) for row in rows]


def teacher_detail_to_graphql(row: dict) -> TeacherDetail:
    node = teacher_to_graphql(row, TeacherDetail)
    node.subjects = [
        TeacherSubject(
            id=strawberry.ID(subject["id"]),
            name=subject.get("name") or "",
            code=subject.get("code"),
        )
        for subject in (row.get("subjects") or [])
    ]
    return node


@strawberry.type(
    description=(
        "A subject a teacher is assigned to. The assignment, not the "
        "catalogue entry — `subjectId` names the subject itself."
    )
)
class TeacherSubjectAssignment:
    id: strawberry.ID
    teacher_id: strawberry.ID
    subject_id: strawberry.ID
    subject_name: Optional[str] = None
    subject_code: Optional[str] = None


@strawberry.type(
    description=(
        "Whether a teacher is free in one period of one day. Rows exist only "
        "where a school has said something; silence means no constraint."
    )
)
class TeacherAvailability:
    id: strawberry.ID
    teacher_id: strawberry.ID
    day_of_week: int = strawberry.field(description="0 = Monday.")
    period_number: int = 0
    available: bool = True


@strawberry.type(
    description=(
        "How much a teacher may be asked to teach. Null where the school has "
        "set no ceiling, which is not the same as a ceiling of nil."
    )
)
class TeacherWorkload:
    id: Optional[strawberry.ID] = None
    teacher_id: Optional[strawberry.ID] = None
    max_periods_per_day: Optional[int] = None
    max_periods_per_week: Optional[int] = None


@strawberry.type(
    description=(
        "A teacher's request to be away. `workingDays` is what it costs their "
        "balance — weekends and closures inside the range do not count."
    )
)
class TeacherLeave:
    id: strawberry.ID
    teacher_id: strawberry.ID
    teacher_name: Optional[str] = None
    teacher_employee_id: Optional[str] = None
    teacher_profile_picture: Optional[str] = None
    leave_type: Optional[str] = None
    status: Optional[str] = strawberry.field(
        default=None, description="pending, approved, rejected or cancelled."
    )
    reason: Optional[str] = None
    start_date: Optional[datetime.date] = None
    end_date: Optional[datetime.date] = None
    working_days: Optional[float] = None
    academic_year: Optional[str] = None


def teacher_subject_to_graphql(row: dict) -> TeacherSubjectAssignment:
    return TeacherSubjectAssignment(
        id=strawberry.ID(row["id"]),
        teacher_id=strawberry.ID(row["teacher_id"]),
        subject_id=strawberry.ID(row["subject_id"]),
        subject_name=row.get("subject_name"),
        subject_code=row.get("subject_code"),
    )


def availability_to_graphql(row: dict) -> TeacherAvailability:
    return TeacherAvailability(
        id=strawberry.ID(row["id"]),
        teacher_id=strawberry.ID(row["teacher_id"]),
        day_of_week=int(row.get("day_of_week") or 0),
        period_number=int(row.get("period_number") or 0),
        available=bool(row.get("available", True)),
    )


def workload_to_graphql(row) -> TeacherWorkload:
    row = row or {}
    return TeacherWorkload(
        id=strawberry.ID(row["id"]) if row.get("id") else None,
        teacher_id=(
            strawberry.ID(row["teacher_id"]) if row.get("teacher_id") else None
        ),
        max_periods_per_day=row.get("max_periods_per_day"),
        max_periods_per_week=row.get("max_periods_per_week"),
    )


def leave_to_graphql(row: dict) -> TeacherLeave:
    return TeacherLeave(
        id=strawberry.ID(row["id"]),
        teacher_id=strawberry.ID(row["teacher_id"]),
        teacher_name=row.get("teacher_name"),
        teacher_employee_id=row.get("teacher_employee_id"),
        teacher_profile_picture=row.get("teacher_profile_picture"),
        leave_type=row.get("leave_type"),
        status=row.get("status"),
        reason=row.get("reason"),
        start_date=_date(row.get("start_date")),
        end_date=_date(row.get("end_date")),
        working_days=row.get("working_days"),
        academic_year=row.get("academic_year"),
    )
