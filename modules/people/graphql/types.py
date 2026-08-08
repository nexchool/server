"""What a client sees when the school reconciles its records.

Two people who turn out to be one is an ordinary event in a school: a parent
recorded once at admission and again when a second child arrives, a teacher
re-entered by a bulk import. These types describe the suggestion and what a
merge actually did, because both are things a human has to judge.
"""

from __future__ import annotations

import datetime
from typing import Dict, List, Optional

import strawberry


@strawberry.type(
    description=(
        "Enough of a person to tell them from somebody who looks like them."
    )
)
class PersonSummary:
    id: strawberry.ID
    full_name: str
    date_of_birth: Optional[datetime.date] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None
    # What this record *is* in the school. A merge is refused when both sides
    # hold the same one of these, so showing them turns a refusal the reviewer
    # would have walked into into a decision they can make.
    has_account: bool = False
    is_employed: bool = False
    is_student: bool = False


@strawberry.type(
    description=(
        "Two records that may describe the same human, for someone to confirm "
        "or dismiss. A suggestion is never acted on automatically — households "
        "share a phone, so looking alike is a question, not an answer."
    )
)
class DuplicateSuggestion:
    person: PersonSummary
    other: PersonSummary
    reason: str = strawberry.field(
        description="Why these two were put together, in the words a reviewer needs."
    )

    @strawberry.field(
        description=(
            "Why these two cannot be combined, if they cannot. Both holding an "
            "account, an employment or a studentship means two real humans, or "
            "a problem a merge would hide rather than fix."
        )
    )
    def blocked_reason(self) -> Optional[str]:
        for held, label in (
            (("has_account",), "an account"),
            (("is_employed",), "an employment record"),
            (("is_student",), "a student record"),
        ):
            attribute = held[0]
            if getattr(self.person, attribute) and getattr(self.other, attribute):
                return f"Both records hold {label}."
        return None


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


def _summary(row, holdings: Dict[str, Dict[str, bool]]) -> PersonSummary:
    held = holdings.get(row.id, {})
    return PersonSummary(
        id=strawberry.ID(row.id),
        full_name=row.full_name,
        date_of_birth=row.date_of_birth,
        phone_number=row.phone_number,
        email=row.email,
        has_account=held.get("has_account", False),
        is_employed=held.get("is_employed", False),
        is_student=held.get("is_student", False),
    )


def suggestions_to_graphql(found) -> List[DuplicateSuggestion]:
    """Turn id pairs into two people a reviewer can compare.

    The people and what they hold are fetched for the whole batch, not per
    suggestion: a hundred pairs is two hundred ids, and asking per row is the
    N+1 that makes a reconciliation screen unusable on the tenant that most
    needs one.
    """
    from modules.people.service import people_summaries

    wanted = {item.person_id for item in found} | {
        item.other_person_id for item in found
    }
    rows, holdings = people_summaries(wanted)
    return [
        DuplicateSuggestion(
            person=_summary(rows[item.person_id], holdings),
            other=_summary(rows[item.other_person_id], holdings),
            reason=item.reason,
        )
        for item in found
        if item.person_id in rows and item.other_person_id in rows
    ]
