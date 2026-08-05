"""Identity questions about the signed-in person.

Business logic only: no transport types, no HTTP, no GraphQL.
"""

from __future__ import annotations

import enum
from typing import List, Optional


class ActiveContext(enum.Enum):
    """A business experience the application can present (ADR-004)."""

    STAFF = "staff"
    TEACHER = "teacher"
    STUDENT = "student"
    PARENT = "parent"


def person_for(user) -> Optional[object]:
    """The human behind an account."""
    return user.person


def available_contexts(user) -> List[ActiveContext]:
    """Experiences this person may use.

    Derived from business relationships rather than stored, so the answer cannot
    drift from the relationships it describes.

    Every relationship is read through the Person: employment from Staff,
    teaching from the participation hanging off that employment (ADR-005), and
    studentship from the Student relationship. Nothing here is derived from the
    login any more.

    Teaching is reported instead of, not in addition to, employment: a teacher
    has one experience in the application, and offering a switch that changes
    nothing would be noise.

    PARENT is absent by design. While a household shares the student's
    credentials there is no separate parent experience to switch to (ADR-011);
    it appears when an organization issues parent logins.
    """
    from modules.people.employment import Staff
    from modules.students.models import Student
    from modules.teachers.models import Teacher

    if not user.person_id:
        return []

    contexts: List[ActiveContext] = []

    employment = Staff.query.filter_by(person_id=user.person_id).first()
    if employment is not None and employment.is_employed:
        teaches = Teacher.query.filter_by(staff_id=employment.id).first() is not None
        contexts.append(ActiveContext.TEACHER if teaches else ActiveContext.STAFF)

    if Student.query.filter_by(person_id=user.person_id).first() is not None:
        contexts.append(ActiveContext.STUDENT)

    return contexts
