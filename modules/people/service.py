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

from .models import Person


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
