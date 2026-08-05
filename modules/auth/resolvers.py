"""GraphQL fields for the Identity module.

Credentials stay on REST, where the backend architecture places infrastructure
concerns. What lives here are the identity questions the application asks about
the person already signed in.
"""

from __future__ import annotations

import strawberry

from graphql_api.errors import NotFoundError, TenantRequiredError
from graphql_api.permissions import IsAuthenticated

from .graphql.types import ActiveContext, SignedInPerson
from .identity_service import available_contexts, person_for


@strawberry.type
class IdentityQuery:
    @strawberry.field(
        permission_classes=[IsAuthenticated],
        description="The person this request is signed in as, and the experiences they may use.",
    )
    def me(self, info: strawberry.Info) -> SignedInPerson:
        context = info.context

        if context.tenant_id is None:
            raise TenantRequiredError(
                context.tenant_error or "This operation requires a tenant."
            )

        user = context.current_user
        person = person_for(user)
        if person is None:
            raise NotFoundError("No person is linked to this account yet.")

        return SignedInPerson(
            id=strawberry.ID(person.id),
            full_name=person.full_name,
            email=person.email,
            phone_number=person.phone_number,
            photo_url=person.photo_url,
            available_contexts=[
                ActiveContext(context_value) for context_value in available_contexts(user)
            ],
        )
