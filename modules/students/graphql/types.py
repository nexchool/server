"""What a client sees of a student.

Deliberately narrower than the REST payload. That one grew to carry every
column any screen ever wanted — extended profile, medical notes, four
addresses — and every caller pays for all of it. Here a client asks for what
it renders, so this type exposes what a student *is* and lets the rest be
added when something actually needs it.
"""

from __future__ import annotations

import datetime
from typing import List, Optional

import strawberry


@strawberry.type(description="The class a student currently sits in.")
class StudentClass:
    id: strawberry.ID
    name: Optional[str]
    section: Optional[str]
    grade_name: Optional[str] = None
    programme_name: Optional[str] = None


@strawberry.type(description="A child the school is teaching, or has taught.")
class Student:
    id: strawberry.ID
    admission_number: str
    full_name: str
    status: Optional[str] = strawberry.field(
        description=(
            "Where the student stands with the school. Changed only by the "
            "lifecycle workflows — withdrawal, graduation, transfer — never "
            "by editing this value."
        )
    )
    date_of_birth: Optional[datetime.date] = None
    gender: Optional[str] = None
    roll_number: Optional[int] = None
    guardian_phone: Optional[str] = strawberry.field(
        default=None,
        description=(
            "Contact for the student's guardian. Still a column on the student "
            "row rather than a household read — see the debt register."
        ),
    )

    # Not exposed: the key the class field loads from.
    class_id: strawberry.Private[Optional[str]] = None

    @strawberry.field(
        description="The class this student sits in, if they are placed in one."
    )
    def current_class(self, info: strawberry.Info) -> Optional[StudentClass]:
        """Read from what the page already fetched.

        Asked per student this would be one query per row — the N+1 that a
        list of fifteen thousand children turns into an outage. The page
        primes every class id it contains before returning, so this is a
        dictionary lookup.
        """
        return _class_of(info.context.loaders.classes.get(self.class_id))


@strawberry.type(description="Where a page sits in the whole result.")
class PageInfo:
    has_next_page: bool
    end_cursor: Optional[str] = strawberry.field(
        description="Pass as `after` to continue from here."
    )


@strawberry.type(description="One student, and the cursor that follows them.")
class StudentEdge:
    node: Student
    cursor: str


@strawberry.type(description="A page of students, and how to get the next one.")
class StudentConnection:
    edges: List[StudentEdge]
    page_info: PageInfo

    # What produced this page, so a count can repeat the same filters.
    filters: strawberry.Private[dict]

    @strawberry.field(
        description=(
            "How many students match, ignoring paging. Counted only when "
            "asked — a list that shows no total should not pay for one."
        )
    )
    def total_count(self, info: strawberry.Info) -> int:
        from modules.students.services import students_matching_count

        return students_matching_count(**self.filters)


def _class_of(row) -> Optional[StudentClass]:
    if row is None:
        return None
    return StudentClass(
        id=strawberry.ID(row.id),
        name=row.name,
        section=row.section,
        grade_name=row.grade.name if row.grade else None,
        programme_name=row.programme.name if row.programme else None,
    )


def student_to_graphql(row) -> Student:
    person = row.person
    return Student(
        id=strawberry.ID(row.id),
        admission_number=row.admission_number,
        full_name=person.full_name if person else "",
        status=row.student_status,
        date_of_birth=person.date_of_birth if person else None,
        gender=person.gender if person else None,
        roll_number=row.roll_number,
        guardian_phone=row.guardian_phone,
        class_id=row.class_id,
    )
