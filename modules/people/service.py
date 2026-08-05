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


def _adult_already_recorded(tenant_id: str, role: str, name, phone, email):
    """An adult in this role whom the evidence says is the same human.

    Uses the recognition rules of ADR-010, so a father enrolled with a second
    child is found rather than recorded twice. The database narrows the
    candidates; the match key decides.
    """
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

    adult = _adult_already_recorded(tenant_id, role, name, phone, email)
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
    return _ensure_membership(tenant_id, family_id, adult.id, role)


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
        )

    if _is_same_name(held_by.person.full_name, name):
        revise_identity(
            held_by.person,
            {"phone_number": phone, "email": email, "occupation": occupation},
        )
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


def name_for_account(user) -> str:
    """A person must have a name; derive one when the account carries none."""
    if getattr(user, "name", None) and user.name.strip():
        return user.name.strip()
    email = getattr(user, "email", None)
    if email and "@" in email:
        return email.split("@", 1)[0]
    return "Unnamed"


def build_person_for_account(user) -> Person:
    """The Person an account implies, from what the account itself knows.

    Only identity the account carries is copied. Anything the school knows
    elsewhere — a student's date of birth, a teacher's address — is filled in by
    whoever owns that information.
    """
    return Person(
        id=str(uuid.uuid4()),
        tenant_id=user.tenant_id,
        full_name=name_for_account(user),
        email=getattr(user, "email", None),
        photo_url=getattr(user, "profile_picture_url", None),
    )


def _pending_account(session, user_id: str):
    """The account with this id, whether already saved or still being saved."""
    from modules.auth.models import User

    for pending in session.new:
        if isinstance(pending, User) and pending.id == user_id:
            return pending
    return session.get(User, user_id) if user_id else None


def _person_behind(session, instance):
    """The human whose account this relationship was created for."""
    account = _pending_account(session, getattr(instance, "user_id", None))
    return getattr(account, "person", None) if account is not None else None


@event.listens_for(Session, "before_flush")
def _relationships_belong_to_people(session, flush_context, instances) -> None:
    """Keep every arriving record attached to the human it describes.

    This enforces a structural rule and deliberately nothing more: an account
    belongs to a person, and a student relationship belongs to the same person
    as the account it was created for. Both are derivations with no business
    decision in them, and assigning the relationship rather than the id is what
    orders each insert ahead of the row referencing it.

    Employment is deliberately *not* handled here. Employing someone is a
    business event, so it lives in ``employ()`` where a reader can find it — an
    ORM hook is the wrong place to learn that the organization hired somebody.

    Autoflush is suspended because resolving these may read the database, and a
    flush inside a flush would recurse.
    """
    # Imported here: this module loads while the models are still being defined.
    from modules.auth.models import User
    from modules.students.models import Student

    with session.no_autoflush:
        # Accounts first: the student relationships below borrow this person.
        for instance in session.new:
            if isinstance(instance, User) and not instance.person_id:
                if not instance.tenant_id:
                    # Nothing to attach a person to; the account is invalid and
                    # will fail its own constraint.
                    continue
                instance.person = build_person_for_account(instance)

        for instance in session.new:
            if isinstance(instance, Student) and not instance.person_id:
                instance.person = _person_behind(session, instance)

