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

    # Existing employment is not overwritten by a later form; only gaps filled.
    for field, value in employment.items():
        if value is not None and getattr(staff, field, None) is None:
            setattr(staff, field, value)
    return staff


def ensure_employment_period(staff, joined_on=None):
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
        tenant_id=staff.tenant_id, staff_id=staff.id, joined_on=joined_on
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


@event.listens_for(Session, "before_flush")
def _give_every_new_account_a_person(session, flush_context, instances) -> None:
    """Create the Person behind any account that arrives without one.

    Runs before the flush so the Person is inserted in the same transaction, and
    ahead of the account that references it.
    """
    # Imported here: this module is loaded while models are still being defined.
    from modules.auth.models import User

    for instance in session.new:
        if not isinstance(instance, User) or instance.person_id:
            continue
        if not instance.tenant_id:
            # Nothing to attach a person to; the account itself is invalid and
            # will fail its own constraint.
            continue

        # Assigning the relationship rather than the id makes the person part of
        # this flush and orders their insert ahead of the account.
        instance.person = build_person_for_account(instance)
