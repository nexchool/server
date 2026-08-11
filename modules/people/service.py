"""People domain services.

Holds one structural guarantee: an account always belongs to a person.

The platform creates accounts from a dozen places — registration, admissions,
staff onboarding, bulk imports, seed scripts — and "remember to create a Person
too" at every one of them is a rule that will eventually be forgotten. It is
enforced here instead, in the same spirit as the tenant scoping that already
guards every query.
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import event
from sqlalchemy.orm import Session

from .models import (
    FAMILY_ROLE_AUNT,
    FAMILY_ROLE_BROTHER,
    FAMILY_ROLE_FATHER,
    FAMILY_ROLE_GRANDFATHER,
    FAMILY_ROLE_GRANDMOTHER,
    FAMILY_ROLE_GUARDIAN,
    FAMILY_ROLE_MOTHER,
    FAMILY_ROLE_SISTER,
    FAMILY_ROLE_UNCLE,
    Person,
)

# Schools type the relationship in free text. Recognising the common ones keeps
# a father recorded as a guardian from being treated as a different kind of
# person than a father recorded as a father.
_WRITTEN_RELATIONSHIPS = {
    "father": FAMILY_ROLE_FATHER,
    "dad": FAMILY_ROLE_FATHER,
    "papa": FAMILY_ROLE_FATHER,
    "mother": FAMILY_ROLE_MOTHER,
    "mom": FAMILY_ROLE_MOTHER,
    "mum": FAMILY_ROLE_MOTHER,
    "mummy": FAMILY_ROLE_MOTHER,
    "grandfather": FAMILY_ROLE_GRANDFATHER,
    "grandmother": FAMILY_ROLE_GRANDMOTHER,
    "uncle": FAMILY_ROLE_UNCLE,
    "aunt": FAMILY_ROLE_AUNT,
    "brother": FAMILY_ROLE_BROTHER,
    "sister": FAMILY_ROLE_SISTER,
}


def family_role_for(written_relationship: Optional[str]) -> str:
    """Map what the school wrote to a family relationship.

    Anything unrecognised is a guardian: the school has told us this person is
    responsible for the student, which is the part that matters.
    """
    return _WRITTEN_RELATIONSHIPS.get(
        (written_relationship or "").strip().lower(), FAMILY_ROLE_GUARDIAN
    )


def fill_blank_identity(person: Person, values: dict) -> bool:
    """Fill only what the Person does not already know. Never overwrites."""
    changed = False
    for field, value in values.items():
        if value is not None and getattr(person, field, None) is None:
            setattr(person, field, value)
            changed = True
    return changed


def _fill_employment_gaps(staff, employment: dict):
    """Existing employment is not overwritten by a later form; only gaps filled."""
    for field, value in employment.items():
        if value is not None and getattr(staff, field, None) is None:
            setattr(staff, field, value)
    return staff


def ensure_staff(tenant_id: str, person_id: str, **employment):
    """The Staff relationship for a person, created if they have none.

    Employment is created once per person (ADR-001); someone who already works
    here and starts teaching keeps the employment they had.
    """
    from .employment import Staff

    staff = Staff.query.filter_by(tenant_id=tenant_id, person_id=person_id).first()
    if staff is None:
        staff = Staff(tenant_id=tenant_id, person_id=person_id, **employment)
        db_session_add(staff)
        return staff

    return _fill_employment_gaps(staff, employment)


def _adult_already_recorded(
    tenant_id: str, role: str, name, phone, email, child_person_id=None
):
    """An adult in this role whom the evidence says is the same human.

    Uses the recognition rules of ADR-010, so a father enrolled with a second
    child is found rather than recorded twice. The database narrows the
    candidates; the match key decides.

    A household is checked first, and on the name alone. Naming the father of a
    child who already has a father of that name is correcting his details or
    repeating them — not introducing a second father — so a changed phone
    number must not split him in two. Only within the one household: two
    families may each have a Rajesh Patel, and they are different men.
    """
    if child_person_id is not None:
        already_there = _same_name_in_household(tenant_id, child_person_id, role, name)
        if already_there is not None:
            return already_there

    from core.database import db

    from .matching import build_match_key, normalize_phone
    from .models import FamilyMember, Person

    key = build_match_key(role, name, phone, email)
    if key is None:
        return None

    candidates = (
        db.session.query(Person)
        .join(FamilyMember, FamilyMember.person_id == Person.id)
        .filter(
            FamilyMember.tenant_id == tenant_id,
            FamilyMember.relationship == role,
            Person.deleted_at.is_(None),
        )
    )

    digits = normalize_phone(phone)
    if digits:
        # Phone numbers are written inconsistently, so narrow on the part that
        # never changes and let the match key be the judge.
        candidates = candidates.filter(Person.phone_number.ilike(f"%{digits[-8:]}%"))
    elif email:
        candidates = candidates.filter(Person.email.ilike(email.strip()))

    for person in candidates.all():
        if build_match_key(role, person.full_name, person.phone_number, person.email) == key:
            return person
    return None


def _same_name_in_household(tenant_id: str, child_person_id: str, role: str, name):
    """The adult of this name already holding this role in the child's family."""
    from .models import FamilyMember, Person

    family_id = _family_containing(tenant_id, child_person_id)
    if family_id is None or not name:
        return None

    for membership in FamilyMember.query.filter_by(
        tenant_id=tenant_id, family_id=family_id, relationship=role
    ).all():
        person = membership.person
        if person is not None and _is_same_name(person.full_name, name):
            return person
    return None


def _family_containing(tenant_id: str, person_id: str):
    from .models import FamilyMember

    membership = FamilyMember.query.filter_by(
        tenant_id=tenant_id, person_id=person_id
    ).first()
    return membership.family_id if membership is not None else None


def _ensure_membership(tenant_id: str, family_id: str, person_id: str, relationship: str):
    from .models import FamilyMember

    existing = FamilyMember.query.filter_by(
        tenant_id=tenant_id, family_id=family_id, person_id=person_id
    ).first()
    if existing is not None:
        return existing

    membership = FamilyMember(
        tenant_id=tenant_id,
        family_id=family_id,
        person_id=person_id,
        relationship=relationship,
    )
    db_session_add(membership)
    return membership


def record_family_member(
    tenant_id: str,
    child_person_id: str,
    *,
    name: Optional[str],
    relationship: Optional[str],
    phone: Optional[str] = None,
    email: Optional[str] = None,
    occupation: Optional[str] = None,
    is_primary_contact: bool = False,
):
    """Record an adult responsible for a student as a Person in their family.

    Admission is where a school tells us who is responsible for a child, so it
    is where the family is recorded — not only when a migration runs later.

    A sibling enrolled afterwards finds the same adult and joins the family
    already holding them, which is how two children come to share one father
    rather than one each.
    """
    from .models import FAMILY_ROLE_CHILD, Family, Person

    if not name or not name.strip():
        return None

    role = family_role_for(relationship)

    adult = _adult_already_recorded(
        tenant_id, role, name, phone, email, child_person_id=child_person_id
    )
    if adult is None:
        adult = Person(
            tenant_id=tenant_id,
            full_name=name.strip(),
            phone_number=phone,
            email=email,
            occupation=occupation,
        )
        db_session_add(adult)

    family_id = _family_containing(tenant_id, child_person_id) or _family_containing(
        tenant_id, adult.id
    )
    if family_id is None:
        family = Family(tenant_id=tenant_id)
        db_session_add(family)
        family_id = family.id

    _ensure_membership(tenant_id, family_id, child_person_id, FAMILY_ROLE_CHILD)
    membership = _ensure_membership(tenant_id, family_id, adult.id, role)

    if is_primary_contact:
        name_the_contact(membership)
    return membership


def name_the_contact(membership) -> None:
    """Make this household member the adult the school calls.

    A household has one, so naming a new contact stands the previous one down
    rather than leaving two — which the database would refuse anyway.
    """
    from core.database import db

    from .models import FamilyMember

    if membership is None or membership.is_primary_contact:
        return

    FamilyMember.query.filter(
        FamilyMember.family_id == membership.family_id,
        FamilyMember.is_primary_contact.is_(True),
    ).update({"is_primary_contact": False}, synchronize_session=False)
    db.session.flush()

    membership.is_primary_contact = True
    db.session.flush()


def revise_identity(person: Person, values: dict) -> bool:
    """Record a correction to what is known about this person.

    ``fill_blank_identity`` is for learning a fact nobody had recorded. This is
    the school saying the fact on record is wrong, so it overwrites — but only
    the fields it was given, since an edit form that omits a field is silent
    about it rather than clearing it.
    """
    if person is None:
        return False

    changed = False
    for field, value in values.items():
        if value is None:
            continue
        if getattr(person, field, None) != value:
            setattr(person, field, value)
            changed = True
    return changed


def revise_family_member(
    tenant_id: str,
    child_person_id: str,
    *,
    relationship: Optional[str],
    name: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    occupation: Optional[str] = None,
    is_primary_contact: bool = False,
):
    """The school has corrected who is responsible for a child, or how to reach them.

    Two different statements arrive through the same form, and they must not be
    treated alike:

    Correcting a *detail* — a new phone number, a spelling fixed — corrects it
    for every child of that adult. One human, one record, which is the whole
    point of holding people once; a father whose number changes should not have
    to be corrected on each of his children.

    Changing the *name* is a different statement: this child's father is a
    different man. Renaming the adult on record would rewrite him on his other
    children too, so the household's membership moves to the new person and the
    old one keeps their own record and their other families.
    """
    if not name or not name.strip():
        return None

    role = family_role_for(relationship)
    held_by = _member_in_role(tenant_id, child_person_id, role)

    if held_by is None:
        return record_family_member(
            tenant_id,
            child_person_id,
            name=name,
            relationship=relationship,
            phone=phone,
            email=email,
            occupation=occupation,
            is_primary_contact=is_primary_contact,
        )

    if _is_same_name(held_by.person.full_name, name):
        revise_identity(
            held_by.person,
            {"phone_number": phone, "email": email, "occupation": occupation},
        )
        if is_primary_contact:
            name_the_contact(held_by)
        return held_by

    from core.database import db

    db.session.delete(held_by)
    db.session.flush()
    return record_family_member(
        tenant_id,
        child_person_id,
        name=name,
        relationship=relationship,
        phone=phone,
        email=email,
        occupation=occupation,
        is_primary_contact=is_primary_contact,
    )


def _member_in_role(tenant_id: str, child_person_id: str, role: str):
    """The household member holding this role for this child, if any."""
    from .models import FamilyMember

    family_id = _family_containing(tenant_id, child_person_id)
    if family_id is None:
        return None

    return FamilyMember.query.filter_by(
        tenant_id=tenant_id, family_id=family_id, relationship=role
    ).first()


def _is_same_name(recorded: Optional[str], written: Optional[str]) -> bool:
    return (recorded or "").strip().casefold() == (written or "").strip().casefold()


def employment_status_for_legacy_flag(legacy_status: Optional[str]) -> str:
    """Translate the v1 active/inactive flag into a business state.

    v1 recorded only whether someone was active, so a departure cannot be
    reported as a resignation, retirement or dismissal without inventing a fact.
    'Left' says exactly what is known: they have gone, and the reason was never
    recorded.
    """
    from .employment import EMPLOYMENT_STATUS_LEFT, EMPLOYMENT_STATUS_WORKING

    if (legacy_status or "").strip().lower() == "active":
        return EMPLOYMENT_STATUS_WORKING
    return EMPLOYMENT_STATUS_LEFT


def record_employment_standing(staff, legacy_status: Optional[str]) -> None:
    """Apply a v1 active/inactive flag to an employment without flattening it.

    v1 records only whether someone is active, so a suspension and a
    resignation arrive as the same word. Translate only when the flag changes
    whether the person works here at all: someone suspended or on leave is
    already "inactive" in that vocabulary, and rewriting them to plain working
    would quietly reinstate them.

    Every path that marks a teacher active or inactive goes through here, so
    the employment and the record the school edited cannot drift apart.
    """
    from .employment import EMPLOYMENT_STATUS_LEFT

    if staff is None or legacy_status is None:
        return

    translated = employment_status_for_legacy_flag(legacy_status)
    if staff.is_employed != (translated != EMPLOYMENT_STATUS_LEFT):
        staff.employment_status = translated


def employ(
    tenant_id: str,
    person_id: str,
    *,
    employee_number: Optional[str] = None,
    designation: Optional[str] = None,
    department_id: Optional[str] = None,
    joined_on=None,
    employment_status: Optional[str] = None,
):
    """Record that the organization employs this person — the StaffJoined event.

    One business action, deliberately readable as one: employment begins, and it
    covers a period. Someone already employed here keeps the employment they
    have, because starting to teach is not a second job.

    Teaching is layered on top of this by the Academic side (ADR-005); this
    function knows nothing about it.
    """
    employment = {
        "employee_number": employee_number,
        "designation": designation,
        "department_id": department_id,
    }
    if employment_status is not None:
        employment["employment_status"] = employment_status

    staff = ensure_staff(tenant_id, person_id, **employment)
    # The period must agree with the employment it belongs to: recording someone
    # who has already gone should not leave their period reading as ongoing.
    ensure_employment_period(
        staff,
        joined_on,
        end_reason=None if staff.is_employed else staff.employment_status,
    )
    return staff


def ensure_employment_period(staff, joined_on=None, end_reason=None):
    """The employment period a staff member is currently serving.

    Opened once when they join. Someone who leaves and returns gets a second
    period, which is a separate business event rather than a side effect of
    filling in a form.
    """
    from .employment import StaffEmploymentPeriod

    period = StaffEmploymentPeriod.query.filter_by(staff_id=staff.id).first()
    if period is not None:
        return period

    period = StaffEmploymentPeriod(
        tenant_id=staff.tenant_id,
        staff_id=staff.id,
        joined_on=joined_on,
        end_reason=end_reason,
    )
    db_session_add(period)
    return period


def db_session_add(instance) -> None:
    """Add and flush, so the caller immediately has an id to reference."""
    from core.database import db

    db.session.add(instance)
    db.session.flush()


def person_on_record(person_id: str) -> Optional[Person]:
    """The person with this id, if this organization knows them.

    Tenant scoping does the restricting, so a person belonging to another
    school is simply not on record here — which is the honest answer to give
    a caller holding an id they should not have.
    """
    return Person.query.filter_by(id=person_id).first()


def record_person(
    tenant_id: str,
    full_name: str,
    *,
    email: Optional[str] = None,
    photo_url: Optional[str] = None,
) -> Person:
    """Record a human this organization now knows about.

    Takes what it is told rather than an object to read it off, so People does
    not need to know what an account is. Whoever holds the identity — Identity
    for an account, admissions for a student — decides what to pass.

    Only what the caller states is recorded. Anything the school learns
    elsewhere is filled in by whoever owns it (see fill_blank_identity).
    """
    return Person(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        full_name=full_name,
        email=email,
        photo_url=photo_url,
    )


def record_household(tenant_id: str, child_person_id: str, members) -> None:
    """Make this child's household match what the school just submitted.

    The form sends the household whole — every adult it holds, each with a
    relationship — so an adult it no longer lists has been removed from the
    child's household, not merely left unedited. The Person survives that: they
    may still be a parent in another family, and forgetting a human because one
    form stopped mentioning them would be wrong.

    Adults are matched by person_id when the form returns one, and by
    relationship otherwise, so editing a father's phone corrects the father
    already on record instead of adding a second one.
    """
    from core.database import db

    from .models import FAMILY_ROLE_CHILD, FamilyMember
    from .relationships import household_of

    if members is None:
        return

    person = Person.query.get(child_person_id)
    if person is None:
        return

    existing = {member.person_id: member for member in household_of(person)}
    submitted = []
    keep = set()

    for entry in members:
        name = (entry.get("name") or "").strip()
        if not name:
            continue

        held_by = existing.get(entry.get("person_id"))
        if held_by is not None:
            keep.add(held_by.person_id)
            revise_identity(
                held_by.person,
                {
                    "full_name": name,
                    "phone_number": entry.get("phone"),
                    "email": entry.get("email"),
                    "occupation": entry.get("occupation"),
                },
            )
            held_by.relationship = family_role_for(entry.get("relationship"))
            submitted.append((held_by, bool(entry.get("is_primary_contact"))))
            continue

        recorded = revise_family_member(
            tenant_id,
            child_person_id,
            relationship=entry.get("relationship"),
            name=name,
            phone=entry.get("phone"),
            email=entry.get("email"),
            occupation=entry.get("occupation"),
        )
        if recorded is not None:
            keep.add(recorded.person_id)
            submitted.append((recorded, bool(entry.get("is_primary_contact"))))

    for person_id, member in existing.items():
        if person_id not in keep and member.relationship != FAMILY_ROLE_CHILD:
            db.session.delete(member)
    db.session.flush()

    # Naming the contact last, once the household is settled, so standing the
    # previous one down never collides with a member about to be removed.
    for member, is_contact in submitted:
        if is_contact:
            name_the_contact(member)
            break


def people_summaries(person_ids):
    """Several people, and what each of them holds, in a fixed number of queries.

    "What they hold" is an account, an employment, a studentship — the three
    things only one human may have, and therefore the three things that decide
    whether two records can be combined at all.

    Read through the backrefs those modules declare onto Person, not by
    importing them: People is a foundation domain and must not know that
    Identity or Academic exist (a Person is a person whether or not they ever
    log in). `selectinload` batches each one into a single query, so this is
    four queries whatever the batch size — asked per person it is the N+1 that
    makes a reconciliation screen unusable on the tenant that most needs one.
    """
    from sqlalchemy.orm import selectinload

    from .models import Person

    wanted = [pid for pid in set(person_ids or ()) if pid]
    if not wanted:
        return {}, {}

    rows = (
        Person.query.options(
            selectinload(Person.accounts),
            selectinload(Person.employments),
            selectinload(Person.student_relationships),
        )
        .filter(Person.id.in_(wanted))
        .all()
    )

    by_id, holdings = {}, {}
    for row in rows:
        by_id[row.id] = row
        holdings[row.id] = {
            "has_account": bool(row.accounts),
            "is_employed": bool(row.employments),
            "is_student": bool(row.student_relationships),
        }
    return by_id, holdings
