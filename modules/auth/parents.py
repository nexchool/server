"""Giving a parent their own way in, and working out whose parent they are.

The identity model this rests on already existed and is not changed here:

    Person ──── FamilyMember ──── Family ──── FamilyMember(child) ──── Student
                 (father)                          × many

A parent is **one Person and one membership**, and their children are the other
members of the same household. Three children is three `family_members` rows
belonging to the *children*, not three parents — which is why one parent with
three children needs no new table, no new column, and no second account.

So the whole of this module is two things the repository did not have: a way to
turn that relationship into a login, and a way to ask which students it
covers. Everything else is reused — the account, the identifier, the
credential, the pipeline, the policy.

**A family relationship is not an account.** Recording that a father exists
creates a Person and a membership and nothing else, exactly as it did before;
an account appears only when somebody provisions one deliberately, for a
school that has chosen separate parent logins. Removing one child's
relationship leaves the parent, their account and their other children alone,
because the account hangs off the Person and not off any child.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from core.database import db

logger = logging.getLogger(__name__)


class ParentProvisioningError(Exception):
    """The parent login was asked for something it must not do."""


# ---------------------------------------------------------------------------
# Whose parent is this?
# ---------------------------------------------------------------------------

def is_a_parent(person) -> bool:
    """Whether this person is a responsible adult in some household.

    The child's own membership is excluded: being in a family is what makes a
    student somebody's child, not somebody's parent.
    """
    from modules.people.models import FAMILY_ROLE_CHILD

    memberships = getattr(person, "family_memberships", None) or []
    return any(m.relationship != FAMILY_ROLE_CHILD for m in memberships)


def children_of(person) -> List:
    """Every student this person is a responsible adult for, in this school.

    Across **all** the households they belong to, not just one. A parent whose
    children live in two families — a re-marriage, a guardian who took in a
    second child — is one person with one account, and answering from a single
    household would silently drop half their children. (`_family_containing`
    in the People service resolves such a person's household with `.first()`,
    which is fine for recording an edit and would be wrong here.)

    Tenant-scoped by the join: a membership belongs to a family, a family
    belongs to a school, and a student is read inside the same one. There is
    no path here that could return a child from somewhere else.
    """
    from modules.people.models import FAMILY_ROLE_CHILD, FamilyMember
    from modules.students.models import Student

    if person is None:
        return []

    adult_memberships = [
        m
        for m in (getattr(person, "family_memberships", None) or [])
        if m.relationship != FAMILY_ROLE_CHILD
    ]
    if not adult_memberships:
        return []

    family_ids = {m.family_id for m in adult_memberships}

    child_person_ids = [
        row.person_id
        for row in FamilyMember.query.filter(
            FamilyMember.tenant_id == person.tenant_id,
            FamilyMember.family_id.in_(family_ids),
            FamilyMember.relationship == FAMILY_ROLE_CHILD,
        ).all()
    ]
    if not child_person_ids:
        return []

    return (
        Student.query.filter(
            Student.tenant_id == person.tenant_id,
            Student.person_id.in_(child_person_ids),
        )
        .order_by(Student.admission_number)
        .all()
    )


def children_of_account(account) -> List:
    """The students the signed-in account is a parent of.

    The authorization question, asked of the relationship rather than of
    anything the caller sent. A parent who supplies a student id still has to
    be in this list for it to mean anything — see `may_access_student`.
    """
    if account is None:
        return []
    return children_of(getattr(account, "person", None))


def may_access_student(account, student_id: str) -> bool:
    """Whether this account is a parent of that student.

    Deliberately a membership test against the resolved set rather than a
    query built from the id: a parent asking about a child who is not theirs
    gets the same answer as one asking about a child who does not exist, and
    neither reveals anything about the other school's roll.
    """
    if not student_id:
        return False
    return any(student.id == student_id for student in children_of_account(account))


# ---------------------------------------------------------------------------
# Giving them a login
# ---------------------------------------------------------------------------

@dataclass
class ProvisionedParent:
    """What happened, and the one moment a password exists outside the school."""

    account: object
    created_account: bool
    password: Optional[str] = None
    reused_existing_account: bool = False


def provision_parent_login(
    person,
    *,
    email: str,
    actor_user_id: Optional[str] = None,
) -> ProvisionedParent:
    """Give this parent their own way to sign in.

    Explicit, never automatic. Importing a spreadsheet full of fathers creates
    fathers, not logins; a school that has chosen separate parent logins still
    asks for each one deliberately, and that is what makes the operation
    auditable.

    The rules it will not bend:

    **One account per person per school.** If this person already has one —
    because they are also a teacher, or a former student, or the parent of a
    child admitted last year — that account is reused and given the parent's
    email identifier. A second account is never created, and the database
    would refuse one anyway (`uq_users_tenant_person_live`).

    **A real email, or nothing.** Phase 6 authenticates parents with email and
    password, so an account needs an address. One is never invented, never
    derived from a name, and never borrowed from the child — a parent with no
    usable address simply does not get a login, and remains a perfectly valid
    Person with a perfectly valid relationship. That is not a gap to be
    plastered over; it is what ADR-003 means by authentication being optional.

    **The school must have chosen this.** Under shared access there is no
    parent experience to sign in to, so provisioning is refused rather than
    quietly preparing one.
    """
    from modules.people.models import Person

    from .identifiers import IDENTIFIER_TYPE_EMAIL, normalize_email
    from .models import User
    from .policy import family_access_mode
    from .policy_models import FAMILY_ACCESS_SEPARATE
    from .provisioning import generate_initial_password, issue_password_credential

    if person is None:
        raise ParentProvisioningError("There is no such person at this school.")

    if not is_a_parent(person):
        raise ParentProvisioningError(
            "This person is not recorded as a parent or guardian of any student."
        )

    if family_access_mode(person.tenant_id) != FAMILY_ACCESS_SEPARATE:
        raise ParentProvisioningError(
            "This school shares one login with the student. Turn on separate "
            "parent logins before provisioning one."
        )

    address = normalize_email(email or "")
    if not address:
        # Not a validation nicety. A synthesized address is a fake identity
        # that would then receive password resets, notifications and audit
        # attribution for a real person.
        raise ParentProvisioningError(
            "A parent login needs a real email address. One cannot be made up."
        )

    existing = _account_for(person)
    if existing is not None:
        return _attach_email_to(existing, address, actor_user_id=actor_user_id)

    _refuse_if_taken(person.tenant_id, address, account_id=None)

    password = generate_initial_password()
    account = User(
        tenant_id=person.tenant_id,
        person_id=person.id,
        email=address,
        name=person.full_name,
        # Verified, the same way every other account a school issues is —
        # students at admission, teachers at appointment, tenant admins at
        # creation all set this. The school is asserting that the address
        # belongs to the parent, which is the same assertion it makes for
        # everybody else, and an account that could not sign in would make the
        # operation pointless rather than safer.
        email_verified=True,
    )
    account.set_password(password)
    db.session.add(account)
    db.session.flush()

    issue_password_credential(account, password, issued_by_user_id=actor_user_id)
    db.session.flush()

    _record(account, "credential_issued", actor_user_id)
    return ProvisionedParent(
        account=account, created_account=True, password=password
    )


def _account_for(person):
    """This person's live account at their school, if they have one."""
    from .models import User

    return (
        User.query.filter_by(tenant_id=person.tenant_id, person_id=person.id)
        .filter(User.deleted_at.is_(None))
        .first()
    )


def _attach_email_to(account, address: str, *, actor_user_id):
    """Reuse an account somebody already has.

    The interesting case, and the one a naive implementation gets wrong: a
    teacher who becomes a parent must not acquire a second account. They keep
    the one they have, with the subject kinds they now hold, and sign in with
    the credential they already know.

    No password is issued here — they have one. Returning a new one would
    reset a working login for somebody who did not ask.
    """
    if account.email and account.email.lower() != address:
        # Their account is under a different address. Changing it would rename
        # somebody's identity as a side effect of a parent operation, so it is
        # refused and left to whoever manages that account.
        raise ParentProvisioningError(
            "This person already signs in with a different email address. "
            "Change it on their account first if it should be this one."
        )

    _refuse_if_taken(account.tenant_id, address, account_id=account.id)

    if not account.email:
        account.email = address
        db.session.flush()

    return ProvisionedParent(
        account=account, created_account=False, reused_existing_account=True
    )


def _refuse_if_taken(tenant_id: str, address: str, *, account_id: Optional[str]):
    """Refuse an address that already belongs to somebody else here.

    Silently taking it would give one human another's notifications and
    password resets, which is the worst failure this operation has available
    to it.
    """
    from .models import AccountIdentifier

    from .identifiers import IDENTIFIER_TYPE_EMAIL

    clash = (
        AccountIdentifier.query.filter_by(
            tenant_id=tenant_id,
            identifier_type=IDENTIFIER_TYPE_EMAIL,
            identifier_value_normalized=address,
        )
        .filter(AccountIdentifier.deleted_at.is_(None))
        .first()
    )
    if clash is not None and clash.account_id != account_id:
        raise ParentProvisioningError(
            "Somebody else at this school already signs in with that address."
        )


def _record(account, event_type: str, actor_user_id):
    from .event_models import record_event

    try:
        record_event(
            event_type=event_type,
            tenant_id=account.tenant_id,
            account_id=account.id,
            actor_user_id=actor_user_id,
            method_key="email_password",
        )
    except Exception:  # noqa: BLE001 - an unwritten audit line must not fail this
        logger.exception("could not record a parent provisioning event")
