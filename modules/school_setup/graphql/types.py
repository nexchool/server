"""How ready a school is to be used.

The REST payload is a map keyed by module name — `{units: {...}, grades:
{...}, overall: {...}}` — which a schema cannot express as a record without
inventing a field per module and changing the schema every time a module is
added. So it is a list here: each module says what it is, whether it is ready,
how many of the thing exist, and what is stopping it.

`blockers` are short codes, not sentences (`add_at_least_one_unit`,
`3_classes_without_subjects`). The client turns them into words, because the
words are the client's to translate.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import strawberry


@strawberry.type(description="One thing a school has to set up before it can run.")
class SetupModule:
    key: str = strawberry.field(
        description="units, programmes, grades, academic_year, classes, subjects, terms."
    )
    ready: bool
    count: int = strawberry.field(
        default=0, description="How many of the thing exist."
    )
    optional: bool = strawberry.field(
        default=False,
        description="Whether the school can be used without it. Terms can.",
    )
    blockers: List[str] = strawberry.field(
        default_factory=list,
        description=(
            "Short codes for what is missing. Words are the client's job, "
            "because the words need translating."
        ),
    )
    active_academic_year_id: Optional[strawberry.ID] = strawberry.field(
        default=None, description="Only the academic_year module carries this."
    )


@strawberry.type(description="Whether the school is ready, taken as a whole.")
class SetupOverall:
    ready: bool
    is_setup_complete: bool = strawberry.field(
        description="What the school last confirmed, which can lag `ready`."
    )
    needs_reconfirm: bool = strawberry.field(
        description="Everything is ready but nobody has said so yet."
    )
    regressed_modules: List[str] = strawberry.field(
        default_factory=list,
        description="Confirmed once, no longer ready — something was removed.",
    )


@strawberry.type(description="How far a school has got with setting itself up.")
class SetupStatus:
    modules: List[SetupModule]
    overall: SetupOverall


def setup_status_to_graphql(payload: Dict[str, Any]) -> SetupStatus:
    overall = payload.get("overall", {})
    return SetupStatus(
        modules=[
            SetupModule(
                key=key,
                ready=bool(module.get("ready")),
                count=int(module.get("count") or 0),
                optional=bool(module.get("optional")),
                blockers=list(module.get("blockers") or []),
                active_academic_year_id=(
                    strawberry.ID(module["active_id"])
                    if module.get("active_id")
                    else None
                ),
            )
            for key, module in payload.items()
            if key != "overall" and isinstance(module, dict)
        ],
        overall=SetupOverall(
            ready=bool(overall.get("ready")),
            is_setup_complete=bool(overall.get("is_setup_complete")),
            needs_reconfirm=bool(overall.get("needs_reconfirm")),
            regressed_modules=list(overall.get("regressed_modules") or []),
        ),
    )
