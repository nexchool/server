"""Merging two Person records that turn out to be one human (ADR-010).

The backfill merges only where the evidence is conclusive. Everything else — a
parent recorded under two spellings, a parent who also teaches — ends up as two
records that a person at the school can recognise and combine here.

A merge refuses rather than guesses whenever combining would destroy something:
two logins, two employments or two admissions belonging to one human are real
problems that a merge would hide instead of solve.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.database import db

from .matching import normalize_name, normalize_phone
from .models import FamilyMember, Person, PersonMerge

# Identity worth carrying over to the surviving record when it has none.
CARRIED_FIELDS = (
    "date_of_birth",
    "gender",
    "phone_number",
    "email",
    "address",
    "occupation",
    "aadhaar_number",
    "photo_url",
)


class MergeRefused(Exception):
    """The two records cannot be combined without losing something."""


@dataclass(frozen=True)
class DuplicateSuggestion:
    """Two people who look like one, for someone to confirm or dismiss."""

    person_id: str
    other_person_id: str
    reason: str

    def as_dict(self) -> Dict[str, str]:
        return {
            "person_id": self.person_id,
            "other_person_id": self.other_person_id,
            "reason": self.reason,
        }


def _snapshot(person: Person) -> Dict[str, Any]:
    """Everything the absorbed person held, so the merge can be undone."""
    return {
        "id": person.id,
        "full_name": person.full_name,
        "date_of_birth": person.date_of_birth.isoformat() if person.date_of_birth else None,
        "gender": person.gender,
        "phone_number": person.phone_number,
        "email": person.email,
        "address": person.address,
        "occupation": person.occupation,
        "aadhaar_number": person.aadhaar_number,
        "photo_url": person.photo_url,
    }


def _refuse_if_both_hold(kept: Person, absorbed: Person) -> None:
    """Stop when both records carry something only one human may have."""
    from modules.auth.models import User
    from modules.people.employment import Staff
    from modules.students.models import Student

    for model, column, what in (
        (User, User.person_id, "an account"),
        (Staff, Staff.person_id, "an employment record"),
        (Student, Student.person_id, "a student record"),
    ):
        if (
            model.query.filter(column == kept.id).first() is not None
            and model.query.filter(column == absorbed.id).first() is not None
        ):
            raise MergeRefused(
                f"Both people have {what}. Merging would hide one of them; "
                "decide which should remain before combining these records."
            )


def merge_people(
    kept_person_id: str,
    absorbed_person_id: str,
    *,
    reason: Optional[str] = None,
    merged_by_user_id: Optional[str] = None,
) -> PersonMerge:
    """Combine two records that describe one human.

    Everything pointing at the absorbed person is repointed at the one that
    remains, blanks on the survivor are filled from the absorbed record, and
    what was combined is written down before the absorbed record is retired.
    """
    from modules.auth.models import User
    from modules.people.employment import Staff
    from modules.students.models import Student

    if kept_person_id == absorbed_person_id:
        raise MergeRefused("A person cannot be merged into themselves.")

    kept = Person.query.get(kept_person_id)
    absorbed = Person.query.get(absorbed_person_id)

    if kept is None or absorbed is None:
        raise MergeRefused("Both people must exist.")
    if kept.tenant_id != absorbed.tenant_id:
        raise MergeRefused("People from different organizations are not the same human.")
    if absorbed.deleted_at is not None:
        raise MergeRefused("That person has already been merged.")

    _refuse_if_both_hold(kept, absorbed)

    record = PersonMerge(
        tenant_id=kept.tenant_id,
        kept_person_id=kept.id,
        absorbed_person_id=absorbed.id,
        absorbed_person_details=_snapshot(absorbed),
        reason=reason,
        merged_by_user_id=merged_by_user_id,
    )
    db.session.add(record)

    for field in CARRIED_FIELDS:
        if getattr(kept, field, None) is None:
            value = getattr(absorbed, field, None)
            if value is not None:
                setattr(kept, field, value)

    for model, column in (
        (User, User.person_id),
        (Staff, Staff.person_id),
        (Student, Student.person_id),
    ):
        for row in model.query.filter(column == absorbed.id).all():
            row.person_id = kept.id

    _move_family_memberships(kept, absorbed)

    absorbed.deleted_at = datetime.now(timezone.utc)
    db.session.flush()

    return record


def _move_family_memberships(kept: Person, absorbed: Person) -> None:
    """Repoint family participation, without joining a family twice."""
    families_already_in = {
        membership.family_id
        for membership in FamilyMember.query.filter(
            FamilyMember.person_id == kept.id
        ).all()
    }

    for membership in FamilyMember.query.filter(
        FamilyMember.person_id == absorbed.id
    ).all():
        if membership.family_id in families_already_in:
            # The survivor is already in this family; a second membership would
            # be the same fact recorded twice.
            db.session.delete(membership)
        else:
            membership.person_id = kept.id
            families_already_in.add(membership.family_id)


def suggest_duplicates(tenant_id: str, limit: int = 100) -> List[DuplicateSuggestion]:
    """People who look like the same human, for someone to judge.

    Computed when asked rather than stored, so the list reflects the records as
    they are now and cannot go stale behind a merge.
    """
    people = Person.query.filter(
        Person.tenant_id == tenant_id, Person.deleted_at.is_(None)
    ).all()

    suggestions: List[DuplicateSuggestion] = []
    by_phone: Dict[str, List[Person]] = {}
    by_name: Dict[str, List[Person]] = {}

    for person in people:
        phone = normalize_phone(person.phone_number)
        if phone:
            by_phone.setdefault(phone, []).append(person)
        name = normalize_name(person.full_name)
        if name:
            by_name.setdefault(name, []).append(person)

    for phone, sharing in by_phone.items():
        for first, second in _pairs(sharing):
            same_name = normalize_name(first.full_name) == normalize_name(
                second.full_name
            )
            suggestions.append(
                DuplicateSuggestion(
                    person_id=first.id,
                    other_person_id=second.id,
                    reason=(
                        "same phone and name"
                        if same_name
                        # Very often a household phone shared by two people, which
                        # is exactly why this is a question and not a merge.
                        else "same phone, different name"
                    ),
                )
            )

    seen = {(s.person_id, s.other_person_id) for s in suggestions}
    for name, sharing in by_name.items():
        for first, second in _pairs(sharing):
            if (first.id, second.id) in seen:
                continue
            if first.date_of_birth and first.date_of_birth == second.date_of_birth:
                suggestions.append(
                    DuplicateSuggestion(
                        person_id=first.id,
                        other_person_id=second.id,
                        reason="same name and date of birth",
                    )
                )

    return suggestions[:limit]


def _pairs(people: List[Person]):
    for index, first in enumerate(people):
        for second in people[index + 1 :]:
            yield first, second
