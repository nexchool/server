"""GraphQL fields for the People module.

Reconciling records is the one People operation a school performs directly:
noticing that two rows describe one human, and saying so. Everything else
about a person is reached through the relationship that gives them a reason
to be in the system — a student's record, a teacher's employment.

Merging is deliberately two steps. Suggestions are computed and offered;
combining is a separate, explicit act by someone holding the authority for
it. Nothing here merges on its own — a shared household phone looks exactly
like a duplicate and is not one.
"""

from __future__ import annotations

from typing import List, Optional

import strawberry

from graphql_api.errors import ConflictError, NotFoundError
from graphql_api.permissions import IsAuthenticated, RequiresTenant, requires

from .graphql.types import (
    DuplicateSuggestion,
    MergeResult,
    PersonMerge,
    suggestions_to_graphql,
)

# Merging is not editing an account: it rewrites which human the school's
# records refer to, across every module at once. It carries its own key so it
# can be granted to whoever reconciles records, and to nobody else.
PERM_MERGE = "person.merge"


@strawberry.type
class PeopleQuery:
    @strawberry.field(
        permission_classes=[IsAuthenticated, RequiresTenant, requires(PERM_MERGE)],
        description=(
            "People who look like the same human, for someone to judge. "
            "Computed when asked, so the list cannot go stale behind a merge."
        ),
    )
    def duplicate_suggestions(
        self, info: strawberry.Info, limit: int = 100
    ) -> List[DuplicateSuggestion]:
        from .merge import suggest_duplicates

        # Bounded here as well as in the service: a client asking for
        # everything should not be able to make the server pair the school.
        capped = max(1, min(limit, 200))
        return suggestions_to_graphql(
            suggest_duplicates(info.context.tenant_id, limit=capped)
        )


@strawberry.type
class PeopleMutation:
    @strawberry.mutation(
        permission_classes=[IsAuthenticated, RequiresTenant, requires(PERM_MERGE)],
        description=(
            "Combine two records that describe one human. Everything pointing "
            "at the absorbed record is repointed at the one that remains, and "
            "what was combined is written down first."
        ),
    )
    def merge_people(
        self,
        info: strawberry.Info,
        keep: strawberry.ID,
        absorb: strawberry.ID,
        reason: Optional[str] = None,
    ) -> MergeResult:
        from .merge import MergeRefused, merge_people as combine
        from .service import person_on_record

        context = info.context
        # Both must be this school's. The ORM scope already restricts the
        # read, so a person from elsewhere simply is not found — said plainly
        # rather than reported as a merge failure.
        for person_id in (keep, absorb):
            if person_on_record(str(person_id)) is None:
                raise NotFoundError(f"No person with id {person_id}")

        try:
            record = combine(
                str(keep),
                str(absorb),
                reason=reason,
                merged_by_user_id=context.current_user.id,
            )
        except MergeRefused as refusal:
            # The service refuses when both sides hold an account, an
            # employment or a studentship — combining them would hide a real
            # problem rather than fix one. That is a conflict to resolve, not
            # a bad request to correct.
            raise ConflictError(str(refusal))

        survivor = person_on_record(record.kept_person_id)
        return MergeResult(
            person_id=strawberry.ID(record.kept_person_id),
            full_name=survivor.full_name if survivor else "",
            merge=PersonMerge(
                id=strawberry.ID(record.id),
                kept_person_id=strawberry.ID(record.kept_person_id),
                absorbed_person_id=strawberry.ID(record.absorbed_person_id),
                reason=record.reason,
                merged_at=record.created_at.isoformat(),
            ),
        )
