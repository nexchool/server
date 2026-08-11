"""An account belongs to a person, and so does the studentship behind it.

The platform opens accounts from a dozen places — registration, admissions,
staff onboarding, two bulk importers, seed scripts, test fixtures — and
"remember to record the person too" at every one of them is a rule that will
eventually be forgotten. It is enforced once here, in the same spirit as the
tenant scoping that already guards every query.

It lives in Identity rather than People because it is a fact about *accounts*,
and People must not need to know what an account is (ADR-001, and the
dependency order). People is told what to record; deciding that an account
implies a person is Identity's business, and deriving a name from an email
address is a rule about email addresses.

Only structure is enforced here, never a business decision. Employment is the
counter-example: the organization hiring somebody is an event, so it lives in
``employ()`` where a reader can find it, not in an ORM hook.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import event
from sqlalchemy.orm import Session


def name_for_account(user) -> str:
    """A person must have a name; derive one when the account carries none.

    The part of an email before the @ is what a school will recognise on a
    screen, which beats leaving a human called nothing.
    """
    if getattr(user, "name", None) and user.name.strip():
        return user.name.strip()

    email = getattr(user, "email", None)
    if email and "@" in email:
        return email.split("@", 1)[0]
    return "Unnamed"


def person_for_account(user):
    """The Person this account implies, from what the account itself knows."""
    from modules.people.service import record_person

    return record_person(
        user.tenant_id,
        name_for_account(user),
        email=getattr(user, "email", None),
        photo_url=getattr(user, "profile_picture_url", None),
    )


def _pending_account(session, user_id: Optional[str]):
    """The account with this id, whether already saved or still being saved."""
    from .models import User

    for pending in session.new:
        if isinstance(pending, User) and pending.id == user_id:
            return pending
    return session.get(User, user_id) if user_id else None


def _person_behind(session, instance):
    """The human whose account this relationship was created for."""
    account = _pending_account(session, getattr(instance, "user_id", None))
    return getattr(account, "person", None) if account is not None else None


@event.listens_for(Session, "before_flush")
def _accounts_and_their_relationships_belong_to_people(
    session, flush_context, instances
) -> None:
    """Attach every arriving account, and studentship, to the human it describes.

    Assigning the relationship rather than the id is what orders each insert
    ahead of the row referencing it.

    Autoflush is suspended because resolving these may read the database, and a
    flush inside a flush would recurse.
    """
    from modules.students.models import Student

    from .models import User

    with session.no_autoflush:
        # Accounts first: the studentships below borrow this person.
        for instance in session.new:
            if isinstance(instance, User) and not instance.person_id:
                if not instance.tenant_id:
                    # Nothing to attach a person to; the account is invalid and
                    # will fail its own constraint with a clearer message.
                    continue
                instance.person = person_for_account(instance)

        for instance in session.new:
            if isinstance(instance, Student) and not instance.person_id:
                person = _person_behind(session, instance)
                if person is not None:
                    instance.person = person
                # An account-less studentship (user_id None, ADR-003) has no
                # account to borrow a person from: its creator must say who
                # the student is, and the NOT NULL on person_id holds them
                # to it.
