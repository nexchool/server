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
    """The human behind an account, or None while the backfill is pending."""
    if not user.person_id:
        return None

    from modules.people.models import Person

    return Person.query.get(user.person_id)


def available_contexts(user) -> List[ActiveContext]:
    """Experiences this person may use.

    Derived from relationships rather than stored, so the answer cannot drift
    from the relationships it describes. While the Staff and Student
    relationships are still being migrated, the v1 tables serve as the source —
    the compatibility step ADR-010 calls for.

    Teaching is reported instead of, not in addition to, employment: a teacher
    has one experience in the application, and offering a switch that changes
    nothing would be noise.

    PARENT is absent by design. While a household shares the student's
    credentials there is no separate parent experience to switch to (ADR-011);
    it appears when an organization issues parent logins.
    """
    from modules.students.models import Student
    from modules.teachers.models import Teacher

    if Teacher.query.filter_by(user_id=user.id).first() is not None:
        return [ActiveContext.TEACHER]

    if Student.query.filter_by(user_id=user.id).first() is not None:
        return [ActiveContext.STUDENT]

    return [ActiveContext.STAFF]
