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

The same hook now also refuses a *second* live account for a person who
already has one here. That rule is the database's — ``uq_users_tenant_person_live``
is what actually holds it, and it holds against races this hook cannot see.
What the hook adds is a name for the failure: a caller that reuses somebody
else's ``person_id`` gets :class:`AccountAlreadyExists` saying so, rather than
an IntegrityError naming an index.

And it keeps ``users.email`` and the account's ``email`` identifier saying the
same thing (invariant A2). The argument is the one this module was written
for: an account's address is set in a dozen places — admissions, staff
onboarding, two bulk importers, the platform's admin creation and reset, seed
scripts — and asking each of them to also maintain an identifier row is a rule
that will be forgotten. Nothing *reads* the identifier yet; keeping it true
from the moment it exists is what lets a later phase switch the read over
without a second backfill.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import event
from sqlalchemy.orm import Session

from core.school_time import utc_now

from .identifiers import IDENTIFIER_TYPE_EMAIL, normalize_email


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


class AccountAlreadyExists(Exception):
    """This person already signs in here.

    Raised before the flush rather than after it, so the caller is told which
    person and which account rather than being handed a constraint name.
    """


def _person_arrived_with_this_flush(session, account) -> bool:
    """True if this account's person is itself being inserted right now.

    A person created moments ago by :func:`person_for_account` cannot already
    hold an account, so the check below can skip the query — which matters on
    the bulk importers, where it would otherwise be one query per row.
    """
    person = getattr(account, "person", None)
    return person is not None and person in session.new


def _live_account_held_by(session, tenant_id: str, person_id: str, excluding_id):
    """The live account this person already holds in this school, if any.

    Read without the tenant scope for the same reason
    ``authenticate_platform_admin`` does: a platform admin acting inside
    another tenant has ``g.tenant_id`` set to the entered one, and the scope
    would then hide the very row this is looking for. The explicit
    ``tenant_id`` filter below is what keeps the question tenant-local.
    """
    from flask import g, has_request_context

    from .models import User

    had_tenant = False
    saved_tenant_id = None
    if has_request_context() and getattr(g, "tenant_id", None) is not None:
        had_tenant = True
        saved_tenant_id = g.tenant_id
        g.tenant_id = None
    try:
        query = session.query(User).filter(
            User.tenant_id == tenant_id,
            User.person_id == person_id,
            User.deleted_at.is_(None),
        )
        if excluding_id is not None:
            query = query.filter(User.id != excluding_id)
        return query.first()
    finally:
        if had_tenant:
            g.tenant_id = saved_tenant_id


def _one_live_account_per_person(session, accounts) -> None:
    """Refuse a second live account for a person who already has one here.

    Two ways it can happen, and both are checked: another account already
    saved, and another account arriving in this same flush.
    """
    arriving = {}

    for account in accounts:
        tenant_id = getattr(account, "tenant_id", None)
        person = getattr(account, "person", None)
        person_id = getattr(account, "person_id", None) or getattr(person, "id", None)
        if not tenant_id or not person_id:
            continue

        held = (tenant_id, person_id)
        if held in arriving:
            raise AccountAlreadyExists(
                f"Two accounts for person {person_id} are being created in "
                f"tenant {tenant_id} at once. A person signs in as one account."
            )
        arriving[held] = account

        if _person_arrived_with_this_flush(session, account):
            continue

        existing = _live_account_held_by(
            session, tenant_id, person_id, getattr(account, "id", None)
        )
        if existing is not None:
            raise AccountAlreadyExists(
                f"Person {person_id} already has an account in tenant "
                f"{tenant_id} ({existing.id}). A person signs in as one "
                f"account; close the existing one first, or use it."
            )


def _blank(value) -> bool:
    return not value or not str(value).strip()


def _live_email_identifier(account):
    """The account's current email identifier, out of what is already loaded.

    Read from the relationship rather than by query: the rows arrive with the
    account through its backref, and a flush that touched several thousand
    imported accounts should not issue a query for each of them.
    """
    for identifier in getattr(account, "identifiers", None) or []:
        if identifier.identifier_type == IDENTIFIER_TYPE_EMAIL and (
            identifier.deleted_at is None
        ):
            return identifier
    return None


def _email_identifiers_follow_their_accounts(session, arriving, changed) -> None:
    """Keep every account's email identifier saying what the account says (A2).

    Three things can happen to an account's address and all three are handled
    here rather than at the dozen call sites that can cause them: it is given
    one, it changes, or the account is closed.
    """
    from .models import AccountIdentifier

    for account in arriving:
        if _blank(getattr(account, "email", None)) or not account.tenant_id:
            continue
        session.add(
            AccountIdentifier(
                tenant_id=account.tenant_id,
                account=account,
                identifier_type=IDENTIFIER_TYPE_EMAIL,
                identifier_value=account.email,
                identifier_value_normalized=normalize_email(account.email),
                # The account's own answer, whatever it is. This mirrors a
                # fact; it does not decide one.
                is_verified=bool(getattr(account, "email_verified", False)),
                is_primary=True,
                deleted_at=getattr(account, "deleted_at", None),
            )
        )

    for account in changed:
        identifier = _live_email_identifier(account)

        # Closing the account closes its identifier, or the address would be
        # held against whoever replaces them.
        if getattr(account, "deleted_at", None) is not None:
            if identifier is not None:
                identifier.deleted_at = account.deleted_at
            continue

        if _blank(getattr(account, "email", None)):
            continue

        if identifier is None:
            # Either the account predates the identifier backfill or it was
            # just reopened. Either way it needs one now.
            session.add(
                AccountIdentifier(
                    tenant_id=account.tenant_id,
                    account=account,
                    identifier_type=IDENTIFIER_TYPE_EMAIL,
                    identifier_value=account.email,
                    identifier_value_normalized=normalize_email(account.email),
                    is_verified=bool(getattr(account, "email_verified", False)),
                    is_primary=True,
                )
            )
            continue

        if identifier.identifier_value != account.email:
            identifier.identifier_value = account.email
            identifier.identifier_value_normalized = normalize_email(account.email)
        # Verification is a fact about the address, so it follows the address.
        if identifier.is_verified != bool(
            getattr(account, "email_verified", False)
        ):
            identifier.is_verified = bool(account.email_verified)


def _credentials_follow_their_accounts(session, changed) -> None:
    """Keep a password credential saying what the account says.

    Consistency only: no credential is created here. What it prevents is a
    mirror that silently stops mirroring, and since Phase 1b that is not a
    tidiness question but a correctness one — the authentication pipeline
    reads the credential row *first* when one exists, so a password changed on
    the account and not here would leave the person unable to sign in with the
    password they just chose.

    Both halves therefore follow the account: the secret, and whether it must
    be replaced.
    """
    from .models import AccountCredential

    for account in changed:
        credential = next(
            (
                c
                for c in getattr(account, "credentials", None) or []
                if c.credential_type == "password" and c.deleted_at is None
            ),
            None,
        )
        if credential is None:
            continue

        # The secret. `users.password_hash` is still authoritative during the
        # dual-read window, so the credential follows it rather than the other
        # way round.
        current_hash = getattr(account, "password_hash", None)
        if current_hash and credential.secret_hash != current_hash:
            credential.secret_hash = current_hash
            credential.hash_algorithm = (
                current_hash.split("$", 1)[0][:40] if "$" in current_hash else "unknown"
            )
            credential.last_rotated_at = utc_now()

        wanted = bool(getattr(account, "force_password_reset", False))
        if credential.must_change != wanted:
            credential.must_change = wanted


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
        arriving_accounts = [
            instance for instance in session.new if isinstance(instance, User)
        ]
        for instance in arriving_accounts:
            if instance.person_id:
                continue
            if not instance.tenant_id:
                # Nothing to attach a person to; the account is invalid and
                # will fail its own constraint with a clearer message.
                continue
            instance.person = person_for_account(instance)

        # Every arriving account now knows its person, so the question "does
        # this person already sign in here?" can be asked of all of them.
        _one_live_account_per_person(session, arriving_accounts)

        changed_accounts = [
            instance for instance in session.dirty if isinstance(instance, User)
        ]
        _email_identifiers_follow_their_accounts(
            session, arriving_accounts, changed_accounts
        )
        _credentials_follow_their_accounts(session, changed_accounts)

        for instance in session.new:
            if isinstance(instance, Student) and not instance.person_id:
                person = _person_behind(session, instance)
                if person is not None:
                    instance.person = person
                # An account-less studentship (user_id None, ADR-003) has no
                # account to borrow a person from: its creator must say who
                # the student is, and the NOT NULL on person_id holds them
                # to it.
