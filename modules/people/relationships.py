"""What a person is to the organization.

A person's standing relationships — they work here, they teach, they study
here, they belong to a family here — are People's own business (ADR-001). The
rows live in modules named after the departments that use them, which is where
v1 put them and where ADR-012 leaves them.

So each owning module declares its relationship *back onto* Person or Staff,
and People reads what has been declared. People imports nothing from Academic:
the dependency runs the direction the architecture says it does, and asking
"what is this person to us?" costs one place to look instead of three.
"""

from __future__ import annotations

import enum
from typing import Set


class PersonRelationship(enum.Enum):
    """A standing relationship between a person and the organization."""

    EMPLOYMENT = "employment"
    TEACHING = "teaching"
    STUDENTSHIP = "studentship"
    FAMILY_MEMBERSHIP = "family_membership"


def relationships_held_by(person) -> Set[PersonRelationship]:
    """The relationships this person holds with the organization right now.

    Employment that has ended is not a relationship they hold — it is one they
    held — so it is left out, and the teaching that hangs off it goes with it
    (ADR-005). Teaching is reported *alongside* the employment rather than
    instead of it: whether a teacher is shown one experience or two is a
    presentation question, and this answers a business one.
    """
    if person is None:
        return set()

    held: Set[PersonRelationship] = set()

    for employment in person.employments:
        if not employment.is_employed:
            continue
        held.add(PersonRelationship.EMPLOYMENT)
        if employment.teaching_participations:
            held.add(PersonRelationship.TEACHING)

    if person.student_relationships:
        held.add(PersonRelationship.STUDENTSHIP)

    if person.family_memberships:
        held.add(PersonRelationship.FAMILY_MEMBERSHIP)

    return held
