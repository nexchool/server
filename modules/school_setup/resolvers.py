"""GraphQL field for how far a school has got with setting itself up.

⚠️ This read is not free of side effects, and that is deliberate rather than
overlooked: `get_status_payload` recomputes readiness and, if a school that
had confirmed setup no longer qualifies, clears the flag and commits. The
alternative is a stored answer that quietly goes stale — a school that deleted
its last class would still be told it is ready. The REST route has always
behaved this way and the behaviour is kept rather than changed underneath it;
it is registered in the debt register as a query that writes.
"""

from __future__ import annotations

import strawberry

from graphql_api.permissions import IsAuthenticated, RequiresTenant, requires_any

from .graphql.types import SetupStatus, setup_status_to_graphql

# Read off the route, not inferred from the module name.
PERM_READ = "school_setup.read"
PERM_MANAGE = "school_setup.manage"


@strawberry.type
class SchoolSetupQuery:
    @strawberry.field(
        permission_classes=[
            IsAuthenticated,
            RequiresTenant,
            requires_any(PERM_READ, PERM_MANAGE),
        ],
        description=(
            "How far this school has got with setting itself up — each module "
            "it needs, whether that module is ready, and what is missing."
        ),
    )
    def setup_status(self, info: strawberry.Info) -> SetupStatus:
        from .services import get_status_payload

        return setup_status_to_graphql(get_status_payload(info.context.tenant_id))
