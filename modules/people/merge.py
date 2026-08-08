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
    # Read through the relationships each module declares onto Person, so this
    # does not have to know which modules exist.
    for holding, what in (
        ("accounts", "an account"),
        ("employments", "an employment record"),
        ("student_relationships", "a student record"),
    ):
        if getattr(kept, holding) and getattr(absorbed, holding):
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

    # Everything the absorbed person held now belongs to the one kept.
    for holding in ("accounts", "employments", "student_relationships"):
        for row in list(getattr(absorbed, holding)):
            row.person_id = kept.id

    _move_family_memberships(kept, absorbed)

    absorbed.deleted_at = datetime.now(timezone.utc)
    # Committed here, not left to the caller. A merge rewrites which human a
    # school's records refer to across every module at once; half of that
    # sitting in a caller's open transaction is not a state worth supporting,
    # and a caller that forgot answered with a survivor and changed nothing.
    db.session.commit()

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


# A phone number shared by more people than a household could hold is not
# identifying: it is the school's own office number, or the placeholder a bulk
# import wrote when the column was blank. Pairing such a group produces
# thousands of suggestions that are all wrong, and costs the square of the
# group to produce them — one placeholder shared by six thousand people is
# eighteen million pairs, which is where this scan used to spend its minute.
#
# Names are not capped. That path already requires an exact date of birth
# match, which is what makes it precise, and a common name in a large trust is
# ordinary rather than suspicious.
CROWD = 12


def suggest_duplicates(tenant_id: str, limit: int = 100) -> List[DuplicateSuggestion]:
    """People who look like the same human, for someone to judge.

    Computed when asked rather than stored, so the list reflects the records as
    they are now and cannot go stale behind a merge.

    Reads columns rather than people: at fifteen thousand students this is a
    scan of every person in the organization, and building an ORM instance —
    with its identity-map bookkeeping and every column it never reads — for
    each one costs far more than the comparison does.

    `limit` is honoured while pairing rather than by slicing the finished
    list, so asking for ten no longer costs the same as asking for every
    duplicate in the school.
    """
    rows = (
        db.session.query(
            Person.id, Person.full_name, Person.phone_number, Person.date_of_birth
        )
        .filter(Person.tenant_id == tenant_id, Person.deleted_at.is_(None))
        .all()
    )

    by_phone: Dict[str, List[tuple]] = {}
    by_name: Dict[str, List[tuple]] = {}

    for row in rows:
        phone = normalize_phone(row.phone_number)
        if phone:
            by_phone.setdefault(phone, []).append(row)
        name = normalize_name(row.full_name)
        if name:
            by_name.setdefault(name, []).append(row)

    suggestions: List[DuplicateSuggestion] = []
    seen = set()

    def offer(first, second, reason: str) -> bool:
        """Record a suggestion. Returns False once enough have been found."""
        if (first.id, second.id) in seen:
            return True
        seen.add((first.id, second.id))
        suggestions.append(
            DuplicateSuggestion(
                person_id=first.id, other_person_id=second.id, reason=reason
            )
        )
        return len(suggestions) < limit

    # A shared phone is the stronger signal, so it is offered first — the
    # limit should spend itself on the likeliest duplicates.
    for sharing in by_phone.values():
        if len(sharing) > CROWD:
            continue
        for first, second in _pairs(sharing):
            same_name = normalize_name(first.full_name) == normalize_name(
                second.full_name
            )
            if not offer(
                first,
                second,
                "same phone and name"
                if same_name
                # Very often a household phone shared by two people, which
                # is exactly why this is a question and not a merge.
                else "same phone, different name",
            ):
                return suggestions

    for sharing in by_name.values():
        for first, second in _pairs(sharing):
            if not first.date_of_birth or first.date_of_birth != second.date_of_birth:
                continue
            if not offer(first, second, "same name and date of birth"):
                return suggestions

    return suggestions


def _pairs(people: List[Person]):
    for index, first in enumerate(people):
        for second in people[index + 1 :]:
            yield first, second
