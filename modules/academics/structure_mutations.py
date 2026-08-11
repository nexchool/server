"""Changing the structure a school is arranged into.

The campuses it teaches at, the programmes it offers, the grades it teaches and
the languages it teaches in. Four small catalogues that everything else refers
to — a class names all four.

**These are the writes that are honestly record editing.** The conventions ask
for mutations named as the school names the act, and warn against
`updateStudentStatus` when the act is `withdrawStudent`. There is no hidden act
here: adding a grade is adding a grade. What the names do say is that removing
one is *removing it from the catalogue* — a soft delete the service refuses
while any class still names it — rather than erasing it, which is why these are
`remove…` and not `delete…`.

Each entry answers to its own authority, the same one its route carried. They
are four catalogues, not one "structure" permission, because a school may let
somebody name a new grade without letting them open a campus.

The reads live in `resolvers.py` next door (`campuses`, `programmes`, `grades`,
`mediums`); this file is their write half. Departments belong with them and are
absent on purpose — that module has no GraphQL read yet, so it is a read *and*
write slice rather than this one.
"""

from __future__ import annotations

from typing import Optional

import strawberry

from graphql_api.errors import ConflictError, NotFoundError, ValidationError
from graphql_api.permissions import IsAuthenticated, RequiresTenant, requires, requires_any

from .graphql.types import (
    Campus,
    Grade,
    Medium,
    Programme,
    campus_to_graphql,
    grade_to_graphql,
    medium_to_graphql,
    programme_to_graphql,
)
from .resolvers import (
    PERM_CAMPUS_MANAGE,
    PERM_CLASS_SUBJECT_MANAGE,
    PERM_GRADE_MANAGE,
    PERM_MEDIUM_MANAGE,
    PERM_PROGRAMME_MANAGE,
)


def _guard(*keys: str):
    return [IsAuthenticated, RequiresTenant, requires(keys[0])] if len(keys) == 1 else [
        IsAuthenticated,
        RequiresTenant,
        requires_any(*keys),
    ]


# A service answers `{"success": False, "error": "..."}` in prose written for a
# person. A client needs to tell "no such thing" from "that name is taken" from
# "something still uses it" without reading English, so the prose is classified
# here.
#
# The fragments are taken from the messages these four services actually
# return — not invented. Each is the shortest stable part of a sentence that
# would survive rewording it for a human:
#
#   "Grade not found" / "School unit not found"                    → NOT_FOUND
#   "A grade with this name already exists"                        → CONFLICT
#   "Grade is referenced by existing classes; …"                   → CONFLICT
#   "Cannot delete this branch because 3 classes are still …"      → CONFLICT
#
# A refusal that matches nothing is still the caller's problem rather than ours,
# so it lands on VALIDATION_ERROR. That default is why the in-use cases are
# covered by tests: a reworded message does not fail loudly here, it quietly
# downgrades to the wrong code, and only a test asking for CONFLICT notices.
_REFUSALS = (
    ("not found", NotFoundError),
    ("already exists", ConflictError),
    ("referenced by existing", ConflictError),
    ("cannot delete", ConflictError),
)


def _refused(result: dict):
    message = result.get("error") or "The change was refused."
    lowered = message.lower()
    for fragment, error in _REFUSALS:
        if fragment in lowered:
            raise error(message)
    raise ValidationError(message)


def _completed(result: dict, key: str, to_graphql):
    """The record the service returned, or the refusal it gave, as an error."""
    if result.get("success"):
        return to_graphql(result[key])
    _refused(result)


def _removed(result: dict) -> bool:
    if result.get("success"):
        return True
    _refused(result)


@strawberry.input(description="A site this school teaches at.")
class CampusInput:
    name: str
    code: str
    status: Optional[str] = strawberry.UNSET
    address: Optional[str] = strawberry.UNSET
    phone: Optional[str] = strawberry.UNSET
    dise_no: Optional[str] = strawberry.UNSET
    index_no: Optional[str] = strawberry.UNSET
    recognition_no: Optional[str] = strawberry.UNSET
    gr_number_scheme: Optional[str] = strawberry.UNSET
    logo_url: Optional[str] = strawberry.UNSET
    principal_signature_url: Optional[str] = strawberry.UNSET


@strawberry.input(description="Fields to change on a campus. Omit what stays.")
class CampusChanges:
    name: Optional[str] = strawberry.UNSET
    code: Optional[str] = strawberry.UNSET
    status: Optional[str] = strawberry.UNSET
    address: Optional[str] = strawberry.UNSET
    phone: Optional[str] = strawberry.UNSET
    dise_no: Optional[str] = strawberry.UNSET
    index_no: Optional[str] = strawberry.UNSET
    recognition_no: Optional[str] = strawberry.UNSET
    gr_number_scheme: Optional[str] = strawberry.UNSET
    logo_url: Optional[str] = strawberry.UNSET
    principal_signature_url: Optional[str] = strawberry.UNSET


@strawberry.input(description="A course of education this school offers.")
class ProgrammeInput:
    name: str
    board: str
    code: str
    medium: Optional[str] = strawberry.UNSET
    medium_id: Optional[strawberry.ID] = strawberry.UNSET
    status: Optional[str] = strawberry.UNSET


@strawberry.input(description="Fields to change on a programme. Omit what stays.")
class ProgrammeChanges:
    name: Optional[str] = strawberry.UNSET
    board: Optional[str] = strawberry.UNSET
    code: Optional[str] = strawberry.UNSET
    medium: Optional[str] = strawberry.UNSET
    medium_id: Optional[strawberry.ID] = strawberry.UNSET
    status: Optional[str] = strawberry.UNSET


@strawberry.input(description="A year-group this school teaches.")
class GradeInput:
    name: str
    sequence: Optional[int] = strawberry.field(
        default=strawberry.UNSET,
        description=(
            "What orders grades, because their names do not — sorted as text, "
            "Std 10 comes before Std 2. Appended to the end when omitted."
        ),
    )


@strawberry.input(description="Fields to change on a grade. Omit what stays.")
class GradeChanges:
    name: Optional[str] = strawberry.UNSET
    sequence: Optional[int] = strawberry.UNSET


@strawberry.input(description="A language this school teaches in.")
class MediumInput:
    name: str
    code: Optional[str] = strawberry.UNSET
    is_active: Optional[bool] = strawberry.UNSET


@strawberry.input(description="Fields to change on a medium. Omit what stays.")
class MediumChanges:
    name: Optional[str] = strawberry.UNSET
    code: Optional[str] = strawberry.UNSET
    is_active: Optional[bool] = strawberry.UNSET


def _changes(payload) -> dict:
    """Only the fields the caller actually sent.

    A partial update has to tell "leave this alone" from "set this to nothing",
    and both of those are `None` if the only signal is the value. The services
    read presence — `if field not in data: continue` — so an explicit null is
    already meaningful to them: it clears the field. The branch form relies on
    exactly that, sending null for a box the user emptied.

    So the distinction has to survive the transport, which is what `UNSET` is
    for: a field the caller never mentioned arrives as `UNSET` and is dropped
    here, while one they sent as null arrives as `None` and is passed through to
    clear the value. Filtering on `is not None` instead would silently turn
    every "clear this field" into a no-op.
    """
    return {
        key: value
        for key, value in strawberry.asdict(payload).items()
        if value is not strawberry.UNSET
    }


@strawberry.type
class StructureMutation:
    # ---------------------------------------------------------------- campuses
    @strawberry.mutation(
        permission_classes=_guard(PERM_CAMPUS_MANAGE),
        description="Open a site this school teaches at. A school unit in the tables.",
    )
    def add_campus(self, info: strawberry.Info, input: CampusInput) -> Campus:
        from modules.school_units import services

        return _completed(
            services.create_school_unit(_changes(input), info.context.tenant_id),
            "school_unit",
            campus_to_graphql,
        )

    @strawberry.mutation(
        permission_classes=_guard(PERM_CAMPUS_MANAGE),
        description="Change a campus's details.",
    )
    def update_campus(
        self, info: strawberry.Info, id: strawberry.ID, changes: CampusChanges
    ) -> Campus:
        from modules.school_units import services

        return _completed(
            services.update_school_unit(
                str(id), _changes(changes), info.context.tenant_id
            ),
            "school_unit",
            campus_to_graphql,
        )

    @strawberry.mutation(
        permission_classes=_guard(PERM_CAMPUS_MANAGE),
        description=(
            "Take a campus out of the catalogue. Refused while any class is "
            "still taught there — the classes are the reason it exists."
        ),
    )
    def remove_campus(self, info: strawberry.Info, id: strawberry.ID) -> bool:
        from modules.school_units import services

        return _removed(services.delete_school_unit(str(id), info.context.tenant_id))

    # -------------------------------------------------------------- programmes
    @strawberry.mutation(
        permission_classes=_guard(PERM_PROGRAMME_MANAGE),
        description="Offer a course of education — a board, and the medium it is taught in.",
    )
    def add_programme(self, info: strawberry.Info, input: ProgrammeInput) -> Programme:
        from modules.academic_programmes import services

        return _completed(
            services.create_programme(_changes(input), info.context.tenant_id),
            "programme",
            programme_to_graphql,
        )

    @strawberry.mutation(
        permission_classes=_guard(PERM_PROGRAMME_MANAGE),
        description="Change a programme's details.",
    )
    def update_programme(
        self, info: strawberry.Info, id: strawberry.ID, changes: ProgrammeChanges
    ) -> Programme:
        from modules.academic_programmes import services

        return _completed(
            services.update_programme(
                str(id), _changes(changes), info.context.tenant_id
            ),
            "programme",
            programme_to_graphql,
        )

    @strawberry.mutation(
        permission_classes=_guard(PERM_PROGRAMME_MANAGE),
        description=(
            "Stop offering a programme. Refused while any class still runs on it."
        ),
    )
    def remove_programme(self, info: strawberry.Info, id: strawberry.ID) -> bool:
        from modules.academic_programmes import services

        return _removed(services.delete_programme(str(id), info.context.tenant_id))

    # ------------------------------------------------------------------ grades
    @strawberry.mutation(
        permission_classes=_guard(PERM_GRADE_MANAGE),
        description="Teach a new year-group.",
    )
    def add_grade(self, info: strawberry.Info, input: GradeInput) -> Grade:
        from modules.grades import services

        return _completed(
            services.create_grade(_changes(input), info.context.tenant_id),
            "grade",
            grade_to_graphql,
        )

    @strawberry.mutation(
        permission_classes=_guard(PERM_GRADE_MANAGE),
        description="Rename a grade, or change where it sits in teaching order.",
    )
    def update_grade(
        self, info: strawberry.Info, id: strawberry.ID, changes: GradeChanges
    ) -> Grade:
        from modules.grades import services

        return _completed(
            services.update_grade(str(id), _changes(changes), info.context.tenant_id),
            "grade",
            grade_to_graphql,
        )

    @strawberry.mutation(
        permission_classes=_guard(PERM_GRADE_MANAGE),
        description=(
            "Stop teaching a year-group. Refused while any class is in it."
        ),
    )
    def remove_grade(self, info: strawberry.Info, id: strawberry.ID) -> bool:
        from modules.grades import services

        return _removed(services.delete_grade(str(id), info.context.tenant_id))

    # ----------------------------------------------------------------- mediums
    @strawberry.mutation(
        permission_classes=_guard(PERM_MEDIUM_MANAGE, PERM_CLASS_SUBJECT_MANAGE),
        description="Teach in another language.",
    )
    def add_medium(self, info: strawberry.Info, input: MediumInput) -> Medium:
        from modules.mediums import services

        return _completed(
            services.create_medium(
                info.context.tenant_id,
                _changes(input),
                actor_user_id=info.context.current_user.id,
            ),
            "medium",
            medium_to_graphql,
        )

    @strawberry.mutation(
        permission_classes=_guard(PERM_MEDIUM_MANAGE, PERM_CLASS_SUBJECT_MANAGE),
        description="Change a medium's details.",
    )
    def update_medium(
        self, info: strawberry.Info, id: strawberry.ID, changes: MediumChanges
    ) -> Medium:
        from modules.mediums import services

        return _completed(
            services.update_medium(
                str(id),
                info.context.tenant_id,
                _changes(changes),
                actor_user_id=info.context.current_user.id,
            ),
            "medium",
            medium_to_graphql,
        )

    @strawberry.mutation(
        permission_classes=_guard(PERM_MEDIUM_MANAGE, PERM_CLASS_SUBJECT_MANAGE),
        description=(
            "Stop teaching in a language. Refused while a class, a programme "
            "or a subject context still names it."
        ),
    )
    def remove_medium(self, info: strawberry.Info, id: strawberry.ID) -> bool:
        from modules.mediums import services

        return _removed(services.delete_medium(str(id), info.context.tenant_id))
