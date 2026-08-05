"""What a client learns about the person it has signed in as."""

from __future__ import annotations

from typing import List, Optional

import strawberry

from ..identity_service import ActiveContext as ActiveContextEnum

# The domain enum is the one definition; this registers it with the schema.
ActiveContext = strawberry.enum(
    ActiveContextEnum,
    description="A business experience the application can present.",
)


@strawberry.type(description="The person this request is signed in as.")
class SignedInPerson:
    id: strawberry.ID
    full_name: str
    email: Optional[str]
    phone_number: Optional[str]
    photo_url: Optional[str]
    available_contexts: List[ActiveContext] = strawberry.field(
        description=(
            "Experiences this person may use, derived from their business "
            "relationships. Most people hold exactly one."
        )
    )
