"""What a client sees when the school reconciles its records.

Two people who turn out to be one is an ordinary event in a school: a parent
recorded once at admission and again when a second child arrives, a teacher
re-entered by a bulk import. These types describe the suggestion and what a
merge actually did, because both are things a human has to judge.
"""

from __future__ import annotations

from typing import List, Optional

import strawberry


@strawberry.type(
    description=(
        "Two records that may describe the same human, for someone to confirm "
        "or dismiss. A suggestion is never acted on automatically — households "
        "share a phone, so looking alike is a question, not an answer."
    )
)
class DuplicateSuggestion:
    person_id: strawberry.ID
    other_person_id: strawberry.ID
    reason: str = strawberry.field(
        description="Why these two were put together, in the words a reviewer needs."
    )


@strawberry.type(
    description=(
        "What a merge combined. Recorded so the decision can be understood "
        "later — and, if it was wrong, unpicked by someone who can see what "
        "was folded in."
    )
)
class PersonMerge:
    id: strawberry.ID
    kept_person_id: strawberry.ID
    absorbed_person_id: strawberry.ID
    reason: Optional[str]
    merged_at: str = strawberry.field(description="ISO-8601, in UTC.")


@strawberry.type(
    description="The surviving person, and the record of what was merged into them."
)
class MergeResult:
    person_id: strawberry.ID
    full_name: str
    merge: PersonMerge


def suggestions_to_graphql(found) -> List[DuplicateSuggestion]:
    return [
        DuplicateSuggestion(
            person_id=strawberry.ID(item.person_id),
            other_person_id=strawberry.ID(item.other_person_id),
            reason=item.reason,
        )
        for item in found
    ]
