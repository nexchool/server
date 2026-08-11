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

    Identity does not know what those relationships are — it asks People, which
    owns the question of what a person is to the organization. What Identity
    decides is how to *present* the answer, which is its own business:

    Teaching is presented instead of, not in addition to, employment: a teacher
    has one experience in the application, and offering a switch that changes
    nothing would be noise.

    PARENT is absent by design. While a household shares the student's
    credentials there is no separate parent experience to switch to (ADR-011);
    it appears when an organization issues parent logins, at which point family
    membership becomes a context rather than only a relationship.
    """
    from modules.people.relationships import PersonRelationship, relationships_held_by

    held = relationships_held_by(user.person)

    contexts: List[ActiveContext] = []

    if PersonRelationship.TEACHING in held:
        contexts.append(ActiveContext.TEACHER)
    elif PersonRelationship.EMPLOYMENT in held:
        contexts.append(ActiveContext.STAFF)

    if PersonRelationship.STUDENTSHIP in held:
        contexts.append(ActiveContext.STUDENT)

    return contexts
